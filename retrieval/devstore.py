"""dev 模式内存产物/向量存储：让 v1 全链路在无 Milvus/模型服务时仍可运行。

生产适配器（Milvus 稠密/稀疏索引、PG 产物表、真实 embedding）以依赖覆盖
单独接入；hash embedding 仅用于开发与冒烟，不代表检索质量（见 benchmarks/）。
"""
import hashlib
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

DIM = 64


def hash_embed(text: str) -> List[float]:
    vec = [0.0] * DIM
    for token in text.lower().split():
        digest = hashlib.md5(token.encode()).digest()
        for i in range(DIM):
            vec[i] += (digest[i % 16] - 128) / 128.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


@dataclass
class StoredChunk:
    chunk_id: str
    document_id: str
    kb_id: str
    tenant_id: str
    text: str
    file_name: str = ""
    page_number: Optional[int] = None
    embedding: List[float] = field(default_factory=list)


def chunk_text(text: str, chunk_size: int = 300, overlap: int = 100) -> List[str]:
    if len(text) <= chunk_size:
        return [text]
    out: List[str] = []
    start = 0
    while start < len(text):
        out.append(text[start:start + chunk_size])
        start += chunk_size - overlap
    return out


class DevStore:
    def __init__(self):
        self.parsed_documents: Dict[str, dict] = {}
        self.chunks: List[StoredChunk] = []

    def store_parsed(self, parsed) -> str:
        parsed_id = f"parsed-{len(self.parsed_documents) + 1}"
        self.parsed_documents[parsed_id] = {
            "document_id": str(parsed.document_id),
            "tenant_id": str(parsed.tenant_id),
            "kb_id": str(parsed.kb_id),
            "text": parsed.text,
            "pages": parsed.pages,
            "images": parsed.images,
            "parser_version": parsed.parser_version,
        }
        return parsed_id

    def add_chunks(self, chunks: Sequence[StoredChunk]) -> None:
        self.chunks.extend(chunks)

    def filtered(self, tenant_id, kb_ids) -> List[StoredChunk]:
        tenant = str(tenant_id)
        kbs = {str(kb) for kb in kb_ids}
        return [c for c in self.chunks if c.tenant_id == tenant and c.kb_id in kbs]

    async def search(self, query, source, tenant_id, kb_ids, top_k):
        query_vec = hash_embed(query)
        scored = []
        for chunk in self.filtered(tenant_id, kb_ids):
            score = sum(a * b for a, b in zip(query_vec, chunk.embedding))
            scored.append((score, chunk))
        scored.sort(key=lambda pair: -pair[0])
        return [
            {
                "chunk_id": c.chunk_id,
                "document_id": c.document_id,
                "kb_id": c.kb_id,
                "text": c.text,
                "score": score,
                "file_name": c.file_name,
                "page_number": c.page_number,
            }
            for score, c in scored[:top_k]
        ]


def bm25_loader_from(store: DevStore):
    async def loader(ctx):
        return [
            {
                "chunk_id": c.chunk_id,
                "document_id": c.document_id,
                "kb_id": c.kb_id,
                "text": c.text,
                "file_name": c.file_name,
                "page_number": c.page_number,
            }
            for c in store.filtered(ctx.tenant_id, ctx.kb_ids)
        ]
    return loader
