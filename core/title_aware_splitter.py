"""
标题感知切分器 - 在 chunk 切分时将标题路径注入到 metadata
"""
from typing import List, Dict, Any, Optional

from llama_index.core.node_parser import SentenceSplitter
from llama_index.core import Document
from llama_index.core.schema import TextNode

from core.document_structure_parser import DocumentStructureParser, HeadingInfo
from utils.logger import get_logger
import os

logger = get_logger()


class TitleAwareSplitter:
    """
    标题感知切分器

    在 LlamaIndex SentenceSplitter 的基础上，将文档的标题层级信息
    注入到每个 chunk 的 metadata 中。
    """

    def __init__(self, chunk_size: int = 300, chunk_overlap: int = 100):
        """
        Args:
            chunk_size: 每个 chunk 的最大字符数
            chunk_overlap: chunk 之间的重叠字符数
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._splitter = SentenceSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap
        )
        self._parser = DocumentStructureParser()

    def split_documents(
        self,
        documents: List[Document],
        file_path_map: Optional[Dict[str, str]] = None
    ) -> List[Document]:
        """
        将文档切分为带标题信息的 chunks

        Args:
            documents: LlamaIndex Document 列表
            file_path_map: {file_name: file_path} 映射，用于定位 DOCX/MD 等文件以提取标题

        Returns:
            切分后的 Document/TextNode 列表，每个 chunk 的 metadata 中已注入标题信息
        """
        all_chunks = []

        for doc in documents:
            file_name = doc.metadata.get("file_name", "")
            file_path = file_path_map.get(file_name) if file_path_map else None

            # 提取文档结构（标题层级）
            structured_doc = self._extract_document_structure(doc, file_path)

            # 使用 SentenceSplitter 切分
            chunks = self._splitter.get_nodes_from_documents([doc])

            # 为每个 chunk 注入标题信息
            for chunk in chunks:
                heading_info = self._parser.get_heading_path_for_range(
                    structured_doc.headings,
                    chunk.start_char_idx or 0,
                    chunk.end_char_idx or 0
                )

                # 注入到 metadata
                chunk.metadata["heading_path"] = heading_info["heading_path"]
                chunk.metadata["nearest_heading"] = heading_info["nearest_heading"]
                chunk.metadata["heading_level"] = heading_info["heading_level"]

            all_chunks.extend(chunks)

        logger.info(
            f"标题感知切分完成: {len(documents)} 个文档 -> {len(all_chunks)} 个 chunks, "
            f"其中 {sum(1 for c in all_chunks if c.metadata.get('heading_path'))} 个 chunk 携带标题信息"
        )
        return all_chunks

    def _extract_document_structure(
        self,
        doc: Document,
        file_path: Optional[str] = None
    ) -> Any:
        """
        提取文档的标题结构

        Args:
            doc: LlamaIndex Document
            file_path: 原始文件路径（如果可用）

        Returns:
            StructuredDocument
        """
        # 检查是否是本地文件路径（URL 不需要处理，直接回退到纯文本）
        is_local_path = (
            file_path
            and not file_path.startswith(('http://', 'https://', '/api/', '/static/'))
            and os.path.isfile(file_path)
        )

        if not is_local_path:
            # 没有本地文件，回退到纯文本解析
            return self._parser._parse_as_plain_text_from_text(doc.text)

        ext = os.path.splitext(file_path)[1].lower()

        try:
            if ext in ('.docx',):
                return self._parser.parse_from_docx(file_path)
            elif ext in ('.md', '.markdown'):
                return self._parser.parse_from_markdown(file_path)
            elif ext in ('.html', '.htm'):
                return self._parser.parse_from_html(file_path)
            else:
                # 其他格式回退到纯文本解析
                return self._parser._parse_as_plain_text(file_path)
        except Exception as e:
            logger.warning(f"文件结构提取失败 ({file_path}): {e}")
            return self._parser._parse_as_plain_text_from_text(doc.text)

    def get_nodes_from_documents(
        self,
        documents: List[Document],
        file_path_map: Optional[Dict[str, str]] = None
    ) -> List[TextNode]:
        """
        兼容 LlamaIndex SentenceSplitter 接口的别名方法

        Args:
            documents: LlamaIndex Document 列表
            file_path_map: {file_name: file_path} 映射

        Returns:
            TextNode 列表
        """
        return self.split_documents(documents, file_path_map)


# 让 DocumentStructureParser 支持从纯文本直接解析的方法
def _parse_as_plain_text_from_text(self, text: str):
    """从纯文本字符串提取标题（不需要文件路径）"""
    headings = []
    lines = text.split('\n')
    char_offset = 0

    for line in lines:
        stripped = line.strip()
        if not stripped:
            char_offset += len(line) + 1
            continue

        matched = self._match_heading(stripped)
        if matched:
            level, heading_text = matched
            headings.append(HeadingInfo(
                level=level,
                text=heading_text,
                char_start=char_offset,
                char_end=char_offset + len(line)
            ))

        char_offset += len(line) + 1

    from core.document_structure_parser import StructuredDocument
    return StructuredDocument(text=text, headings=headings)


# 动态添加方法到 DocumentStructureParser
DocumentStructureParser._parse_as_plain_text_from_text = _parse_as_plain_text_from_text
