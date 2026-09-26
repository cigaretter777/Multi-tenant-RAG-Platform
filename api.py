import nltk
from pathlib import Path
from typing import Dict, Any

import uvicorn
from fastapi import FastAPI, Request, Depends, HTTPException, BackgroundTasks
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool
from pymilvus import MilvusClient


# NLTK 配置
def no_download(*args, **kwargs):
    raise RuntimeError("NLTK download disabled")


nltk.download = no_download
nltk.data.path.clear()
nltk.data.path.append("tmp/nltk_data")
from nltk.corpus import stopwords
# print(stopwords.words('english')[:10]) # 可选：启动时打印测试

from configs.config import (
    EMB_ENV, MILVUS_CONFIG, MILVUS_CONFIG_TEST,
    SIMILARITY_THRESHOLD, SIMILARITY_TOP_K,
    settings
)
from utils.logger import get_logger
from utils.response import success_response, error_response, handle_exception
from utils.embedding import embedding_service, get_index
from utils.security_validation import retrieve_for_phish

from schemas import (
    QueryRequest,
    ApiResponse, KbInfo,
    # 保留的 schemas
    ProcessFilesRequest, ProcessStatusResponse, EmbedTaskRequest,
    DeleteDocumentsRequest,
    # 用户确认相关 schemas
    ConfirmSemanticTextRequest,
    # 可视化相关 schemas
    MindmapRequest,
    # Mermaid 图表相关 schemas
    MermaidRequest,
    # 网页结构化相关 schemas
    WebpageRequest
)
from services import QueryService, DocumentService, VisualizationService

logger = get_logger()

# ============ FastAPI 应用 ============

app = FastAPI(
    title="Embedding Service",
    description="向量嵌入和检索服务",
    version="1.1.0"
)

# ============ 全局变量 ============

milvus_cfg: Dict[str, Any] = {}
query_service: QueryService = None
document_service: DocumentService = None
visualization_service: VisualizationService = None


# ============ 依赖注入 ============

def get_query_service() -> QueryService:
    return query_service


def get_document_service() -> DocumentService:
    return document_service


def get_visualization_service() -> VisualizationService:
    return visualization_service


# ============ 启动和关闭事件 ============

@app.on_event("startup")
async def startup_event():
    """应用启动时初始化"""
    global milvus_cfg, query_service, document_service, visualization_service

    logger.info("========== 服务启动中 ==========")

    if settings.visualization_only:
        visualization_service = VisualizationService()
        logger.info("仅启动知识可视化接口，跳过 Milvus/Embedding/PostgreSQL 初始化")
        logger.info(
            "Web Search 配置: enabled=%s provider=%s url=%s",
            settings.web_search_enabled,
            settings.web_search_provider,
            settings.web_search_url or "(未配置)",
        )
        if not settings.web_search_enabled:
            logger.warning(
                "WEB_SEARCH_ENABLED=false：Demo/API 勾选 Web Search 时将返回 web_search_disabled，请在 .env 中开启"
            )
        return

    # 根据环境选择 Milvus 配置
    if EMB_ENV == 'test':
        milvus_cfg = MILVUS_CONFIG_TEST
    else:
        milvus_cfg = MILVUS_CONFIG

    # [修复] Monkey patch MilvusClient 使用 'default' 连接别名
    # 解决 llama-index MilvusVectorStore 内部使用旧版 connections API 的兼容性问题
    from pymilvus import MilvusClient
    _original_milvusclient_init = MilvusClient.__init__
    def _patched_milvusclient_init(self, *args, **kwargs):
        _original_milvusclient_init(self, *args, **kwargs)
        self._using = 'default'
    MilvusClient.__init__ = _patched_milvusclient_init

    # 建立旧版 connections 连接（供 MilvusVectorStore 内部 Collection 使用）
    from pymilvus import connections
    connections.connect(
        alias='default',
        uri=milvus_cfg['uri'],
        user=milvus_cfg['user'],
        password=milvus_cfg['password'],
        db_name=milvus_cfg['db_name'],
    )
    logger.info("Milvus 默认连接已建立（compatibility patch）")

    # 初始化 embedding 服务
    embedding_service()
    logger.info("Embedding 模型加载成功")

    # 初始化 PostgreSQL 数据库
    from utils.db import init_database
    await init_database()
    logger.info("PostgreSQL 数据库初始化完成")

    # 初始化服务（服务内部会懒加载 Milvus 连接）
    logger.info(f"Milvus 配置已加载: {milvus_cfg['uri']}")
    query_service = QueryService(None, milvus_cfg)
    document_service = DocumentService(None, milvus_cfg)
    visualization_service = VisualizationService()
    logger.info("服务初始化完成")

    # 启动定时清理任务（使用异步方式）
    from utils.scheduler import start_parse_cleanup_scheduler
    await start_parse_cleanup_scheduler()
    logger.info("定时清理任务已启动")


