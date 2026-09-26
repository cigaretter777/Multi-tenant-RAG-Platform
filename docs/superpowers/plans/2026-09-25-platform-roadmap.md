# Multi-tenant RAG Platform Delivery Roadmap

**Spec:** `docs/superpowers/specs/2026-09-25-multi-tenant-rag-platform-design.md`

The design spans five independently reviewable subsystems. Each phase gets its own TDD implementation plan and must leave the repository runnable before the next phase starts.

## Phase 1: Platform foundation and tenant isolation

- Initialize the open-source repository safely.
- Remove embedded credentials and private infrastructure defaults.
- Add tenants, API keys, knowledge bases, authentication, authorization, and protected v1 knowledge-base APIs.
- Disable unauthenticated legacy APIs by default.

Detailed plan: `docs/superpowers/plans/2026-09-25-platform-foundation.md`

## Phase 2: Idempotent ingestion control plane

- Add document versions and ingestion-stage records.
- Introduce parse, embedding, graph, and cleanup queues.
- Reuse one canonical parsed document for Milvus and GraphRAG.
- Add retries, idempotency keys, deletion compensation, and reconciliation.

## Phase 3: Configurable hybrid retrieval

- Add tenant-and-knowledge-base filtering to every retriever.
- Extract BM25, dense, sparse, RRF, and reranker capabilities behind common interfaces.
- Add query rewriting, token-budgeted context selection, and retrieval tracing.
- Ship `vector` and `hybrid` strategies with ablation hooks.

## Phase 4: GraphRAG routing, generation, and citations

- Add `graph` and `auto` strategy routing.
- Normalize GraphRAG output into the common candidate model.
- Add timeout, circuit-breaker, and hybrid fallback behavior.
- Add streaming generation, refusal behavior, citation construction, and citation validation.

## Phase 5: Evaluation, reproducible deployment, and open-source handoff

- Add the two-tenant, four-knowledge-base demo fixture.
- Add retrieval, answer, citation, refusal, fault-injection, and load evaluations.
- Add Docker Compose for PostgreSQL, Redis, Milvus, Neo4j, the API, and workers.
- Add `ARCHITECTURE.md`, `CONTRIBUTIONS.md`, `LICENSES.md`, benchmark reports, and release documentation.

## Phase gates

Every phase must meet all of these gates before the next phase begins:

1. Its focused tests pass.
2. The existing regression suite still passes.
3. No secret or private credential is committed.
4. New public interfaces are documented.
5. The phase is committed as independently reviewable changes.

