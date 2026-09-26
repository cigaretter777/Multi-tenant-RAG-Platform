# Embedding Service API 文档

## 基本信息

| 项目 | 说明 |
|------|------|
| 服务名称 | Embedding Service |
| 版本 | 1.5.0 |
| 描述 | 向量嵌入和检索服务，支持多模型动态切换、可选 GraphRAG 建图及图谱上下文召回 |
| 默认端口 | 8000 |

## 统一响应格式

所有接口返回统一的响应格式：

```json
{
  "code": 200,
  "msg": "success",
  "data": {}
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| code | int | 状态码，200 表示成功 |
| msg | string | 消息描述 |
| data | any | 响应数据 |

---

## 接口列表

### 1. 文件处理接口（解析 + 向量化）

提交文件处理任务，异步执行解析和向量化流程。

**请求**
```
POST /embedding/process
```

**请求参数**
```json
{
  "file_list": [
    {
      "file_id": 123,
      "name": "文档.pdf",
      "path": "/api/files/123"
    }
  ],
  "tenant_id": 1,
  "kb_id": 1,
  "is_guard": false,
  "chunk_size": 300,
  "chunk_overlap": 100,
  "embedding_model": "bge-m3-finetune",
  "embedding_dim": 1024,
  "build_graph": true,
  "domain_brief": {"preset": "general"},
  "graph_chunk_size": 500,
  "graph_chunk_overlap": 50
}
```

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| file_list | array | 是 | - | 文件列表，每项需包含 file_id、name、path |
| tenant_id | int | 是 | - | 租户ID |
| kb_id | int | 是 | - | 知识库ID（即 GraphRAG 的 graph_id） |
| is_guard | bool | 否 | false | 是否开启防护 |
| chunk_size | int | 否 | 300 | **向量化**切块大小（与 GraphRAG 建图切块无关） |
| chunk_overlap | int | 否 | 100 | **向量化**切块重叠 |
| embedding_model | string | 否 | null | Embedding模型名称，为空使用系统默认 |
| embedding_dim | int | 否 | null | 向量维度，为空使用系统默认 |
| build_graph | bool | 否 | false | 是否同步提交 GraphRAG 文本建图（仅文件模式） |
| domain_brief | object | 否 | `{"preset":"general"}` | GraphRAG 领域抽取配置，见下文 |
| graph_chunk_size | int | 否 | 500 | GraphRAG 建图切块大小（字符） |
| graph_chunk_overlap | int | 否 | 50 | GraphRAG 建图切块重叠（字符） |

**知识库模型绑定规则**

| 场景 | 行为 |
|------|------|
| 新建KB，传入模型 | 使用该模型，记录到元数据表 |
| 新建KB，未传模型 | 使用默认模型，记录到元数据表 |
| 已有KB，传入相同模型 | 正常执行，使用已有模型 |
| 已有KB，传入不同模型 | 警告并更新为新模型（重建场景） |
| 已有KB，未传模型 | 使用绑定模型 |

**响应**
```json
{
  "code": 200,
  "msg": "success",
  "data": {
    "task_id": "550e8400-e29b-41d4-a716-446655440000",
    "parse_status": "pending",
    "embed_status": "pending"
  }
}
```

**处理流程**
1. 创建任务记录，返回 task_id
2. 后台异步执行解析阶段
3. 如需用户确认则暂停，等待确认
4. 后台异步执行向量化阶段；若 `build_graph=true`，在解析完成（含确认后）并行提交 GraphRAG 建图

**GraphRAG 建图说明**

文成**不要直连 GraphRAG**；由 RAG 在文件解析完成后内部调用 GraphRAG 子接口。

**调用链：**

```
文成 → POST /embedding/process（build_graph=true）
     → RAG 解析文件、使用已有 file_id
     → RAG 内部 POST GraphRAG /api/text/process
     → 文成 GET /embedding/process/{task_id} 或 /graph-progress 查询进度
