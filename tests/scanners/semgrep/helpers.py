"""Assertions that narrow optional public result fields in Semgrep tests."""

from typing import TypeVar

T = TypeVar("T")


def require(value: T | None) -> T:
    """Provide require for the test fixture."""
    assert value is not None
    return value
