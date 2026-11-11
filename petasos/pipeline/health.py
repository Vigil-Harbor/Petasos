"""Bound scanner work and report circuit-breaker health."""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import TYPE_CHECKING, Any

from petasos.model import (
    _TIMEOUT_ERROR_PREFIX,
    AVAILABILITY_CAUSE_LOAD_FAILED,
    ScanResult,
)
from petasos.scanners.semgrep import SemgrepScanner

if TYPE_CHECKING:
    from collections.abc import Sequence

    from petasos.model import Direction, Scanner
    from petasos.pipeline.pipeline import Pipeline

# PET-103: scanner-health status names as module-level constants (D8) so the
# pipeline and its tests cannot drift on the spelling. ``error`` (load-time
# crash) is distinct from ``degraded`` (run-time error) and from ``unavailable``
# (genuinely not installed / prerequisites missing).
_HEALTH_STATUS_HEALTHY = "healthy"
_HEALTH_STATUS_DEGRADED = "degraded"
_HEALTH_STATUS_CIRCUIT_OPEN = "circuit_open"
_HEALTH_STATUS_UNAVAILABLE = "unavailable"
_HEALTH_STATUS_ERROR = "error"

# Default per-scanner timeout (PIPE-03). Lowered from 30s; overridable per
# Pipeline via PetasosConfig.scanner_timeout_seconds. Kept as the _scan_one
# default so callers/tests that omit a timeout still get a bounded wait.
_SCANNER_TIMEOUT = 10.0

# Error-string prefixes used to classify scanner failures for the circuit
# breaker (PIPE-03). A timeout increments the per-scanner consecutive-timeout
# counter; any other error (or success) resets it.
_BREAKER_OPEN_ERROR_PREFIX = "ScannerCircuitOpen"


async def _scan_one(
    scanner: Scanner,
    normalized_text: str,
    *,
    direction: Direction,
    session_id: str | None,
    timeout: float = _SCANNER_TIMEOUT,
    extra_entities: Sequence[str] | None = None,
) -> ScanResult:
    sname = getattr(scanner, "name", "unknown")
    t0 = time.perf_counter()
    try:
        # extra_entities is Presidio-only (PET-119); passed conditionally so the
        # generic Scanner.scan() call stays protocol-conformant under mypy --strict
        # (no keyword reaches non-Presidio scanners).
        scan_kwargs: dict[str, Any] = {"direction": direction, "session_id": session_id}
        if extra_entities is not None:
            scan_kwargs["extra_entities"] = list(extra_entities)
        return await asyncio.wait_for(
            scanner.scan(normalized_text, **scan_kwargs),
            timeout=timeout,
        )
    except asyncio.TimeoutError:  # noqa: UP041
        # Classified separately from other failures so the circuit breaker can
        # count consecutive timeouts. asyncio.TimeoutError (not the builtin) is
        # what wait_for raises on Python <3.11; on 3.11+ it is an alias of the
        # builtin TimeoutError, so this catches both. The UP041 rewrite to the
        # bare builtin is suppressed because it breaks on 3.10. CancelledError is
        # a BaseException, not a TimeoutError, so it falls through below (PET-48).
        elapsed = (time.perf_counter() - t0) * 1000
        return ScanResult(
            scanner_name=sname,
            findings=(),
            duration_ms=elapsed,
            error=f"{_TIMEOUT_ERROR_PREFIX}: scanner exceeded {timeout}s",
        )
    except BaseException as exc:
        elapsed = (time.perf_counter() - t0) * 1000
        return ScanResult(
            scanner_name=sname,
            findings=(),
            duration_ms=elapsed,
            error=f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__,
        )


def _normalize_gather_result(
    result: ScanResult | BaseException,
    scanner_name: str,
) -> ScanResult:
    if isinstance(result, BaseException):
        return ScanResult(
            scanner_name=scanner_name,
            findings=(),
            duration_ms=0.0,
            error=f"{type(result).__name__}: {result}" if str(result) else type(result).__name__,
        )
    return result


