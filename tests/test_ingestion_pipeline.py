import unittest
from uuid import uuid4

from ingestion.models import Chain, IngestionStage, VersionKey
from ingestion.pipeline import (
    ParsedDocument,
    PipelineDeps,
    RetryableError,
    run_graph_version,
    run_parse_version,
)
from ingestion.queues import QueueRegistry


class FakeRepo:
    def __init__(self):
        self.advances = []
        self.stages = {}
        self.attempts = {}

    async def advance(self, version_id, chain, to_stage):
        self.advances.append((chain, to_stage))

    async def record_stage(self, version_id, stage_key, stage, status, error=None, degraded=None):
        self.stages[stage_key] = {"status": status, "error": error, "degraded": degraded}

    async def attempt_stage(self, stage_key, max_attempts):
        used = self.attempts.get(stage_key, 0)
        if used >= max_attempts:
            return False
        self.attempts[stage_key] = used + 1
        return True


class FakeSleep:
    def __init__(self):
        self.delays = []

    async def __call__(self, delay):
        self.delays.append(delay)


def make_deps(**overrides):
    repo = FakeRepo()
    queues = QueueRegistry()
    sleeps = FakeSleep()
    state = {"parsed_ids": [], "embeds": [], "graphs": []}

    async def parse(row):
        return ParsedDocument(
            document_id=uuid4(), tenant_id=uuid4(), kb_id=uuid4(), text="body", images=["img.png"]
        )

    async def store_parsed(parsed):
        parsed_id = f"parsed-{len(state['parsed_ids']) + 1}"
        state["parsed_ids"].append(parsed_id)
        return parsed_id

    async def embed(row, parsed_id):
        state["embeds"].append(parsed_id)

    async def build_graph(row, parsed_id):
        state["graphs"].append(parsed_id)

    deps = PipelineDeps(
        repository=repo,
        queues=queues,
        parse=parse,
        store_parsed=store_parsed,
        embed=embed,
        build_graph=build_graph,
        sleep=sleeps,
        base_delay=1.0,
    )
    return repo, queues, sleeps, state, PipelineDeps(**{**deps.__dict__, **overrides})


def make_row(graph_enabled=True):
    return {"id": uuid4(), "graph_enabled": graph_enabled}


class IngestionPipelineTest(unittest.IsolatedAsyncioTestCase):
    async def test_embedding_and_graph_receive_same_parsed_document(self):
        repo, queues, sleeps, state, deps = make_deps()
        row = make_row(graph_enabled=True)
        key = VersionKey(uuid4(), uuid4(), uuid4(), 1)

        await run_parse_version(row, key, deps)
        embed_job = await queues.get("embedding_queue").next()
        graph_job = await queues.get("graph_queue").next()
        await embed_job[1]()
        await graph_job[1]()

        self.assertEqual(state["embeds"], state["graphs"])
        self.assertEqual(len(state["embeds"]), 1)
        self.assertIn((Chain.GRAPH, IngestionStage.GRAPH_PENDING), repo.advances)

    async def test_retry_uses_bounded_exponential_backoff(self):
        repo, queues, sleeps, state, deps = make_deps()
        calls = {"n": 0}

        async def flaky_parse(row):
            calls["n"] += 1
            if calls["n"] < 3:
                raise RetryableError("timeout")
            return ParsedDocument(document_id=uuid4(), tenant_id=uuid4(), kb_id=uuid4(), text="body")

        deps = PipelineDeps(**{**deps.__dict__, "parse": flaky_parse})
        row = make_row(graph_enabled=False)
        key = VersionKey(uuid4(), uuid4(), uuid4(), 1)

        await run_parse_version(row, key, deps)

        self.assertEqual(calls["n"], 3)
        self.assertEqual(sleeps.delays, [1.0, 2.0])

    async def test_max_attempts_marks_vector_chain_failed(self):
        repo, queues, sleeps, state, deps = make_deps()

        async def always_fail(row):
            raise RetryableError("timeout")

        deps = PipelineDeps(**{**deps.__dict__, "parse": always_fail})
        row = make_row(graph_enabled=False)
        key = VersionKey(uuid4(), uuid4(), uuid4(), 1)

        with self.assertRaises(RetryableError):
            await run_parse_version(row, key, deps)

        self.assertIn((Chain.VECTOR, IngestionStage.FAILED), repo.advances)
        stage = repo.stages[key.stage_key(IngestionStage.PARSING)]
        self.assertEqual(stage["status"], "failed")

    async def test_vl_failure_degrades_but_text_still_indexes(self):
        repo, queues, sleeps, state, deps = make_deps()

        async def bad_vl(parsed):
            raise RuntimeError("vl unavailable")

        deps = PipelineDeps(**{**deps.__dict__, "enrich_images": bad_vl})
        row = make_row(graph_enabled=False)
        key = VersionKey(uuid4(), uuid4(), uuid4(), 1)

        parsed = await run_parse_version(row, key, deps)
        embed_job = await queues.get("embedding_queue").next()
        await embed_job[1]()

        self.assertEqual(parsed.text, "body")
        self.assertEqual(len(state["embeds"]), 1)
        stage = repo.stages[key.stage_key(IngestionStage.PARSING)]
        self.assertIn("vl: vl unavailable", stage["degraded"])

    async def test_graph_failure_does_not_touch_vector_chain(self):
        repo, queues, sleeps, state, deps = make_deps()

        async def bad_graph(row, parsed_id):
            raise RuntimeError("graphrag down")

        deps = PipelineDeps(**{**deps.__dict__, "build_graph": bad_graph})
        row = make_row(graph_enabled=True)
        key = VersionKey(uuid4(), uuid4(), uuid4(), 1)

        await run_graph_version(row, key, "parsed-1", deps)

        self.assertIn((Chain.GRAPH, IngestionStage.FAILED), repo.advances)
        self.assertNotIn((Chain.VECTOR, IngestionStage.FAILED), repo.advances)
