"""RRF 融合：按 chunk_id 去重、保留各召回来源与原始排名（设计文档 §7.4）。

不同召回器的原始分数不直接相加：RRF(d) = Σ 1 / (k + rank_i(d))。
"""
from dataclasses import replace
from typing import Dict, List

from retrieval.candidates import Candidate


def rrf_fusion(ranked_lists: Dict[str, List[Candidate]], k: int = 60, top_n: int = 10) -> List[Candidate]:
    merged: Dict[str, Candidate] = {}
    for source, candidates in ranked_lists.items():
        for rank, candidate in enumerate(candidates, start=1):
            item = merged.get(candidate.chunk_id)
            if item is None:
                item = replace(candidate, ranks={})
                merged[candidate.chunk_id] = item
            item.ranks[source] = rank

    for item in merged.values():
        item.score = sum(1.0 / (k + rank) for rank in item.ranks.values())

    fused = sorted(merged.values(), key=lambda c: (-c.score, c.chunk_id))
    return fused[:top_n]
