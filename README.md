# Embedding Service

基于 FastAPI 的向量嵌入和检索服务，支持文档解析、向量化存储和语义检索。

## 项目阶段状态

| 阶段 | 内容 | 状态 |
|-----|------|------|
| Phase 1 | 平台基础与租户隔离（鉴权、知识库 v1 API、legacy 守卫） | ✅ 已实现并验证 |
| Phase 2 | 幂等建库控制面（版本/阶段/重试/降级/删除补偿/一致性扫描） | ✅ 模块已实现并验证（fake 依赖单测） |
| Phase 3 | 可配置混合检索（租户过滤、BM25/稠密/稀疏、RRF、精排、Token 预算、追踪） | ✅ 模块已实现并验证（fake 客户端单测） |
| Phase 4 | GraphRAG 路由、熔断降级、流式生成、拒答与引用校验 | ✅ 模块已实现并验证（fake 客户端单测） |
| Phase 5 | 评测 harness/fixtures/指标、Docker Compose、ARCHITECTURE/CONTRIBUTIONS/LICENSES | ✅ 已交付；在线评测与压测待跑（见 `benchmarks/`） |

说明：Phase 2 控制面位于 `ingestion/`；旧建库流程（`services/document_service.py`，BIGINT id 模型）
与控制面的接线将随 v1 建库 API 一并完成，暂不建过渡桥（见 `docs/superpowers/plans/2026-09-28-ingestion-control-plane.md`）。

## 功能特性

- **文档处理**：支持 PDF、Word、Excel、TXT、图片、音频等多种格式
- **图片理解**：可选 VL 模型生成图片描述，或 OCR 提取文字
- **音频转录**：支持多种音频格式转文本（wav/mp3/flac/ogg/m4a/aac/wma/opus等）
- **向量化存储**：基于 Milvus 的向量数据库
- **语义检索**：支持向量检索和混合检索模式
- **元数据管理**：PostgreSQL 存储任务状态和知识库元数据
- **用户确认**：支持语义清洗后的文本确认机制

## 项目结构

```
embedding/
├── api.py                      # FastAPI 主入口
├── configs/
│   └── config.py               # 配置管理（Pydantic Settings）
├── core/
│   ├── document_processor.py   # 文档处理（下载、解析、VL模型）
│   └── index_manager.py        # 索引管理
├── schemas/
│   └── __init__.py             # Pydantic 请求/响应模型
├── services/
│   ├── document_service.py     # 文档服务（处理流程）
│   └── query_service.py        # 查询服务（检索逻辑）
├── utils/
│   ├── db.py                   # PostgreSQL 数据库管理
│   ├── embedding.py            # Embedding 模型封装
│   ├── parse_storage_manager.py # 解析结果存储
│   ├── scheduler.py            # 定时任务调度
│   ├── audio_transcribe.py     # 音频转文本
│   └── get_txt.py              # OCR 图片转文本
├── test_milvus_connection.py   # Milvus 连接测试工具
├── .env                        # 环境变量配置
└── requirements.txt            # 依赖清单
```

## 快速开始

### 1. 安装依赖

```bash
# 使用 uv（推荐）
uv pip install -r requirements.txt

# 或使用 pip
pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `.env` 并根据实际情况修改：

```bash
# 核心配置
APP_ENV=test                                    # 运行环境：test/prod
EMBEDDING_MODEL_NAME=bge-m3-finetune            # Embedding 模型
EMBEDDING_SERVER=https://api.sail-cloud.com/v1  # Embedding 服务地址
EMBEDDING_KEY=replace-with-your-key             # Embedding API Key

# Milvus 配置
MILVUS_URI=http://localhost:19530
MILVUS_USER=root
MILVUS_PASSWORD=your-password
MILVUS_DB_NAME=kbs

# PostgreSQL 配置
PG_HOST=localhost
PG_PORT=5432
PG_USER=postgres
PG_PASSWORD=your-password
PG_DATABASE=postgres

# VL 模型配置（图片理解）
VL_MODEL_URL=https://api.sail-cloud.com/v1
VL_MODEL_NAME=Qwen3-VL-235B-A22B-Instruct
VL_MODEL_KEY=replace-with-your-key

