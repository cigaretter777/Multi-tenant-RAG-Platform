# 多租户混合检索与 GraphRAG 增强问答平台设计

## 1. 文档信息

- 日期：2026-09-25
- 状态：待用户书面审阅
- 项目性质：个人开源项目原型
- 主要求职方向：大模型应用算法、AI 搜索
- 辅助能力方向：大模型应用开发、后端工程、模型部署

## 2. 背景

现有代码由三个相互独立的项目组成：

1. `rag-system-master` 提供 FastAPI 接口、多格式文档解析、Embedding、Milvus 检索、PostgreSQL 任务状态，以及部分 GraphRAG 调用能力。
2. `车书问答系统源码` 提供汽车手册场景中的 Query 改写、BM25、稠密/稀疏召回、RRF、Reranker、页码和图片引用，以及离线模型训练能力。
3. `graph-rag-master` 提供多租户知识图谱构建、Neo4j 存储，以及 Local、Global、Hybrid、Mix 等图检索能力。

本项目不将三个仓库机械合并，而是以 `rag-system-master` 为平台主干，将车书项目中的通用检索能力抽象为可配置模块，并将 `graph-rag-master` 保持为独立内部服务。

汽车用户手册是首个垂直验证场景，同时增加技术文档知识库，证明平台不存在汽车领域硬编码。

## 3. 目标与非目标

### 3.1 目标

- 支持多个租户，每个租户拥有多个独立知识库。
- 支持文档上传、解析、切片、Embedding、向量索引和可选 GraphRAG 建图。
- 支持 BM25、稠密向量、稀疏向量和 GraphRAG 召回。
- 支持 RRF 融合、Reranker 精排和基于 Token 预算的上下文选择。
- 支持流式回答、拒答和文件、页码、图片、切片级引用溯源。
- 支持异步建库、幂等执行、有限重试、故障降级和最终一致性补偿。
- 提供 Docker Compose 可复现部署、自动化测试、检索评测和单机压测。
- 明确第三方代码、已有能力和个人新增贡献的边界。

### 3.2 非目标

- 不声称具备数百真实租户或互联网规模流量。
- 不在首版实现多地域容灾、商业计费或复杂组织权限体系。
- 不在首版实现 Kubernetes GPU 自动扩缩容。
- 不要求重新训练所有 Embedding、Reranker 和 LLM。
- 不将 LLaMA-Factory 和 RAG-Retrieval 作为线上常驻服务。

## 4. 总体架构

采用“模块化主服务加独立重资源服务”的结构。

### 4.1 平台主服务

`rag-system-master` 负责：

- API Key 或 JWT 鉴权。
- 租户、知识库、文档、任务和策略管理。
- 文档建库任务编排。
- Query 理解和检索策略路由。
- 多路召回、结果标准化、融合、精排和上下文构建。
- LLM 问答、流式输出、引用校验和查询追踪。

### 4.2 图谱服务

`graph-rag-master` 保持独立部署：

- 接收主服务解析后的标准文本，避免重复解析原文件。
- 使用 `X-Tenant-ID` 和 `X-Graph-ID` 隔离数据。
- 负责实体关系抽取、知识融合、Neo4j 写入和图谱查询。
- 超时或失败时不阻断普通 RAG 链路。

一个知识库对应一个图谱空间：`graph_id = kb_id`。

### 4.3 模型服务

Embedding、Reranker 和生成 LLM 以独立模型服务部署。线上服务只消费训练产出的模型权重：

- LLaMA-Factory 用于离线微调生成模型。
- RAG-Retrieval 用于离线训练或微调 Embedding 和 Reranker。
- 在线侧使用轻量推理封装或 OpenAI 兼容模型接口。

### 4.4 存储

- PostgreSQL：控制面和事实数据源。
- Milvus：向量与稀疏索引。
- Neo4j：实体和关系图谱。
- Redis：任务队列、限流和短期状态缓存。
- 对象存储：原文件、解析文本、图片和其他解析产物。

Milvus 与 Neo4j 都是可以根据 PostgreSQL 状态和对象存储内容重建的派生数据。

## 5. 数据模型与租户隔离

### 5.1 核心实体

- `Tenant`：租户、状态、配额。
- `Principal`：用户或 API Key，只属于一个租户。
- `KnowledgeBase`：知识库、启用状态、默认策略和 GraphRAG 开关。
- `Document`：文件元数据、版本及各阶段状态。
- `Chunk`：切片及页码、图片、标题路径等引用信息。
- `IngestionTask`：解析、Embedding、建图和清理任务。
- `ModelBinding`：知识库使用的模型和版本。
- `RetrievalPolicy`：召回渠道、Top-K、融合、精排和图谱参数。

所有资源使用全局 UUID：

```text
tenant_id
kb_id
document_id
chunk_id
task_id
```

### 5.2 身份来源

客户端不能通过请求正文声明自身租户。服务端从 API Key 或 JWT 中解析 `tenant_id`，然后验证请求中的 `kb_id` 是否属于该租户。

