import unittest
from uuid import uuid4

from platform_auth.models import Principal
from repositories.control_plane import DuplicateKnowledgeBaseName
from services.knowledge_base_service import (
    KnowledgeBaseConflict,
    KnowledgeBaseForbidden,
    KnowledgeBaseService,
)


class FakeKnowledgeBaseRepository:
    def __init__(self):
        self.rows = {}
        self.last_create_tenant_id = None

    async def create_knowledge_base(self, tenant_id, name, graph_enabled):
        self.last_create_tenant_id = tenant_id
        if any(row["tenant_id"] == tenant_id and row["name"] == name for row in self.rows.values()):
            raise DuplicateKnowledgeBaseName(name)
        row = {
            "id": uuid4(), "tenant_id": tenant_id, "name": name,
            "graph_enabled": graph_enabled, "status": "active",
        }
        self.rows[row["id"]] = row
        return row

    async def list_knowledge_bases(self, tenant_id):
        return [row for row in self.rows.values() if row["tenant_id"] == tenant_id]

    async def get_knowledge_base(self, tenant_id, kb_id):
        row = self.rows.get(kb_id)
        return row if row and row["tenant_id"] == tenant_id else None


class KnowledgeBaseServiceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.repo = FakeKnowledgeBaseRepository()
        self.service = KnowledgeBaseService(self.repo)
        self.tenant_a = Principal(uuid4(), uuid4(), "a")
        self.tenant_b = Principal(uuid4(), uuid4(), "b")

    async def test_create_injects_principal_tenant(self):
        await self.service.create(self.tenant_a, "manuals", False)
        self.assertEqual(self.repo.last_create_tenant_id, self.tenant_a.tenant_id)

    async def test_foreign_kb_and_missing_kb_raise_same_forbidden(self):
        foreign = await self.service.create(self.tenant_b, "manuals", False)
        for kb_id in (foreign["id"], uuid4()):
            with self.subTest(kb_id=kb_id):
                with self.assertRaisesRegex(KnowledgeBaseForbidden, "knowledge base unavailable"):
                    await self.service.get(self.tenant_a, kb_id)

    async def test_duplicate_name_raises_conflict(self):
        await self.service.create(self.tenant_a, "manuals", False)
        with self.assertRaises(KnowledgeBaseConflict):
            await self.service.create(self.tenant_a, "manuals", True)

    async def test_same_name_is_allowed_for_different_tenants(self):
        await self.service.create(self.tenant_a, "manuals", False)
        created = await self.service.create(self.tenant_b, "manuals", False)
        self.assertEqual(created["tenant_id"], self.tenant_b.tenant_id)
