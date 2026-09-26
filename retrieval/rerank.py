"""精排：问题与候选文本重新打分（设计文档 §7.4）。"""
from dataclasses import replace
from typing import Callable, List

from retrieval.candidates import Candidate


class PassthroughReranker:
    """消融基线：不改变融合顺序。"""

    async def rerank(self, question: str, candidates: List[Candidate]) -> List[Candidate]:
        return list(candidates)


class ScoringReranker:
    """score_fn: async (question, text) -> float；按新分数降序。"""

    def __init__(self, score_fn: Callable):
        self.score_fn = score_fn

    async def rerank(self, question: str, candidates: List[Candidate]) -> List[Candidate]:
        scored = []
        for candidate in candidates:
            score = await self.score_fn(question, candidate.text)
            scored.append(replace(candidate, score=score))
        scored.sort(key=lambda c: -c.score)
        return scored
