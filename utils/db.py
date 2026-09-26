"""
PostgreSQL 数据库连接管理模块

提供数据库连接池和基本的数据库操作
"""
import time
from contextlib import asynccontextmanager
from pathlib import Path
import asyncpg
from typing import Optional, Dict, Any, List
from configs.config import settings
from utils.logger import get_logger

logger = get_logger()


class DatabaseManager:
    """PostgreSQL 数据库管理器（单例模式）"""

    _pool: Optional[asyncpg.Pool] = None
    _config: dict = None

    @classmethod
    async def initialize(cls):
        """初始化数据库连接池"""
        if cls._pool is not None:
            logger.debug("数据库连接池已存在")
            return

        cls._config = settings.postgres_config

        logger.info(f"正在连接 PostgreSQL: {cls._config['host']}:{cls._config['port']}/{cls._config['database']}")
        logger.info(f"使用 Schema: {cls._config['schema']}")

        try:
            cls._pool = await asyncpg.create_pool(
                host=cls._config['host'],
                port=cls._config['port'],
                user=cls._config['user'],
                password=cls._config['password'],
                database=cls._config['database'],
                min_size=5,
                max_size=20,
                command_timeout=60,
                server_settings={
                    "search_path": cls._config['schema']
                }
            )
            logger.info("PostgreSQL 连接池创建成功")

        except Exception as e:
            logger.error(f"PostgreSQL 连接失败: {str(e)}")
            raise RuntimeError(f"PostgreSQL 连接失败: {str(e)}") from e

    @classmethod
    async def close(cls):
        """关闭数据库连接池"""
        if cls._pool:
            await cls._pool.close()
            cls._pool = None
            logger.info("PostgreSQL 连接池已关闭")

    @classmethod
    def get_pool(cls) -> asyncpg.Pool:
        """获取数据库连接池"""
        if cls._pool is None:
            raise RuntimeError("数据库连接池未初始化，请先调用 initialize()")
        return cls._pool

    @classmethod
    async def execute(cls, query: str, *args):
        """执行 SQL 语句（无返回结果）"""
        pool = cls.get_pool()
        async with pool.acquire() as conn:
            return await conn.execute(query, *args)

    @classmethod
    async def fetch(cls, query: str, *args):
        """执行 SQL 查询，返回所有结果"""
        pool = cls.get_pool()
        async with pool.acquire() as conn:
            return await conn.fetch(query, *args)

    @classmethod
    async def fetchrow(cls, query: str, *args):
        """执行 SQL 查询，返回单行结果"""
        pool = cls.get_pool()
        async with pool.acquire() as conn:
            return await conn.fetchrow(query, *args)

    @classmethod
    async def executemany(cls, command: str, args):
        """批量执行 SQL 语句"""
        pool = cls.get_pool()
        async with pool.acquire() as conn:
            return await conn.executemany(command, args)

    @classmethod
    @asynccontextmanager
    async def transaction(cls):
        """获取单一连接并开启事务（用于跨表原子写入）"""
        pool = cls.get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                yield conn


# ============ 数据库初始化表 ============

CREATE_SCHEMA_RAG_IF_NOT_EXISTS = """
CREATE SCHEMA IF NOT EXISTS rag;
"""

CREATE_TABLE_PARSED_DOCUMENTS = """
CREATE TABLE IF NOT EXISTS rag.parsed_documents (
    id SERIAL PRIMARY KEY,
    parse_id VARCHAR(255) NOT NULL,
    file_id BIGINT,
    file_name VARCHAR(255),
    original_text TEXT,              -- 原始文本
    semantic_text TEXT,              -- 防护后的文本（semantic_cleaned_data）
    document_text TEXT NOT NULL,     -- 最终用于向量化的文本
    document_metadata JSONB,
    created_at BIGINT NOT NULL,
    expires_at BIGINT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_parsed_documents_parse_id ON rag.parsed_documents(parse_id);
CREATE INDEX IF NOT EXISTS idx_parsed_documents_expires_at ON rag.parsed_documents(expires_at);
"""

