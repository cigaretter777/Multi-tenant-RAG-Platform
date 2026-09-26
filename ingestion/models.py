"""建库控制面领域模型：版本键、阶段枚举与合法转移表。

向量链与图谱链独立推进：图谱失败时向量链仍可到达 indexed，
知识库继续提供普通 RAG 服务（设计文档 §6.4）。
"""
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Set
from uuid import UUID


class IngestionStage(str, Enum):
    UPLOADED = "uploaded"
    PARSING = "parsing"
    PARSED = "parsed"
    EMBEDDING = "embedding"
    INDEXED = "indexed"
    GRAPH_PENDING = "graph_pending"
    GRAPH_BUILDING = "graph_building"
    GRAPH_READY = "graph_ready"
    DELETING = "deleting"
    DELETED = "deleted"
    FAILED = "failed"


class Chain(str, Enum):
    VECTOR = "vector"
    GRAPH = "graph"


# 向量链：uploaded → parsing → parsed → embedding → indexed
VECTOR_TRANSITIONS: Dict[IngestionStage, Set[IngestionStage]] = {
    IngestionStage.UPLOADED: {IngestionStage.PARSING, IngestionStage.DELETING},
    IngestionStage.PARSING: {IngestionStage.PARSED, IngestionStage.FAILED, IngestionStage.DELETING},
    IngestionStage.PARSED: {IngestionStage.EMBEDDING, IngestionStage.DELETING},
    IngestionStage.EMBEDDING: {IngestionStage.INDEXED, IngestionStage.FAILED, IngestionStage.DELETING},
    IngestionStage.INDEXED: {IngestionStage.DELETING},
    IngestionStage.FAILED: {IngestionStage.PARSING, IngestionStage.EMBEDDING, IngestionStage.DELETING},
}

# 图谱链：parsed → graph_pending → graph_building → graph_ready
GRAPH_TRANSITIONS: Dict[IngestionStage, Set[IngestionStage]] = {
    IngestionStage.PARSED: {IngestionStage.GRAPH_PENDING, IngestionStage.DELETING},
    IngestionStage.GRAPH_PENDING: {IngestionStage.GRAPH_BUILDING, IngestionStage.FAILED, IngestionStage.DELETING},
    IngestionStage.GRAPH_BUILDING: {IngestionStage.GRAPH_READY, IngestionStage.FAILED, IngestionStage.DELETING},
    IngestionStage.GRAPH_READY: {IngestionStage.DELETING},
    IngestionStage.FAILED: {IngestionStage.GRAPH_PENDING, IngestionStage.DELETING},
}

TERMINAL_STAGES = {IngestionStage.DELETED}


@dataclass(frozen=True)
class VersionKey:
    """幂等键的文档坐标：tenant + kb + document + version。"""

    tenant_id: UUID
    kb_id: UUID
    document_id: UUID
    version: int

    def stage_key(self, stage: IngestionStage) -> str:
        return f"{self.tenant_id}:{self.kb_id}:{self.document_id}:{self.version}:{stage.value}"


class IllegalStageTransition(Exception):
    """阶段转移不在合法转移表内。"""
