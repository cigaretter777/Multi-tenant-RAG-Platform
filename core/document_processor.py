"""
文档处理模块 - 处理文档的加载、下载和解析
"""
import asyncio
import os
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import requests
from llama_index.core import Document
from llama_index.core import SimpleDirectoryReader

from configs.config import settings, GUARD_URL
from utils.logger import get_logger
from utils.get_txt import get_new_file_path

logger = get_logger()


@dataclass
class GuardedDocumentInfo:
    """防护后的文档信息"""
    document: Document
    original_text: str
    semantic_text: Optional[str] = None
    needs_confirmation: bool = False


class FileDownloader:
    """文件下载器"""

    def __init__(self, download_dir: Optional[str] = None):
        """
        初始化文件下载器

        Args:
            download_dir: 下载目录，默认从配置读取
        """
        self.download_dir = Path(download_dir or settings.download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def download_sync(self, url: str, filename: str) -> str:
        """
        下载文件到本地（同步版本，用于线程池）

        Args:
            url: 文件URL (相对路径)
            filename: 文件名

        Returns:
            本地文件路径

        Raises:
            RuntimeError: 下载失败时抛出
        """
        full_url = f"{settings.domain_name}{url}"
        local_path = self.download_dir / filename

        # 如果文件已存在，直接返回
        if local_path.exists():
            logger.info(f"文件已存在: {local_path}")
            return str(local_path)

        try:
            logger.info(f"开始下载: {full_url}")
            response = requests.get(full_url, timeout=60)
            response.raise_for_status()

            # 写入文件
            with open(local_path, 'wb') as f:
                f.write(response.content)

            logger.info(f"下载完成: {local_path}")
            return str(local_path)

        except requests.exceptions.RequestException as e:
            logger.error(f"下载失败: {url} - {str(e)}")
            raise RuntimeError(f"下载文件失败: {url}") from e
        except IOError as e:
            logger.error(f"文件写入失败: {local_path} - {str(e)}")
            raise RuntimeError(f"无法保存文件: {local_path}") from e

    async def download(self, url: str, filename: str) -> str:
        """
        下载文件到本地（异步版本）

        Args:
            url: 文件URL (相对路径)
            filename: 文件名

        Returns:
            本地文件路径

        Raises:
            RuntimeError: 下载失败时抛出
        """
        # 异步版本调用同步版本
        return self.download_sync(url, filename)

    def cleanup(self, filepath: str):
        """
        清理下载的文件

        Args:
            filepath: 文件路径
        """
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
                logger.info(f"清理文件: {filepath}")
        except Exception as e:
            logger.warning(f"清理文件失败: {filepath} - {str(e)}")


class DocumentProcessor:
    """文档处理器"""

    # 支持的图片格式
    IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}

    # 支持的音频格式
    AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg", ".wma"}

    def __init__(self, downloader: Optional[FileDownloader] = None):
        """
        初始化文档处理器

        Args:
            downloader: 文件下载器，如果为 None 则创建新实例
        """
        self.downloader = downloader or FileDownloader()

    def _is_image_file(self, filepath: str) -> bool:
        """判断是否为图片文件"""
        return Path(filepath).suffix.lower() in self.IMAGE_EXTENSIONS

    def _is_audio_file(self, filepath: str) -> bool:
        """判断是否为音频文件"""
        return Path(filepath).suffix.lower() in self.AUDIO_EXTENSIONS

    def _load_image_file(self, filepath: str, file_name: str, enable_vl_model: bool = False) -> List[Document]:
        """
        加载图片文件

        Args:
            filepath: 文件路径
            file_name: 文件名
            enable_vl_model: 是否启用VL模型处理图片

        Returns:
            文档列表
        """
        if enable_vl_model:
            # 使用 VL 模型生成图片描述
            try:
                description = self._generate_image_description(filepath, file_name)
                # 创建包含详细描述的文档，适合向量化
                doc = Document(text=description)
                doc.metadata.update({
                    "file_type": "image",
                    "source_format": Path(filepath).suffix.lower(),
                    "processing_method": "vl_model"
                })
                logger.info(f"图片文件(VL模型)解析完成: {file_name}")
                return [doc]
            except Exception as e:
                logger.warning(f"VL模型处理失败，回退到OCR: {file_name} - {str(e)}")
                # 回退到 OCR 处理
                return self._load_image_with_ocr(filepath, file_name)
        else:
            # 使用 OCR 处理图片
            return self._load_image_with_ocr(filepath, file_name)

    def _load_image_with_ocr(self, filepath: str, file_name: str) -> List[Document]:
        """
        使用OCR加载图片文件

        Args:
            filepath: 文件路径
            file_name: 文件名

        Returns:
            文档列表
        """
        txt_path = get_new_file_path(filepath)
        try:
            documents = SimpleDirectoryReader(input_files=[txt_path]).load_data()
            logger.info(f"图片文件(OCR)解析完成: {file_name}")
            return documents
        finally:
            # 清理临时 txt 文件
            if os.path.exists(txt_path):
                os.remove(txt_path)
                logger.info(f"清理临时文件: {txt_path}")

    def _generate_image_description(self, filepath: str, file_name: str) -> str:
        """
        使用VL模型生成图片描述（兼容 OpenAI Vision API 格式）

        Args:
            filepath: 图片文件路径
            file_name: 文件名

        Returns:
            图片描述文本（适合向量化的详细描述）
        """
        import base64

        try:
            # 读取图片并编码为 base64
            with open(filepath, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')

            # 使用配置的 prompt（支持从 .env 自定义）
            prompt = settings.vl_model_prompt
            logger.info(f"[DEBUG] Using VL model prompt: {prompt[:50]}...")

            # 调用 VL 模型服务（使用 OpenAI 格式）
            payload = {
                "model": settings.vl_model_name,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_data}"
                                }
                            }
                        ]
                    }
                ],
                "max_tokens": 500
            }

            # 构造请求头
            headers = {
                "Content-Type": "application/json"
            }

            # 如果配置了 API Key，添加 Authorization header
            logger.info(f"[DEBUG] VL model key configured: {bool(settings.vl_model_key)}")
            logger.info(f"[DEBUG] VL model key length: {len(settings.vl_model_key) if settings.vl_model_key else 0}")
            if settings.vl_model_key:
                headers["Authorization"] = f"Bearer {settings.vl_model_key}"
                logger.info(f"[DEBUG] Authorization header added")
            else:
                logger.warning(f"[DEBUG] No VL model key configured, request will be sent without Authorization")

            # 确保 URL 包含完整路径
            vl_url = settings.vl_model_url
            if vl_url.endswith('/v1'):
                vl_url = f"{vl_url}/chat/completions"
            elif not vl_url.endswith('/chat/completions'):
                # 如果不是以 /chat/completions 结尾，追加它
                vl_url = vl_url.rstrip('/') + '/v1/chat/completions'

            logger.info(f"[DEBUG] VL model request URL: {vl_url}")

            response = requests.post(
                vl_url,
                json=payload,
                headers=headers,
                timeout=settings.vl_model_timeout
            )

            if response.status_code == 200:
                result = response.json()
                # 兼容 OpenAI 格式的响应
                description = ""
                if "choices" in result and len(result["choices"]) > 0:
                    description = result["choices"][0].get("message", {}).get("content", "")
                # 兼容其他格式
                if not description:
                    description = result.get("description", result.get("text", ""))

                if description:
                    logger.info(f"VL模型生成图片描述成功: {file_name}")
                    return description
                else:
                    logger.warning(f"VL模型返回空描述: {file_name}")
                    raise ValueError("VL模型返回空描述")
            else:
                logger.error(f"VL模型服务调用失败: {file_name} - {response.text}")
                raise RuntimeError(f"VL模型服务调用失败: {response.status_code}")

        except requests.exceptions.Timeout:
            logger.error(f"VL模型请求超时: {file_name}")
            raise RuntimeError("VL模型请求超时")
        except Exception as e:
            logger.error(f"VL模型处理图片失败: {file_name} - {str(e)}")
            raise

    def _load_audio_file(self, filepath: str, file_name: str) -> List[Document]:
        """
        加载音频文件，转换为文本后处理

        Args:
            filepath: 音频文件路径
            file_name: 文件名

        Returns:
            文档列表
        """
        from utils.audio_transcribe import get_audio_text

        try:
            # 1. 调用音频转文本服务
            text = get_audio_text(filepath)

            # 2. 创建文档对象
            doc = Document(text=text)

            # 3. 添加音频特有的元数据
            doc.metadata.update({
                "file_type": "audio",
                "source_format": Path(filepath).suffix.lower()
            })

            logger.info(f"音频文件解析完成: {file_name}")
            return [doc]

        except Exception as e:
            logger.error(f"音频文件解析失败: {file_name} - {str(e)}")
            raise

    def _load_regular_file(self, filepath: str, file_name: str) -> List[Document]:
        """
        加载普通文件

        Args:
            filepath: 文件路径
            file_name: 文件名

        Returns:
            文档列表
        """
        # 处理 Excel 文件
        if filepath.endswith((".xlsx", ".xls")):
            return self._load_excel_file(filepath, file_name)

        documents = SimpleDirectoryReader(input_files=[filepath]).load_data()
        logger.info(f"文件解析完成: {file_name}")
        return documents

    def _load_excel_file(self, filepath: str, file_name: str) -> List[Document]:
        """
        加载 Excel 文件

        Args:
            filepath: 文件路径
            file_name: 文件名

        Returns:
            文档列表
        """
        import pandas as pd

        try:
            # 读取所有 sheet
            excel_file = pd.ExcelFile(filepath)
            all_text = []

            for sheet_name in excel_file.sheet_names:
                df = pd.read_excel(filepath, sheet_name=sheet_name)
                # 将 DataFrame 转换为文本
                sheet_text = f"Sheet: {sheet_name}\n{df.to_string()}"
                all_text.append(sheet_text)
                logger.info(f"  Sheet '{sheet_name}': {len(df)} 行")

            # 创建文档
            combined_text = "\n\n".join(all_text)
            doc = Document(text=combined_text)
            logger.info(f"Excel 文件解析完成: {file_name} ({len(excel_file.sheet_names)} 个 sheet)")
            return [doc]

        except Exception as e:
            logger.error(f"Excel 文件解析失败: {file_name} - {str(e)}")
            raise

    def process_file(
        self,
        file_url: str,
        file_name: str,
        cleanup: bool = True,
        enable_vl_model: bool = False
    ) -> List[Document]:
        """
        处理单个文件

        Args:
            file_url: 文件URL (相对路径)
            file_name: 文件名
            cleanup: 是否清理下载的文件
            enable_vl_model: 是否启用VL模型处理图片

        Returns:
            文档列表

        Raises:
            RuntimeError: 处理失败时抛出
        """
        local_path = None

        try:
            # 下载文件（使用同步版本，避免在线程池中的 asyncio.run 问题）
            local_path = self.downloader.download_sync(file_url, file_name)

            # 根据文件类型加载
            if self._is_image_file(local_path):
                documents = self._load_image_file(local_path, file_name, enable_vl_model)
            elif self._is_audio_file(local_path):
                documents = self._load_audio_file(local_path, file_name)
            else:
                documents = self._load_regular_file(local_path, file_name)

            # 更新元数据
            for doc in documents:
                doc.metadata.update({
                    "file_name": file_name,
                    "file_path": file_url
                })

            return documents

        except Exception as e:
            logger.error(f"处理文件失败: {file_name} - {str(e)}")
            raise RuntimeError(f"处理文件失败: {file_name}") from e
        finally:
            # 清理下载的文件
            if cleanup and local_path and settings.cleanup_downloads:
                self.downloader.cleanup(local_path)

    def process_files_batch(
        self,
        file_list: List[Dict[str, str]],
        max_workers: Optional[int] = None,
        is_guard: bool = False,
        enable_vl_model: bool = False
    ) -> List[GuardedDocumentInfo]:
        """
        批量处理文件（多线程）

        Args:
            file_list: 文件信息列表 [{"path": "...", "name": "..."}, ...]
            max_workers: 最大工作线程数，默认从配置读取
            is_guard: 是否开启防护模式
            enable_vl_model: 是否启用VL模型处理图片

        Returns:
            GuardedDocumentInfo 列表

        Raises:
            RuntimeError: 处理失败时抛出
        """
        max_workers = max_workers or settings.max_workers
        all_guarded_info: List[GuardedDocumentInfo] = []

        logger.info(f"========== 开始批量处理文件 ==========")
        logger.info(f"文件数量: {len(file_list)}")
        logger.info(f"线程数: {max_workers}")
        logger.info(f"防护模式: {is_guard}")
        logger.info(f"VL模型: {enable_vl_model}")

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务
            futures = {
                executor.submit(
                    self.process_file,
                    file_info["path"],
                    file_info["name"],
                    True,  # cleanup
                    enable_vl_model
                ): file_info for file_info in file_list
            }

            # 收集结果
            for future in as_completed(futures):
                file_info = futures[future]
                try:
                    documents = future.result()
                    if is_guard:
                        # 防护模式：对每个文档调用防护服务
                        for doc in documents:
                            original_text = doc.text
                            guard_res = requests.post(
                                GUARD_URL,
                                json={"data": original_text, "enable_semantic_sanitization": True}
                            )
                            if guard_res.status_code == 200:
                                response_data = guard_res.json()["data"]
                                semantic_text = response_data.get("semantic_cleaned_data", "")
                                basic_cleaned = response_data.get("basic_cleaned_data", "")

                                # 初始使用原始文本作为document_text，等待用户确认
                                doc_with_original = Document(text=original_text, metadata=doc.metadata)

                                guarded_info = GuardedDocumentInfo(
                                    document=doc_with_original,
                                    original_text=original_text,
                                    semantic_text=semantic_text if semantic_text else None,
                                    needs_confirmation=bool(semantic_text)
                                )
                                all_guarded_info.append(guarded_info)

                                if semantic_text:
                                    logger.info(f"文件 {file_info['name']} 需要用户确认（有语义清洗结果）")
                                else:
                                    logger.info(f"文件 {file_info['name']} 无需确认（无语义清洗结果）")
                            else:
                                logger.error(f"LLM08 预处理失败: {file_info['name']} - {guard_res.text}")
                                # 失败时使用原始文本
                                all_guarded_info.append(GuardedDocumentInfo(
                                    document=doc,
                                    original_text=doc.text,
                                    semantic_text=None,
                                    needs_confirmation=False
                                ))
                    else:
                        # 非防护模式：直接使用原始文本
                        for doc in documents:
                            all_guarded_info.append(GuardedDocumentInfo(
                                document=doc,
                                original_text=doc.text,
                                semantic_text=None,
                                needs_confirmation=False
                            ))

                    logger.info(f"成功处理: {file_info['name']} -> {len(documents)} 个文档片段")
                except Exception as e:
                    logger.error(f"处理失败: {file_info['name']} - {str(e)}")
                    raise

        logger.info(f"========== 批量处理完成 ==========")
        logger.info(f"总计生成 {len(all_guarded_info)} 个文档片段")
        needs_confirm_count = sum(1 for info in all_guarded_info if info.needs_confirmation)
        logger.info(f"需要用户确认的文档数: {needs_confirm_count}")

        return all_guarded_info


# ============ 向后兼容的函数 ============

async def download_file(url: str, local_path: str) -> str:
    """
    异步下载文件（兼容旧代码）

    Args:
        url: 文件URL
        local_path: 本地保存路径

    Returns:
        本地文件路径
    """
    downloader = FileDownloader()
    filename = os.path.basename(local_path)
    return await downloader.download(url, filename)
