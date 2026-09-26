"""
数据库安全读取模块

基于 SQLAlchemy + LlamaIndex Document 实现的数据库接入层。
解决原生 DatabaseReader 无法分页、无法指定 text_column 的局限，
同时保留对多数据库的兼容能力。

功能：
- 驱动运行时检测
- SQL 只读校验（黑名单）
- 超长检测（COUNT(*) 预估）
- SQLAlchemy 流式游标分页读取（避免 OOM）
- 自动转为 LlamaIndex Document 列表
"""

import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from llama_index.core import Document

from utils.logger import get_logger

logger = get_logger()

# 数据库类型 -> SQLAlchemy dialect 映射
DIALECT_MAP = {
    "postgresql": "postgresql+psycopg2",
    "mysql": "mysql+pymysql",
    "oracle": "oracle+cx_oracle",
    "mssql": "mssql+pyodbc",
    "sqlite": "sqlite",
}

# 运行时驱动检测映射：dialect -> Python 包名
DRIVER_IMPORT_MAP = {
    "postgresql+psycopg2": "psycopg2",
    "mysql+pymysql": "pymysql",
    "oracle+cx_oracle": "cx_Oracle",
    "mssql+pyodbc": "pyodbc",
    "sqlite": "sqlite3",  # 内置
}

# pip 安装包名提示
DRIVER_PACKAGE_MAP = {
    "postgresql": "psycopg2-binary",
    "mysql": "pymysql",
    "oracle": "cx-oracle",
    "mssql": "pyodbc",
    "sqlite": None,  # 内置
}

# SQL 写操作关键字黑名单（正则）
WRITE_KEYWORD_PATTERNS = [
    r"\bINSERT\b",
    r"\bUPDATE\b",
    r"\bDELETE\b",
    r"\bDROP\b",
    r"\bALTER\b",
    r"\bCREATE\b",
    r"\bTRUNCATE\b",
    r"\bGRANT\b",
    r"\bREVOKE\b",
    r"\bMERGE\b",
    r"\bREPLACE\b",
    r"\bEXEC\b",
    r"\bEXECUTE\b",
    r"\bCALL\b",
    r"\bLOAD\s+DATA\b",
    r";\s*\w+",  # 分号后接关键字（防止多语句注入）
]


@dataclass
class DBConnectionConfig:
    """数据库连接配置"""
    db_type: str
    host: str
    port: int
    database: str
    user: str
    password: str
    connect_args: Optional[Dict[str, Any]] = None


