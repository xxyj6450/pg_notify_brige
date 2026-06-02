"""PostgreSQL NOTIFY listener built on pgnotify."""

from __future__ import annotations

import logging
import signal
import time

import psycopg2

from .config import Settings
from .forwarder import WebhookForwarder

logger = logging.getLogger(__name__)

SIGNALS_TO_HANDLE = [signal.SIGINT, signal.SIGTERM]


def _load_pgnotify():
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
    """Listen for NOTIFY events and forward them to a webhook."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._forwarder = WebhookForwarder(settings)
        self._stop_requested = False

    def run(self) -> None:
        logger.info(
            "Starting listener | channels=%s",
            ", ".join(self._settings.pg_channels),
        )
        while not self._stop_requested:
            try:
                self._listen_once()
            except RuntimeError:
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
        self._stop_requested = True

    def close(self) -> None:
        self._forwarder.close()

    def _listen_once(self) -> None:
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
                    sig = signal.Signals(event)
                    logger.info("Received %s, shutting down gracefully", sig.name)
                    self._stop_requested = True
                    break

                if event is None:
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
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
        except psycopg2.Error as exc:
            logger.warning("Connection health check failed: %s", exc)
            raise psycopg2.OperationalError(str(exc)) from exc


def _safe_payload(payload: str | None, limit: int = 200) -> str:
    if payload is None:
        return "<null>"
    if len(payload) <= limit:
        return payload
    return payload[: limit - 3] + "..."
