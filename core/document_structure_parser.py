"""
文档结构解析器 - 从不同格式的文档中提取标题层级信息
"""
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

from utils.logger import get_logger

logger = get_logger()


@dataclass
class HeadingInfo:
    """标题信息"""
    level: int           # 标题层级 1-6
    text: str            # 标题文本
    char_start: int      # 在原文中的起始字符位置
    char_end: int        # 在原文中的结束字符位置


@dataclass
class StructuredDocument:
    """结构化文档"""
    text: str                            # 完整文本
    headings: List[HeadingInfo] = field(default_factory=list)  # 提取的标题列表
    metadata: Dict[str, Any] = field(default_factory=dict)     # 原有元数据


class DocumentStructureParser:
    """文档结构解析器 - 从不同格式文档中提取标题层级"""

    # 中文编号模式：第X章、一、（一）、1、1.1、1.1.1 等
    CHINESE_HEADING_PATTERNS = [
        # 第X章 / 第X节
        (r'^第[一二三四五六七八九十百千万\d]+[章节篇部卷回]\s*(.+)$', 1),
        # 一、二、三、...
        (r'^[一二三四五六七八九十百千万]+\s*[、.]\s*(.+)$', 2),
        # （一）（二）...
        (r'^[（(][一二三四五六七八九十百千万]+[）)]\s*(.+)$', 3),
        # 1.1.1 格式（数字层级）
        (r'^(\d+(?:\.\d+){0,3})[\s.、]*(.+)$', None),  # level 由点数决定
        # 1、2、3、...
        (r'^\d+\s*[、.]\s*(.+)$', 3),
    ]

    def parse_from_docx(self, filepath: str) -> StructuredDocument:
        """
        从 DOCX 文件中提取标题层级

        Args:
            filepath: DOCX 文件路径

        Returns:
            StructuredDocument
        """
        try:
            from docx import Document as DocxDocument

            doc = DocxDocument(filepath)
            full_text_parts = []
            headings = []
            char_offset = 0

            for para in doc.paragraphs:
                text = para.text
                full_text_parts.append(text)

                # 检查是否是标题样式
                style_name = para.style.name.lower() if para.style else ''
                if style_name.startswith('heading'):
                    # 从样式名提取层级: Heading 1 -> level 1
                    level_match = re.search(r'heading\s*(\d+)', style_name, re.IGNORECASE)
                    if level_match:
                        level = int(level_match.group(1))
                        headings.append(HeadingInfo(
                            level=level,
                            text=text,
                            char_start=char_offset,
                            char_end=char_offset + len(text)
                        ))

                char_offset += len(text) + 1  # +1 for newline

            full_text = '\n'.join(full_text_parts)
            logger.info(f"DOCX 解析完成: 提取到 {len(headings)} 个标题")
            return StructuredDocument(text=full_text, headings=headings)

        except ImportError:
            logger.warning("python-docx 未安装，回退到纯文本解析")
            return self._parse_as_plain_text(filepath)
        except Exception as e:
            logger.error(f"DOCX 标题提取失败: {e}")
            return self._parse_as_plain_text(filepath)

    def parse_from_markdown(self, filepath: str) -> StructuredDocument:
        """
        从 Markdown 文件中提取标题层级

        Args:
            filepath: MD 文件路径

        Returns:
            StructuredDocument
        """
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()

            headings = []
            # 匹配 # ~ ###### 标题
            for match in re.finditer(r'^(#{1,6})\s+(.+)$', content, re.MULTILINE):
                level = len(match.group(1))
                text = match.group(2).strip()
                headings.append(HeadingInfo(
                    level=level,
                    text=text,
                    char_start=match.start(),
                    char_end=match.end()
                ))

            logger.info(f"Markdown 解析完成: 提取到 {len(headings)} 个标题")
            return StructuredDocument(text=content, headings=headings)

        except Exception as e:
            logger.error(f"Markdown 标题提取失败: {e}")
            return self._parse_as_plain_text(filepath)

    def parse_from_html(self, filepath: str) -> StructuredDocument:
        """
        从 HTML 文件中提取标题层级

        Args:
            filepath: HTML 文件路径

        Returns:
            StructuredDocument
        """
        try:
            from bs4 import BeautifulSoup

            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()

            soup = BeautifulSoup(content, 'html.parser')

            # 提取纯文本
            full_text = soup.get_text(separator='\n', strip=True)

            headings = []
            char_offset = 0

            # 遍历所有元素，同时重建文本和提取标题
            for element in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'div', 'span', 'br']):
                tag = element.name
                if tag and tag.startswith('h') and tag[1:].isdigit():
                    level = int(tag[1:])
                    text = element.get_text(strip=True)
                    if text:
                        # 在完整文本中定位标题位置
                        pos = full_text.find(text, char_offset)
                        if pos >= 0:
                            headings.append(HeadingInfo(
                                level=level,
                                text=text,
                                char_start=pos,
                                char_end=pos + len(text)
                            ))
                            char_offset = pos + len(text)

            logger.info(f"HTML 解析完成: 提取到 {len(headings)} 个标题")
            return StructuredDocument(text=full_text, headings=headings)

        except ImportError:
            logger.warning("beautifulsoup4 未安装，回退到纯文本解析")
            return self._parse_as_plain_text(filepath)
        except Exception as e:
            logger.error(f"HTML 标题提取失败: {e}")
            return self._parse_as_plain_text(filepath)

    def parse_from_pdf(self, filepath: str) -> StructuredDocument:
        """
        从 PDF 文件中提取标题层级（基于正则匹配中文编号模式）

        Args:
            filepath: PDF 文件路径

        Returns:
            StructuredDocument
        """
        # PDF 结构提取较复杂，先用正则匹配通用标题模式
        # 后续可扩展使用 pdfplumber 提取字体信息
        return self._parse_as_plain_text(filepath)

    def _parse_as_plain_text(self, filepath: str) -> StructuredDocument:
        """
        通用纯文本解析器 - 基于正则匹配编号模式

        适用于 TXT、PDF 等无法直接提取结构的格式

        Args:
            filepath: 文件路径

        Returns:
            StructuredDocument
        """
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
        except UnicodeDecodeError:
            with open(filepath, 'r', encoding='gbk', errors='ignore') as f:
                content = f.read()
        except Exception as e:
            logger.error(f"文件读取失败: {filepath} - {e}")
            return StructuredDocument(text="", headings=[])

        headings = []
        lines = content.split('\n')
        char_offset = 0

        for line in lines:
            stripped = line.strip()
            if not stripped:
                char_offset += len(line) + 1
                continue

            matched = self._match_heading(stripped)
            if matched:
                level, text = matched
                headings.append(HeadingInfo(
                    level=level,
                    text=text,
                    char_start=char_offset,
                    char_end=char_offset + len(line)
                ))

            char_offset += len(line) + 1

        logger.info(f"纯文本解析完成: 提取到 {len(headings)} 个标题")
        return StructuredDocument(text=content, headings=headings)

    def _match_heading(self, line: str) -> Optional[tuple]:
        """
        判断一行文本是否为标题，返回 (level, text) 或 None

        Args:
            line: 单行文本

        Returns:
            (level, text) 或 None
        """
        for pattern, default_level in self.CHINESE_HEADING_PATTERNS:
            match = re.match(pattern, line)
            if match:
                if default_level is not None:
                    return (default_level, match.group(0))
                else:
                    # 数字层级，由小数点数量决定 level
                    number_part = match.group(1)
                    dot_count = number_part.count('.')
                    level = min(dot_count + 1, 6)
                    text = match.group(0)
                    return (level, text)
        return None

    def get_heading_path_for_range(
        self,
        headings: List[HeadingInfo],
        char_start: int,
        char_end: int
    ) -> Dict[str, Any]:
        """
        根据字符范围反查对应的标题路径

        Args:
            headings: 文档的所有标题列表
            char_start: chunk 的起始字符位置
            char_end: chunk 的结束字符位置

        Returns:
            {
                "heading_path": "第一章 > 1.1 概述 > 1.1.2 背景",
                "nearest_heading": "1.1.2 背景",
                "heading_level": 3,
                "heading_context_levels": [
                    {"level": 1, "text": "第一章"},
                    {"level": 2, "text": "1.1 概述"},
                    {"level": 3, "text": "1.1.2 背景"},
                ]
            }
        """
        if not headings:
            return {
                "heading_path": "",
                "nearest_heading": "",
                "heading_level": 0,
                "heading_context_levels": []
            }

        # 找到 chunk 范围内最近的标题（在 chunk 起始位置之前或之内的最高层级标题）
        parent_headings = []
        nearest_heading = None

        for heading in headings:
            if heading.char_end <= char_start:
                # 标题在 chunk 之前，可能是父级标题
                # 移除比当前标题层级更深的已收集标题
                while parent_headings and parent_headings[-1].level >= heading.level:
                    parent_headings.pop()
                parent_headings.append(heading)
            elif heading.char_start >= char_start and heading.char_start <= char_end:
                # 标题在 chunk 范围内
                nearest_heading = heading
                break

        # 如果没有在 chunk 范围内找到标题，使用最近的父级标题
        if nearest_heading is None and parent_headings:
            nearest_heading = parent_headings[-1]
            parent_headings = parent_headings[:-1]  # 移除最近的那个，避免重复

        # 构建标题路径
        context_levels = parent_headings + ([nearest_heading] if nearest_heading else [])
        heading_path = " > ".join(h.text for h in context_levels)

        return {
            "heading_path": heading_path,
            "nearest_heading": nearest_heading.text if nearest_heading else "",
            "heading_level": nearest_heading.level if nearest_heading else 0,
            "heading_context_levels": [
                {"level": h.level, "text": h.text} for h in context_levels
            ]
        }
