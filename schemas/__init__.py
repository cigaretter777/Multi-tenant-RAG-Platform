"""
请求/响应数据模型
使用 Pydantic 进行参数校验和序列化
"""
from typing import List, Optional, Any, Literal, Dict
from pydantic import BaseModel, Field, field_validator, model_validator


# ============ 通用响应模型 ============

class ApiResponse(BaseModel):
    """统一响应格式"""
    code: int = Field(default=200, description="状态码")
    msg: str = Field(default="success", description="消息")
    data: Any = Field(default=None, description="数据")


# ============ 请求模型 ============

class KbInfo(BaseModel):
    """知识库信息"""
    id: int = Field(..., description="知识库ID")
    name: Optional[str] = Field(None, description="知识库名称")


class QueryRequest(BaseModel):
    """统一查询请求 - 支持向量/混合检索及可选 GraphRAG 图谱上下文"""
    question: str = Field(..., min_length=1, description="查询问题")
    tenant_id: int = Field(..., description="租户ID")
    collection: str = Field(default="common_slice", description="集合名称")
    kb_id_list: List[KbInfo] = Field(default_factory=list, description="知识库ID列表")
    similarity_threshold: float = Field(default=0.5, ge=0, le=1, description="相似度阈值")
    similarity_top_k: int = Field(default=3, ge=1, le=100, description="返回结果数量")
    mode: Literal["naive", "hybrid"] = Field(default="naive", description="检索模式: naive=朴素向量检索, hybrid=混合检索")
    alpha: float = Field(default=0.5, ge=0, le=1, description="向量检索权重 (混合检索时有效, 0-1)")
    include_graph: bool = Field(default=False, description="是否并行调用 GraphRAG 图谱上下文召回")
    graph_strategy: Literal["local", "global", "mix"] = Field(
        default="mix",
        description="GraphRAG 图谱查询策略",
    )
    graph_context: Optional[str] = Field(
        default=None,
        description="GraphRAG local 策略可选的实体周边上下文 hint",
    )

    @field_validator('kb_id_list')
    @classmethod
    def validate_kb_id_list(cls, v):
        if not v:
            raise ValueError('kb_id_list 不能为空')
        return v


# ============ 数据库接入相关模型 ============

class DatabaseConfig(BaseModel):
    """数据库连接配置"""
    db_type: Literal["postgresql", "mysql", "oracle", "mssql", "sqlite"] = Field(
        ..., description="数据库类型"
    )
    host: str = Field(..., description="数据库主机地址")
    port: int = Field(..., ge=1, le=65535, description="数据库端口")
    database: str = Field(..., description="数据库名称")
    user: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")


class DatabaseQueryConfig(BaseModel):
    """单个数据库查询配置"""
    query: str = Field(..., min_length=1, description="只读 SQL 查询语句")
    text_column: str = Field(..., description="作为 Document.text 的列名")
    metadata_columns: Optional[List[str]] = Field(
        None, description="作为 metadata 的列名列表，为空则全部其他列作为 metadata"
    )


# ============ 保留的请求/响应模型 ============

