"""熔断器：连续失败超阈值即开路，冷却结束前快速失败（设计文档 §7.5）。"""
from typing import Callable
import time


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.clock = clock
        self.failures = 0
        self.state = "closed"
        self.opened_at = None

    def allow(self) -> bool:
        if self.state != "open":
            return True
        if self.clock() - self.opened_at >= self.cooldown_seconds:
            self.state = "half-open"
            return True
        return False

    def record_success(self) -> None:
        self.failures = 0
        self.state = "closed"
        self.opened_at = None

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self.state = "open"
            self.opened_at = self.clock()
