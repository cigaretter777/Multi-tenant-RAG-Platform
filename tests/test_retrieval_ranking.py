import unittest

from retrieval.candidates import Candidate
from retrieval.context_budget import select_within_budget
from retrieval.rerank import PassthroughReranker, ScoringReranker
from retrieval.tracing import RetrievalTrace


def cand(chunk_id, text, score=0.5):
    return Candidate(
        chunk_id=chunk_id, document_id="d", kb_id="k", text=text,
        source="dense", score=score,
    )


class RerankerTest(unittest.IsolatedAsyncioTestCase):
    async def test_scoring_reranker_reorders_by_new_score(self):
        async def score_fn(question, text):
            return 1.0 if "relevant" in text else 0.1

        candidates = [cand("a", "noise"), cand("b", "relevant answer")]

        ranked = await ScoringReranker(score_fn).rerank("q", candidates)

        self.assertEqual([c.chunk_id for c in ranked], ["b", "a"])

    async def test_passthrough_keeps_order(self):
        candidates = [cand("a", "x"), cand("b", "y")]

        ranked = await PassthroughReranker().rerank("q", candidates)

        self.assertEqual([c.chunk_id for c in ranked], ["a", "b"])


class BudgetTest(unittest.TestCase):
    def test_budget_never_splits_a_candidate(self):
        candidates = [cand("a", "12345678"), cand("b", "12345678"), cand("c", "1234")]

        selected = select_within_budget(candidates, budget_tokens=4, tokenizer=lambda t: len(t) // 4)

        # 每条 2 token：a+b=4 刚好放满，c 再 +1 超预算 → 整条停止不截半
        self.assertEqual([c.chunk_id for c in selected], ["a", "b"])

    def test_budget_skips_nothing_when_room(self):
        candidates = [cand("a", "1234")]

        selected = select_within_budget(candidates, budget_tokens=10, tokenizer=lambda t: len(t) // 4)

        self.assertEqual(len(selected), 1)


class TraceTest(unittest.TestCase):
    def test_trace_records_sources_and_fusion(self):
        trace = RetrievalTrace(trace_id="t1", question="q", strategy="hybrid", fusion_k=60)
        trace.sources["dense"] = {"latency_ms": 12.0, "count": 3}
        trace.stages.extend(["rrf", "rerank", "budget"])

        self.assertEqual(trace.sources["dense"]["count"], 3)
        self.assertEqual(trace.stages, ["rrf", "rerank", "budget"])
