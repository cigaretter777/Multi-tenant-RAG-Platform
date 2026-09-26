"""
核心模块 - Embedding 服务的核心组件
"""
from core.embedding_service import EmbeddingService, embedding_service
from core.document_processor import DocumentProcessor, FileDownloader
from core.index_manager import IndexManager, create_index_async, get_index
from core.retriever import (
    VectorRetriever,
    HybridRetriever,
    query_question,
    query_question_hybrid,
    query_question_from_file,
    get_file_id
)

__all__ = [
    # Embedding 服务
    'EmbeddingService',
    'embedding_service',

    # 文档处理
    'DocumentProcessor',
    'FileDownloader',

    # 索引管理
    'IndexManager',
    'create_index_async',
    'get_index',

    # 检索
    'VectorRetriever',
    'HybridRetriever',
    'query_question',
    'query_question_hybrid',
    'query_question_from_file',
    'get_file_id',
]
