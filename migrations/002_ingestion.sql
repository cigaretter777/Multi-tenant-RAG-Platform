-- 建库控制面：文档版本与阶段执行记录（PostgreSQL 为事实源）
CREATE TABLE IF NOT EXISTS rag.document_versions (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    kb_id UUID NOT NULL,
    document_id UUID NOT NULL,
    version INT NOT NULL,
    vector_stage VARCHAR(20) NOT NULL DEFAULT 'uploaded',
    graph_stage VARCHAR(20),
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, kb_id, document_id, version)
);

CREATE TABLE IF NOT EXISTS rag.ingestion_stages (
    stage_key VARCHAR(255) PRIMARY KEY,
    version_id UUID NOT NULL REFERENCES rag.document_versions(id),
    stage VARCHAR(20) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    attempts INT NOT NULL DEFAULT 0,
    error TEXT,
    degraded TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_document_versions_stalled ON rag.document_versions(updated_at);
CREATE INDEX IF NOT EXISTS idx_ingestion_stages_updated ON rag.ingestion_stages(updated_at);
