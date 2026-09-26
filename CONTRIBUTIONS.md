# 个人贡献边界

## 复用内容（第三方/既有项目）

- `rag-system-master`：文档解析、向量化、旧任务状态与部分 GraphRAG 调用（本仓库主干前身）。
- `车书问答系统源码`：BM25/稠密/稀疏召回、RRF、Reranker 的检索思路与页码/图片引用范式。
- `graph-rag-master`：多租户知识图谱构建与 Local/Global/Hybrid 图检索（独立服务）。
- LLaMA-Factory / RAG-Retrieval：离线微调能力（仅训练期使用，非常驻服务）。
- 依赖库：FastAPI、Pydantic、asyncpg、pymilvus、LlamaIndex、NLTK 等（见 `LICENSES.md`）。

## 个人整合与新增

- 统一领域模型、v1 接口与错误语义（401/403/409 一致化）。
- 多租户认证授权与三层存储隔离（API Key 派生租户、SQL 双过滤、图谱 X-Tenant-ID）。
- 建库控制面：版本/阶段状态机、幂等键、有限重试、降级、删除补偿、一致性扫描。
- 可配置检索流水线：统一候选、RRF、精排、Token 预算、追踪、auto 路由与图谱降级。
- 流式生成、拒答与引用校验（[ref-N] 真实性验证）。
- 评测 harness、fixtures、指标与消融钩子；Docker Compose 可复现部署。
- 开源安全化：清除私有凭据与内网默认值、legacy 接口默认拒绝、bootstrap 一次性密钥。