class SafeDatabaseReader:
    """
    安全数据库读取器

    提供从多种关系型数据库安全读取数据并转为 LlamaIndex Document 的能力。
    """

    DEFAULT_MAX_ROWS = 10_000
    DEFAULT_PAGE_SIZE = 500

    def __init__(self, config: DBConnectionConfig):
        self.config = config
        self._dialect: Optional[str] = None
        self._engine: Optional[Engine] = None

    # ---------- 内部工具方法 ----------

    def _resolve_dialect(self) -> str:
        """解析数据库方言，并检测驱动是否已安装"""
        db_type = self.config.db_type.lower()
        dialect = DIALECT_MAP.get(db_type)
        if not dialect:
            raise ValueError(
                f"不支持的数据库类型: {db_type}。"
                f"支持: {list(DIALECT_MAP.keys())}"
            )

        # SQLite 是内置驱动，无需检测
        if db_type == "sqlite":
            self._dialect = dialect
            return dialect

        # 运行时检测驱动
        import_name = DRIVER_IMPORT_MAP.get(dialect)
        if import_name:
            try:
                __import__(import_name)
            except ImportError:
                pkg = DRIVER_PACKAGE_MAP.get(db_type, "")
                raise RuntimeError(
                    f"缺少 {db_type} 数据库驱动 '{import_name}'，"
                    f"请安装: pip install {pkg}"
                )

        self._dialect = dialect
        return dialect

    def _build_connection_url(self, dialect: str) -> str:
        """构建 SQLAlchemy 连接 URL"""
        if self.config.db_type.lower() == "sqlite":
            return f"sqlite:///{self.config.database}"

        # 密码中可能包含特殊字符，需要转义
        from urllib.parse import quote_plus
        password = quote_plus(str(self.config.password))

        return (
            f"{dialect}://{self.config.user}:{password}"
            f"@{self.config.host}:{self.config.port}/{self.config.database}"
        )

    def _get_engine(self) -> Engine:
        """获取或创建 SQLAlchemy Engine（懒加载）"""
        if self._engine is not None:
            return self._engine

        dialect = self._resolve_dialect()
        url = self._build_connection_url(dialect)
        connect_args = self.config.connect_args or {}

        self._engine = create_engine(
            url,
            connect_args=connect_args,
            pool_pre_ping=True,
            pool_recycle=3600,
        )
        return self._engine

    @classmethod
    def validate_readonly(cls, query: str) -> None:
        """
        校验 SQL 是否为只读查询。

        通过正则黑名单检测写操作关键字。注意：这不是绝对安全的 SQL 解析，
        生产环境强烈建议配合数据库层面的只读账号使用。
        """
        # 移除注释，避免被绕过
        cleaned = query
        # 移除 -- 行注释
        cleaned = re.sub(r"--.*$", "", cleaned, flags=re.MULTILINE)
        # 移除 /* */ 块注释
        cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL)

        upper_cleaned = cleaned.upper()

        for pattern in WRITE_KEYWORD_PATTERNS:
            match = re.search(pattern, upper_cleaned, re.IGNORECASE)
            if match:
                matched_text = match.group(0)
                raise ValueError(
                    f"SQL 安全校验失败：检测到非只读关键字 '{matched_text}'。"
                    f"仅允许 SELECT 查询。"
                )

        # 额外校验：必须以 SELECT 开头
        stripped = upper_cleaned.strip()
        if not stripped.startswith("SELECT"):
            raise ValueError(
                "SQL 安全校验失败：查询必须以 SELECT 开头。"
            )

    def estimate_row_count(self, query: str) -> int:
        """
        预估查询结果行数。

        通过 SELECT COUNT(*) FROM (用户SQL) AS t 来估算。
        """
        self.validate_readonly(query)
        engine = self._get_engine()
        count_sql = f"SELECT COUNT(*) FROM ({query}) AS t"

        try:
            with engine.connect() as conn:
                result = conn.execute(text(count_sql))
                count = result.scalar()
                logger.info(f"超长检测: 预估行数 {count}")
                return count or 0
        except Exception as e:
            logger.error(f"超长检测失败: {str(e)}")
            raise RuntimeError(f"无法预估查询结果行数: {str(e)}") from e

    def load_data(
        self,
        query: str,
        text_column: str,
        metadata_columns: Optional[List[str]] = None,
        max_rows: int = DEFAULT_MAX_ROWS,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> List[Document]:
        """
        安全读取数据并转为 LlamaIndex Document 列表。

        Args:
            query: 用户提供的只读 SQL
            text_column: 哪一列作为 Document.text
            metadata_columns: 哪些列作为 metadata，None 表示除 text_column 外全部
            max_rows: 单个查询最大允许行数
            page_size: 流式分页大小

        Returns:
            List[Document]
        """
        # 1. 只读校验
        self.validate_readonly(query)

        # 2. 超长检测
        total_rows = self.estimate_row_count(query)
        if total_rows > max_rows:
            raise ValueError(
                f"查询结果行数 ({total_rows}) 超过最大限制 ({max_rows})，"
                f"请优化 SQL 添加更严格的 WHERE 条件以缩小数据范围。"
            )

        # 3. 流式读取
        logger.info(
            f"开始读取数据: 预估 {total_rows} 行, "
            f"分页大小 {page_size}, text_column='{text_column}'"
        )
        documents = self._stream_read(query, text_column, metadata_columns, page_size)
        logger.info(f"数据读取完成: 共 {len(documents)} 条 Document")
        return documents

    def _stream_read(
        self,
        query: str,
        text_column: str,
        metadata_columns: Optional[List[str]],
        page_size: int,
    ) -> List[Document]:
        """
        使用 SQLAlchemy 流式游标分批读取数据。

        通过 execution_options(yield_per=page_size) 实现服务端游标，
        避免一次性加载全部结果到内存。
        """
        engine = self._get_engine()
        documents: List[Document] = []

        try:
            with engine.connect() as conn:
                result = conn.execution_options(
                    yield_per=page_size,
                    stream_results=True,
                ).execute(text(query))

                for row in result.mappings():
                    # 提取 text
                    text_value = row.get(text_column)
                    if text_value is None:
                        continue

                    # 提取 metadata
                    meta: Dict[str, Any] = {}
                    if metadata_columns is not None:
                        # 用户显式指定了 metadata 列
                        for col in metadata_columns:
                            meta[col] = row.get(col)
                    else:
                        # 默认：除 text_column 外全部作为 metadata
                        for key, value in row.items():
                            if key != text_column:
                                meta[key] = value

                    documents.append(
                        Document(text=str(text_value), metadata=meta)
                    )
        except Exception as e:
            logger.error(f"数据库读取失败: {str(e)}")
            raise RuntimeError(f"数据库读取失败: {str(e)}") from e
        finally:
            # 确保 engine 被释放（连接池回收）
            if self._engine is not None:
                self._engine.dispose()
                self._engine = None

        return documents


# ============ 便捷函数 ============


def check_driver_installed(db_type: str) -> bool:
    """检查指定数据库的驱动是否已安装"""
    dialect = DIALECT_MAP.get(db_type.lower())
    if not dialect:
        return False
    import_name = DRIVER_IMPORT_MAP.get(dialect)
    if not import_name or import_name == "sqlite3":
        return True
    try:
        __import__(import_name)
        return True
    except ImportError:
        return False


def get_driver_install_hint(db_type: str) -> Optional[str]:
    """获取驱动安装提示"""
    pkg = DRIVER_PACKAGE_MAP.get(db_type.lower())
    if pkg:
        return f"pip install {pkg}"
    return None
