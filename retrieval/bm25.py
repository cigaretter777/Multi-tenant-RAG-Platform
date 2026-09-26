"""BM25 召回器：语料快照由依赖注入（PG tsvector / 内存快照皆可）。"""
import math
from collections import Counter
from typing import Callable, List

from retrieval.base import RetrievalContext
from retrieval.candidates import Candidate


def tokenize(text: str) -> List[str]:
    return text.lower().split()


class BM25Retriever:
    name = "bm25"

    def __init__(self, corpus_loader: Callable, k1: float = 1.5, b: float = 0.75):
        self.corpus_loader = corpus_loader
        self.k1 = k1
        self.b = b

    async def retrieve(self, question: str, ctx: RetrievalContext) -> List[Candidate]:
        docs = await self.corpus_loader(ctx)
        tokenized = [tokenize(d["text"]) for d in docs]
        n = len(tokenized)
        if n == 0:
            return []
        avgdl = sum(len(t) for t in tokenized) / n
        df = Counter()
        for toks in tokenized:
            for term in set(toks):
                df[term] += 1

        scored = []
        for i, toks in enumerate(tokenized):
            tf = Counter(toks)
            score = 0.0
            for term in tokenize(question):
                if term not in tf:
                    continue
                idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
                score += idf * (tf[term] * (self.k1 + 1)) / (
                    tf[term] + self.k1 * (1 - self.b + self.b * len(toks) / avgdl)
                )
            scored.append((score, i))
        scored.sort(key=lambda pair: (-pair[0], pair[1]))

        out = []
        for rank, (score, i) in enumerate(scored[: ctx.top_k], start=1):
            doc = docs[i]
            out.append(
                Candidate(
                    chunk_id=doc["chunk_id"],
                    document_id=doc["document_id"],
                    kb_id=doc["kb_id"],
                    text=doc["text"],
                    source=self.name,
                    score=score,
                    file_name=doc.get("file_name", ""),
                    page_number=doc.get("page_number"),
                    ranks={self.name: rank},
                )
            )
        return out
