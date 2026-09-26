"""Token 预算控制：按排名顺序整条选取，不跨候选截半（设计文档 §7.4）。"""
from typing import Callable, List

from retrieval.candidates import Candidate


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def select_within_budget(
    candidates: List[Candidate],
    budget_tokens: int,
    tokenizer: Callable[[str], int] = estimate_tokens,
) -> List[Candidate]:
    selected: List[Candidate] = []
    used = 0
    for candidate in candidates:
        cost = tokenizer(candidate.text)
        if used + cost > budget_tokens:
            break
        selected.append(candidate)
        used += cost
    return selected
