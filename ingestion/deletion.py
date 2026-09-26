"""删除补偿：deleting → milvus → graph → artifacts → deleted。

每一步幂等可重试；失败停在该步并以 `failed_at:<step>` 记录结构化错误，
重跑时跳过已完成步骤，不对用户声称已完全删除（设计文档 §6.5）。
"""
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional, Set

from ingestion.models import IngestionStage, VersionKey

STEP_NAMES = ("milvus", "graph", "artifacts")


@dataclass
class DeletionDeps:
    delete_milvus: Callable[[Dict], Awaitable[None]]
    delete_graph: Callable[[Dict], Awaitable[None]]
    delete_artifacts: Callable[[Dict], Awaitable[None]]

    def steps(self):
        return [
            ("milvus", self.delete_milvus),
            ("graph", self.delete_graph),
            ("artifacts", self.delete_artifacts),
        ]


def _completed_steps(error: Optional[str]) -> Set[str]:
    """从 failed_at 错误推导已完成的步骤（失败步之前的都已完成）。"""
    if not error or not error.startswith("failed_at:"):
        return set()
    failed_name = error.split(":", 2)[1]
    completed = set()
    for name in STEP_NAMES:
        if name == failed_name:
            break
        completed.add(name)
    return completed


async def delete_version(version_row: Dict, key: VersionKey, repo, deps: DeletionDeps) -> bool:
    version_id = version_row["id"]
    stage_key = key.stage_key(IngestionStage.DELETING)

    existing = await repo.get_stage(stage_key)
    completed = _completed_steps(existing.get("error") if existing else None)

    await repo.record_stage(version_id, stage_key, IngestionStage.DELETING, "running")
    for name, step in deps.steps():
        if name in completed:
            continue
        try:
            await step(version_row)
        except Exception as exc:
            await repo.record_stage(
                version_id, stage_key, IngestionStage.DELETING, "running",
                error=f"failed_at:{name}: {exc}",
            )
            return False
        completed.add(name)

    await repo.mark_deleted(version_id)
    await repo.record_stage(version_id, stage_key, IngestionStage.DELETING, "finish")
    return True
