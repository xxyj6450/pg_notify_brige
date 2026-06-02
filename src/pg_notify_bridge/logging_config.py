"""控制台日志初始化。

统一日志格式与级别，并降低 httpx 等第三方库的噪声输出。
"""

from __future__ import annotations

import logging
import sys


def setup_logging(level: str = "INFO") -> None:
    """配置根 logger，将结构化日志输出到标准输出。

    Args:
        level: 日志级别名称，如 INFO、DEBUG；非法值回退为 INFO。
    """
    # 将字符串级别转换为 logging 模块使用的整数常量
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    # 清除已有 handler，避免重复配置时日志重复打印
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(numeric_level)

    # HTTP 客户端内部 DEBUG 信息过多，默认只保留 WARNING 及以上
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
