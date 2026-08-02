"""Structured JSON logging.

One-line JSON records on stdout: Cloud Run (and most log collectors) parse them
automatically, and the `severity` field maps to Cloud Logging levels.
"""

import json
import logging
import sys
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict = {
            "time": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "severity": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        extra = getattr(record, "extra_fields", None)
        if extra:
            entry.update(extra)
        return json.dumps(entry, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.handlers = [handler]
    # keep noisy third-party loggers at WARNING
    for name in ("httpx", "httpcore", "chromadb", "uvicorn.access"):
        logging.getLogger(name).setLevel(logging.WARNING)


def log_event(logger: logging.Logger, message: str, **fields) -> None:
    """Log a message with structured extra fields (rendered into the JSON record)."""
    logger.info(message, extra={"extra_fields": fields})
