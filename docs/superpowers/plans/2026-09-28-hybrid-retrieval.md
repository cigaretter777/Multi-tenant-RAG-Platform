# Phase 3: Configurable Hybrid Retrieval — Implementation Plan

**Spec:** `docs/superpowers/specs/2026-09-25-multi-tenant-rag-platform-design.md` §7
**Roadmap:** `docs/superpowers/plans/2026-09-25-platform-roadmap.md` Phase 3
**Predecessor:** Phase 2（`10ed37c..`，ingestion 控制面）

**Goal:** 把检索能力抽象为可配置流水线：租户/知识库强制过滤、多路召回、统一候选、RRF 融合、精排、Token 预算、检索追踪；首版交付 `vector` 与 `hybrid` 两策略并留消融钩子。

**Architecture:** 新增 `retrieval/` 包。所有召回器实现同一 `Retriever` 协议并强制接收 `RetrievalContext`（tenant_id + kb_ids + top_k）；Milvus/ES 等真实客户端以依赖注入接入，单测全部使用 fake。既有 `core/retriever.py` 的 naive/hybrid 实现由 `retrieval/adapters.py` 包装为 DenseRetriever（标记为待集成验证）。

## Global Constraints

- 统一候选结构：`chunk_id, document_id, kb_id, text, source, score, file_name, page_number, image_refs`；`source ∈ {bm25, dense, sparse, graph}`。
- 所有检索 SQL/DSL 必须同时带 `tenant_id == authenticated` 与 `kb_id IN authorized`（设计文档 §5.3）。
- 不同召回器原始分数不直接相加；融合只用 RRF：`RRF(d) = Σ 1/(k + rank_i(d))`。
- 精排与 Token 预算在融合之后；预算按估算 token 截断。
- 策略注册表支持消融：`vector` = 仅 dense；`hybrid` = bm25 + dense + sparse + RRF + reranker。

## Task 1: 候选模型与召回器协议 + 租户过滤

**Files:** `retrieval/__init__.py`, `retrieval/candidates.py`, `retrieval/base.py`, `tests/test_retrieval_base.py`
**Tests pin:** Candidate 字段完整；fake retriever 收到的 context 必含 tenant_id 与 kb_ids；缺 tenant 的 context 构造即抛错。

## Task 2: BM25 / dense / sparse 召回器（fake 客户端）

**Files:** `retrieval/bm25.py`, `retrieval/dense.py`, `retrieval/sparse.py`, `retrieval/adapters.py`, `tests/test_retrieval_retrievers.py`
**Tests pin:** BM25 对已知语料的排序；dense/sparse 把 client 返回映射为统一候选且保留 source；adapter 将过滤条件透传进 Milvus expr（字符串断言）。

## Task 3: RRF 融合与去重

**Files:** `retrieval/fusion.py`, `tests/test_retrieval_fusion.py`
**Tests pin:** 手算 RRF 数值（k=60，两路各 3 条含 1 条重叠）；重叠候选保留双来源与原始排名；去重按 chunk_id。

## Task 4: 精排、Token 预算与检索追踪

**Files:** `retrieval/rerank.py`, `retrieval/context_budget.py`, `retrieval/tracing.py`, `tests/test_retrieval_ranking.py`
**Tests pin:** reranker 重排顺序；预算截断不跨候选截半；trace 记录每路耗时/排名/融合参数与 trace_id。

## Task 5: 策略流水线（vector/hybrid）+ Query 改写钩子 + 验收

**Files:** `retrieval/pipeline.py`, `retrieval/query_rewrite.py`, `tests/test_retrieval_pipeline.py`, `README.md`
**Tests pin:** `vector` 策略只调用 dense；`hybrid` 调用三路并融合+精排+预算；改写器默认 identity、可注入；消融钩子=策略注册表按名字取组件集合。
**Gate:** 全量 pytest 绿；compileall retrieval；每 task 独立 commit；推送 main。
