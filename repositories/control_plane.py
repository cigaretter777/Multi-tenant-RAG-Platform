"""租户控制面仓储：租户、API Key 与知识库的 SQL 访问。

所有读路径都必须带 tenant_id 谓词，跨租户访问在 service 层统一转为 Forbidden。
"""
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4


class DuplicateKnowledgeBaseName(Exception):
    """同一租户下知识库重名。"""


class ControlPlaneRepository:
    def __init__(self, database):
        self.database = database

    async def get_api_key_record(self, prefix: str) -> Optional[Dict[str, Any]]:
        query = """
            SELECT ak.key_prefix,
                   ak.key_digest,
                   ak.status AS key_status,
                   ak.expires_at,
                   p.id AS principal_id,
                   p.name AS principal_name,
                   p.status AS principal_status,
                   t.id AS tenant_id,
                   t.status AS tenant_status
            FROM rag.api_keys ak
            JOIN rag.principals p ON p.id = ak.principal_id
            JOIN rag.tenants t ON t.id = p.tenant_id
            WHERE ak.key_prefix = $1
        """
        row = await self.database.fetchrow(query, prefix)
        return dict(row) if row else None

    async def create_knowledge_base(
        self, tenant_id: UUID, name: str, graph_enabled: bool
    ) -> Dict[str, Any]:
        query = """
            INSERT INTO rag.knowledge_bases (id, tenant_id, name, graph_enabled)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (tenant_id, name) DO NOTHING
            RETURNING id, tenant_id, name, graph_enabled, status, created_at, updated_at
        """
        row = await self.database.fetchrow(query, uuid4(), tenant_id, name, graph_enabled)
        if row is None:
            raise DuplicateKnowledgeBaseName(name)
        return dict(row)

    async def list_knowledge_bases(self, tenant_id: UUID) -> List[Dict[str, Any]]:
        query = """
            SELECT id, tenant_id, name, graph_enabled, status, created_at, updated_at
            FROM rag.knowledge_bases
            WHERE tenant_id = $1
            ORDER BY created_at
        """
        rows = await self.database.fetch(query, tenant_id)
        return [dict(row) for row in rows]

    async def get_knowledge_base(self, tenant_id: UUID, kb_id: UUID) -> Optional[Dict[str, Any]]:
        query = """
            SELECT id, tenant_id, name, graph_enabled, status, created_at, updated_at
            FROM rag.knowledge_bases
            WHERE tenant_id = $1 AND id = $2
        """
        row = await self.database.fetchrow(query, tenant_id, kb_id)
        return dict(row) if row else None

    async def create_tenant_principal_and_key(
        self,
        tenant_id: UUID,
        tenant_name: str,
        principal_id: UUID,
        principal_name: str,
        key_id: UUID,
        key_prefix: str,
        key_digest: str,
    ) -> None:
        """单事务写入租户、主体与 API Key，避免留下半截 bootstrap 记录。"""
        async with self.database.transaction() as connection:
            await connection.execute(
                "INSERT INTO rag.tenants (id, name) VALUES ($1, $2)",
                tenant_id, tenant_name,
            )
            await connection.execute(
                "INSERT INTO rag.principals (id, tenant_id, name) VALUES ($1, $2, $3)",
                principal_id, tenant_id, principal_name,
            )
            await connection.execute(
                "INSERT INTO rag.api_keys (id, principal_id, key_prefix, key_digest) VALUES ($1, $2, $3, $4)",
                key_id, principal_id, key_prefix, key_digest,
            )
