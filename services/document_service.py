"""
文档服务层 - 封装文档嵌入和索引创建相关业务逻辑
"""
import asyncio
import time
import uuid
import json
from typing import List, Dict, Any, Optional

from pymilvus import MilvusClient
from starlette.concurrency import run_in_threadpool
from utils.logger import get_logger
from utils.db import DatabaseManager, KBMetadataManager
from utils.parse_storage_manager import ParseStorageManager
from utils.graphrag_client import (
    delete_knowledge_by_files,
    process_text_files,
    get_text_progress,
    get_domain_presets,
    normalize_domain_brief,
    is_graph_build_complete,
)
from core.document_processor import DocumentProcessor
from configs.config import settings

logger = get_logger()

GRAPH_POLL_MAX_ATTEMPTS = 900  # 约 30 分钟（配合 2s 间隔）


class DocumentService:
    """文档服务类 - 处理文档嵌入和索引创建"""

    def __init__(self, milvus_client: MilvusClient, milvus_cfg: Dict[str, Any]):
        """
        初始化文档服务

        Args:
            milvus_client: Milvus 客户端（可为 None，懒加载）
            milvus_cfg: Milvus 配置
        """
        self._client = milvus_client
        self._client_lock = None  # 用于线程安全的懒加载
        self.milvus_cfg = milvus_cfg

    def _create_milvus_client(self):
        """创建 Milvus 客户端"""
        from pymilvus import MilvusClient
        return MilvusClient(
            uri=self.milvus_cfg['uri'],
            token=f"{self.milvus_cfg['user']}:{self.milvus_cfg['password']}",
            db_name=self.milvus_cfg['db_name']
        )

    @property
    def client(self):
        """获取 Milvus 客户端（懒加载，线程安全）"""
        if self._client is None:
            # 线程安全的单例模式
            import threading
            if self._client_lock is None:
                self._client_lock = threading.Lock()
            with self._client_lock:
                if self._client is None:
                    self._client = self._create_milvus_client()
        return self._client

    # ============ 1. 任务调度与状态管理 (Task Scheduling & Status) ============

    async def run_parse_only_pipeline(self, task_id: str, request_data: Dict[str, Any]):
        """仅解析流水线"""
        try:
            await self._update_task_status(task_id, {"parse_status": "processing", "embed_status": "skipped"})

            # 执行解析逻辑
            parse_stats = await self.smart_parse_documents(
                request_data['file_list'],
                parse_id=task_id,
                is_guard=request_data.get('is_guard', False),
                enable_vl_model=request_data.get('enable_vl_model', False)
            )

            # 检查是否需要用户确认
            if parse_stats.get("needs_confirmation"):
                await self._update_task_status(task_id, {
                    "parse_status": "waiting_confirmation",
                    "needs_confirmation": True,
                    "confirmation_status": "pending"
                })
                logger.info(f"任务 {task_id} 解析完成，等待用户确认")
            else:
                await self._update_task_status(task_id, {"parse_status": "finish"})
                logger.info(f"任务 {task_id} 解析完成，无需用户确认")
                await self._schedule_graph_build_if_ready(task_id)
        except Exception as e:
            logger.error(f"解析任务 {task_id} 失败: {str(e)}")
            await self._update_task_status(task_id, {"parse_status": "failed", "error_message": str(e)})

    async def run_embed_only_pipeline(
            self,
            task_id: str,
            task_info: Dict[str, Any],
            chunk_size: int,
            chunk_overlap: int,
            embedding_model: str = None,
            embedding_dim: int = None
    ):
        """
        [向量化流水线 V2] 基于已有 Task 状态执行

        支持文件任务（按 file_ids 读取）和数据库任务（按 parse_id 读取）。
        """
        try:
            # 更新状态为向量化中
            await self._update_task_status(task_id, {"embed_status": "processing"})
            await self._schedule_graph_build_if_ready(task_id)

            # 判断模式
            file_ids = task_info.get('file_ids', [])
            is_db_mode = not file_ids

            # [新增] 获取KB模型配置（校验或创建）
            kb_model_config = await KBMetadataManager.get_or_create_kb_model(
                kb_id=task_info['kb_id'],
                tenant_id=task_info['tenant_id'],
                requested_model=embedding_model,
                requested_dim=embedding_dim,
                default_model=settings.embedding_model_name,
                default_dim=settings.embedding_dim
            )

            logger.info(
                f"任务 {task_id} - KB {task_info['kb_id']} 使用模型: "
                f"{kb_model_config['embedding_model']} (dim={kb_model_config['embedding_dim']})"
            )

            if is_db_mode:
                # 数据库模式：从 parsed_documents 按 parse_id 读取
                logger.info(f"任务 {task_id} 数据库模式向量化")
                docs_data = await ParseStorageManager.get_documents_by_parse_id(task_id)
                if not docs_data:
                    raise ValueError(f"任务 {task_id} 未找到数据库读取记录")

                # 转换为 Document 对象
                from llama_index.core import Document
                documents = []
                for d in docs_data:
                    metadata = {}
                    if d.get('document_metadata'):
                        try:
                            metadata = json.loads(d['document_metadata'])
                        except json.JSONDecodeError:
                            metadata = {}
                    documents.append(Document(text=d.get('document_text', ''), metadata=metadata))

                logger.info(f"任务 {task_id} 从数据库读取到 {len(documents)} 个文档片段")

                # 临时切换模型配置
                original_model = settings.embedding_model_name
                original_dim = settings.embedding_dim
                try:
                    settings.embedding_model_name = kb_model_config['embedding_model']
                    settings.embedding_dim = kb_model_config['embedding_dim']
                    await run_in_threadpool(
                        self.create_index_from_documents,
                        documents=documents,
                        tenant_id=task_info['tenant_id'],
                        kb_id=task_info['kb_id'],
                        chunk_size=chunk_size,
                        chunk_overlap=chunk_overlap,
                    )
                finally:
                    settings.embedding_model_name = original_model
                    settings.embedding_dim = original_dim
            else:
                # 文件模式（原有逻辑）
                file_ids_int = [int(fid) for fid in file_ids]
                logger.info(f"任务 {task_id} 文件模式向量化，文件数: {len(file_ids_int)}")
                await self.create_index_by_file_ids(
                    file_ids=file_ids_int,
                    tenant_id=task_info['tenant_id'],
                    kb_id=task_info['kb_id'],
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    embedding_model=kb_model_config['embedding_model'],
                    embedding_dim=kb_model_config['embedding_dim']
                )

            await self._update_task_status(task_id, {"embed_status": "finish"})
            logger.info(f"任务 {task_id} 向量化成功")

        except Exception as e:
            logger.error(f"任务 {task_id} 向量化失败: {str(e)}")
            await self._update_task_status(task_id, {
                "embed_status": "failed",
                "error_message": f"向量化阶段失败: {str(e)}"
            })

    async def create_process_task(self, request_data: Dict[str, Any]) -> str:
        """
        创建处理任务并初始化状态

        兼容文件模式和数据库模式。
        """
        task_id = str(uuid.uuid4())
        current_time = int(time.time())

        # 判断模式
        is_db_mode = request_data.get('db_config') is not None

        # 提取 file_ids（文件模式）
        file_ids = []
        file_count = 0
        if not is_db_mode:
            file_ids = [
                str(f.get('file_id'))
                for f in request_data.get('file_list', [])
                if f.get('file_id')
            ]
            file_count = len(request_data.get('file_list', []))

        build_graph = bool(request_data.get('build_graph')) and not is_db_mode
        graph_status = 'pending' if build_graph else 'skipped'
        domain_brief = request_data.get('domain_brief')
        if build_graph and domain_brief:
            domain_brief = normalize_domain_brief(domain_brief)
        elif build_graph:
            domain_brief = {"preset": "general"}

        graph_chunk_size = request_data.get('graph_chunk_size')
        graph_chunk_overlap = request_data.get('graph_chunk_overlap')

        query = """
            INSERT INTO rag.process_tasks
            (task_id, tenant_id, kb_id, parse_status, embed_status, file_count, file_ids,
             build_graph_requested, graph_status, domain_brief, graph_chunk_size, graph_chunk_overlap,
             created_at, updated_at)
            VALUES ($1, $2, $3, 'pending', 'pending', $4, $5, $6, $7, $8::jsonb, $9, $10, $11, $12)
        """

        await DatabaseManager.execute(
            query,
            task_id,
            request_data['tenant_id'],
            request_data['kb_id'],
            file_count,
            file_ids,
            build_graph,
            graph_status,
            json.dumps(domain_brief) if domain_brief is not None else None,
            graph_chunk_size,
            graph_chunk_overlap,
            current_time,
            current_time
        )

        return task_id

    async def get_task_status(self, task_id: str, sync_graph: bool = False) -> Dict[str, Any]:
        """获取任务状态"""
        if sync_graph:
            await self.refresh_graph_status(task_id)

        query = "SELECT * FROM rag.process_tasks WHERE task_id = $1"
        row = await DatabaseManager.fetchrow(query, task_id)
        if not row:
            raise ValueError(f"任务不存在: {task_id}")
        return dict(row)

    def _normalize_domain_brief(self, task_info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        domain_brief = task_info.get('domain_brief')
        if isinstance(domain_brief, str):
            try:
                domain_brief = json.loads(domain_brief)
            except json.JSONDecodeError:
                domain_brief = None
        normalized = normalize_domain_brief(domain_brief)
        return normalized or {"preset": "general"}

    async def _schedule_graph_build_if_ready(self, task_id: str):
        """解析完成后异步提交 GraphRAG 建图（若已满足条件）"""
        task_info = await self.get_task_status(task_id)
        if not task_info.get('build_graph_requested'):
            return
        if task_info.get('graph_status') != 'pending':
            return
        if task_info.get('parse_status') != 'finish':
            return
        asyncio.create_task(self._submit_graph_build(task_id))

    async def _submit_graph_build(self, task_id: str):
        """提交 GraphRAG 建图任务并启动进度轮询"""
        try:
            task_info = await self.get_task_status(task_id)
            if not task_info.get('build_graph_requested'):
                return
            if task_info.get('graph_status') != 'pending':
                return
            if task_info.get('parse_status') != 'finish':
                return

            if not settings.graphrag_enabled:
                await self._update_task_status(task_id, {
                    "graph_status": "failed",
                    "graph_error": "GraphRAG 服务未启用",
                })
                logger.warning(f"任务 {task_id} build_graph=true 但 GraphRAG 未启用")
                return

            file_ids = [int(fid) for fid in (task_info.get('file_ids') or []) if fid]
            parsed_files = await ParseStorageManager.get_parsed_files_by_parse_id(
                parse_id=task_id,
                file_ids=file_ids or None,
            )
            found_ids = {item["file_id"] for item in parsed_files}
            missing_ids = [fid for fid in file_ids if fid not in found_ids]
            if missing_ids:
                docs_data = await ParseStorageManager.get_documents_by_file_ids(missing_ids)
                grouped: Dict[int, Dict[str, Any]] = {}
                for doc in docs_data:
                    fid = doc.get("metadata", {}).get("file_id")
                    if fid is None:
                        continue
                    text = doc.get("text") or ""
                    file_name = doc.get("metadata", {}).get("file_name") or f"file_{fid}"
                    if fid not in grouped:
                        grouped[fid] = {
                            "file_id": fid,
                            "file_name": file_name,
                            "document_text": text,
                        }
                    elif text:
                        grouped[fid]["document_text"] += "\n" + text
                parsed_files.extend(grouped.values())

            graph_file_list = []
            for item in parsed_files:
                content = (item.get("document_text") or "").strip()
                if not content:
                    logger.warning(
                        f"任务 {task_id} 跳过空文本文件: file_id={item.get('file_id')}"
                    )
                    continue
                graph_file_list.append({
                    "file_id": str(item["file_id"]),
                    "name": item.get("file_name") or f"file_{item['file_id']}",
                    "file_content": content,
                })

            if not graph_file_list:
                await self._update_task_status(task_id, {
                    "graph_status": "failed",
                    "graph_error": "没有可用于建图的文件文本",
                })
                return

            domain_brief = self._normalize_domain_brief(task_info)
            graph_data = await run_in_threadpool(
                process_text_files,
                task_info['tenant_id'],
                task_info['kb_id'],
                graph_file_list,
                domain_brief,
                task_info.get('graph_chunk_size'),
                task_info.get('graph_chunk_overlap'),
            )
            graph_task_id = graph_data.get("task_id")
            if not graph_task_id:
                raise RuntimeError("GraphRAG 未返回 task_id")

            await self._update_task_status(task_id, {
                "graph_status": "processing",
                "graph_task_id": graph_task_id,
                "graph_error": None,
            })
            logger.info(f"任务 {task_id} 已提交 GraphRAG 建图: graph_task_id={graph_task_id}")
            asyncio.create_task(self._poll_graph_progress(task_id))

        except Exception as e:
            logger.error(f"任务 {task_id} GraphRAG 建图提交失败: {str(e)}", exc_info=True)
            await self._update_task_status(task_id, {
                "graph_status": "failed",
                "graph_error": str(e),
            })

    async def _poll_graph_progress(self, task_id: str):
        """后台轮询 GraphRAG 建图进度直至终态"""
        poll_interval = settings.graphrag_poll_interval
        for _ in range(GRAPH_POLL_MAX_ATTEMPTS):
            await asyncio.sleep(poll_interval)
            task_info = await self.get_task_status(task_id)
            if task_info.get('graph_status') not in ('processing',):
                return
            if not task_info.get('graph_task_id'):
                return

            try:
                await self.refresh_graph_status(task_id)
            except Exception as e:
                logger.warning(f"任务 {task_id} GraphRAG 进度轮询失败: {str(e)}")

            task_info = await self.get_task_status(task_id)
            if task_info.get('graph_status') in ('finish', 'failed'):
                return

        await self._update_task_status(task_id, {
            "graph_status": "failed",
            "graph_error": "GraphRAG 建图进度轮询超时",
        })

    async def refresh_graph_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """从 GraphRAG 同步建图进度并更新任务状态"""
        task_info = await self.get_task_status(task_id)
        graph_status = task_info.get('graph_status')
        graph_task_id = task_info.get('graph_task_id')

        if graph_status in (None, 'skipped', 'pending', 'finish', 'failed'):
            return None
        if not graph_task_id:
            return None
        if not settings.graphrag_enabled:
            return None

        progress_data = await run_in_threadpool(
            get_text_progress,
            task_info['tenant_id'],
            task_info['kb_id'],
            graph_task_id,
        )
        remote_status = progress_data.get('status')
        updates: Dict[str, Any] = {}

        if remote_status == 'failed':
            updates['graph_status'] = 'failed'
            updates['graph_error'] = progress_data.get('error_message') or 'GraphRAG 建图失败'
        elif is_graph_build_complete(progress_data):
            updates['graph_status'] = 'finish'
            updates['graph_error'] = progress_data.get('error_message')
        elif remote_status in ('pending', 'processing', 'completed'):
            updates['graph_status'] = 'processing'

        if updates:
            await self._update_task_status(task_id, updates)

        return progress_data

    async def get_graph_progress(self, task_id: str) -> Dict[str, Any]:
        """获取 GraphRAG 建图细粒度进度（方案 A：挂在 RAG task 上）"""
        task_info = await self.get_task_status(task_id)
        base_result = {
            "task_id": task_id,
            "graph_status": task_info.get('graph_status', 'skipped'),
            "graph_task_id": task_info.get('graph_task_id'),
            "graph_error": task_info.get('graph_error'),
            "build_graph_requested": task_info.get('build_graph_requested', False),
        }

        if not task_info.get('build_graph_requested'):
            base_result["message"] = "未请求 GraphRAG 建图"
            return base_result

        if task_info.get('graph_status') == 'pending':
            base_result["message"] = "等待解析完成后提交建图"
            return base_result

        if not task_info.get('graph_task_id'):
            base_result["message"] = base_result.get("graph_error") or "尚未提交 GraphRAG 建图"
            return base_result

        progress_data = await self.refresh_graph_status(task_id)
        task_info = await self.get_task_status(task_id)

        result = {
            **base_result,
            "graph_status": task_info.get('graph_status'),
            "graph_error": task_info.get('graph_error'),
        }
        if progress_data:
            result.update({
                "remote_status": progress_data.get("status"),
                "progress": progress_data.get("progress"),
                "current_step": progress_data.get("current_step"),
                "total_files": progress_data.get("total_files"),
                "processed_files": progress_data.get("processed_files"),
                "entities_extracted": progress_data.get("entities_extracted"),
                "relationships_extracted": progress_data.get("relationships_extracted"),
                "entity_dedup_key_mode": progress_data.get("entity_dedup_key_mode"),
                "merge_stats_by_file": progress_data.get("merge_stats_by_file"),
                "domain_brief_submitted": progress_data.get("domain_brief_submitted"),
                "domain_extraction": progress_data.get("domain_extraction"),
                "domain_extraction_files": progress_data.get("domain_extraction_files"),
                "started_at": progress_data.get("started_at"),
                "completed_at": progress_data.get("completed_at"),
            })
        return result

    async def get_graph_domain_presets(
        self,
        tenant_id: int,
        kb_id: int,
    ) -> Dict[str, Any]:
        """代理 GraphRAG 领域预设列表"""
        if not settings.graphrag_enabled:
            raise ValueError("GraphRAG 服务未启用")

        return await run_in_threadpool(get_domain_presets, tenant_id, kb_id)

    async def _update_task_status(self, task_id: str, updates: Dict[str, Any]):
        """更新任务状态 (内部方法)"""
        set_clauses = []
        values = []
        idx = 1

        for k, v in updates.items():
            set_clauses.append(f"{k} = ${idx}")
            values.append(v)
            idx += 1

        values.append(int(time.time())) # updated_at
        values.append(task_id) # task_id

        query = f"""
            UPDATE rag.process_tasks 
            SET {', '.join(set_clauses)}, updated_at = ${idx} 
            WHERE task_id = ${idx+1}
        """
        await DatabaseManager.execute(query, *values)

    async def run_process_pipeline(self, task_id: str, request_data: Dict[str, Any]):
        """
        [调度核心] 后台处理流水线
        流程：
        1. 解析: 检查缓存 -> 下载解析 -> 存库 (不持有文档对象)
        2. 检查是否需要用户确认
        3. 向量化: 根据 file_ids 从数据库重新拉取内容 -> 向量化 -> 存 Milvus
        """
        logger.info(f"========== 调度开始: 任务 {task_id} ==========")

        try:
            # ----------------- 步骤 1: 文件解析阶段 -----------------
            await self._update_task_status(task_id, {"parse_status": "processing"})

            # 智能解析 (只执行逻辑，不返回具体文档内容)
            parse_stats = await self.smart_parse_documents(
                request_data['file_list'],
                parse_id=task_id,
                is_guard=request_data.get('is_guard', False),
                enable_vl_model=request_data.get('enable_vl_model', False)
            )
            logger.info(f"任务 {task_id} - 解析统计: {parse_stats}")

            # 检查是否需要用户确认
            if parse_stats.get("needs_confirmation"):
                await self._update_task_status(task_id, {
                    "parse_status": "waiting_confirmation",
                    "needs_confirmation": True,
                    "confirmation_status": "pending"
                })
                logger.info(f"任务 {task_id} - 解析完成，等待用户确认")
                return  # 等待用户确认后再执行向量化与建图
            else:
                await self._update_task_status(task_id, {"parse_status": "finish"})
                logger.info(f"任务 {task_id} - 解析阶段完成，无需用户确认")

            # ----------------- 步骤 2: 向量化阶段 -----------------
            await self._schedule_graph_build_if_ready(task_id)
            await self._update_task_status(task_id, {"embed_status": "processing"})

            # 提取 file_ids
            file_ids = [f['file_id'] for f in request_data['file_list'] if 'file_id' in f]

            if not file_ids:
                logger.warning(f"任务 {task_id} - 没有有效的 file_ids，跳过向量化")
            else:
                logger.info(f"任务 {task_id} - 开始从 DB 加载数据并向量化，文件数: {len(file_ids)}")

                # [新增] 获取或创建KB模型配置
                kb_model_config = await KBMetadataManager.get_or_create_kb_model(
                    kb_id=request_data['kb_id'],
                    tenant_id=request_data['tenant_id'],
                    requested_model=request_data.get('embedding_model'),
                    requested_dim=request_data.get('embedding_dim'),
                    default_model=settings.embedding_model_name,
                    default_dim=settings.embedding_dim
                )

                logger.info(
                    f"任务 {task_id} - KB {request_data['kb_id']} 使用模型: "
                    f"{kb_model_config['embedding_model']} (dim={kb_model_config['embedding_dim']})"
                )

                # 调用解耦的向量化方法，传入确定的模型参数
                await self.create_index_by_file_ids(
                    file_ids=file_ids,
                    tenant_id=request_data['tenant_id'],
                    kb_id=request_data['kb_id'],
                    chunk_size=request_data.get('chunk_size', 300),
                    chunk_overlap=request_data.get('chunk_overlap', 100),
                    embedding_model=kb_model_config['embedding_model'],
                    embedding_dim=kb_model_config['embedding_dim']
                )

            # 向量化完成 -> finish
            await self._update_task_status(task_id, {"embed_status": "finish"})
            logger.info(f"任务 {task_id} - 向量化阶段完成")

        except Exception as e:
            logger.error(f"任务 {task_id} 执行失败: {str(e)}", exc_info=True)
            error_msg = str(e)

            try:
                status = await self.get_task_status(task_id)
                update_data = {"error_message": error_msg}

                if status['parse_status'] not in ['finish', 'waiting_confirmation']:
                    update_data['parse_status'] = 'failed'
                else:
                    update_data['embed_status'] = 'failed'

                await self._update_task_status(task_id, update_data)
            except Exception:
                pass

    # ============ 2. 文件解析逻辑 (File Parsing Logic) ============

    async def smart_parse_documents(
        self,
        file_list: List[Dict[str, Any]],
        parse_id: Optional[str] = None,
        is_guard: bool = False,
        enable_vl_model: bool = False
    ) -> Dict[str, int]:
        """
        智能解析：
        1. 检查 PG 数据库缓存
        2. 对未命中的文件：下载 -> 解析 -> 存入 PG
        3. 返回统计信息 (包含是否需要确认的标识)

        Args:
            file_list: 文件列表
            parse_id: 解析ID
            is_guard: 是否开启防护模式
            enable_vl_model: 是否启用VL模型处理图片

        Returns:
            Dict: {"total_files": int, "cached_files": int, "new_files": int, "needs_confirmation": bool}
        """
        from llama_index.core import Document

        target_file_ids = [f['file_id'] for f in file_list if 'file_id' in f]
        file_map = {f['file_id']: f for f in file_list if 'file_id' in f}

        stats = {
            "total_files": len(target_file_ids),
            "cached_files": 0,
            "new_files": 0,
            "needs_confirmation": False
        }

        # 1. 检查 PG 缓存
        existing_data = await ParseStorageManager.get_documents_by_file_ids(target_file_ids)
        found_file_ids = set()

        if existing_data:
            for doc_data in existing_data:
                fid = doc_data.get('metadata', {}).get('file_id') or doc_data.get('file_id')
                if fid:
                    found_file_ids.add(fid)

            stats["cached_files"] = len(found_file_ids)
            logger.info(f"智能解析 - 命中缓存: {len(found_file_ids)} 个文件")

            # 立即释放内存
            del existing_data

        # 2. 解析缺失文件
        missing_file_ids = set(target_file_ids) - found_file_ids
        files_to_parse = [file_map[fid] for fid in missing_file_ids]

        if files_to_parse:
            logger.info(f"智能解析 - 开始解析 {len(files_to_parse)} 个新文件")
            processor = DocumentProcessor()

            # 同步耗时操作，使用 threadpool
            guarded_infos = await run_in_threadpool(
                processor.process_files_batch,
                files_to_parse,
                is_guard=is_guard,
                enable_vl_model=enable_vl_model
            )

            # 补全 metadata
            name_to_id = {f['name']: f['file_id'] for f in files_to_parse}
            for info in guarded_infos:
                fname = info.document.metadata.get('file_name')
                if fname and fname in name_to_id:
                    info.document.metadata['file_id'] = name_to_id[fname]

            # 保存新解析结果到 PG（传入 guarded_infos）
            save_result = await ParseStorageManager.save_parse_result(
                documents=guarded_infos,
                file_list=files_to_parse,
                parse_id=parse_id,
                guarded_infos=guarded_infos
            )

            stats["new_files"] = len(files_to_parse)
            stats["needs_confirmation"] = save_result.get("needs_confirmation", False)

            # 立即释放内存
            del guarded_infos

        return stats

    # ============ 3. 向量化逻辑 (Vectorization Logic) ============

    async def create_index_by_file_ids(
        self,
        file_ids: List[int],
        tenant_id: int,
        kb_id: int,
        chunk_size: int = 300,
        chunk_overlap: int = 100,
        embedding_model: str = None,    # 新增：向量模型名称
        embedding_dim: int = None       # 新增：向量维度
    ) -> Dict[str, Any]:
        """
        [向量化核心入口] 根据 file_ids 从数据库获取内容并向量化
        """
        if not file_ids:
             raise ValueError("file_ids 不能为空")

        logger.info(f"准备向量化: 查询数据库获取 {len(file_ids)} 个文件的内容...")

        # 1. 查库
        logger.info(f"[DEBUG] 开始查询数据库...")
        docs_data = await ParseStorageManager.get_documents_by_file_ids(file_ids)
        logger.info(f"[DEBUG] 数据库查询完成")

        if not docs_data:
            logger.warning(f"数据库中未找到 file_ids={file_ids} 的任何内容")
            return {"status": "empty", "message": "未找到文档内容"}

        logger.info(f"数据库查询成功，获取到 {len(docs_data)} 个文档片段")

        # 2. 转换为 LlamaIndex Document 对象
        from llama_index.core import Document
        logger.info(f"[DEBUG] 开始转换为 LlamaIndex Document 对象...")
        documents = []
        for d in docs_data:
            documents.append(Document(text=d['text'], metadata=d['metadata']))
        logger.info(f"[DEBUG] Document 对象转换完成, 共 {len(documents)} 个")

        # 3. 执行向量化（使用临时配置）
        effective_model = embedding_model or settings.embedding_model_name
        effective_dim = embedding_dim or settings.embedding_dim

        logger.info(f"使用向量模型: {effective_model}, 维度: {effective_dim}")

        # 临时保存原始配置
        original_model = settings.embedding_model_name
        original_dim = settings.embedding_dim

        try:
            # 临时修改配置
            settings.embedding_model_name = effective_model
            settings.embedding_dim = effective_dim

            logger.info(f"[DEBUG] 准备在线程池中执行向量化...")
            logger.info(f"[DEBUG] 当前 embedding_model_name: {settings.embedding_model_name}")
            logger.info(f"[DEBUG] 当前 embedding_dim: {settings.embedding_dim}")

            return await run_in_threadpool(
                self.create_index_from_documents,
                documents=documents,
                tenant_id=tenant_id,
                kb_id=kb_id,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap
            )

        finally:
            # 恢复原始配置
            settings.embedding_model_name = original_model
            settings.embedding_dim = original_dim
            logger.info(f"[DEBUG] 已恢复原始配置")

    def create_index_from_documents(
        self,
        documents: List[Any],
        tenant_id: int,
        kb_id: int,
        chunk_size: int = 300,
        chunk_overlap: int = 100
    ) -> Dict[str, Any]:
        """
        [底层同步方法] 从 Document 对象创建索引并保存到 Milvus
        """
        if not documents:
            raise ValueError("文档列表不能为空")

        logger.info(f"开始执行向量化计算 (Embedding & Indexing), 片段数: {len(documents)}")

        from llama_index.core import VectorStoreIndex, Settings as LlamaSettings
        from core.index_manager import IndexManager
        from core.title_aware_splitter import TitleAwareSplitter

        original_chunk_size = LlamaSettings.chunk_size
        original_chunk_overlap = LlamaSettings.chunk_overlap

        try:
            LlamaSettings.chunk_size = chunk_size
            LlamaSettings.chunk_overlap = chunk_overlap

            logger.info(f"[DEBUG] 准备创建索引管理器")
            index_manager = IndexManager()
            logger.info(f"[DEBUG] 索引管理器创建完成")

            # 构建 file_path_map 用于标题提取
            file_path_map = {}
            for doc in documents:
                file_name = doc.metadata.get("file_name", "")
                file_path = doc.metadata.get("file_path", "")
                if file_name and file_path:
                    file_path_map[file_name] = file_path

            # 使用标题感知切分器切分文档
            logger.info(f"[DEBUG] 开始使用 TitleAwareSplitter 切分文档")
            splitter = TitleAwareSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
            nodes = splitter.get_nodes_from_documents(documents, file_path_map=file_path_map)
            logger.info(f"[DEBUG] 标题感知切分完成, 生成 {len(nodes)} 个 chunks")

            # 记录开始时间
            import time
            start_time = time.time()

            # 从切分后的 nodes 创建索引（不再让 LlamaIndex 自动切分）
            index = VectorStoreIndex(nodes)

            elapsed_time = time.time() - start_time
            logger.info(f"[DEBUG] VectorStoreIndex 创建完成, 耗时: {elapsed_time:.2f}秒")

            logger.info(f"[DEBUG] 开始提取索引数据")
            all_data = index_manager.extract_index_data(index)
            logger.info(f"[DEBUG] 索引数据提取完成, 提取到 {len(all_data)} 条数据")

            inserted_count = 0
            if self.client and all_data:
                from utils.common_slice_manager import extract_and_insert_common_slices_batch

                logger.info(f"开始保存 {len(all_data)} 条切片数据到 common_slice 表")
                inserted_count = extract_and_insert_common_slices_batch(
                    client=self.client,
                    index_data=all_data,
                    tenant_id=tenant_id,
                    kb_id=kb_id
                )
                logger.info(f"成功保存 {inserted_count} 条切片数据")

            return {
                "document_count": len(documents),
                "slice_count": inserted_count,
                "status": "completed"
            }

        finally:
            LlamaSettings.chunk_size = original_chunk_size
            LlamaSettings.chunk_overlap = original_chunk_overlap

    # ============ 4. 用户确认相关方法 ============

    async def confirm_semantic_text(
        self,
        task_id: str,
        confirmations: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        确认使用语义清洗后的文本（列表形式）

        Args:
            task_id: 任务ID
            confirmations: 确认列表，每项包含 file_id 和 use_semantic

        Returns:
            更新结果
        """
        try:
            updated_count = 0
            confirm_results = []

            for item in confirmations:
                file_id = item.get('file_id')
                use_semantic = item.get('use_semantic', True)

                # 确定目标文本字段
                if use_semantic:
                    target_field = "semantic_text"
                else:
                    target_field = "original_text"

                # 更新单个文件
                update_query = f"""
                    UPDATE rag.parsed_documents
                    SET document_text = {target_field}
                    WHERE parse_id = $1 AND file_id = $2 AND semantic_text IS NOT NULL AND semantic_text != ''
                """
                result = await DatabaseManager.execute(update_query, task_id, file_id)
                updated_count += 1

                confirm_results.append({
                    "file_id": file_id,
                    "use_semantic": use_semantic
                })

            # 检查是否还有待确认的文件
            # 逻辑：获取该任务下所有需要确认的文件，检查是否都在本次确认列表中
            get_all_files_query = """
                SELECT DISTINCT file_id
                FROM rag.parsed_documents
                WHERE parse_id = $1 AND semantic_text IS NOT NULL AND semantic_text != ''
            """
            rows = await DatabaseManager.fetch(get_all_files_query, task_id)
            all_files_need_confirmation = {row['file_id'] for row in rows}

            # 获取本次确认的文件ID集合
            confirmed_files = {item.get('file_id') for item in confirmations}

            # 计算还待确认的文件数
            pending_files = all_files_need_confirmation - confirmed_files
            pending_count = len(pending_files)

            if pending_count == 0:
                # 所有文件都已确认
                await self._update_task_status(task_id, {
                    "confirmation_status": "confirmed",
                    "parse_status": "finish"
                })
                await self._schedule_graph_build_if_ready(task_id)
            else:
                # 还有文件待确认
                await self._update_task_status(task_id, {
                    "confirmation_status": "partial"
                })

            return {
                "task_id": task_id,
                "updated_count": updated_count,
                "pending_count": pending_count,
                "confirmations": confirm_results
            }

        except Exception as e:
            logger.error(f"确认语义文本失败: {str(e)}")
            raise RuntimeError(f"确认语义文本失败: {str(e)}") from e

    # ============ 5. 数据库接入方法 ============

    def _build_db_reader(self, request_data: Dict[str, Any]):
        """构建数据库读取器（内部辅助方法）"""
        from utils.db_reader import SafeDatabaseReader, DBConnectionConfig
        db_cfg_raw = request_data['db_config']
        db_config = DBConnectionConfig(
            db_type=db_cfg_raw['db_type'],
            host=db_cfg_raw['host'],
            port=db_cfg_raw['port'],
            database=db_cfg_raw['database'],
            user=db_cfg_raw['user'],
            password=db_cfg_raw['password'],
            connect_args=db_cfg_raw.get('connect_args'),
        )
        return SafeDatabaseReader(db_config)

    async def _read_database_documents(self, task_id: str, request_data: Dict[str, Any]) -> List[Any]:
        """读取数据库数据并返回 Document 列表（内部辅助方法）"""
        reader = self._build_db_reader(request_data)
        all_documents: List[Any] = []
        queries = request_data['queries']
        max_rows = request_data.get('max_rows', 10_000)
        page_size = request_data.get('page_size', 500)

        logger.info(f"任务 {task_id} - 开始执行 {len(queries)} 个数据库查询")

        for idx, qcfg in enumerate(queries):
            query_str = qcfg['query']
            text_column = qcfg['text_column']
            metadata_columns = qcfg.get('metadata_columns')

            logger.info(
                f"任务 {task_id} - 执行查询 {idx + 1}/{len(queries)}: "
                f"text_column='{text_column}'"
            )

            docs = await run_in_threadpool(
                reader.load_data,
                query=query_str,
                text_column=text_column,
                metadata_columns=metadata_columns,
                max_rows=max_rows,
                page_size=page_size,
            )
            all_documents.extend(docs)
            logger.info(f"任务 {task_id} - 查询 {idx + 1} 读取 {len(docs)} 条")

        return all_documents

    async def run_database_process_pipeline(self, task_id: str, request_data: Dict[str, Any]):
        """
        [数据库完整流水线] 读取 -> 存 PG -> 向量化

        复用文件流程的状态流转：
        parse_status: pending -> processing -> finish
        embed_status: pending -> processing -> finish
        """
        try:
            # ---------- 阶段 1: 读取数据存 PG ----------
            await self._update_task_status(task_id, {"parse_status": "processing"})

            documents = await self._read_database_documents(task_id, request_data)
            await self._update_task_status(task_id, {"file_count": len(documents)})

            if not documents:
                logger.warning(f"任务 {task_id} - 未从数据库读取到任何数据")
                await self._update_task_status(task_id, {
                    "parse_status": "finish",
                    "embed_status": "finish"
                })
                return

            # 保存到 parsed_documents（复用现有存储表）
            await ParseStorageManager.save_database_parse_result(
                documents=documents,
                parse_id=task_id,
            )
            await self._update_task_status(task_id, {"parse_status": "finish"})
            logger.info(f"任务 {task_id} - 数据库读取完成，共 {len(documents)} 条")

            # ---------- 阶段 2: 向量化 ----------
            await self._update_task_status(task_id, {"embed_status": "processing"})
            await self.run_database_embed_only_pipeline(task_id, request_data)

        except Exception as e:
            logger.error(f"数据库任务 {task_id} 失败: {str(e)}", exc_info=True)
            try:
                status = await self.get_task_status(task_id)
                update_data = {"error_message": str(e)}
                if status['parse_status'] != 'finish':
                    update_data['parse_status'] = 'failed'
                else:
                    update_data['embed_status'] = 'failed'
                await self._update_task_status(task_id, update_data)
            except Exception:
                pass

    async def run_database_parse_only_pipeline(self, task_id: str, request_data: Dict[str, Any]):
        """
        [数据库纯读取流水线] 读取 -> 存 PG
        """
        try:
            await self._update_task_status(
                task_id, {"parse_status": "processing", "embed_status": "skipped"}
            )

            documents = await self._read_database_documents(task_id, request_data)
            await self._update_task_status(task_id, {"file_count": len(documents)})

            if not documents:
                logger.warning(f"任务 {task_id} - 未从数据库读取到任何数据")
                await self._update_task_status(task_id, {"parse_status": "finish"})
                return

            await ParseStorageManager.save_database_parse_result(
                documents=documents,
                parse_id=task_id,
            )
            await self._update_task_status(task_id, {"parse_status": "finish"})
            logger.info(f"任务 {task_id} - 数据库纯读取完成，共 {len(documents)} 条")

        except Exception as e:
            logger.error(f"数据库读取任务 {task_id} 失败: {str(e)}")
            await self._update_task_status(task_id, {
                "parse_status": "failed",
                "error_message": str(e),
            })

    async def run_database_embed_only_pipeline(self, task_id: str, request_data: Dict[str, Any]):
        """
        [数据库纯向量化流水线] 从 PG 读取 -> 向量化

        通常被 run_database_process_pipeline 调用，也可被 /embedding/embed 触发。
        """
        from llama_index.core import Document

        try:
            await self._update_task_status(task_id, {"embed_status": "processing"})

            # 从 PG 读取
            docs_data = await ParseStorageManager.get_documents_by_parse_id(task_id)
            if not docs_data:
                raise ValueError(f"任务 {task_id} 未找到数据库读取记录")

            documents = []
            for d in docs_data:
                metadata = {}
                if d.get('document_metadata'):
                    try:
                        metadata = json.loads(d['document_metadata'])
                    except json.JSONDecodeError:
                        metadata = {}
                documents.append(Document(text=d.get('document_text', ''), metadata=metadata))

            logger.info(f"任务 {task_id} - 从 PG 读取到 {len(documents)} 个文档片段，开始向量化")

            # 获取 KB 模型配置
            kb_model_config = await KBMetadataManager.get_or_create_kb_model(
                kb_id=request_data['kb_id'],
                tenant_id=request_data['tenant_id'],
                requested_model=request_data.get('embedding_model'),
                requested_dim=request_data.get('embedding_dim'),
                default_model=settings.embedding_model_name,
                default_dim=settings.embedding_dim,
            )

            # 临时切换模型配置并执行向量化
            original_model = settings.embedding_model_name
            original_dim = settings.embedding_dim
            try:
                settings.embedding_model_name = kb_model_config['embedding_model']
                settings.embedding_dim = kb_model_config['embedding_dim']

                await run_in_threadpool(
                    self.create_index_from_documents,
                    documents=documents,
                    tenant_id=request_data['tenant_id'],
                    kb_id=request_data['kb_id'],
                    chunk_size=request_data.get('chunk_size', 300),
                    chunk_overlap=request_data.get('chunk_overlap', 100),
                )
            finally:
                settings.embedding_model_name = original_model
                settings.embedding_dim = original_dim

            await self._update_task_status(task_id, {"embed_status": "finish"})
            logger.info(f"任务 {task_id} - 数据库向量化完成")

        except Exception as e:
            logger.error(f"数据库向量化任务 {task_id} 失败: {str(e)}")
            await self._update_task_status(task_id, {
                "embed_status": "failed",
                "error_message": str(e),
            })

    async def delete_documents_by_file_ids(
        self,
        tenant_id: int,
        kb_id: int,
        file_ids: List[int],
        collection_name: str = "common_slice",
        delete_graph: bool = False,
    ) -> Dict[str, Any]:
        """
        删除指定文档的 Milvus 向量切片及 PostgreSQL 解析缓存

        Args:
            tenant_id: 租户ID
            kb_id: 知识库ID
            file_ids: 文件ID列表
            collection_name: Milvus 集合名称
            delete_graph: 是否同步删除 GraphRAG 图谱数据

        Returns:
            删除结果统计
        """
        if not file_ids:
            raise ValueError("file_ids 不能为空")

        collections = self.client.list_collections()
        if collection_name not in collections:
            raise ValueError(f"集合 '{collection_name}' 不存在")

        from utils.common_slice_manager import CommonSliceManager

        unique_file_ids = list(dict.fromkeys(file_ids))

        deleted_milvus_count = await run_in_threadpool(
            CommonSliceManager.delete_slices,
            self.client,
            tenant_id,
            kb_id,
            unique_file_ids,
            collection_name,
        )

        deleted_pg_count = 0
        try:
            deleted_pg_count = await ParseStorageManager.delete_documents_by_file_ids(unique_file_ids)
        except Exception as e:
            logger.warning(f"Milvus 删除成功，但 PG 解析缓存删除失败: {str(e)}")

        result: Dict[str, Any] = {
            "collection": collection_name,
            "tenant_id": tenant_id,
            "kb_id": kb_id,
            "file_ids": unique_file_ids,
            "deleted_milvus_count": deleted_milvus_count,
            "deleted_pg_count": deleted_pg_count,
        }

        if delete_graph:
            graph_deletion: Dict[str, Any] = {"requested": True}
            if not settings.graphrag_enabled:
                graph_deletion["success"] = False
                graph_deletion["error"] = "GraphRAG 服务未启用"
                logger.warning(
                    f"delete_graph=true 但 GraphRAG 未启用，跳过图谱删除: "
                    f"tenant_id={tenant_id}, kb_id={kb_id}, file_ids={unique_file_ids}"
                )
            else:
                try:
                    graph_data = await run_in_threadpool(
                        delete_knowledge_by_files,
                        tenant_id,
                        kb_id,
                        [str(fid) for fid in unique_file_ids],
                    )
                    graph_deletion["success"] = True
                    graph_deletion.update(graph_data)
                except Exception as e:
                    graph_deletion["success"] = False
                    graph_deletion["error"] = str(e)
                    logger.error(
                        f"Milvus/PG 删除成功，但 GraphRAG 图谱删除失败: {str(e)}"
                    )
            result["graph_deletion"] = graph_deletion
        else:
            result["graph_deletion"] = {"requested": False}

        return result
