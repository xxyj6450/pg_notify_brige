"""Load configuration from environment variables."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any


class ConfigError(ValueError):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Settings:
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


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


def _parse_channels(raw: str) -> tuple[str, ...]:
    channels = tuple(ch.strip() for ch in raw.split(",") if ch.strip())
    if not channels:
        raise ConfigError("PG_CHANNELS must contain at least one channel name")
    return channels


def _parse_headers(raw: str | None) -> dict[str, str]:
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
    """Build settings from the current process environment."""
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
        worker_threads=max(1, _parse_int("WORKER_THREADS", 4)),
    )


def settings_summary(settings: Settings) -> dict[str, Any]:
    """Return a log-safe summary without secrets."""
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
    }


def _mask_dsn(dsn: str) -> str:
    if "@" not in dsn:
        return dsn
    prefix, suffix = dsn.split("@", 1)
    if "://" in prefix:
        scheme, _rest = prefix.split("://", 1)
        return f"{scheme}://***@{suffix}"
    return f"***@{suffix}"
