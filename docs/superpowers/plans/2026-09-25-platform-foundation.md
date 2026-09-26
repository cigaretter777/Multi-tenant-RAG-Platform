# Platform Foundation and Tenant Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the copied RAG service into an open-source-safe, authenticated multi-tenant control plane with tenant-scoped knowledge-base APIs and legacy endpoints disabled by default.

**Architecture:** Keep the existing FastAPI service and add focused `platform_auth`, `platform_api`, `repositories`, and `services` modules rather than restructuring the whole application. PostgreSQL is the source of truth for tenants, API keys, and knowledge bases; API keys resolve the tenant server-side, and every knowledge-base operation passes that authenticated tenant explicitly.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic v2, pydantic-settings, asyncpg, PostgreSQL, unittest/pytest-compatible tests, HMAC-SHA256 API-key hashing.

**Spec:** `docs/superpowers/specs/2026-09-25-multi-tenant-rag-platform-design.md`

## Global Constraints

- The project is a personal open-source prototype; do not claim unverified production scale.
- Clients never supply their trusted `tenant_id`; the server derives it from an API key or JWT.
- Resource IDs created by the new control plane are UUIDs.
- PostgreSQL is the source of truth; Milvus and Neo4j remain derived stores.
- Cross-tenant access must not reveal whether a foreign knowledge base exists.
- Existing `/embedding/*` APIs remain compatibility code but are unavailable by default until migrated to server-derived tenant context.
- No credentials, private API keys, or private-network passwords may have non-empty source-code defaults.
- Use tests before implementation and keep each task independently reviewable.

## Review Focus

- Missing, malformed, unknown, disabled, or incorrectly signed API keys must all fail with HTTP 401 without revealing which check failed; Task 4 tests each class.
- A valid tenant-A key requesting a tenant-B or nonexistent knowledge base must receive the same HTTP 403 response; Task 5 pins both cases.
- Duplicate knowledge-base names within one tenant must fail with HTTP 409, while the same name in another tenant is valid; Task 3 repository tests and Task 5 service tests pin this.
- Private infrastructure values must not appear as executable defaults, and a clean environment must resolve only local-safe defaults; Task 1 tests this.
- Unauthenticated legacy `/embedding/*` endpoints must be unavailable when `LEGACY_API_ENABLED=false`; Task 6 tests the middleware boundary.

---

## File Structure

### New files

- `requirements-dev.txt` — development-only test dependencies.
- `platform_auth/__init__.py` — authentication package marker.
- `platform_auth/models.py` — immutable authenticated-principal model.
- `platform_auth/api_keys.py` — API-key generation, parsing, and HMAC verification.
- `platform_auth/service.py` — authentication orchestration against the repository.
- `platform_auth/dependencies.py` — FastAPI bearer-token dependency.
- `repositories/__init__.py` — repository package marker.
- `repositories/control_plane.py` — tenant, API-key, and knowledge-base SQL access.
- `services/knowledge_base_service.py` — tenant-scoped knowledge-base business rules.
- `platform_api/__init__.py` — platform API package marker.
- `platform_api/schemas.py` — v1 request and response models.
- `platform_api/knowledge_bases.py` — authenticated knowledge-base routes.
- `platform_api/router.py` — v1 router composition.
- `middleware/__init__.py` — middleware package marker.
- `middleware/legacy_api_guard.py` — default-deny guard for legacy endpoints.
- `migrations/001_control_plane.sql` — PostgreSQL control-plane schema.
- `scripts/bootstrap_tenant.py` — local tenant and one-time API-key bootstrap utility.
- `tests/test_settings_security.py` — clean-environment secret/default regression tests.
- `tests/test_api_keys.py` — key-format and signature tests.
- `tests/test_control_plane_repository.py` — exact SQL parameter and duplicate-name tests.
- `tests/test_authentication.py` — authentication failure-class tests.
- `tests/test_knowledge_base_service.py` — authorization and tenant-boundary tests.
- `tests/test_platform_api.py` — route, dependency, and legacy-guard tests.

### Modified files

- `configs/config.py` — safe defaults and auth/legacy settings.
- `.env.example` — documented local configuration without real credentials.
- `.gitignore` — stop ignoring `pyproject.toml`; ignore generated local secrets only.
- `api.py` — include the v1 router and legacy guard.
- `utils/db.py` — execute the control-plane migration during startup.
- `README.md` — document the platform identity and authenticated quick start.

