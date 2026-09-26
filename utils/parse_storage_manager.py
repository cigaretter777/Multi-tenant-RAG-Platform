"""
解析结果存储管理模块

使用 PostgreSQL 存储解析后的文档结果
"""
import json
import time
import uuid
from typing import List, Dict, Any, Optional

from utils.db import DatabaseManager
from utils.logger import get_logger

logger = get_logger()


def clean_text_for_postgres(text: Optional[str]) -> Optional[str]:
    """
    清理文本，移除 PostgreSQL 不支持的字符（如空字节 \x00）

    Args:
        text: 原始文本

    Returns:
        清理后的文本
    """
    if text is None:
        return None
    # 移除空字节 (0x00) 和其他控制字符
    return text.replace('\x00', '')


class ParseStorageManager:
    """解析结果存储管理器 - 使用 PostgreSQL 存储"""

    @staticmethod
    def generate_parse_id() -> str:
        """
        生成唯一的解析任务ID

        Returns:
            UUID v4 格式的字符串
        """
        return str(uuid.uuid4())

    @staticmethod
    async def save_parse_result(
        documents: List[Any],
        file_list: List[Dict[str, Any]],
        expires_in: int = 86400,
        parse_id: Optional[str] = None,  # [新增参数] 支持外部传入 parse_id
        guarded_infos: Any = None  # [新增参数] GuardedDocumentInfo 列表
    ) -> Dict[str, Any]:
        """
        保存解析结果到 PostgreSQL（去重：跳过已存在的 file_id）

        Args:
            documents: llama_index Document 对象列表（兼容旧版）或 GuardedDocumentInfo 列表
            file_list: 原始文件信息列表
            expires_in: 过期时间（秒），默认 24 小时
            parse_id: 解析任务ID
            guarded_infos: GuardedDocumentInfo 列表（防护模式下的结果）

        Returns:
            保存结果的统计信息，包含 needs_confirmation 标识

        Raises:
            RuntimeError: 保存失败时抛出
        """
        if not documents:
            logger.warning("文档列表为空，跳过保存")
            return {"parse_id": parse_id, "document_count": 0, "file_count": 0, "skipped_count": 0, "needs_confirmation": False}

        try:
            from utils.db import DatabaseManager

            # 判断是否为 GuardedDocumentInfo 列表
            is_guarded = guarded_infos is not None and len(guarded_infos) > 0
            if is_guarded:
                docs_to_process = guarded_infos
            else:
                docs_to_process = documents

            # 收集所有 file_id
            file_ids = set()
            for item in docs_to_process:
                if is_guarded:
                    # GuardedDocumentInfo
                    file_id = item.document.metadata.get("file_id")
                else:
                    # 普通Document
                    file_id = item.metadata.get("file_id")
                if file_id is not None:
                    file_ids.add(file_id)

            if not file_ids:
                logger.warning("没有有效的 file_id，跳过保存")
                return {"parse_id": "", "document_count": 0, "file_count": 0, "skipped_count": 0, "needs_confirmation": False}

            # 查询已存在的 file_id
            check_query = """
                SELECT DISTINCT file_id
                FROM parsed_documents
                WHERE file_id = ANY($1)
            """

            existing_rows = await DatabaseManager.fetch(check_query, list(file_ids))
            existing_file_ids = {row['file_id'] for row in existing_rows}

            # 过滤掉已存在的 file_id 对应的文档
            new_items = []
            skipped_file_ids = set()

            for item in docs_to_process:
                if is_guarded:
                    file_id = item.document.metadata.get("file_id")
                else:
                    file_id = item.metadata.get("file_id")
                if file_id in existing_file_ids:
                    skipped_file_ids.add(file_id)
                    continue
                new_items.append(item)

            if not new_items:
                logger.info(f"所有文件已存在，跳过保存。file_ids: {file_ids}")
                return {"parse_id": "", "document_count": 0, "file_count": 0, "skipped_count": len(docs_to_process), "reason": "所有文件已存在", "needs_confirmation": False}

            if skipped_file_ids:
                logger.info(f"跳过已存在的文件: {skipped_file_ids}")

            # [逻辑变更] 确定使用的 parse_id
            if not parse_id:
                parse_id = ParseStorageManager.generate_parse_id()

            # 计算过期时间戳
            expires_at = int(time.time()) + expires_in
            created_at = int(time.time())

            # 准备批量插入数据
            file_id_set = set()
            records_to_insert = []
            needs_confirmation = False

            for item in new_items:
                if is_guarded:
                    # GuardedDocumentInfo 处理
                    doc = item.document
                    file_id = doc.metadata.get("file_id")
                    original_text = item.original_text
                    semantic_text = item.semantic_text
                    document_text = original_text  # 初始使用原始文本
                    if item.needs_confirmation:
                        needs_confirmation = True
                else:
                    # 普通 Document 处理
                    doc = item
                    file_id = doc.metadata.get("file_id")
                    original_text = doc.text
                    semantic_text = None
                    document_text = doc.text

                if file_id is not None:
                    file_id_set.add(file_id)

                # 将 metadata 转为 JSON
                metadata_json = json.dumps(doc.metadata, ensure_ascii=False)

                # 清理文本，移除 PostgreSQL 不支持的字符（空字节）
                safe_original_text = clean_text_for_postgres(original_text)
                safe_semantic_text = clean_text_for_postgres(semantic_text)
                safe_document_text = clean_text_for_postgres(document_text)

                records_to_insert.append((
                    parse_id,
                    file_id,
                    doc.metadata.get("file_name", ""),
                    safe_original_text,
                    safe_semantic_text,
                    safe_document_text,
                    metadata_json,
                    created_at,
                    expires_at
                ))

            # 批量插入（包含新字段）
            insert_query = """
                INSERT INTO parsed_documents
                (parse_id, file_id, file_name, original_text, semantic_text, document_text, document_metadata, created_at, expires_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """

            await DatabaseManager.executemany(insert_query, records_to_insert)

            result = {
                "parse_id": parse_id,
                "document_count": len(new_items),
                "file_count": len(file_id_set),
                "expires_at": expires_at,
                "skipped_count": len(docs_to_process) - len(new_items),
                "needs_confirmation": needs_confirmation
            }

            logger.info(f"成功保存解析结果: parse_id={parse_id}, documents={result['document_count']}, files={result['file_count']}, skipped={result['skipped_count']}")
            return result

        except Exception as e:
            logger.error(f"保存解析结果失败: {str(e)}")
            raise RuntimeError(f"保存解析结果失败: {str(e)}") from e

    # [新增] 根据 file_id 列表获取已解析的文档
    @staticmethod
    async def get_documents_by_file_ids(
            file_ids: List[int]
    ) -> List[Dict[str, Any]]:
        """
        根据 file_id 列表从 PostgreSQL 加载已解析的文档
        """
        if not file_ids:
            return []

        try:
            from utils.db import DatabaseManager

            # 查询指定 file_id 的所有文档片段（包含原始文本和语义清洗文本）
            query = """
                SELECT file_id, original_text, semantic_text, document_text, document_metadata, expires_at
                FROM parsed_documents
                WHERE file_id = ANY($1)
            """

            rows = await DatabaseManager.fetch(query, file_ids)

            documents = []
            current_time = int(time.time())

            for row in rows:
                # 检查过期 (可选：如果需要严格控制过期，取消注释)
                # if row['expires_at'] < current_time:
                #     continue

                try:
                    metadata = json.loads(row['document_metadata']) if row['document_metadata'] else {}
                except json.JSONDecodeError:
                    metadata = {}

                # 确保 metadata 中包含 file_id
                if 'file_id' not in metadata:
                    metadata['file_id'] = row['file_id']

                documents.append({
                    "text": row['document_text'],  # 使用 document_text（最终用于向量化的文本）
                    "metadata": metadata,
                    "original_text": row['original_text'],
                    "semantic_text": row['semantic_text']
                })

            logger.info(f"从数据库命中已解析文档: {len(documents)} 个片段 (查询 file_ids: {len(file_ids)})")
            return documents

        except Exception as e:
            logger.error(f"获取已解析文档失败: {str(e)}")
            return []

    @staticmethod
    async def get_parsed_files_by_parse_id(
        parse_id: str,
        file_ids: Optional[List[int]] = None,
    ) -> List[Dict[str, Any]]:
        """
        按 parse_id 获取文件级解析结果（用于 GraphRAG 建图）

        同一 file_id 若有多条记录，会按 id 顺序拼接 document_text。
        """
        if not parse_id:
            return []

        try:
            if file_ids:
                query = """
                    SELECT file_id, file_name, document_text
                    FROM rag.parsed_documents
                    WHERE parse_id = $1 AND file_id = ANY($2)
                    ORDER BY file_id, id
                """
                rows = await DatabaseManager.fetch(query, parse_id, file_ids)
            else:
                query = """
                    SELECT file_id, file_name, document_text
                    FROM rag.parsed_documents
                    WHERE parse_id = $1 AND file_id IS NOT NULL
                    ORDER BY file_id, id
                """
                rows = await DatabaseManager.fetch(query, parse_id)

            grouped: Dict[int, Dict[str, Any]] = {}
            for row in rows:
                fid = row["file_id"]
                if fid is None:
                    continue
                text = row.get("document_text") or ""
                if fid not in grouped:
                    grouped[fid] = {
                        "file_id": fid,
                        "file_name": row.get("file_name") or f"file_{fid}",
                        "document_text": text,
                    }
                elif text:
                    grouped[fid]["document_text"] += "\n" + text

            result = list(grouped.values())
            logger.info(
                f"按 parse_id 获取建图文件: parse_id={parse_id}, file_count={len(result)}"
            )
            return result

        except Exception as e:
            logger.error(f"按 parse_id 获取建图文件失败: {str(e)}")
            return []

    @staticmethod
    async def load_parse_result(
        parse_id: str
    ) -> List[Dict[str, Any]]:
        """
        从 PostgreSQL 加载解析结果

        Args:
            parse_id: 解析任务ID

        Returns:
            Document 数据列表，格式: [{"text": "...", "metadata": {...}}, ...]

        Raises:
            ValueError: 如果 parse_id 不存在或已过期
            RuntimeError: 加载失败时抛出
        """
        try:
            from utils.db import DatabaseManager

            # 查询数据（包含新字段）
            query = """
                SELECT original_text, semantic_text, document_text, document_metadata, expires_at
                FROM parsed_documents
                WHERE parse_id = $1
                ORDER BY id
            """

            rows = await DatabaseManager.fetch(query, parse_id)

            if not rows:
                raise ValueError(f"解析任务不存在或已过期: parse_id={parse_id}")

            # 检查是否过期
            current_time = int(time.time())
            first_expires_at = rows[0]['expires_at']

            if first_expires_at < current_time:
                # 自动清理过期数据
                await ParseStorageManager.delete_parse_result(parse_id)
                raise ValueError(f"解析任务已过期: parse_id={parse_id}")

            # 转换为 Document 格式
            documents = []
            for row in rows:
                try:
                    metadata = json.loads(row['document_metadata']) if row['document_metadata'] else {}
                except json.JSONDecodeError:
                    metadata = {}

                documents.append({
                    "text": row['document_text'],  # 使用 document_text
                    "metadata": metadata,
                    "original_text": row['original_text'],
                    "semantic_text": row['semantic_text']
                })

            logger.info(f"成功加载解析结果: parse_id={parse_id}, documents={len(documents)}")
            return documents

        except ValueError:
            raise
        except Exception as e:
            logger.error(f"加载解析结果失败: {str(e)}")
            raise RuntimeError(f"加载解析结果失败: {str(e)}") from e

    @staticmethod
    async def delete_parse_result(
        parse_id: str
    ) -> int:
        """
        删除指定 parse_id 的解析结果

        Args:
            parse_id: 解析任务ID

        Returns:
            删除的记录数
        """
        try:
            from utils.db import DatabaseManager

            # 删除数据
            delete_query = "DELETE FROM parsed_documents WHERE parse_id = $1"
            result = await DatabaseManager.execute(delete_query, parse_id)

            # 解析返回结果，获取删除数量
            # PostgreSQL 的 DELETE 返回 "DELETE 0" 或 "DELETE n"
            deleted_count = int(result.split()[-1]) if result else 0

            logger.info(f"删除解析结果: parse_id={parse_id}, count={deleted_count}")
            return deleted_count

        except Exception as e:
            logger.error(f"删除解析结果失败: {str(e)}")
            raise RuntimeError(f"删除解析结果失败: {str(e)}") from e

    @staticmethod
    async def delete_documents_by_file_ids(file_ids: List[int]) -> int:
        """
        按 file_id 列表删除 parsed_documents 中的解析缓存

        Args:
            file_ids: 文件ID列表

        Returns:
            删除的记录数
        """
        if not file_ids:
            logger.warning("file_ids 为空，跳过 PG 删除")
            return 0

        try:
            from utils.db import DatabaseManager

            unique_file_ids = list(dict.fromkeys(file_ids))
            delete_query = "DELETE FROM rag.parsed_documents WHERE file_id = ANY($1)"
            result = await DatabaseManager.execute(delete_query, unique_file_ids)

            deleted_count = int(result.split()[-1]) if result else 0
            logger.info(f"删除解析缓存: file_ids={unique_file_ids}, count={deleted_count}")
            return deleted_count

        except Exception as e:
            logger.error(f"按 file_id 删除解析缓存失败: {str(e)}")
            raise RuntimeError(f"按 file_id 删除解析缓存失败: {str(e)}") from e

    @staticmethod
    async def get_parse_status(
        parse_id: str
    ) -> Dict[str, Any]:
        """
        获取解析任务的状态信息

        Args:
            parse_id: 解析任务ID

        Returns:
            状态信息字典
        """
        try:
            from utils.db import DatabaseManager

            # 查询数据
            query = """
                SELECT
                    COUNT(DISTINCT file_id) as file_count,
                    COUNT(*) as document_count,
                    MAX(expires_at) as expires_at
                FROM parsed_documents
                WHERE parse_id = $1
            """

            row = await DatabaseManager.fetchrow(query, parse_id)

            if not row or row['document_count'] == 0:
                return {
                    "parse_id": parse_id,
                    "status": "not_found",
                    "file_count": 0,
                    "document_count": 0,
                    "expires_at": None
                }

            # 检查是否过期
            current_time = int(time.time())
            expires_at = row['expires_at']

            if expires_at < current_time:
                return {
                    "parse_id": parse_id,
                    "status": "expired",
                    "file_count": 0,
                    "document_count": 0,
                    "expires_at": expires_at
                }

            return {
                "parse_id": parse_id,
                "status": "ready",
                "file_count": row['file_count'],
                "document_count": row['document_count'],
                "expires_at": expires_at
            }

        except Exception as e:
            logger.error(f"获取解析任务状态失败: {str(e)}")
            raise RuntimeError(f"获取解析任务状态失败: {str(e)}") from e

    @staticmethod
    async def cleanup_expired() -> int:
        """
        清理所有过期的解析结果

        Returns:
            清理的记录数
        """
        try:
            from utils.db import DatabaseManager

            current_time = int(time.time())

            # 删除过期数据
            delete_query = "DELETE FROM parsed_documents WHERE expires_at < $1"
            result = await DatabaseManager.execute(delete_query, current_time)

            # 解析返回结果
            deleted_count = int(result.split()[-1]) if result else 0

            if deleted_count > 0:
                logger.info(f"清理过期解析结果: count={deleted_count}")

            return deleted_count

        except Exception as e:
            logger.error(f"清理过期解析结果失败: {str(e)}")
            raise RuntimeError(f"清理过期解析结果失败: {str(e)}") from e

    @staticmethod
    async def get_documents_by_parse_id(parse_id: str) -> List[Dict[str, Any]]:
        """
        根据解析任务 ID 获取所有解析后的文档片段

        Args:
            parse_id: 任务 ID (task_id)

        Returns:
            List[Dict]: 包含 text 和 metadata 的列表
        """
        # 查询逻辑需与 save_parse_result 存储的结构对应（包含新字段）
        query = """
                SELECT file_id, file_name, original_text, semantic_text, document_text, document_metadata
                FROM rag.parsed_documents
                WHERE parse_id = $1
                ORDER BY id
                """

        try:
            rows = await DatabaseManager.fetch(query, parse_id)
            if not rows:
                logger.warning(f"未找到 parse_id 为 {parse_id} 的解析记录")
                return []

            # 将数据库行对象转换为字典列表
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"从数据库获取解析结果失败: {str(e)}")
            raise

    @staticmethod
    async def save_database_parse_result(
        documents: List[Any],
        parse_id: str,
        expires_in: int = 86400,
    ) -> Dict[str, Any]:
        """
        保存数据库读取结果到 PostgreSQL（无 file_id，不复用去重逻辑）

        Args:
            documents: LlamaIndex Document 对象列表
            parse_id: 解析/读取任务ID
            expires_in: 过期时间（秒），默认 24 小时

        Returns:
            保存结果的统计信息
        """
        if not documents:
            logger.warning("文档列表为空，跳过保存")
            return {"parse_id": parse_id, "document_count": 0, "row_count": 0}

        try:
            expires_at = int(time.time()) + expires_in
            created_at = int(time.time())
            records_to_insert = []

            for doc in documents:
                text = doc.text if doc.text else ""
                metadata_json = json.dumps(doc.metadata, ensure_ascii=False) if doc.metadata else "{}"
                safe_text = clean_text_for_postgres(text)

                records_to_insert.append((
                    parse_id,
                    None,  # file_id 为 NULL
                    doc.metadata.get("source", "database"),  # file_name 用 source 标识
                    safe_text,  # original_text
                    None,  # semantic_text
                    safe_text,  # document_text
                    metadata_json,
                    created_at,
                    expires_at,
                ))

            insert_query = """
                INSERT INTO parsed_documents
                (parse_id, file_id, file_name, original_text, semantic_text, document_text, document_metadata, created_at, expires_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """

            await DatabaseManager.executemany(insert_query, records_to_insert)

            result = {
                "parse_id": parse_id,
                "document_count": len(documents),
                "row_count": len(documents),
            }
            logger.info(
                f"成功保存数据库读取结果: parse_id={parse_id}, "
                f"documents={result['document_count']}"
            )
            return result

        except Exception as e:
            logger.error(f"保存数据库读取结果失败: {str(e)}")
            raise RuntimeError(f"保存数据库读取结果失败: {str(e)}") from e


