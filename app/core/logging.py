"""Structured logging configuration.

Emits JSON lines when ``LOG_FORMAT=json`` (intended for production, where logs are
shipped to a collector) and a concise human-readable format otherwise (local dev).
Both honour ``LOG_LEVEL`` (default ``INFO``) and write to stdout.
"""

import datetime as dt
import json
import logging
import os
import sys
from typing import Any

# Attributes always present on a ``LogRecord``; everything else passed via the
# ``extra=`` kwarg is treated as structured context and included in JSON output.
_RESERVED_RECORD_ATTRS: frozenset[str] = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
        "message",
    }
)

# Libraries that are chatty at INFO; quieted so application logs stay readable.
_NOISY_LOGGERS: dict[str, int] = {
    "sqlalchemy.engine": logging.WARNING,
    "telethon": logging.WARNING,
    "httpx": logging.WARNING,
    "apscheduler.executors.default": logging.WARNING,
}

_CONSOLE_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_CONSOLE_DATEFMT = "%Y-%m-%d %H:%M:%S"


class JSONFormatter(logging.Formatter):
    """Render log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": dt.datetime.fromtimestamp(record.created, tz=dt.UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        for key, value in record.__dict__.items():
            if key not in _RESERVED_RECORD_ATTRS and not key.startswith("_"):
                payload[key] = value

        return json.dumps(payload, default=str)


def _resolve_level(level: str | int | None) -> int:
    """Coerce a level name or number (or ``None`` → env/default) into an int."""
    if level is None:
        level = os.getenv("LOG_LEVEL", "INFO")
    if isinstance(level, int):
        return level
    return logging.getLevelNamesMapping().get(level.upper(), logging.INFO)


def configure_logging(
    level: str | int | None = None,
    log_format: str | None = None,
) -> None:
    """Configure the root logger for the whole process.

    Args:
        level: Log level name or number. Defaults to ``LOG_LEVEL`` env var, then ``INFO``.
        log_format: ``"json"`` or ``"console"``. Defaults to ``LOG_FORMAT`` env var,
            then ``"console"``.
    """
    resolved_format = (log_format or os.getenv("LOG_FORMAT", "console")).strip().lower()
    resolved_level = _resolve_level(level)

    handler = logging.StreamHandler(sys.stdout)
    if resolved_format == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(logging.Formatter(fmt=_CONSOLE_FORMAT, datefmt=_CONSOLE_DATEFMT))

    root = logging.getLogger()
    for existing in root.handlers[:]:
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(resolved_level)

    for logger_name, logger_level in _NOISY_LOGGERS.items():
        logging.getLogger(logger_name).setLevel(logger_level)


def get_logger(name: str) -> logging.Logger:
    """Return a module-scoped logger by name."""
    return logging.getLogger(name)