## Task 1: Repository baseline and open-source-safe configuration

**Files:**
- Create: `requirements-dev.txt`
- Create: `tests/test_settings_security.py`
- Modify: `configs/config.py`
- Modify: `.env.example`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: existing `configs.config.Settings`.
- Produces: `Settings.api_key_pepper: str`, `Settings.legacy_api_enabled: bool`, and local-safe service defaults used by all later tasks.

- [ ] **Step 1: Initialize Git and record the copied baseline**

Run:

```bash
git init -b main
git add .
git commit -m "chore: import rag service baseline"
```

Expected: `git status --short` prints nothing. If Git identity is not configured, stop and ask the user to configure it; do not invent an identity.

- [ ] **Step 2: Add development test dependencies**

Create `requirements-dev.txt`:

```text
-r requirements.txt
pytest>=8.0,<9.0
pytest-asyncio>=0.23,<1.0
httpx>=0.27,<1.0
```

- [ ] **Step 3: Write the failing safe-default tests**

Create `tests/test_settings_security.py`:

```python
import unittest

from configs.config import Settings


class SettingsSecurityTest(unittest.TestCase):
    def test_clean_settings_use_local_infrastructure_and_no_passwords(self):
        settings = Settings(_env_file=None)

        self.assertEqual(settings.milvus_uri, "http://localhost:19530")
        self.assertEqual(settings.pg_host, "localhost")
        self.assertEqual(settings.milvus_password, "")
        self.assertEqual(settings.pg_password, "")
        self.assertEqual(settings.embedding_key, "")
        self.assertEqual(settings.api_key_pepper, "")

    def test_legacy_api_is_disabled_by_default(self):
        settings = Settings(_env_file=None)

        self.assertFalse(settings.legacy_api_enabled)
```

- [ ] **Step 4: Run the tests and verify the current defaults fail**

Run:

```bash
python -m pytest tests/test_settings_security.py -v
```

Expected: FAIL because private-network URLs/passwords are current defaults and the two new settings do not exist.

- [ ] **Step 5: Replace executable defaults with local-safe values**

In `configs/config.py`, add or replace the relevant `Settings` fields with:

```python
api_key_pepper: str = Field(default="", description="HMAC pepper for stored API-key digests")
legacy_api_enabled: bool = Field(default=False, description="Expose unauthenticated legacy /embedding APIs")

embedding_server: str = Field(default="http://localhost:8090/v1", description="Embedding service URL")
embedding_key: str = Field(default="", description="Embedding API key")
milvus_uri: str = Field(default="http://localhost:19530", description="Milvus URI")
milvus_user: str = Field(default="root", description="Milvus username")
milvus_password: str = Field(default="", description="Milvus password")
milvus_test_uri: str = Field(default="http://localhost:19530", description="Milvus test URI")
milvus_test_password: str = Field(default="", description="Milvus test password")
ocr_url: str = Field(default="http://localhost:31780/upload_pic", description="OCR service URL")
v2t_url: str = Field(default="http://localhost:30086/v2t", description="Audio transcription service URL")
domain_name: str = Field(default="http://localhost:8000", description="Public service base URL")
guard_url: str = Field(default="http://localhost:8020/llm08/preprocess", description="Guard service URL")
graphrag_base_url: str = Field(default="http://localhost:8001", description="GraphRAG service URL")
web_search_url: str = Field(default="http://localhost:31887/web_search", description="Web search service URL")
```

Keep the existing PostgreSQL field defaults at `pg_host="localhost"` and `pg_password=""`. Replace every remaining `10.140.*` or `10.141.*` executable default with its documented localhost port. Update `.env.example` to contain only localhost examples plus:

```text
API_KEY_PEPPER=replace-with-a-random-secret
LEGACY_API_ENABLED=false
```

Remove `pyproject.toml` from `.gitignore`; it is source configuration, not a generated secret.

- [ ] **Step 6: Run focused and existing regression tests**

Run:

```bash
python -m pytest tests/test_settings_security.py tests/test_deep_research_normalize.py tests/test_web_search_service.py tests/test_webpage_web_search.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add requirements-dev.txt tests/test_settings_security.py configs/config.py .env.example .gitignore
git commit -m "security: make default configuration safe for open source"
```

