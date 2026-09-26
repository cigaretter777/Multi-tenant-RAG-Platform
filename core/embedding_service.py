"""
Embedding 服务模块 - 管理嵌入模型的初始化和配置
"""
from llama_index.core import Settings
from llama_index.embeddings.openai import OpenAIEmbedding

from configs.config import settings
from utils.logger import get_logger

logger = get_logger()


class EmbeddingService:
    """
    Embedding 服务类 - 单例模式
    管理嵌入模型的全局配置
    """

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if EmbeddingService._initialized:
            return

        self.model_name = settings.embedding_model_name
        self.api_base = settings.embedding_server
        self.api_key = settings.embedding_key
        self.chunk_size = settings.chunk_size
        self.chunk_overlap = settings.chunk_overlap

        self._initialize()

        EmbeddingService._initialized = True

    def _initialize(self):
        """初始化 Embedding 模型和配置"""
        logger.info("========== 初始化 Embedding 服务 ==========")

        # 初始化嵌入模型
        logger.info(f"[DEBUG] 开始初始化 OpenAIEmbedding 模型...")
        logger.info(f"[DEBUG] 模型名称: {self.model_name}")
        logger.info(f"[DEBUG] API 地址: {self.api_base}")
        logger.info(f"[DEBUG] 批处理大小: {settings.embed_batch_size}")
        logger.info(f"[DEBUG] 超时时间: {settings.embed_timeout}s")

        try:
            self.embed_model = OpenAIEmbedding(
                model_name=self.model_name,
                api_base=self.api_base,
                api_key=self.api_key,
                embed_batch_size=settings.embed_batch_size,
                timeout=settings.embed_timeout
            )
            logger.info(f"[DEBUG] OpenAIEmbedding 模型创建成功")
        except Exception as e:
            logger.error(f"[DEBUG] OpenAIEmbedding 模型创建失败: {str(e)}")
            raise

        logger.info(f"Embedding 模型: {self.model_name}")
        logger.info(f"API 地址: {self.api_base}")
        logger.info(f"API key: {self.api_key,}")
        logger.info(f"批处理大小: {settings.embed_batch_size}")
        logger.info(f"超时时间: {settings.embed_timeout}s")

        # 配置全局 Settings
        logger.info(f"[DEBUG] 配置全局 Settings...")
        Settings.embed_model = self.embed_model
        Settings.chunk_size = self.chunk_size
        Settings.chunk_overlap = self.chunk_overlap
        logger.info(f"[DEBUG] 全局 Settings 配置完成")

        logger.info(f"分块大小: {self.chunk_size}")
        logger.info(f"分块重叠: {self.chunk_overlap}")

        logger.info("========== Embedding 服务初始化完成 ==========")

    @classmethod
    def get_instance(cls) -> "EmbeddingService":
        """获取服务实例（兼容原有代码）"""
        return cls()

    def get_model(self):
        """获取嵌入模型"""
        return self.embed_model


# ============ 向后兼容的函数 ============

def embedding_service():
    """
    初始化 embedding 服务（兼容旧代码）
    """
    EmbeddingService()
    logger.info("Embedding 服务已启动")
