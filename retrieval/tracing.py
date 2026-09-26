"""检索追踪：每路耗时/命中数、融合参数与阶段序列（设计文档 §7.2）。"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class RetrievalTrace:
    trace_id: str
    question: str
    strategy: str
    sources: Dict[str, Dict] = field(default_factory=dict)
    fusion_k: Optional[int] = None
    stages: List[str] = field(default_factory=list)
