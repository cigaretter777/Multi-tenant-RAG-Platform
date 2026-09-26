from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from platform_api.knowledge_bases import get_knowledge_base_service
from platform_api.router import router
from platform_auth.dependencies import get_current_principal
from platform_auth.models import Principal
from services.knowledge_base_service import (
    KnowledgeBaseConflict,
    KnowledgeBaseForbidden,
)


class FakeKnowledgeBaseService:
    def __init__(self):
        self.rows = {}
        self.last_principal = None

    async def create(self, principal, name, graph_enabled):
        self.last_principal = principal
        if any(
            row["tenant_id"] == principal.tenant_id and row["name"] == name
            for row in self.rows.values()
        ):
            raise KnowledgeBaseConflict("knowledge base name already exists")
        row = {
            "id": uuid4(),
            "tenant_id": principal.tenant_id,
            "name": name,
            "graph_enabled": graph_enabled,
            "status": "active",
        }
        self.rows[row["id"]] = row
        return row

    async def list(self, principal):
        return [row for row in self.rows.values() if row["tenant_id"] == principal.tenant_id]

    async def get(self, principal, kb_id):
        row = self.rows.get(kb_id)
        if row is None or row["tenant_id"] != principal.tenant_id:
            raise KnowledgeBaseForbidden("knowledge base unavailable")
        return row


def build_client(principal, service):
    app = FastAPI()
    app.include_router(router, prefix="/v1")
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_knowledge_base_service] = lambda: service
    return TestClient(app)


def test_create_knowledge_base_uses_authenticated_tenant():
    principal = Principal(uuid4(), uuid4(), "developer")
    service = FakeKnowledgeBaseService()
    client = build_client(principal, service)

    response = client.post("/v1/knowledge-bases", json={"name": "manuals"})

    assert response.status_code == 201
    assert service.last_principal == principal
    assert response.json()["name"] == "manuals"


def test_list_returns_only_current_tenant_rows():
    principal_a = Principal(uuid4(), uuid4(), "a")
    principal_b = Principal(uuid4(), uuid4(), "b")
    service = FakeKnowledgeBaseService()
    client_a = build_client(principal_a, service)
    client_b = build_client(principal_b, service)

    client_a.post("/v1/knowledge-bases", json={"name": "manuals-a"})
    client_b.post("/v1/knowledge-bases", json={"name": "manuals-b"})

    response = client_a.get("/v1/knowledge-bases")

    assert response.status_code == 200
    assert [row["name"] for row in response.json()] == ["manuals-a"]


def test_get_foreign_and_missing_kb_return_same_403():
    principal_a = Principal(uuid4(), uuid4(), "a")
    principal_b = Principal(uuid4(), uuid4(), "b")
    service = FakeKnowledgeBaseService()
    client_a = build_client(principal_a, service)
    client_b = build_client(principal_b, service)
    foreign = client_b.post("/v1/knowledge-bases", json={"name": "manuals"}).json()

    for kb_id in (foreign["id"], str(uuid4())):
        response = client_a.get(f"/v1/knowledge-bases/{kb_id}")
        assert response.status_code == 403
        assert response.json()["detail"] == "knowledge base unavailable"


def test_duplicate_name_returns_409():
    principal = Principal(uuid4(), uuid4(), "developer")
    service = FakeKnowledgeBaseService()
    client = build_client(principal, service)

    client.post("/v1/knowledge-bases", json={"name": "manuals"})
    response = client.post("/v1/knowledge-bases", json={"name": "manuals"})

    assert response.status_code == 409


def test_missing_bearer_token_returns_401():
    app = FastAPI()
    app.include_router(router, prefix="/v1")
    client = TestClient(app)

    response = client.get("/v1/knowledge-bases")

    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"
