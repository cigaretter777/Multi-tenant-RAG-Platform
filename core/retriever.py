"""
检索模块 - 处理向量检索和混合检索
"""
from typing import List, Dict, Any, Optional

from llama_index.core import VectorStoreIndex
from llama_index.core.vector_stores import MetadataFilters, ExactMatchFilter
from llama_index.retrievers.bm25 import BM25Retriever

from configs.config import settings
from utils.logger import get_logger

logger = get_logger()


class MilvusMetadataManager:
    """Milvus 元数据管理器"""

    def __init__(self, milvus_cfg: Dict[str, Any]):
        """
        初始化元数据管理器

        Args:
            milvus_cfg: Milvus 配置
        """
        self.milvus_cfg = milvus_cfg
        self._client = None

    def _get_client(self) -> "MilvusClient":
        """获取 MilvusClient 实例（懒加载）"""
        if self._client is None:
            from pymilvus import MilvusClient
            self._client = MilvusClient(
                uri=self.milvus_cfg['uri'],
                token=f"{self.milvus_cfg['user']}:{self.milvus_cfg['password']}",
                db_name=self.milvus_cfg['db_name'],
            )
        return self._client

    def get_file_id(self, ref_doc_id: str, collection_name: str = "common_slice") -> int:
        """
        获取 ref_doc_id 对应的 file_id

        Args:
            ref_doc_id: 文档引用ID
            collection_name: 集合名称

        Returns:
            file_id
        """
        client = self._get_client()

        res = client.query(
            collection_name=collection_name,
            filter=f"ref_doc_id == '{ref_doc_id}'",
            output_fields=["file_id"],
            limit=1
        )

        if not res:
            logger.warning(f"未找到 ref_doc_id: {ref_doc_id}")
            return None

        file_id = res[0]["file_id"]
        logger.info(f"{ref_doc_id} -> file_id: {file_id}")
        return file_id


class VectorRetriever:
    """向量检索器"""

    def __init__(self, milvus_cfg: Dict[str, Any]):
        """
        初始化向量检索器

        Args:
            milvus_cfg: Milvus 配置
        """
        self.milvus_cfg = milvus_cfg
        self.metadata_manager = MilvusMetadataManager(milvus_cfg)

    def query(
        self,
        index: VectorStoreIndex,
        question: str,
        kb_id_list: List[Dict[str, Any]],
        similarity_threshold: float = None,
        similarity_top_k: int = None
    ) -> List[Dict[str, Any]]:
        """
        向量检索

        Args:
            index: 向量索引
            question: 查询问题
            kb_id_list: 知识库ID列表
            similarity_threshold: 相似度阈值
            similarity_top_k: 返回结果数量

        Returns:
            检索结果列表
        """
        similarity_threshold = similarity_threshold or settings.similarity_threshold
        similarity_top_k = similarity_top_k or settings.similarity_top_k

        retriever_result = []

        for kb_id_info in kb_id_list:
            kb_id = kb_id_info["id"]

            # 类型转换
            if isinstance(kb_id, str):
                kb_id = int(kb_id)

            # 构建过滤条件
            filter = MetadataFilters(filters=[ExactMatchFilter(key="kb_id", value=kb_id)])
            retriever = index.as_retriever(similarity_top_k=similarity_top_k, filters=filter)

            logger.info(f"检索知识库: {kb_id_info.get('name', kb_id)}")
            results = retriever.retrieve(question)

            # 处理结果
            for i, result_with_score in enumerate(results):
                if result_with_score.score < similarity_threshold:
                    continue

                # 获取 file_id
                file_id = self.metadata_manager.get_file_id(
                    result_with_score.node.ref_doc_id,
                    collection_name="common_slice"
                )

                file_meta_data = result_with_score.metadata.get("file_name", "Unknown")

                # 提取标题信息（兼容老数据：可能没有标题字段）
                heading_path = result_with_score.node.metadata.get("heading_path", "")
                nearest_heading = result_with_score.node.metadata.get("nearest_heading", "")

                # 将标题信息拼接到 fileText 末尾，供 LLM 使用
                file_text = f"{result_with_score.node.text}\n"
                if nearest_heading:
                    file_text += f"[所属章节] {nearest_heading}\n"

                text_info = {
                    "fileMateData": file_meta_data,
                    "file_id": file_id,
                    "fileText": file_text,
                    "kb_id": kb_id,
                    "kb_name": kb_id_info["name"],
                    "score": result_with_score.score,
                    "heading_path": heading_path,
                    "nearest_heading": nearest_heading,
                }
                retriever_result.append(text_info)

        # 按 score 排序并取 top_k
        if len(retriever_result) > similarity_top_k:
            retriever_result = sorted(
                retriever_result,
                key=lambda x: x["score"],
                reverse=True
            )[:similarity_top_k]
            # 移除 score 字段
            for item in retriever_result:
                del item["score"]

        logger.info(f"向量检索完成，返回 {len(retriever_result)} 个结果")
        return retriever_result


