"""pg-notify-bridge 程序入口。

加载 .env / 环境变量，初始化日志，启动 NotifyBridge 主循环。
"""

from __future__ import annotations

import logging
import sys

from dotenv import load_dotenv

from .config import ConfigError, load_settings, settings_summary
from .listener import NotifyBridge
from .logging_config import setup_logging

logger = logging.getLogger(__name__)


def main() -> int:
    """应用主函数。

    流程：加载环境 → 校验配置 → 初始化日志 → 运行监听桥 → 清理资源。

    Returns:
        进程退出码，0 表示正常，1 表示配置或运行时错误。
    """
    # 本地开发时从 .env 文件注入环境变量（生产环境通常由 Docker/K8s 注入）
    load_dotenv()

    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    setup_logging(settings.log_level)
    logger.info("pg-notify-bridge starting")
    logger.info("Configuration: %s", settings_summary(settings))

    bridge = NotifyBridge(settings)
    exit_code = 0

    try:
        bridge.run()
    except RuntimeError as exc:
        # 例如 Windows 上 pgnotify 不可用
        logger.error("%s", exc)
        exit_code = 1
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received, shutting down")
    except Exception:
        logger.exception("Fatal error in listener loop")
        exit_code = 1
    finally:
        # 无论正常或异常退出，都等待在途 Webhook 并关闭线程池
        bridge.close()

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
