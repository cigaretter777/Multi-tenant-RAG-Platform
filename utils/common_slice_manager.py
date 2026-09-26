"""
common_slice 表管理模块

负责管理 Milvus 中 common_slice 集合的创建和数据插入
"""
import json
from typing import List, Dict, Any, Optional
from pymilvus import MilvusClient

from utils.json_serializer import safe_json_dumps, safe_json_loads

from configs.config import settings
from utils.logger import get_logger

logger = get_logger()


def _node_content_for_storage(node_content: Dict[str, Any]) -> Dict[str, Any]:
    """序列化前移除冗余 embedding，向量已单独存储在 vector 字段中。"""
    if not isinstance(node_content, dict):
        return node_content
    return {k: v for k, v in node_content.items() if k != "embedding"}


class CommonSliceManager:
    """common_slice 表管理器"""

    # 集合名称
    COLLECTION_NAME = "common_slice"

    # 向量维度
    DIM = settings.embedding_dim

    @staticmethod
    def ensure_collection_exists(client: MilvusClient) -> bool:
        """
        确保 common_slice 集合存在，如果不存在则创建

        Args:
            client: Milvus 客户端

        Returns:
            True 如果集合已存在或创建成功
        """
        try:
            # 检查集合是否存在
            if client.has_collection(CommonSliceManager.COLLECTION_NAME):
                logger.info(f"集合 {CommonSliceManager.COLLECTION_NAME} 已存在")
                return True

            # 创建集合
            logger.info(f"创建集合 {CommonSliceManager.COLLECTION_NAME}")

            client.create_collection(
                collection_name=CommonSliceManager.COLLECTION_NAME,
                dimension=CommonSliceManager.DIM,
                auto_id=True,  # 自动生成 ID
                enable_dynamic_field=True,  # 允许动态字段
                consistency_level="Strong"
            )

            # 创建索引
            logger.info(f"为集合 {CommonSliceManager.COLLECTION_NAME} 创建向量索引")
            client.create_index(
                collection_name=CommonSliceManager.COLLECTION_NAME,
                field_name="vector",
                index_type="IVF_FLAT",
                metric_type="IP",  # 内积
                params={"nlist": 128}
            )

            logger.info(f"✅ 集合 {CommonSliceManager.COLLECTION_NAME} 创建成功")
            return True

        except Exception as e:
            logger.error(f"创建集合失败: {str(e)}")
            raise RuntimeError(f"创建集合失败: {str(e)}") from e

    @staticmethod
    def insert_slices(
        client: MilvusClient,
        slices_data: List[Dict[str, Any]]
    ) -> int:
        """
        插入切片数据到 common_slice 表

        Args:
            client: Milvus 客户端
            slices_data: 切片数据列表，格式：
                [
                    {
                        "vector": [0.1, 0.2, ...],  # 向量数据
                        "tenant_id": 123,            # 租户ID (int64)
                        "kb_id": 1,                  # 知识库ID (int64)
                        "file_id": 12345,            # 文件ID (int64)
                        "file_name": "test.pdf",     # 文件名 (varchar)
                        "text": "切片文本内容"  # 文本内容 (varchar)
                    },
                    ...
                ]

        Returns:
            插入的记录数

        Raises:
            RuntimeError: 插入失败时抛出
        """
        if not slices_data:
            logger.warning("切片数据为空，跳过插入")
            return 0

        try:
            # 确保集合存在
            CommonSliceManager.ensure_collection_exists(client)

            total_count = len(slices_data)
            batch_size = settings.milvus_insert_batch_size
            logger.info(
                f"准备插入 {total_count} 条切片数据到 {CommonSliceManager.COLLECTION_NAME}，"
                f"批次大小: {batch_size}"
            )

            inserted_count = 0
            for i in range(0, total_count, batch_size):
                batch = slices_data[i:i + batch_size]
                insert_result = client.insert(
                    collection_name=CommonSliceManager.COLLECTION_NAME,
                    data=batch
                )
                inserted_count += len(batch)
                logger.info(f"已插入 {inserted_count}/{total_count} 条切片数据")
                logger.debug(f"批次插入结果: {insert_result}")

            # 刷新数据，确保数据可被搜索
            client.flush(CommonSliceManager.COLLECTION_NAME)

            logger.info(f"✅ 成功插入 {inserted_count} 条切片数据")

            return inserted_count

        except Exception as e:
            logger.error(f"插入切片数据失败: {str(e)}")
            raise RuntimeError(f"插入切片数据失败: {str(e)}") from e

    @staticmethod
    def extract_and_insert_slices(
        client: MilvusClient,
        index_data: List[Dict[str, Any]],
        file_id: int,
        tenant_id: int,
        kb_id: int
    ) -> int:
        """
        从索引数据中提取切片信息并插入到 common_slice 表（旧版本，单个文件ID）

        Args:
            client: Milvus 客户端
            index_data: 索引数据列表（从 index_manager.extract_index_data 获取）
            file_id: 文件ID（数字）
            tenant_id: 租户ID
            kb_id: 知识库ID

        Returns:
            插入的记录数

        Raises:
            RuntimeError: 插入失败时抛出
        """
        if not index_data:
            logger.warning("索引数据为空，跳过插入")
            return 0

        try:
            # 转换索引数据为 common_slice 格式
            slices_data = []

            for item in index_data:
                # 提取节点内容
                node_content = item.get("_node_content", {})
                if isinstance(node_content, str):
                    node_content = json.loads(node_content)

                # 提取元数据
                metadata = node_content.get("metadata", {})

                slice_record = {
                    "vector": item.get("vector"),  # 向量数据
                    "tenant_id": tenant_id,        # 租户ID
                    "kb_id": kb_id,                # 知识库ID
                    "file_id": file_id,            # 文件ID（int64 类型）
                    "file_name": metadata.get("file_name", ""),  # 文件名
                    "text": node_content.get("text", ""),  # 文本内容（原slice_info改为text）
                    # 添加llama-index需要的关键字段
                    "metadata": safe_json_dumps(node_content.get("metadata", {})),  # 序列化的元数据
                    "_node_content": safe_json_dumps(_node_content_for_storage(node_content)),
                    "ref_doc_id": node_content.get("ref_doc_id", "")  # 从node_content获取文档引用ID
                }

                # 过滤掉向量为空的记录
                if slice_record["vector"] is None:
                    logger.warning(f"跳过向量为空的记录: file_id={file_id}, file_name={slice_record['file_name']}")
                    continue

                slices_data.append(slice_record)

            # 插入数据
            if not slices_data:
                logger.warning("没有有效的切片数据可插入")
                return 0

            return CommonSliceManager.insert_slices(client, slices_data)

        except Exception as e:
            logger.error(f"提取和插入切片数据失败: {str(e)}")
            raise RuntimeError(f"提取和插入切片数据失败: {str(e)}") from e

    @staticmethod
    def extract_and_insert_slices_batch(
        client: MilvusClient,
        index_data: List[Dict[str, Any]],
        tenant_id: int,
        kb_id: int
    ) -> int:
        """
        从索引数据中批量提取切片信息并插入到 common_slice 表（新版本，支持多个文件ID）

        从每个切片的元数据中提取 file_id，支持一个请求处理多个文件，每个文件有不同的 file_id。

        Args:
            client: Milvus 客户端
            index_data: 索引数据列表（从 index_manager.extract_index_data 获取）
            tenant_id: 租户ID
            kb_id: 知识库ID

        Returns:
            插入的记录数

        Raises:
            RuntimeError: 插入失败时抛出
        """
        if not index_data:
            logger.warning("索引数据为空，跳过插入")
            return 0

        try:
            # 转换索引数据为 common_slice 格式
            slices_data = []

            for item in index_data:
                # 提取节点内容
                node_content = item.get("_node_content", {})
                if isinstance(node_content, str):
                    node_content = json.loads(node_content)

                # 提取元数据
                metadata = node_content.get("metadata", {})

                # 从元数据中获取 file_id（如果存在）
                file_id = metadata.get("file_id")
                if file_id is None:
                    logger.warning(f"切片缺少 file_id，跳过: file_name={metadata.get('file_name', '')}")
                    continue

                # 提取文本内容并检查是否为空（OCR可能识别不到文字）
                text = node_content.get("text", "").strip()
                if not text:
                    logger.info(f"跳过无文字内容的切片: file_id={file_id}, file_name={metadata.get('file_name', '')}")
                    continue

                slice_record = {
                    "vector": item.get("vector"),  # 向量数据
                    "tenant_id": tenant_id,        # 租户ID
                    "kb_id": kb_id,                # 知识库ID
                    "file_id": file_id,            # 文件ID（int64 类型，从元数据提取）
                    "file_name": metadata.get("file_name", ""),  # 文件名
                    "text": text,  # 文本内容（已确保非空）
                    # 添加llama-index需要的关键字段
                    "metadata": safe_json_dumps(node_content.get("metadata", {})),  # 序列化的元数据
                    "_node_content": safe_json_dumps(_node_content_for_storage(node_content)),
                    "ref_doc_id": node_content.get("ref_doc_id", "")  # 从node_content获取文档引用ID
                }

                # 过滤掉向量为空的记录
                if slice_record["vector"] is None:
                    logger.warning(f"跳过向量为空的记录: file_id={file_id}, file_name={slice_record['file_name']}")
                    continue

                slices_data.append(slice_record)

            # 插入数据
            if not slices_data:
                logger.warning("没有有效的切片数据可插入")
                return 0

            return CommonSliceManager.insert_slices(client, slices_data)

        except Exception as e:
            logger.error(f"批量提取和插入切片数据失败: {str(e)}")
            raise RuntimeError(f"批量提取和插入切片数据失败: {str(e)}") from e

    @staticmethod
    def search_slices(
        client: MilvusClient,
        query_vector: List[float],
        tenant_id: Optional[int] = None,
        kb_id: Optional[int] = None,
        file_id: Optional[int] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        在 common_slice 表中搜索相似的切片

        Args:
            client: Milvus 客户端
            query_vector: 查询向量
            tenant_id: 租户ID过滤（可选）
            kb_id: 知识库ID过滤（可选）
            file_id: 文件ID过滤（可选，int64 类型）
            limit: 返回结果数量

        Returns:
            搜索结果列表
        """
        try:
            # 构建过滤表达式
            filter_expr = ""
            conditions = []

            if tenant_id is not None:
                conditions.append(f"tenant_id == {tenant_id}")

            if kb_id is not None:
                conditions.append(f"kb_id == {kb_id}")

            if file_id is not None:
                conditions.append(f"file_id == {file_id}")  # int64 类型，不需要引号

            if conditions:
                filter_expr = " and ".join(conditions)

            # 执行搜索
            results = client.search(
                collection_name=CommonSliceManager.COLLECTION_NAME,
                data=[query_vector],
                limit=limit,
                filter=filter_expr if filter_expr else None,
                output_fields=["tenant_id", "kb_id", "file_id", "file_name", "text"]
            )

            # 格式化结果
            formatted_results = []
            for result in results[0]:  # 第一个查询的结果
                formatted_results.append({
                    "id": result["id"],
                    "distance": result["distance"],
                    "tenant_id": result["entity"].get("tenant_id"),
                    "kb_id": result["entity"].get("kb_id"),
                    "file_id": result["entity"].get("file_id"),
                    "file_name": result["entity"].get("file_name"),
                    "text": result["entity"].get("text")
                })

            return formatted_results

        except Exception as e:
            logger.error(f"搜索切片失败: {str(e)}")
            raise RuntimeError(f"搜索切片失败: {str(e)}") from e

    @staticmethod
    def delete_slices(
        client: MilvusClient,
        tenant_id: int,
        kb_id: int,
        file_ids: List[int],
        collection_name: str = COLLECTION_NAME,
        file_id_batch_size: int = 100,
    ) -> int:
        """
        按 tenant_id + kb_id + file_ids 删除 Milvus 中的切片数据

        Args:
            client: Milvus 客户端
            tenant_id: 租户ID
            kb_id: 知识库ID
            file_ids: 文件ID列表
            collection_name: 集合名称
            file_id_batch_size: 单次 filter 中包含的 file_id 数量上限

        Returns:
            删除的记录数
        """
        if not file_ids:
            logger.warning("file_ids 为空，跳过删除")
            return 0

        try:
            if not client.has_collection(collection_name):
                logger.warning(f"集合 {collection_name} 不存在，跳过删除")
                return 0

            unique_file_ids = list(dict.fromkeys(file_ids))
            total_deleted = 0

            logger.info(
                f"准备从 {collection_name} 删除文档切片: "
                f"tenant_id={tenant_id}, kb_id={kb_id}, file_ids={unique_file_ids}"
            )

            for i in range(0, len(unique_file_ids), file_id_batch_size):
                batch_file_ids = unique_file_ids[i:i + file_id_batch_size]
                id_list = ",".join(str(fid) for fid in batch_file_ids)
                filter_expr = (
                    f"tenant_id == {tenant_id} and kb_id == {kb_id} "
                    f"and file_id in [{id_list}]"
                )

                delete_result = client.delete(
                    collection_name=collection_name,
                    filter=filter_expr,
                )
                batch_deleted = delete_result.get("delete_count", 0) if delete_result else 0
                total_deleted += batch_deleted
                logger.info(
                    f"已删除 {batch_deleted} 条切片 "
                    f"(file_ids 批次 {i // file_id_batch_size + 1}, 共 {len(batch_file_ids)} 个 file_id)"
                )

            client.flush(collection_name)
            logger.info(f"✅ 成功从 {collection_name} 删除 {total_deleted} 条切片数据")
            return total_deleted

        except Exception as e:
            logger.error(f"删除切片数据失败: {str(e)}")
            raise RuntimeError(f"删除切片数据失败: {str(e)}") from e


# ============ 便捷函数 ============

def ensure_common_slice_collection(client: MilvusClient) -> bool:
    """确保 common_slice 集合存在"""
    return CommonSliceManager.ensure_collection_exists(client)


def insert_common_slices(
    client: MilvusClient,
    slices_data: List[Dict[str, Any]]
) -> int:
    """插入切片数据到 common_slice 表"""
    return CommonSliceManager.insert_slices(client, slices_data)


def extract_and_insert_common_slices(
    client: MilvusClient,
    index_data: List[Dict[str, Any]],
    file_id: int,
    tenant_id: int,
    kb_id: int
) -> int:
    """从索引数据中提取并插入切片到 common_slice 表（旧版本，单个文件ID）"""
    return CommonSliceManager.extract_and_insert_slices(client, index_data, file_id, tenant_id, kb_id)


def extract_and_insert_common_slices_batch(
    client: MilvusClient,
    index_data: List[Dict[str, Any]],
    tenant_id: int,
    kb_id: int
) -> int:
    """从索引数据中批量提取并插入切片到 common_slice 表（新版本，支持多个文件ID）"""
    return CommonSliceManager.extract_and_insert_slices_batch(client, index_data, tenant_id, kb_id)


def search_common_slices(
    client: MilvusClient,
    query_vector: List[float],
    tenant_id: Optional[int] = None,
    kb_id: Optional[int] = None,
    file_id: Optional[int] = None,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """在 common_slice 表中搜索切片"""
    return CommonSliceManager.search_slices(
        client, query_vector, tenant_id, kb_id, file_id, limit
    )


def delete_common_slices(
    client: MilvusClient,
    tenant_id: int,
    kb_id: int,
    file_ids: List[int],
    collection_name: str = CommonSliceManager.COLLECTION_NAME,
) -> int:
    """按 tenant_id + kb_id + file_ids 删除 common_slice 表中的切片"""
    return CommonSliceManager.delete_slices(
        client, tenant_id, kb_id, file_ids, collection_name
    )
