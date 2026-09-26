from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ingestion.queues import QueueRegistry
from platform_api.ingest import (
    get_dev_store,
    get_ingestion_repository,
    get_kb_repository,
    get_queues,
)
from platform_api.router import router
from platform_auth.dependencies import get_current_principal
from platform_auth.models import Principal
from retrieval.devstore import DevStore


class FakeKbRepo:
    def __init__(self, allowed):
        self.allowed = allowed

    async def get_knowledge_base(self, tenant_id, kb_id):
        if (tenant_id, kb_id) in self.allowed:
            return {"id": kb_id, "tenant_id": tenant_id, "name": "kb", "graph_enabled": False, "status": "active"}
        return None


class FakeIngestionRepo:
    def __init__(self):
        self.versions = {}
        self.stages = {}
        self.attempts = {}

    async def start_version(self, key):
        version_id = uuid4()
        row = {
            "id": version_id, "tenant_id": key.tenant_id, "kb_id": key.kb_id,
            "document_id": key.document_id, "version": key.version,
            "vector_stage": "uploaded", "graph_stage": None, "status": "active",
        }
        self.versions[version_id] = row
        return dict(row)

    async def get_version(self, version_id):
        row = self.versions.get(version_id)
        return dict(row) if row else None

    async def advance(self, version_id, chain, to_stage):
        row = self.versions[version_id]
        column = "vector_stage" if chain.value == "vector" else "graph_stage"
        row[column] = to_stage.value
        return dict(row)

    async def record_stage(self, version_id, stage_key, stage, status, error=None, degraded=None):
        self.stages[stage_key] = {"status": status, "error": error, "degraded": degraded}

    async def attempt_stage(self, stage_key, max_attempts):
        used = self.attempts.get(stage_key, 0)
        if used >= max_attempts:
            return False
        self.attempts[stage_key] = used + 1
        return True

    async def get_stage(self, stage_key):
        return self.stages.get(stage_key)

    async def mark_deleted(self, version_id):
        self.versions[version_id]["status"] = "deleted"

    async def list_stalled(self, older_than):
        return []

    async def list_deleting(self):
        return []


def build_client(principal, kb_repo):
    app = FastAPI()
    app.include_router(router, prefix="/v1")
    repo = FakeIngestionRepo()
    store = DevStore()
    queues = QueueRegistry()
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_kb_repository] = lambda: kb_repo
    app.dependency_overrides[get_ingestion_repository] = lambda: repo
    app.dependency_overrides[get_dev_store] = lambda: store
    app.dependency_overrides[get_queues] = lambda: queues
    return TestClient(app)


def test_ingest_then_query_returns_cited_answer():
    principal = Principal(uuid4(), uuid4(), "developer")
    kb_id = uuid4()
    client = build_client(principal, FakeKbRepo({(principal.tenant_id, kb_id)}))

    ingest = client.post(
        "/v1/ingest",
        json={
            "kb_id": str(kb_id),
            "documents": [{"text": "胎压报警灯亮起时，请先停车检查四个轮胎的胎压。", "file_name": "手册.pdf"}],
        },
    )
    assert ingest.status_code == 200
    assert ingest.json()["results"][0]["vector_stage"] == "indexed"

    response = client.post(
        "/v1/query",
        json={"question": "胎压报警怎么办", "kb_ids": [str(kb_id)]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["refused"] is False
    assert "[ref-1]" in body["answer"]
    assert body["citations"][0]["ref_id"] == "ref-1"
    assert body["trace_id"]


def test_ingest_foreign_kb_is_403():
    principal = Principal(uuid4(), uuid4(), "developer")
    client = build_client(principal, FakeKbRepo(set()))

    response = client.post("/v1/ingest", json={"kb_id": str(uuid4()), "documents": [{"text": "x"}]})

    assert response.status_code == 403


def test_query_foreign_kb_is_403():
    principal = Principal(uuid4(), uuid4(), "developer")
    client = build_client(principal, FakeKbRepo(set()))

    response = client.post("/v1/query", json={"question": "q", "kb_ids": [str(uuid4())]})

    assert response.status_code == 403


def test_query_without_evidence_refuses():
    principal = Principal(uuid4(), uuid4(), "developer")
    kb_id = uuid4()
    client = build_client(principal, FakeKbRepo({(principal.tenant_id, kb_id)}))

    response = client.post("/v1/query", json={"question": "胎压报警怎么办", "kb_ids": [str(kb_id)]})

    assert response.status_code == 200
    assert response.json()["refused"] is True
