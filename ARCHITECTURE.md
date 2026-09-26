# 架构说明

个人开源多租户 RAG 平台原型。已实现、已验证与仅设计的能力分别在 README 与本文件中标注。

## 分层

```
platform_api (v1 鉴权路由)          middleware (legacy 守卫)
        │                                    │
platform_auth (API Key → Principal)          │
        │                                    │
services (知识库业务 / 文档 / 查询 / 可视化)   │
        │
┌───────┴────────┬───────────────┬───────────────┐
ingestion        retrieval       answer          repositories
建库控制面        混合检索         生成与引用       控制面 SQL
└───────┬────────┴───────────────┴───────────────┘
utils (db / milvus / embedding / 存储)  +  外部模型服务
```

## 存储与事实源

- **PostgreSQL**：控制面与事实源（tenants / principals / api_keys / knowledge_bases /
  document_versions / ingestion_stages / 旧任务表）。Milvus 与 Neo4j 为可重建的派生数据。
- **Milvus**：稠密/稀疏向量索引；每条切片带 tenant_id 与 kb_id，检索强制双过滤。
- **Neo4j**：实体关系图谱（独立 GraphRAG 服务持有，主服务经 `utils/graphrag_client.py` 调用）。
- **对象存储/本地**：原文件与解析产物；canonical ParsedDocument 只解析一次，向量与图谱共用。

## 关键状态机

- 向量链：`uploaded → parsing → parsed → embedding → indexed`
- 图谱链：`parsed → graph_pending → graph_building → graph_ready`
- 删除链：`deleting → milvus → graph → artifacts → deleted`（每步幂等，失败停步记录 `failed_at:<step>`）

两链独立：图谱失败不阻断普通 RAG；删除失败不声称已删除；reconcile 周期重入队 stalled 版本。

## 检索流水线

```
鉴权与 KB 权限 → Query 改写 → 策略路由(auto/vector/hybrid/hybrid_graph)
→ 多路召回(bm25/dense/sparse/graph，graph 可降级) → 统一候选
→ RRF 融合(k=60，保留各源原始排名) → Reranker 精排 → Token 预算
→ 流式生成 → 引用校验([ref-N] 必须真实存在) → 拒答策略
```

## 安全模型

- 租户身份只来自服务端解析的 API Key（HMAC-SHA256 加盐摘要存储，raw key 仅打印一次）。
- 所有读路径 SQL 带 `tenant_id = $1`；跨租户与不存在的 KB 统一 403/404 语义，不可枚举。
- 旧 `/embedding/*` 接口默认 404（`LEGACY_API_ENABLED=false`）。
- 源码默认值不含任何凭据或私有网络地址；CI 级扫描命令见路线图门禁。

## 验证状态

- 单元测试：131+（fake 依赖覆盖控制面、建库、检索、生成、评测指标）。
- 需在线基础设施验证（未验证）：Milvus/Neo4j/PG 集成链路、真实 embedding/reranker
  的检索质量、检索消融实验（A–E，设计文档 §10.2）、压测 P50/P95。
  脚本与 compose 已备，结果产出后记录于 `benchmarks/`。
