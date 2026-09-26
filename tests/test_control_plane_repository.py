import unittest
from uuid import uuid4

from repositories.control_plane import ControlPlaneRepository, DuplicateKnowledgeBaseName


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


class ControlPlaneRepositoryTest(unittest.IsolatedAsyncioTestCase):
    async def test_get_knowledge_base_always_scopes_by_tenant(self):
        db = FakeDatabase()
        repo = ControlPlaneRepository(db)
        tenant_id, kb_id = uuid4(), uuid4()

        await repo.get_knowledge_base(tenant_id, kb_id)

        _, sql, args = db.calls[0]
        self.assertIn("tenant_id = $1", sql)
        self.assertIn("id = $2", sql)
        self.assertEqual(args, (tenant_id, kb_id))

    async def test_same_name_conflict_becomes_domain_error(self):
        db = FakeDatabase()
        repo = ControlPlaneRepository(db)
        db.row = None

        with self.assertRaises(DuplicateKnowledgeBaseName):
            await repo.create_knowledge_base(uuid4(), "manuals", False)
