"""
索引管理模块 - 管理向量索引的创建、加载和查询
"""
import json
import functools
import asyncio
from typing import List, Dict, Any, Iterable, Optional
from concurrent.futures import ThreadPoolExecutor

from llama_index.core import VectorStoreIndex, Document
from llama_index.vector_stores.milvus import MilvusVectorStore

from configs.config import settings
from utils.logger import get_logger
from utils.json_serializer import make_relationships_serializable

logger = get_logger()


class IndexManager:
    """索引管理器"""

    def __init__(self):
        """初始化索引管理器"""
        self.dim = settings.embedding_dim

    def create_milvus_vector_store(
        self,
        collection_name: str,
        milvus_cfg: Dict[str, Any],
        overwrite: bool = False,
        dim: Optional[int] = None
    ) -> MilvusVectorStore:
        """
        创建 Milvus 向量存储

        Args:
            collection_name: 集合名称
            milvus_cfg: Milvus 配置
            overwrite: 是否覆盖现有集合
            dim: 向量维度（仅在创建新集合时有效，加载已有集合时可为 None）

        Returns:
            MilvusVectorStore 实例
        """
        logger.info(f"创建 Milvus VectorStore: {collection_name}")

        vector_store = MilvusVectorStore(
            dim=dim or self.dim,
            uri=milvus_cfg['uri'],
            token=f"{milvus_cfg['user']}:{milvus_cfg['password']}",
            db_name=milvus_cfg['db_name'],
            collection_name=collection_name,
            embedding_field="vector",
            overwrite=overwrite,
            hybrid_ranker="RRFRanker",
            hybrid_ranker_params={"k": settings.hybrid_ranker_k}
        )

        logger.info(f"Milvus VectorStore 创建完成")
        return vector_store

    def create_index_from_documents(
        self,
        documents: List[Document],
        collection_name: str,
        milvus_cfg: Dict[str, Any]
    ) -> VectorStoreIndex:
        """
        从文档创建索引

        Args:
            documents: 文档列表
            collection_name: 集合名称
            milvus_cfg: Milvus 配置

        Returns:
            VectorStoreIndex 实例
        """
        logger.info(f"从 {len(documents)} 个文档创建索引")

        # 创建向量存储
        vector_store = self.create_milvus_vector_store(collection_name, milvus_cfg)

        # 创建索引
        index = VectorStoreIndex.from_documents(documents, vector_store=vector_store)

        logger.info(f"索引创建完成: {collection_name}")
        return index

    def get_index(self, collection_name: str, milvus_cfg: Dict[str, Any]) -> VectorStoreIndex:
        """
        获取已存在的索引

        Args:
            collection_name: 集合名称
            milvus_cfg: Milvus 配置

        Returns:
            VectorStoreIndex 实例
        """
        logger.info(f"加载索引: {collection_name}")

        vector_store = self.create_milvus_vector_store(collection_name, milvus_cfg, overwrite=False)
        index = VectorStoreIndex.from_vector_store(vector_store)

        logger.info(f"索引加载完成: {collection_name}")
        return index

    def extract_index_data(self, index: VectorStoreIndex) -> List[Dict[str, Any]]:
        """
        从索引中提取数据（用于返回给后端保存）

        Args:
            index: VectorStoreIndex 实例

        Returns:
            包含嵌入向量和元数据的数据列表
        """
        logger.info("开始提取索引数据")

        embedding_dict = index._vector_store.data.embedding_dict
        store_data_dict = index._storage_context.docstore.docs
        metadata_dict = index._vector_store.data.metadata_dict

        all_data = []

        for embedding_id in embedding_dict:
            try:
                vector = embedding_dict[embedding_id]
                node = store_data_dict[embedding_id]

                node_content = {
                    "id_": str(node.id_) if node.id_ else "",
                    "embedding": list(node.embedding) if node.embedding is not None else [],
                    "metadata": dict(node.metadata) if node.metadata else {},
                    "excluded_embed_metadata_keys": list(node.excluded_embed_metadata_keys) if node.excluded_embed_metadata_keys else [],
                    "excluded_llm_metadata_keys": list(node.excluded_llm_metadata_keys) if node.excluded_llm_metadata_keys else [],
                    "relationships": make_relationships_serializable(node.relationships) if node.relationships else {},
                    "text": str(node.text) if node.text else "",
                    "mimetype": str(node.mimetype) if node.mimetype else "",
                    "start_char_idx": int(node.start_char_idx) if node.start_char_idx is not None else None,
                    "end_char_idx": int(node.end_char_idx) if node.end_char_idx is not None else None,
                    "text_template": str(node.text_template) if node.text_template else "",
                    "metadata_template": str(node.metadata_template) if node.metadata_template else "",
                    "metadata_seperator": str(node.metadata_seperator) if node.metadata_seperator else "",
                    "class_name": str(node.class_name) if hasattr(node, "class_name") else "",
                    "ref_doc_id": str(node.ref_doc_id) if hasattr(node, 'ref_doc_id') and node.ref_doc_id else str(node.id_) if node.id_ else "",
                }

                # 安全地获取 metadata，确保可序列化
                metadata = metadata_dict.get(embedding_id, {})
                if isinstance(metadata, dict):
                    # 检查 metadata 中是否包含方法对象
                    safe_metadata = {}
                    for k, v in metadata.items():
                        if callable(v):
                            safe_metadata[k] = str(v)
                        else:
                            safe_metadata[k] = v
                else:
                    safe_metadata = {}

                all_data.append({
                    **safe_metadata,
                    "_node_content": node_content,
                    "vector": vector.tolist() if hasattr(vector, 'tolist') else list(vector),
                    "embedding_id": str(embedding_id)
                })

            except Exception as e:
                logger.error(f"提取嵌入数据失败: {embedding_id} - {str(e)}")
                continue

        logger.info(f"索引数据提取完成，共 {len(all_data)} 条")
        return all_data


async def _build_doc(raw: Any) -> Document:
    """
    在线程池中完成 JSON 序列化与 Document 创建

    Args:
        raw: 原始数据

    Returns:
        Document 实例
    """
    loop = asyncio.get_running_loop()
    text = await loop.run_in_executor(
        ThreadPoolExecutor(),
        functools.partial(json.dumps, ensure_ascii=False),
        raw
    )
    return Document(text=text)


async def create_index_async(contents: Iterable[Any]) -> List[Dict[str, Any]]:
    """
    异步创建索引（从内容列表）

    Args:
        contents: 内容列表

    Returns:
        索引数据列表
    """
    logger.info(f"开始异步创建索引，内容数量: {len(contents)}")

    # 并发创建 Document
    docs = await asyncio.gather(*[_build_doc(c) for c in contents])

    # 构建索引
    index = VectorStoreIndex.from_documents(docs)

    # 提取数据
    manager = IndexManager()
    all_data = manager.extract_index_data(index)

    logger.info(f"异步索引创建完成，共 {len(all_data)} 条数据")
    return all_data


# ============ 向后兼容的函数 ============

def get_index(collection_name: str, milvus_cfg: Dict[str, Any]) -> VectorStoreIndex:
    """
    获取索引（兼容旧代码）

    Args:
        collection_name: 集合名称
        milvus_cfg: Milvus 配置

    Returns:
        VectorStoreIndex 实例
    """
    manager = IndexManager()
    return manager.get_index(collection_name, milvus_cfg)
