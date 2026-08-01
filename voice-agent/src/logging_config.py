import logging
import sys
import json
from datetime import datetime, timezone

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
            "service": "voice-agent",
        }

        for key, val in record.__dict__.items():
            if key not in STANDARD_ATTRS and key not in log_entry:
                log_entry[key] = val

        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, default=str)


def setup_logging():
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers = [handler]
    for lib in ["httpx", "httpcore", "aiortc", "aioice"]:
        logging.getLogger(lib).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
