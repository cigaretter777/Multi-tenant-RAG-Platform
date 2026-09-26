"""建库队列：四条队列 + 四级优先级（设计文档 §6.2）。

首版为进程内 asyncio 实现；接口（submit / next）预留 Redis 适配器。
在线问答不进入离线建库队列。
"""
import asyncio
from enum import IntEnum
from typing import Any, Awaitable, Callable, Tuple


class QueueName(str):
    PARSE = "parse_queue"
    EMBEDDING = "embedding_queue"
    GRAPH = "graph_queue"
    CLEANUP = "cleanup_queue"


class Priority(IntEnum):
    ONLINE_ANSWER = 0
    URGENT_INDEX = 1
    NORMAL_INGEST = 2
    GRAPH_BUILD = 3


Job = Callable[[], Awaitable[Any]]


class InProcessQueue:
    """单队列：按优先级出队，同优先级 FIFO。"""

    def __init__(self, name: str):
        self.name = name
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._seq = 0

    async def submit(self, priority: Priority, job: Job) -> None:
        self._seq += 1
        await self._queue.put((int(priority), self._seq, job))

    async def next(self) -> Tuple[Priority, Job]:
        priority, _, job = await self._queue.get()
        return Priority(priority), job

    def qsize(self) -> int:
        return self._queue.qsize()


class QueueRegistry:
    """四条建库队列的注册表。"""

    def __init__(self):
        self.queues = {
            name: InProcessQueue(name)
            for name in (QueueName.PARSE, QueueName.EMBEDDING, QueueName.GRAPH, QueueName.CLEANUP)
        }

    def get(self, name: str) -> InProcessQueue:
        return self.queues[name]

    async def submit(self, name: str, priority: Priority, job: Job) -> None:
        await self.get(name).submit(priority, job)
