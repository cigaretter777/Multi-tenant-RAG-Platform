# 许可证声明

本项目代码以 MIT License 发布（待仓库根添加 LICENSE 文件后生效）。

## 主要第三方组件

| 组件 | 许可证 | 用途 |
|-----|--------|------|
| FastAPI / Starlette | MIT | Web 框架 |
| Pydantic / pydantic-settings | MIT | 模型与配置 |
| asyncpg | Apache-2.0 | PostgreSQL 驱动 |
| pymilvus / Milvus | Apache-2.0 | 向量数据库 |
| Neo4j Community | GPL-3.0 | 图谱存储（独立服务部署；生产商用需评估 Neo4j 商业许可） |
| LlamaIndex | MIT | 文档解析读取器 |
| NLTK | Apache-2.0 | 停用词等 NLP 资源 |
| Redis | BSD-3 | 队列/缓存（规划） |
| PostgreSQL | PostgreSQL License | 控制面存储 |

## 既有代码来源

- `rag-system-master`、`graph-rag-master`、`车书问答系统源码` 为个人既有项目，
  复用边界见 `CONTRIBUTIONS.md`；对外发布前需逐仓库确认原始许可与可发布性。
- 模型权重（bge-m3 系列、Qwen 系列）遵循各自发布许可，本项目不随仓库分发权重。
