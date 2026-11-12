"""Expose immutable findings and results with validated scanner contracts."""

from __future__ import annotations

import enum
import inspect
from collections.abc import Mapping  # noqa: TC003 - resolved by typing.get_type_hints at runtime
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal, Protocol, runtime_checkable

from petasos.coverage import CoverageSpan as CoverageSpan
from petasos.coverage import ScanCoverage as ScanCoverage

Direction = Literal["inbound", "outbound"]

# See docs/architecture/rationale.md, "Finding suppression floors".
FloorScope = Literal["all", "inbound"]

# Availability causes distinguish missing prerequisites from terminal load failure.
AvailabilityCause = Literal["absent", "load_failed"]
AVAILABILITY_CAUSE_ABSENT: AvailabilityCause = "absent"
AVAILABILITY_CAUSE_LOAD_FAILED: AvailabilityCause = "load_failed"


class Severity(enum.Enum):
    """How severe a finding is.

    ``rank`` runs from info (0) to critical (4). A higher rank is more severe.
    Member order is not rank order: serialization and ``list(Severity)`` follow
    the declaration order below.
    """

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"

    @property
    def rank(self) -> int:
        """This member's place on the severity scale.

        Info is 0 and critical is 4. A higher rank is more severe.
        """
        return _RANK_BY_VALUE[self.value]


# Least severe first. Rank is the index into this tuple, not the member's
# declaration order.
_SEVERITY_ORDER: tuple[Severity, ...] = (
    Severity.INFO,
    Severity.LOW,
    Severity.MEDIUM,
    Severity.HIGH,
    Severity.CRITICAL,
)
if len(_SEVERITY_ORDER) != len(set(_SEVERITY_ORDER)) or set(_SEVERITY_ORDER) != set(Severity):
    raise RuntimeError("severity order must list each Severity member once")

_RANK_BY_VALUE: Mapping[str, int] = MappingProxyType(
    {member.value: index for index, member in enumerate(_SEVERITY_ORDER)}
)
# Strictly below info. Two values that are not known severities compare equal,
# and both lose to every known severity.
_UNKNOWN_BELOW = -1
# Strictly above critical. One past the last index, so an unknown value wins a
# "higher is more severe" comparison against every member.
_UNKNOWN_ABOVE = len(_SEVERITY_ORDER)


def severity_rank(value: object, *, unknown_wins: bool = False) -> int:
    """Rank of a severity. Info is 0 and critical is 4; higher is more severe.

    ``value`` may be a ``Severity`` or its value string. A value that is not a
    known severity ranks below info, unless ``unknown_wins`` is set, in which
    case it ranks above critical.
    """
    if isinstance(value, Severity):
        return value.rank
    if isinstance(value, str):
        found = _RANK_BY_VALUE.get(value)
        if found is not None:
            return found
    return _UNKNOWN_ABOVE if unknown_wins else _UNKNOWN_BELOW


def at_least(severity: object, threshold: Severity) -> bool:
    """True when ``severity`` is ``threshold`` or more severe.

    A value that is not a known severity is not at least any threshold.
    """
    return severity_rank(severity) >= threshold.rank


@dataclass(frozen=True)
class Position:
    """Hold a nonnegative, end-exclusive interval with end at least start."""

    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0:
            raise ValueError(f"Position.start must be >= 0, got {self.start}")
        if self.end < self.start:
            raise ValueError(f"Position.end ({self.end}) must be >= Position.start ({self.start})")


@dataclass(frozen=True)
class ScanFinding:
    """Hold immutable finding fields with validated confidence and position basis."""

    rule_id: str
    finding_type: str
    severity: Severity
    confidence: float
    message: str
    scanner_name: str
    position: Position | None = None
    matched_text: str | None = None
    position_basis: Literal["legacy", "original"] = "legacy"

    def __post_init__(self) -> None:
        if self.position_basis not in ("legacy", "original"):
            raise ValueError("unknown position basis")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(
                f"ScanFinding.confidence must be in [0.0, 1.0], got {self.confidence}"
            )

    def to_dict(self) -> dict[str, Any]:
        """Return the finding as JSON-serialisable data."""
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
        if self.position_basis != "legacy":
            d["position_basis"] = self.position_basis
        d["matched_text"] = self.matched_text
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScanFinding:
        """Construct and validate a finding from serialized data."""
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
            position_basis=data.get("position_basis", "legacy"),
        )


@dataclass(frozen=True)
class ScanResult:
    """Hold one scanner outcome with immutable findings and optional coverage."""

    scanner_name: str
    findings: tuple[ScanFinding, ...]
    duration_ms: float = 0.0
    error: str | None = None
    coverage: ScanCoverage | None = None

    def __post_init__(self) -> None:
        if self.coverage is not None and not isinstance(self.coverage, ScanCoverage):
            raise ValueError("coverage must be ScanCoverage")

    def to_dict(self) -> dict[str, Any]:
        """Return the scanner outcome as JSON-serialisable data."""
        result: dict[str, Any] = {
            "scanner_name": self.scanner_name,
            "findings": [f.to_dict() for f in self.findings],
            "duration_ms": self.duration_ms,
            "error": self.error,
        }

        if self.coverage is not None:
            result["coverage"] = self.coverage.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScanResult:
        """Construct and validate a scanner outcome from serialized data."""
        return cls(
            scanner_name=data["scanner_name"],
            findings=tuple(ScanFinding.from_dict(f) for f in data["findings"]),
            duration_ms=data.get("duration_ms", 0.0),
            error=data.get("error"),
            coverage=(
                ScanCoverage.from_dict(data["coverage"])
                if data.get("coverage") is not None
                else None
            ),
        )


