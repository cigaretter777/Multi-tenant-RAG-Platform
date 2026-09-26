"""auto 策略路由：实体关系/多跳/全局总结类问题加挂 GraphRAG（设计文档 §7.5）。

默认启发式可被注入的分类器替换（评测消融钩子）。
"""
from typing import Callable, Optional

GRAPH_MARKERS = (
    "关系", "关联", "影响", "原因", "为什么", "对比", "区别",
    "总结", "概述", "历程", "如何演化", "哪些因素",
)
MULTI_HOP_MARKERS = ("分别", "进而", "导致", "之后", "前提", "依赖", "是否同时")


def heuristic_classify(question: str) -> str:
    if any(marker in question for marker in GRAPH_MARKERS + MULTI_HOP_MARKERS):
        return "hybrid_graph"
    return "hybrid"


class QueryRouter:
    def __init__(self, classify: Optional[Callable[[str], str]] = None):
        self.classify = classify or heuristic_classify

    def route(self, question: str) -> str:
        return self.classify(question)