```

| RAG 请求字段 | GraphRAG 请求头 |
|--------------|-----------------|
| `tenant_id` | `X-Tenant-ID` |
| `kb_id` | `X-Graph-ID`（即 `graph_id`） |

**要点：**

- `tenant_id` / `graph_id` **仅通过请求头**传给 GraphRAG，不出现在 body 中
- 传给 GraphRAG 的 `file_content` 为 RAG 解析后的纯文本，与最终向量化使用的 `document_text` 一致
- `file_id` 须与删文件接口（`delete_graph`）保持一致，强烈建议由文成分配并在 `file_list` 中传入
- 需语义确认时，建图在用户确认全部完成后触发
- GraphRAG 建图失败**不会**导致解析/向量化失败，错误见 `graph_error`
- 删除侧对称参数：`POST /embedding/delete` 的 `delete_graph`

**`domain_brief` 字段（透传 GraphRAG）**

| 字段 | 说明 |
|------|------|
| `preset` | 内置预设：`general` / `cyber_security` / `medical` / `legal` / `finance` |
| `domain_description` | 领域自然语言说明；与 `preset` **至少填其一**才启用领域抽取 |
| `output_language` | 输出语言，默认 `zh` |
| `strictness` | 抽取严格度：`literal` / `normal` |

> 兼容说明：若传入旧字段 `description`，RAG 会自动映射为 `domain_description`。

**示例**

```json
{"preset": "general"}
```

```json
{
  "preset": "cyber_security",
  "output_language": "zh",
  "strictness": "normal"
}
```

```json
{
  "domain_description": "汽车涂装车间安全管理规章，关注工序、设备、违规条款与时间窗口"
}
```

**RAG 转发 GraphRAG 时的 body 结构（内部参考）**

| 字段 | 说明 |
|------|------|
| `file_list[].file_id` | 字符串，业务文件 ID |
| `file_list[].name` | 文件名 |
| `file_list[].file_content` | 解析后正文 |
| `chunk_size` / `chunk_overlap` | 来自 `graph_chunk_size` / `graph_chunk_overlap` |
| `domain_brief` | 来自请求的 `domain_brief` |

---

### 2. 纯解析接口

仅执行文件解析，不进行向量化。

**请求**
```
POST /embedding/parse
```

**请求参数**
```json
{
  "file_list": [
    {
      "file_id": 123,
      "name": "文档.pdf",
      "path": "/api/files/123"
    }
  ],
  "tenant_id": 1,
  "kb_id": 1,
  "is_guard": false,
  "build_graph": true,
  "domain_brief": {"preset": "general"}
}
```

支持与 `/embedding/process` 相同的 `build_graph`、`domain_brief`、`graph_chunk_size`、`graph_chunk_overlap` 参数（仅文件模式）。解析完成后若 `build_graph=true` 会提交 GraphRAG 建图。

**响应**
```json
{
  "code": 200,
  "msg": "success",
  "data": {
    "task_id": "550e8400-e29b-41d4-a716-446655440000",
    "parse_status": "pending"
  }
}
```

---

### 3. 纯向量化接口

对已解析的任务执行向量化。

**请求**
```
POST /embedding/embed
```

**请求参数**
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "chunk_size": 300,
  "chunk_overlap": 100,
  "embedding_model": "text2vec-large-chinese",
  "embedding_dim": 768
}
```

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| task_id | string | 是 | - | 任务ID |
| chunk_size | int | 否 | 300 | 切块大小 |
| chunk_overlap | int | 否 | 100 | 重叠大小 |
| embedding_model | string | 否 | null | 向量模型名称，不传使用全局配置 |
| embedding_dim | int | 否 | null | 向量维度，不传使用全局配置 |

**向后兼容性说明**
- 此接口完全向后兼容，现有代码无需修改
- 新增参数 `embedding_model` 和 `embedding_dim` 均为可选字段
- 不传入新参数时，将使用全局默认配置
- 支持部分参数传入，如只传 `embedding_model` 不传 `embedding_dim`

**使用示例**
```json
// 向后兼容的调用（现有代码无需修改）
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "chunk_size": 300,
  "chunk_overlap": 100
}

// 使用新参数的调用
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "chunk_size": 300,
  "chunk_overlap": 100,
  "embedding_model": "text2vec-large-chinese",
  "embedding_dim": 768
}

// 部分新参数的调用
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "chunk_size": 300,
  "chunk_overlap": 100,
  "embedding_model": "bge-m3-finetune"
}
```

**响应**
```json
{
  "code": 200,
  "msg": "success",
  "data": {
    "task_id": "550e8400-e29b-41d4-a716-446655440000",
    "embed_status": "processing"
  }
}
```

---

### 4. 任务状态查询接口

查询文件处理任务的执行进度。

**请求**
```
GET /embedding/process/{task_id}
```

**路径参数**
| 参数 | 类型 | 说明 |
|------|------|------|
| task_id | string | 任务ID |

**响应**
```json
{
  "code": 200,
  "msg": "success",
  "data": {
    "task_id": "550e8400-e29b-41d4-a716-446655440000",
    "parse_status": "finish",
    "embed_status": "processing",
    "file_count": 5,
    "created_at": 1706745600,
    "updated_at": 1706745900,
    "error_message": null,
    "graph_status": "processing",
    "graph_task_id": "5915cee2-767a-418b-86d9-77c07e2dc5b0",
    "graph_error": null
  }
}
```

**状态值说明**
| 字段 | 可能值 |
|------|--------|
| parse_status | pending / processing / finish / failed / waiting_confirmation |
| embed_status | pending / processing / finish / failed / skipped |
| graph_status | skipped / pending / processing / finish / failed |

| graph_status | 说明 |
|--------------|------|
| skipped | 未请求建图（`build_graph=false`） |
| pending | 已请求建图，等待解析完成或用户确认 |
| processing | 已提交 GraphRAG，处理中 |
| finish | GraphRAG 建图完成（`remote_status=completed` 且 `processed_files=total_files`） |
| failed | GraphRAG 建图失败，详见 `graph_error` |

**GraphRAG `remote_status` 生命周期（经 graph-progress 返回）：**

```
pending → processing → completed
                    ↘ failed
```

查询进行中的任务时会同步刷新 GraphRAG 状态（轮询间隔默认 2s，可配置 `graphrag_poll_interval`）。