def scanner_health(self: Pipeline) -> list[dict[str, Any]]:
    """Return per-scanner health status for the console dashboard."""
    import time as _time

    result: list[dict[str, Any]] = []
    if self._minimal_scanner is not None:
        minimal_err = self._last_scan_errors.get("minimal")
        result.append(
            {
                "name": "minimal",
                "status": _HEALTH_STATUS_DEGRADED if minimal_err else _HEALTH_STATUS_HEALTHY,
                "last_ms": self._last_scan_durations.get("minimal"),
                "consecutive_timeouts": 0,
                "last_error": minimal_err,
            }
        )
    for s in self._ml_scanners:
        sname = s.name
        if isinstance(s, SemgrepScanner):
            with self._semgrep_lock:
                open_until = self._breaker_open_until.get(sname, 0.0)
                timeouts = self._breaker_consecutive_timeouts.get(sname, 0)
                scan_err = self._last_scan_errors.get(sname)
                last_ms = self._last_scan_durations.get(sname)
        else:
            open_until = self._breaker_open_until.get(sname, 0.0)
            timeouts = self._breaker_consecutive_timeouts.get(sname, 0)
            scan_err = self._last_scan_errors.get(sname)
            last_ms = self._last_scan_durations.get(sname)

        probe_fn = getattr(s, "availability", None)
        probe_ok = True
        probe_reason: str | None = None
        probe_cause: str | None = None
        if probe_fn is not None:
            # PET-103 D4: arity-tolerant, fail-safe extraction. ``probe_result``
            # is ``Any`` (``availability()`` is duck-typed) and MUST stay ``Any``
            # — annotating it as a fixed-arity tuple makes the ``len`` guards
            # statically dead and ``probe_result[2]`` a mypy error. A legacy 2-tuple
            # leaves ``probe_cause`` None → the non-``load_failed`` branch →
            # ``unavailable`` (backward compatible). A short/non-indexable or
            # throwing return is suppressed, leaving ``probe_ok`` True →
            # ``healthy`` (pre-existing PET-87 behavior, unchanged here).
            with contextlib.suppress(Exception):
                probe_result = probe_fn()
                probe_ok = bool(probe_result[0])
                probe_reason = probe_result[1] if len(probe_result) > 1 else None
                probe_cause = probe_result[2] if len(probe_result) > 2 else None

        if not probe_ok:
            if probe_cause == AVAILABILITY_CAUSE_LOAD_FAILED:
                status = _HEALTH_STATUS_ERROR
            else:
                status = _HEALTH_STATUS_UNAVAILABLE
            # Provenance is load-bearing for ``error``: an operator told the
            # backend crashed on load must see the crash message, not a stale
            # ``scan_err``. ``is not None`` (not ``or``) preserves an
            # explicitly-empty crash reason. (PET-103)
            last_error = probe_reason if probe_reason is not None else scan_err
        elif open_until > _time.monotonic():
            status = _HEALTH_STATUS_CIRCUIT_OPEN
            last_error = scan_err
        elif timeouts > 0 or scan_err:
            status = _HEALTH_STATUS_DEGRADED
            last_error = scan_err
        else:
            status = _HEALTH_STATUS_HEALTHY
            last_error = None

        result.append(
            {
                "name": sname,
                "status": status,
                "last_ms": last_ms,
                "consecutive_timeouts": timeouts,
                "last_error": last_error,
            }
        )
        if isinstance(s, SemgrepScanner) and s.qualification_warning:
            result[-1]["warning"] = s.qualification_warning
    return result


async def _scan_with_breaker(
    self: Pipeline,
    scanner: Scanner,
    normalized_text: str,
    *,
    direction: Direction,
    session_id: str | None,
    extra_entities: Sequence[str] | None = None,
) -> ScanResult:
    """Run one ML scanner under the consecutive-timeout circuit breaker (PIPE-03).

    Advisory only: while a scanner's breaker is open it is short-circuited to
    an error ScanResult for the cooldown window instead of being re-awaited.
    This never throws and never bypasses the syntactic pre-filter, so the
    never-throws and fail-mode invariants hold — in degraded mode a tripped
    breaker still blocks content (the error counts toward _compute_safe).
    Single-threaded asyncio access only.
    """
    sname = getattr(scanner, "name", "unknown")
    threshold = self._config.scanners.breaker_threshold

    open_until = self._breaker_open_until.get(sname)
    if open_until is not None:
        if time.monotonic() < open_until:
            err = (
                f"{_BREAKER_OPEN_ERROR_PREFIX}: short-circuited after "
                f"{threshold} consecutive timeouts"
            )
            self._last_scan_errors[sname] = err
            return ScanResult(
                scanner_name=sname,
                findings=(),
                duration_ms=0.0,
                error=err,
            )
        # Cooldown expired — clear the old streak so the scanner must
        # accumulate a fresh consecutive-timeout run to reopen the breaker.
        self._breaker_consecutive_timeouts.pop(sname, None)
        self._breaker_open_until.pop(sname, None)

    _t0 = time.monotonic()
    result = await _scan_one(
        scanner,
        normalized_text,
        direction=direction,
        session_id=session_id,
        timeout=self._config.scanners.timeout_seconds,
        extra_entities=extra_entities,
    )
    self._last_scan_durations[sname] = (time.monotonic() - _t0) * 1000
    if result.error is not None:
        self._last_scan_errors[sname] = result.error
    else:
        self._last_scan_errors.pop(sname, None)

    if result.error is not None and result.error.startswith(_TIMEOUT_ERROR_PREFIX):
        count = self._breaker_consecutive_timeouts.get(sname, 0) + 1
        self._breaker_consecutive_timeouts[sname] = count
        if count >= threshold:
            self._breaker_open_until[sname] = (
                time.monotonic() + self._config.scanners.breaker_cooldown_seconds
            )
    else:
        # Any non-timeout outcome (success or a different error) breaks the
        # consecutive-timeout streak and re-closes the breaker.
        self._breaker_consecutive_timeouts.pop(sname, None)
        self._breaker_open_until.pop(sname, None)
    return result
