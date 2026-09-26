import unittest
from uuid import uuid4

from retrieval.base import RetrievalContext
from retrieval.candidates import Candidate


class CandidateModelTest(unittest.TestCase):
    def test_candidate_requires_known_source(self):
        with self.assertRaises(ValueError):
            Candidate(
                chunk_id="c1", document_id="d1", kb_id="k1",
                text="t", source="telepathy", score=0.5,
            )

    def test_candidate_keeps_citation_fields(self):
        candidate = Candidate(
            chunk_id="c1", document_id="d1", kb_id="k1", text="t",
            source="dense", score=0.9, file_name="manual.pdf", page_number=36,
        )
        self.assertEqual(candidate.page_number, 36)
        self.assertEqual(candidate.image_refs, [])


class RetrievalContextTest(unittest.TestCase):
    def test_context_requires_tenant_and_kbs(self):
        with self.assertRaises(ValueError):
            RetrievalContext(tenant_id=None, kb_ids=(1,))
        with self.assertRaises(ValueError):
            RetrievalContext(tenant_id=uuid4(), kb_ids=())

    async def _fake_retrieve(self, question, ctx):
        return ctx

    def test_retriever_receives_tenant_scoped_context(self):
        import asyncio

        ctx = RetrievalContext(tenant_id=uuid4(), kb_ids=(1, 2), top_k=3)
        received = asyncio.run(self._fake_retrieve("q", ctx))
        self.assertEqual(received.tenant_id, ctx.tenant_id)
        self.assertEqual(received.kb_ids, (1, 2))
