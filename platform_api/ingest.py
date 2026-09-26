"""v1 建库与查询路由（设计文档 §6.1、§7.1）。

默认适配器为 dev 模式内存实现（retrieval.devstore + 抽取式 dev LLM）；
生产适配器（Milvus、PG 产物表、真实 embedding/reranker/LLM/GraphRAG）
通过依赖覆盖接入，路由与契约不变。
"""
import re
from typing import List
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from answer.generation import AnswerService
from ingestion.models import VersionKey
from ingestion.pipeline import ParsedDocument, PipelineDeps, run_parse_version
from ingestion.queues import QueueRegistry
from ingestion.repository import IngestionRepository
from platform_auth.dependencies import get_current_principal
from platform_auth.models import Principal
from repositories.control_plane import ControlPlaneRepository
from retrieval.base import RetrievalContext
from retrieval.bm25 import BM25Retriever
from retrieval.dense import DenseRetriever, SparseRetriever
from retrieval.devstore import DevStore, StoredChunk, bm25_loader_from, chunk_text, hash_embed
from retrieval.pipeline import RetrievalPipeline
from utils.db import DatabaseManager

router = APIRouter(tags=["platform-ingest"])

_dev_store = DevStore()
_queues = QueueRegistry()


class IngestDocument(BaseModel):
    text: str = Field(min_length=1)
    file_name: str = ""


class IngestRequest(BaseModel):
    kb_id: UUID
    documents: List[IngestDocument] = Field(min_length=1)


class QueryRequestV1(BaseModel):
    question: str = Field(min_length=1)
    kb_ids: List[UUID] = Field(min_length=1)
    strategy: str = "auto"
    top_k: int = 5


def get_dev_store() -> DevStore:
    return _dev_store


def get_queues() -> QueueRegistry:
    return _queues


def get_kb_repository() -> ControlPlaneRepository:
    return ControlPlaneRepository(DatabaseManager)


def get_ingestion_repository() -> IngestionRepository:
    return IngestionRepository(DatabaseManager)


def build_pipeline_deps(repo, queues, store, row_extras=None) -> PipelineDeps:
    async def parse(row):
        return ParsedDocument(
            document_id=UUID(str(row["document_id"])),
            tenant_id=UUID(str(row["tenant_id"])),
            kb_id=UUID(str(row["kb_id"])),
            text=row["text"],
        )

    async def store_parsed(parsed):
        return store.store_parsed(parsed)

    async def embed(row, parsed_id):
        parsed = store.parsed_documents[parsed_id]
        chunks = [
            StoredChunk(
                chunk_id=f"{parsed_id}:{i}",
                document_id=parsed["document_id"],
                kb_id=parsed["kb_id"],
                tenant_id=parsed["tenant_id"],
                text=piece,
                file_name=row.get("file_name", ""),
                embedding=hash_embed(piece),
            )
            for i, piece in enumerate(chunk_text(parsed["text"]))
        ]
        store.add_chunks(chunks)

    async def build_graph(row, parsed_id):
        return None

    return PipelineDeps(
        repository=repo,
        queues=queues,
        parse=parse,
        store_parsed=store_parsed,
        embed=embed,
        build_graph=build_graph,
    )


async def dev_llm_stream(question: str, context: str):
    """dev 模式生成：抽取首条证据并正确引用 [ref-1]（非生产答案质量）。"""
    match = re.search(r"\[ref-1\][^\n]*\n内容：(.*?)(\n\n|$)", context, re.S)
    snippet = match.group(1).strip() if match else ""
    yield f"根据知识库：{snippet} [ref-1]"


def get_answer_service() -> AnswerService:
    return AnswerService(dev_llm_stream)


@router.post("/ingest")
async def ingest(
    payload: IngestRequest,
    principal: Principal = Depends(get_current_principal),
    kb_repo=Depends(get_kb_repository),
    repo=Depends(get_ingestion_repository),
    store: DevStore = Depends(get_dev_store),
    queues: QueueRegistry = Depends(get_queues),
):
    kb = await kb_repo.get_knowledge_base(principal.tenant_id, payload.kb_id)
    if kb is None:
        raise HTTPException(status_code=403, detail="knowledge base unavailable")

    results = []
    for document in payload.documents:
        document_id = uuid4()
        key = VersionKey(principal.tenant_id, payload.kb_id, document_id, 1)
        version = await repo.start_version(key)
        row = {
            **version,
            "document_id": str(document_id),
            "tenant_id": str(principal.tenant_id),
            "kb_id": str(payload.kb_id),
            "text": document.text,
            "file_name": document.file_name,
            "graph_enabled": kb.get("graph_enabled", False),
        }
        deps = build_pipeline_deps(repo, queues, store)
        await run_parse_version(row, key, deps)
        queue = queues.get("embedding_queue")
        while queue.qsize():
            _, job = await queue.next()
            await job()
        updated = await repo.get_version(version["id"])
        results.append({"document_id": str(document_id), "vector_stage": updated["vector_stage"]})
    return {"results": results}


@router.post("/query")
async def query(
    payload: QueryRequestV1,
    principal: Principal = Depends(get_current_principal),
    kb_repo=Depends(get_kb_repository),
    store: DevStore = Depends(get_dev_store),
    service: AnswerService = Depends(get_answer_service),
):
    for kb_id in payload.kb_ids:
        if await kb_repo.get_knowledge_base(principal.tenant_id, kb_id) is None:
            raise HTTPException(status_code=403, detail="knowledge base unavailable")

    ctx = RetrievalContext(
        tenant_id=principal.tenant_id,
        kb_ids=tuple(str(kb) for kb in payload.kb_ids),
        top_k=payload.top_k,
    )
    pipeline = RetrievalPipeline(
        {
            "bm25": BM25Retriever(bm25_loader_from(store)),
            "dense": DenseRetriever(store),
            "sparse": SparseRetriever(store),
        }
    )
    result = await pipeline.retrieve(payload.question, ctx, strategy=payload.strategy)

    final = None
    async for event in service.stream(payload.question, result.candidates):
        final = event
    return {
        "answer": final.answer,
        "citations": final.citations,
        "refused": final.refused,
        "reason": final.reason,
        "trace_id": result.trace.trace_id,
    }
