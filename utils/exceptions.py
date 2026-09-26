"""
自定义异常类
"""
from typing import Any


class EmbeddingServiceError(Exception):
    """基础异常类"""

    def __init__(self, message: str, code: int = 500, data: Any = None):
        self.message = message
        self.code = code
        self.data = data
        super().__init__(self.message)
