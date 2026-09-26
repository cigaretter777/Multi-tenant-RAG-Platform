import unittest

from eval.harness import run_retrieval_eval
from eval.fixtures import QUESTIONS
from eval.metrics import citation_accuracy, mrr, ndcg_at_k, recall_at_k, refusal_accuracy


class MetricsTest(unittest.TestCase):
    def test_recall_at_k_hand_computed(self):
        self.assertEqual(recall_at_k(["a", "b", "c"], ["b", "d"], 3), 0.5)
        self.assertEqual(recall_at_k(["a", "b", "c"], ["b", "d"], 1), 0.0)
        self.assertEqual(recall_at_k(["a"], [], 5), 0.0)

    def test_mrr_and_ndcg(self):
        self.assertEqual(mrr(["a", "b", "c"], ["b"]), 0.5)
        self.assertEqual(mrr(["a", "b"], ["z"]), 0.0)
        self.assertAlmostEqual(ndcg_at_k(["b", "a"], ["b"], 2), 1.0)

    def test_citation_and_refusal_accuracy(self):
        self.assertEqual(citation_accuracy(["ref-1", "ref-9"], ["ref-1", "ref-2"]), 0.5)
        self.assertEqual(citation_accuracy([], ["ref-1"]), 1.0)
        self.assertEqual(refusal_accuracy([True, False], [True, False]), 1.0)
        self.assertEqual(refusal_accuracy([True], [False]), 0.0)


class HarnessTest(unittest.IsolatedAsyncioTestCase):
    async def test_harness_reports_all_metrics(self):
        report = await run_retrieval_eval(QUESTIONS)

        self.assertEqual(set(report), {"recall@5", "recall@10", "mrr", "ndcg@5"})
        self.assertTrue(all(0.0 <= value <= 1.0 for value in report.values()))
        # 单文档事实题应被 BM25 代理召回命中
        self.assertGreater(report["recall@5"], 0.0)
