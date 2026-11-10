"""The doctor report. Checks and the two renderers share this data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

Status = Literal["ok", "warn", "fail", "info"]
EXIT_PROTECTED = 0
EXIT_WARNINGS = 1
EXIT_NOT_PROTECTED = 2


@dataclass(frozen=True, slots=True)
class Check:
    """One doctor line.

    ``status`` is ``ok``, ``warn``, ``fail``, or ``info``. ``info`` does not
    change the verdict. ``meaning`` says what the line implies. ``next_step``
    is the command or action that addresses it, and is empty when none is due.
    """

    id: str
    status: Status
    summary: str
    meaning: str = ""
    next_step: str = ""


@dataclass(frozen=True, slots=True)
class HermesView:
    """What this Python can see of Hermes. ``version`` is None when unknown."""

    status: Status
    summary: str
    meaning: str = ""
    next_step: str = ""
    version: str | None = None


@dataclass(frozen=True, slots=True)
class Report:
    """The doctor result for one profile directory.

    ``verdict`` is ``protected``, ``protected_with_warnings``, or
    ``not_protected``. ``exit_code`` is 0, 1, or 2 in that order.
    ``protected_paths`` is the full list. The default text uses
    ``paths_summary`` and leaves the list for verbose output and JSON.
    """

    home: Path
    home_reason: str
    checks: tuple[Check, ...]
    suggestions: tuple[str, ...]
    protected_paths: tuple[str, ...]
    paths_summary: str
    detail: Mapping[str, object]

    @property
    def verdict(self) -> str:
        """``protected``, ``protected_with_warnings``, or ``not_protected``."""
        if any(check.status == "fail" for check in self.checks):
            return "not_protected"
        if any(check.status == "warn" for check in self.checks):
            return "protected_with_warnings"
        return "protected"

    @property
    def exit_code(self) -> int:
        """0 protected, 1 warnings, 2 not protected."""
        if self.verdict == "protected":
            return EXIT_PROTECTED
        if self.verdict == "protected_with_warnings":
            return EXIT_WARNINGS
        return EXIT_NOT_PROTECTED