# OCR 服务
OCR_URL=http://localhost:31780/upload_pic

# Chat 模型配置
CHAT_MODEL_URL=https://api.sail-cloud.com/v1
CHAT_MODEL_NAME=Qwen3.6-35B-A3B
CHAT_MODEL_KEY=replace-with-your-key
```

### 3. 启动服务

```bash
# 方式1：直接运行
python api.py

# 方式2：使用 uvicorn
uvicorn api:app --host 0.0.0.0 --port 8000 --reload

# 方式3：生产环境
uvicorn api:app --host 0.0.0.0 --port 8000 --workers 4
```

服务启动后访问：http://localhost:8000/docs

## 平台 v1 鉴权快速开始（Phase 1）

控制面 API 使用 API Key 鉴权：租户身份由服务端从 Key 推导，客户端不能自行声明。

```bash
# 1. 创建本地租户并生成一次性 API Key（仅打印一次，切勿提交入库）
python scripts/bootstrap_tenant.py --tenant-name demo --principal-name developer

# 2. 使用该 Key 调用 v1 接口
export RAG_API_KEY=rag_<bootstrap 打印的完整 key>
curl -H "Authorization: Bearer $RAG_API_KEY" http://localhost:8000/v1/knowledge-bases
```

- bootstrap 只在 stdout 打印一次 raw key；数据库仅保存 key 前缀与 HMAC-SHA256 摘要（加盐 pepper 见 `.env` 的 `API_KEY_PEPPER`）。
- 旧版 `/embedding/*` 接口默认返回 404；如需临时兼容旧客户端，设置 `LEGACY_API_ENABLED=true`。

## API 接口

### 1. 文件处理（解析 + 向量化）

```http
POST /embedding/process
```

**请求体：**
```json
{
  "tenant_id": 1,
  "kb_id": 2,
  "file_list": [
    {
      "file_id": 123,
      "name": "document.pdf",
      "path": "/uploads/document.pdf"
    }
  ],
  "is_guard": false,
  "enable_vl_model": false,
  "chunk_size": 300,
  "chunk_overlap": 100
}
```

**参数说明：**
- `is_guard`: 是否开启防护模式（语义清洗）
- `enable_vl_model`: 图片是否使用 VL 模型理解（默认 OCR）
- `chunk_size`: 文本分块大小
- `chunk_overlap`: 分块重叠大小

**响应：**
```json
{
  "code": 200,
  "msg": "success",
  "data": {
    "task_id": "uuid-string",
    "parse_status": "pending",
    "embed_status": "pending"
  }
}
```

### 2. 仅解析（不生成向量）

```http
POST /embedding/parse
```

参数同 `/embedding/process`，但只执行解析步骤。

### 3. 仅向量化（基于已解析数据）

```http
POST /embedding/embed
```

```json
{
  "task_id": "uuid-string",
  "chunk_size": 300,
  "chunk_overlap": 100,
  "embedding_model": "bge-m3-finetune",
  "embedding_dim": 1024
}
```

### 4. 查询任务状态

```http
GET /embedding/process/{task_id}
```

### 5. 语义检索

```http
POST /embedding/query
```

```json
{
  "question": "查询问题",
  "collection": "common_slice",
  "kb_id_list": [{"id": 1, "name": "知识库1"}],
  "similarity_threshold": 0.5,
  "similarity_top_k": 3,
  "mode": "naive",
  "alpha": 0.5
}
```

**检索模式：**
- `naive`: 纯向量检索
- `hybrid`: 混合检索（向量 + 关键词）

### 6. 确认语义清洗文本

```http
POST /embedding/confirm
```

```json
{
  "task_id": "uuid-string",
  "confirmations": [
    {"file_id": 1, "use_semantic": true},
    {"file_id": 2, "use_semantic": false}
  ]
}
```

### 7. 思维导图生成

根据文本内容生成思维导图结构（供前端渲染为可视化思维导图）。

```http
POST /visualization/mindmap
```

**请求体：**

```json
{
  "text": "机器学习通常分为有监督学习（Supervised Learning）和无监督学习（Unsupervised Learning）两大类。有监督学习（Supervised Learning）线性回归、逻辑回归、SVM，无监督学习（Unsupervised Learning）： K-Means、层次聚类、PCA"
}
```

**参数说明：**

- `text`: 用于生成思维导图的文本内容

**响应：**

```json
{
  "code": 200,
  "msg": "success",
  "data": {
    "title": "机器学习",
    "children": [
      {
        "title": "有监督学习",
        "children": [
          {
            "title": "线性回归",
            "id": 3
          },
          {
            "title": "逻辑回归",
            "id": 4
          },
          {
            "title": "SVM",
            "id": 5
          }
        ],
        "id": 2
      },
      {
        "title": "无监督学习",
        "children": [
          {
            "title": "K-Means",
            "id": 7
          },
          {
            "title": "层次聚类",
            "id": 8
          },
          {
            "title": "PCA",
            "id": 9
          }
        ],
        "id": 6
      }
    ],
    "id": 1
  }
}
```

**结构说明：**

- `title`: 节点标题
- `children`: 子节点列表（可选）

### 8. Mermaid 图表生成

根据文本内容生成 Mermaid 图表结构（供前端渲染为可视化图表）。

```http
POST /visualization/mermaid
```

**请求体：**

```json
{
  "text": "用户登录系统后，先验证身份，然后查询权限，最后返回结果"
}
```

**参数说明：**

- `text`: 用于生成 Mermaid 图表的文本内容

**响应：**

```json
{
  "code": 200,
  "msg": "success",
  "data": {
    "mermaid": "graph TD\nA[用户登录] --> B[验证身份]\nB --> C[查询权限]\nC --> D[返回结果]"
  }
}
```

### 9. Deep Research 网页结构化生成

根据文本内容生成 Deep Research 报告 JSON（供前端渲染成包含文字分析、思维导图、图表与表格的可视化网页）。

```http
POST /visualization/webpage
```

**请求体：**

```json
{
  "text": "2024年，全球人工智能（AI）市场规模达到4500亿美元，同比增长25%，继续保持高速扩张态势。过去五年，全球AI市场持续增长，市场规模从2020年的2100亿美元增长至2021年的2600亿美元、2022年的3200亿美元、2023年的3600亿美元，并在2024年突破4500亿美元，显示出人工智能技术正加速渗透至各行各业。从区域分布来看，北美市场仍然占据全球领先地位，市场规模约为1800亿美元，占全球市场总量的40%。亚太地区增长最快，市场规模达到1575亿美元，占比35%，其中中国、日本和韩国是主要推动力量。欧洲市场规模约为900亿美元，占比20%，主要受制造业智能化和企业数字化转型推动。拉丁美洲、中东及非洲等新兴市场合计占比约5%，虽然整体规模较小，但增长潜力巨大。从行业应用角度分析，生成式人工智能和大模型相关应用成为2024年最重要的增长引擎，占整体AI市场的30%。智能制造占比22%，主要应用于工业质检、设备预测性维护和生产流程优化。金融科技领域占比18%，应用场景包括智能风控、算法交易和客户服务自动化。医疗健康领域占比15%，主要包括医学影像分析、药物研发和智能诊断。零售与电商领域占比10%，主要用于个性化推荐和供应链优化。其他行业应用合计占比5%。从技术投入结构来看，企业在AI基础设施上的投入持续增加。2024年，AI算力基础设施投资达到1200亿美元，占整体市场的27%；模型训练与开发平台投入约900亿美元，占比20%；行业解决方案和应用层服务投入达到1800亿美元，占比40%；AI安全治理与合规相关投入约600亿美元，占比13%。主要市场参与者方面，OpenAI、Google、Microsoft、Amazon和Meta仍然处于全球领先地位。其中，Microsoft市场份额约为18%，Google占15%，OpenAI占12%，Amazon占10%，Meta占8%，其他企业合计占37%。随着开源模型生态的发展，越来越多初创企业和区域性科技公司正在进入市场，推动行业竞争进一步加剧。未来几年，人工智能市场预计仍将保持快速增长。预计到2025年，全球AI市场规模将达到5600亿美元；到2026年有望突破6800亿美元。推动增长的关键因素包括生成式AI商业化落地、企业数字化转型需求提升，以及各国政府对人工智能基础设施和监管体系的持续投入。总体来看，人工智能正从技术创新阶段逐步迈向产业规模化应用阶段，成为推动全球经济增长和产业升级的重要核心力量。",
  "enable_web_search": false,
  "web_search_query": "",
  "web_search_count": 3,
  "web_search_answer": true
}
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| text | string | 是 | 用于生成 Deep Research 报告的文本内容 |
| enable_web_search | boolean | 否 | 是否启用可选 Web Search 补充信息，默认 false |
| web_search_query | string | 否 | 自定义搜索词；为空时根据 text 自动生成 |
| web_search_count | integer | 否 | 搜索返回条数，默认 3，最大值由 WEB_SEARCH_MAX_COUNT 控制 |
| web_search_answer | boolean | 否 | 是否请求搜索侧 AI 总结，默认 true |

Web Search 是 `/visualization/webpage` 的可选增强能力，不接 RAG，不影响 mindmap/mermaid。启用后会把搜索来源作为补充上下文注入 Deep Research；搜索失败或无结果时接口自动降级为纯文本报告，并在 `metadata.warnings` 中记录原因。

**响应**
```json
{
  "code": 200,
  "msg": "success",
  "data": {
    "title": {"id": "1", "text": "2024年全球人工智能市场规模与趋势分析"},
    "summary": {"id": "2", "text": "2024年全球AI市场规模达4500亿美元，同比增长25%。"},
    "research_overview": {
      "id": "3",
      "question": "AI市场的规模、结构和增长趋势如何？",
      "scope": "市场规模、区域分布、行业应用、竞争格局",
      "method": "基于输入文本进行归纳、比较、趋势判断和结构化分析"
    },
    "key_findings": [
      {
        "id": "4.1",
        "title": "市场继续高速扩张",
        "insight": "2024年AI市场规模达4500亿美元，同比增长25%。",
        "evidence": ["2024年全球AI市场规模达到4500亿美元，同比增长25%。"],
        "confidence": "high"
      }
    ],
    "sections": [
      {
        "id": "5.1",
        "title": "市场规模与增长趋势",
        "summary": "AI市场延续高速增长。",
        "content": "从2020年至2024年，全球AI市场规模持续提升，说明AI正在从技术创新进入产业规模化应用阶段。",
        "evidence": ["市场规模从2020年的2100亿美元增长至2024年的4500亿美元。"]
      }
    ],
    "mindmap": {
      "id": "6",
      "title": "知识结构",
      "nodes": [{"id": "6.1", "label": "市场规模", "children": []}]
    },
    "charts": [
      {
        "id": "7.1",
        "type": "line",
        "title": "2020-2024年全球AI市场规模",
        "description": "来自输入文本中的年度市场规模数据。",
        "data": {
          "categories": ["2020", "2021", "2022", "2023", "2024"],
          "values": [2100, 2600, 3200, 3600, 4500]
        }
      }
    ],
    "conclusion": {"id": "8", "text": "AI市场正在进入产业规模化应用阶段。"},
    "recommendations": [],
    "sources": [],
    "metadata": {
      "id": "10",
      "visualization_type": "deep_research_webpage",
      "chart_count": 1,
      "section_count": 1,
      "finding_count": 1,
      "source_count": 0,
      "web_search_requested": false,
      "web_search_enabled": false
    }
  }
}
```

**模块说明：**

- `title`: 页面标题（id: "1"）
- `summary`: 执行摘要（id: "2"，不超过300字）
- `kpis`: 关键指标卡片（id: "2.x"，建议 3~6 个；无明确数字时为空数组）
- `research_overview`: 研究问题、范围和方法（id: "3"）
- `sections`: 分节深度分析（id: "5.x"，含 observation/interpretation/mechanism/implication/uncertainty/outlook/insight；`used_source_ids` 可选）
- `key_findings`: 核心发现列表（id: "4.x"，含 confidence；`used_source_ids` 可选）
- `charts`: 图表数组（含 `chart_insight`、`data_confidence`、`data_source_refs`）
- `recommendations`: 行动建议（`priority` 为 P0/P1/P2；含 rationale、risk）
- `sources`: Web Search 来源列表（可为空数组）
- `metadata`: 含 `research_complexity`、`quality_banner`、`degraded` 等

**编号规则：**

- title："1"
- summary："2"
- research_overview："3"
- key_findings："4.1", "4.2"...
- sections："5.1", "5.2"...
- mindmap："6"，节点从 "6.1" 开始
- charts："7.1", "7.2"...
- conclusion："8"
- recommendations："9.1", "9.2"...
- metadata："10"

**图表约束：**

- 只有输入文本中存在明确数字、比例、金额、年份、时间序列、排名或分类统计时才生成 `charts`
- 没有明确可视化数据时返回 `"charts": []`
- `charts[].type` 支持：`bar`、`line`、`pie`、`table`、`area`、`horizontal_bar`、`scatter`、`radar`、`gauge`、`funnel`、`donut`、`stacked_bar`、`heatmap`
- `charts` 数量不设上限
- `table` 不单独使用 `tables` 字段，统一作为 `charts[].type = "table"`
- 图表数量由**数据可可视化价值**决定，不由输入长度或 `research_complexity` 直接决定
- 分析深度由 `metadata.research_complexity`（simple/standard/deep）引导，不由字数分档

### Deep Research Demo 预览

```bash
# 仅启动可视化相关接口（可选）
VISUALIZATION_ONLY=true python api.py
```

1. 打开 Demo 页面：`http://127.0.0.1:8000/visualization/demo`
2. 调用 `POST /visualization/webpage` 成功后，最新报告自动写入 `output/last-webpage-response.json`
3. 预览最近一次结果：`http://127.0.0.1:8000/visualization/demo?render=latest`
4. Web Search：Demo 页勾选「启用 Web Search」，或请求体设置 `enable_web_search: true`（失败时自动降级，不阻断报告）

完整 JSON 契约见 [docs/deep-research-schema.md](docs/deep-research-schema.md)。

## 支持的文件格式

| 类型 | 格式 | 处理方式 |
|-----|------|---------|
| 文本 | PDF, DOCX, TXT, MD | 直接解析 |
| 表格 | XLSX, XLS | 转为文本表格 |
| 图片 | JPG, PNG, GIF, BMP, WEBP | VL模型/OCR |
| 音频 | MP3, WAV, M4A, FLAC, OGG, WMA | 语音转文本 |

## 测试工具

### Milvus 连接测试

```bash
# 使用默认配置
python test_milvus_connection.py

# 使用命令行参数
python test_milvus_connection.py -u http://10.0.0.1:19530 -n root -p mypass

# 交互模式
python test_milvus_connection.py --interactive

# 测试所有预设配置
python test_milvus_connection.py --all
```

## 配置详解

### VL 模型 Prompt 自定义

在 `.env` 中修改 `VL_MODEL_PROMPT`：

```bash
VL_MODEL_PROMPT="请详细描述这张图片的内容...

要求：
1. xxx
2. xxx"
```

### 环境切换

```bash
# 测试环境
APP_ENV=test

# 生产环境
APP_ENV=prod
```

不同环境会自动使用对应的 Milvus 和 PostgreSQL 配置。

## 部署建议

### 生产环境

```bash
# 使用 gunicorn + uvicorn
pip install gunicorn
gunicorn api:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
```

### Docker 部署

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
EXPOSE 8000

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
```

## 常见问题

### 1. VL 模型 401 错误

检查 `.env` 中的 `VL_MODEL_KEY` 是否正确配置。

### 2. Milvus 连接超时

```bash
# 测试连接
python test_milvus_connection.py
```

### 3. 图片 OCR 失败

检查 `OCR_URL` 是否可达，图片格式是否支持。

### 4. 音频转录失败

确保系统安装了 ffmpeg：
```bash
# Ubuntu/Debian
apt-get install ffmpeg

# macOS
brew install ffmpeg

# Windows
# 下载并添加到 PATH: https://ffmpeg.org/download.html
```

## 技术栈

- **Web 框架**: FastAPI
- **向量数据库**: Milvus
- **关系数据库**: PostgreSQL + asyncpg
- **文档解析**: LlamaIndex, SimpleDirectoryReader
- **向量化**: OpenAI Embedding API
- **图片理解**: Vision Language Model (OpenAI 格式)
- **音频处理**: FFmpeg + Whisper/V2T 服务

## License

MIT License