# ============ 便捷函数 ============

def generate_parse_id() -> str:
    """生成唯一的解析任务ID"""
    return ParseStorageManager.generate_parse_id()


async def save_parse_result(
    documents: List[Any],
    file_list: List[Dict[str, Any]],
    expires_in: int = 86400
) -> Dict[str, Any]:
    """保存解析结果到 PostgreSQL"""
    return await ParseStorageManager.save_parse_result(documents, file_list, expires_in)


async def load_parse_result(
    parse_id: str
) -> List[Dict[str, Any]]:
    """从 PostgreSQL 加载解析结果"""
    return await ParseStorageManager.load_parse_result(parse_id)


async def delete_parse_result(
    parse_id: str
) -> int:
    """删除指定 parse_id 的解析结果"""
    return await ParseStorageManager.delete_parse_result(parse_id)


async def delete_documents_by_file_ids(file_ids: List[int]) -> int:
    """按 file_id 列表删除 parsed_documents 中的解析缓存"""
    return await ParseStorageManager.delete_documents_by_file_ids(file_ids)


async def get_parse_status(
    parse_id: str
) -> Dict[str, Any]:
    """获取解析任务的状态信息"""
    return await ParseStorageManager.get_parse_status(parse_id)


async def cleanup_expired_parse_results() -> int:
    """清理所有过期的解析结果"""
    return await ParseStorageManager.cleanup_expired()
