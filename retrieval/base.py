"""召回器协议与检索上下文：租户/知识库过滤为构造期强制项（设计文档 §5.3）。"""
from dataclasses import dataclass
from typing import List, Protocol, Tuple
from uuid import UUID

from retrieval.candidates import Candidate


@dataclass(frozen=True)
class RetrievalContext:
    tenant_id: UUID
    kb_ids: Tuple
    top_k: int = 5

    def __post_init__(self):
        if self.tenant_id is None:
            raise ValueError("tenant_id is required for every retrieval")
        if not self.kb_ids:
            raise ValueError("kb_ids is required for every retrieval")


class Retriever(Protocol):
    name: str

    async def retrieve(self, question: str, ctx: RetrievalContext) -> List[Candidate]:
        ...
