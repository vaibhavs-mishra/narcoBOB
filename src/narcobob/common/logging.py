"""One logging setup for every process. Use `extra={...}` for structured fields."""

from __future__ import annotations

import logging

_STANDARD = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


class _KeyValueFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        extras = {k: v for k, v in record.__dict__.items() if k not in _STANDARD}
        if extras:
            line += " " + " ".join(f"{k}={v}" for k, v in extras.items())
        return line


def setup_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(_KeyValueFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