### 5.3 存储隔离

Milvus 每条切片至少包含：

```text
tenant_id
kb_id
document_id
chunk_id
file_name
page_number
text
embedding_model_version
```

所有检索必须同时使用租户和知识库过滤：

```text
tenant_id == authenticated_tenant
AND kb_id IN authorized_kb_ids
```

GraphRAG 请求统一使用：

```text
X-Tenant-ID = tenant_id
X-Graph-ID  = kb_id
```

任何跨租户访问返回 `403 Forbidden`，不存在和无权限的知识库对外采用一致错误语义，避免通过错误信息枚举资源。

## 6. 文档建库链路

### 6.1 标准流程

```text
上传文件
→ 保存原文件与 Document 记录
→ 创建 IngestionTask
→ 文档解析/OCR/VL
→ 生成 ParsedDocument
├── 切片、Embedding、写入 Milvus
└── 按知识库配置提交 GraphRAG 建图
```

统一解析产物包含：

```json
{
  "document_id": "uuid",
  "tenant_id": "uuid",
  "kb_id": "uuid",
  "text": "解析后的完整正文",
  "pages": [],
  "images": [],
  "parser_version": "v1"
}
```

向量索引和 GraphRAG 必须消费同一份解析文本，避免两个服务分别解析造成正文和引用不一致。

### 6.2 队列

- `parse_queue`：文档解析、OCR、VL。
- `embedding_queue`：切片、Embedding 和 Milvus 写入。
- `graph_queue`：实体关系抽取与建图。
- `cleanup_queue`：删除与一致性补偿。

在线问答不进入离线建库队列。优先级为：

```text
在线问答 > 紧急索引更新 > 普通建库 > GraphRAG 建图
```

### 6.3 幂等

任务阶段幂等键为：

```text
tenant_id + kb_id + document_id + document_version + stage
```

Embedding 使用稳定 `chunk_id` 执行 Upsert；GraphRAG 使用稳定 `document_id` 作为业务 `file_id`。重复投递不得产生重复向量、实体或关系。

### 6.4 状态

向量链路：

```text
uploaded → parsing → parsed → embedding → indexed
```

图谱链路：

```text
parsed → graph_pending → graph_building → graph_ready
```

两个状态独立。允许向量已经可用而图谱失败，此时知识库继续提供普通 RAG 服务。

### 6.5 删除

```text
deleting
→ 删除 Milvus 切片
→ 删除 Neo4j 中对应文档数据
→ 删除解析产物
→ deleted
```

每一步都可以幂等重试。失败时保留当前阶段和错误，不对用户声称已经完全删除。

## 7. 在线检索与问答

### 7.1 查询接口

```http
POST /v1/chat/query
Authorization: Bearer <token>
```

```json
{
  "question": "胎压报警后应该怎么办？",
  "kb_ids": ["kb-user-manual", "kb-after-sales"],
  "strategy": "auto",
  "top_k": 5,
  "stream": true
}
```

支持策略：

- `vector`：纯稠密向量基线。
- `hybrid`：BM25、稠密/稀疏向量、RRF 和 Reranker。
- `graph`：以 GraphRAG 为主。
- `auto`：按问题类型选择 Hybrid 或 Hybrid 加 GraphRAG。

### 7.2 处理流程

```text
鉴权与知识库权限校验
→ Query 纠错/改写
→ 检索策略路由
→ 多路并行召回
→ 统一候选格式
→ 去重与 RRF 融合
→ Reranker 精排
→ Token 预算控制
→ LLM 流式生成
→ 引用校验和结构化响应
```

### 7.3 统一候选结构

```json
{
  "chunk_id": "uuid",
  "document_id": "uuid",
  "kb_id": "uuid",
  "text": "候选文本",
  "source": "dense",
  "score": 0.82,
  "file_name": "用户手册.pdf",
  "page_number": 36,
  "image_refs": []
}
```

`source` 的允许值为 `bm25`、`dense`、`sparse` 和 `graph`。一个候选可以记录多个来源及各来源原始排名。

### 7.4 融合与精排

不同召回器的原始分数不直接相加。系统使用 RRF：

```text
RRF(d) = Σ 1 / (k + rank_i(d))
```

融合步骤：

1. 按 `chunk_id` 去重。
2. 保留召回来源及原始排名。
3. 计算 RRF 并选择候选 Top-N。
4. 使用 Reranker 对问题与候选文本重新打分。
5. 根据 Token 预算选择最终上下文。

### 7.5 GraphRAG 路由与降级

`auto` 策略优先将实体关系、跨文档、多跳推理和全局总结问题并行发送给 GraphRAG。普通事实问题默认使用 Hybrid。

GraphRAG 超时、失败或图谱未就绪时：

- 保留 Hybrid 结果。
- 正常生成答案。
- 在内部查询追踪中记录降级原因。
- 不向最终用户暴露内部异常堆栈。

