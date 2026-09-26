"""流式生成、拒答与引用校验（设计文档 §7.6）。

证据为空 → 明确拒答，不靠模型参数知识补全；
答案引用了不存在的编号 → 视为生成失败，终态事件改为拒答并说明原因。
"""
from dataclasses import dataclass, field
from typing import AsyncIterator, List, Optional

from answer.citations import build_context, validate

REFUSAL = "证据不足，无法回答该问题。请补充或改写问题。"


@dataclass
class AnswerEvent:
    token: Optional[str] = None
    final: bool = False
    answer: str = ""
    citations: List[dict] = field(default_factory=list)
    refused: bool = False
    reason: str = ""


class AnswerService:
    def __init__(self, llm_stream):
        """llm_stream: async (question, context) -> 异步 token 迭代器"""
        self.llm_stream = llm_stream

    async def stream(self, question: str, candidates) -> AsyncIterator[AnswerEvent]:
        if not candidates:
            yield AnswerEvent(final=True, answer=REFUSAL, refused=True, reason="no evidence")
            return

        context, citations = build_context(candidates)
        buffer: List[str] = []
        async for token in self.llm_stream(question, context):
            buffer.append(token)
            yield AnswerEvent(token=token)

        answer = "".join(buffer)
        missing = validate(answer, citations)
        if missing:
            yield AnswerEvent(
                final=True, answer=REFUSAL, citations=[], refused=True,
                reason=f"invalid citations: {missing}",
            )
            return

        used = [
            citation.__dict__
            for citation in citations.values()
            if f"[{citation.ref_id}]" in answer
        ]
        yield AnswerEvent(final=True, answer=answer, citations=used)