---

### 4.1 GraphRAG 建图进度查询接口

查询任务关联的 GraphRAG **细粒度**建图进度。RAG 代理 GraphRAG `GET /api/text/progress/{task_id}`，文成无需直连 GraphRAG。

**请求**
```
GET /embedding/process/{task_id}/graph-progress
```

**路径参数**
| 参数 | 类型 | 说明 |
|------|------|------|
| task_id | string | RAG 任务ID |

**响应字段（建图已提交时）**

| 字段 | 说明 |
|------|------|
| `graph_status` | RAG 聚合状态：skipped / pending / processing / finish / failed |
| `remote_status` | GraphRAG 原始状态：pending / processing / completed / failed |
| `graph_task_id` | GraphRAG 返回的任务 ID |
| `progress` | 0～100 |
| `current_step` | 当前步骤描述 |
| `total_files` / `processed_files` | 文件总数 / 已处理数 |
| `entities_extracted` / `relationships_extracted` | 累计抽取实体、关系数 |
| `entity_dedup_key_mode` | 实体去重模式 |
| `merge_stats_by_file` | 每文件合并统计 |
| `domain_brief_submitted` | 创建时是否传了 domain_brief |
| `domain_extraction` | 领域抽取摘要 |
| `domain_extraction_files` | 每文件领域抽取摘要 |
| `graph_error` | 失败原因；任务级失败或单文件异常时可能有值 |

**完成判定：** `remote_status === "completed"` 且 `processed_files === total_files` 时，RAG 将 `graph_status` 置为 `finish`。

**响应示例（建图进行中）**
```json
{
  "code": 200,
  "msg": "success",
  "data": {
    "task_id": "550e8400-e29b-41d4-a716-446655440000",
    "build_graph_requested": true,
    "graph_status": "processing",
    "remote_status": "processing",
    "graph_task_id": "5915cee2-767a-418b-86d9-77c07e2dc5b0",
    "graph_error": null,
    "progress": 65.0,
    "current_step": "处理文件 1/1: api_test.txt",
    "total_files": 1,
    "processed_files": 0,
    "entities_extracted": 8,
    "relationships_extracted": 5,
    "entity_dedup_key_mode": "name_only",
    "merge_stats_by_file": [],
    "domain_brief_submitted": true,
    "domain_extraction": null,
    "domain_extraction_files": null,
    "started_at": "2026-06-22T02:48:06.889254",
    "completed_at": null
  }
}
```

**响应示例（建图完成）**
```json
{
  "code": 200,
  "msg": "success",
  "data": {
    "task_id": "550e8400-e29b-41d4-a716-446655440000",
    "graph_status": "finish",
    "remote_status": "completed",
    "graph_task_id": "5915cee2-767a-418b-86d9-77c07e2dc5b0",
    "graph_error": null,
    "progress": 100.0,
    "current_step": "处理完成",
    "total_files": 1,
    "processed_files": 1,
    "entities_extracted": 8,
    "relationships_extracted": 5,
    "merge_stats_by_file": [
      {
        "file_name": "api_test.txt",
        "file_id": "graphrag_api_test_002",
        "merged_entity_count": 8,
        "merged_relationship_count": 5
      }
    ],
    "domain_extraction": {
      "enabled": true,
      "preset_used": "general",
      "domain_summary": "通用知识图谱：人物、组织、地点、时间等常见实体。"
    }
  }
}
```

**响应示例（未请求建图）**
```json
{
  "code": 200,
  "msg": "success",
  "data": {
    "task_id": "550e8400-e29b-41d4-a716-446655440000",
    "graph_status": "skipped",
    "graph_task_id": null,
    "graph_error": null,
    "build_graph_requested": false,
    "message": "未请求 GraphRAG 建图"
  }
}
```

---

### 4.2 GraphRAG 领域预设查询接口

代理 GraphRAG `GET /api/text/domain-presets`，供上传表单展示内置领域选项（可选）。

**请求**
```
GET /embedding/graph/domain-presets?tenant_id=6&kb_id=1
```

**查询参数**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| tenant_id | int | 是 | 租户ID → `X-Tenant-ID` |
| kb_id | int | 是 | 知识库ID → `X-Graph-ID` |

**响应示例**
```json
{
  "code": 200,
  "msg": "success",
  "data": {
    "presets": [
      {
        "key": "general",
        "domain_summary": "通用知识图谱：人物、组织、地点、时间等常见实体。",
        "entity_types": ["人物", "组织"],
        "relation_types": ["位于", "属于"]
      }
    ]
  }
}
```

> 实际字段以 GraphRAG 返回为准；`graphrag_enabled=false` 时返回 400。

---

### 5. 确认语义文本接口

确认是否使用语义清洗后的文本（列表形式批量确认）。

**请求**
```
POST /embedding/confirm
```

**请求参数**
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "confirmations": [
    {"file_id": 123, "use_semantic": true},
    {"file_id": 124, "use_semantic": false}
  ]
}
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| task_id | string | 是 | 任务ID |
| confirmations | array | 是 | 确认列表 |
| confirmations[].file_id | int | 是 | 文件ID |
| confirmations[].use_semantic | bool | 是 | true=使用语义清洗文本，false=使用原始文本 |

