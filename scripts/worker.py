"""建库 worker：周期性一致性扫描 + 队列消费骨架。

首版使用进程内队列与定时 reconcile；生产形态替换为 Redis 队列适配器
（接口见 ingestion/queues.py），本脚本保持入口不变。
"""
import asyncio
from datetime import datetime, timezone

from ingestion.queues import QueueRegistry
from ingestion.reconciliation import reconcile
from ingestion.repository import IngestionRepository
from utils.db import DatabaseManager, close_database, init_database


async def main(interval: float = 60.0) -> None:
    await init_database()
    queues = QueueRegistry()
    repository = IngestionRepository(DatabaseManager)
    try:
        while True:
            counts = await reconcile(repository, queues, datetime.now(timezone.utc))
            if any(counts.values()):
                print(f"reconcile: {counts}")
            await asyncio.sleep(interval)
    finally:
        await close_database()


if __name__ == "__main__":
    asyncio.run(main())