class HybridRetriever:
    """混合检索器 - 向量检索 + BM25"""

    def __init__(self, milvus_cfg: Dict[str, Any]):
        """
        初始化混合检索器

        Args:
            milvus_cfg: Milvus 配置
        """
        self.milvus_cfg = milvus_cfg
        self.metadata_manager = MilvusMetadataManager(milvus_cfg)

    def query(
        self,
        index: VectorStoreIndex,
        question: str,
        kb_id_list: List[Dict[str, Any]],
        similarity_threshold: float = None,
        similarity_top_k: int = None,
        alpha: float = 0.5
    ) -> List[Dict[str, Any]]:
        """
        混合检索 - 结合向量检索和 BM25 关键词检索

        Args:
            index: 向量索引
            question: 查询问题
            kb_id_list: 知识库ID列表
            similarity_threshold: 相似度阈值
            similarity_top_k: 返回结果数量
            alpha: 向量检索权重 (0-1)

        Returns:
            检索结果列表
        """
        similarity_threshold = similarity_threshold or settings.similarity_threshold
        similarity_top_k = similarity_top_k or settings.similarity_top_k

        logger.info(f"========== 混合检索 ==========")
        logger.info(f"问题: {question}")
        logger.info(f"alpha (向量权重): {alpha}")

        # 存储所有检索结果
        vector_results = []
        bm25_results = []

        # 对每个知识库进行检索
        for kb_id_info in kb_id_list:
            kb_id = kb_id_info["id"]
            kb_name = kb_id_info.get("name", "")

            if isinstance(kb_id, str):
                kb_id = int(kb_id)

            logger.info(f"处理知识库: {kb_name} (kb_id={kb_id})")

            # 1. 向量检索
            filter = MetadataFilters(filters=[ExactMatchFilter(key="kb_id", value=kb_id)])
            vector_retriever = index.as_retriever(
                similarity_top_k=similarity_top_k * 2,
                filters=filter
            )
            vector_nodes = vector_retriever.retrieve(question)
            logger.info(f"  向量检索返回 {len(vector_nodes)} 个结果")

            # 2. BM25 检索
            try:
                all_nodes = list(index.docstore.docs.values())
                kb_nodes = [
                    node for node in all_nodes
                    if node.metadata.get("kb_id") == kb_id
                ]

                if kb_nodes:
                    bm25_retriever = BM25Retriever.from_defaults(
                        nodes=kb_nodes,
                        similarity_top_k=similarity_top_k * 2
                    )
                    bm25_nodes = bm25_retriever.retrieve(question)
                    logger.info(f"  BM25 检索返回 {len(bm25_nodes)} 个结果")
                else:
                    bm25_nodes = []
                    logger.info(f"  当前知识库无节点，跳过 BM25 检索")

            except Exception as e:
                logger.warning(f"  BM25 检索失败: {e}，仅使用向量检索")
                bm25_nodes = []

            # 收集结果
            for rank, node_with_score in enumerate(vector_nodes):
                vector_results.append({
                    "node": node_with_score.node,
                    "kb_id": kb_id,
                    "kb_name": kb_name,
                    "vector_score": node_with_score.score,
                    "vector_rank": rank + 1
                })

            for rank, node_with_score in enumerate(bm25_nodes):
                bm25_results.append({
                    "node": node_with_score.node,
                    "kb_id": kb_id,
                    "kb_name": kb_name,
                    "bm25_score": node_with_score.score,
                    "bm25_rank": rank + 1
                })

        # RRF 融合
        return self._rrf_fusion(
            vector_results,
            bm25_results,
            similarity_threshold,
            similarity_top_k,
            alpha  # 传递 alpha 参数
        )

    def _rrf_fusion(
        self,
        vector_results: List[Dict],
        bm25_results: List[Dict],
        similarity_threshold: float,
        similarity_top_k: int,
        alpha: float = 0.5
    ) -> List[Dict[str, Any]]:
        """
        RRF (Reciprocal Rank Fusion) 融合算法

        Args:
            vector_results: 向量检索结果
            bm25_results: BM25 检索结果
            similarity_threshold: 相似度阈值
            similarity_top_k: 返回结果数量
            alpha: 向量检索权重 (0-1)，1-alpha 为 BM25 权重

        Returns:
            融合后的结果列表
        """
        logger.info(f"========== RRF 融合 ==========")
        logger.info(f"alpha (向量权重): {alpha}, BM25 权重: {1 - alpha}")

        # 收集所有唯一的 node_id
        all_node_ids = set()
        for item in vector_results:
            all_node_ids.add(item["node"].node_id)
        for item in bm25_results:
            all_node_ids.add(item["node"].node_id)

        logger.info(f"唯一节点数: {len(all_node_ids)}")

        # RRF 算法
        K = settings.hybrid_ranker_k
        fused_scores = {}

        for node_id in all_node_ids:
            vector_rank = None
            bm25_rank = None

            for item in vector_results:
                if item["node"].node_id == node_id:
                    vector_rank = item["vector_rank"]
                    break

            for item in bm25_results:
                if item["node"].node_id == node_id:
                    bm25_rank = item["bm25_rank"]
                    break

            score = 0.0
            if vector_rank is not None:
                score += alpha / (K + vector_rank)
            if bm25_rank is not None:
                score += (1 - alpha) / (K + bm25_rank)

            fused_scores[node_id] = score

        # 按分数排序
        sorted_results = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)

        # 构建最终结果
        retriever_result = []
        for node_id, rrf_score in sorted_results[:similarity_top_k]:
            node = None
            kb_id_val = None
            kb_name_val = None
            vector_score_val = None

            # 查找节点
            for item in vector_results:
                if item["node"].node_id == node_id:
                    node = item["node"]
                    kb_id_val = item["kb_id"]
                    kb_name_val = item["kb_name"]
                    vector_score_val = item["vector_score"]
                    break

            if node is None:
                for item in bm25_results:
                    if item["node"].node_id == node_id:
                        node = item["node"]
                        kb_id_val = item["kb_id"]
                        kb_name_val = item["kb_name"]
                        break

            if node and rrf_score >= similarity_threshold * 0.01:
                try:
                    file_id = self.metadata_manager.get_file_id(
                        node.ref_doc_id,
                        collection_name="common_slice"
                    )
                    file_meta_data = node.metadata.get("file_name", "Unknown")

                    # 提取标题信息（兼容老数据：可能没有标题字段）
                    heading_path = node.metadata.get("heading_path", "")
                    nearest_heading = node.metadata.get("nearest_heading", "")

                    # 将标题信息拼接到 fileText 末尾，供 LLM 使用
                    file_text = f"{node.text}\n"
                    if nearest_heading:
                        file_text += f"[所属章节] {nearest_heading}\n"

                    text_info = {
                        "fileMateData": file_meta_data,
                        "file_id": file_id,
                        "fileText": file_text,
                        "kb_id": kb_id_val,
                        "kb_name": kb_name_val,
                        "rrf_score": rrf_score,
                        "vector_score": vector_score_val,
                        "heading_path": heading_path,
                        "nearest_heading": nearest_heading,
                    }
                    retriever_result.append(text_info)

                except Exception as e:
                    logger.warning(f"处理节点 {node_id} 失败: {e}")

        logger.info(f"混合检索完成，返回 {len(retriever_result)} 个结果")
        return retriever_result


