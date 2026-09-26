"""统一候选结构（设计文档 §7.3）。"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

ALLOWED_SOURCES = ("bm25", "dense", "sparse", "graph")


@dataclass
class Candidate:
    chunk_id: str
    document_id: str
    kb_id: str
    text: str
    source: str
    score: float
    file_name: str = ""
    page_number: Optional[int] = None
    image_refs: List[str] = field(default_factory=list)
    ranks: Dict[str, int] = field(default_factory=dict)

    def __post_init__(self):
        if self.source not in ALLOWED_SOURCES:
            raise ValueError(f"unknown candidate source: {self.source}")
