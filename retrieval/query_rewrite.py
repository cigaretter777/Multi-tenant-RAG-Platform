"""Query 改写钩子：默认 identity，可注入纠错/改写/扩展实现（设计文档 §7.2）。"""
from typing import Awaitable, Callable

QueryRewriter = Callable[[str], Awaitable[str]]


async def identity_rewriter(question: str) -> str:
    return question