# [新增] 任务状态表
CREATE_TABLE_PROCESS_TASKS = """
CREATE TABLE IF NOT EXISTS rag.process_tasks (
    task_id VARCHAR(255) PRIMARY KEY,
    tenant_id BIGINT,
    kb_id BIGINT,
    parse_status VARCHAR(50) DEFAULT 'pending', -- pending, processing, finish, failed, waiting_confirmation
    embed_status VARCHAR(50) DEFAULT 'pending', -- pending, processing, finish, failed, skipped
    file_count INT,
    file_ids TEXT[], -- 文件ID列表
    needs_confirmation BOOLEAN DEFAULT false, -- 是否需要用户确认
    confirmation_status VARCHAR(50) DEFAULT 'none', -- none, pending, partial, confirmed
    error_message TEXT,
    build_graph_requested BOOLEAN DEFAULT false,
    graph_status VARCHAR(50) DEFAULT 'skipped',
    graph_task_id VARCHAR(255),
    graph_error TEXT,
    domain_brief JSONB,
    graph_chunk_size INT,
    graph_chunk_overlap INT,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_process_tasks_created_at ON rag.process_tasks(created_at);
"""

# [新增] 知识库元数据表 - 记录每个KB使用的embedding模型
CREATE_TABLE_KB_METADATA = """
CREATE TABLE IF NOT EXISTS rag.kb_metadata (
    kb_id BIGINT PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    embedding_model VARCHAR(100) NOT NULL,  -- 使用的embedding模型名称
    embedding_dim INT NOT NULL,              -- 向量维度
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_kb_metadata_tenant_id ON rag.kb_metadata(tenant_id);
"""


async def apply_control_plane_migration() -> None:
    """执行控制面迁移（tenants / principals / api_keys / knowledge_bases）"""
    migration_path = Path(__file__).resolve().parents[1] / "migrations" / "001_control_plane.sql"
    await DatabaseManager.execute(migration_path.read_text(encoding="utf-8"))


async def init_database():
    """初始化数据库表"""
    try:
        await DatabaseManager.initialize()

        logger.info("正在创建数据库 schema 和表...")
        # 先创建 schema
        await DatabaseManager.execute(CREATE_SCHEMA_RAG_IF_NOT_EXISTS)
        # 控制面表（幂等迁移）
        await apply_control_plane_migration()
        # 再创建表
        await DatabaseManager.execute(CREATE_TABLE_PARSED_DOCUMENTS)
        # [新增] 创建任务表
        await DatabaseManager.execute(CREATE_TABLE_PROCESS_TASKS)
        # [新增] 创建知识库元数据表
        await DatabaseManager.execute(CREATE_TABLE_KB_METADATA)

        # [迁移] 为已存在的 process_tasks 表添加 file_ids 字段
        try:
            alter_table_sql = """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'rag'
                        AND table_name = 'process_tasks'
                        AND column_name = 'file_ids'
                    ) THEN
                        ALTER TABLE rag.process_tasks ADD COLUMN file_ids TEXT[];
                    END IF;
                END $$;
            """
            await DatabaseManager.execute(alter_table_sql)
            logger.info("数据库迁移完成: 添加 file_ids 字段")
        except Exception as migrate_error:
            logger.warning(f"迁移 file_ids 字段失败（可能已存在）: {str(migrate_error)}")

        # [迁移] 为已存在的 process_tasks 表添加 source_type 字段
        try:
            alter_table_sql = """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'rag'
                        AND table_name = 'process_tasks'
                        AND column_name = 'source_type'
                    ) THEN
                        ALTER TABLE rag.process_tasks ADD COLUMN source_type VARCHAR(20) DEFAULT 'file';
                    END IF;
                END $$;
            """
            await DatabaseManager.execute(alter_table_sql)
            logger.info("数据库迁移完成: 添加 source_type 字段")
        except Exception as migrate_error:
            logger.warning(f"迁移 source_type 字段失败（可能已存在）: {str(migrate_error)}")

        # [迁移] GraphRAG 建图相关字段
        graph_columns = [
            ("build_graph_requested", "BOOLEAN DEFAULT false"),
            ("graph_status", "VARCHAR(50) DEFAULT 'skipped'"),
            ("graph_task_id", "VARCHAR(255)"),
            ("graph_error", "TEXT"),
            ("domain_brief", "JSONB"),
            ("graph_chunk_size", "INT"),
            ("graph_chunk_overlap", "INT"),
        ]
        for column_name, column_def in graph_columns:
            try:
                alter_table_sql = f"""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_schema = 'rag'
                            AND table_name = 'process_tasks'
                            AND column_name = '{column_name}'
                        ) THEN
                            ALTER TABLE rag.process_tasks ADD COLUMN {column_name} {column_def};
                        END IF;
                    END $$;
                """
                await DatabaseManager.execute(alter_table_sql)
                logger.info(f"数据库迁移完成: 添加 {column_name} 字段")
            except Exception as migrate_error:
                logger.warning(f"迁移 {column_name} 字段失败（可能已存在）: {str(migrate_error)}")

        logger.info("数据库表创建/检查完成")

        return True

    except Exception as e:
        logger.error(f"初始化数据库失败: {str(e)}")
        raise RuntimeError(f"初始化数据库失败: {str(e)}") from e


