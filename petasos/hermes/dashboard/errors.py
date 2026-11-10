"""Structured failures for the dashboard API.

A response never carries a traceback. The router logs the detail and returns
:func:`error_body`.
"""

from __future__ import annotations

from typing import Any

API_VERSION = 1


class ApiError(Exception):
    """One failure a person can act on.

    ``code`` is stable. ``message`` is the sentence the front end shows.
    ``path`` is a settings path when the failure is one value, otherwise None.
    ``status`` is the HTTP status the router uses.
    """

    def __init__(
        self,
        code: str,
        message: str,
        status: int = 400,
        path: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.path = path


def envelope(**payload: Any) -> dict[str, Any]:
    """A success body. ``version`` is always first so clients can branch on it."""
    body: dict[str, Any] = {"version": API_VERSION}
    body.update(payload)
    return body


def error_body(exc: ApiError) -> dict[str, Any]:
    """The error body. No exception text beyond ``message``."""
    return envelope(
        error={
            "code": exc.code,
            "message": exc.message,
            "path": exc.path,
        }
    )


def problems_of(errors: tuple[tuple[str, str], ...]) -> list[dict[str, str]]:
    """``ConfigError.errors`` as a list the front end can render."""
    return [{"path": path, "message": message} for path, message in errors]
