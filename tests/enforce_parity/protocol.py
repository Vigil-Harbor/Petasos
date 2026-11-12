"""Specify clean-process scenario replay without changing recorded outcomes."""

from __future__ import annotations

from typing import Any, Protocol


class EnforcementAdapter(Protocol):
    """Provide Enforcement Adapter test data.

    See docs/architecture/rationale.md, "Test timing and backend qualification"."""

    def replay(self, scenario: dict[str, Any]) -> list[dict[str, Any]]:
        """Run ``scenario`` from a clean process and return its outcomes."""
        ...
