import unittest
from uuid import uuid4

from retrieval.adapters import build_milvus_expr
from retrieval.base import RetrievalContext
from retrieval.bm25 import BM25Retriever
from retrieval.dense import DenseRetriever, SparseRetriever


def make_ctx(top_k=3):
    return RetrievalContext(tenant_id=uuid4(), kb_ids=(1, 2), top_k=top_k)


CORPUS = [
    {"chunk_id": "c1", "document_id": "d1", "kb_id": 1, "text": "tire pressure warning light reset procedure"},
    {"chunk_id": "c2", "document_id": "d1", "kb_id": 1, "text": "engine oil change interval"},
    {"chunk_id": "c3", "document_id": "d2", "kb_id": 2, "text": "tire pressure sensor battery replacement"},
]


class BM25RetrieverTest(unittest.IsolatedAsyncioTestCase):
    async def test_bm25_ranks_term_overlap_first(self):
        async def loader(ctx):
            return CORPUS

        retriever = BM25Retriever(loader)
        results = await retriever.retrieve("tire pressure", make_ctx())

        # c1/c3 均含全部查询词，长度归一化使更短的 c3 领先；c2 无重叠垫底
        self.assertEqual([r.chunk_id for r in results], ["c3", "c1", "c2"])
        self.assertEqual(results[0].source, "bm25")
        self.assertEqual([r.ranks["bm25"] for r in results], [1, 2, 3])


class FakeSearchClient:
    def __init__(self):
        self.calls = []

    async def search(self, query, source, tenant_id, kb_ids, top_k):
        self.calls.append({"query": query, "source": source, "tenant_id": tenant_id, "kb_ids": kb_ids, "top_k": top_k})
        return [
            {"chunk_id": "c1", "document_id": "d1", "kb_id": 1, "text": "a", "score": 0.9, "page_number": 3},
            {"chunk_id": "c2", "document_id": "d1", "kb_id": 1, "text": "b", "score": 0.7},
        ]


class VectorRetrieverTest(unittest.IsolatedAsyncioTestCase):
    async def test_dense_maps_hits_and_keeps_source(self):
        client = FakeSearchClient()
        results = await DenseRetriever(client).retrieve("q", make_ctx())

        self.assertEqual([r.source for r in results], ["dense", "dense"])
        self.assertEqual(results[0].ranks, {"dense": 1})
        self.assertEqual(results[0].page_number, 3)

    async def test_sparse_uses_sparse_source(self):
        client = FakeSearchClient()
        results = await SparseRetriever(client).retrieve("q", make_ctx())

        self.assertEqual([r.source for r in results], ["sparse", "sparse"])
        self.assertEqual(client.calls[0]["source"], "sparse")


class MilvusAdapterTest(unittest.TestCase):
    def test_expr_always_carries_tenant_and_kb_filters(self):
        expr = build_milvus_expr(make_ctx())

        self.assertIn("tenant_id ==", expr)
        self.assertIn("kb_id in [1, 2]", expr)
