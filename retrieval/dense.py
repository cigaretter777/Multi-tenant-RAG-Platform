"""稠密向量召回器：真实 Milvus 客户端以依赖注入接入。"""
from typing import Any, Dict, List

from retrieval.base import RetrievalContext
from retrieval.candidates import Candidate


class DenseRetriever:
    name = "dense"

    def __init__(self, search_client):
        self.search_client = search_client

    async def retrieve(self, question: str, ctx: RetrievalContext) -> List[Candidate]:
        hits = await self.search_client.search(
            query=question,
            source=self.name,
            tenant_id=ctx.tenant_id,
            kb_ids=list(ctx.kb_ids),
            top_k=ctx.top_k,
        )
        return [self._to_candidate(hit, rank) for rank, hit in enumerate(hits, start=1)]

    def _to_candidate(self, hit: Dict[str, Any], rank: int) -> Candidate:
        return Candidate(
            chunk_id=hit["chunk_id"],
            document_id=hit["document_id"],
            kb_id=hit["kb_id"],
            text=hit["text"],
            source=self.name,
            score=hit["score"],
            file_name=hit.get("file_name", ""),
            page_number=hit.get("page_number"),
            image_refs=hit.get("image_refs", []),
            ranks={self.name: rank},
        )


class SparseRetriever(DenseRetriever):
    name = "sparse"
