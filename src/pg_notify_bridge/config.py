"""从环境变量加载 PostgreSQL 与 Webhook 相关配置。

本模块负责解析、校验并封装运行所需的全部配置项，
供 listener 与 forwarder 在启动时使用。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any


class ConfigError(ValueError):
    """配置缺失或格式非法时抛出的异常。"""


@dataclass(frozen=True)
class Settings:
    """不可变的运行时配置快照，启动后不再修改。

    Attributes:
        pg_dsn: PostgreSQL 连接串（DSN / URL）。
        pg_channels: 需要 LISTEN 的 NOTIFY 频道名元组。
        webhook_url: 消息转发目标 HTTP 端点。
        webhook_timeout: 单次 Webhook HTTP 请求超时（秒）。
        webhook_max_retries: Webhook 失败后的最大重试次数。
        webhook_retry_backoff: 重试间隔基数（秒），第 n 次等待 n × backoff。
        webhook_headers: 转发请求使用的 HTTP 头。
        listen_timeout: pgnotify select 轮询超时（秒），也用于连接心跳。
        reconnect_delay: 数据库断连后，下次重连前的等待时间（秒）。
        log_level: 日志级别字符串，如 INFO、DEBUG。
        worker_threads: Webhook 异步投递线程池大小。
        bot_key:默认企业微信群机器人key，当notify中没有bot_key时使用。
        event_source: 默认事件源，如 "postgresql"、"kafka"、"rabbitmq"，当notify中没有event_source时使用。
        project: 默认项目名，如 "orders"、"inventory"，用于写入JIRA项目任务，当notify中没有project时使用。
        component: 默认组件名，如 "orders"、"inventory"，用于写入JIRA项目任务，当notify中没有component时使用。
    """

    pg_dsn: str
    pg_channels: tuple[str, ...]
    webhook_url: str
    webhook_timeout: float
    webhook_max_retries: int
    webhook_retry_backoff: float
    webhook_headers: dict[str, str]
    listen_timeout: float
    reconnect_delay: float
    log_level: str
    worker_threads: int
    bot_key: str
    event_source: str
    project: str
    component: str


def _require(name: str) -> str:
    """读取必填环境变量，缺失或为空时抛出 ConfigError。

    Args:
        name: 环境变量名。

    Returns:
        去除首尾空白后的非空字符串。
    """
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


def _parse_channels(raw: str) -> tuple[str, ...]:
    """将逗号分隔的频道字符串解析为元组。

    Args:
        raw: 如 ``"orders, inventory"`` 的环境变量原始值。

    Returns:
        去重空白后的频道名元组，至少包含一个元素。
    """
    channels = tuple(ch.strip() for ch in raw.split(",") if ch.strip())
    if not channels:
        raise ConfigError("PG_CHANNELS must contain at least one channel name")
    return channels


def _parse_headers(raw: str | None) -> dict[str, str]:
    """解析 WEBHOOK_HEADERS JSON 字符串为请求头字典。

    未配置时默认仅设置 ``Content-Type: application/json``。

    Args:
        raw: JSON 对象字符串，或 None / 空字符串。

    Returns:
        键值均为字符串的 HTTP 头字典。
    """
    if not raw or not raw.strip():
        return {"Content-Type": "application/json"}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"WEBHOOK_HEADERS must be valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ConfigError("WEBHOOK_HEADERS must be a JSON object")
    return {str(k): str(v) for k, v in parsed.items()}


def _parse_float(name: str, default: float) -> float:
    """读取浮点型环境变量，支持默认值与非负校验。

    Args:
        name: 环境变量名。
        default: 未设置或为空时使用的默认值。

    Returns:
        解析后的非负浮点数。
    """
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got: {raw!r}") from exc
    if value < 0:
        raise ConfigError(f"{name} must be >= 0, got: {value}")
    return value


def _parse_int(name: str, default: int) -> int:
    """读取整型环境变量，支持默认值与非负校验。

    Args:
        name: 环境变量名。
        default: 未设置或为空时使用的默认值。

    Returns:
        解析后的非负整数。
    """
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got: {raw!r}") from exc
    if value < 0:
        raise ConfigError(f"{name} must be >= 0, got: {value}")
    return value


def load_settings() -> Settings:
    """从当前进程环境变量构建 Settings 对象。

    必填项：PG_DSN、PG_CHANNELS、WEBHOOK_URL。
    其余项见 .env.example 中的默认值说明。

    Returns:
        校验通过的不可变配置对象。
    """
    return Settings(
        pg_dsn=_require("PG_DSN"),
        pg_channels=_parse_channels(_require("PG_CHANNELS")),
        webhook_url=_require("WEBHOOK_URL"),
        webhook_timeout=_parse_float("WEBHOOK_TIMEOUT", 30.0),
        webhook_max_retries=_parse_int("WEBHOOK_MAX_RETRIES", 3),
        webhook_retry_backoff=_parse_float("WEBHOOK_RETRY_BACKOFF", 1.0),
        webhook_headers=_parse_headers(os.getenv("WEBHOOK_HEADERS")),
        listen_timeout=_parse_float("LISTEN_TIMEOUT", 10.0),
        reconnect_delay=_parse_float("RECONNECT_DELAY", 5.0),
        log_level=os.getenv("LOG_LEVEL", "INFO").strip() or "INFO",
        # 至少保留 1 个 worker，避免线程池配置为 0 导致无法投递
        worker_threads=max(1, _parse_int("WORKER_THREADS", 4)),
        bot_key=os.getenv("BOT_KEY"),
        event_source=os.getenv("EVENT_SOURCE"),
        project=os.getenv("PROJECT"),
        component=os.getenv("COMPONENT"),
    )


def settings_summary(settings: Settings) -> dict[str, Any]:
    """生成可安全写入日志的配置摘要（不含数据库密码）。

    Args:
        settings: 已加载的运行时配置。

    Returns:
        适合 INFO 级别打印的字典，DSN 中凭证部分已脱敏。
    """
    return {
        "pg_dsn": _mask_dsn(settings.pg_dsn),
        "pg_channels": list(settings.pg_channels),
        "webhook_url": settings.webhook_url,
        "webhook_timeout": settings.webhook_timeout,
        "webhook_max_retries": settings.webhook_max_retries,
        "webhook_retry_backoff": settings.webhook_retry_backoff,
        "listen_timeout": settings.listen_timeout,
        "reconnect_delay": settings.reconnect_delay,
        "log_level": settings.log_level,
        "worker_threads": settings.worker_threads,
        "bot_key": settings.bot_key,
        "event_source": settings.event_source,
        "project": settings.project,
        "component": settings.component,
    }


def _mask_dsn(dsn: str) -> str:
    """对连接串中的用户名/密码部分做脱敏，便于日志输出。

    示例：``postgresql://user:secret@host/db`` → ``postgresql://***@host/db``

    Args:
        dsn: 原始 PostgreSQL 连接串。

    Returns:
        隐藏 ``@`` 之前凭证信息的连接串。
    """
    if "@" not in dsn:
        return dsn
    prefix, suffix = dsn.split("@", 1)
    if "://" in prefix:
        scheme, _rest = prefix.split("://", 1)
        return f"{scheme}://***@{suffix}"
    return f"***@{suffix}"
