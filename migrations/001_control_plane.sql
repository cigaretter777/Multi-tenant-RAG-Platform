-- 控制面 schema：租户、主体、API Key 与知识库（PostgreSQL 为事实源）
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
