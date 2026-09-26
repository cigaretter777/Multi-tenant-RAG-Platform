"""
优化的日志模块
- 解决日志重复打印问题
- 彩色终端输出
- 单例模式
"""
import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler


class LogColor:
    """日志颜色"""
    RESET = "\033[0m"
    RED = "\033[91m"      # ERROR
    YELLOW = "\033[93m"   # WARNING
    GREEN = "\033[92m"    # INFO
    BLUE = "\033[94m"     # DEBUG


class ColoredFormatter(logging.Formatter):
    """彩色日志格式化器"""

    COLORS = {
        logging.ERROR: LogColor.RED,
        logging.WARNING: LogColor.YELLOW,
        logging.INFO: LogColor.GREEN,
        logging.DEBUG: LogColor.BLUE,
    }

    def format(self, record):
        message = super().format(record)
        color = self.COLORS.get(record.levelno, "")
        if color:
            message = message.replace(f"- {record.levelname} -",
                                     f"- {color}{record.levelname}{LogColor.RESET} -")
        return message


# 单例
_logger_instance = None


def get_logger(name="embedding_app"):
    """获取 logger 实例（单例模式）"""
    global _logger_instance

    # 已初始化则直接返回
    if _logger_instance is not None:
        return _logger_instance

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # 已有 handlers 则直接返回
    if logger.handlers:
        return logger

    logger.propagate = False

    # 日志目录
    log_dir = f"./logs/{datetime.now().date()}"
    os.makedirs(log_dir, exist_ok=True)

    # 文件 handler（无颜色）
    file_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler = RotatingFileHandler(
        f"{log_dir}/app.log",
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setFormatter(file_formatter)

    # 终端 handler（彩色）
    console_formatter = ColoredFormatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(console_formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    _logger_instance = logger
    return logger
