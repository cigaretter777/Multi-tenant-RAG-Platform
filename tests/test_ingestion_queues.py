import unittest

from ingestion.queues import InProcessQueue, Priority, QueueName, QueueRegistry


async def _noop():
    return None


class IngestionQueueTest(unittest.IsolatedAsyncioTestCase):
    async def test_dequeue_follows_priority_then_fifo(self):
        queue = InProcessQueue(QueueName.EMBEDDING)

        await queue.submit(Priority.GRAPH_BUILD, _noop)
        await queue.submit(Priority.NORMAL_INGEST, _noop)
        await queue.submit(Priority.URGENT_INDEX, _noop)
        await queue.submit(Priority.NORMAL_INGEST, _noop)

        priorities = []
        while queue.qsize():
            priority, _ = await queue.next()
            priorities.append(priority)

        self.assertEqual(
            priorities,
            [Priority.URGENT_INDEX, Priority.NORMAL_INGEST, Priority.NORMAL_INGEST, Priority.GRAPH_BUILD],
        )

    async def test_graph_build_never_jumps_ahead_of_normal_ingest(self):
        queue = InProcessQueue(QueueName.GRAPH)

        await queue.submit(Priority.GRAPH_BUILD, _noop)
        await queue.submit(Priority.NORMAL_INGEST, _noop)

        first, _ = await queue.next()
        self.assertEqual(first, Priority.NORMAL_INGEST)

    async def test_registry_exposes_four_queues(self):
        registry = QueueRegistry()

        await registry.submit(QueueName.PARSE, Priority.NORMAL_INGEST, _noop)
        await registry.submit(QueueName.CLEANUP, Priority.URGENT_INDEX, _noop)

        self.assertEqual(registry.get(QueueName.PARSE).qsize(), 1)
        self.assertEqual(registry.get(QueueName.GRAPH).qsize(), 0)
