from __future__ import annotations

import enum
import inspect
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal, Protocol, runtime_checkable

Direction = Literal["inbound", "outbound"]


class Severity(enum.Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


@dataclass(frozen=True)
class Position:
    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0:
            raise ValueError(f"Position.start must be >= 0, got {self.start}")
        if self.end < self.start:
            raise ValueError(f"Position.end ({self.end}) must be >= Position.start ({self.start})")


@dataclass(frozen=True)
class ScanFinding:
    rule_id: str
    finding_type: str
    severity: Severity
    confidence: float
    message: str
    scanner_name: str
    position: Position | None = None
    matched_text: str | None = None

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(
                f"ScanFinding.confidence must be in [0.0, 1.0], got {self.confidence}"
            )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "rule_id": self.rule_id,
            "finding_type": self.finding_type,
            "severity": self.severity.value,
            "confidence": self.confidence,
            "message": self.message,
            "scanner_name": self.scanner_name,
        }
        if self.position is not None:
            d["position"] = {"start": self.position.start, "end": self.position.end}
        else:
            d["position"] = None
        d["matched_text"] = self.matched_text
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScanFinding:
        pos = data.get("position")
        position = Position(**pos) if pos is not None else None
        return cls(
            rule_id=data["rule_id"],
            finding_type=data["finding_type"],
            severity=Severity(data["severity"]),
            confidence=data["confidence"],
            message=data["message"],
            scanner_name=data["scanner_name"],
            position=position,
            matched_text=data.get("matched_text"),
        )


@dataclass(frozen=True)
class ScanResult:
    scanner_name: str
    findings: tuple[ScanFinding, ...]
    duration_ms: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "scanner_name": self.scanner_name,
            "findings": [f.to_dict() for f in self.findings],
            "duration_ms": self.duration_ms,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScanResult:
        return cls(
            scanner_name=data["scanner_name"],
            findings=tuple(ScanFinding.from_dict(f) for f in data["findings"]),
            duration_ms=data.get("duration_ms", 0.0),
            error=data.get("error"),
        )


@runtime_checkable
class Scanner(Protocol):
    @property
    def name(self) -> str: ...

    async def scan(
        self,
        text: str,
        *,
        direction: Direction = "inbound",
        session_id: str | None = None,
    ) -> ScanResult: ...


def _validate_scanner(obj: Any) -> None:
    """Structural validation beyond @runtime_checkable isinstance check."""
    try:
        has_name = hasattr(obj, "name")
    except Exception as exc:
        raise TypeError(
            f"Scanner {type(obj).__name__!r}: accessing 'name' raised {type(exc).__name__}: {exc}"
        ) from exc
    if not has_name:
        raise TypeError(f"Scanner object {type(obj).__name__!r} missing 'name' attribute")

    scan = getattr(obj, "scan", None)
    if scan is None or not callable(scan):
        raise TypeError(f"Scanner object {type(obj).__name__!r} missing callable 'scan' method")

    if not inspect.iscoroutinefunction(scan):
        raise TypeError(f"Scanner {type(obj).__name__!r}.scan() must be async")

    try:
        sig = inspect.signature(scan)
    except (ValueError, TypeError) as exc:
        raise TypeError(
            f"Scanner {type(obj).__name__!r}.scan(): cannot introspect signature: {exc}"
        ) from exc

    params = sig.parameters
    has_var_keyword = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
    if not has_var_keyword:
        param_names = set(params.keys())
        for required in ("text", "direction", "session_id"):
            if required not in param_names:
                raise TypeError(
                    f"Scanner {type(obj).__name__!r}.scan() missing '{required}' parameter"
                )


@dataclass(frozen=True)
class NormalizedText:
    original: str
    normalized: str
    transformations_applied: tuple[str, ...]
    invisible_chars_stripped: int = 0
    confusables_normalized: bool = False
    rtl_overrides_detected: bool = False


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    timestamp: float
    session_id: str | None
    event_type: str
    payload: MappingProxyType[str, Any]
    sequence_number: int


@dataclass(frozen=True)
class Alert:
    alert_id: str
    timestamp: float
    rule_id: str
    severity: str
    session_id: str | None
    message: str
    context: MappingProxyType[str, Any]


@dataclass(frozen=True)
class PipelineResult:
    """Aggregate result from pipeline execution."""

    safe: bool
    findings: tuple[ScanFinding, ...]
    sanitized_content: str | None = None
    scanner_results: tuple[ScanResult, ...] = ()
    errors: tuple[str, ...] = ()
    escalation_tier: str | None = None
    session_score: float | None = None
    premium_features: MappingProxyType[str, str] | None = None

    def __post_init__(self) -> None:
        pf = self.premium_features
        if pf is not None and not isinstance(pf, MappingProxyType):
            object.__setattr__(self, "premium_features", MappingProxyType(dict(pf)))