**响应**
```json
{
  "code": 200,
  "msg": "success",
  "data": {
    "task_id": "550e8400-e29b-41d4-a716-446655440000",
    "updated_count": 2,
    "pending_count": 0,
    "confirmations": [
      {"file_id": 123, "use_semantic": true},
      {"file_id": 124, "use_semantic": false}
    ]
  }
}
```

**字段说明**
| 字段 | 说明 |
|------|------|
| updated_count | 本次更新的文件数 |
| pending_count | 还待确认的文件数（0表示全部确认完成） |

---

### 6. 删除文档接口

删除指定文档在 Milvus 中的向量切片，并同步清理 PostgreSQL `parsed_documents` 中的解析缓存。可选同步删除 GraphRAG 图谱中对应文件的实体/关系。

**请求**
```
POST /embedding/delete
```

**请求参数**
```json
{
  "tenant_id": 1,
  "kb_id": 123,
  "file_ids": [1001, 1002],
  "collection": "common_slice",
  "delete_graph": true
}
```

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| tenant_id | int | 是 | - | 租户ID |
| kb_id | int | 是 | - | 知识库ID（即 GraphRAG 的 graph_id） |
| file_ids | array | 是 | - | 要删除的文档 file_id 列表 |
| collection | string | 否 | common_slice | Milvus 集合名称 |
| delete_graph | bool | 否 | false | 是否同步删除 GraphRAG 图谱数据 |

**响应（仅删向量）**
```json
{
  "code": 200,
  "msg": "success",
  "data": {
    "collection": "common_slice",
    "tenant_id": 1,
    "kb_id": 123,
    "file_ids": [1001, 1002],
    "deleted_milvus_count": 856,
    "deleted_pg_count": 2,
    "graph_deletion": {
      "requested": false
    }
  }
}
```

**响应（同步删图谱，`delete_graph=true`）**
```json
{
  "code": 200,
  "msg": "success",
  "data": {
    "collection": "common_slice",
    "tenant_id": 1,
    "kb_id": 123,
    "file_ids": [1001, 1002],
    "deleted_milvus_count": 856,
    "deleted_pg_count": 2,
    "graph_deletion": {
      "requested": true,
      "success": true,
      "tenant_id": "1",
      "graph_id": "123",
      "file_ids": ["1001", "1002"],
      "results": [
        {
          "file_id": "1001",
          "entities_deleted": 7,
          "entities_updated": 1,
          "relationships_deleted": 0,
          "relationships_updated": 0,
          "entities_matched": 8,
          "relationships_matched": 5
        }
      ],
      "entities_deleted": 7,
      "entities_updated": 1,
      "relationships_deleted": 0,
      "relationships_updated": 0,
      "entities_matched": 8,
      "relationships_matched": 5
    }
  }
}
```

**注意事项**

- Milvus 删除范围限定为 `tenant_id + kb_id + file_ids`，避免跨租户/跨知识库误删
- PostgreSQL 侧仅按 `file_id` 删除解析缓存（表中无 tenant_id/kb_id 字段）
- 适用于文件模式文档；数据库模式若未写入 file_id 则无法通过本接口删除 Milvus 数据
- `delete_graph=true` 时，RAG 在完成 Milvus/PG 删除后调用 GraphRAG `DELETE /api/knowledge/by-file`，批量传入 `file_ids`（转为字符串）
- GraphRAG 删除失败不会回滚 Milvus/PG 删除，失败信息记录在 `graph_deletion.error` 中
- GraphRAG 相关配置：`graphrag_base_url`、`graphrag_timeout`、`graphrag_enabled`（见 `.env`）

---

### 7. 统一检索接口

根据问题进行向量检索或混合检索，**可选并行** GraphRAG 图谱上下文召回。系统会自动根据知识库绑定的 embedding 模型进行切换。

> **响应格式变更（v1.5）：** `data` 由原先的**数组**改为**对象**，包含 `vector_results` 与 `graph_context` 两路召回结果，便于下游（文成）合并后调 LLM。

**请求**
```
POST /embedding/query
```

**请求参数**
```json
{
  "question": "张三在哪个公司工作？",
  "tenant_id": 6,
  "collection": "common_slice",
  "kb_id_list": [
    {"id": 1, "name": "知识库1"},
    {"id": 2, "name": "知识库2"}
  ],
  "similarity_threshold": 0.5,
  "similarity_top_k": 3,
  "mode": "hybrid",
  "alpha": 0.5,
  "include_graph": true,
  "graph_strategy": "mix"
}
```

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| question | string | 是 | - | 查询问题 |
| tenant_id | int | 是 | - | 租户ID → GraphRAG `X-Tenant-ID` |
| collection | string | 否 | common_slice | Milvus 集合名称 |
| kb_id_list | array | 是 | - | 知识库ID列表；向量检索与图谱查询均按此列表并行 |
| similarity_threshold | float | 否 | 0.5 | 相似度阈值 (0-1) |
| similarity_top_k | int | 否 | 3 | 向量召回返回数量 (1-100) |
| mode | string | 否 | naive | 向量检索模式：`naive` / `hybrid`（与 GraphRAG 无关） |
| alpha | float | 否 | 0.5 | 混合检索向量权重 (0-1) |
| include_graph | bool | 否 | false | 是否并行调用 GraphRAG 图谱上下文 |
| graph_strategy | string | 否 | mix | GraphRAG 策略：`local` / `global` / `mix` |
| graph_context | string | 否 | null | 仅 `graph_strategy=local` 时可传的实体周边 hint |

