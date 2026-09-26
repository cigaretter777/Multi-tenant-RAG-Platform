import unittest

from retrieval.candidates import Candidate
from retrieval.fusion import rrf_fusion


def cand(chunk_id, source, rank):
    return Candidate(
        chunk_id=chunk_id, document_id="d", kb_id="k", text=f"text-{chunk_id}",
        source=source, score=0.5, ranks={source: rank},
    )


class RrfFusionTest(unittest.TestCase):
    def test_hand_computed_rrf_with_overlap(self):
        dense = [cand("a", "dense", 1), cand("b", "dense", 2), cand("c", "dense", 3)]
        bm25 = [cand("b", "bm25", 1), cand("d", "bm25", 2), cand("e", "bm25", 3)]

        fused = rrf_fusion({"dense": dense, "bm25": bm25}, k=60, top_n=5)

        by_id = {c.chunk_id: c for c in fused}
        # b: 1/61 + 1/62；a: 1/61；d: 1/62 ...
        self.assertAlmostEqual(by_id["b"].score, 1 / 61 + 1 / 62)
        self.assertAlmostEqual(by_id["a"].score, 1 / 61)
        self.assertAlmostEqual(by_id["d"].score, 1 / 62)
        self.assertEqual(fused[0].chunk_id, "b")
        self.assertEqual(by_id["b"].ranks, {"dense": 2, "bm25": 1})

    def test_dedup_by_chunk_id_keeps_single_entry(self):
        dense = [cand("a", "dense", 1)]
        sparse = [cand("a", "sparse", 1)]

        fused = rrf_fusion({"dense": dense, "sparse": sparse}, k=60, top_n=5)

        self.assertEqual(len(fused), 1)
        self.assertEqual(sorted(fused[0].ranks), ["dense", "sparse"])

    def test_top_n_truncates(self):
        lists = {"dense": [cand(f"c{i}", "dense", i + 1) for i in range(10)]}

        fused = rrf_fusion(lists, k=60, top_n=3)

        self.assertEqual(len(fused), 3)
