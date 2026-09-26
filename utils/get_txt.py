import mimetypes
import os

import requests
import json
from utils.logger import get_logger
from utils.response import *
from configs.config import *

logger = get_logger()

"""
用于实现1.从图片/pdf中获取txt
"""


def get_new_file_path(file_path: str) -> str:
    """
    file_path: 相对路径，如 downloads/xxx.jpg
    返回: 生成的 .txt 文件绝对路径
    """
    # 1. 拼绝对路径（处理 Windows 和 Linux 路径差异）
    # 统一使用正斜杠，并相对于当前工作目录
    normalized_path = file_path.replace("\\", "/")
    abs_path = os.path.abspath(normalized_path)
    if not os.path.isfile(abs_path):
        raise FileNotFoundError(f"图片不存在: {abs_path}")

    # 2. 下游 OCR 地址
    request_ocr_url = OCR_URL

    # 3. 发文件
    mime, _ = mimetypes.guess_type(abs_path)
    mime = mime or "image/jpeg"
    with open(abs_path, "rb") as f:
        resp = requests.post(
            url=request_ocr_url,
            files={"file": (os.path.basename(abs_path), f, mime)},
            timeout=30
        )

    # 4. 判断 OCR 服务返回
    if resp.status_code != 200:
        logger.error(f"OCR 服务返回异常: {resp.text}")
        raise RuntimeError("图片解析失败")

    # 5. 取文本
    txt = resp.json().get("data", "")
    if not txt:                       # 视业务可放宽
        logger.warning("OCR 未识别到任何文本")

    # 6. 写 .txt 文件（绝对路径，防止写到奇怪位置）
    file_suffix = abs_path.split(".")[-1]
    txt_file_path = abs_path.replace(f".{file_suffix}", f"-{file_suffix}.txt")

    with open(txt_file_path, "w", encoding="utf-8") as f:
        f.write(txt)

    logger.info(f"提取后的文本已写入 {txt_file_path}")
    return txt_file_path



