"""引用构建与校验：[ref-N] 编号必须真实存在于候选集合（设计文档 §7.6）。"""
import re
from dataclasses import dataclass
from typing import Dict, List, Tuple

REF_PATTERN = re.compile(r"\[ref-(\d+)\]")


@dataclass
class Citation:
    ref_id: str
    document_id: str
    file_name: str
    page_number: object = None
    chunk_id: str = ""


def build_context(candidates) -> Tuple[str, Dict[str, Citation]]:
    blocks: List[str] = []
    citations: Dict[str, Citation] = {}
    for i, candidate in enumerate(candidates, start=1):
        ref = f"ref-{i}"
        citations[ref] = Citation(
            ref_id=ref,
            document_id=candidate.document_id,
            file_name=candidate.file_name,
            page_number=candidate.page_number,
            chunk_id=candidate.chunk_id,
        )
        page = candidate.page_number if candidate.page_number is not None else "?"
        blocks.append(f"[{ref}] 文件：{candidate.file_name or candidate.document_id}，第 {page} 页\n内容：{candidate.text}")
    return "\n\n".join(blocks), citations


def used_refs(answer: str) -> List[str]:
    return [f"ref-{n}" for n in REF_PATTERN.findall(answer)]


def validate(answer: str, citations: Dict[str, Citation]) -> List[str]:
    """返回答案引用了但不真实存在的编号；空列表表示全部有效。"""
    return [ref for ref in used_refs(answer) if ref not in citations]
