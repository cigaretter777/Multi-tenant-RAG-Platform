"""GraphRAG 召回：图谱服务输出归一化为统一候选；超时/失败抛 GraphUnavailable 供上层降级。"""
import asyncio
from typing import List

from retrieval.base import RetrievalContext
from retrieval.candidates import Candidate


class GraphUnavailable(Exception):
    """GraphRAG 超时、失败或图谱未就绪。"""


class GraphRAGRetriever:
    name = "graph"

    def __init__(self, client, timeout_seconds: float = 5.0):
        self.client = client
        self.timeout_seconds = timeout_seconds

    async def retrieve(self, question: str, ctx: RetrievalContext) -> List[Candidate]:
        try:
            hits = await asyncio.wait_for(
                self.client.query(
                    question=question,
                    tenant_id=ctx.tenant_id,
                    graph_ids=list(ctx.kb_ids),
                    top_k=ctx.top_k,
                ),
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise GraphUnavailable("graphrag timeout") from exc
        except Exception as exc:
            raise GraphUnavailable(f"graphrag error: {exc}") from exc

        return [
            Candidate(
                chunk_id=hit["chunk_id"],
                document_id=hit["document_id"],
                kb_id=hit["kb_id"],
                text=hit["text"],
                source=self.name,
                score=hit.get("score", 0.5),
                file_name=hit.get("file_name", ""),
                page_number=hit.get("page_number"),
                ranks={self.name: rank},
            )
            for rank, hit in enumerate(hits, start=1)
        ]
