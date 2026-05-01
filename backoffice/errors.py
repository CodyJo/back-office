"""Production error envelope.

Internal exceptions become structured ``{error, code}`` JSON for
HTTP clients. Tracebacks are logged but never returned in responses.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def safe_error_response(code: int, error: str, *, exc: BaseException | None = None,
                        **extra) -> tuple[int, dict]:
    """Return a (status_code, body) tuple suitable for an HTTP error.

    The body never includes ``str(exc)`` for 5xx responses — that
    would leak implementation detail to clients. For 4xx responses
    a brief detail string is included if provided. Always logs the
    full exception when one is supplied.
    """
    body: dict = {"error": error}
    if extra:
        body.update(extra)
    if exc is not None:
        logger.exception("error response %s: %s", code, error)
        if 400 <= code < 500 and not extra.get("detail"):
            # 4xx errors may include the exception text; it's almost
            # always useful and almost never sensitive.
            body["detail"] = str(exc)
        # 5xx never echoes the exception.
    return code, body
