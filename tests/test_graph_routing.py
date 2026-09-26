import asyncio
import unittest
from uuid import uuid4

from retrieval.base import RetrievalContext
from retrieval.circuit import CircuitBreaker
from retrieval.graph import GraphRAGRetriever, GraphUnavailable
from retrieval.pipeline import RetrievalPipeline
from retrieval.router import QueryRouter, heuristic_classify


def make_ctx(top_k=3):
    return RetrievalContext(tenant_id=uuid4(), kb_ids=(1,), top_k=top_k)


class StubDense:
    name = "dense"

    async def retrieve(self, question, ctx):
        from retrieval.candidates import Candidate

        return [Candidate(chunk_id="d1", document_id="d", kb_id="k", text="dense text", source="dense", score=0.8)]


class StubEmpty:
    def __init__(self, name):
        self.name = name

    async def retrieve(self, question, ctx):
        return []


class SlowGraphClient:
    async def query(self, question, tenant_id, graph_ids, top_k):
        await asyncio.sleep(5)
        return []


class GoodGraphClient:
    async def query(self, question, tenant_id, graph_ids, top_k):
        return [
            {"chunk_id": "g1", "document_id": "d", "kb_id": 1, "text": "graph text", "score": 0.7}
        ]


class GraphRetrieverTest(unittest.IsolatedAsyncioTestCase):
    async def test_normalizes_graph_hits(self):
        retriever = GraphRAGRetriever(GoodGraphClient())

        results = await retriever.retrieve("q", make_ctx())

        self.assertEqual(results[0].source, "graph")
        self.assertEqual(results[0].ranks, {"graph": 1})

    async def test_timeout_becomes_graph_unavailable(self):
        retriever = GraphRAGRetriever(SlowGraphClient(), timeout_seconds=0.05)

        with self.assertRaises(GraphUnavailable):
            await retriever.retrieve("q", make_ctx())


class GraphDegradationTest(unittest.IsolatedAsyncioTestCase):
    async def test_graph_failure_keeps_hybrid_results(self):
        pipeline = RetrievalPipeline(
            {
                "dense": StubDense(),
                "bm25": StubEmpty("bm25"),
                "sparse": StubEmpty("sparse"),
                "graph": GraphRAGRetriever(SlowGraphClient(), 0.05),
            }
        )

        result = await pipeline.retrieve("q", make_ctx(), strategy="hybrid_graph")

        self.assertEqual([c.chunk_id for c in result.candidates], ["d1"])
        self.assertIn("error", result.trace.sources["graph"])
        self.assertIn("degraded:graph", result.trace.stages)


class CircuitBreakerTest(unittest.TestCase):
    def test_opens_after_threshold_and_half_opens_after_cooldown(self):
        now = {"t": 0.0}
        breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=10.0, clock=lambda: now["t"])

        breaker.record_failure()
        self.assertTrue(breaker.allow())
        breaker.record_failure()
        self.assertFalse(breaker.allow())

        now["t"] = 10.0
        self.assertTrue(breaker.allow())
        self.assertEqual(breaker.state, "half-open")

        breaker.record_success()
        self.assertEqual(breaker.state, "closed")


class RouterTest(unittest.TestCase):
    def test_relation_question_routes_to_graph(self):
        self.assertEqual(heuristic_classify("电池管理系统的组件之间有什么关系？"), "hybrid_graph")
        self.assertEqual(heuristic_classify("胎压报警后应该怎么办？"), "hybrid")

    def test_router_is_injectable(self):
        router = QueryRouter(classify=lambda q: "vector")
        self.assertEqual(router.route("anything"), "vector")
