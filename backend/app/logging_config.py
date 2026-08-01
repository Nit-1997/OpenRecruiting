import logging
import sys
import json
import time
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)


STANDARD_ATTRS = frozenset({
    "name", "msg", "args", "created", "relativeCreated", "exc_info",
    "exc_text", "stack_info", "lineno", "funcName", "pathname", "filename",
    "module", "levelno", "levelname", "msecs", "thread", "threadName",
    "process", "processName", "message", "taskName",
})


class JsonFormatter(logging.Formatter):
    def format(self, record):
        record.message = record.getMessage()
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.message,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "service": "backend",
        }

        rid = request_id_var.get()
        if rid:
            log_entry["request_id"] = rid

        cid = correlation_id_var.get()
        if cid:
            log_entry["correlation_id"] = cid

        for key, val in record.__dict__.items():
            if key not in STANDARD_ATTRS and key not in log_entry:
                log_entry[key] = val

        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, default=str)


class ConsoleFormatter(logging.Formatter):
    """Dev-mode formatter. Renders the same structured fields the JSON
    formatter exposes (method, path, status_code, duration_ms, cr_id,
    operation, error, ...) so triaging via `docker logs` doesn't require
    flipping to ENV=production.

    The JsonFormatter still owns prod logs; this only changes what hits
    a TTY developer console.
    """

    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "RESET": "\033[0m"
    }

    # Keys we surface inline on every line. Anything else in record.__dict__
    # remains accessible via JsonFormatter but is dropped from the console
    # output to keep lines scannable.
    _INLINE_KEYS = (
        "event",
        "operation",
        "method",
        "path",
        "status",
        "status_code",
        "duration_ms",
        "table",
        "cr_id",
        "bot_id",
        "candidate_round_id",
        "requisition_id",
        "round_id",
        "error",
        "error_type",
    )

    def format(self, record):
        color = self.COLORS.get(record.levelname, "")
        reset = self.COLORS["RESET"]
        timestamp = datetime.now(timezone.utc).strftime('%H:%M:%S')

        prefix_extras = ""
        rid = request_id_var.get()
        cid = correlation_id_var.get()
        if rid:
            prefix_extras += f" req={rid[:8]}"
        if cid:
            prefix_extras += f" cor={cid}"

        # Render whitelisted structured fields after the message.
        rec_dict = record.__dict__
        inline_parts = []
        for key in self._INLINE_KEYS:
            if key in rec_dict and rec_dict[key] not in (None, ""):
                value = rec_dict[key]
                if isinstance(value, str) and len(value) > 200:
                    value = value[:197] + "..."
                inline_parts.append(f"{key}={value}")
        inline = (" " + " ".join(inline_parts)) if inline_parts else ""

        return (
            f"{timestamp} {color}[{record.levelname:5}]{reset} "
            f"[{record.name}]{prefix_extras} {record.getMessage()}{inline}"
        )


def setup_logging():
    from app.config import get_settings
    settings = get_settings()

    is_prod = settings.ENV.lower() == "production"

    if settings.LOG_LEVEL:
        level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    else:
        level = logging.INFO if is_prod else logging.DEBUG

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if is_prod else ConsoleFormatter())

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = [handler]

    for lib in ["httpx", "httpcore", "uvicorn.access"]:
        logging.getLogger(lib).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


@asynccontextmanager
async def log_operation(
    logger: logging.Logger,
    op: str,
    **fields: Any,
):
    """Bookmark a logical operation with start/end log lines so the chain
    of work triggered by one inbound request is grep-able.

    Emits:
      - `<op>.start` at INFO with the kwargs as structured fields
      - `<op>.ok` at INFO on success with `duration_ms`
      - `<op>.error` at ERROR on exception with `duration_ms` and `error`

    All three carry the ambient `request_id` / `correlation_id` via the
    JsonFormatter — no need to pass them explicitly.

    Usage:
        async with log_operation(logger, "schedule_round", cr_id=str(cr_id)):
            ...real work...

    Keep the field count small — these lines land in production logs once
    per operation. Use it on multi-step flows and external API boundaries;
    not for every helper.
    """
    start = time.monotonic()
    base_extra = {"event": f"{op}.start", "operation": op, **fields}
    logger.info(f"{op}.start", extra=base_extra)
    try:
        yield
    except Exception as err:
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.error(
            f"{op}.error",
            extra={
                "event": f"{op}.error",
                "operation": op,
                "duration_ms": duration_ms,
                "error": str(err),
                "error_type": type(err).__name__,
                **fields,
            },
            exc_info=True,
        )
        raise
    else:
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            f"{op}.ok",
            extra={
                "event": f"{op}.ok",
                "operation": op,
                "duration_ms": duration_ms,
                **fields,
            },
        )