**GraphRAG 图谱召回说明**

- RAG 内部调用 `POST /api/query`，**固定** `return_context: true`（只取实体/关系，不生成最终答案）
- 头映射：`tenant_id` → `X-Tenant-ID`，`kb_id` → `X-Graph-ID`
- 多 KB 时对每个 `kb_id` **并发**查询 GraphRAG，结果在 `graph_context.results[]` 中按 KB 分组
- 某 KB 图谱查询失败**不影响**向量结果与其他 KB 的图谱结果
- `graphrag_enabled=false` 时 `graph_context.error` 为「GraphRAG 服务未启用」

**模型自动切换机制**

1. 系统根据 `kb_id_list` 查询各知识库绑定的 embedding 模型
2. 校验所有 KB 是否使用**相同的模型**（不一致则返回 400 错误）
3. 临时切换到 KB 绑定的模型进行向量查询
4. 查询完成后恢复原始模型配置

**可能的错误**

```json
{
  "code": 400,
  "msg": "模型一致性校验失败: 知识库使用了不同的embedding模型: {1: 'model-a', 2: 'model-b'}"
}
```

**响应（不含图谱，`include_graph=false`）**
```json
{
  "code": 200,
  "msg": "success",
  "data": {
    "mode": "naive",
    "vector_results": [
      {
        "fileMateData": "文档.pdf",
        "file_id": 123,
        "fileText": "检索到的文本内容\n",
        "kb_id": 1,
        "kb_name": "知识库1",
        "heading_path": "",
        "nearest_heading": ""
      }
    ],
    "graph_context": {
      "requested": false
    }
  }
}
```

**响应（含图谱，`include_graph=true`，多 KB）**
```json
{
  "code": 200,
  "msg": "success",
  "data": {
    "mode": "hybrid",
    "vector_results": [
      {
        "fileMateData": "api_test.txt",
        "file_id": 1001,
        "fileText": "张三是一家名为 GraphRAG 测试公司的工程师。\n",
        "kb_id": 1,
        "kb_name": "知识库1"
      }
    ],
    "graph_context": {
      "requested": true,
      "error": null,
      "results": [
        {
          "kb_id": 1,
          "kb_name": "知识库1",
          "success": true,
          "query_type": "mix",
          "confidence": 0.8,
          "execution_time": 0.45,
          "entities": [
            {
              "id": "…",
              "entity": "张三",
              "type": "人物",
              "description": "GraphRAG 测试公司的工程师",
              "created_at": "2026-06-22 10:48:00",
              "properties": {}
            }
          ],
          "relationships": [
            {
              "id": "…",
              "entity1": "…",
              "entity2": "…",
              "type": "供职于",
              "description": "张三供职于 GraphRAG 测试公司",
              "properties": {}
            }
          ],
          "entities_count": 1,
          "relationships_count": 1,
          "sources": ["local_query"],
          "error": null
        },
        {
          "kb_id": 2,
          "kb_name": "知识库2",
          "success": false,
          "entities": [],
          "relationships": [],
          "error": "GraphRAG 图谱查询失败: …"
        }
      ]
    }
  }
}
```

**下游（文成）合并建议**

| 字段 | 用途 |
|------|------|
| `vector_results[].fileText` | 文档证据片段 |
| `graph_context.results[].entities` / `relationships` | 结构化图谱上下文 |
| 最终 LLM 作答 | 由文成调用大模型，rag-system **不提供** `/embedding/chat` |

---

### 8. 钓鱼网站模板检索接口

基于模板类型进行精确匹配检索。

**请求**
```
POST /embedding/retrieve_for_phish
```

**请求参数**
```json
{
  "question": "银行登录页面",
  "template_type": "banking"
}
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| question | string | 是 | 检索问题 |
| template_type | string | 是 | 模板类型 |

**响应**
```json
{
  "code": 200,
  "msg": "success",
  "data": [
    {
      "text": "匹配的模板内容",
      "score": 0.92,
      "metadata": {...}
    }
  ]
}
```

---

### 9. 思维导图生成接口

根据文本内容生成思维导图结构（供前端渲染为可视化思维导图）。

**请求**
```
POST /visualization/mindmap
```

**请求参数**
```json
{
  "text": "机器学习通常分为有监督学习（Supervised Learning）和无监督学习（Unsupervised Learning）两大类。有监督学习（Supervised Learning）线性回归、逻辑回归、SVM，无监督学习（Unsupervised Learning）： K-Means、层次聚类、PCA"
}
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| text | string | 是 | 用于生成思维导图的文本内容 |

