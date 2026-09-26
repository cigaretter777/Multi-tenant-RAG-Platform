"""
Embedding 工具模块 - 重构版本

本模块提供向量嵌入、文档处理、索引管理和检索功能。
已重构为使用 core 模块，保持向后兼容。
"""
import os
from typing import List, Dict, Iterable, Any, Optional
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader

from configs.config import settings
from utils.logger import get_logger
from utils.get_txt import get_new_file_path

logger = get_logger()

# ============ 导入核心模块 ============
# 使用新的模块化架构，使用别名避免循环导入

from core.embedding_service import EmbeddingService as _EmbeddingService
from core.document_processor import DocumentProcessor, FileDownloader, download_file as _core_download_file
from core.index_manager import IndexManager as _IndexManager
from core.retriever import (
    VectorRetriever,
    HybridRetriever,
    query_question as _core_query_question,
    query_question_hybrid as _core_query_question_hybrid,
    query_question_from_file as _core_query_question_from_file,
    get_file_id as _core_get_file_id,
)
from core.index_manager import (
    create_index_async as _core_create_index_async,
    get_index as _core_get_index,
)

# ============ 全局服务实例 ============
_embedding_service_instance = None


# ============ Embedding 服务初始化 ============

def embedding_service():
    """
    初始化 Embedding 服务（向后兼容）

    该函数会初始化全局的 Embedding 模型配置，包括：
    - 设置嵌入模型
    - 配置文本分块参数
    - 更新 llama-index 全局 Settings
    """
    global _embedding_service_instance

    if _embedding_service_instance is None:
        _embedding_service_instance = _EmbeddingService()
        logger.info("Embedding 服务已启动")

    return _embedding_service_instance


# ============ 索引管理 ============

async def create_index_async(contents: Iterable[Any]) -> List[Dict[str, Any]]:
    """
    异步创建索引（从内容列表）

    Args:
        contents: 内容列表，可以是任意可 JSON 序列化的数据

    Returns:
        索引数据列表

    Example:
        >>> contents = [{"text": "内容1"}, {"text": "内容2"}]
        >>> result = await create_index_async(contents)
    """
    return await _core_create_index_async(contents)


def get_index(collection_name: str, milvus_cfg: Dict[str, Any]) -> VectorStoreIndex:
    """
    获取 Milvus 中的向量索引

    Args:
        collection_name: Milvus 集合名称
        milvus_cfg: Milvus 配置字典

    Returns:
        VectorStoreIndex 实例

    Example:
        >>> milvus_cfg = {"uri": "http://localhost:19530", "user": "root", ...}
        >>> index = get_index("common_slice", milvus_cfg)
    """
    return _core_get_index(collection_name, milvus_cfg)


# ============ 检索功能 ============

def query_question(
    index: VectorStoreIndex,
    question: str,
    milvus_cfg: Dict[str, Any],
    kb_id_list: List[Dict[str, Any]],
    similarity_threshold: float,
    similarity_top_k: int
) -> List[Dict[str, Any]]:
    """
    向量检索

    Args:
        index: 向量索引
        question: 查询问题
        milvus_cfg: Milvus 配置
        kb_id_list: 知识库ID列表，格式: [{"id": 1, "name": "知识库1"}, ...]
        similarity_threshold: 相似度阈值 (0-1)
        similarity_top_k: 返回结果数量

    Returns:
        检索结果列表

    Example:
        >>> result = query_question(index, "什么是人工智能?", milvus_cfg, kb_list, 0.5, 5)
    """
    return _core_query_question(index, question, milvus_cfg, kb_id_list, similarity_threshold, similarity_top_k)


def query_question_hybrid(
    index: VectorStoreIndex,
    question: str,
    milvus_cfg: Dict[str, Any],
    kb_id_list: List[Dict[str, Any]],
    similarity_threshold: float,
    similarity_top_k: int,
    alpha: float = 0.5
) -> List[Dict[str, Any]]:
    """
    混合检索 - 结合向量检索和 BM25 关键词检索

    Args:
        index: 向量索引
        question: 查询问题
        milvus_cfg: Milvus 配置
        kb_id_list: 知识库ID列表
        similarity_threshold: 相似度阈值
        similarity_top_k: 返回结果数量
        alpha: 向量检索权重 (0-1)，1-alpha 为 BM25 权重

    Returns:
        检索结果列表，包含 rrf_score 和 vector_score

    Example:
        >>> result = query_question_hybrid(index, "什么是人工智能?", milvus_cfg, kb_list, 0.5, 5, 0.7)
    """
    return _core_query_question_hybrid(index, question, milvus_cfg, kb_id_list, similarity_threshold, similarity_top_k, alpha)


# ============ 文件下载 ============

async def download_file(url: str, local_path: str) -> str:
    """
    下载文件到本地

    Args:
        url: 文件URL（相对路径）
        local_path: 本地保存路径

    Returns:
        本地文件路径

    Raises:
        RuntimeError: 下载失败时抛出

    Example:
        >>> path = await download_file("/api/file/123", "downloads/file.pdf")
    """
    return await _core_download_file(url, local_path)


# ============ 模块导出 ============

__all__ = [
    # 服务初始化
    'embedding_service',

    # 索引管理
    'create_index_async',
    'get_index',

    # 检索
    'query_question',
    'query_question_hybrid',

    # 工具函数
    'download_file',
]