@runtime_checkable
class Scanner(Protocol):
    """Require a stable name and an asynchronous scan result."""

    @property
    def name(self) -> str:
        """Return the stable scanner name used in results and health reports."""
        ...

    async def scan(
        self,
        text: str,
        *,
        direction: Direction = "inbound",
        session_id: str | None = None,
    ) -> ScanResult:
        """Inspect text asynchronously and return a scanner result."""
        ...


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
    param_names = set(params.keys())
    has_var_positional = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params.values())
    has_var_keyword = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())

    if "text" not in param_names and not has_var_positional:
        raise TypeError(f"Scanner {type(obj).__name__!r}.scan() missing 'text' parameter")

    if not has_var_keyword:
        for required in ("direction", "session_id"):
            if required not in param_names:
                raise TypeError(
                    f"Scanner {type(obj).__name__!r}.scan() missing '{required}' parameter"
                )


@dataclass(frozen=True)
class NormalizedText:
    """Retain original and canonical text plus independent match-only views."""

    original: str
    normalized: str
    transformations_applied: tuple[str, ...]
    invisible_chars_stripped: int = 0
    confusables_normalized: bool = False
    rtl_overrides_detected: bool = False
    # Leet match views preserve canonical offsets and never alter canonical text.
    leet_views: tuple[str, ...] = ()
    # Separator views can change length and therefore cannot supply canonical offsets.
    separator_views: tuple[str, ...] = ()
    # See docs/architecture/rationale.md, "Normalization views".
    composed_views: tuple[str, ...] = ()


@dataclass(frozen=True)
class AuditEvent:
    """Hold a sequenced audit record with immutable payload data."""

    event_id: str
    timestamp: float
    session_id: str | None
    event_type: str
    payload: MappingProxyType[str, Any]
    sequence_number: int

    def to_dict(self) -> dict[str, Any]:
        """Return the audit record as JSON-serialisable data."""
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "event_type": self.event_type,
            "payload": _deep_unproxy(self.payload),
            "sequence_number": self.sequence_number,
        }


@dataclass(frozen=True)
class Alert:
    """Hold an alert with immutable context data."""

    alert_id: str
    timestamp: float
    rule_id: str
    severity: str
    session_id: str | None
    message: str
    context: MappingProxyType[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Return the alert as JSON-serialisable data."""
        return {
            "alert_id": self.alert_id,
            "timestamp": self.timestamp,
            "rule_id": self.rule_id,
            "severity": self.severity,
            "session_id": self.session_id,
            "message": self.message,
            "context": _deep_unproxy(self.context),
        }


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
    feature_status: MappingProxyType[str, str] | None = None
    backend_coverage: Mapping[str, ScanCoverage] | None = None

    def __post_init__(self) -> None:
        if self.backend_coverage is not None:
            if any(
                not isinstance(k, str) or not isinstance(v, ScanCoverage)
                for k, v in self.backend_coverage.items()
            ):
                raise ValueError("backend coverage must map names to ScanCoverage")
            object.__setattr__(
                self, "backend_coverage", MappingProxyType(dict(self.backend_coverage))
            )
        pf = self.feature_status
        if pf is not None and not isinstance(pf, MappingProxyType):
            object.__setattr__(self, "feature_status", MappingProxyType(dict(pf)))

    def to_dict(self) -> dict[str, Any]:
        """Return the inspection result as JSON-serialisable data."""
        result: dict[str, Any] = {
            "safe": self.safe,
            "findings": [f.to_dict() for f in self.findings],
            "sanitized_content": self.sanitized_content,
            "scanner_results": [sr.to_dict() for sr in self.scanner_results],
            "errors": list(self.errors),
            "escalation_tier": self.escalation_tier,
            "session_score": self.session_score,
            "feature_status": (
                dict(self.feature_status) if self.feature_status is not None else None
            ),
        }
        if self.backend_coverage is not None:
            result["backend_coverage"] = {k: v.to_dict() for k, v in self.backend_coverage.items()}
        return result


def _deep_unproxy(obj: Any) -> Any:
    """Recursively convert MappingProxyType to dict for JSON serialization."""
    if isinstance(obj, MappingProxyType):
        return {k: _deep_unproxy(v) for k, v in obj.items()}
    if isinstance(obj, dict):
        return {k: _deep_unproxy(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_deep_unproxy(item) for item in obj]
    if isinstance(obj, Severity):
        return obj.value
    return obj


# Scanner error vocabulary is shared with the pipeline circuit breaker.
_TIMEOUT_ERROR_PREFIX = "ScannerTimeout"