**响应**
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

**思维导图结构说明**

| 字段 | 类型 | 说明 |
|------|------|------|
| title | string | 节点标题 |
| children | array | 子节点列表（可选） |
| children[].title | string | 子节点标题 |
| children[].children | array | 孙节点列表（可选） |

---

### 10. Mermaid 图表生成接口

根据文本内容生成 Mermaid 图表结构（供前端渲染为可视化图表）。

**请求**
```
POST /visualization/mermaid
```

**请求参数**
```json
{
  "text": "用户登录系统后，先验证身份，然后查询权限，最后返回结果"
}
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| text | string | 是 | 用于生成 Mermaid 图表的文本内容 |

**响应**
```json
{
  "code": 200,
  "msg": "success",
  "data": {
    "mermaid": "graph TD\nA[用户登录] --> B[验证身份]\nB --> C[查询权限]\nC --> D[返回结果]"
  }
}
```

---

### 10. Deep Research 网页结构化生成接口

根据文本内容生成 Deep Research 报告 JSON（供前端渲染成包含文字分析、思维导图、图表与表格的可视化网页）。

**请求**
```
POST /visualization/webpage
```

**请求参数**
```json
{
  "text": "2024年，全球人工智能（AI）市场规模达到4500亿美元，同比增长25%，继续保持高速扩张态势。过去五年，全球AI市场持续增长，市场规模从2020年的2100亿美元增长至2021年的2600亿美元、2022年的3200亿美元、2023年的3600亿美元，并在2024年突破4500亿美元，显示出人工智能技术正加速渗透至各行各业。从区域分布来看，北美市场仍然占据全球领先地位，市场规模约为1800亿美元，占全球市场总量的40%。亚太地区增长最快，市场规模达到1575亿美元，占比35%，其中中国、日本和韩国是主要推动力量。欧洲市场规模约为900亿美元，占比20%，主要受制造业智能化和企业数字化转型推动。拉丁美洲、中东及非洲等新兴市场合计占比约5%，虽然整体规模较小，但增长潜力巨大。从行业应用角度分析，生成式人工智能和大模型相关应用成为2024年最重要的增长引擎，占整体AI市场的30%。智能制造占比22%，主要应用于工业质检、设备预测性维护和生产流程优化。金融科技领域占比18%，应用场景包括智能风控、算法交易和客户服务自动化。医疗健康领域占比15%，主要包括医学影像分析、药物研发和智能诊断。零售与电商领域占比10%，主要用于个性化推荐和供应链优化。其他行业应用合计占比5%。从技术投入结构来看，企业在AI基础设施上的投入持续增加。2024年，AI算力基础设施投资达到1200亿美元，占整体市场的27%；模型训练与开发平台投入约900亿美元，占比20%；行业解决方案和应用层服务投入达到1800亿美元，占比40%；AI安全治理与合规相关投入约600亿美元，占比13%。主要市场参与者方面，OpenAI、Google、Microsoft、Amazon和Meta仍然处于全球领先地位。其中，Microsoft市场份额约为18%，Google占15%，OpenAI占12%，Amazon占10%，Meta占8%，其他企业合计占37%。随着开源模型生态的发展，越来越多初创企业和区域性科技公司正在进入市场，推动行业竞争进一步加剧。未来几年，人工智能市场预计仍将保持快速增长。预计到2025年，全球AI市场规模将达到5600亿美元；到2026年有望突破6800亿美元。推动增长的关键因素包括生成式AI商业化落地、企业数字化转型需求提升，以及各国政府对人工智能基础设施和监管体系的持续投入。总体来看，人工智能正从技术创新阶段逐步迈向产业规模化应用阶段，成为推动全球经济增长和产业升级的重要核心力量。",
  "enable_web_search": false,
  "web_search_query": "",
  "web_search_count": 3,
  "web_search_answer": false
}
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| text | string | 是 | 用于生成 Deep Research 报告的文本内容 |
| enable_web_search | boolean | 否 | 是否启用可选 Web Search 补充信息，默认 false |
| web_search_query | string | 否 | 自定义搜索词；为空时根据 text 自动生成 |
| web_search_count | integer | 否 | 搜索返回条数，默认 3，最大值由 `WEB_SEARCH_MAX_COUNT` 控制（默认 10） |
| web_search_answer | boolean | 否 | 是否请求搜索侧 AI 总结，默认 false（开启会增加延迟） |

Web Search 是 `/visualization/webpage` 的可选增强能力，不接 RAG，不影响 mindmap/mermaid。启用后会把搜索来源作为补充上下文注入 Deep Research；搜索失败或无结果时接口自动降级为纯文本报告，并在 `metadata.warnings` 中记录原因。

**两层开关（易混淆，请注意）：**

| 开关 | 位置 | 说明 |
|------|------|------|
| `enable_web_search` | API 请求体 / Demo 勾选 | 单次请求是否尝试 Web Search，默认 `false` |
| `WEB_SEARCH_ENABLED` | `.env` 服务端配置 | 管理员能力开关，默认 `true`；若为 `false` 会返回 `web_search_disabled` |