## Task 2: API-key identity model and cryptography

**Files:**
- Create: `platform_auth/__init__.py`
- Create: `platform_auth/models.py`
- Create: `platform_auth/api_keys.py`
- Create: `tests/test_api_keys.py`

**Interfaces:**
- Consumes: `Settings.api_key_pepper` from Task 1.
- Produces: `Principal`, `GeneratedApiKey`, `generate_api_key(pepper)`, `parse_api_key(raw_key)`, `verify_api_key(raw_key, expected_digest, pepper)`.

- [ ] **Step 1: Write failing API-key tests**

Create `tests/test_api_keys.py`:

```python
import unittest
from uuid import uuid4

from platform_auth.api_keys import generate_api_key, parse_api_key, verify_api_key
from platform_auth.models import Principal


class ApiKeyTest(unittest.TestCase):
    def test_generated_key_round_trips_and_verifies(self):
        generated = generate_api_key("test-pepper")

        parsed = parse_api_key(generated.raw_key)

        self.assertEqual(parsed.prefix, generated.prefix)
        self.assertTrue(verify_api_key(generated.raw_key, generated.digest, "test-pepper"))
        self.assertFalse(verify_api_key(generated.raw_key + "x", generated.digest, "test-pepper"))

    def test_malformed_keys_are_rejected(self):
        for value in ("", "Bearer x", "rag_short", "rag_bad_prefix_secret"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_api_key(value)

    def test_principal_is_tenant_scoped_and_immutable(self):
        principal = Principal(principal_id=uuid4(), tenant_id=uuid4(), name="local")

        with self.assertRaises(Exception):
            principal.name = "changed"
```

- [ ] **Step 2: Run the tests and verify imports fail**

Run: `python -m pytest tests/test_api_keys.py -v`

Expected: FAIL with `ModuleNotFoundError: platform_auth`.

- [ ] **Step 3: Implement the identity and key types**

Create `platform_auth/models.py`:

```python
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class Principal:
    principal_id: UUID
    tenant_id: UUID
    name: str
```

Create `platform_auth/api_keys.py` with these public types and signatures:

```python
from dataclasses import dataclass
import hashlib
import hmac
import secrets


@dataclass(frozen=True)
class ParsedApiKey:
    prefix: str
    secret: str


@dataclass(frozen=True)
class GeneratedApiKey:
    raw_key: str
    prefix: str
    digest: str


def _digest(prefix: str, secret: str, pepper: str) -> str:
    message = f"{prefix}:{secret}".encode()
    return hmac.new(pepper.encode(), message, hashlib.sha256).hexdigest()


def generate_api_key(pepper: str) -> GeneratedApiKey:
    prefix = secrets.token_hex(4)
    secret = secrets.token_urlsafe(32)
    raw_key = f"rag_{prefix}_{secret}"
    return GeneratedApiKey(raw_key, prefix, _digest(prefix, secret, pepper))


def parse_api_key(raw_key: str) -> ParsedApiKey:
    parts = raw_key.split("_", 2)
    if len(parts) != 3 or parts[0] != "rag" or len(parts[1]) != 8 or len(parts[2]) < 32:
        raise ValueError("invalid api key")
    int(parts[1], 16)
    return ParsedApiKey(prefix=parts[1], secret=parts[2])


def verify_api_key(raw_key: str, expected_digest: str, pepper: str) -> bool:
    try:
        parsed = parse_api_key(raw_key)
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(_digest(parsed.prefix, parsed.secret, pepper), expected_digest)
```

Create an empty `platform_auth/__init__.py`.

- [ ] **Step 4: Run the focused tests**

Run: `python -m pytest tests/test_api_keys.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add platform_auth tests/test_api_keys.py
git commit -m "feat: add tenant-scoped API key identities"
```

## Task 3: PostgreSQL control-plane schema and repository

**Files:**
- Create: `migrations/001_control_plane.sql`
- Create: `repositories/__init__.py`
- Create: `repositories/control_plane.py`
- Create: `tests/test_control_plane_repository.py`
- Modify: `utils/db.py`

