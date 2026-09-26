"""检索与答案指标（设计文档 §10.2）。"""
import math
from typing import List, Sequence


def recall_at_k(retrieved: Sequence[str], relevant: Sequence[str], k: int) -> float:
    if not relevant:
        return 0.0
    hits = len(set(retrieved[:k]) & set(relevant))
    return hits / len(relevant)


def mrr(retrieved: Sequence[str], relevant: Sequence[str]) -> float:
    rel = set(relevant)
    for rank, item in enumerate(retrieved, start=1):
        if item in rel:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(retrieved: Sequence[str], relevant: Sequence[str], k: int) -> float:
    rel = set(relevant)
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, item in enumerate(retrieved[:k], start=1)
        if item in rel
    )
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(len(rel), k) + 1))
    return dcg / idcg if idcg else 0.0


def citation_accuracy(used_refs: Sequence[str], valid_refs: Sequence[str]) -> float:
    if not used_refs:
        return 1.0
    valid = set(valid_refs)
    return sum(ref in valid for ref in used_refs) / len(used_refs)


def refusal_accuracy(predicted: Sequence[bool], expected: Sequence[bool]) -> float:
    if not expected:
        return 1.0
    return sum(p == e for p, e in zip(predicted, expected)) / len(expected)