本地开发请复制 `.env.example` 为 `.env`，并确认 `WEB_SEARCH_ENABLED=true`、`WEB_SEARCH_URL` 可访问。

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
    "conclusion": {
      "id": "8",
      "headline": "一句话总判断",
      "problem_analysis": "综合判断",
      "root_causes": "关键驱动",
      "strategic_implications": "战略启示",
      "text": "展望收束",
      "disclaimer": "研究说明"
    },
    "outlook_trends": [
      {"id": "8.1", "title": "趋势要点", "description": "基于前文分析的展望说明"}
    ],
    "recommendations": [],
    "sources": [],
    "metadata": {
      "id": "10",
      "visualization_type": "deep_research_webpage",
      "schema_version": "1.0",
      "chart_count": 1,
      "section_count": 1,
      "finding_count": 1,
      "source_count": 0,
      "cited_source_count": 0,
      "web_search_retrieved_count": 0,
      "web_search_requested": false,
      "web_search_enabled": false
    }
  }
}
```

**模块说明**

| 模块 | id | 说明 |
|------|-----|------|
| title | "1" | 页面标题 |
| summary | "2" | 执行摘要（不超过400字，Deep Research 风格） |
| kpis | "2.x" | 关键指标卡片，建议 3~6 个 |
| research_overview | "3" | 研究问题、范围和方法 |
| sections | "5.x" | OIIUO+mechanism 深度分析；`used_source_ids` 结构化来源；启用 Web Search 时正文分析句末可含 `[sN]`，须与 `used_source_ids` 一致 |
| key_findings | "4.x" | 核心发现；`used_source_ids` 可选；evidence 为空 |
| charts | "7.x" | `chart_insight`、`interpretation`、`data_confidence`、`data_source_refs`、`data_notes` |
| recommendations | "9.x" | `target`/`rationale`/`action`/`priority`(P0\|P1\|P2)/`risk`/`used_source_ids` |
| mindmap | "6" | 思维导图结构（包含 nodes 数组） |
| conclusion | "8" | 结构化总结：headline / problem_analysis / root_causes / strategic_implications / text / disclaimer（兼容仅 text） |
| outlook_trends | "8.x" | 展望要点卡片（0~6 条），展示于总结章节 |
| cross_section_insights | - | 跨章节关联洞察（0~3 条，展示于总结章节） |
| sources | - | **仅包含报告实际引用的来源**（后端按 `[sN]`/`used_source_ids` 过滤）；章节/图表通过 `used_source_ids`/`data_source_refs` 引用 |
| metadata | "10" | 含 `schema_version`、`research_complexity`、`complexity_reason`、`degraded`、`partial_recovery`、`quality_banner` 等 |

**来源与引用策略**

- `sources` 只列出报告中**实际被引用**的来源，按正文首次出现顺序排列；每项含 `cite_no`（展示用 `[1][2]…`，与正文引用序号一致）。`metadata.cited_source_count` = 已引用数，`metadata.web_search_retrieved_count` = 检索到的总数（前端展示「N 条已引用（检索 M 条）」）。
- 引用以模型自身标注为准；仅当全报告完全无引用时，后端做最小、单锚点的低置信兜底，并追加 `low_confidence_refs` 警告，提示来源关联为启发式补全。
- `metadata.schema_version` 标识报告结构契约版本，破坏性变更时递增。

**metadata 质量字段示例**

```json
{
  "degraded": false,
  "partial_recovery": false,
  "research_complexity": "standard",
  "complexity_reason": "具备明确研究主题，适合标准研究报告",
  "warnings": ["source_marker_stripped"],
  "quality_issues": [
    { "level": "info", "code": "source_marker_stripped", "message": "部分正文来源标记已被清理。" }
  ],
  "quality_banner": ["部分正文来源标记已被清理。"]
}
```

**Web Search 成功与失败**

- 成功：`metadata.web_search_enabled=true`，`sources` 非空，sections/charts 可含 `used_source_ids`/`data_source_refs`
- 失败或无来源：`metadata.web_search_enabled=false`，`quality_banner` 可能提示「Web Search 未获得有效来源」，报告仍 200 返回

**本地预览**

- 接口成功后自动原子写入 `output/last-webpage-response.json`（本地 demo/debug，非生产多用户存储）
- 浏览器打开 `GET /visualization/demo?render=latest` 渲染最近一次报告

完整 JSON 字段说明见 [docs/deep-research-schema.md](docs/deep-research-schema.md)。

**编号规则**

- title："1"
- summary："2"
- research_overview："3"
- key_findings："4.1", "4.2"...
- sections："5.1", "5.2"...
- mindmap："6"，节点从 "6.1" 开始
- charts："7.1", "7.2"...
- conclusion："8"
- outlook_trends："8.1", "8.2"...
- recommendations："9.1", "9.2"...
- metadata："10"

**图表约束**

- 图表数量由**数据可可视化价值**决定，不由输入长度决定
- 分析深度由 `metadata.research_complexity` 引导
- `charts[].type` 支持：`bar`、`line`、`pie`、`table`、`area`、`horizontal_bar`、`scatter`、`radar`、`gauge`、`funnel`、`donut`、`stacked_bar`、`heatmap`
- `charts` 数量不设上限
- `table` 不单独使用 `tables` 字段，统一作为 `charts[].type = "table"`

---

## 错误码说明

| HTTP状态码 | 说明 |
|-----------|------|
| 200 | 请求成功 |
| 400 | 参数校验失败 / 模型一致性校验失败 |
| 404 | 资源不存在 |
| 500 | 服务器内部错误 |

---

## 知识库元数据管理

系统使用 `rag.kb_metadata` 表记录每个知识库绑定的 embedding 模型信息。

### 数据库表结构

```sql
CREATE TABLE IF NOT EXISTS rag.kb_metadata (
    kb_id BIGINT PRIMARY KEY,           -- 知识库ID
    tenant_id BIGINT NOT NULL,          -- 租户ID
    embedding_model VARCHAR(100) NOT NULL,  -- 使用的embedding模型名称
    embedding_dim INT NOT NULL,         -- 向量维度
    created_at BIGINT NOT NULL,         -- 创建时间戳
    updated_at BIGINT NOT NULL          -- 更新时间戳
);
```

### 管理操作

**查看知识库模型信息**
```sql
SELECT kb_id, tenant_id, embedding_model, embedding_dim
FROM rag.kb_metadata
WHERE kb_id = 123;
```

**手动更新知识库模型（谨慎操作）**
```sql
UPDATE rag.kb_metadata
SET embedding_model = 'new-model', embedding_dim = 1024
WHERE kb_id = 123;
```

**删除知识库元数据**
```sql
DELETE FROM rag.kb_metadata WHERE kb_id = 123;
```

### 注意事项

1. **首次查询前必须先构建**：查询时如果 KB 没有元数据记录会返回 400 错误
2. **跨模型查询不允许**：不能同时查询使用不同 embedding 模型的知识库
3. **模型变更会触发重建**：向已有 KB 传入不同模型时会更新绑定关系

---

## GraphRAG 对接配置

| 环境变量 | 说明 | 默认值 |
|----------|------|--------|
| `graphrag_base_url` | GraphRAG 服务地址 | `http://localhost:8001` |
| `graphrag_timeout` | 请求超时（秒） | `120` |
| `graphrag_enabled` | 是否启用 GraphRAG 对接 | `true` |
| `graphrag_chunk_size` | GraphRAG 建图默认切块大小 | `500` |
| `graphrag_chunk_overlap` | GraphRAG 建图默认切块重叠 | `50` |
| `graphrag_poll_interval` | 建图进度后台轮询间隔（秒） | `2` |