**Interfaces:**
- Consumes: `DatabaseManager.fetch`, `fetchrow`, and `execute`.
- Produces: `ControlPlaneRepository.get_api_key_record(prefix)`, `create_knowledge_base(tenant_id, name, graph_enabled)`, `list_knowledge_bases(tenant_id)`, and `get_knowledge_base(tenant_id, kb_id)`.

- [ ] **Step 1: Write failing repository tests with a fake database**

Create `tests/test_control_plane_repository.py` with an async fake that records SQL and arguments. Pin these behaviors:

```python
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
```

- [ ] **Step 2: Run the repository tests and verify imports fail**

Run: `python -m pytest tests/test_control_plane_repository.py -v`

Expected: FAIL with `ModuleNotFoundError: repositories`.

- [ ] **Step 3: Add the control-plane migration**

Create `migrations/001_control_plane.sql` containing idempotent `CREATE TABLE IF NOT EXISTS` statements for:

```sql
CREATE TABLE IF NOT EXISTS rag.tenants (
    id UUID PRIMARY KEY,
    name VARCHAR(120) NOT NULL UNIQUE,
    status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS rag.principals (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES rag.tenants(id),
    name VARCHAR(120) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS rag.api_keys (
    id UUID PRIMARY KEY,
    principal_id UUID NOT NULL REFERENCES rag.principals(id),
    key_prefix CHAR(8) NOT NULL UNIQUE,
    key_digest CHAR(64) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS rag.knowledge_bases (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES rag.tenants(id),
    name VARCHAR(120) NOT NULL,
    graph_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled', 'deleting')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, name)
);

CREATE INDEX IF NOT EXISTS idx_principals_tenant ON rag.principals(tenant_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_bases_tenant ON rag.knowledge_bases(tenant_id);
```

- [ ] **Step 4: Implement the repository with tenant-scoped SQL**

Create `repositories/control_plane.py`. Its constructor accepts a database object exposing `fetch`, `fetchrow`, and `execute`. Convert asyncpg records to dictionaries before returning. `create_knowledge_base` generates `uuid4()` in Python and uses:

```sql
INSERT INTO rag.knowledge_bases (id, tenant_id, name, graph_enabled)
VALUES ($1, $2, $3, $4)
ON CONFLICT (tenant_id, name) DO NOTHING
RETURNING id, tenant_id, name, graph_enabled, status, created_at, updated_at
```

If no row returns, raise `DuplicateKnowledgeBaseName`. Every read must include `tenant_id` in the SQL predicate.

Implement `get_api_key_record(prefix)` with this join so authentication receives all three status values in one read:

```sql
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
```

- [ ] **Step 5: Execute migration content during database startup**

In `utils/db.py`, add:

```python
from pathlib import Path


async def apply_control_plane_migration() -> None:
    migration_path = Path(__file__).resolve().parents[1] / "migrations" / "001_control_plane.sql"
    await DatabaseManager.execute(migration_path.read_text(encoding="utf-8"))
```

Call it from `init_database()` after creating the `rag` schema and before returning success.

- [ ] **Step 6: Run the focused tests**

Run: `python -m pytest tests/test_control_plane_repository.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add migrations repositories tests/test_control_plane_repository.py utils/db.py
git commit -m "feat: add tenant control-plane repository"
```

## Task 4: Authentication service and FastAPI dependency

**Files:**
- Create: `platform_auth/service.py`
- Create: `platform_auth/dependencies.py`
- Create: `tests/test_authentication.py`

**Interfaces:**
- Consumes: `ControlPlaneRepository.get_api_key_record(prefix)` and Task 2 key helpers.
- Produces: `AuthenticationService.authenticate(raw_key) -> Principal` and `get_current_principal(credentials) -> Principal`.

- [ ] **Step 1: Write failing authentication tests**

Create `tests/test_authentication.py` with this fake repository and failure matrix:

