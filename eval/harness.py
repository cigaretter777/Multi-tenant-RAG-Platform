"""离线检索评测 harness。

默认以 BM25 作为离线代理召回器（不依赖在线模型服务）；真实 embedding/
reranker 评测需注入对应 retriever 并在 benchmarks/ 记录环境元数据（设计文档 §10.4）。
"""
from typing import Dict, List

from eval.fixtures import CHUNKS
from eval.metrics import mrr, ndcg_at_k, recall_at_k
from retrieval.base import RetrievalContext
from retrieval.bm25 import BM25Retriever


def corpus_loader_for(kb_names: List[str]):
    async def loader(ctx):
        docs = []
        for kb in kb_names:
            for chunk in CHUNKS.get(kb, []):
                docs.append(
                    {
                        "chunk_id": chunk["chunk_id"],
                        "document_id": kb,
                        "kb_id": kb,
                        "text": chunk["text"],
                        "file_name": kb,
                        "page_number": chunk["page"],
                    }
                )
        return docs
    return loader


async def run_retrieval_eval(questions: List[Dict], top_k: int = 5) -> Dict[str, float]:
    scores = {"recall@5": [], "recall@10": [], "mrr": [], "ndcg@5": []}
    for item in questions:
        if not item["answerable"]:
            continue
        retriever = BM25Retriever(corpus_loader_for(item["kbs"]))
        ctx = RetrievalContext(tenant_id=item["tenant"], kb_ids=tuple(item["kbs"]), top_k=top_k)
        candidates = await retriever.retrieve(item["question"], ctx)
        retrieved = [c.chunk_id for c in candidates]
        relevant = item["relevant"]
        scores["recall@5"].append(recall_at_k(retrieved, relevant, 5))
        scores["recall@10"].append(recall_at_k(retrieved, relevant, 10))
        scores["mrr"].append(mrr(retrieved, relevant))
        scores["ndcg@5"].append(ndcg_at_k(retrieved, relevant, 5))
    return {name: sum(values) / len(values) for name, values in scores.items()}
