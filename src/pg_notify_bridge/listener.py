"""基于 pgnotify 的 PostgreSQL NOTIFY 长期监听器。

负责建立 LISTEN 长连接、处理信号与断连重连，
并将收到的通知交给 WebhookForwarder 异步转发。
"""

from __future__ import annotations

import logging
import signal
import time

import psycopg2

from .config import Settings
from .forwarder import WebhookForwarder

logger = logging.getLogger(__name__)

# Docker stop / Ctrl+C 时触发优雅退出
SIGNALS_TO_HANDLE = [signal.SIGINT, signal.SIGTERM]


def _load_pgnotify():
    """延迟导入 pgnotify，并在 Windows 上给出明确错误提示。

    pgnotify 依赖 fcntl 等 Unix API，无法在原生 Windows 上运行。

    Returns:
        (await_pg_notifications, get_dbapi_connection) 函数元组。

    Raises:
        RuntimeError: 在缺少 fcntl 的非 Unix 系统上导入失败时。
    """
    try:
        from pgnotify import await_pg_notifications, get_dbapi_connection
    except ModuleNotFoundError as exc:
        if exc.name == "fcntl":
            raise RuntimeError(
                "pgnotify requires a Unix-like OS (Linux/macOS). "
                "Run this service in Docker or WSL2 on Windows."
            ) from exc
        raise
    return await_pg_notifications, get_dbapi_connection


class NotifyBridge:
    """NOTIFY 监听与 Webhook 转发的协调器。

    外层 run() 循环负责断连后自动重连；
    内层 _listen_once() 单次建立连接并阻塞在 pgnotify 迭代器上。
    """

    def __init__(self, settings: Settings) -> None:
        """创建桥接实例。

        Args:
            settings: 数据库、频道、Webhook 等运行时配置。
        """
        self._settings = settings
        self._forwarder = WebhookForwarder(settings)
        self._stop_requested = False

    def run(self) -> None:
        """启动主循环：监听 NOTIFY，异常时自动重连直至收到停止信号。

        RuntimeError（如 Windows 平台不支持）会直接向上抛出，不重试。
        """
        logger.info(
            "Starting listener | channels=%s",
            ", ".join(self._settings.pg_channels),
        )
        while not self._stop_requested:
            try:
                self._listen_once()
            except RuntimeError:
                # 平台不支持等不可恢复错误，不应进入重连循环
                raise
            except psycopg2.OperationalError as exc:
                logger.error(
                    "PostgreSQL connection error: %s. Reconnecting in %.1fs",
                    exc,
                    self._settings.reconnect_delay,
                )
                time.sleep(self._settings.reconnect_delay)
            except Exception:
                logger.exception(
                    "Unexpected listener error. Reconnecting in %.1fs",
                    self._settings.reconnect_delay,
                )
                time.sleep(self._settings.reconnect_delay)

        logger.info("Shutdown complete")

    def stop(self) -> None:
        """请求停止监听（可由外部调用）。"""
        self._stop_requested = True

    def close(self) -> None:
        """释放转发器资源，等待在途 Webhook 完成。"""
        self._forwarder.close()

    def _listen_once(self) -> None:
        """建立一次 PostgreSQL 连接并进入 pgnotify 事件循环。

        await_pg_notifications 可能 yield 三类值：
        - NOTIFY 对象：实际通知，提交给 forwarder
        - None：select 超时（yield_on_timeout=True），用于心跳检测
        - int：收到的信号编号（SIGINT/SIGTERM），触发优雅退出
        """
        await_pg_notifications, get_dbapi_connection = _load_pgnotify()
        connection = get_dbapi_connection(self._settings.pg_dsn)
        logger.info("Connected to PostgreSQL, subscribing to channels")

        try:
            for event in await_pg_notifications(
                connection,
                list(self._settings.pg_channels),
                timeout=self._settings.listen_timeout,
                yield_on_timeout=True,
                handle_signals=SIGNALS_TO_HANDLE,
            ):
                if self._stop_requested:
                    break

                if isinstance(event, int):
                    # pgnotify 在收到 SIGINT/SIGTERM 时 yield 信号编号
                    sig = signal.Signals(event)
                    logger.info("Received %s, shutting down gracefully", sig.name)
                    self._stop_requested = True
                    break

                if event is None:
                    # 空闲超时：执行 SELECT 1 确认连接仍可用
                    logger.debug("Listen poll timeout, connection still alive")
                    self._ensure_connection_alive(connection)
                    continue

                logger.info(
                    "NOTIFY received | channel=%s | pid=%s | payload=%s",
                    event.channel,
                    event.pid,
                    _safe_payload(event.payload),
                )
                self._forwarder.submit(event)
        finally:
            try:
                connection.close()
            except Exception:
                logger.exception("Error while closing PostgreSQL connection")

    def _ensure_connection_alive(self, connection) -> None:
        """通过简单查询检测 LISTEN 长连接是否仍然有效。

        若连接已被服务端或中间网络断开，将抛出 OperationalError，
        由 run() 外层捕获并触发重连。

        Args:
            connection: psycopg2 DBAPI 连接对象。
        """
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
        except psycopg2.Error as exc:
            logger.warning("Connection health check failed: %s", exc)
            raise psycopg2.OperationalError(str(exc)) from exc


def _safe_payload(payload: str | None, limit: int = 200) -> str:
    """格式化 NOTIFY payload 用于日志输出，避免过长内容刷屏。

    Args:
        payload: NOTIFY 原始载荷，可能为 None。
        limit: 日志中最多显示的字符数。

    Returns:
        适合写入日志的短字符串。
    """
    if payload is None:
        return "<null>"
    if len(payload) <= limit:
        return payload
    return payload[: limit - 3] + "..."