class ProcessRequest(BaseModel):
    """通用处理请求 - 支持文件或数据库数据源"""
    # 文件模式参数
    file_list: Optional[List[Dict[str, Any]]] = Field(
        None, description="文件列表, 需包含 file_id, name, path（文件模式必填）"
    )
    is_guard: bool = Field(False, description="是否开启防护（仅文件模式有效）")
    enable_vl_model: bool = Field(False, description="是否启用VL模型处理图片（仅文件模式有效）")

    # 数据库模式参数
    db_config: Optional[DatabaseConfig] = Field(
        None, description="数据库连接配置（数据库模式必填）"
    )
    queries: Optional[List[DatabaseQueryConfig]] = Field(
        None, description="SQL 查询配置列表（数据库模式必填）"
    )
    max_rows: int = Field(10_000, ge=1, le=1_000_000, description="单个查询最大允许读取行数（仅数据库模式有效）")
    page_size: int = Field(500, ge=100, le=50_000, description="流式分页大小（仅数据库模式有效）")

    # 通用参数
    tenant_id: int = Field(..., description="租户ID")
    kb_id: int = Field(..., description="知识库ID")
    chunk_size: int = Field(300, description="切块大小")
    chunk_overlap: int = Field(100, description="重叠大小")
    embedding_model: Optional[str] = Field(None, description="Embedding模型名称，为空则使用系统默认模型")
    embedding_dim: Optional[int] = Field(None, description="向量维度，为空则使用系统默认维度")

    # GraphRAG 建图（仅文件模式有效）
    build_graph: bool = Field(default=False, description="是否同步提交 GraphRAG 文本建图")
    domain_brief: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            'GraphRAG domain_brief：preset(general/cyber_security/medical/legal/finance)、'
            'domain_description、output_language(默认zh)、strictness(literal/normal)'
        ),
    )
    graph_chunk_size: Optional[int] = Field(
        default=None,
        ge=1,
        description="GraphRAG 建图切块大小（字符），为空使用服务默认 500",
    )
    graph_chunk_overlap: Optional[int] = Field(
        default=None,
        ge=0,
        description="GraphRAG 建图切块重叠（字符），为空使用服务默认 50",
    )

    @model_validator(mode='after')
    def check_source(self):
        has_files = self.file_list is not None and len(self.file_list) > 0
        has_db = self.db_config is not None
        if not has_files and not has_db:
            raise ValueError('必须提供 file_list 或 db_config')
        if has_files and has_db:
            raise ValueError('file_list 和 db_config 不能同时提供')
        if has_db and (self.queries is None or len(self.queries) == 0):
            raise ValueError('数据库模式下必须提供 queries')
        return self


# 保留旧名称作为别名，保持向后兼容
ProcessFilesRequest = ProcessRequest


class ProcessStatusResponse(BaseModel):
    """任务状态响应"""
    task_id: str
    parse_status: str  # pending, processing, finish, failed
    embed_status: str  # pending, processing, finish, failed
    file_count: int
    created_at: int
    updated_at: int
    error_message: Optional[str] = None
    graph_status: Optional[str] = None  # skipped, pending, processing, finish, failed
    graph_task_id: Optional[str] = None
    graph_error: Optional[str] = None


class EmbedTaskRequest(BaseModel):
    """向量化任务请求"""
    task_id: str
    chunk_size: Optional[int] = 300
    chunk_overlap: Optional[int] = 100
    embedding_model: Optional[str] = None    # 向量模型名称，默认为None使用全局配置
    embedding_dim: Optional[int] = None      # 向量维度，默认为None使用全局配置


class DeleteDocumentsRequest(BaseModel):
    """删除文档向量及解析缓存请求"""
    tenant_id: int = Field(..., description="租户ID")
    kb_id: int = Field(..., description="知识库ID")
    file_ids: List[int] = Field(..., min_length=1, description="要删除的文档 file_id 列表")
    collection: str = Field(default="common_slice", description="Milvus 集合名")
    delete_graph: bool = Field(default=False, description="是否同步删除 GraphRAG 图谱中对应文件的实体/关系")


# ============ 用户确认相关模型 ============

class FileConfirmationItem(BaseModel):
    """单个文件确认项"""
    file_id: int = Field(..., description="文件ID")
    use_semantic: bool = Field(..., description="是否使用语义清洗后的文本")


class ConfirmSemanticTextRequest(BaseModel):
    """用户确认语义清洗文本请求（列表形式）"""
    task_id: str = Field(..., description="任务ID")
    confirmations: List[FileConfirmationItem] = Field(..., description="确认列表")


# ============ 可视化相关模型 ============

class MindmapRequest(BaseModel):
    """思维导图生成请求"""
    text: str = Field(..., min_length=1, description="用于生成思维导图的文本内容")


class MermaidRequest(BaseModel):
    """Mermaid 图表生成请求"""
    text: str = Field(..., min_length=1, description="用于生成 Mermaid 图表的文本内容")


class WebpageRequest(BaseModel):
    """网页结构化生成请求"""
    text: str = Field(..., min_length=1, description="用于生成网页结构化内容的文本内容")
    enable_web_search: bool = Field(default=False, description="是否启用可选 Web Search 补充信息")
    web_search_query: Optional[str] = Field(default=None, max_length=300, description="可选 Web Search 查询词，为空时根据 text 自动生成")
    web_search_count: Optional[int] = Field(default=None, ge=1, le=10, description="可选 Web Search 返回条数，上限与 WEB_SEARCH_MAX_COUNT 一致")
    web_search_answer: Optional[bool] = Field(default=None, description="是否请求搜索侧 AI 总结")
