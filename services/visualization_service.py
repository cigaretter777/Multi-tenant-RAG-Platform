"""
可视化服务层 - 生成思维导图、Mermaid 图表等可视化内容
"""
import json
import os
import re
import subprocess
import tempfile
import time
from typing import Dict, Any, List, Optional

import requests

from configs.config import settings
from services.deep_research_prompts import (
    COMPLEXITY_GUIDANCE,
    QUALITY_RULES_PROMPT,
    RESEARCH_COMPLEXITY_PROMPT,
    SCHEMA_SOURCE_FIELDS_PROMPT,
    WEB_SEARCH_PROMPT,
)
from services.web_search_service import WebSearchService
from utils.logger import get_logger

logger = get_logger()


class VisualizationService:
    """可视化服务类 - 生成思维导图、Mermaid 图表等可视化内容"""

    # Deep Research 报告结构契约版本：字段语义或结构发生破坏性变更时递增。
    DEEP_RESEARCH_SCHEMA_VERSION = "1.0"

    SOURCE_REF_RE = re.compile(r"\[s(\d+)\]")
    SOURCE_MARKER_RE = re.compile(r"\s*\[(?:s\d+|Web Answer)\]\s*", re.IGNORECASE)
    SECTION_DEPTH_RULES = {
        "observation": 100,
        "interpretation": 140,
        "mechanism": 120,
        "implication": 140,
        "uncertainty": 60,
        "outlook": 100,
        "insight": 80,
    }

    def __init__(self, web_search_service: Optional[WebSearchService] = None):
        self.web_search_service = web_search_service or WebSearchService()

    def generate_mindmap(self, text: str) -> Dict[str, Any]:
        """
        根据文本生成思维导图结构

        Args:
            text: 用于生成思维导图的文本内容

        Returns:
            思维导图 JSON 字典 {title, children}
        """
        prompt = settings.mindmap_prompt.replace('{text}', text)

        payload = {
            "model": settings.chat_model_name,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 20480,
            "temperature": 0.3
        }

        headers = {"Content-Type": "application/json"}
        if settings.chat_model_key:
            headers["Authorization"] = f"Bearer {settings.chat_model_key}"

        url = self._build_chat_url(settings.chat_model_url)

        logger.info(f"调用 Chat 模型生成思维导图: {url}")

        response = self._post_chat_completion(url, payload, headers)

        if response.status_code != 200:
            logger.error(f"Chat 模型调用失败: {response.text}")
            raise RuntimeError(f"Chat 模型调用失败: {response.status_code}")

        result = response.json()
        content = ""
        if "choices" in result and len(result["choices"]) > 0:
            content = result["choices"][0].get("message", {}).get("content", "")

        if not content:
            raise ValueError("Chat 模型返回空内容")

        logger.info(f"Chat 模型返回内容: {content[:200]}...")

        # 解析 JSON：处理可能存在的 markdown code block 包裹
        content = self._extract_json(content)

        try:
            mindmap = json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"Chat 模型返回内容解析 JSON 失败: {content}")
            raise ValueError(f"模型返回格式无效: {str(e)}")

        mindmap = self._normalize_standalone_mindmap(mindmap)
        self._add_ids_to_mindmap(mindmap)
        return mindmap

    def generate_mermaid(self, text: str) -> Dict[str, Any]:
        """
        根据文本生成 Mermaid 图表结构

        Args:
            text: 用于生成 Mermaid 图表的文本内容

        Returns:
            包含 mermaid 字段的字典，如 {"mermaid": "graph TD\\nA[...]..."}
        """
        prompt = settings.mermaid_prompt.replace('{text}', text)

        payload = {
            "model": settings.chat_model_name,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 20480,
            "temperature": 0.3
        }

        headers = {"Content-Type": "application/json"}
        if settings.chat_model_key:
            headers["Authorization"] = f"Bearer {settings.chat_model_key}"

        url = self._build_chat_url(settings.chat_model_url)

        logger.info(f"调用 Chat 模型生成 Mermaid 图表: {url}")

        response = self._post_chat_completion(url, payload, headers)

        if response.status_code != 200:
            logger.error(f"Chat 模型调用失败: {response.text}")
            raise RuntimeError(f"Chat 模型调用失败: {response.status_code}")

        result = response.json()
        content = ""
        if "choices" in result and len(result["choices"]) > 0:
            content = result["choices"][0].get("message", {}).get("content", "")

        if not content:
            raise ValueError("Chat 模型返回空内容")

        logger.info(f"Chat 模型返回内容: {content[:200]}...")

        # 解析 JSON：处理可能存在的 markdown code block 包裹
        content = self._extract_json(content)

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"Chat 模型返回内容解析 JSON 失败: {content}")
            raise ValueError(f"模型返回格式无效: {str(e)}")

        return parsed

    def generate_webpage(
        self,
        text: str,
        enable_web_search: bool = False,
        web_search_query: Optional[str] = None,
        web_search_count: Optional[int] = None,
        web_search_answer: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        根据文本生成 Deep Research 网页结构化 JSON

        Args:
            text: 用于生成 Deep Research 报告的文本内容

        Returns:
            报告 JSON dict，包含 title、summary、research_overview、
            key_findings、sections、mindmap、charts、conclusion、
            recommendations、metadata
        """
        web_context = self._build_web_search_context(
            text=text,
            enable_web_search=enable_web_search,
            web_search_query=web_search_query,
            web_search_count=web_search_count,
            web_search_answer=web_search_answer,
        )
        complexity_hint, complexity_reason_hint = self._infer_research_complexity(text, web_context)
        prompt = self._build_webpage_prompt(text, web_context, complexity_hint)

        payload = {
            "model": settings.chat_model_name,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 40960,
            "temperature": 0.3
        }

        headers = {"Content-Type": "application/json"}
        if settings.chat_model_key:
            headers["Authorization"] = f"Bearer {settings.chat_model_key}"

        url = self._build_chat_url(settings.chat_model_url)

        logger.info(
            "调用 Chat 模型生成网页结构化 JSON: %s (research_complexity_hint=%s)",
            url,
            complexity_hint,
        )

        response = self._post_chat_completion(url, payload, headers)

        if response.status_code != 200:
            logger.error(f"Chat 模型调用失败: {response.text}")
            raise RuntimeError(f"Chat 模型调用失败: {response.status_code}")

        result = response.json()
        content = ""
        if "choices" in result and len(result["choices"]) > 0:
            content = result["choices"][0].get("message", {}).get("content", "")

        if not content:
            raise ValueError("Chat 模型返回空内容")

        logger.info(f"Chat 模型返回内容: {content[:200]}...")

        # 解析 JSON：处理可能存在的 markdown code block 包裹；失败时修复或降级
        content = self._extract_json(content)
        parsed, report_flags = self._parse_llm_report_json(content, text)
        if not isinstance(parsed.get("warnings"), list):
            parsed["warnings"] = [str(parsed["warnings"])] if parsed.get("warnings") else []
        if report_flags.get("partial_recovery"):
            parsed["warnings"].append("partial_recovery")
        if report_flags.get("degraded"):
            parsed["warnings"].append("degraded_report")

        normalized = self._normalize_deep_research(
            parsed,
            web_context,
            report_flags=report_flags,
            source_text=text,
            complexity_hint=complexity_hint,
            complexity_reason_hint=complexity_reason_hint,
        )
        if not report_flags.get("degraded") and self._needs_section_deepening(normalized.get("sections", []), text):
            rewritten_sections = self._rewrite_sections_for_depth(text, normalized, web_context)
            if rewritten_sections is not None:
                original_sections = normalized.get("sections", [])
                merged_sections = self._merge_deepened_sections(original_sections, rewritten_sections)
                if not isinstance(parsed.get("warnings"), list):
                    parsed["warnings"] = [str(parsed["warnings"])] if parsed.get("warnings") else []
                parsed["warnings"].append("sections_rewritten_for_depth")
                parsed["sections"] = merged_sections
                normalized = self._normalize_deep_research(
                    parsed,
                    web_context,
                    report_flags=report_flags,
                    source_text=text,
                    complexity_hint=complexity_hint,
                    complexity_reason_hint=complexity_reason_hint,
                )

        meta = normalized.setdefault("metadata", {})
        final_warnings = meta.get("warnings") if isinstance(meta.get("warnings"), list) else list(normalized.get("warnings") or [])
        VisualizationService._filter_sources_to_cited(normalized, final_warnings, web_context)
        meta["warnings"] = final_warnings
        cited_count = len(normalized.get("sources") or [])
        meta["source_count"] = cited_count
        meta["cited_source_count"] = cited_count
        if web_context.get("enabled"):
            ctx_sources = web_context.get("sources") or []
            if isinstance(ctx_sources, list) and ctx_sources:
                meta["web_search_retrieved_count"] = len(ctx_sources)
        meta["warning_count"] = len(final_warnings)
        normalized["warnings"] = final_warnings

        return normalized

    def _build_web_search_context(
        self,
        text: str,
        enable_web_search: bool = False,
        web_search_query: Optional[str] = None,
        web_search_count: Optional[int] = None,
        web_search_answer: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """根据开关生成 LLM 可读 Web Search 上下文。"""
        context = {
            "requested": bool(enable_web_search),
            "enabled": False,
            "query": (web_search_query or "").strip(),
            "provider": settings.web_search_provider,
            "sources": [],
            "answer": "",
            "warnings": [],
            "prompt_context": "未启用 Web Search。请只基于输入文本生成报告。",
        }
        if not enable_web_search:
            return context

        search_result = self.web_search_service.search(
            text=text,
            query=web_search_query,
            count=web_search_count,
            answer=web_search_answer,
            requested=True,
        )
        sources = search_result.get("sources") if isinstance(search_result.get("sources"), list) else []
        answer = search_result.get("answer") if isinstance(search_result.get("answer"), str) else ""
        warnings = search_result.get("warnings") if isinstance(search_result.get("warnings"), list) else []

        context.update({
            "query": str(search_result.get("query") or context["query"]),
            "provider": str(search_result.get("provider") or settings.web_search_provider),
            "sources": sources,
            "answer": answer,
            "warnings": [str(w) for w in warnings if w],
            "enabled": bool(sources),
            "answer_used": bool(answer and str(answer).strip()) and not sources,
            "has_web_answer": bool(answer and str(answer).strip()),
        })
        context["prompt_context"] = self._format_web_context_for_prompt(context)
        return context

    @staticmethod
    def _cap_web_context(text: str) -> str:
        max_len = max(500, int(getattr(settings, "web_search_context_max_len", 3000) or 3000))
        text = text.strip()
        if len(text) <= max_len:
            return text
        cut = text[:max_len].rfind("\n")
        if cut > max_len * 0.55:
            return text[:cut].rstrip() + "\n...(Web Search 上下文已截断)"
        return text[:max_len].rstrip() + "\n...(Web Search 上下文已截断)"

    @staticmethod
    def _format_web_source_blocks(sources: list, max_total: int) -> List[str]:
        """按来源均衡分配字符预算，避免尾部来源被整体截断丢弃。"""
        if not sources:
            return []
        max_total = max(800, int(max_total or 3000))
        fixed_overhead = 80 * len(sources)
        snippet_budget = max(120, (max_total - fixed_overhead) // max(len(sources), 1))
        lines: List[str] = []
        for source in sources:
            if not isinstance(source, dict):
                continue
            sid = str(source.get("id") or "").strip()
            title = VisualizationService._truncate_text(str(source.get("title", "")), 140)
            url = str(source.get("url") or "").strip()
            snippet = VisualizationService._truncate_text(
                str(source.get("snippet") or source.get("summary") or ""),
                snippet_budget,
            )
            lines.append(f"[{sid}] 标题: {title}")
            if url:
                lines.append(f"[{sid}] URL: {url}")
            if snippet:
                lines.append(f"[{sid}] 摘要: {snippet}")
        return lines

    @staticmethod
    def _format_web_context_for_prompt(context: Dict[str, Any]) -> str:
        if not context.get("requested"):
            return "未启用 Web Search。请只基于输入文本生成报告。"

        sources = context.get("sources") or []
        answer = str(context.get("answer") or "").strip()
        query = context.get("query") or ""
        warning_text = "; ".join(context.get("warnings") or [])

        if not sources and not answer:
            lines = [
                "Web Search 已请求，但未获得有效来源或总结。",
                "请仅基于用户原文生成报告，不要引用外部来源，不要声称使用了 Web Search。",
                f"搜索问题: {query}",
            ]
            if warning_text:
                lines.append(f"搜索警告: {warning_text}")
            return "\n".join(lines)

        lines = [
            "已请求 Web Search，下列为可引用材料；用户原文优先级最高。",
            f"搜索问题: {query}",
        ]

        if sources:
            lines.append(
                "请在 interpretation / mechanism / implication / outlook 等分析句末标注对应 [sN]，"
                "并同步填写 used_source_ids / data_source_refs；尽量分散引用多条来源。"
            )
            lines.append("来源列表:")
            max_len = max(500, int(getattr(settings, "web_search_context_max_len", 3000) or 3000))
            lines.extend(VisualizationService._format_web_source_blocks(sources, max_len - 400))
        elif answer:
            lines.append("未返回可引用的来源列表，仅有搜索侧总结。")
            lines.append("请仅基于用户原文生成报告主体；下列总结仅作低优先级参考。")
            lines.append("不得据此生成 charts/kpis；引用总结时在 evidence 标注 [Web Answer]。")

        if answer:
            lines.append("Web Answer/summary（低优先级，不可单独用于 charts 或 KPI 数字）:")
            lines.append(VisualizationService._truncate_text(answer, 1500))

        if warning_text:
            lines.append(f"搜索警告: {warning_text}")
        return VisualizationService._cap_web_context("\n".join(lines))

    @staticmethod
    def _normalize_deep_research(
        parsed: Dict[str, Any],
        web_search_context: Optional[Dict[str, Any]] = None,
        report_flags: Optional[Dict[str, Any]] = None,
        source_text: str = "",
        complexity_hint: str = "standard",
        complexity_reason_hint: str = "",
    ) -> Dict[str, Any]:
        """
        轻量稳定 Deep Research Webpage 输出结构。

        只做兼容性补齐和低风险过滤，不做严格 schema 校验，避免模型轻微漏字段
        导致整个接口不可用。
        """
        if not isinstance(parsed, dict):
            raise ValueError("模型返回格式无效: 顶层 JSON 必须是对象")

        search_warnings = []
        if web_search_context and isinstance(web_search_context.get("warnings"), list):
            search_warnings = [str(w) for w in web_search_context["warnings"] if w]
        model_warnings = parsed.get("warnings") if isinstance(parsed, dict) else []
        if not isinstance(model_warnings, list):
            model_warnings = [model_warnings] if model_warnings else []
        warnings = search_warnings + [str(w) for w in model_warnings if w]

        parsed["title"] = VisualizationService._normalize_text_block(
            parsed.get("title"), "1", "text"
        )
        parsed["summary"] = VisualizationService._normalize_text_block(
            parsed.get("summary"), "2", "text"
        )
        parsed["research_overview"] = VisualizationService._normalize_research_overview(
            parsed.get("research_overview")
        )
        parsed["conclusion"] = VisualizationService._normalize_conclusion(
            parsed.get("conclusion")
        )

        parsed.setdefault("kpis", [])
        parsed.setdefault("key_findings", [])
        parsed.setdefault("sections", [])
        parsed.setdefault("mindmap", {"id": "6", "title": "", "nodes": []})
        parsed.setdefault("charts", [])
        parsed.setdefault("recommendations", [])
        parsed.setdefault("cross_section_insights", [])
        parsed.setdefault("outlook_trends", [])
        parsed["sources"] = VisualizationService._normalize_sources(
            parsed.get("sources"), web_search_context, warnings
        )
        source_ids = VisualizationService._source_ids_set(parsed.get("sources", []))

        parsed["title"]["text"] = VisualizationService._normalize_text_field(
            parsed["title"].get("text", ""), source_ids, warnings
        )
        parsed["summary"]["text"] = VisualizationService._normalize_text_field(
            parsed["summary"].get("text", ""), source_ids, warnings
        )
        conclusion = parsed["conclusion"]
        for key in (
            "text", "headline", "problem_analysis", "root_causes",
            "strategic_implications", "disclaimer",
        ):
            conclusion[key] = VisualizationService._normalize_text_field(
                conclusion.get(key, ""), source_ids, warnings
            )
        parsed["warnings"] = warnings

        if not isinstance(parsed.get("kpis"), list):
            parsed["kpis"] = []
            warnings.append("fixed_kpis: non_array")
        if not isinstance(parsed.get("key_findings"), list):
            parsed["key_findings"] = []
        if not isinstance(parsed.get("sections"), list):
            parsed["sections"] = []
        if not isinstance(parsed.get("charts"), list):
            parsed["charts"] = []
        if not isinstance(parsed.get("recommendations"), list):
            parsed["recommendations"] = []
        if not isinstance(parsed.get("outlook_trends"), list):
            parsed["outlook_trends"] = []
            warnings.append("fixed_outlook_trends: non_array")

        parsed["cross_section_insights"] = VisualizationService._normalize_cross_section_insights(
            parsed.get("cross_section_insights"), warnings
        )
        parsed["outlook_trends"] = VisualizationService._normalize_outlook_trends(
            parsed.get("outlook_trends"), warnings
        )

        parsed["kpis"] = VisualizationService._normalize_kpis(parsed["kpis"], warnings)
        VisualizationService._normalize_mindmap(parsed)
        parsed["key_findings"] = VisualizationService._normalize_findings(
            parsed["key_findings"], warnings, parsed.get("sources", [])
        )
        parsed["charts"] = VisualizationService._filter_charts(
            parsed["charts"], warnings, source_text=source_text, web_search_context=web_search_context,
            sources=parsed.get("sources", []),
        )
        parsed["sections"] = VisualizationService._normalize_sections(
            parsed["sections"], parsed["charts"], warnings, parsed.get("sources", [])
        )
        parsed["recommendations"] = VisualizationService._normalize_recommendations(
            parsed["recommendations"], warnings, parsed.get("sources", [])
        )
        VisualizationService._sync_structured_refs_from_body(parsed)
        VisualizationService._autofill_structured_source_refs(
            parsed, web_search_context, warnings
        )
        VisualizationService._sync_structured_refs_from_body(parsed)
        VisualizationService._validate_source_references(parsed, warnings)
        VisualizationService._filter_sources_to_cited(parsed, warnings, web_search_context)
        VisualizationService._check_web_sources_referenced(parsed, web_search_context, warnings)
        VisualizationService._dedupe_warnings(warnings)
        VisualizationService._run_content_consistency_checks(parsed, warnings)
        complexity, complexity_reason = VisualizationService._resolve_research_complexity(
            parsed, complexity_hint, complexity_reason_hint
        )
        VisualizationService._fill_metadata(
            parsed,
            warnings,
            web_search_context,
            report_flags=report_flags or {},
            research_complexity=complexity,
            complexity_reason=complexity_reason,
        )

        return parsed

    @staticmethod
    def _is_short_or_thin_text(text: str, min_len: int) -> bool:
        value = str(text or "").strip()
        return len(value) < min_len

    # 显式深度意图（用户直接要求深度/对比/研判类报告）
    DEEP_INTENT_RE = re.compile(
        r"深度分析|深度研究|deep\s*research|全面分析|战略研判|机制分析",
        re.IGNORECASE,
    )
    # 分析维度信号（比较、竞争、趋势、风险、预测等），与显式深度意图不重叠
    ANALYTIC_DIMENSION_RE = re.compile(
        r"对比|比较|竞争|格局|多维|交叉|预测|趋势|风险|演化|驱动",
        re.IGNORECASE,
    )
    SIMPLE_COMPLEXITY_RE = re.compile(r"简述|简要|概述|一句话|简单介绍|快速了解")
    DATA_SIGNAL_RE = re.compile(r"\d+%|\d{4}\s*年|\d+\.\d+|\d+亿|\d+万")

    @staticmethod
    def _infer_research_complexity(
        text: str,
        web_context: Optional[Dict[str, Any]] = None,
    ) -> tuple:
        """根据研究主题与数据特征预判复杂度，不按输入字数分档。

        各信号互斥计分，避免同一关键词在多处重复加分；最终仍允许模型据实调整。
        """
        value = str(text or "").strip()
        if not value:
            return "simple", "输入为空，按精炼报告处理"

        score = 0
        reasons: List[str] = []

        # 显式深度意图：强信号
        if VisualizationService.DEEP_INTENT_RE.search(value):
            score += 3
            reasons.append("用户明确要求深度/全面/战略级分析")

        # 简要意图：强反向信号
        if VisualizationService.SIMPLE_COMPLEXITY_RE.search(value):
            score -= 2
            reasons.append("用户要求简要概述")

        # 分析维度（去重计数，按出现的“不同维度”而非总次数计分）
        dimension_hits = {m.lower() for m in VisualizationService.ANALYTIC_DIMENSION_RE.findall(value)}
        if len(dimension_hits) >= 2:
            score += 2
            reasons.append("涉及多维度比较或趋势/风险判断")
        elif len(dimension_hits) == 1:
            score += 1
            reasons.append("包含一定分析维度")

        # 可量化数据：利于图表与多维分析
        data_signals = len(VisualizationService.DATA_SIGNAL_RE.findall(value))
        if data_signals >= 4:
            score += 1
            reasons.append("输入含较多可量化数据，适合图表与多维分析")

        # 多个研究问题
        question_markers = value.count("?") + value.count("？")
        if question_markers >= 2:
            score += 1
            reasons.append("包含多个明确研究问题")

        # Web Search 有效来源可增强深度
        if web_context and web_context.get("enabled") and web_context.get("sources"):
            score += 1
            reasons.append("Web Search 获得有效来源，可增强研究深度")

        if score >= 3:
            complexity = "deep"
        elif score <= 0:
            complexity = "simple"
        else:
            complexity = "standard"

        reason = "；".join(dict.fromkeys(reasons)) or {
            "simple": "问题相对直接，适合精炼报告",
            "standard": "具备明确研究主题，适合标准研究报告",
            "deep": "主题复杂且具备深度分析价值",
        }[complexity]
        return complexity, reason

    @staticmethod
    def _resolve_research_complexity(
        parsed: Dict[str, Any],
        complexity_hint: str,
        complexity_reason_hint: str,
    ) -> tuple:
        """合并模型输出的 research_complexity 与后端预判。"""
        valid = {"simple", "standard", "deep"}
        hint = complexity_hint if complexity_hint in valid else "standard"
        metadata = parsed.get("metadata") if isinstance(parsed.get("metadata"), dict) else {}
        llm_value = str(metadata.get("research_complexity") or "").strip().lower()
        llm_reason = str(metadata.get("complexity_reason") or "").strip()

        if llm_value in valid:
            complexity = llm_value
            reason = llm_reason or complexity_reason_hint or ""
        else:
            complexity = hint
            reason = complexity_reason_hint or ""

        if not isinstance(parsed.get("metadata"), dict):
            parsed["metadata"] = {}
        parsed["metadata"]["research_complexity"] = complexity
        parsed["metadata"]["complexity_reason"] = reason
        return complexity, reason

    @staticmethod
    def _needs_section_deepening(sections: list, source_text: str = "") -> bool:
        """判断 sections 是否分析深度不足（不按输入长度跳过）。"""
        if not isinstance(sections, list) or not sections:
            return False

        shallow_count = 0
        for section in sections:
            if not isinstance(section, dict):
                continue
            non_empty_layers = 0
            short_layers = 0
            for key, min_len in VisualizationService.SECTION_DEPTH_RULES.items():
                value = str(section.get(key) or "").strip()
                if value:
                    non_empty_layers += 1
                if VisualizationService._is_short_or_thin_text(value, min_len):
                    short_layers += 1

            if non_empty_layers < 4 or short_layers >= 3:
                shallow_count += 1

        # 至少一半章节偏浅，才触发重写，避免过度干预
        return shallow_count > 0 and shallow_count >= max(1, len(sections) // 2)

    def _rewrite_sections_for_depth(
        self,
        text: str,
        normalized: Dict[str, Any],
        web_context: Dict[str, Any],
    ) -> Optional[List[Dict[str, Any]]]:
        """
        当 sections 深度不足时，触发一次“仅重写 sections”的补强。
        不改变报告主题，不写死行业话术。
        """
        sections = normalized.get("sections")
        if not isinstance(sections, list) or not sections:
            return None

        base_sections = []
        for sec in sections:
            if not isinstance(sec, dict):
                continue
            base_sections.append({
                "id": sec.get("id", ""),
                "title": sec.get("title", ""),
                "observation": sec.get("observation", ""),
                "interpretation": sec.get("interpretation", ""),
                "mechanism": sec.get("mechanism", ""),
                "implication": sec.get("implication", ""),
                "uncertainty": sec.get("uncertainty", ""),
                "outlook": sec.get("outlook", ""),
                "insight": sec.get("insight", ""),
            })

        prompt = (
            "你是 Deep Research 报告质量补强助手。请仅重写 sections 的分析层字段，使分析更深入。"
            "\n要求："
            "\n1) 保持 section 数量、id、title 不变；不要输出 summary、visual_refs、content、evidence。"
            "\n2) 只能修改：observation、interpretation、mechanism、implication、uncertainty、outlook、insight。"
            "\n3) 禁止引入输入文本与原 sections 中不存在的新数字、新年份、新比例、新金额、新排名。"
            "\n4) 禁止修改或暗示变更 KPI、charts、来源与事实结论；补强分析，不补强事实。"
            "\n5) 必须按 OIIUO+mechanism 完整填写七层 + insight；各层信息递进，回答 Why / So What / What Next。"
            "\n6) observation >=100 字；interpretation/mechanism/implication 各 >=120 字；uncertainty >=60 字；outlook >=100 字；insight 80~140 字。"
            "\n7) 不要硬编码任何行业模板词，按输入主题自适应。"
            "\n8) Web 来源观点可融入 interpretation/mechanism/implication/outlook；当某句确实引用了某来源时，在该句末标注合法 [sN]（N 须为 Web Search 上下文中真实存在的来源 id），并在该 section 的 used_source_ids 中同步列出；未真正引用就不要标注，禁止 [Web Answer] 标记。"
            "\n9) insight 为 Research Insight：1~2 句，总结本章真正价值，不重复 observation 原句。"
            "\n10) 输出仅包含合法 JSON，格式为 {\"sections\": [...]}，每项含 id、title、七个分析层字段及 used_source_ids。"
            "\n\nWeb Search 上下文：\n"
            f"{web_context.get('prompt_context', '未启用 Web Search')}"
            "\n\n用户输入文本：\n"
            f"{text}"
            "\n\n当前 sections（请在此基础上深化，不改主题）：\n"
            f"{json.dumps(base_sections, ensure_ascii=False)}"
        )

        payload = {
            "model": settings.chat_model_name,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 12288,
            "temperature": 0.2,
        }
        headers = {"Content-Type": "application/json"}
        if settings.chat_model_key:
            headers["Authorization"] = f"Bearer {settings.chat_model_key}"
        url = self._build_chat_url(settings.chat_model_url)

        try:
            response = self._post_chat_completion(url, payload, headers)
            if response.status_code != 200:
                logger.warning("sections 补强调用失败: %s", response.status_code)
                return None
            result = response.json()
            content = ""
            if "choices" in result and result["choices"]:
                content = result["choices"][0].get("message", {}).get("content", "")
            if not content:
                return None
            parsed = json.loads(self._extract_json(content))
            rewritten = parsed.get("sections") if isinstance(parsed, dict) else None
            return rewritten if isinstance(rewritten, list) else None
        except Exception as exc:
            logger.warning("sections 补强失败，保留原结果: %s", exc)
            return None

    @staticmethod
    def _normalize_text_block(value: Any, field_id: str, text_key: str) -> Dict[str, Any]:
        """将 title/summary/conclusion 一类文本块稳定为 {id, text}。"""
        if isinstance(value, dict):
            block = value
            if not isinstance(block.get(text_key), str):
                block[text_key] = "" if block.get(text_key) is None else str(block.get(text_key))
        elif isinstance(value, str):
            block = {text_key: value}
        else:
            block = {text_key: "" if value is None else str(value)}
        block.setdefault("id", field_id)
        return block

    @staticmethod
    def _normalize_conclusion(value: Any) -> Dict[str, Any]:
        """稳定结论章节结构，兼容仅含 text 的旧格式。"""
        block = VisualizationService._normalize_text_block(value, "8", "text")
        for key in (
            "headline",
            "problem_analysis",
            "root_causes",
            "strategic_implications",
            "disclaimer",
        ):
            raw = block.get(key)
            if not isinstance(raw, str):
                raw = "" if raw is None else str(raw)
            block[key] = raw.strip()
        return block

    @staticmethod
    def _normalize_outlook_trends(value: Any, warnings: list = None) -> list:
        """展望要点卡片，最多保留 6 条。"""
        warnings = warnings if warnings is not None else []
        if not isinstance(value, list):
            if value:
                warnings.append("fixed_outlook_trends: non_array")
            return []
        normalized = []
        for item in value:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            description = str(item.get("description") or "").strip()
            if not title and not description:
                continue
            if len(title) > 40:
                title = title[:40]
                warnings.append("truncated_outlook_trend_title")
            if len(description) > 300:
                description = description[:300]
                warnings.append("truncated_outlook_trend_description")
            normalized.append({
                "id": str(item.get("id") or f"8.{len(normalized) + 1}"),
                "title": title,
                "description": description,
            })
            if len(normalized) >= 6:
                warnings.append("truncated_outlook_trends: max_6")
                break
        return normalized

    @staticmethod
    def _normalize_research_overview(value: Any) -> Dict[str, Any]:
        """稳定研究概览结构。"""
        if not isinstance(value, dict):
            value = {}
        value.setdefault("id", "3")
        for key in ("question", "scope", "method"):
            if not isinstance(value.get(key), str):
                value[key] = "" if value.get(key) is None else str(value.get(key))
        return value

    @staticmethod
    def _normalize_sources(
        value: Any,
        web_search_context: Optional[Dict[str, Any]] = None,
        warnings: Optional[list] = None,
    ) -> List[Dict[str, str]]:
        """来源以后端 Web Search 结果为准，避免模型伪造来源。"""
        warnings = warnings if warnings is not None else []
        llm_sources = value if isinstance(value, list) else []

        if web_search_context and web_search_context.get("requested"):
            if llm_sources:
                warnings.append("dropped_llm_sources")
            raw_sources = (
                web_search_context.get("sources")
                if isinstance(web_search_context.get("sources"), list)
                else []
            )
        elif isinstance(value, list):
            raw_sources = value
        else:
            raw_sources = []

        normalized = []
        for item in raw_sources:
            if not isinstance(item, dict):
                continue
            sid = str(item.get("id") or f"s{len(normalized) + 1}")
            if not re.fullmatch(r"s\d+", sid):
                sid = f"s{len(normalized) + 1}"
            normalized.append({
                "id": sid,
                "title": VisualizationService._truncate_text(str(item.get("title") or ""), 160),
                "url": str(item.get("url") or ""),
                "snippet": VisualizationService._truncate_text(str(item.get("snippet") or ""), 500),
                "summary": VisualizationService._truncate_text(str(item.get("summary") or ""), 1000),
            })
        return normalized

    @staticmethod
    def _truncate_text(value: str, max_len: int) -> str:
        value = value.strip()
        if len(value) <= max_len:
            return value
        cut = value[:max_len].rfind("。")
        if cut > max_len * 0.45:
            return value[:cut + 1]
        return value[:max_len].rstrip() + "..."

    @staticmethod
    def _normalize_mindmap(parsed: Dict[str, Any]) -> None:
        """保证 webpage 内嵌 mindmap 维持 nodes/label/children 结构。"""
        mindmap = parsed.get("mindmap")
        if not isinstance(mindmap, dict):
            parsed["mindmap"] = {"id": "6", "title": "", "nodes": []}
            return

        mindmap.setdefault("id", "6")
        mindmap.setdefault("title", "")
        nodes = mindmap.get("nodes")
        if not isinstance(nodes, list):
            mindmap["nodes"] = []
            return

        def normalize_nodes(items, prefix):
            normalized = []
            ordinal = 1
            for node in items:
                if not isinstance(node, dict):
                    continue
                node.setdefault("id", f"{prefix}.{ordinal}")
                node.setdefault("label", node.get("title", ""))
                if not isinstance(node.get("label"), str):
                    node["label"] = str(node.get("label", ""))
                children = node.get("children")
                if not isinstance(children, list):
                    node["children"] = []
                else:
                    node["children"] = normalize_nodes(children, node["id"])
                normalized.append(node)
                ordinal += 1
            return normalized

        mindmap["nodes"] = normalize_nodes(nodes, "6")

    @staticmethod
    def _normalize_kpis(kpis: list, warnings: list = None) -> list:
        """补齐 KPI 指标卡片，建议保留 3~6 项。"""
        warnings = warnings if warnings is not None else []
        normalized = []
        for item in kpis:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "").strip()
            value = str(item.get("value") or "").strip()
            if not label or not value:
                continue
            if len(label) > 16:
                label = label[:16]
                warnings.append("truncated_kpi_label")
            item.setdefault("id", f"2.{len(normalized) + 1}")
            item["label"] = label
            item["value"] = value
            desc = item.get("description")
            if not isinstance(desc, str):
                desc = "" if desc is None else str(desc)
            desc = desc.strip()
            if len(desc) > 80:
                cut = desc[:80].rfind("。")
                desc = desc[: cut + 1 if cut > 20 else 80]
                warnings.append("truncated_kpi_description")
            item["description"] = desc
            evidence = item.get("evidence")
            if isinstance(evidence, list):
                item["evidence"] = [str(x) for x in evidence if x]
            elif evidence:
                item["evidence"] = [str(evidence)]
            else:
                item["evidence"] = []
            normalized.append(item)
            if len(normalized) >= 6:
                warnings.append("truncated_kpis: max_6")
                break
        return normalized

    @staticmethod
    def _source_ids_set(sources: list) -> set:
        return {
            str(source.get("id"))
            for source in (sources or [])
            if isinstance(source, dict) and source.get("id")
        }

    @staticmethod
    def _normalize_source_id_list(
        value: Any,
        source_ids: set,
        warnings: list,
        item_id: Any = None,
    ) -> list:
        if not isinstance(value, list):
            return []
        normalized = []
        for ref in value:
            sid = str(ref).strip()
            if not re.fullmatch(r"s\d+", sid):
                if sid:
                    warnings.append(f"removed_invalid_source_ref:{sid}")
                continue
            if source_ids and sid not in source_ids:
                warnings.append(f"removed_invalid_source_ref:{sid}")
                continue
            if sid not in normalized:
                normalized.append(sid)
        if source_ids and not normalized and value:
            warnings.append(f"cleared_invalid_used_source_ids:{item_id}")
        return normalized

    @staticmethod
    def _extract_inline_source_ids(text: str) -> List[str]:
        ids = []
        for match in VisualizationService.SOURCE_REF_RE.finditer(str(text or "")):
            sid = f"s{match.group(1)}"
            if sid not in ids:
                ids.append(sid)
        return ids

    @staticmethod
    def _merge_source_id_list(
        existing: Any,
        extra: List[str],
        source_ids: set,
    ) -> List[str]:
        merged = []
        for raw in list(existing or []) + list(extra or []):
            sid = str(raw).strip()
            if not re.fullmatch(r"s\d+", sid):
                continue
            if source_ids and sid not in source_ids:
                continue
            if sid not in merged:
                merged.append(sid)
        return merged

    @staticmethod
    def _collect_cited_source_ids(parsed: Dict[str, Any]) -> set:
        cited: set = set()
        section_text_keys = VisualizationService.SECTION_ANALYSIS_KEYS + (
            "summary", "content", "title",
        )

        def absorb(item: dict, text_keys: tuple, id_key: str) -> None:
            if not isinstance(item, dict):
                return
            for ref in item.get(id_key) or []:
                sid = str(ref).strip()
                if re.fullmatch(r"s\d+", sid):
                    cited.add(sid)
            for key in text_keys:
                cited.update(VisualizationService._extract_inline_source_ids(item.get(key, "")))

        for section in parsed.get("sections", []):
            absorb(section, section_text_keys, "used_source_ids")
        for finding in parsed.get("key_findings", []):
            absorb(finding, ("title", "insight"), "used_source_ids")
        for rec in parsed.get("recommendations", []):
            absorb(
                rec,
                ("target", "rationale", "action", "risk", "title", "description"),
                "used_source_ids",
            )
        for chart in parsed.get("charts", []):
            absorb(
                chart,
                ("title", "description", "chart_insight", "interpretation", "data_notes"),
                "data_source_refs",
            )

        summary = parsed.get("summary")
        if isinstance(summary, dict):
            cited.update(
                VisualizationService._extract_inline_source_ids(summary.get("text", ""))
            )
        conclusion = parsed.get("conclusion")
        if isinstance(conclusion, dict):
            for key in (
                "text", "headline", "problem_analysis", "root_causes",
                "strategic_implications", "disclaimer",
            ):
                cited.update(
                    VisualizationService._extract_inline_source_ids(conclusion.get(key, ""))
                )
        return cited

    @staticmethod
    def _collect_cited_source_ids_ordered(parsed: Dict[str, Any]) -> List[str]:
        """按报告阅读顺序收集首次出现的来源 id，用于 [1][2] 展示排序。"""
        ordered: List[str] = []
        seen: set = set()

        def add_from_text(text: str) -> None:
            for match in VisualizationService.SOURCE_REF_RE.finditer(str(text or "")):
                sid = f"s{match.group(1)}"
                if sid not in seen:
                    seen.add(sid)
                    ordered.append(sid)

        def add_from_ids(ids: Any) -> None:
            if not isinstance(ids, list):
                return
            for raw in ids:
                sid = str(raw).strip()
                if re.fullmatch(r"s\d+", sid) and sid not in seen:
                    seen.add(sid)
                    ordered.append(sid)

        def walk_item(item: Dict[str, Any], text_keys: tuple, id_key: str) -> None:
            if not isinstance(item, dict):
                return
            for key in text_keys:
                add_from_text(item.get(key, ""))
            add_from_ids(item.get(id_key))

        summary = parsed.get("summary")
        if isinstance(summary, dict):
            add_from_text(summary.get("text", ""))

        for finding in parsed.get("key_findings", []):
            walk_item(finding, ("title", "insight"), "used_source_ids")

        section_keys = VisualizationService.SECTION_ANALYSIS_KEYS + ("summary", "content", "title")
        for section in parsed.get("sections", []):
            walk_item(section, section_keys, "used_source_ids")

        for chart in parsed.get("charts", []):
            walk_item(
                chart,
                ("title", "description", "chart_insight", "interpretation", "data_notes"),
                "data_source_refs",
            )

        conclusion = parsed.get("conclusion")
        if isinstance(conclusion, dict):
            for key in (
                "text",
                "headline",
                "problem_analysis",
                "root_causes",
                "strategic_implications",
                "disclaimer",
            ):
                add_from_text(conclusion.get(key, ""))

        for rec in parsed.get("recommendations", []):
            walk_item(rec, ("target", "rationale", "action", "risk", "title", "description"), "used_source_ids")

        return ordered

    @staticmethod
    def _normalize_text_field(text: str, source_ids: set, warnings: list) -> str:
        """保留合法 [sN] 引用，移除无效编号与 [Web Answer]。"""
        value = str(text or "")
        if not value:
            return ""

        if re.search(r"\[Web Answer\]", value, re.IGNORECASE):
            warnings.append("removed_web_answer_marker")
        value = re.sub(r"\s*\[Web Answer\]\s*", " ", value, flags=re.IGNORECASE)

        if not source_ids:
            if VisualizationService.SOURCE_REF_RE.search(value):
                warnings.append("removed_orphan_source_markers")
            return VisualizationService._strip_source_markers(value).strip()

        def repl(match: re.Match) -> str:
            ref_id = f"s{match.group(1)}"
            if ref_id not in source_ids:
                warnings.append(f"removed_invalid_source_ref:{ref_id}")
                return ""
            return match.group(0)

        value = VisualizationService.SOURCE_REF_RE.sub(repl, value)
        value = re.sub(r"\s+([，。；：、,.!?！？])", r"\1", value)
        return value.strip()

    @staticmethod
    def _strip_text_field(text: str, warnings: list) -> str:
        """兼容旧调用：无来源上下文时移除全部引用标记。"""
        return VisualizationService._normalize_text_field(text, set(), warnings)

    @staticmethod
    def _normalize_findings(findings: list, warnings: list = None, sources: list = None) -> list:
        """补齐核心发现的低风险默认字段。"""
        warnings = warnings if warnings is not None else []
        source_ids = VisualizationService._source_ids_set(sources)
        valid_confidence = {"high", "medium", "low"}
        normalized = []
        for item in findings:
            if not isinstance(item, dict):
                continue
            item.setdefault("id", f"4.{len(normalized) + 1}")
            item.setdefault("title", "")
            item["title"] = VisualizationService._normalize_text_field(
                item.get("title", ""), source_ids, warnings
            )
            item.setdefault("insight", "")
            item["insight"] = VisualizationService._normalize_text_field(
                item.get("insight", ""), source_ids, warnings
            )
            if not isinstance(item.get("evidence"), list):
                item["evidence"] = []
            elif item["evidence"]:
                warnings.append(f"cleared_finding_evidence: {item.get('id')}")
                item["evidence"] = []
            item["used_source_ids"] = VisualizationService._normalize_source_id_list(
                item.get("used_source_ids"), source_ids, warnings, item.get("id")
            )
            if item.get("confidence") not in valid_confidence:
                item["confidence"] = "medium"
            normalized.append(item)
        return normalized

    SECTION_ANALYSIS_KEYS = (
        "observation", "interpretation", "mechanism", "implication", "uncertainty", "outlook", "insight",
    )

    @staticmethod
    def _normalize_cross_section_insights(value: Any, warnings: list = None) -> list:
        """跨章节关联洞察，最多保留 3 条。"""
        warnings = warnings if warnings is not None else []
        if not isinstance(value, list):
            if value:
                warnings.append("fixed_cross_section_insights: non_array")
            return []
        normalized = []
        for item in value:
            text = str(item or "").strip()
            if not text:
                continue
            if len(text) > 500:
                text = text[:500]
                warnings.append("truncated_cross_section_insight")
            normalized.append(text)
            if len(normalized) >= 3:
                warnings.append("truncated_cross_section_insights: max_3")
                break
        return normalized

    @staticmethod
    def _normalize_sections(sections: list, charts: list = None, warnings: list = None, sources: list = None) -> list:
        """补齐章节分析的低风险默认字段，并校验 visual_refs。"""
        warnings = warnings if warnings is not None else []
        source_ids = VisualizationService._source_ids_set(sources)
        chart_ids = {
            str(chart.get("id"))
            for chart in (charts or [])
            if isinstance(chart, dict) and chart.get("id") is not None
        }
        normalized = []
        for item in sections:
            if not isinstance(item, dict):
                continue
            item.setdefault("id", f"5.{len(normalized) + 1}")
            item.setdefault("title", "")
            item.setdefault("summary", "")
            item.setdefault("content", "")
            item["title"] = VisualizationService._normalize_text_field(
                item.get("title", ""), source_ids, warnings
            )
            item["summary"] = VisualizationService._normalize_text_field(
                item.get("summary", ""), source_ids, warnings
            )
            item["content"] = VisualizationService._normalize_text_field(
                item.get("content", ""), source_ids, warnings
            )
            for key in VisualizationService.SECTION_ANALYSIS_KEYS:
                if not isinstance(item.get(key), str):
                    item[key] = "" if item.get(key) is None else str(item.get(key))
                item[key] = VisualizationService._normalize_text_field(
                    item[key], source_ids, warnings
                )
            if not item["insight"] and item["content"]:
                warnings.append(f"missing_section_insight: {item.get('id')}")
            if not isinstance(item.get("evidence"), list):
                item["evidence"] = []
            elif item["evidence"]:
                warnings.append(f"cleared_section_evidence: {item.get('id')}")
                item["evidence"] = []
            if item["observation"] and not item["interpretation"]:
                warnings.append(f"weak_section_interpretation: {item.get('id')}")
            if item["observation"] and not item["implication"]:
                warnings.append(f"weak_section_implication: {item.get('id')}")
            refs = item.get("visual_refs")
            if not isinstance(refs, list):
                refs = []
            valid_refs = []
            for ref in refs:
                ref_id = str(ref)
                if ref_id in chart_ids:
                    valid_refs.append(ref_id)
                else:
                    warnings.append(f"removed_invalid_visual_ref: {ref_id}")
            item["visual_refs"] = valid_refs
            item["used_source_ids"] = VisualizationService._normalize_source_id_list(
                item.get("used_source_ids"), source_ids, warnings, item.get("id")
            )
            if item["observation"] and item["interpretation"] and not item.get("mechanism"):
                warnings.append(f"weak_section_mechanism: {item.get('id')}")
            obs = item.get("observation", "")
            interp = item.get("interpretation", "")
            if obs and interp and VisualizationService._text_overlap_ratio(obs[:80], interp[:80]) >= 0.6:
                warnings.append(f"duplicate_section_layers: {item.get('id')}")
            normalized.append(item)
        return normalized

    @staticmethod
    def _strip_source_markers(text: str) -> str:
        """清理面向用户正文中的 [sN]/[Web Answer] 引用标记。"""
        value = str(text or "")
        value = VisualizationService.SOURCE_MARKER_RE.sub("", value)
        value = re.sub(r"\s+([，。；：、,.!?！？])", r"\1", value)
        return value

    @staticmethod
    def _validate_source_references(parsed: Dict[str, Any], warnings: list = None) -> None:
        """校验正文与 evidence 中的 [sN] 引用，避免引用不存在的 Web 来源。"""
        warnings = warnings if warnings is not None else []
        source_ids = {
            str(source.get("id"))
            for source in parsed.get("sources", [])
            if isinstance(source, dict) and source.get("id")
        }

        def scan_text(text: str) -> None:
            for match in VisualizationService.SOURCE_REF_RE.finditer(str(text)):
                ref_id = f"s{match.group(1)}"
                if ref_id not in source_ids:
                    warnings.append(f"invalid_source_reference:{ref_id}")

        def check_item_text(item: dict, keys: tuple) -> None:
            if not isinstance(item, dict):
                return
            for key in keys:
                if item.get(key):
                    scan_text(str(item[key]))
            evidence = item.get("evidence")
            if isinstance(evidence, list):
                for evidence_item in evidence:
                    scan_text(str(evidence_item))

        for item in parsed.get("key_findings", []):
            check_item_text(item, ("title", "insight"))
        for item in parsed.get("sections", []):
            check_item_text(
                item,
                VisualizationService.SECTION_ANALYSIS_KEYS + ("summary", "content"),
            )
        for item in parsed.get("kpis", []):
            check_item_text(item, ("label", "description"))

        conclusion = parsed.get("conclusion")
        if isinstance(conclusion, dict):
            check_item_text(
                conclusion,
                (
                    "text", "headline", "problem_analysis", "root_causes",
                    "strategic_implications", "disclaimer",
                ),
            )
        for item in parsed.get("outlook_trends", []):
            check_item_text(item, ("title", "description"))

    @staticmethod
    def _has_structured_source_refs(parsed: Dict[str, Any]) -> bool:
        def has_ids(value: Any) -> bool:
            if not isinstance(value, list):
                return False
            return any(str(item).strip() for item in value)

        for item in parsed.get("sections", []):
            if isinstance(item, dict) and has_ids(item.get("used_source_ids")):
                return True
        for item in parsed.get("key_findings", []):
            if isinstance(item, dict) and has_ids(item.get("used_source_ids")):
                return True
        for item in parsed.get("recommendations", []):
            if isinstance(item, dict) and has_ids(item.get("used_source_ids")):
                return True
        for chart in parsed.get("charts", []):
            if isinstance(chart, dict) and has_ids(chart.get("data_source_refs")):
                return True
        return False

    @staticmethod
    def _sync_structured_refs_from_body(parsed: Dict[str, Any]) -> None:
        """将正文中的 [sN] 合并进 used_source_ids / data_source_refs。"""
        source_ids = VisualizationService._source_ids_set(parsed.get("sources"))

        def sync(item: dict, text_keys: tuple, id_key: str) -> None:
            if not isinstance(item, dict):
                return
            inline = []
            for key in text_keys:
                inline.extend(VisualizationService._extract_inline_source_ids(item.get(key, "")))
            if inline:
                item[id_key] = VisualizationService._merge_source_id_list(
                    item.get(id_key), inline, source_ids
                )

        section_keys = VisualizationService.SECTION_ANALYSIS_KEYS + ("summary", "content", "title")
        for section in parsed.get("sections", []):
            sync(section, section_keys, "used_source_ids")
        for finding in parsed.get("key_findings", []):
            sync(finding, ("title", "insight"), "used_source_ids")
        for rec in parsed.get("recommendations", []):
            sync(
                rec,
                ("target", "rationale", "action", "risk", "title", "description"),
                "used_source_ids",
            )
        for chart in parsed.get("charts", []):
            sync(
                chart,
                ("title", "description", "chart_insight", "interpretation", "data_notes"),
                "data_source_refs",
            )

    @staticmethod
    def _autofill_structured_source_refs(
        parsed: Dict[str, Any],
        web_search_context: Optional[Dict[str, Any]],
        warnings: list = None,
    ) -> None:
        """引用以模型自身标注为准；仅当全报告完全无引用时，做最小、低置信度的兜底补全。

        设计原则（避免“机械凑引用”）：
        - 若模型已在任意模块给出引用（含正文 [sN]），完全信任模型，不再伪造任何条目引用；
        - 仅在启用 Web Search 且检索到来源、但全报告零引用时，才把来源分散补到 sections
          的分析层，并打 low_confidence_refs 标记，提示该关联为启发式补全；
        - 不再给 findings / charts / recommendations 机械分配来源。
        """
        warnings = warnings if warnings is not None else []
        if not web_search_context or not web_search_context.get("enabled"):
            return
        sources = parsed.get("sources", [])
        if not isinstance(sources, list) or not sources:
            return
        source_ids = [
            str(item.get("id")).strip()
            for item in sources
            if isinstance(item, dict) and item.get("id")
        ]
        if not source_ids:
            return

        # 模型已有任何引用 → 信任模型，不做任何补全。
        if VisualizationService._collect_cited_source_ids(parsed):
            return

        # 零引用兜底：只选一个最主要的模块作为锚点分散补全，避免每个模块都机械挂来源；
        # 按 sections → key_findings → recommendations 优先级择一，确保来源不会整批丢失。
        anchor_specs = [
            ("sections", ("interpretation", "implication", "outlook", "insight", "observation")),
            ("key_findings", ("insight", "title")),
            ("recommendations", ("rationale", "action", "target")),
        ]
        anchor_items = None
        anchor_body_keys: tuple = ()
        for field, body_keys in anchor_specs:
            items = [i for i in parsed.get(field, []) if isinstance(i, dict)]
            if items:
                anchor_items = items
                anchor_body_keys = body_keys
                break
        if not anchor_items:
            return

        idx = 0

        def next_id() -> str:
            nonlocal idx
            sid = source_ids[idx % len(source_ids)]
            idx += 1
            return sid

        filled = False
        for item in anchor_items:
            sid = next_id()
            item["used_source_ids"] = [sid]
            body_key = next((k for k in anchor_body_keys if str(item.get(k) or "").strip()), anchor_body_keys[0])
            body = str(item.get(body_key) or "").rstrip()
            marker = f"[{sid}]"
            if marker not in body:
                item[body_key] = f"{body} {marker}".strip() if body else marker
            filled = True

        if filled:
            warnings.append("auto_assigned_source_refs")
            warnings.append("low_confidence_refs")

    @staticmethod
    def _filter_sources_to_cited(
        parsed: Dict[str, Any],
        warnings: list = None,
        web_search_context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """仅保留报告中实际引用的来源，供前端参考来源区展示。"""
        warnings = warnings if warnings is not None else []
        sources = parsed.get("sources")
        if not isinstance(sources, list) or not sources:
            return
        retrieved = len(sources)
        if web_search_context and web_search_context.get("enabled"):
            ctx_sources = web_search_context.get("sources")
            if isinstance(ctx_sources, list) and ctx_sources:
                retrieved = len(ctx_sources)
        cited_ids = VisualizationService._collect_cited_source_ids(parsed)
        ordered_ids = VisualizationService._collect_cited_source_ids_ordered(parsed)
        for sid in cited_ids:
            if sid not in ordered_ids:
                ordered_ids.append(sid)
        meta = parsed.setdefault("metadata", {})
        if isinstance(meta, dict):
            meta["web_search_retrieved_count"] = retrieved
        if not cited_ids:
            parsed["sources"] = []
            if isinstance(meta, dict):
                meta["cited_source_count"] = 0
            if retrieved > 0:
                warnings.append("web_content_unreferenced")
            return
        by_id = {
            str(item.get("id")).strip(): item
            for item in sources
            if isinstance(item, dict) and str(item.get("id")).strip()
        }
        retrieval_order = {
            str(item.get("id")).strip(): index
            for index, item in enumerate(sources)
            if isinstance(item, dict)
        }
        filtered: List[Dict[str, Any]] = []
        cite_no = 0
        for sid in ordered_ids:
            if sid not in cited_ids:
                continue
            item = by_id.get(sid)
            if not isinstance(item, dict):
                continue
            cite_no += 1
            entry = dict(item)
            entry["cite_no"] = cite_no
            filtered.append(entry)
        if not filtered:
            filtered = [
                dict(item, cite_no=index + 1)
                for index, item in enumerate(
                    sorted(
                        [by_id[sid] for sid in cited_ids if sid in by_id],
                        key=lambda row: retrieval_order.get(str(row.get("id")).strip(), 9999),
                    )
                )
            ]
        parsed["sources"] = filtered
        if isinstance(meta, dict):
            meta["cited_source_count"] = len(filtered)
        VisualizationService._prune_structured_refs_to_sources(parsed, cited_ids)
        unused_count = retrieved - len(filtered)
        if unused_count > 0:
            warnings.append(f"unused_web_sources:{unused_count}")

    @staticmethod
    def _prune_structured_refs_to_sources(parsed: Dict[str, Any], cited_ids: set) -> None:
        """过滤后同步裁剪各模块中指向已移除来源的结构化引用。"""
        allowed = set(cited_ids or [])

        def prune_list(value: Any) -> list:
            if not isinstance(value, list):
                return []
            return [str(item).strip() for item in value if str(item).strip() in allowed]

        for section in parsed.get("sections", []):
            if isinstance(section, dict):
                section["used_source_ids"] = prune_list(section.get("used_source_ids"))
        for finding in parsed.get("key_findings", []):
            if isinstance(finding, dict):
                finding["used_source_ids"] = prune_list(finding.get("used_source_ids"))
        for rec in parsed.get("recommendations", []):
            if isinstance(rec, dict):
                rec["used_source_ids"] = prune_list(rec.get("used_source_ids"))
        for chart in parsed.get("charts", []):
            if isinstance(chart, dict):
                chart["data_source_refs"] = prune_list(chart.get("data_source_refs"))

    @staticmethod
    def _dedupe_warnings(warnings: list) -> None:
        if not warnings:
            return
        seen = set()
        deduped = []
        for item in warnings:
            key = str(item)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(key)
        warnings[:] = deduped

    @staticmethod
    def _check_web_sources_referenced(
        parsed: Dict[str, Any],
        web_search_context: Optional[Dict[str, Any]],
        warnings: list = None,
    ) -> None:
        """若存在 Web 来源但结构化字段未引用，记录 warning。"""
        warnings = warnings if warnings is not None else []
        if not web_search_context or not web_search_context.get("enabled"):
            return
        sources = parsed.get("sources", [])
        if not isinstance(sources, list) or not sources:
            return
        if VisualizationService._has_structured_source_refs(parsed):
            return

        warnings.append("web_content_unreferenced")

    @staticmethod
    def _normalize_recommendations(
        recommendations: list,
        warnings: list = None,
        sources: list = None,
    ) -> list:
        """补齐建议项的低风险默认字段，兼容旧 title/description 结构。"""
        warnings = warnings if warnings is not None else []
        source_ids = VisualizationService._source_ids_set(sources)
        legacy_map = {"high": "P0", "medium": "P1", "low": "P2"}
        normalized = []
        for item in recommendations:
            if not isinstance(item, dict):
                continue
            item.setdefault("id", f"9.{len(normalized) + 1}")
            for key in ("target", "rationale", "action", "risk", "title", "description"):
                if not isinstance(item.get(key), str):
                    item[key] = "" if item.get(key) is None else str(item.get(key))
                item[key] = VisualizationService._normalize_text_field(
                    item[key], source_ids, warnings
                )
            if not item["target"] and item["title"]:
                item["target"] = item["title"]
            if not item["action"] and item["description"]:
                item["action"] = item["description"]
            if not item["title"] and item["target"]:
                item["title"] = item["target"]
            if not item["description"] and item["action"]:
                item["description"] = item["action"]
            raw_priority = str(item.get("priority") or "P1").strip()
            lower = raw_priority.lower()
            upper = raw_priority.upper()
            if lower in legacy_map:
                item["priority"] = legacy_map[lower]
            elif upper in {"P0", "P1", "P2"}:
                item["priority"] = upper
            else:
                item["priority"] = "P1"
            item["used_source_ids"] = VisualizationService._normalize_source_id_list(
                item.get("used_source_ids"), source_ids, warnings, item.get("id")
            )
            normalized.append(item)
        priority_rank = {"P0": 0, "P1": 1, "P2": 2}
        normalized.sort(key=lambda x: priority_rank.get(x.get("priority"), 1))
        return normalized

    # 前端 ECharts / HTML 支持的图表类型（table 由 HTML 渲染，其余走 ECharts）
    ALLOWED_CHART_TYPES = frozenset({
        "bar", "line", "pie", "table",
        "area", "horizontal_bar", "scatter", "radar", "gauge", "funnel", "donut",
        "stacked_bar", "heatmap",
    })

    @staticmethod
    def _filter_charts(
        charts: list,
        warnings: list = None,
        source_text: str = "",
        web_search_context: Optional[Dict[str, Any]] = None,
        sources: list = None,
    ) -> list:
        """过滤非法图表类型，并补齐前端需要的基本结构。"""
        warnings = warnings if warnings is not None else []
        source_ids = VisualizationService._source_ids_set(sources)
        filtered = []

        for index, chart in enumerate(charts, start=1):
            if not isinstance(chart, dict):
                warnings.append("dropped_invalid_chart: non_object")
                logger.warning("忽略非法 chart: 非对象")
                continue

            chart_type = chart.get("type")
            if chart_type not in VisualizationService.ALLOWED_CHART_TYPES:
                warnings.append(f"dropped_invalid_chart_type: {chart_type}")
                logger.warning(f"忽略非法 chart 类型: {chart_type}")
                continue

            data = chart.get("data")
            if not isinstance(data, dict):
                data = {}
                chart["data"] = data

            if not VisualizationService._normalize_chart_data(
                chart_type, data, warnings, chart.get("id", index)
            ):
                warnings.append(f"dropped_empty_chart: {chart.get('id', index)}")
                continue

            chart.setdefault("id", f"7.{len(filtered) + 1}")
            chart.setdefault("title", "")
            chart["title"] = VisualizationService._normalize_text_field(
                chart.get("title", ""), source_ids, warnings
            )
            for key in ("description", "chart_insight", "why_this_chart", "interpretation", "data_notes"):
                if not isinstance(chart.get(key), str):
                    chart[key] = "" if chart.get(key) is None else str(chart.get(key))
                chart[key] = VisualizationService._normalize_text_field(
                    chart[key], source_ids, warnings
                )
            if not chart.get("chart_insight"):
                warnings.append(f"missing_chart_insight: {chart.get('id')}")
                fallback = chart.get("interpretation") or chart.get("description") or ""
                chart["chart_insight"] = str(fallback).strip() or "详见图表数据与解读。"
            if not chart.get("interpretation"):
                warnings.append(f"missing_chart_interpretation: {chart.get('id')}")
            if not str(chart.get("description") or "").strip():
                chart["description"] = ""
                warnings.append(f"missing_chart_description: {chart.get('id')}")
            chart["data_source_refs"] = VisualizationService._normalize_source_id_list(
                chart.get("data_source_refs"), source_ids, warnings, chart.get("id")
            )
            chart["data_confidence"] = VisualizationService._infer_chart_data_confidence(
                chart, source_text, web_search_context
            )
            if chart["data_confidence"] == "unverified":
                warnings.append(f"chart_data_unverified: {chart.get('id')}")
            filtered.append(chart)

        return filtered

    @staticmethod
    def _normalize_chart_data(
        chart_type: str, data: dict, warnings: list, chart_id: Any
    ) -> bool:
        """按类型规范化 chart.data，返回 False 表示应丢弃该图表。"""
        if chart_type in {"bar", "pie", "funnel", "donut", "horizontal_bar"}:
            labels = data.get("labels") if isinstance(data.get("labels"), list) else []
            values = data.get("values") if isinstance(data.get("values"), list) else []
            labels, values, _ = VisualizationService._align_parallel_arrays(
                labels, values, warnings, chart_id
            )
            if not labels or not values:
                return False
            data["labels"] = labels
            data["values"] = values
            return True

        if chart_type in {"line", "area"}:
            if "categories" not in data and "labels" in data:
                data["categories"] = data["labels"]
            categories = data.get("categories") if isinstance(data.get("categories"), list) else []
            values = data.get("values") if isinstance(data.get("values"), list) else []
            categories, values, _ = VisualizationService._align_parallel_arrays(
                categories, values, warnings, chart_id
            )
            if not categories or not values:
                return False
            data["categories"] = categories
            data["values"] = values
            return True

        if chart_type == "table":
            headers = data.get("headers") if isinstance(data.get("headers"), list) else []
            rows = data.get("rows") if isinstance(data.get("rows"), list) else []
            rows = [row for row in rows if isinstance(row, list)]
            if not headers or not rows:
                return False
            header_len = len(headers)
            aligned_rows = []
            for row in rows:
                if len(row) < header_len:
                    aligned_rows.append(list(row) + [""] * (header_len - len(row)))
                    warnings.append(f"fixed_table_row_length: {chart_id}")
                elif len(row) > header_len:
                    aligned_rows.append(row[:header_len])
                    warnings.append(f"fixed_table_row_length: {chart_id}")
                else:
                    aligned_rows.append(row)
            data["headers"] = headers
            data["rows"] = aligned_rows
            return True

        if chart_type == "scatter":
            points = data.get("points")
            if isinstance(points, list) and points:
                normalized = []
                for pt in points:
                    if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                        normalized.append([pt[0], pt[1]])
                if not normalized:
                    return False
                data["points"] = normalized
                return True
            x_vals = data.get("x") if isinstance(data.get("x"), list) else []
            y_vals = data.get("y") if isinstance(data.get("y"), list) else []
            x_vals, y_vals, _ = VisualizationService._align_parallel_arrays(
                x_vals, y_vals, warnings, chart_id
            )
            if not x_vals or not y_vals:
                return False
            data["x"] = x_vals
            data["y"] = y_vals
            return True

        if chart_type == "radar":
            indicators = data.get("indicators")
            if not isinstance(indicators, list) or not indicators:
                return False
            norm_indicators = []
            for ind in indicators:
                if isinstance(ind, dict) and ind.get("name"):
                    norm_indicators.append({
                        "name": str(ind["name"]),
                        "max": ind.get("max", 100),
                    })
                elif isinstance(ind, str) and ind.strip():
                    norm_indicators.append({"name": ind.strip(), "max": 100})
            if not norm_indicators:
                return False
            data["indicators"] = norm_indicators
            series = data.get("series")
            if isinstance(series, list) and series:
                norm_series = []
                for item in series:
                    if not isinstance(item, dict):
                        continue
                    vals = item.get("values") if isinstance(item.get("values"), list) else []
                    size = min(len(vals), len(norm_indicators))
                    if size == 0:
                        continue
                    if len(vals) != len(norm_indicators):
                        warnings.append(f"fixed_chart_data_length: {chart_id}")
                    norm_series.append({
                        "name": str(item.get("name", "")),
                        "values": vals[:size] + [0] * (len(norm_indicators) - size),
                    })
                if not norm_series:
                    return False
                data["series"] = norm_series
            else:
                values = data.get("values") if isinstance(data.get("values"), list) else []
                size = min(len(values), len(norm_indicators))
                if size == 0:
                    return False
                if len(values) != len(norm_indicators):
                    warnings.append(f"fixed_chart_data_length: {chart_id}")
                data["values"] = values[:size] + [0] * (len(norm_indicators) - size)
            return True

        if chart_type == "gauge":
            if "value" not in data:
                return False
            value = data.get("value")
            if value is None:
                return False
            data["value"] = value
            data.setdefault("max", 100)
            data.setdefault("name", "")
            return True

        if chart_type == "stacked_bar":
            labels = data.get("labels") if isinstance(data.get("labels"), list) else []
            series = data.get("series") if isinstance(data.get("series"), list) else []
            if not labels or not series:
                return False
            norm_series = []
            for item in series:
                if not isinstance(item, dict):
                    continue
                vals = item.get("values") if isinstance(item.get("values"), list) else []
                if not vals:
                    continue
                if len(vals) != len(labels):
                    warnings.append(f"fixed_chart_data_length: {chart_id}")
                size = min(len(vals), len(labels))
                norm_series.append({
                    "name": str(item.get("name", "")),
                    "values": vals[:size],
                })
            if not norm_series:
                return False
            data["labels"] = labels
            data["series"] = norm_series
            return True

        if chart_type == "heatmap":
            x_labels = data.get("xLabels") or data.get("x_labels") or []
            y_labels = data.get("yLabels") or data.get("y_labels") or []
            values = data.get("values")
            if not isinstance(x_labels, list) or not isinstance(y_labels, list):
                return False
            if not x_labels or not y_labels or not isinstance(values, list):
                return False
            data["xLabels"] = x_labels
            data["yLabels"] = y_labels
            data["values"] = values
            return True

        return False

    @staticmethod
    def _align_parallel_arrays(
        left: list, right: list, warnings: list = None, chart_id: Any = None
    ) -> tuple:
        """对齐图表横轴/值数组，避免前端渲染长度不一致。"""
        if len(left) != len(right):
            if warnings is not None:
                warnings.append(f"fixed_chart_data_length: {chart_id}")
        size = min(len(left), len(right))
        return left[:size], right[:size], len(left) == len(right)

    @staticmethod
    def _fill_metadata(
        parsed: Dict[str, Any],
        warnings: list = None,
        web_search_context: Optional[Dict[str, Any]] = None,
        report_flags: Optional[Dict[str, Any]] = None,
        research_complexity: str = "standard",
        complexity_reason: str = "",
    ) -> None:
        """由后端补齐统计元数据，避免模型生成不稳定。"""
        metadata = parsed.setdefault("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
            parsed["metadata"] = metadata

        requested = bool(web_search_context.get("requested")) if web_search_context else False
        enabled = bool(web_search_context.get("enabled")) if web_search_context else False
        answer_used = bool(web_search_context.get("answer_used")) if web_search_context else False
        query = str(web_search_context.get("query") or "") if web_search_context else ""
        provider = str(web_search_context.get("provider") or settings.web_search_provider) if web_search_context else str(settings.web_search_provider)
        sources = parsed.get("sources", [])
        cited_count = len(sources) if isinstance(sources, list) else 0
        retrieved_count = int(metadata.get("web_search_retrieved_count") or cited_count)

        metadata.setdefault("id", "10")
        metadata["visualization_type"] = "deep_research_webpage"
        metadata["schema_version"] = VisualizationService.DEEP_RESEARCH_SCHEMA_VERSION
        metadata["chart_count"] = len(parsed.get("charts", []))
        metadata["section_count"] = len(parsed.get("sections", []))
        metadata["finding_count"] = len(parsed.get("key_findings", []))
        metadata["kpi_count"] = len(parsed.get("kpis", []))
        metadata["cross_section_insight_count"] = len(parsed.get("cross_section_insights", []))
        metadata["outlook_trend_count"] = len(parsed.get("outlook_trends", []))
        metadata["source_count"] = cited_count
        metadata["cited_source_count"] = cited_count
        metadata["web_search_retrieved_count"] = retrieved_count
        metadata["web_search_requested"] = requested
        metadata["web_search_enabled"] = enabled
        metadata["web_search_answer_used"] = answer_used and not enabled
        metadata["web_search_query"] = query
        metadata["web_search_provider"] = provider
        answer_text = ""
        if web_search_context and isinstance(web_search_context.get("answer"), str):
            answer_text = web_search_context["answer"].strip()
        if requested and answer_text and metadata["source_count"] == 0:
            metadata["web_answer_preview"] = VisualizationService._truncate_text(answer_text, 200)
        else:
            metadata["web_answer_preview"] = ""
        metadata["warnings"] = warnings or []
        metadata["warning_count"] = len(metadata["warnings"])
        metadata["research_complexity"] = research_complexity
        metadata["complexity_reason"] = complexity_reason or ""
        flags = report_flags or {}
        metadata["degraded"] = bool(flags.get("degraded"))
        metadata["partial_recovery"] = bool(flags.get("partial_recovery"))
        metadata["quality_issues"] = VisualizationService._build_quality_issues(
            metadata["warnings"], metadata
        )
        metadata["quality_banner"] = VisualizationService._quality_banner_messages(
            metadata["quality_issues"], metadata
        )

        overview = parsed.get("research_overview")
        if isinstance(overview, dict):
            if enabled:
                overview["method"] = "基于输入文本，并结合 Web Search 公开信息补充分析"
            elif answer_used:
                overview["method"] = "基于输入文本，并结合 Web Search 总结线索进行补充分析（无可追溯来源条目）"
            elif requested:
                overview["method"] = "基于输入文本进行归纳、比较、趋势判断和结构化分析"

    def _build_webpage_prompt(
        self, text: str, web_context: Dict[str, Any], complexity_hint: str
    ) -> str:
        ctx = web_context.get("prompt_context", "")
        base = settings.webpage_prompt.replace("{text}", text).replace("{web_context}", ctx)
        guidance = COMPLEXITY_GUIDANCE.get(complexity_hint, COMPLEXITY_GUIDANCE["standard"])
        complexity_block = RESEARCH_COMPLEXITY_PROMPT.format(
            complexity_hint=f"后端预判研究复杂度倾向：{complexity_hint}（模型可据实际内容调整）。",
            complexity_guidance=guidance,
        )
        parts = [base, complexity_block, QUALITY_RULES_PROMPT, SCHEMA_SOURCE_FIELDS_PROMPT]
        if web_context.get("enabled") and web_context.get("sources"):
            parts.append(WEB_SEARCH_PROMPT)
        return "\n".join(parts)

    @staticmethod
    def _repair_json_text(text: str) -> str:
        """轻量 JSON 修复：去尾逗号并尝试补全未闭合括号。"""
        value = str(text or "").strip()
        if not value:
            return value
        value = re.sub(r",\s*}", "}", value)
        value = re.sub(r",\s*]", "]", value)
        open_curly = value.count("{") - value.count("}")
        open_square = value.count("[") - value.count("]")
        if open_curly > 0:
            value += "}" * open_curly
        if open_square > 0:
            value += "]" * open_square
        return value

    @staticmethod
    def _parse_llm_report_json(content: str, source_text: str) -> tuple:
        """解析 LLM JSON；失败时修复，仍失败则返回降级报告。"""
        candidates = [content, VisualizationService._repair_json_text(content)]
        last_error: Optional[json.JSONDecodeError] = None
        for index, candidate in enumerate(candidates):
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    flags = {
                        "degraded": False,
                        "partial_recovery": index > 0,
                    }
                    return parsed, flags
            except json.JSONDecodeError as exc:
                last_error = exc
                continue
        logger.error("Chat 模型返回 JSON 无法解析，启用降级报告: %s", last_error)
        return VisualizationService._build_degraded_report(source_text), {
            "degraded": True,
            "partial_recovery": False,
        }

    @staticmethod
    def _build_degraded_report(source_text: str) -> Dict[str, Any]:
        """最小可渲染降级报告，保证接口可用。"""
        text = str(source_text or "").strip()
        excerpt = text[:500] if text else "（无输入文本）"
        title_text = excerpt[:48] + ("…" if len(excerpt) > 48 else "")
        return {
            "title": {"id": "1", "text": title_text or "研究报告（降级）"},
            "summary": {"id": "2", "text": excerpt},
            "kpis": [],
            "research_overview": {
                "id": "3",
                "question": "基于输入文本的核心问题（降级模式）",
                "scope": "仅基于用户输入，模型结构化输出失败后的最小报告。",
                "method": "基于输入文本进行归纳与结构化分析（降级模式）",
            },
            "key_findings": [],
            "sections": [],
            "mindmap": {"id": "6", "title": "知识结构", "nodes": []},
            "charts": [],
            "cross_section_insights": [],
            "conclusion": {
                "id": "8",
                "headline": "",
                "problem_analysis": "",
                "root_causes": "",
                "strategic_implications": "",
                "text": excerpt,
                "disclaimer": "本报告为 JSON 解析失败后的降级输出，分析深度有限。",
            },
            "outlook_trends": [],
            "recommendations": [],
            "sources": [],
            "warnings": ["degraded_report"],
        }

    @staticmethod
    def _merge_deepened_sections(
        original_sections: list, rewritten_sections: list
    ) -> list:
        """合并补强结果：锁定 title/summary/visual_refs，仅采纳分析层。"""
        orig_by_id = {
            str(sec.get("id")): sec
            for sec in (original_sections or [])
            if isinstance(sec, dict) and sec.get("id") is not None
        }
        merged = []
        analysis_keys = VisualizationService.SECTION_ANALYSIS_KEYS
        for rw in rewritten_sections or []:
            if not isinstance(rw, dict):
                continue
            sec_id = str(rw.get("id", ""))
            orig = orig_by_id.get(sec_id, {})
            merged_source_ids = []
            for sid in list(orig.get("used_source_ids") or []) + list(rw.get("used_source_ids") or []):
                sid = str(sid).strip()
                if sid and sid not in merged_source_ids:
                    merged_source_ids.append(sid)
            item = {
                "id": sec_id or orig.get("id", f"5.{len(merged) + 1}"),
                "title": orig.get("title", rw.get("title", "")),
                "summary": orig.get("summary", ""),
                "content": "",
                "evidence": [],
                "visual_refs": list(orig.get("visual_refs") or []),
                "used_source_ids": merged_source_ids,
            }
            for key in analysis_keys:
                value = rw.get(key) if isinstance(rw.get(key), str) else orig.get(key, "")
                item[key] = str(value or "").strip()
            merged.append(item)
        if merged:
            return merged
        return list(original_sections or [])

    @staticmethod
    def _infer_chart_data_confidence(
        chart: dict,
        source_text: str = "",
        web_search_context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """轻量图表可信度：verified / derived / unverified。"""
        model_value = str(chart.get("data_confidence") or "").strip().lower()
        if model_value in {"verified", "derived", "unverified"}:
            return model_value

        corpus_parts = [str(source_text or "")]
        if web_search_context:
            for src in web_search_context.get("sources") or []:
                if isinstance(src, dict):
                    corpus_parts.append(str(src.get("snippet") or ""))
                    corpus_parts.append(str(src.get("summary") or ""))
        corpus = "\n".join(corpus_parts)
        desc = " ".join(
            str(chart.get(key) or "")
            for key in ("title", "description", "chart_insight", "interpretation")
        )
        combined = desc + corpus
        derived_markers = ("预计", "预测", "有望", "推导", "估算", "forecast", "projected")
        if any(m in combined for m in derived_markers):
            return "derived"
        if any(m in desc for m in ("输入文本", "原文", "snippet", "来源")):
            return "verified"
        # 若图表数值中的整数在语料中出现，视为 verified
        data = chart.get("data") if isinstance(chart.get("data"), dict) else {}
        values = data.get("values") if isinstance(data.get("values"), list) else []
        for raw in values[:6]:
            num = re.sub(r"[^\d.]", "", str(raw))
            if num and num in re.sub(r"[^\d.]", "", corpus):
                return "verified"
        return "unverified"

    @staticmethod
    def _text_overlap_ratio(a: str, b: str) -> float:
        """基于字符二元组(shingle)的 Jaccard 重叠度，返回 0~1。

        相比单纯子串包含，可检出改写式/部分重复；对中文按字符切 bigram。
        完全子串包含直接判为 1.0。
        """
        a = re.sub(r"\s+", "", str(a or ""))
        b = re.sub(r"\s+", "", str(b or ""))
        if not a or not b:
            return 0.0
        short, long = (a, b) if len(a) <= len(b) else (b, a)
        if short in long:
            return 1.0
        if len(a) < 2 or len(b) < 2:
            return 1.0 if a == b else 0.0
        grams_a = {a[i:i + 2] for i in range(len(a) - 1)}
        grams_b = {b[i:i + 2] for i in range(len(b) - 1)}
        union = len(grams_a | grams_b)
        if not union:
            return 0.0
        return len(grams_a & grams_b) / union

    @staticmethod
    def _run_content_consistency_checks(parsed: Dict[str, Any], warnings: list) -> None:
        """轻量内容与一致性检查（非 NLP）。"""
        summary_text = ""
        if isinstance(parsed.get("summary"), dict):
            summary_text = str(parsed.get("summary", {}).get("text") or "")
        for finding in parsed.get("key_findings") or []:
            if not isinstance(finding, dict):
                continue
            insight = str(finding.get("insight") or "")
            if summary_text and VisualizationService._text_overlap_ratio(summary_text[:120], insight) >= 0.55:
                warnings.append(f"duplicate_summary_finding: {finding.get('id')}")
        for section in parsed.get("sections") or []:
            if not isinstance(section, dict):
                continue
            if not str(section.get("insight") or "").strip():
                warnings.append(f"missing_section_insight: {section.get('id')}")
        chart_ids = {
            str(c.get("id"))
            for c in (parsed.get("charts") or [])
            if isinstance(c, dict) and c.get("id") is not None
        }
        for section in parsed.get("sections") or []:
            if not isinstance(section, dict):
                continue
            for ref in section.get("visual_refs") or []:
                if str(ref) not in chart_ids:
                    continue
                if not str(section.get("interpretation") or "").strip():
                    warnings.append(f"weak_section_for_chart: {section.get('id')}->{ref}")
        for rec in parsed.get("recommendations") or []:
            if not isinstance(rec, dict):
                continue
            if not str(rec.get("rationale") or "").strip():
                warnings.append(f"missing_recommendation_rationale: {rec.get('id')}")

    WARNING_LEVEL_MAP = {
        "degraded_report": "error",
        "json_parse_failed": "error",
        "dropped_empty_chart": "error",
        "dropped_invalid_chart_type": "error",
        "sections_rewritten_for_depth": "warn",
        "partial_recovery": "warn",
        "missing_chart_insight": "warn",
        "missing_chart_interpretation": "warn",
        "missing_chart_description": "warn",
        "chart_data_unverified": "warn",
        "duplicate_summary_finding": "warn",
        "weak_section_for_chart": "warn",
        "missing_recommendation_rationale": "warn",
        "missing_section_insight": "warn",
        "source_marker_stripped": "info",
        "removed_orphan_source_markers": "info",
        "distributed_unused_web_sources": "info",
        "unused_web_sources": "info",
        "low_confidence_refs": "warn",
        "web_content_unreferenced": "warn",
        "weak_section_mechanism": "warn",
        "duplicate_section_layers": "warn",
        "web_search_disabled": "warn",
        "web_search_request_failed": "warn",
        "web_search_empty": "warn",
    }

    WARNING_MESSAGES = {
        "degraded_report": "报告以降级模式生成，分析深度可能受限。",
        "partial_recovery": "模型输出 JSON 曾不完整，已尝试自动修复。",
        "sections_rewritten_for_depth": "部分章节已经过自动分析补强。",
        "chart_data_unverified": "部分图表数据未完全确认，请结合来源谨慎解读。",
        "source_marker_stripped": "部分正文来源标记已被清理。",
        "removed_orphan_source_markers": "无 Web 来源时，已移除正文中的来源编号。",
        "distributed_unused_web_sources": "未引用的 Web 来源已分散补充到分析段落。",
        "unused_web_sources": "部分检索来源未写入报告正文。",
        "low_confidence_refs": "模型未主动标注引用，来源关联为系统启发式补全，请谨慎核对。",
        "web_content_unreferenced": "Web Search 来源未在结构化字段中引用。",
        "missing_chart_insight": "部分图表缺少洞察说明，已使用兜底文案。",
        "missing_section_insight": "部分章节缺少研究洞察。",
        "missing_recommendation_rationale": "部分建议缺少依据说明。",
        "web_search_disabled": "服务端未开启 Web Search（请在 .env 设置 WEB_SEARCH_ENABLED=true）。",
        "web_search_request_failed": "Web Search 请求失败，已按原文生成报告。",
        "web_search_empty": "Web Search 未返回有效结果，已按原文生成报告。",
    }

    @staticmethod
    def _warning_level(code: str) -> str:
        base = str(code or "").split(":", 1)[0]
        return VisualizationService.WARNING_LEVEL_MAP.get(base, "info")

    @staticmethod
    def _build_quality_issues(warnings: list, metadata: Dict[str, Any]) -> list:
        issues = []
        seen_codes = set()
        for item in warnings or []:
            code = str(item)
            base = code.split(":", 1)[0]
            message = VisualizationService.WARNING_MESSAGES.get(base, "")
            issues.append({
                "level": VisualizationService._warning_level(code),
                "code": code,
                "message": message,
            })
            seen_codes.add(base)
        if metadata.get("degraded") and "degraded_report" not in seen_codes:
            issues.append({
                "level": "error",
                "code": "degraded_report",
                "message": VisualizationService.WARNING_MESSAGES["degraded_report"],
            })
        if metadata.get("partial_recovery") and "partial_recovery" not in seen_codes:
            issues.append({
                "level": "warn",
                "code": "partial_recovery",
                "message": VisualizationService.WARNING_MESSAGES["partial_recovery"],
            })
        return issues

    @staticmethod
    def _quality_banner_messages(quality_issues: list, metadata: Dict[str, Any]) -> list:
        codes = {str(i.get("code", "")).split(":", 1)[0] for i in (quality_issues or [])}
        messages = []
        banner_map = {
            "degraded_report": "报告以降级模式生成，分析深度可能受限。",
            "sections_rewritten_for_depth": "部分章节已经过自动分析补强。",
            "chart_data_unverified": "部分图表数据为模型推导或未完全确认，请结合来源谨慎解读。",
            "source_marker_stripped": "部分正文来源标记已被清理。",
            "partial_recovery": "模型输出 JSON 曾不完整，已尝试自动修复。",
            "low_confidence_refs": "模型未主动标注引用，底部来源为系统启发式关联，请谨慎核对。",
            "web_content_unreferenced": "Web Search 来源未在报告中结构化引用。",
            "web_search_disabled": "服务端未开启 Web Search（请设置 WEB_SEARCH_ENABLED=true）。",
            "web_search_request_failed": "Web Search 请求失败，报告已按原文生成。",
            "web_search_empty": "Web Search 未返回有效结果，报告已按原文生成。",
        }
        if metadata.get("degraded"):
            messages.append(banner_map["degraded_report"])
        for code, text in banner_map.items():
            if code == "degraded_report":
                continue
            if code in codes or any(str(c).startswith(code) for c in codes):
                if text not in messages:
                    messages.append(text)
        if metadata.get("web_search_requested") and not metadata.get("web_search_enabled"):
            msg = "Web Search 未获得有效来源，报告已降级为纯文本分析。"
            if msg not in messages:
                messages.append(msg)
        return messages

    class _ChatResponse:
        """统一 requests 与 curl fallback 的响应形态。"""

        def __init__(self, status_code: int, text: str):
            self.status_code = status_code
            self.text = text

        def json(self) -> Dict[str, Any]:
            return json.loads(self.text)

    @staticmethod
    def _post_chat_completion(
        url: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ) -> "VisualizationService._ChatResponse":
        """调用 Chat Completions，requests 失败时可回退到 curl。"""
        retries = max(1, int(settings.chat_model_request_retries or 1))
        last_error: Optional[Exception] = None

        for attempt in range(1, retries + 1):
            try:
                response = requests.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=settings.chat_model_timeout,
                )
                return VisualizationService._ChatResponse(response.status_code, response.text)
            except requests.RequestException as exc:
                last_error = exc
                logger.warning(
                    "Chat 模型 requests 调用失败: attempt=%s/%s error=%s",
                    attempt,
                    retries,
                    exc.__class__.__name__,
                )
                if attempt < retries:
                    time.sleep(min(2 ** (attempt - 1), 3))

        if settings.chat_model_curl_fallback:
            logger.warning("Chat 模型 requests 连续失败，尝试 curl fallback: %s", url)
            return VisualizationService._post_chat_completion_with_curl(url, payload, headers)

        raise RuntimeError(f"Chat 模型连接失败: {last_error}")

    @staticmethod
    def _post_chat_completion_with_curl(
        url: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ) -> "VisualizationService._ChatResponse":
        body_path = ""
        try:
            fd, body_path = tempfile.mkstemp(prefix="chat-payload-", suffix=".json")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)

            cmd = [
                settings.chat_model_curl_path or "curl",
                "-sS",
                "--max-time",
                str(int(settings.chat_model_timeout or 120)),
                "--retry",
                "1",
                "--retry-delay",
                "1",
                "-X",
                "POST",
                url,
            ]
            for key, value in headers.items():
                cmd.extend(["-H", f"{key}: {value}"])
            cmd.extend(["--data-binary", f"@{body_path}"])

            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=int(settings.chat_model_timeout or 120) + 10,
            )
            if proc.returncode != 0:
                err = (proc.stderr or proc.stdout or "").strip()
                raise RuntimeError(f"curl fallback 调用失败: exit={proc.returncode} {err[:300]}")

            text = proc.stdout.strip()
            if not text:
                raise RuntimeError("curl fallback 调用失败: 空响应")

            status_code = 200
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict) and parsed.get("error"):
                    status_code = 500
            except json.JSONDecodeError:
                status_code = 502
            return VisualizationService._ChatResponse(status_code, text)
        finally:
            if body_path:
                try:
                    os.unlink(body_path)
                except OSError:
                    pass

    @staticmethod
    def _build_chat_url(base_url: str) -> str:
        """构造完整的 chat completions URL"""
        if base_url.endswith('/v1'):
            return f"{base_url}/chat/completions"
        elif not base_url.endswith('/chat/completions'):
            return base_url.rstrip('/') + '/v1/chat/completions'
        return base_url

    @staticmethod
    def _extract_json(content: str) -> str:
        """从 LLM 返回内容中提取 JSON 字符串"""
        content = content.strip()

        # 处理 ```json ... ``` 或 ``` ... ``` 包裹
        match = re.search(r'```(?:json)?\s*\n?([\s\S]*?)\n?```', content)
        if match:
            return match.group(1).strip()

        # 尝试找到顶层 JSON 对象
        if content.startswith('{'):
            depth = 0
            for i, ch in enumerate(content):
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        return content[:i + 1]

        return content

    @staticmethod
    def _normalize_standalone_mindmap(node: Any) -> Dict[str, Any]:
        """兼容模型将叶子节点返回为字符串的情况。"""
        if isinstance(node, str):
            return {"title": node, "children": []}
        if not isinstance(node, dict):
            return {"title": "", "children": []}

        title = node.get("title") or node.get("label") or node.get("text") or ""
        node["title"] = str(title)
        children = node.get("children")
        if isinstance(children, list):
            node["children"] = [
                VisualizationService._normalize_standalone_mindmap(child)
                for child in children
            ]
        elif children is None:
            node["children"] = []
        else:
            node["children"] = [
                VisualizationService._normalize_standalone_mindmap(children)
            ]
        return node

    @staticmethod
    def _add_ids_to_mindmap(node: Dict[str, Any], counter: list = None) -> None:
        """
        递归为 mindmap 的每个节点添加唯一 id 字段（原地修改）

        Args:
            node: 当前节点 dict，包含 title 和可选的 children
            counter: 用于生成递增 id 的计数器 [0]
        """
        if counter is None:
            counter = [0]

        counter[0] += 1
        node["id"] = counter[0]

        if "children" in node and isinstance(node.get("children"), list):
            for child in node["children"]:
                VisualizationService._add_ids_to_mindmap(child, counter)
