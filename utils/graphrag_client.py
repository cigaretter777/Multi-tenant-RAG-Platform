"""GraphRAG 客户端 - 建图、进度查询、领域预设、图谱删除等对接"""
from typing import List, Dict, Any, Optional

import requests

from configs.config import settings
from utils.logger import get_logger

logger = get_logger()


def _graphrag_headers(tenant_id: int, graph_id: int) -> Dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-Tenant-ID": str(tenant_id),
        "X-Graph-ID": str(graph_id),
    }


def _parse_graphrag_response(response: requests.Response, action: str) -> Dict[str, Any]:
    if response.status_code == 403:
        detail = response.text
        try:
            detail = response.json().get("detail") or detail
        except Exception:
            pass
        logger.error(f"GraphRAG {action}失败 HTTP 403: {detail}")
        raise RuntimeError(f"GraphRAG {action}失败: 无权访问 ({detail})")

    if response.status_code != 200:
        logger.error(f"GraphRAG {action}失败 HTTP {response.status_code}: {response.text}")
        raise RuntimeError(f"GraphRAG {action}失败: HTTP {response.status_code}")

    body = response.json()
    if not body.get("success"):
        message = body.get("message") or body.get("detail") or "未知错误"
        logger.error(f"GraphRAG {action}失败: {message}")
        raise RuntimeError(f"GraphRAG {action}失败: {message}")

    return body.get("data") or {}


def normalize_domain_brief(domain_brief: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    规范化 domain_brief，兼容旧字段 description → domain_description
    """
    if not domain_brief:
        return None

    normalized = dict(domain_brief)
    if "domain_description" not in normalized and "description" in normalized:
        normalized["domain_description"] = normalized.pop("description")

    preset = normalized.get("preset")
    if preset is not None and preset not in (
        "general", "cyber_security", "medical", "legal", "finance"
    ):
        logger.warning(f"domain_brief.preset 非内置值: {preset}，将原样透传 GraphRAG")

    if normalized.get("strictness") is not None and normalized["strictness"] not in (
        "literal", "normal"
    ):
        logger.warning(
            f"domain_brief.strictness 非标准值: {normalized['strictness']}，将原样透传 GraphRAG"
        )

    return normalized


def process_text_files(
    tenant_id: int,
    graph_id: int,
    file_list: List[Dict[str, str]],
    domain_brief: Optional[Dict[str, Any]] = None,
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
) -> Dict[str, Any]:
    """
    提交文本建图任务到 GraphRAG（POST /api/text/process）

    tenant_id / graph_id 仅通过请求头传递，不出现在 body 中。
    """
    if not file_list:
        raise ValueError("file_list 不能为空")

    url = f"{settings.graphrag_base_url.rstrip('/')}/api/text/process"
    payload: Dict[str, Any] = {"file_list": file_list}

    effective_chunk_size = chunk_size if chunk_size is not None else settings.graphrag_chunk_size
    effective_chunk_overlap = (
        chunk_overlap if chunk_overlap is not None else settings.graphrag_chunk_overlap
    )
    payload["chunk_size"] = effective_chunk_size
    payload["chunk_overlap"] = effective_chunk_overlap

    normalized_brief = normalize_domain_brief(domain_brief)
    if normalized_brief:
        payload["domain_brief"] = normalized_brief

    logger.info(
        f"调用 GraphRAG 文本建图: tenant_id={tenant_id}, graph_id={graph_id}, "
        f"file_count={len(file_list)}, chunk_size={effective_chunk_size}, "
        f"chunk_overlap={effective_chunk_overlap}, "
        f"domain_brief={'yes' if normalized_brief else 'no'}"
    )

    response = requests.post(
        url,
        json=payload,
        headers=_graphrag_headers(tenant_id, graph_id),
        timeout=settings.graphrag_timeout,
    )
    return _parse_graphrag_response(response, "建图")


def get_text_progress(
    tenant_id: int,
    graph_id: int,
    graph_task_id: str,
) -> Dict[str, Any]:
    """
    查询 GraphRAG 文本建图进度（GET /api/text/progress/{task_id}）
    """
    if not graph_task_id:
        raise ValueError("graph_task_id 不能为空")

    url = f"{settings.graphrag_base_url.rstrip('/')}/api/text/progress/{graph_task_id}"

    response = requests.get(
        url,
        headers=_graphrag_headers(tenant_id, graph_id),
        timeout=settings.graphrag_timeout,
    )
    return _parse_graphrag_response(response, "进度查询")


def is_graph_build_complete(progress_data: Dict[str, Any]) -> bool:
    """GraphRAG 建图完成判定：status=completed 且 processed_files=total_files"""
    if progress_data.get("status") != "completed":
        return False
    total_files = progress_data.get("total_files")
    processed_files = progress_data.get("processed_files")
    if total_files is None or processed_files is None:
        return True
    return processed_files == total_files


def get_domain_presets(tenant_id: int, graph_id: int) -> Dict[str, Any]:
    """
    获取 GraphRAG 内置领域预设（GET /api/text/domain-presets）
    """
    url = f"{settings.graphrag_base_url.rstrip('/')}/api/text/domain-presets"

    response = requests.get(
        url,
        headers=_graphrag_headers(tenant_id, graph_id),
        timeout=settings.graphrag_timeout,
    )
    return _parse_graphrag_response(response, "领域预设查询")


def query_graph_context(
    tenant_id: int,
    graph_id: int,
    question: str,
    strategy: str = "mix",
    context: Optional[str] = None,
    return_context: bool = True,
) -> Dict[str, Any]:
    """
    图谱问答上下文检索（POST /api/query）

    rag-system 集成须 return_context=true，仅取实体/关系，不由 GraphRAG 生成最终答案。
    tenant_id / graph_id 仅通过请求头传递。
    """
    if not question:
        raise ValueError("question 不能为空")

    valid_strategies = ("local", "global", "mix")
    if strategy not in valid_strategies:
        raise ValueError(f"strategy 必须是 {valid_strategies} 之一")

    url = f"{settings.graphrag_base_url.rstrip('/')}/api/query"
    payload: Dict[str, Any] = {
        "question": question,
        "strategy": strategy,
        "return_context": return_context,
    }
    if context:
        payload["context"] = context

    logger.info(
        f"调用 GraphRAG 图谱查询: tenant_id={tenant_id}, graph_id={graph_id}, "
        f"strategy={strategy}, return_context={return_context}"
    )

    response = requests.post(
        url,
        json=payload,
        headers=_graphrag_headers(tenant_id, graph_id),
        timeout=settings.graphrag_timeout,
    )
    return _parse_graphrag_response(response, "图谱查询")


def delete_knowledge_by_files(
    tenant_id: int,
    graph_id: int,
    file_ids: List[str],
) -> Dict[str, Any]:
    """
    批量删除 GraphRAG 图谱中指定文件的贡献
    """
    if not file_ids:
        raise ValueError("file_ids 不能为空")

    url = f"{settings.graphrag_base_url.rstrip('/')}/api/knowledge/by-file"
    payload = {"file_ids": file_ids}

    logger.info(
        f"调用 GraphRAG 删除图谱: tenant_id={tenant_id}, graph_id={graph_id}, "
        f"file_ids={file_ids}"
    )

    response = requests.delete(
        url,
        json=payload,
        headers=_graphrag_headers(tenant_id, graph_id),
        timeout=settings.graphrag_timeout,
    )
    return _parse_graphrag_response(response, "删除")