### 7.6 答案与引用

上下文片段使用稳定引用编号：

```text
[ref-1] 文件：用户手册.pdf，第 36 页
内容：……
```

响应至少包含：

```json
{
  "answer": "请先检查四个轮胎的胎压……[ref-1]",
  "citations": [
    {
      "ref_id": "ref-1",
      "document_id": "uuid",
      "file_name": "用户手册.pdf",
      "page_number": 36,
      "chunk_id": "uuid"
    }
  ],
  "retrieval_trace_id": "uuid"
}
```

系统必须验证答案中引用编号真实存在。证据不足时使用明确拒答，不要求模型依靠参数知识补全。

## 8. 模型与索引版本

知识库绑定以下版本：

```text
embedding_model
embedding_dimension
chunk_policy_version
reranker_version
graph_extraction_version
```

Embedding 模型或维度变化时创建新索引版本。重建完成前继续使用旧版本，完成后原子切换 `active_version`，不在同一查询空间混用不兼容向量。

## 9. 错误处理与一致性

错误分类：

- 可重试：网络超时、模型服务暂时不可用、数据库临时连接失败。
- 不可重试：文件损坏、不支持格式、请求参数非法。
- 可降级：OCR、VL 或 GraphRAG 失败，但基础文本和向量链路仍可用。

使用有限次数指数退避。达到最大次数后任务进入失败状态，并保存结构化错误信息。

系统不在 PostgreSQL、Milvus 和 Neo4j 之间实现分布式事务，而采用：

- 幂等写入。
- 阶段状态。
- 有限重试。
- 补偿任务。
- 定期一致性扫描。

## 10. 测试与评测

### 10.1 验证数据

至少配置：

```text
tenant_auto
├── 汽车用户手册
└── 汽车售后 FAQ

tenant_tech
├── Python 或框架文档
└── 数据库运维文档
```

问题集包含单文档事实、关键词匹配、口语化表达、跨段落、跨文档、多跳、无答案及越权请求。

### 10.2 消融实验

比较：

```text
A：纯稠密向量
B：BM25 + 稠密/稀疏召回
C：B + RRF
D：C + Reranker
E：D + GraphRAG 路由
```

记录 Recall@5、Recall@10、MRR、NDCG@5、Context Precision/Recall、答案正确率、引用准确率、拒答准确率和阶段耗时。

GraphRAG 对普通事实题和多跳题分别统计。未提升的实验同样保留并分析。

### 10.3 自动化测试

- 单元测试：RRF、去重、引用解析、状态转换、权限判断。
- 租户隔离测试：跨租户访问返回 403，并验证三个存储层的隔离。
- 契约测试：主服务和 GraphRAG 的请求头、请求体、超时与响应结构。
- 集成测试：上传、解析、向量化、查询、引用和删除完整链路。
- 故障注入：GraphRAG 超时、Embedding 失败、Milvus 暂时不可用、任务重复投递。

### 10.4 性能记录

所有结果必须注明 CPU、内存、GPU、模型、文档数、切片数、并发数及是否使用外部 API。

记录查询 P50/P95、首 Token 延迟、各阶段耗时、每分钟建库页数、Embedding 批吞吐、GraphRAG 建图耗时、失败率和降级成功率。

## 11. 验收标准

- Docker Compose 可以从干净环境启动。
- 两个测试租户之间没有数据串读。
- 同一租户可以查询一个或多个已授权知识库。
- 所有引用可以解析到真实文档和切片。
- GraphRAG 故障时 Hybrid RAG 仍可回答。
- 重复任务不会生成重复索引数据。
- 文档删除流程最终清理 PostgreSQL 状态之外的派生数据。
- 检索、答案质量和性能结论具有脚本、配置和原始结果。
- `CONTRIBUTIONS.md` 明确列出复用内容和个人实现。

## 12. 开源交付结构

仓库至少包含：

```text
README.md
ARCHITECTURE.md
CONTRIBUTIONS.md
LICENSES.md
docker-compose.yml
docs/api.md
tests/
eval/
benchmarks/
examples/
```

简历与 README 统一将项目称为“个人开源多租户 RAG 平台原型”。已实现、已验证和仅设计的能力必须分别标注，不声称未经验证的生产规模。

## 13. 个人贡献边界

复用内容：

- `rag-system-master` 的文档解析、向量化和现有任务能力。
- `车书问答系统源码` 的检索思路及相关模型使用方式。
- `graph-rag-master` 的图谱构建和查询能力。
- LLaMA-Factory 与 RAG-Retrieval 的离线训练能力。

个人整合与新增内容：

- 统一领域模型、接口和错误语义。
- 多租户认证、授权与存储隔离。
- 可配置检索流水线和 GraphRAG 路由。
- 统一候选结构、RRF、精排和引用标准。
- 异步建库、任务幂等、重试、降级和一致性补偿。
- 自动化测试、评测、基准测试和可复现部署。

