"""Webhook 异步转发与重试逻辑。

监听循环在收到 NOTIFY 后立即 submit 任务到线程池，
由 worker 负责 HTTP POST，避免阻塞 PostgreSQL 长连接监听。
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from urllib.parse import quote
from .config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NotificationPayload:
    """转发到 Webhook 的 JSON 消息体结构。

    Attributes:
        channel: NOTIFY 频道名。
        payload: NOTIFY 携带的字符串载荷，可能为 None。
        pid: 发送 NOTIFY 的 PostgreSQL 后端进程 ID。
        received_at: 本服务收到通知的 UTC 时间（ISO 8601）。
    """

    channel: str
    payload: str | None
    pid: int
    received_at: str

    @classmethod
    def from_notify(cls, notify: Any) -> NotificationPayload:
        """从 pgnotify 返回的通知对象构造载荷。

        Args:
            notify: 具有 channel、payload、pid 属性的 NOTIFY 对象。

        Returns:
            用于序列化并 POST 的不可变载荷。
        """
        return cls(
            channel=notify.channel,
            payload= json.loads(notify.payload),
            pid=notify.pid,
            received_at=datetime.now(timezone.utc).isoformat(),
        )

    def to_dict(self) -> dict[str, Any]:
        """转换为可 JSON 序列化的字典。"""
        return asdict(self)


class WebhookForwarder:
    """将 NOTIFY 消息异步投递到 Webhook 的后台转发器。

    使用 ThreadPoolExecutor 在独立线程中执行 HTTP 请求，
    主监听线程只需调用 submit()，不会被网络 I/O 阻塞。
    """

    def __init__(self, settings: Settings) -> None:
        """初始化线程池与 HTTP 客户端。

        Args:
            settings: 包含 webhook_url、超时、重试等参数的配置。
        """
        self._settings = settings
        self._executor = ThreadPoolExecutor(
            max_workers=settings.worker_threads,
            thread_name_prefix="webhook",
        )
        self._client = httpx.Client(
            timeout=settings.webhook_timeout,
            follow_redirects=True,
        )
        # 跟踪尚未完成的投递任务，便于优雅关闭时等待
        self._pending: set[Future[None]] = set()

    def submit(self, notify: Any) -> None:
        """提交一条 NOTIFY 到后台线程异步投递。

        Args:
            notify: pgnotify yield 的原始通知对象。
        """
        message = NotificationPayload.from_notify(notify)
        future = self._executor.submit(self._deliver, message)
        self._pending.add(future)
        future.add_done_callback(self._on_done)

    def wait_for_pending(self, timeout: float | None = None) -> None:
        """阻塞等待所有在途 Webhook 任务完成（或超时）。

        Args:
            timeout: 每个 future 的最大等待秒数；None 表示一直等待。
        """
        pending = list(self._pending)
        for future in pending:
            try:
                future.result(timeout=timeout)
            except Exception:
                logger.exception("Unexpected error while waiting for webhook delivery")

    def close(self) -> None:
        """关闭转发器：等待在途任务、停止线程池、释放 HTTP 连接。"""
        # 给予足够时间让最后一次重试完成
        self.wait_for_pending(timeout=self._settings.webhook_timeout * 2)
        self._executor.shutdown(wait=True, cancel_futures=False)
        self._client.close()

    def _on_done(self, future: Future[None]) -> None:
        """Future 完成回调：从 pending 集合移除并记录未捕获异常。"""
        self._pending.discard(future)
        try:
            future.result()
        except Exception:
            logger.exception("Webhook delivery task failed unexpectedly")
    def _safe_quote(self, value):
        if isinstance(value, bytes):
            value = value.decode('utf-8')
        return quote(str(value))  # 确保转为字符串

    def _deliver(self, message: NotificationPayload) -> None:
        """在 worker 线程中执行 HTTP POST，失败时按配置重试。

        重试策略：最多 webhook_max_retries 次额外尝试，
        第 n 次重试前等待 n × webhook_retry_backoff 秒。

        Args:
            message: 已封装好的 Webhook JSON 载荷。
        """
        body = json.dumps(message.to_dict(), ensure_ascii=False)
        settings = self._settings
        attempt = 0
        last_error: Exception | None = None
        # 从payload中获取event_source、bot_key、project、component、severity、event_id
        payload = json.loads(message.payload)
        # 优先从payload中获取，如果没有则从channel中获取，如果没有则从settings中获取
        event_source = payload.get("event_source") or message.channel or settings.event_source or ""
        # 优先从payload中获取，如果没有则从settings中获取   
        bot_key = payload.get("bot_key") or settings.bot_key or ""
        # 优先从payload中获取，如果没有则从settings中获取
        project = payload.get("project") or settings.project or ""
        # 优先从payload中获取，如果没有则从settings中获取
        component = payload.get("component") or settings.component or ""
        # 优先从payload中获取，如果没有则从settings中获取
        severity = payload.get("severity") or "信息"
        # 优先从payload中获取，如果没有则从settings中获取
        event_id = payload.get("event_id") or ""
        # 如果bot_key不为空，则redirect为1，否则为0
        redirect= "1" if bot_key not in("",None) else "0"
        # 总尝试次数 = 1 次初始请求 + webhook_max_retries 次重试
        while attempt <= settings.webhook_max_retries:
            attempt += 1
            try:
                url=settings.webhook_url + "?source=" + self._safe_quote(event_source) + "&botkey=" + self._safe_quote(bot_key) + "&project=" + self._safe_quote(project) + "&component=" + self._safe_quote(component) + "&severity=" + self._safe_quote(severity) + "&redirect=" + self._safe_quote(redirect) + "&event_id=" + self._safe_quote(event_id)
                logger.info("Webhook url: %s", url)
                logger.info("Webhook body: %s", body)
                logger.info("Webhook headers: %s", settings.webhook_headers)
                response = self._client.post(
                    url,
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
                # 4xx/5xx 响应：记录状态码与响应体摘要
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
                # 连接失败、DNS 错误等网络层问题
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
    """截断过长文本，避免错误响应体刷屏日志。

    Args:
        text: 原始字符串（如 HTTP 响应 body）。
        limit: 最大保留字符数。

    Returns:
        去除换行并截断后的单行文本。
    """
    text = text.replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."
