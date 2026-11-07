"""Source-free, immutable coverage metadata shared by scanner results."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

CoverageStatus = Literal["complete", "no_targets", "unsupported", "partial", "error"]
Projection = Literal["raw", "json_string", "numbered_lines", "search_rows", "dedented"]
_STATUSES = frozenset({"complete", "no_targets", "unsupported", "partial", "error"})
_PROJECTIONS = frozenset({"raw", "json_string", "numbered_lines", "search_rows", "dedented"})
_REASON = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")


def _count(value: int, name: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")


@dataclass(frozen=True)
class CoverageSpan:
    """End-exclusive original character interval, never a source excerpt."""

    start: int
    end: int
    language: str | None
    status: CoverageStatus
    projection: Projection = "raw"

    def __post_init__(self) -> None:
        _count(self.start, "start")
        _count(self.end, "end")
        if self.end < self.start:
            raise ValueError("coverage span is reversed")
        if self.language not in (None, "python", "javascript", "typescript"):
            raise ValueError("unknown coverage language")
        if self.status not in _STATUSES or self.projection not in _PROJECTIONS:
            raise ValueError("unknown coverage status or projection")

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "language": self.language,
            "status": self.status,
            "projection": self.projection,
        }


@dataclass(frozen=True)
class ScanCoverage:
    """Coverage of supplied text; complete does not claim unsupported languages."""

    status: CoverageStatus
    total_chars: int
    examined_chars: int
    target_count: int
    completed_target_count: int
    spans: tuple[CoverageSpan, ...] = ()
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in _STATUSES:
            raise ValueError("unknown coverage status")
        for name in ("total_chars", "examined_chars", "target_count", "completed_target_count"):
            _count(getattr(self, name), name)
        if self.examined_chars > self.total_chars:
            raise ValueError("examined characters exceed input")
        if self.completed_target_count > self.target_count or self.target_count > 16:
            raise ValueError("invalid coverage target counts")
        spans, reasons = tuple(self.spans), tuple(self.reasons)
        if len(spans) > 17 or len(reasons) > 32:
            raise ValueError("coverage metadata exceeds bounds")
        if any(not isinstance(s, CoverageSpan) or s.end > self.total_chars for s in spans):
            raise ValueError("coverage span exceeds input")
        if any(not isinstance(r, str) or _REASON.fullmatch(r) is None for r in reasons):
            raise ValueError("coverage reasons must be fixed identifiers")
        object.__setattr__(self, "spans", spans)
        object.__setattr__(self, "reasons", reasons)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "total_chars": self.total_chars,
            "examined_chars": self.examined_chars,
            "target_count": self.target_count,
            "completed_target_count": self.completed_target_count,
            "spans": [s.to_dict() for s in self.spans],
            "reasons": list(self.reasons),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScanCoverage:
        return cls(
            status=data["status"],
            total_chars=data["total_chars"],
            examined_chars=data["examined_chars"],
            target_count=data["target_count"],
            completed_target_count=data["completed_target_count"],
            spans=tuple(CoverageSpan(**s) for s in data.get("spans", ())),
            reasons=tuple(data.get("reasons", ())),
        )