**RAG 对外接口 ↔ GraphRAG 内部子接口：**

| RAG 对外接口 | GraphRAG 子接口 | 说明 |
|--------------|-----------------|------|
| `POST /embedding/process`（`build_graph=true`） | `POST /api/text/process` | 提交文本建图 |
| `GET /embedding/process/{task_id}/graph-progress` | `GET /api/text/progress/{task_id}` | 查询建图进度 |
| `POST /embedding/query`（`include_graph=true`） | `POST /api/query` | 图谱上下文召回（`return_context=true`） |
| `GET /embedding/graph/domain-presets` | `GET /api/text/domain-presets` | 领域预设列表 |
| `POST /embedding/delete`（`delete_graph=true`） | `DELETE /api/knowledge/by-file` | 按 file_id 删图谱 |

**文成对接入口（与 GraphRAG 集成文档对齐）：**

| 集成文档描述 | RAG 实际接口 |
|--------------|--------------|
| 文件上传建图 | `POST /embedding/process`（`build_graph=true`） |
| 查询处理/建图进度 | `GET /embedding/process/{task_id}`、`GET /embedding/process/{task_id}/graph-progress` |
| 问答图谱上下文 | `POST /embedding/query`（`include_graph=true`） |
| 领域预设 | `GET /embedding/graph/domain-presets` |
| 删文件/删图谱 | `POST /embedding/delete`（`delete_graph=true`） |

---

## 规划暂未实现

以下能力经评估后**暂不实现**，留作后续迭代参考：

| 能力 | 说明 |
|------|------|
| 数据库模式建图 | `db_config` 数据源暂不支持 `build_graph`；需先约定 SQL 结果与 `file_id` 的映射规则 |
| `/embedding/embed` 补建图 | 任务创建时未开 `build_graph`，或建图失败后，无法通过 embed 接口单独补提交 GraphRAG；需重新 `POST /embedding/process` 并 `build_graph=true`，或后续新增专用补建接口 |
| `/documents/upload` 路径别名 | 不新增对外路径；文成继续调用现有 `/embedding/process` 等接口，由 RAG 内部对接 GraphRAG |
| `/embedding/chat` 问答生成 | 最终 LLM 作答由文成负责；rag-system 仅提供多路召回（`vector_results` + `graph_context`） |

---

## 服务启动

```bash
python api.py
```

或使用 uvicorn：

```bash
uvicorn api:app --host 0.0.0.0 --port 8000
```