# ============ 向后兼容的函数 ============

def query_question(
    index: VectorStoreIndex,
    question: str,
    milvus_cfg: Dict[str, Any],
    kb_id_list: List[Dict[str, Any]],
    similarity_threshold: float,
    similarity_top_k: int
) -> List[Dict[str, Any]]:
    """向量检索（兼容旧代码）"""
    retriever = VectorRetriever(milvus_cfg)
    return retriever.query(index, question, kb_id_list, similarity_threshold, similarity_top_k)


def query_question_hybrid(
    index: VectorStoreIndex,
    question: str,
    milvus_cfg: Dict[str, Any],
    kb_id_list: List[Dict[str, Any]],
    similarity_threshold: float,
    similarity_top_k: int,
    alpha: float = 0.5
) -> List[Dict[str, Any]]:
    """混合检索（兼容旧代码）"""
    retriever = HybridRetriever(milvus_cfg)
    return retriever.query(index, question, kb_id_list, similarity_threshold, similarity_top_k, alpha)


def query_question_from_file(
    file_name_list: List[str],
    index: VectorStoreIndex,
    question: str,
    similarity_top_k: int
) -> List[Dict[str, Any]]:
    """从文件检索（兼容旧代码）"""
    from llama_index.core.vector_stores import MetadataFilters, ExactMatchFilter

    retriever_result = []

    for file_name in file_name_list:
        filter = MetadataFilters(filters=[ExactMatchFilter(key="file_id", value=file_name)])
        retriever = index.as_retriever(similarity_top_k=similarity_top_k, filters=filter)

        results = retriever.retrieve(question)

        for i, result in enumerate(results):
            file_meta_data = result.metadata.get("file_name", "Unknown")
            file_text = f"{result.node.text}\n"
            text_info = {
                "fileMateData": file_meta_data,
                "fileText": file_text
            }
            retriever_result.append(text_info)

    logger.info(f"文件检索完成，返回 {len(retriever_result)} 个结果")
    return retriever_result


def get_file_id(ref_doc_id: str, collection_name: str, milvus_cfg: Dict[str, Any]) -> int:
    """获取 file_id（兼容旧代码）"""
    manager = MilvusMetadataManager(milvus_cfg)
    return manager.get_file_id(ref_doc_id, collection_name)
