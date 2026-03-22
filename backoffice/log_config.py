"""Structured logging configuration for the backoffice package.

All log output goes to stderr. Stdout is reserved for data output
(JSON, shell-export) so pipes and redirects work cleanly.
"""
import json
import logging
import sys
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def setup_logging(*, verbose: bool = False, json_output: bool = False) -> None:
    """Configure the backoffice logger. Call once at entry point."""
    root = logging.getLogger("backoffice")

    # Remove existing handlers to avoid duplicates on repeated calls
    root.handlers.clear()

    level = logging.DEBUG if verbose else logging.INFO
    root.setLevel(level)

    handler = logging.StreamHandler(sys.stderr)
    if json_output:
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        ))

    root.addHandler(handler)
