"""
音频转文本工具函数
参考 get_txt.py 的实现模式
"""
import os
import requests
from utils.logger import get_logger
from configs.config import settings

logger = get_logger()


def get_audio_text(file_path: str) -> str:
    """
    调用音频转文本服务，返回转录文本

    Args:
        file_path: 音频文件的绝对路径

    Returns:
        转录后的文本内容

    Raises:
        RuntimeError: 调用失败时抛出
    """
    # 1. 检查文件是否存在
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"音频文件不存在: {file_path}")

    # 2. 准备请求
    v2t_url = settings.v2t_url

    try:
        # 3. 发送音频文件到转文本服务
        with open(file_path, 'rb') as f:
            files = {"file": (os.path.basename(file_path), f, "audio/mpeg")}
            response = requests.post(
                url=v2t_url,
                files=files,
                timeout=settings.v2t_timeout
            )

        # 4. 检查响应状态
        if response.status_code != 200:
            logger.error(f"音频转文本服务返回异常: {response.text}")
            raise RuntimeError("音频转文本失败")

        # 5. 解析响应
        result = response.json()
        if result.get("status") != 200:
            logger.error(f"音频转文本服务返回错误状态: {result}")
            raise RuntimeError(f"音频转文本失败: {result.get('response', '未知错误')}")

        # 6. 提取文本
        text = result.get("response", "")
        if not text:
            logger.warning("音频转文本未识别到任何内容")

        logger.info(f"音频转文本成功，文本长度: {len(text)}")
        return text

    except requests.exceptions.Timeout:
        logger.error(f"音频转文本超时: {file_path}")
        raise RuntimeError("音频转文本超时")
    except requests.exceptions.RequestException as e:
        logger.error(f"音频转文本请求失败: {str(e)}")
        raise RuntimeError(f"音频转文本请求失败: {str(e)}")
    except Exception as e:
        logger.error(f"音频转文本处理失败: {str(e)}")
        raise RuntimeError(f"音频转文本处理失败: {str(e)}")