```python
import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from platform_auth.api_keys import generate_api_key
from platform_auth.service import AuthenticationError, AuthenticationService


class FakeAuthRepository:
    def __init__(self, record):
        self.record = record

    async def get_api_key_record(self, prefix):
        if self.record and self.record["key_prefix"] == prefix:
            return self.record
        return None


class AuthenticationServiceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.generated = generate_api_key("pepper")
        self.record = {
            "key_prefix": self.generated.prefix,
            "key_digest": self.generated.digest,
            "key_status": "active",
            "principal_id": uuid4(),
            "principal_name": "developer",
            "principal_status": "active",
            "tenant_id": uuid4(),
            "tenant_status": "active",
            "expires_at": datetime.now(timezone.utc) + timedelta(days=1),
        }

    async def test_valid_key_returns_principal(self):
        service = AuthenticationService(FakeAuthRepository(self.record), "pepper")
        principal = await service.authenticate(self.generated.raw_key)
        self.assertEqual(principal.tenant_id, self.record["tenant_id"])

    async def test_unknown_prefix_is_unauthorized(self):
        service = AuthenticationService(FakeAuthRepository(None), "pepper")
        with self.assertRaisesRegex(AuthenticationError, "invalid credentials"):
            await service.authenticate(self.generated.raw_key)

    async def test_bad_signature_is_unauthorized(self):
        service = AuthenticationService(FakeAuthRepository(self.record), "wrong-pepper")
        with self.assertRaisesRegex(AuthenticationError, "invalid credentials"):
            await service.authenticate(self.generated.raw_key)

    async def test_inactive_or_expired_record_is_unauthorized(self):
        cases = (
            ("key_status", "disabled"),
            ("principal_status", "disabled"),
            ("tenant_status", "disabled"),
            ("expires_at", datetime.now(timezone.utc) - timedelta(seconds=1)),
        )
        for field, value in cases:
            with self.subTest(field=field):
                record = {**self.record, field: value}
                service = AuthenticationService(FakeAuthRepository(record), "pepper")
                with self.assertRaisesRegex(AuthenticationError, "invalid credentials"):
                    await service.authenticate(self.generated.raw_key)
```

Generate a real test key with `generate_api_key("pepper")`; do not hard-code a production-shaped secret. Assert every failure raises the same `AuthenticationError("invalid credentials")`.

- [ ] **Step 2: Run tests and verify they fail**

Run: `python -m pytest tests/test_authentication.py -v`

Expected: FAIL because `AuthenticationService` does not exist.

- [ ] **Step 3: Implement authentication orchestration**

Create `platform_auth/service.py`:

```python
class AuthenticationError(Exception):
    pass


class AuthenticationService:
    def __init__(self, repository, pepper: str):
        self.repository = repository
        self.pepper = pepper

    async def authenticate(self, raw_key: str) -> Principal:
        try:
            prefix = parse_api_key(raw_key).prefix
        except (TypeError, ValueError):
            raise AuthenticationError("invalid credentials")
        record = await self.repository.get_api_key_record(prefix)
        if not record or not self._record_is_active(record):
            raise AuthenticationError("invalid credentials")
        if not verify_api_key(raw_key, record["key_digest"], self.pepper):
            raise AuthenticationError("invalid credentials")
        return Principal(
            principal_id=record["principal_id"],
            tenant_id=record["tenant_id"],
            name=record["principal_name"],
        )

    @staticmethod
    def _record_is_active(record: dict) -> bool:
        if any(record[field] != "active" for field in (
            "key_status", "principal_status", "tenant_status"
        )):
            return False
        expires_at = record.get("expires_at")
        return expires_at is None or expires_at > datetime.now(timezone.utc)
```

- [ ] **Step 4: Implement the FastAPI bearer dependency**

Create `platform_auth/dependencies.py` using `HTTPBearer(auto_error=False)`. Missing credentials and every `AuthenticationError` must raise:

```python
HTTPException(
    status_code=401,
    detail="invalid credentials",
    headers={"WWW-Authenticate": "Bearer"},
)
```

Expose `get_authentication_service()` separately so tests can override it without a real database.

- [ ] **Step 5: Run focused tests**

Run: `python -m pytest tests/test_api_keys.py tests/test_authentication.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add platform_auth tests/test_authentication.py
git commit -m "feat: authenticate tenant API keys"
```

## Task 5: Tenant-scoped knowledge-base service and v1 API

**Files:**
- Create: `services/knowledge_base_service.py`
- Create: `platform_api/__init__.py`
- Create: `platform_api/schemas.py`
- Create: `platform_api/knowledge_bases.py`
- Create: `platform_api/router.py`
- Create: `tests/test_knowledge_base_service.py`
- Create: `tests/test_platform_api.py`

