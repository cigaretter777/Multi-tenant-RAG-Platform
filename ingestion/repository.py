"""建库控制面仓储：版本行与阶段执行记录。

幂等键 = tenant_id + kb_id + document_id + document_version + stage；
阶段执行记录以 stage_key 为主键 Upsert，重复投递不产生重复行。
"""
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from ingestion.models import (
    TERMINAL_STAGES,
    Chain,
    GRAPH_TRANSITIONS,
    IllegalStageTransition,
    IngestionStage,
    VersionKey,
    VECTOR_TRANSITIONS,
)


class IngestionRepository:
    def __init__(self, database):
        self.database = database

    async def start_version(self, key: VersionKey) -> Dict[str, Any]:
        query = """
            INSERT INTO rag.document_versions (id, tenant_id, kb_id, document_id, version)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (tenant_id, kb_id, document_id, version) DO NOTHING
            RETURNING id, tenant_id, kb_id, document_id, version, vector_stage, graph_stage, status
        """
        row = await self.database.fetchrow(
            query, uuid4(), key.tenant_id, key.kb_id, key.document_id, key.version
        )
        if row is not None:
            return dict(row)
        existing = await self.database.fetchrow(
            """
            SELECT id, tenant_id, kb_id, document_id, version, vector_stage, graph_stage, status
            FROM rag.document_versions
            WHERE tenant_id = $1 AND kb_id = $2 AND document_id = $3 AND version = $4
            """,
            key.tenant_id, key.kb_id, key.document_id, key.version,
        )
        return dict(existing)

    async def get_version(self, version_id: UUID) -> Optional[Dict[str, Any]]:
        row = await self.database.fetchrow(
            """
            SELECT id, tenant_id, kb_id, document_id, version, vector_stage, graph_stage, status
            FROM rag.document_versions
            WHERE id = $1
            """,
            version_id,
        )
        return dict(row) if row else None

    async def advance(self, version_id: UUID, chain: Chain, to_stage: IngestionStage) -> Dict[str, Any]:
        current = await self.get_version(version_id)
        if current is None:
            raise IllegalStageTransition(f"unknown version {version_id}")
        if chain is Chain.VECTOR:
            from_stage = IngestionStage(current["vector_stage"])
            allowed = VECTOR_TRANSITIONS.get(from_stage, set())
            column = "vector_stage"
        else:
            raw = current["graph_stage"]
            from_stage = IngestionStage(raw) if raw else IngestionStage.PARSED
            allowed = GRAPH_TRANSITIONS.get(from_stage, set())
            column = "graph_stage"
        if to_stage not in allowed:
            raise IllegalStageTransition(f"{from_stage.value} -> {to_stage.value} on {chain.value}")
        await self.database.execute(
            f"UPDATE rag.document_versions SET {column} = $1, updated_at = NOW() WHERE id = $2",
            to_stage.value, version_id,
        )
        return {**current, column: to_stage.value}

    async def record_stage(
        self,
        version_id: UUID,
        stage_key: str,
        stage: IngestionStage,
        status: str,
        error: Optional[str] = None,
        degraded: Optional[str] = None,
    ) -> None:
        await self.database.execute(
            """
            INSERT INTO rag.ingestion_stages (stage_key, version_id, stage, status, error, degraded, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, NOW())
            ON CONFLICT (stage_key) DO UPDATE
            SET status = $4, error = $5, degraded = $6, updated_at = NOW()
            """,
            stage_key, version_id, stage.value, status, error, degraded,
        )

    async def attempt_stage(self, stage_key: str, max_attempts: int) -> bool:
        row = await self.database.fetchrow(
            """
            UPDATE rag.ingestion_stages
            SET attempts = attempts + 1, updated_at = NOW()
            WHERE stage_key = $1 AND attempts < $2
            RETURNING attempts
            """,
            stage_key, max_attempts,
        )
        return row is not None

    async def get_stage(self, stage_key: str) -> Optional[Dict[str, Any]]:
        row = await self.database.fetchrow(
            """
            SELECT stage_key, version_id, stage, status, attempts, error, degraded, updated_at
            FROM rag.ingestion_stages
            WHERE stage_key = $1
            """,
            stage_key,
        )
        return dict(row) if row else None

    async def list_stalled(self, older_than) -> List[Dict[str, Any]]:
        rows = await self.database.fetch(
            """
            SELECT id, tenant_id, kb_id, document_id, version, vector_stage, graph_stage, status, updated_at
            FROM rag.document_versions
            WHERE updated_at < $1 AND status = 'active' AND vector_stage <> 'indexed'
            """,
            older_than,
        )
        return [dict(row) for row in rows]

    async def list_deleting(self) -> List[Dict[str, Any]]:
        rows = await self.database.fetch(
            """
            SELECT id, tenant_id, kb_id, document_id, version, vector_stage, graph_stage, status, updated_at
            FROM rag.document_versions
            WHERE vector_stage = 'deleting' AND status = 'active'
            """,
        )
        return [dict(row) for row in rows]

    async def mark_deleted(self, version_id: UUID) -> None:
        await self.database.execute(
            "UPDATE rag.document_versions SET vector_stage = 'deleted', status = 'deleted', updated_at = NOW() WHERE id = $1",
            version_id,
        )
