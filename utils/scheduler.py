"""
定时任务调度器模块

负责定时清理过期的解析结果
使用 FastAPI 原生的后台任务方式，避免事件循环冲突
"""
import asyncio
from typing import Optional

from configs.config import settings
from utils.logger import get_logger

logger = get_logger()


class ParseResultScheduler:
    """解析结果清理调度器 - 使用 FastAPI 原生后台任务"""

    _instance: Optional["ParseResultScheduler"] = None
    _task: Optional[asyncio.Task] = None
    _running: bool = False

    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """初始化调度器"""
        pass

    async def start_cleanup_job(self, interval_seconds: Optional[int] = None):
        """
        启动定时清理任务（异步版本）

        Args:
            interval_seconds: 清理间隔（秒），如果不指定则使用配置中的值
        """
        if self._running:
            logger.warning("定时清理任务已在运行中")
            return

        if interval_seconds is None:
            interval_seconds = settings.parse_cleanup_interval

        self._running = True
        logger.info(f"定时清理任务已启动，间隔: {interval_seconds}秒")

        # 创建后台任务
        self._task = asyncio.create_task(self._cleanup_loop(interval_seconds))

    async def _cleanup_loop(self, interval_seconds: int):
        """
        清理循环

        Args:
            interval_seconds: 清理间隔（秒）
        """
        try:
            while self._running:
                try:
                    await self._cleanup_expired()
                except Exception as e:
                    logger.error(f"定时清理任务执行失败: {str(e)}")

                # 等待下一个周期
                await asyncio.sleep(interval_seconds)

        except asyncio.CancelledError:
            logger.info("定时清理任务已取消")
        except Exception as e:
            logger.error(f"定时清理循环异常退出: {str(e)}")
        finally:
            self._running = False

    async def _cleanup_expired(self):
        """清理过期的解析结果"""
        try:
            from utils.parse_storage_manager import cleanup_expired_parse_results

            deleted_count = await cleanup_expired_parse_results()
            if deleted_count > 0:
                logger.info(f"定时清理完成，删除了 {deleted_count} 条过期记录")

        except Exception as e:
            logger.error(f"清理过期解析结果失败: {str(e)}")

    async def shutdown(self):
        """关闭调度器"""
        if not self._running:
            return

        logger.info("正在停止定时清理任务...")
        self._running = False

        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.info("定时清理任务已停止")


# ============ 全局调度器实例 ============

_scheduler_instance: Optional[ParseResultScheduler] = None


def get_scheduler() -> ParseResultScheduler:
    """获取调度器实例"""
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = ParseResultScheduler()
    return _scheduler_instance


async def start_parse_cleanup_scheduler(interval_seconds: Optional[int] = None):
    """
    启动解析结果清理调度器（异步版本）

    Args:
        interval_seconds: 清理间隔（秒），如果不指定则使用配置中的值
    """
    scheduler = get_scheduler()
    await scheduler.start_cleanup_job(interval_seconds)


async def shutdown_scheduler():
    """关闭调度器（异步版本）"""
    global _scheduler_instance
    if _scheduler_instance:
        await _scheduler_instance.shutdown()
