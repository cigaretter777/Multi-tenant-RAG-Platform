import unittest
from uuid import uuid4

from answer.citations import build_context, used_refs, validate
from answer.generation import REFUSAL, AnswerService
from retrieval.candidates import Candidate


def make_candidates():
    return [
        Candidate(
            chunk_id="c1", document_id="d1", kb_id="k1", text="先检查四个轮胎的胎压",
            source="dense", score=0.9, file_name="用户手册.pdf", page_number=36,
        ),
        Candidate(
            chunk_id="c2", document_id="d1", kb_id="k1", text="再检查胎压传感器",
            source="dense", score=0.8, file_name="用户手册.pdf", page_number=37,
        ),
    ]


async def stream_tokens(*chunks):
    async def _llm(question, context):
        for chunk in chunks:
            yield chunk
    return _llm


class CitationsTest(unittest.TestCase):
    def test_build_context_numbers_refs_and_validate(self):
        context, citations = build_context(make_candidates())

        self.assertIn("[ref-1]", context)
        self.assertIn("第 36 页", context)
        self.assertEqual(sorted(citations), ["ref-1", "ref-2"])

        self.assertEqual(used_refs("答案 [ref-1] 与 [ref-2]"), ["ref-1", "ref-2"])
        self.assertEqual(validate("答案 [ref-1]", citations), [])
        self.assertEqual(validate("答案 [ref-9]", citations), ["ref-9"])


class AnswerServiceTest(unittest.IsolatedAsyncioTestCase):
    async def _collect(self, service, candidates):
        events = []
        async for event in service.stream("q", candidates):
            events.append(event)
        return events

    async def test_no_evidence_refuses(self):
        service = AnswerService(await stream_tokens("x"))

        events = await self._collect(service, [])

        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].refused)
        self.assertEqual(events[0].answer, REFUSAL)

    async def test_streamed_answer_with_valid_citation(self):
        service = AnswerService(await stream_tokens("请先检查胎压 ", "[ref-1]"))

        events = await self._collect(service, make_candidates())

        tokens = [e.token for e in events if e.token]
        self.assertEqual(tokens, ["请先检查胎压 ", "[ref-1]"])
        final = events[-1]
        self.assertFalse(final.refused)
        self.assertEqual([c["ref_id"] for c in final.citations], ["ref-1"])
        self.assertEqual(final.citations[0]["page_number"], 36)

    async def test_invalid_citation_becomes_refusal(self):
        service = AnswerService(await stream_tokens("见 [ref-9]"))

        events = await self._collect(service, make_candidates())

        final = events[-1]
        self.assertTrue(final.refused)
        self.assertIn("ref-9", final.reason)
        self.assertEqual(final.citations, [])
