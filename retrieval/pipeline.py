"""检索策略流水线：vector / hybrid（设计文档 §7.1-7.4）。

策略注册表即消融钩子：每个策略名映射到一组召回器与后处理阶段，
评测可按名字替换任意组件（RRF、Reranker、预算）。
"""
import time
import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional

from retrieval.base import RetrievalContext
from retrieval.candidates import Candidate
from retrieval.context_budget import select_within_budget
from retrieval.fusion import rrf_fusion
from retrieval.query_rewrite import identity_rewriter
from retrieval.rerank import PassthroughReranker
from retrieval.tracing import RetrievalTrace

STRATEGIES: Dict[str, tuple] = {
    "vector": ("dense",),
    "hybrid": ("bm25", "dense", "sparse"),
}


@dataclass
class RetrievalResult:
    candidates: List[Candidate]
    trace: RetrievalTrace


class RetrievalPipeline:
    def __init__(
        self,
        retrievers: Dict[str, object],
        reranker=None,
        budget_tokens: int = 2048,
        fusion_k: int = 60,
        query_rewriter=None,
    ):
        self.retrievers = retrievers
        self.reranker = reranker or PassthroughReranker()
        self.budget_tokens = budget_tokens
        self.fusion_k = fusion_k
        self.query_rewriter = query_rewriter or identity_rewriter

    async def retrieve(self, question: str, ctx: RetrievalContext, strategy: str = "hybrid") -> RetrievalResult:
        names = STRATEGIES[strategy]
        trace = RetrievalTrace(
            trace_id=uuid.uuid4().hex,
            question=question,
            strategy=strategy,
            fusion_k=self.fusion_k if len(names) > 1 else None,
        )
        rewritten = await self.query_rewriter(question)

        lists: Dict[str, List[Candidate]] = {}
        for name in names:
            started = time.perf_counter()
            lists[name] = await self.retrievers[name].retrieve(rewritten, ctx)
            trace.sources[name] = {
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                "count": len(lists[name]),
            }

        if len(names) > 1:
            ranked = rrf_fusion(lists, k=self.fusion_k, top_n=ctx.top_k * 3)
            trace.stages.append("rrf")
            ranked = await self.reranker.rerank(rewritten, ranked)
            trace.stages.append("rerank")
        else:
            ranked = list(lists[names[0]])

        final = select_within_budget(ranked, self.budget_tokens)
        trace.stages.append("budget")
        return RetrievalResult(candidates=final, trace=trace)
