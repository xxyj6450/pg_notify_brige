"""Asynchronous webhook forwarding with retries."""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from .config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NotificationPayload:
    channel: str
    payload: str | None
    pid: int
    received_at: str

    @classmethod
    def from_notify(cls, notify: Any) -> NotificationPayload:
        return cls(
            channel=notify.channel,
            payload=notify.payload,
            pid=notify.pid,
            received_at=datetime.now(timezone.utc).isoformat(),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class WebhookForwarder:
    """Submit webhook deliveries to a background thread pool."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._executor = ThreadPoolExecutor(
            max_workers=settings.worker_threads,
            thread_name_prefix="webhook",
        )
        self._client = httpx.Client(
            timeout=settings.webhook_timeout,
            follow_redirects=True,
        )
        self._pending: set[Future[None]] = set()

    def submit(self, notify: Any) -> None:
        message = NotificationPayload.from_notify(notify)
        future = self._executor.submit(self._deliver, message)
        self._pending.add(future)
        future.add_done_callback(self._on_done)

    def wait_for_pending(self, timeout: float | None = None) -> None:
        pending = list(self._pending)
        for future in pending:
            try:
                future.result(timeout=timeout)
            except Exception:
                logger.exception("Unexpected error while waiting for webhook delivery")

    def close(self) -> None:
        self.wait_for_pending(timeout=self._settings.webhook_timeout * 2)
        self._executor.shutdown(wait=True, cancel_futures=False)
        self._client.close()

    def _on_done(self, future: Future[None]) -> None:
        self._pending.discard(future)
        try:
            future.result()
        except Exception:
            logger.exception("Webhook delivery task failed unexpectedly")

    def _deliver(self, message: NotificationPayload) -> None:
        body = json.dumps(message.to_dict(), ensure_ascii=False)
        settings = self._settings
        attempt = 0
        last_error: Exception | None = None

        while attempt <= settings.webhook_max_retries:
            attempt += 1
            try:
                response = self._client.post(
                    settings.webhook_url,
                    content=body,
                    headers=settings.webhook_headers,
                )
                response.raise_for_status()
                logger.info(
                    "Webhook delivered | channel=%s | pid=%s | status=%s | attempt=%s",
                    message.channel,
                    message.pid,
                    response.status_code,
                    attempt,
                )
                return
            except httpx.TimeoutException as exc:
                last_error = exc
                logger.warning(
                    "Webhook timeout | channel=%s | attempt=%s/%s | error=%s",
                    message.channel,
                    attempt,
                    settings.webhook_max_retries + 1,
                    exc,
                )
            except httpx.HTTPStatusError as exc:
                last_error = exc
                logger.warning(
                    "Webhook HTTP error | channel=%s | status=%s | attempt=%s/%s | body=%s",
                    message.channel,
                    exc.response.status_code,
                    attempt,
                    settings.webhook_max_retries + 1,
                    _truncate(exc.response.text),
                )
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning(
                    "Webhook request failed | channel=%s | attempt=%s/%s | error=%s",
                    message.channel,
                    attempt,
                    settings.webhook_max_retries + 1,
                    exc,
                )

            if attempt <= settings.webhook_max_retries:
                delay = settings.webhook_retry_backoff * attempt
                logger.info(
                    "Retrying webhook in %.1fs | channel=%s",
                    delay,
                    message.channel,
                )
                time.sleep(delay)

        logger.error(
            "Webhook delivery exhausted retries | channel=%s | pid=%s | last_error=%s",
            message.channel,
            message.pid,
            last_error,
        )


def _truncate(text: str, limit: int = 200) -> str:
    text = text.replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."
