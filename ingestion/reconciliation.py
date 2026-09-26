"""一致性扫描：把 stalled 版本与卡在 deleting 的版本重新入队（设计文档 §9）。

不做分布式事务；靠幂等写入 + 阶段状态 + 有限重试 + 补偿任务达到最终一致。
"""
from datetime import timedelta
from typing import Any, Awaitable, Callable, Dict, Optional

from ingestion.queues import Priority, QueueName

DEFAULT_STALL_THRESHOLD = timedelta(minutes=15)

JobFactory = Callable[[Dict, str], Callable[[], Awaitable[Any]]]


async def _noop_job(row: Dict, kind: str):
    return None


async def reconcile(
    repo,
    queues,
    now,
    job_factory: Optional[JobFactory] = None,
    stall_threshold: timedelta = DEFAULT_STALL_THRESHOLD,
) -> Dict[str, int]:
    factory = job_factory or (lambda row, kind: (lambda: _noop_job(row, kind)))
    cutoff = now - stall_threshold

    stalled = await repo.list_stalled(cutoff)
    for row in stalled:
        queue = QueueName.PARSE if row["vector_stage"] in ("uploaded", "parsing") else QueueName.EMBEDDING
        await queues.submit(queue, Priority.NORMAL_INGEST, factory(row, "ingest"))

    deleting = await repo.list_deleting()
    for row in deleting:
        await queues.submit(QueueName.CLEANUP, Priority.URGENT_INDEX, factory(row, "cleanup"))

    return {"stalled": len(stalled), "deleting": len(deleting)}
