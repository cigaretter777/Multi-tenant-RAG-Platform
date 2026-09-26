"""
可选 Web Search 服务。

为 Deep Research Webpage 提供轻量外部信息补充。搜索失败时返回 warnings，
由调用方降级为纯文本报告，不让 Web Search 成为硬依赖。
"""
from typing import Any, Dict, List, Optional

import requests

from configs.config import settings
from utils.logger import get_logger

logger = get_logger()


class WebSearchService:
    """统一 Web Search 入口，支持 bocha_internal/mock/none。"""

    def search(
        self,
        text: str,
        query: Optional[str] = None,
        count: Optional[int] = None,
        answer: Optional[bool] = None,
        requested: bool = False,
    ) -> Dict[str, Any]:
        provider = (settings.web_search_provider or "none").strip().lower()
        derived_query = self._derive_query(text, query)
        warnings: List[str] = []

        if not settings.web_search_enabled:
            warnings.append("web_search_disabled")
            logger.warning(
                "Web Search 被服务端配置禁用 (WEB_SEARCH_ENABLED=false)，请求已跳过 requested=%s",
                requested,
            )
            return self._empty_result(derived_query, provider, warnings)

        if provider in {"", "none"}:
            warnings.append("web_search_provider_none")
            return self._empty_result(derived_query, provider or "none", warnings)

        if len(derived_query) < 2:
            warnings.append("web_search_query_too_short")

        if provider == "mock":
            logger.warning(
                "Web Search 使用 mock provider；生产环境请设置 WEB_SEARCH_PROVIDER=bocha_internal"
            )
            return self._mock_result(derived_query, warnings)

        if provider != "bocha_internal":
            warnings.append(f"web_search_unknown_provider:{provider}")
            return self._empty_result(derived_query, provider, warnings)

        if not settings.web_search_url:
            warnings.append("web_search_url_missing")
            return self._empty_result(derived_query, provider, warnings)

        safe_count = self._safe_count(count)
        use_answer = settings.web_search_default_answer if answer is None else bool(answer)
        payload = {
            "query": derived_query,
            "count": safe_count,
            "answer": use_answer,
        }

        try:
            logger.info(
                "调用 Web Search: provider=%s count=%s answer=%s query_len=%s",
                provider,
                safe_count,
                use_answer,
                len(derived_query),
            )
            response = requests.post(
                settings.web_search_url,
                json=payload,
                timeout=settings.web_search_timeout,
            )
            if response.status_code != 200:
                warnings.append(f"web_search_http_error:{response.status_code}")
                logger.warning("Web Search HTTP 异常: %s", response.status_code)
                return self._empty_result(derived_query, provider, warnings)
            raw = response.json()
        except requests.RequestException as exc:
            warnings.append("web_search_request_failed")
            logger.warning("Web Search 请求失败: %s", exc)
            return self._empty_result(derived_query, provider, warnings)
        except ValueError as exc:
            warnings.append("web_search_invalid_json")
            logger.warning("Web Search 响应非 JSON: %s", exc)
            return self._empty_result(derived_query, provider, warnings)

        return self._parse_bocha_response(raw, derived_query, provider, warnings)

    @staticmethod
    def _derive_query(text: str, override: Optional[str]) -> str:
        if override and override.strip():
            return " ".join(override.split())[:200]
        cleaned = " ".join((text or "").split())
        return cleaned[:300]

    @staticmethod
    def _safe_count(count: Optional[int]) -> int:
        default_count = max(1, int(settings.web_search_default_count or 1))
        max_count = max(1, int(settings.web_search_max_count or default_count))
        requested = default_count if count is None else int(count)
        return max(1, min(requested, max_count))

    @staticmethod
    def _empty_result(query: str, provider: str, warnings: List[str]) -> Dict[str, Any]:
        return {
            "query": query,
            "provider": provider,
            "sources": [],
            "answer": "",
            "warnings": warnings,
        }

    @staticmethod
    def _mock_result(query: str, warnings: List[str]) -> Dict[str, Any]:
        sources = [{
            "id": "s1",
            "title": "Mock Web Search Source",
            "url": "https://example.com/mock-web-search",
            "snippet": f"Mock source for query: {query}",
            "summary": "",
        }]
        return {
            "query": query,
            "provider": "mock",
            "sources": sources,
            "answer": "",
            "warnings": warnings,
        }

    @staticmethod
    def _parse_bocha_response(
        raw: Dict[str, Any],
        query: str,
        provider: str,
        warnings: List[str],
    ) -> Dict[str, Any]:
        if not isinstance(raw, dict):
            warnings.append("web_search_invalid_response")
            return WebSearchService._empty_result(query, provider, warnings)

        code = raw.get("code")
        if code not in (None, 0, 200, "0", "200"):
            warnings.append(f"web_search_api_error:{code}")

        data = raw.get("data", [])
        sources = WebSearchService._parse_sources(data)
        answer = WebSearchService._parse_answer(raw, sources)

        if not sources and answer:
            warnings.append("web_search_no_sources")
        elif not sources and not answer:
            warnings.append("web_search_empty")

        return {
            "query": query,
            "provider": provider,
            "sources": sources,
            "answer": answer,
            "warnings": warnings,
        }

    @staticmethod
    def _parse_sources(data: Any) -> List[Dict[str, str]]:
        if isinstance(data, dict):
            candidates = data.get("list") or data.get("results") or data.get("items") or []
        else:
            candidates = data
        if not isinstance(candidates, list):
            return []

        sources: List[Dict[str, str]] = []
        for item in candidates:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or item.get("link") or "").strip()
            title = str(item.get("name") or item.get("title") or "").strip()
            snippet = str(item.get("snippet") or item.get("description") or "").strip()
            summary = str(item.get("summary") or "").strip()
            if not (url or title or snippet or summary):
                continue
            sources.append({
                "id": f"s{len(sources) + 1}",
                "title": title or url or f"来源 {len(sources) + 1}",
                "url": url,
                "snippet": snippet,
                "summary": summary,
            })
        return sources

    @staticmethod
    def _parse_answer(raw: Dict[str, Any], sources: List[Dict[str, str]]) -> str:
        for key in ("answer", "summary", "content"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        data = raw.get("data")
        if isinstance(data, dict):
            for key in ("answer", "summary", "content"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

        summaries = [source.get("summary", "").strip() for source in sources if source.get("summary")]
        return "\n".join(summaries[:3])
