"""Health, flat reconfigure, and the reads the console was the only caller of.

These assertions lived in the console handler tests and the reference plugin.
They call the library directly.
"""

from __future__ import annotations

import time
from types import MappingProxyType
from typing import Any, cast

from petasos.config.secrets import Secrets
from petasos.config.sections import PetasosConfig
from petasos.model import (
    Alert,
    AuditEvent,
    ScanResult,
    Severity,
    severity_rank,
)
from petasos.pipeline import Pipeline
from petasos.scanners.minimal import MinimalScanner
from petasos.scanners.semgrep import SemgrepScanner
from petasos.session.guard import ToolCallGuard
from petasos.session.ingest import scan_ingestion_result


class _StubScanner:
    def __init__(self, name: str, *, error: str | None = None) -> None:
        self._name = name
        self._error = error

    @property
    def name(self) -> str:
        return self._name

    async def scan(
        self,
        text: str,
        *,
        direction: str = "inbound",
        session_id: str | None = None,
    ) -> ScanResult:
        return ScanResult(
            scanner_name=self._name,
            findings=(),
            duration_ms=1.0,
            error=self._error,
        )


class _UnavailableScanner(_StubScanner):
    def availability(self) -> tuple[bool, str | None]:
        return (False, "test backend missing")


class _AvailableScanner(_StubScanner):
    def availability(self) -> tuple[bool, str | None]:
        return (True, None)


class _LoadFailedScanner(_StubScanner):
    def __init__(self, name: str, *, reason: str) -> None:
        super().__init__(name)
        self._reason = reason

    def availability(self) -> tuple[bool, str | None, str | None]:
        return (False, self._reason, "load_failed")


class _AbsentScanner(_StubScanner):
    def availability(self) -> tuple[bool, str | None, str | None]:
        return (False, "backend not installed", "absent")


class _BoomParams:
    def values(self) -> Any:
        raise RuntimeError("classifier broke")


def _row(health: list[dict[str, Any]], name: str) -> dict[str, Any]:
    return next(item for item in health if item["name"] == name)


def test_scanner_health_reports_each_status() -> None:
    pipe = Pipeline(scanners=[MinimalScanner()], config=PetasosConfig(fail_mode="open"))
    health = pipe.scanner_health()
    minimal = _row(health, "minimal")
    assert minimal["status"] == "healthy"
    assert "last_error" in minimal
    assert all("last_error" in entry for entry in health)

    missing = _UnavailableScanner("test_ml")
    unavailable = Pipeline(
        scanners=[MinimalScanner(), missing],
        config=PetasosConfig(fail_mode="open"),
    )
    unavailable._breaker_open_until["test_ml"] = time.monotonic() + 999
    row = _row(unavailable.scanner_health(), "test_ml")
    assert row["status"] == "unavailable"
    assert row["last_error"] == "test backend missing"

    crashed = _LoadFailedScanner("test_ml", reason="")
    errored = Pipeline(
        scanners=[MinimalScanner(), crashed],
        config=PetasosConfig(fail_mode="open"),
    )
    errored._last_scan_errors["test_ml"] = "stale"
    row = _row(errored.scanner_health(), "test_ml")
    assert row["status"] == "error"
    assert row["last_error"] == ""

    absent = Pipeline(
        scanners=[MinimalScanner(), _AbsentScanner("test_ml")],
        config=PetasosConfig(fail_mode="open"),
    )
    assert _row(absent.scanner_health(), "test_ml")["status"] == "unavailable"

    stale = _AvailableScanner("test_ml")
    degraded = Pipeline(
        scanners=[MinimalScanner(), stale],
        config=PetasosConfig(fail_mode="open"),
    )
    degraded._last_scan_errors["test_ml"] = "model exploded"
    row = _row(degraded.scanner_health(), "test_ml")
    assert row["status"] == "degraded"
    assert row["last_error"] == "model exploded"

    open_breaker = Pipeline(
        scanners=[MinimalScanner(), _AvailableScanner("test_ml")],
        config=PetasosConfig(fail_mode="open"),
    )
    open_breaker._breaker_open_until["test_ml"] = time.monotonic() + 999
    assert _row(open_breaker.scanner_health(), "test_ml")["status"] == "circuit_open"


def test_semgrep_health_carries_its_qualification_warning() -> None:
    scanner = object.__new__(SemgrepScanner)
    scanner.qualification_warning = "engine is not qualified"

    async def scan(
        text: str,
        *,
        direction: str = "inbound",
        session_id: str | None = None,
    ) -> ScanResult:
        return ScanResult(scanner_name="semgrep", findings=(), duration_ms=0.0)

    scanner.scan = scan  # type: ignore[method-assign]
    pipe = Pipeline(
        scanners=[MinimalScanner(), scanner],
        config=PetasosConfig(fail_mode="open"),
    )
    row = _row(pipe.scanner_health(), "semgrep")
    assert row["status"] == "healthy"
    assert row["warning"] == "engine is not qualified"


def test_a_classifier_error_does_not_raise() -> None:
    pipe = Pipeline(scanners=[MinimalScanner()], config=PetasosConfig())
    guard = ToolCallGuard(
        pipe,
        pipe._frequency_tracker,
        PetasosConfig(),
        secrets=Secrets(session_secret=b"a" * 32),
        protected_paths=lambda: ["/owned/config.yaml"],
    )
    match = guard._classify_selfmod("terminal", cast("dict[str, Any]", _BoomParams()))
    assert match is None


def test_unknown_severity_and_audit_dicts_round_trip() -> None:
    assert severity_rank("not-a-severity") < severity_rank(Severity.INFO)
    assert severity_rank("not-a-severity", unknown_wins=True) > severity_rank(Severity.CRITICAL)
    payload = MappingProxyType({"sev": Severity.HIGH, "items": [{"nested": 1}]})
    event = AuditEvent("e", 1.0, "s", "scan", payload, 1)
    assert event.to_dict()["payload"]["sev"] == "high"
    alert = Alert("a", 1.0, "rule", "high", "s", "msg", payload)
    assert alert.to_dict()["context"]["items"] == [{"nested": 1}]


async def test_ingestion_failures_are_recorded_and_do_not_raise() -> None:
    class _Bare:
        pass

    class _Head:
        @property
        def scanner_results(self) -> list[object]:
            raise RuntimeError("unreadable")

    class _Pipeline:
        def __init__(self, config: object) -> None:
            self.config = config

        async def inspect(self, *_args: object, **_kwargs: object) -> _Head:
            return _Head()

    class _Lock:
        def acquire(self, *, blocking: bool = False) -> bool:
            raise RuntimeError("locked")

        def release(self) -> None:
            return None

    bare = await scan_ingestion_result(cast("Any", _Pipeline(_Bare())), "hello")
    assert bare.errors
    broken = await scan_ingestion_result(
        cast("Any", _Pipeline(PetasosConfig())),
        "hello",
        inspect_lock=cast("Any", _Lock()),
    )
    assert any("RuntimeError" in item for item in broken.errors)
    unreadable = await scan_ingestion_result(cast("Any", _Pipeline(PetasosConfig())), "hello")
    assert any("unreadable" in item for item in unreadable.errors)