async def close_database():
    """关闭数据库连接"""
    await DatabaseManager.close()


# ============ 知识库元数据管理器 ============

class KBMetadataManager:
    """知识库元数据管理器 - 管理KB与embedding模型的绑定关系"""

    @classmethod
    async def get_kb_metadata(cls, kb_id: int) -> Optional[Dict[str, Any]]:
        """
        获取知识库的元数据

        Args:
            kb_id: 知识库ID

        Returns:
            元数据字典，如果不存在返回None
        """
        query = """
            SELECT kb_id, tenant_id, embedding_model, embedding_dim, created_at, updated_at
            FROM rag.kb_metadata
            WHERE kb_id = $1
        """
        row = await DatabaseManager.fetchrow(query, kb_id)
        if row:
            return dict(row)
        return None

    @classmethod
    async def create_or_update_kb_metadata(
        cls,
        kb_id: int,
        tenant_id: int,
        embedding_model: str,
        embedding_dim: int
    ) -> Dict[str, Any]:
        """
        创建或更新知识库元数据

        Args:
            kb_id: 知识库ID
            tenant_id: 租户ID
            embedding_model: embedding模型名称
            embedding_dim: 向量维度

        Returns:
            操作结果
        """
        current_time = int(time.time())

        query = """
            INSERT INTO rag.kb_metadata (kb_id, tenant_id, embedding_model, embedding_dim, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (kb_id) DO UPDATE
            SET embedding_model = $3, embedding_dim = $4, updated_at = $6
            RETURNING kb_id, tenant_id, embedding_model, embedding_dim, created_at, updated_at
        """

        row = await DatabaseManager.fetchrow(
            query, kb_id, tenant_id, embedding_model, embedding_dim, current_time, current_time
        )
        return dict(row) if row else None

    @classmethod
    async def validate_kb_model_consistency(
        cls,
        kb_id_list: List[int],
        expected_model: str = None
    ) -> Dict[str, Any]:
        """
        验证多个KB的模型一致性

        Args:
            kb_id_list: 知识库ID列表
            expected_model: 期望的模型名称（可选，用于校验）

        Returns:
            {
                "is_consistent": bool,  # 是否所有KB使用相同模型
                "model": str,           # 如果一致，返回模型名称
                "error": str,           # 如果不一致，返回错误信息
                "kb_models": Dict[int, str]  # 每个KB的模型信息
            }
        """
        if not kb_id_list:
            return {
                "is_consistent": True,
                "model": expected_model,
                "error": None,
                "kb_models": {}
            }

        # 查询所有KB的元数据
        placeholders = ','.join([f'${i+1}' for i in range(len(kb_id_list))])
        query = f"""
            SELECT kb_id, embedding_model
            FROM rag.kb_metadata
            WHERE kb_id IN ({placeholders})
        """

        rows = await DatabaseManager.fetch(query, *kb_id_list)
        kb_models = {row['kb_id']: row['embedding_model'] for row in rows}

        # 检查是否有KB没有元数据记录
        missing_kb_ids = set(kb_id_list) - set(kb_models.keys())
        if missing_kb_ids:
            return {
                "is_consistent": False,
                "model": None,
                "error": f"知识库 {missing_kb_ids} 没有元数据记录，可能尚未构建",
                "kb_models": kb_models
            }

        # 检查模型一致性
        unique_models = set(kb_models.values())
        if len(unique_models) > 1:
            return {
                "is_consistent": False,
                "model": None,
                "error": f"知识库使用了不同的embedding模型: {dict(kb_models)}",
                "kb_models": kb_models
            }

        model = list(unique_models)[0]

        # 如果指定了期望模型，检查是否匹配
        if expected_model and model != expected_model:
            return {
                "is_consistent": False,
                "model": model,
                "error": f"期望使用模型 '{expected_model}'，但知识库使用的是 '{model}'",
                "kb_models": kb_models
            }

        return {
            "is_consistent": True,
            "model": model,
            "error": None,
            "kb_models": kb_models
        }

    @classmethod
    async def get_or_create_kb_model(
        cls,
        kb_id: int,
        tenant_id: int,
        requested_model: str = None,
        requested_dim: int = None,
        default_model: str = None,
        default_dim: int = None
    ) -> Dict[str, Any]:
        """
        获取KB的模型配置，如果不存在则创建

        Args:
            kb_id: 知识库ID
            tenant_id: 租户ID
            requested_model: 请求指定的模型（可选）
            requested_dim: 请求指定的维度（可选）
            default_model: 默认模型
            default_dim: 默认维度

        Returns:
            {
                "kb_id": int,
                "embedding_model": str,
                "embedding_dim": int,
                "is_new": bool,  # 是否是新创建的
                "model_changed": bool  # 模型是否发生变化（用于重建场景）
            }
        """
        current_time = int(time.time())

        # 获取现有元数据
        existing = await cls.get_kb_metadata(kb_id)

        if existing:
            # KB已存在，检查模型是否一致
            if requested_model and requested_model != existing['embedding_model']:
                # 模型不一致，更新为新模型（重建场景）
                logger.warning(
                    f"知识库 {kb_id} 的模型从 '{existing['embedding_model']}' "
                    f"变更为 '{requested_model}'"
                )
                effective_model = requested_model
                effective_dim = requested_dim or existing['embedding_dim']
                is_new = False
                model_changed = True
            else:
                # 使用已有模型
                effective_model = existing['embedding_model']
                effective_dim = existing['embedding_dim']
                is_new = False
                model_changed = False

            # 如果模型有变化，更新元数据
            if model_changed:
                await cls.create_or_update_kb_metadata(
                    kb_id, tenant_id, effective_model, effective_dim
                )

            return {
                "kb_id": kb_id,
                "embedding_model": effective_model,
                "embedding_dim": effective_dim,
                "is_new": is_new,
                "model_changed": model_changed
            }
        else:
            # 新KB，创建元数据
            effective_model = requested_model or default_model
            effective_dim = requested_dim or default_dim

            if not effective_model or not effective_dim:
                raise ValueError(
                    f"知识库 {kb_id} 没有元数据记录，且未提供模型参数"
                )

            await cls.create_or_update_kb_metadata(
                kb_id, tenant_id, effective_model, effective_dim
            )

            logger.info(
                f"为知识库 {kb_id} 创建元数据: model={effective_model}, dim={effective_dim}"
            )

            return {
                "kb_id": kb_id,
                "embedding_model": effective_model,
                "embedding_dim": effective_dim,
                "is_new": True,
                "model_changed": False
            }