**Interfaces:**
- Consumes: `Principal`, `ControlPlaneRepository`, and `get_current_principal`.
- Produces: `POST /v1/knowledge-bases`, `GET /v1/knowledge-bases`, and `GET /v1/knowledge-bases/{kb_id}`.

- [ ] **Step 1: Write failing service authorization tests**

Create `tests/test_knowledge_base_service.py` with an in-memory fake that enforces uniqueness per tenant:

```python
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
```

The service signatures are:

```python
async def create(self, principal: Principal, name: str, graph_enabled: bool) -> dict
async def list(self, principal: Principal) -> list[dict]
async def get(self, principal: Principal, kb_id: UUID) -> dict
```

Define domain exceptions `KnowledgeBaseForbidden` and `KnowledgeBaseConflict`.

- [ ] **Step 2: Run tests and verify they fail**

Run: `python -m pytest tests/test_knowledge_base_service.py -v`

Expected: FAIL because the service is missing.

- [ ] **Step 3: Implement the minimal service**

Every repository call must use `principal.tenant_id`. When `get_knowledge_base` returns no row, raise `KnowledgeBaseForbidden("knowledge base unavailable")`. Convert `DuplicateKnowledgeBaseName` to `KnowledgeBaseConflict("knowledge base name already exists")`.

- [ ] **Step 4: Write failing API tests**

Create a small FastAPI test application in `tests/test_platform_api.py`, include `platform_api.router.router`, and override `get_current_principal` and `get_knowledge_base_service`:

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient

from platform_api.router import router
from platform_auth.dependencies import get_current_principal
from platform_auth.models import Principal
from platform_api.knowledge_bases import get_knowledge_base_service


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
```

Add equivalent concrete tests for:

```text
GET  /v1/knowledge-bases         -> 200 and only current-tenant rows
GET  /v1/knowledge-bases/{uuid}  -> 403 for both foreign and missing IDs
POST duplicate name             -> 409
missing bearer token            -> 401
```

- [ ] **Step 5: Implement schemas and routes**

In `platform_api/schemas.py`, define:

```python
class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    graph_enabled: bool = False


class KnowledgeBaseView(BaseModel):
    id: UUID
    name: str
    graph_enabled: bool
    status: Literal["active", "disabled", "deleting"]
