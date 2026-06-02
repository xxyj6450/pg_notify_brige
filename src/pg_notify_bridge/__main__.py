"""Entry point for the PostgreSQL NOTIFY to webhook bridge."""

from __future__ import annotations

import logging
import sys

from dotenv import load_dotenv

from .config import ConfigError, load_settings, settings_summary
from .listener import NotifyBridge
from .logging_config import setup_logging

logger = logging.getLogger(__name__)


def main() -> int:
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
        logger.error("%s", exc)
        exit_code = 1
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received, shutting down")
    except Exception:
        logger.exception("Fatal error in listener loop")
        exit_code = 1
    finally:
        bridge.close()

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