@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭时清理资源"""
    logger.info("========== 服务关闭中 ==========")

    if settings.visualization_only:
        logger.info("仅启动知识可视化接口，无需清理 Milvus/PostgreSQL/调度器资源")
        return

    # 关闭调度器
    from utils.scheduler import shutdown_scheduler
    await shutdown_scheduler()

    # 关闭数据库连接
    from utils.db import close_database
    await close_database()

    logger.info("资源清理完成")


# ============ 全局异常处理 ============

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    error_msg = "; ".join([f"{e['loc'][0] if e['loc'] else 'field'}: {e['msg']}" for e in errors])
    logger.warning(f"参数校验失败: {error_msg}")
    return JSONResponse(
        status_code=400,
        content=error_response(data=error_msg, msg="参数校验失败", code=400)
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content=handle_exception(exc)
    )

# 1. 处理接口 (调度入口) - 支持文件或数据库数据源
@app.post("/embedding/process", response_model=ApiResponse)
async def process_interface(
        request: ProcessFilesRequest,
        background_tasks: BackgroundTasks,
        service: DocumentService = Depends(get_document_service)
):
    """
    [处理接口] 提交处理任务
    - 文件模式: 解析+向量化
    - 数据库模式: 读取+向量化
    - 流程：创建任务 -> 立即返回 task_id -> 后台执行
    """
    is_db_mode = request.db_config is not None
    source_desc = "database" if is_db_mode else f"files={len(request.file_list or [])}"
    logger.info(f"收到调度请求: tenant_id={request.tenant_id}, source={source_desc}")
    try:
        request_dict = request.dict()

        if is_db_mode:
            # 数据库模式
            task_id = await service.create_process_task(request_dict)
            background_tasks.add_task(
                service.run_database_process_pipeline, task_id, request_dict
            )
            return success_response(data={
                "task_id": task_id,
                "parse_status": "pending",
                "embed_status": "pending"
            })
        else:
            # 文件模式（原有逻辑）
            task_id = await service.create_process_task(request_dict)
            background_tasks.add_task(service.run_process_pipeline, task_id, request_dict)
            return success_response(data={
                "task_id": task_id,
                "parse_status": "pending",
                "embed_status": "pending"
            })
    except Exception as e:
        logger.error(f"任务提交失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/embedding/parse", response_model=ApiResponse)
async def parse_interface(
        request: ProcessFilesRequest,
        background_tasks: BackgroundTasks,
        service: DocumentService = Depends(get_document_service)
):
    """
    [纯解析/读取接口]
    - 文件模式: 解析文件，存入 PostgreSQL
    - 数据库模式: 读取数据库数据，存入 PostgreSQL
    """
    is_db_mode = request.db_config is not None
    source_desc = "database" if is_db_mode else f"files={len(request.file_list or [])}"
    logger.info(f"收到解析请求: tenant_id={request.tenant_id}, source={source_desc}")
    try:
        request_dict = request.dict()
        task_id = await service.create_process_task(request_dict)

        if is_db_mode:
            background_tasks.add_task(
                service.run_database_parse_only_pipeline, task_id, request_dict
            )
        else:
            background_tasks.add_task(service.run_parse_only_pipeline, task_id, request_dict)

        return success_response(data={"task_id": task_id, "parse_status": "pending"})
    except Exception as e:
        logger.error(f"解析任务提交失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/embedding/embed", response_model=ApiResponse)
async def embed_interface(
        request: EmbedTaskRequest,
        background_tasks: BackgroundTasks,
        service: DocumentService = Depends(get_document_service)
):
    """
    [纯向量化接口] 直接使用已有任务 ID 触发向量化流程
    - 支持文件任务和数据库任务
    """
    logger.info(f"收到向量化触发请求: task_id={request.task_id}")
    try:
        # 1. 获取任务详情，确保任务存在且解析已完成
        task_info = await service.get_task_status(request.task_id)

        # 检查解析状态
        if task_info['parse_status'] == 'waiting_confirmation':
            return error_response(
                msg="文档解析完成，但需要用户确认是否使用语义清洗后的文本。请调用 /embedding/confirmation/{task_id}获取待确认文件列表，确认后再调用 /embedding/continue/{task_id} 继续向量化",
                code=400,
                data={"needs_confirmation": True, "confirmation_status": task_info.get('confirmation_status', 'pending')}
            )
        elif task_info['parse_status'] not in ('finish', 'skipped'):
            return error_response(msg="文档/数据尚未解析完成，无法开始向量化", code=400)

        # 2. 异步执行向量化 Pipeline
        background_tasks.add_task(
            service.run_embed_only_pipeline,
            request.task_id,
            task_info,
            request.chunk_size,
            request.chunk_overlap,
            request.embedding_model,
            request.embedding_dim
        )

        return success_response(data={"task_id": request.task_id, "embed_status": "processing"})
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"向量化触发失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# 2. 状态查询接口
@app.get("/embedding/process/{task_id}", response_model=ApiResponse)
async def status_query_interface(
        task_id: str,
        service: DocumentService = Depends(get_document_service)
):
    """
    [状态查询接口] 查询任务进度
    """
    try:
        status = await service.get_task_status(task_id, sync_graph=True)

        result = {
            "task_id": status['task_id'],
            "parse_status": status['parse_status'],
            "embed_status": status['embed_status'],
            "file_count": status['file_count'],
            "created_at": status['created_at'],
            "updated_at": status['updated_at'],
            "error_message": status.get('error_message'),
            "graph_status": status.get('graph_status', 'skipped'),
            "graph_task_id": status.get('graph_task_id'),
            "graph_error": status.get('graph_error'),
        }
        return success_response(data=result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/embedding/process/{task_id}/graph-progress", response_model=ApiResponse)
async def graph_progress_interface(
        task_id: str,
        service: DocumentService = Depends(get_document_service)
):
    """
    [GraphRAG 建图进度] 查询任务关联的 GraphRAG 细粒度建图进度
    """
    try:
        result = await service.get_graph_progress(task_id)
        return success_response(data=result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"查询 GraphRAG 建图进度失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/embedding/graph/domain-presets", response_model=ApiResponse)
async def graph_domain_presets_interface(
        tenant_id: int,
        kb_id: int,
        service: DocumentService = Depends(get_document_service)
):
    """
    [GraphRAG 领域预设] 代理 GraphRAG GET /api/text/domain-presets，供上传表单展示
    """
    try:
        result = await service.get_graph_domain_presets(tenant_id=tenant_id, kb_id=kb_id)
        return success_response(data=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"查询 GraphRAG 领域预设失败: {str(e)}")
        raise HTTPException(status_code=502, detail=str(e))

# ============ 用户确认相关 API 路由 ============

@app.post("/embedding/confirm", response_model=ApiResponse)
async def confirm_semantic_text_interface(
    request: ConfirmSemanticTextRequest,
    service: DocumentService = Depends(get_document_service)
):
    """
    [确认语义文本接口] 确认是否使用语义清洗后的文本（列表形式）

    请求示例:
    {
        "task_id": "abc123",
        "confirmations": [
            {"file_id": 1, "use_semantic": true},
            {"file_id": 2, "use_semantic": false}
        ]
    }
    """
    try:
        result = await service.confirm_semantic_text(
            task_id=request.task_id,
            confirmations=[c.dict() for c in request.confirmations]
        )
        return success_response(data=result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"确认语义文本失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ============ 原有/其他 API 路由 ============

@app.post("/embedding/delete", response_model=ApiResponse)
async def delete_documents(
        request: DeleteDocumentsRequest,
        service: DocumentService = Depends(get_document_service)
):
    """删除指定文档的 Milvus 向量切片、PostgreSQL 解析缓存，可选同步删除 GraphRAG 图谱数据"""
    logger.info(
        f"收到删除请求: tenant_id={request.tenant_id}, kb_id={request.kb_id}, "
        f"file_ids={request.file_ids}, collection={request.collection}, "
        f"delete_graph={request.delete_graph}"
    )
    try:
        result = await service.delete_documents_by_file_ids(
            tenant_id=request.tenant_id,
            kb_id=request.kb_id,
            file_ids=request.file_ids,
            collection_name=request.collection,
            delete_graph=request.delete_graph,
        )
        return success_response(data=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"删除文档失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/embedding/query", response_model=ApiResponse)
async def query_embedding(
        request: QueryRequest,
        service: QueryService = Depends(get_query_service)
):
    """统一检索接口 - 向量/混合检索，可选并行 GraphRAG 图谱上下文"""
    logger.info(
        f"请求问题: {request.question}, tenant_id={request.tenant_id}, "
        f"include_graph={request.include_graph}"
    )
    kb_id_list = [{"id": kb.id, "name": kb.name} for kb in request.kb_id_list]
    try:
        result = await service.query(
            question=request.question,
            tenant_id=request.tenant_id,
            kb_id_list=kb_id_list,
            collection_name=request.collection,
            similarity_threshold=request.similarity_threshold,
            similarity_top_k=request.similarity_top_k,
            mode=request.mode,
            alpha=request.alpha,
            include_graph=request.include_graph,
            graph_strategy=request.graph_strategy,
            graph_context=request.graph_context,
        )
        return success_response(data=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/embedding/retrieve_for_phish", response_model=ApiResponse)
async def retrieve_for_phish_endpoint(request: Request):
    """钓鱼网站模板检索"""
    request_data = await request.json()
    question = request_data.get('question')
    template_type = request_data.get('template_type')

    try:
        index = get_index(collection_name="bas_template", milvus_cfg=milvus_cfg)
        result = retrieve_for_phish(index, question, template_type, 5)
        return success_response(data=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/visualization/mindmap", response_model=ApiResponse)
async def generate_mindmap(
        request: MindmapRequest,
        service: VisualizationService = Depends(get_visualization_service)
):
    """[思维导图生成] 根据文本内容生成思维导图结构"""
    logger.info(f"收到思维导图生成请求, 文本长度: {len(request.text)}")
    try:
        result = await run_in_threadpool(
            service.generate_mindmap,
            request.text
        )
        return success_response(data=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        logger.error(f"思维导图生成失败: {str(e)}")
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        logger.error(f"思维导图生成异常: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/visualization/mermaid", response_model=ApiResponse)
async def generate_mermaid_endpoint(
        request: MermaidRequest,
        service: VisualizationService = Depends(get_visualization_service)
):
    """[Mermaid图表生成] 根据文本内容生成 Mermaid 图表结构"""
    logger.info(f"收到 Mermaid 图表生成请求, 文本长度: {len(request.text)}")
    try:
        result = await run_in_threadpool(service.generate_mermaid, request.text)
        return success_response(data=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        logger.error(f"Mermaid 图表生成失败: {str(e)}")
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        logger.error(f"Mermaid 图表生成异常: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


_DEMO_PAGE = Path(__file__).resolve().parent / "static" / "visualization-demo.html"
_LAST_WEBPAGE = Path(__file__).resolve().parent / "output" / "last-webpage-response.json"


def _save_last_webpage_response(data: dict) -> None:
    """API 成功后原子写入最近一次报告，供 ?render=latest 预览。"""
    import json
    payload = {"code": 200, "msg": "success", "data": data}
    _LAST_WEBPAGE.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _LAST_WEBPAGE.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(_LAST_WEBPAGE)


@app.post("/visualization/webpage", response_model=ApiResponse)
async def generate_webpage_endpoint(
        request: WebpageRequest,
        service: VisualizationService = Depends(get_visualization_service)
):
    """[网页结构化生成] 根据文本内容生成网页结构化 JSON"""
    logger.info(
        "收到网页结构化生成请求, 文本长度: %s, Web Search: %s",
        len(request.text),
        request.enable_web_search,
    )
    try:
        result = await run_in_threadpool(
            service.generate_webpage,
            request.text,
            request.enable_web_search,
            request.web_search_query,
            request.web_search_count,
            request.web_search_answer,
        )
        try:
            _save_last_webpage_response(result)
        except OSError as exc:
            logger.warning("写入 last-webpage-response.json 失败: %s", exc)
        return success_response(data=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        logger.error(f"网页结构化生成失败: {str(e)}")
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        logger.error(f"网页结构化生成异常: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/visualization/last")
async def visualization_last_webpage():
    """返回最近一次生成的 webpage JSON（供演示页预览）"""
    if not _LAST_WEBPAGE.is_file():
        raise HTTPException(status_code=404, detail="暂无已生成的 webpage 结果")
    import json
    return JSONResponse(json.loads(_LAST_WEBPAGE.read_text(encoding="utf-8")))


@app.get("/visualization/demo")
async def visualization_demo_page():
    """知识可视化效果演示页（含示例数据与 API 调试）"""
    if not _DEMO_PAGE.is_file():
        raise HTTPException(status_code=404, detail="演示页未找到")
    return FileResponse(_DEMO_PAGE, media_type="text/html; charset=utf-8")


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        workers=1,  # 保持单进程，避免多进程的复杂性
        limit_concurrency=50,  # 限制并发请求数
        limit_max_requests=10000,  # 限制每个worker的最大请求数，防止内存泄漏
        timeout_keep_alive=30,  # 保持连接的超时时间
        access_log=True  # 启用访问日志
    )
