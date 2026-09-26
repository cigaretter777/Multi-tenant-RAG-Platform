import unittest
from uuid import uuid4

from retrieval.base import RetrievalContext
from retrieval.candidates import Candidate
from retrieval.pipeline import STRATEGIES, RetrievalPipeline
from retrieval.rerank import ScoringReranker


def make_ctx(top_k=3):
    return RetrievalContext(tenant_id=uuid4(), kb_ids=(1,), top_k=top_k)


class StubRetriever:
    def __init__(self, name, chunks):
        self.name = name
        self.chunks = chunks
        self.calls = []

    async def retrieve(self, question, ctx):
        self.calls.append(question)
        return [
            Candidate(
                chunk_id=c, document_id="d", kb_id="k", text=f"{self.name}-{c}",
                source=self.name, score=0.5,
            )
            for c in self.chunks
        ]


def build_retrievers():
    return {
        "dense": StubRetriever("dense", ["a", "b"]),
        "bm25": StubRetriever("bm25", ["b", "c"]),
        "sparse": StubRetriever("sparse", ["c", "d"]),
    }


class RetrievalPipelineTest(unittest.IsolatedAsyncioTestCase):
    async def test_vector_strategy_only_calls_dense(self):
        retrievers = build_retrievers()
        pipeline = RetrievalPipeline(retrievers)

        result = await pipeline.retrieve("q", make_ctx(), strategy="vector")

        self.assertEqual(retrievers["dense"].calls, ["q"])
        self.assertEqual(retrievers["bm25"].calls, [])
        self.assertIsNone(result.trace.fusion_k)
        self.assertEqual(result.trace.stages, ["budget"])

    async def test_hybrid_strategy_fuses_reranks_and_budgets(self):
        retrievers = build_retrievers()

        async def score_fn(question, text):
            return 1.0 if text.endswith("-b") else 0.1

        pipeline = RetrievalPipeline(retrievers, reranker=ScoringReranker(score_fn), budget_tokens=1000)

        result = await pipeline.retrieve("q", make_ctx(), strategy="hybrid")

        self.assertEqual(result.candidates[0].chunk_id, "b")
        self.assertEqual(result.trace.stages, ["rrf", "rerank", "budget"])
        self.assertEqual(result.trace.fusion_k, 60)
        self.assertEqual(set(result.trace.sources), set(STRATEGIES["hybrid"]))

    async def test_query_rewriter_is_injectable(self):
        retrievers = build_retrievers()

        async def expand(question):
            return f"{question} 胎压"

        pipeline = RetrievalPipeline(retrievers, query_rewriter=expand)

        await pipeline.retrieve("报警", make_ctx(), strategy="vector")

        self.assertEqual(retrievers["dense"].calls, ["报警 胎压"])
