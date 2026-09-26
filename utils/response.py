"""
统一响应格式
"""
from typing import Any, Optional
from utils.exceptions import EmbeddingServiceError


def success_response(data: Any = None, msg: str = "success", code: int = 200) -> dict:
    """
    成功响应

    Args:
        data: 响应数据
        msg: 响应消息
        code: 状态码

    Returns:
        响应字典
    """
    return {
        "code": code,
        "msg": msg,
        "data": data
    }


def error_response(data: Any = None, msg: str = "error", code: int = 500) -> dict:
    """
    错误响应

    Args:
        data: 错误数据
        msg: 错误消息
        code: 状态码

    Returns:
        响应字典
    """
    return {
        "code": code,
        "msg": msg,
        "data": data
    }


def handle_exception(e: Exception) -> dict:
    """
    统一异常处理

    Args:
        e: 异常对象

    Returns:
        错误响应字典
    """
    from utils.logger import get_logger
    logger = get_logger()

    # 如果是自定义异常
    if isinstance(e, EmbeddingServiceError):
        logger.warning(f"业务异常: {e.message}")
        return error_response(data=e.data, msg=e.message, code=e.code)

    # 其他异常
    logger.error(f"系统异常: {str(e)}", exc_info=True)
    return error_response(data=str(e), msg="系统异常", code=500)
