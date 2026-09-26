"""
查询服务层 - 封装查询相关业务逻辑
"""
import asyncio
from typing import List, Dict, Any, Optional
from pymilvus import MilvusClient
from starlette.concurrency import run_in_threadpool

from configs.config import SIMILARITY_THRESHOLD, SIMILARITY_TOP_K, settings
from utils.embedding import get_index, query_question, query_question_hybrid
from utils.db import KBMetadataManager
from utils.graphrag_client import query_graph_context
from utils.logger import get_logger

logger = get_logger()


class QueryService:
    """查询服务类"""

    def __init__(self, milvus_client: MilvusClient, milvus_cfg: Dict[str, Any]):
        """
        初始化查询服务

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
    def client(self) -> MilvusClient:
        """获取 Milvus 客户端（懒加载，线程安全）"""
        if self._client is None:
            import threading
            if self._client_lock is None:
                self._client_lock = threading.Lock()
            with self._client_lock:
                if self._client is None:
                    self._client = self._create_milvus_client()
        return self._client

    def _validate_collection_exists(self, collection_name: str) -> bool:
        collections = self.client.list_collections()
        if collection_name not in collections:
            raise ValueError(f"知识库 '{collection_name}' 不存在")
        return True

    def _query_vector_sync(
        self,
        question: str,
        kb_id_list: List[Dict[str, Any]],
        collection_name: str,
        similarity_threshold: float,
        similarity_top_k: int,
        mode: str,
        alpha: float,
    ) -> List[Dict[str, Any]]:
        """同步向量/混合检索（供线程池调用）"""
        self._validate_collection_exists(collection_name)

        valid_modes = ["naive", "hybrid"]
        if mode not in valid_modes:
            raise ValueError(f"无效的检索模式: {mode}, 必须是 {valid_modes} 之一")

        kb_ids = [kb["id"] for kb in kb_id_list]
        if not kb_ids:
            raise ValueError("kb_id_list 不能为空")

        index = get_index(collection_name, self.milvus_cfg)
        logger.info(f"获取索引: {collection_name}")

        if mode == "hybrid":
            logger.info(f"使用混合检索 - alpha: {alpha}")
            return query_question_hybrid(
                index, question, self.milvus_cfg, kb_id_list,
                similarity_threshold, similarity_top_k, alpha
            )

        logger.info("使用向量检索")
        return query_question(
            index, question, self.milvus_cfg, kb_id_list,
            similarity_threshold, similarity_top_k
        )

    async def _query_graph_for_kb(
        self,
        tenant_id: int,
        kb_id: int,
        kb_name: Optional[str],
        question: str,
        graph_strategy: str,
        graph_context: Optional[str],
    ) -> Dict[str, Any]:
        """单个 KB 的 GraphRAG 图谱上下文查询"""
        base = {
            "kb_id": kb_id,
            "kb_name": kb_name,
            "success": False,
        }
        try:
            data = await run_in_threadpool(
                query_graph_context,
                tenant_id,
                kb_id,
                question,
                graph_strategy,
                graph_context,
                True,
            )
            return {
                **base,
                "success": True,
                "query_type": data.get("query_type"),
                "confidence": data.get("confidence"),
                "execution_time": data.get("execution_time"),
                "entities": data.get("entities") or [],
                "relationships": data.get("relationships") or [],
                "entities_count": data.get("entities_count"),
                "relationships_count": data.get("relationships_count"),
                "sources": data.get("sources"),
                "error": None,
            }
        except Exception as e:
            logger.warning(
                f"GraphRAG 图谱查询失败: tenant_id={tenant_id}, kb_id={kb_id}, error={e}"
            )
            return {
                **base,
                "error": str(e),
                "entities": [],
                "relationships": [],
            }

    async def _query_graph_multi_kb(
        self,
        tenant_id: int,
        kb_id_list: List[Dict[str, Any]],
        question: str,
        graph_strategy: str,
        graph_context: Optional[str],
    ) -> Dict[str, Any]:
        """多 KB 并行 GraphRAG 图谱上下文查询"""
        if not settings.graphrag_enabled:
            return {
                "requested": True,
                "results": [],
                "error": "GraphRAG 服务未启用",
            }

        tasks = [
            self._query_graph_for_kb(
                tenant_id=tenant_id,
                kb_id=kb["id"],
                kb_name=kb.get("name"),
                question=question,
                graph_strategy=graph_strategy,
                graph_context=graph_context,
            )
            for kb in kb_id_list
        ]
        results = await asyncio.gather(*tasks)
        return {
            "requested": True,
            "results": list(results),
            "error": None,
        }

    async def query(
        self,
        question: str,
        tenant_id: int,
        kb_id_list: List[Dict[str, Any]],
        collection_name: str = "common_slice",
        similarity_threshold: float = SIMILARITY_THRESHOLD,
        similarity_top_k: int = SIMILARITY_TOP_K,
        mode: str = "naive",
        alpha: float = 0.5,
        include_graph: bool = False,
        graph_strategy: str = "mix",
        graph_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        统一查询 - 向量/混合检索，可选并行 GraphRAG 图谱上下文

        Returns:
            {
                "mode": str,
                "vector_results": [...],
                "graph_context": { "requested": bool, "results": [...], "error": ... }
            }
        """
        kb_ids = [kb["id"] for kb in kb_id_list]
        if not kb_ids:
            raise ValueError("kb_id_list 不能为空")

        consistency_check = await KBMetadataManager.validate_kb_model_consistency(kb_ids)
        if not consistency_check["is_consistent"]:
            raise ValueError(f"模型一致性校验失败: {consistency_check['error']}")

        kb_model = consistency_check["model"]
        logger.info(f"查询使用模型: {kb_model}, KB列表: {kb_ids}, include_graph={include_graph}")

        original_model = settings.embedding_model_name
        original_dim = settings.embedding_dim

        try:
            kb_metadata = await KBMetadataManager.get_kb_metadata(kb_ids[0])
            if kb_metadata:
                settings.embedding_model_name = kb_metadata['embedding_model']
                settings.embedding_dim = kb_metadata['embedding_dim']
                logger.info(
                    f"临时切换模型: {kb_metadata['embedding_model']} "
                    f"(dim={kb_metadata['embedding_dim']})"
                )
            else:
                logger.warning(f"KB {kb_ids[0]} 没有元数据，使用默认模型")

            vector_coro = run_in_threadpool(
                self._query_vector_sync,
                question,
                kb_id_list,
                collection_name,
                similarity_threshold,
                similarity_top_k,
                mode,
                alpha,
            )

            if include_graph:
                vector_results, graph_context_result = await asyncio.gather(
                    vector_coro,
                    self._query_graph_multi_kb(
                        tenant_id, kb_id_list, question, graph_strategy, graph_context
                    ),
                )
            else:
                vector_results = await vector_coro
                graph_context_result = {"requested": False}

            logger.info(
                f"查询完成: vector={len(vector_results)} 条, "
                f"graph_kb={len(graph_context_result.get('results') or [])}"
            )

            return {
                "mode": mode,
                "vector_results": vector_results,
                "graph_context": graph_context_result,
            }

        finally:
            settings.embedding_model_name = original_model
            settings.embedding_dim = original_dim
            logger.debug(f"恢复原始模型配置: {original_model}")
