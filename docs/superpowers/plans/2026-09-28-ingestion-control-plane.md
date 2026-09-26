# Phase 2: Idempotent Ingestion Control Plane — Implementation Plan

**Spec:** `docs/superpowers/specs/2026-09-25-multi-tenant-rag-platform-design.md` §6
**Roadmap:** `docs/superpowers/plans/2026-09-25-platform-roadmap.md` Phase 2
**Predecessor:** Phase 1（`4003b58..da67a86`，88 tests green）

**Goal:** 把建库链路升级为带版本、阶段状态、幂等键、有限重试、降级与补偿的控制面；Milvus 与 GraphRAG 消费同一份解析产物。

**Architecture:** 新增 `ingestion/` 包（models / repository / queues / pipeline / deletion / reconciliation），PostgreSQL 为阶段状态事实源；队列首版为进程内优先级队列（接口预留 Redis 适配器）；不重构 `services/document_service.py` 的既有流程，仅在其状态边界插入阶段记录钩子。

**Tech Stack:** Python 3.10+, asyncio, asyncpg, pytest（unittest 风格，与 Phase 1 一致）。

## Global Constraints

- 幂等键：`tenant_id + kb_id + document_id + document_version + stage`；重复投递不得产生重复向量/实体/关系。
- 向量链路状态：`uploaded → parsing → parsed → embedding → indexed`；图谱链路：`parsed → graph_pending → graph_building → graph_ready`；两链独立，图谱失败不阻断普通 RAG。
- 可降级步骤：OCR / VL / GraphRAG；失败记录 `degraded` 原因并继续基础链路。
- 重试：有限次数指数退避；超限进入 `failed` 并保存结构化错误。
- 删除：`deleting → milvus → graph → artifacts → deleted`，每步幂等可重试；失败不声称已删除。
- 所有新模块以 fake 依赖单测；不要求本地起 Milvus/Neo4j/Redis。

## Task 1: 版本与阶段记录（models + migration + repository）

**Files:**
- Create: `ingestion/__init__.py`, `ingestion/models.py`, `ingestion/repository.py`
- Create: `migrations/002_ingestion.sql`
- Modify: `utils/db.py`（启动时执行 002 迁移）
- Create: `tests/test_ingestion_repository.py`

**Interfaces:**
- `IngestionStage` 枚举与合法转移表 `VECTOR_TRANSITIONS` / `GRAPH_TRANSITIONS`
- `IngestionRepository.start_version(...)`, `record_stage(key, stage, status, error=None)`, `get_stage(key, stage)`, `attempt_stage(key, stage, max_attempts) -> bool`, `list_stalled(older_than)`
- `record_stage` 以幂等键 Upsert；非法转移抛 `IllegalStageTransition`

**Tests pin:**
- 同一幂等键重复 `record_stage` 只有一行（fake db 记录 SQL 与参数）
- `parsing → indexed` 等非法转移抛错；`parsed → graph_pending` 合法
- `attempt_stage` 第 max_attempts+1 次返回 False

## Task 2: 优先级队列

**Files:**
- Create: `ingestion/queues.py`
- Create: `tests/test_ingestion_queues.py`

**Interfaces:**
- `QueueName`: parse / embedding / graph / cleanup
- `Priority`: online_answer > urgent_index > normal_ingest > graph_build
- `InProcessQueue.submit(priority, coro_factory)` / `next()`；在线问答不入建库队列

**Tests pin:** 出队顺序按优先级；graph 永远排在 normal_ingest 之后。

## Task 3: 统一解析产物与流水线编排（重试 + 降级）

**Files:**
- Create: `ingestion/pipeline.py`
- Create: `tests/test_ingestion_pipeline.py`

**Interfaces:**
- `ParsedDocument`（document_id/tenant_id/kb_id/text/pages/images/parser_version）
- `run_parse_version(version, deps)`：解析一次 → 存 canonical 产物 → 同产物入 embedding 与 graph 队列
- 可重试错误指数退避（deps.sleep 注入）；OCR/VL 失败记 `degraded` 继续；graph 失败不影响 indexed

**Tests pin:** embedding 与 graph 收到同一 `parsed_document_id`；重试次数与退避调用序列；VL 失败时 text 仍入库且 degraded 有记录。

## Task 4: 删除补偿与一致性扫描

**Files:**
- Create: `ingestion/deletion.py`, `ingestion/reconciliation.py`
- Create: `tests/test_ingestion_deletion.py`

**Interfaces:**
- `delete_version(version, deps)`：四步幂等；任一步失败停在该步并记录错误
- `reconcile(repo, queues, now)`：stalled 阶段与卡在 deleting 的版本重新入队

**Tests pin:** milvus 步骤失败后重跑从该步继续且不重复删除；reconcile 只重入队超过阈值的记录。

## Task 5: 阶段验收与状态文档（范围修订）

**修订记录（2026-09-28）：** 原计划在本任务向 `services/document_service.py` 插入 `record_stage`
钩子。执行时发现旧流程使用 BIGINT tenant/kb/file id，而控制面幂等键为 UUID 坐标；
强行桥接（uuid5 合成 id）会引入假集成并危及稳定旧链路。决策：**钩子推迟到 v1 建库 API
落地时与控制面原生接线**；本任务改为状态文档 + 阶段门禁。

**Files:**
- Modify: `README.md`（阶段状态表与接线说明）

**Gate:** `pytest tests -q` 全绿；`compileall ingestion`；敏感信息扫描无新增；独立 commit 每 task 一个。
