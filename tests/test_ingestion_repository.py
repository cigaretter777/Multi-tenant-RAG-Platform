import unittest
from uuid import uuid4

from ingestion.models import Chain, IllegalStageTransition, IngestionStage, VersionKey
from ingestion.repository import IngestionRepository


class FakeDatabase:
    def __init__(self):
        self.calls = []
        self.row = None
        self.rows = []

    async def fetchrow(self, query, *args):
        self.calls.append(("fetchrow", query, args))
        return self.row

    async def fetch(self, query, *args):
        self.calls.append(("fetch", query, args))
        return self.rows

    async def execute(self, query, *args):
        self.calls.append(("execute", query, args))
        return None


def make_key():
    return VersionKey(tenant_id=uuid4(), kb_id=uuid4(), document_id=uuid4(), version=1)


class IngestionRepositoryTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = FakeDatabase()
        self.repo = IngestionRepository(self.db)
        self.version_id = uuid4()

    async def test_record_stage_upserts_by_idempotency_key(self):
        key = make_key()
        stage_key = key.stage_key(IngestionStage.PARSING)

        await self.repo.record_stage(self.version_id, stage_key, IngestionStage.PARSING, "running")
        await self.repo.record_stage(self.version_id, stage_key, IngestionStage.PARSING, "finish")

        inserts = [c for c in self.db.calls if c[0] == "execute"]
        self.assertEqual(len(inserts), 2)
        for _, sql, args in inserts:
            self.assertIn("ON CONFLICT (stage_key)", sql)
            self.assertEqual(args[0], stage_key)

    async def test_illegal_vector_transition_raises(self):
        self.db.row = {"id": self.version_id, "vector_stage": "uploaded", "graph_stage": None}

        with self.assertRaises(IllegalStageTransition):
            await self.repo.advance(self.version_id, Chain.VECTOR, IngestionStage.INDEXED)

    async def test_legal_vector_and_graph_transitions(self):
        self.db.row = {"id": self.version_id, "vector_stage": "uploaded", "graph_stage": None}
        await self.repo.advance(self.version_id, Chain.VECTOR, IngestionStage.PARSING)

        self.db.row = {"id": self.version_id, "vector_stage": "parsed", "graph_stage": None}
        await self.repo.advance(self.version_id, Chain.VECTOR, IngestionStage.EMBEDDING)
        await self.repo.advance(self.version_id, Chain.GRAPH, IngestionStage.GRAPH_PENDING)

        updates = [c for c in self.db.calls if c[0] == "execute"]
        self.assertEqual(len(updates), 3)

    async def test_attempt_stage_stops_at_max(self):
        key = make_key()
        stage_key = key.stage_key(IngestionStage.EMBEDDING)

        self.db.row = {"attempts": 1}
        self.assertTrue(await self.repo.attempt_stage(stage_key, 3))
        _, sql, args = self.db.calls[-1]
        self.assertIn("attempts < $2", sql)
        self.assertEqual(args, (stage_key, 3))

        self.db.row = None
        self.assertFalse(await self.repo.attempt_stage(stage_key, 3))
