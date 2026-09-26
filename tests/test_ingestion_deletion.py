import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from ingestion.deletion import DeletionDeps, delete_version
from ingestion.models import IngestionStage, VersionKey
from ingestion.queues import QueueName, QueueRegistry
from ingestion.reconciliation import reconcile


class FakeDeletionRepo:
    def __init__(self):
        self.stages = {}
        self.deleted = []

    async def get_stage(self, stage_key):
        return self.stages.get(stage_key)

    async def record_stage(self, version_id, stage_key, stage, status, error=None, degraded=None):
        self.stages[stage_key] = {"status": status, "error": error, "degraded": degraded}

    async def mark_deleted(self, version_id):
        self.deleted.append(version_id)


class FakeQueues:
    def __init__(self):
        self.submitted = []

    async def submit(self, queue, priority, job):
        self.submitted.append((queue, priority))


class IngestionDeletionTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.repo = FakeDeletionRepo()
        self.calls = []
        self.row = {"id": uuid4()}
        self.key = VersionKey(uuid4(), uuid4(), uuid4(), 1)

    def make_deps(self, fail_at=None):
        calls = self.calls

        def make_step(name):
            async def _step(row):
                calls.append(name)
                if fail_at == name:
                    raise RuntimeError(f"{name} unavailable")
            return _step

        return DeletionDeps(
            delete_milvus=make_step("milvus"),
            delete_graph=make_step("graph"),
            delete_artifacts=make_step("artifacts"),
        )

    async def test_milvus_failure_resumes_without_duplicate_delete(self):
        deps = self.make_deps(fail_at="graph")

        first = await delete_version(self.row, self.key, self.repo, deps)
        self.assertFalse(first)
        self.assertEqual(self.calls, ["milvus", "graph"])

        deps_ok = self.make_deps(fail_at=None)
        second = await delete_version(self.row, self.key, self.repo, deps_ok)

        self.assertTrue(second)
        self.assertEqual(self.calls, ["milvus", "graph", "graph", "artifacts"])
        self.assertEqual(self.repo.deleted, [self.row["id"]])

    async def test_reconcile_requeues_stalled_and_deleting(self):
        now = datetime.now(timezone.utc)
        old = now - timedelta(minutes=30)

        class Repo:
            async def list_stalled(self, older_than):
                Repo.cutoff = older_than
                return [{"id": uuid4(), "vector_stage": "parsing"}]

            async def list_deleting(self):
                return [{"id": uuid4(), "vector_stage": "deleting"}]

        queues = QueueRegistry()
        counts = await reconcile(Repo(), queues, now)

        self.assertEqual(counts, {"stalled": 1, "deleting": 1})
        self.assertEqual(queues.get(QueueName.PARSE).qsize(), 1)
        self.assertEqual(queues.get(QueueName.CLEANUP).qsize(), 1)
        self.assertEqual(queues.get(QueueName.GRAPH).qsize(), 0)
        self.assertEqual(Repo.cutoff, now - timedelta(minutes=15))