```

Do not include `tenant_id` in request models. Routes translate domain exceptions to 403 and 409 and use `response_model` declarations.

- [ ] **Step 6: Run service and API tests**

Run:

```bash
python -m pytest tests/test_knowledge_base_service.py tests/test_platform_api.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add services/knowledge_base_service.py platform_api tests/test_knowledge_base_service.py tests/test_platform_api.py
git commit -m "feat: add tenant-scoped knowledge base APIs"
```

## Task 6: Legacy API guard and application integration

**Files:**
- Create: `middleware/__init__.py`
- Create: `middleware/legacy_api_guard.py`
- Modify: `api.py`
- Modify: `tests/test_platform_api.py`

**Interfaces:**
- Consumes: `Settings.legacy_api_enabled` and `platform_api.router.router`.
- Produces: mounted authenticated `/v1/*` APIs and default-denied `/embedding/*` compatibility routes.

- [ ] **Step 1: Add failing guard tests**

Extend `tests/test_platform_api.py` with an app that contains a fake `/embedding/query` endpoint and the real guard middleware. Assert:

```python
def test_legacy_api_is_hidden_when_disabled():
    response = client.post("/embedding/query", json={})
    assert response.status_code == 404


def test_legacy_api_can_be_enabled_explicitly():
    response = enabled_client.post("/embedding/query", json={})
    assert response.status_code == 200
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `python -m pytest tests/test_platform_api.py -v`

Expected: FAIL because the middleware does not exist.

- [ ] **Step 3: Implement the legacy guard**

Create `middleware/legacy_api_guard.py`:

```python
from starlette.responses import JSONResponse


class LegacyApiGuardMiddleware:
    def __init__(self, app, enabled: bool):
        self.app = app
        self.enabled = enabled

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] == "http" and path.startswith("/embedding/") and not self.enabled:
            response = JSONResponse({"detail": "not found"}, status_code=404)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
```

- [ ] **Step 4: Integrate v1 routing and the guard**

In `api.py`, after constructing `app`:

```python
from middleware.legacy_api_guard import LegacyApiGuardMiddleware
from platform_api.router import router as platform_router

app.add_middleware(LegacyApiGuardMiddleware, enabled=settings.legacy_api_enabled)
app.include_router(platform_router, prefix="/v1")
```

- [ ] **Step 5: Run all tests**

Run: `python -m pytest tests -v`

Expected: PASS, including all existing visualization regressions.

- [ ] **Step 6: Commit**

```bash
git add middleware api.py tests/test_platform_api.py
git commit -m "security: protect legacy APIs by default"
```

## Task 7: Tenant bootstrap utility and authenticated quick start

**Files:**
- Create: `scripts/bootstrap_tenant.py`
- Create: `tests/test_bootstrap_tenant.py`
- Modify: `README.md`
- Modify: `.env.example`

**Interfaces:**
- Consumes: `DatabaseManager`, `generate_api_key`, and `Settings.api_key_pepper`.
- Produces: `bootstrap_tenant(name, principal_name, repository, pepper) -> str`, returning the raw API key exactly once.

- [ ] **Step 1: Write the failing bootstrap test**

Create `tests/test_bootstrap_tenant.py` with a fake repository:

```python
class BootstrapTenantTest(unittest.IsolatedAsyncioTestCase):
    async def test_bootstrap_persists_only_digest_and_returns_raw_key_once(self):
        repository = FakeBootstrapRepository()

        raw_key = await bootstrap_tenant("demo", "developer", repository, "pepper")

        self.assertTrue(raw_key.startswith("rag_"))
        self.assertNotIn(raw_key, repr(repository.saved_record))
        self.assertEqual(len(repository.saved_record["key_digest"]), 64)
```

The fake exposes one method:

```python
async def create_tenant_principal_and_key(
    tenant_id, tenant_name, principal_id, principal_name,
    key_id, key_prefix, key_digest,
) -> None
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `python -m pytest tests/test_bootstrap_tenant.py -v`

Expected: FAIL because the bootstrap module is missing.

- [ ] **Step 3: Implement the transactional repository method**

Add `DatabaseManager.transaction()` as an async context manager that acquires one connection and opens `connection.transaction()`. Implement this exact repository interface using that same connection for the tenant, principal, and API-key inserts so partial bootstrap records cannot remain:

```python
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
```

- [ ] **Step 4: Implement the bootstrap function and CLI**

`bootstrap_tenant` generates UUIDs and one API key, stores only prefix/digest, and returns the raw key. The CLI accepts required `--tenant-name` and optional `--principal-name` arguments, initializes the database, prints the key once to stdout, and closes the database in `finally`.

- [ ] **Step 5: Document the authenticated quick start**

Update `README.md` with exact commands:

```bash
python scripts/bootstrap_tenant.py --tenant-name demo --principal-name developer
curl -H "Authorization: Bearer $RAG_API_KEY" http://localhost:8000/v1/knowledge-bases
```

State that the bootstrap key is shown once and must not be committed. Add all auth variables to `.env.example` with non-secret examples.

- [ ] **Step 6: Run the complete phase verification**

Run:

```bash
python -m pytest tests -v
python -m compileall platform_auth platform_api repositories services middleware scripts
rg -n "secAI|sk-[A-Za-z0-9]|10\.(140|141)\." configs .env.example README.md
```

Expected: all tests pass, compileall succeeds, and the secret/private-network scan produces no matches.

- [ ] **Step 7: Commit**

```bash
git add scripts tests/test_bootstrap_tenant.py repositories/control_plane.py utils/db.py README.md .env.example
git commit -m "feat: add reproducible tenant bootstrap"
```

## Final Phase-1 Verification

- [ ] Run `python -m pytest tests -v` and record the pass count.
- [ ] Run `python -m compileall platform_auth platform_api repositories services middleware scripts`.
- [ ] Run `git status --short` and confirm the worktree is clean.
- [ ] Run `git log --oneline --decorate -8` and verify the baseline plus seven focused commits are present.
- [ ] Confirm the v1 OpenAPI schema contains knowledge-base routes but no request schema with a trusted `tenant_id` field.
- [ ] Confirm `/embedding/query` returns 404 with default settings.
