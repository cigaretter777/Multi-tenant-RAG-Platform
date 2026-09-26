"""建库流水线编排：解析一次、双链消费；有限重试；可降级步骤。

- 向量链与图谱链消费同一份 canonical ParsedDocument（设计文档 §6.1）。
- 可重试错误按指数退避有限重试；超限进入 failed 并保存结构化错误。
- OCR/VL/GraphRAG 失败为可降级：记录 degraded 原因，基础链路继续。
"""
import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional
from uuid import UUID

from ingestion.models import Chain, IngestionStage, VersionKey
from ingestion.queues import Priority, QueueName, QueueRegistry


class RetryableError(Exception):
    """网络超时、模型服务暂时不可用等可重试错误。"""


class PermanentError(Exception):
    """文件损坏、不支持格式等不可重试错误。"""


@dataclass(frozen=True)
class ParsedDocument:
    document_id: UUID
    tenant_id: UUID
    kb_id: UUID
    text: str
    pages: List[Any] = field(default_factory=list)
    images: List[Any] = field(default_factory=list)
    parser_version: str = "v1"


@dataclass
class PipelineDeps:
    repository: Any
    queues: QueueRegistry
    parse: Callable[[Dict], Awaitable[ParsedDocument]]
    store_parsed: Callable[[ParsedDocument], Awaitable[str]]
    embed: Callable[[Dict, str], Awaitable[None]]
    build_graph: Callable[[Dict, str], Awaitable[None]]
    enrich_images: Optional[Callable[[ParsedDocument], Awaitable[None]]] = None
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    max_attempts: int = 3
    base_delay: float = 0.1


async def _with_retry(stage_key: str, deps: PipelineDeps, step: Callable[[], Awaitable[Any]], sleeps: List[float]) -> Any:
    attempt = 0
    while True:
        if not await deps.repository.attempt_stage(stage_key, deps.max_attempts):
            raise PermanentError(f"max attempts exceeded for {stage_key}")
        try:
            return await step()
        except RetryableError as exc:
            if attempt + 1 >= deps.max_attempts:
                raise
            delay = deps.base_delay * (2 ** attempt)
            sleeps.append(delay)
            await deps.sleep(delay)
            attempt += 1
        except PermanentError:
            raise


async def run_parse_version(version_row: Dict, key: VersionKey, deps: PipelineDeps) -> ParsedDocument:
    repo = deps.repository
    version_id = version_row["id"]
    sleeps: List[float] = []
    stage_key = key.stage_key(IngestionStage.PARSING)
    degraded_reason = None

    await repo.advance(version_id, Chain.VECTOR, IngestionStage.PARSING)
    await repo.record_stage(version_id, stage_key, IngestionStage.PARSING, "running")
    try:
        parsed = await _with_retry(stage_key, deps, lambda: deps.parse(version_row), sleeps)
        if deps.enrich_images is not None and parsed.images:
            try:
                await deps.enrich_images(parsed)
            except Exception as exc:  # VL/OCR 可降级
                degraded_reason = f"vl: {exc}"
                await repo.record_stage(
                    version_id, stage_key, IngestionStage.PARSING, "running", degraded=degraded_reason
                )
        parsed_document_id = await deps.store_parsed(parsed)
    except (RetryableError, PermanentError) as exc:
        await repo.record_stage(version_id, stage_key, IngestionStage.PARSING, "failed", error=str(exc))
        await repo.advance(version_id, Chain.VECTOR, IngestionStage.FAILED)
        raise

    await repo.record_stage(version_id, stage_key, IngestionStage.PARSING, "finish", degraded=degraded_reason)
    await repo.advance(version_id, Chain.VECTOR, IngestionStage.PARSED)

    await deps.queues.submit(
        QueueName.EMBEDDING,
        Priority.NORMAL_INGEST,
        lambda: deps.embed(version_row, parsed_document_id),
    )
    if version_row.get("graph_enabled"):
        await repo.advance(version_id, Chain.GRAPH, IngestionStage.GRAPH_PENDING)
        await deps.queues.submit(
            QueueName.GRAPH,
            Priority.GRAPH_BUILD,
            lambda: deps.build_graph(version_row, parsed_document_id),
        )
    return parsed


async def run_embed_version(version_row: Dict, key: VersionKey, parsed_document_id: str, deps: PipelineDeps) -> None:
    repo = deps.repository
    version_id = version_row["id"]
    sleeps: List[float] = []
    stage_key = key.stage_key(IngestionStage.EMBEDDING)

    await repo.advance(version_id, Chain.VECTOR, IngestionStage.EMBEDDING)
    await repo.record_stage(version_id, stage_key, IngestionStage.EMBEDDING, "running")
    try:
        await _with_retry(stage_key, deps, lambda: deps.embed(version_row, parsed_document_id), sleeps)
    except (RetryableError, PermanentError) as exc:
        await repo.record_stage(version_id, stage_key, IngestionStage.EMBEDDING, "failed", error=str(exc))
        await repo.advance(version_id, Chain.VECTOR, IngestionStage.FAILED)
        raise
    await repo.record_stage(version_id, stage_key, IngestionStage.EMBEDDING, "finish")
    await repo.advance(version_id, Chain.VECTOR, IngestionStage.INDEXED)


async def run_graph_version(version_row: Dict, key: VersionKey, parsed_document_id: str, deps: PipelineDeps) -> None:
    """图谱链独立于向量链：失败只影响图谱状态（设计文档 §6.4）。"""
    repo = deps.repository
    version_id = version_row["id"]
    stage_key = key.stage_key(IngestionStage.GRAPH_BUILDING)

    await repo.advance(version_id, Chain.GRAPH, IngestionStage.GRAPH_BUILDING)
    await repo.record_stage(version_id, stage_key, IngestionStage.GRAPH_BUILDING, "running")
    try:
        await deps.build_graph(version_row, parsed_document_id)
    except Exception as exc:
        await repo.record_stage(version_id, stage_key, IngestionStage.GRAPH_BUILDING, "failed", error=str(exc))
        await repo.advance(version_id, Chain.GRAPH, IngestionStage.FAILED)
        return
    await repo.record_stage(version_id, stage_key, IngestionStage.GRAPH_BUILDING, "finish")
    await repo.advance(version_id, Chain.GRAPH, IngestionStage.GRAPH_READY)
