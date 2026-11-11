from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import math
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from petasos._types import (
    AVAILABILITY_CAUSE_LOAD_FAILED,
    Alert,
    AuditEvent,
    PipelineResult,
    ScanCoverage,
    ScanFinding,
    ScanResult,
    Severity,
    _validate_scanner,
    at_least,
    severity_rank,
)
from petasos.config.schema import ReconfigureResult, apply_live
from petasos.config.secrets import Secrets, require_hash_key
from petasos.config.sections import PetasosConfig, RulesConfig
from petasos.normalize import normalize
from petasos.scanners._semgrep_runtime import error_result as _semgrep_error
from petasos.scanners.minimal import (
    _ALL_INJECTION_IDS,
    _STRUCTURAL_RULE_IDS,
    MinimalScanner,
)
from petasos.scanners.presidio import PresidioScanner
from petasos.scanners.semgrep import PreparedSemgrepScan, SemgrepScanner
from petasos.session.alerting import AlertManager
from petasos.session.audit import AuditEmitter
from petasos.session.frequency import FrequencyTracker, FrequencyUpdateResult

_logger = logging.getLogger(__name__)

# Lower rank claims less coverage. Two scanners may share a name (Pipeline does not
# require unique names), so a collision keeps the claim that examined the least
# rather than whichever scanner finished last. Every result stays in scanner_results.
_COVERAGE_CLAIM_RANK: dict[str, int] = {
    "error": 0,
    "partial": 1,
    "unsupported": 2,
    "no_targets": 3,
    "complete": 4,
}


def _coverage_claim(coverage: ScanCoverage) -> tuple[int, int, int]:
    return (
        _COVERAGE_CLAIM_RANK[coverage.status],
        coverage.examined_chars,
        coverage.completed_target_count,
    )


def _merge_backend_coverage(
    scanner_results: Sequence[ScanResult],
) -> dict[str, ScanCoverage] | None:
    merged: dict[str, ScanCoverage] = {}
    for r in scanner_results:
        if r.coverage is None:
            continue
        current = merged.get(r.scanner_name)
        if current is None:
            merged[r.scanner_name] = r.coverage
        elif r.coverage != current:
            _logger.debug("duplicate scanner name %s reports differing coverage", r.scanner_name)
            if _coverage_claim(r.coverage) < _coverage_claim(current):
                merged[r.scanner_name] = r.coverage
    return merged or None


# PET-103: scanner-health status names as module-level constants (D8) so the
# pipeline and its tests cannot drift on the spelling. ``error`` (load-time
# crash) is distinct from ``degraded`` (run-time error) and from ``unavailable``
# (genuinely not installed / prerequisites missing).
_HEALTH_STATUS_HEALTHY = "healthy"
_HEALTH_STATUS_DEGRADED = "degraded"
_HEALTH_STATUS_CIRCUIT_OPEN = "circuit_open"
_HEALTH_STATUS_UNAVAILABLE = "unavailable"
_HEALTH_STATUS_ERROR = "error"

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from petasos._types import Direction, FloorScope, Scanner

# Default per-scanner timeout (PIPE-03). Lowered from 30s; overridable per
# Pipeline via PetasosConfig.scanner_timeout_seconds. Kept as the _scan_one
# default so callers/tests that omit a timeout still get a bounded wait.
_SCANNER_TIMEOUT = 10.0

# Error-string prefixes used to classify scanner failures for the circuit
# breaker (PIPE-03). A timeout increments the per-scanner consecutive-timeout
# counter; any other error (or success) resets it.
_TIMEOUT_ERROR_PREFIX = "ScannerTimeout"
_BREAKER_OPEN_ERROR_PREFIX = "ScannerCircuitOpen"

_STRUCTURAL_RULE_PREFIX = "petasos.syntactic.structural."
_SELFMOD_RULE_PREFIX = "petasos.selfmod."


def _is_floor_rule(
    rule_id: str,
    direction: Direction = "inbound",
    scope: FloorScope = "all",
) -> bool:
    # Single chokepoint for both floor checks (PET-162 D1). Structural is ALWAYS
    # floor — independent of direction/scope (a different threat class than
    # injection; injection_floor_scope governs the injection family only). The
    # prefix disjunct is a belt-and-suspenders guard kept aligned by a tripwire
    # test (_STRUCTURAL_RULE_IDS <= the structural-prefix set).
    if rule_id in _STRUCTURAL_RULE_IDS or rule_id.startswith(_STRUCTURAL_RULE_PREFIX):
        return True
    if rule_id.startswith(_SELFMOD_RULE_PREFIX):
        return True
    if rule_id in _ALL_INJECTION_IDS:
        # Injection floor is absolute on inbound for every profile (PET-54/124). A
        # profile may relax it for the agent's OWN outbound only by opting into
        # scope="inbound". Every value other than the exact pair
        # (scope=="inbound" AND direction=="outbound") falls through to floor, so
        # an unvalidated scope reaching here (direct construction) fails safe.
        return not (scope == "inbound" and direction == "outbound")
    return False


def _suppress_scanner_findings(
    results: list[ScanResult],
    suppress_rules: frozenset[str],
    direction: Direction = "inbound",
    scope: FloorScope = "all",
) -> list[ScanResult]:
    """Drop findings whose rule_id is suppressed and NOT on the floor, per scanner.

    ``replace(r, findings=kept)`` mutates ONLY ``findings``; ``scanner_name``,
    ``error``, and ``duration_ms`` are preserved, so ``_compute_safe``'s ML-failure
    accounting and the degraded fail-mode block are unaffected (suppression never
    empties an errored result's error). A drop is logged at DEBUG so a later "why
    was nothing flagged?" is a log grep, not a guess — the only runtime trace that
    a profile suppressed a finding.
    """
    out: list[ScanResult] = []
    for r in results:
        kept = tuple(
            f
            for f in r.findings
            if not (
                f.rule_id in suppress_rules and not _is_floor_rule(f.rule_id, direction, scope)
            )
        )
        if len(kept) != len(r.findings):
            dropped = sorted({f.rule_id for f in r.findings} - {f.rule_id for f in kept})
            _logger.debug("profile suppressed %s on scanner %s", dropped, r.scanner_name)
            out.append(replace(r, findings=kept))
        else:
            out.append(r)
    return out


_STANDALONE_TIER3_CRITICAL_COUNT = 3


def _standalone_tier3_check(findings: tuple[ScanFinding, ...]) -> bool:
    critical_count = sum(1 for f in findings if f.severity == Severity.CRITICAL)
    return critical_count >= _STANDALONE_TIER3_CRITICAL_COUNT


def merge_findings(results: Sequence[ScanResult]) -> tuple[ScanFinding, ...]:
    all_findings: list[ScanFinding] = []
    for r in results:
        all_findings.extend(r.findings)

    if not all_findings:
        return ()

    originals: dict[tuple[str, int | None, int | None], ScanFinding] = {}
    positioned: list[ScanFinding] = []
    unpositioned: list[ScanFinding] = []
    for f in all_findings:
        if f.scanner_name == "semgrep" and f.position_basis == "original":
            originals.setdefault(
                (
                    f.rule_id,
                    f.position.start if f.position else None,
                    f.position.end if f.position else None,
                ),
                f,
            )
        elif f.position is not None:
            positioned.append(f)
        else:
            unpositioned.append(f)

    if not positioned:
        return tuple(unpositioned) + tuple(originals.values())

    positioned.sort(key=lambda f: f.position.start)  # type: ignore[union-attr]

    surviving: list[ScanFinding] = []
    current = positioned[0]

    for nxt in positioned[1:]:
        assert current.position is not None
        assert nxt.position is not None
        if nxt.position.start < current.position.end:
            nxt_rank = severity_rank(nxt.severity)
            cur_rank = severity_rank(current.severity)
            if nxt_rank > cur_rank:
                current = nxt
            elif nxt_rank == cur_rank:
                if nxt.confidence > current.confidence:
                    current = nxt
                elif nxt.confidence == current.confidence:
                    surviving.append(current)
                    current = nxt
        else:
            surviving.append(current)
            current = nxt

    surviving.append(current)
    return tuple(surviving) + tuple(unpositioned) + tuple(originals.values())


def _compute_safe(
    findings: tuple[ScanFinding, ...],
    scanner_results: Sequence[ScanResult],
    fail_mode: str,
) -> bool:
    if fail_mode not in ("open", "closed", "degraded"):
        _logger.warning("fail_mode %r is invalid, falling back to 'degraded'", fail_mode)
        fail_mode = "degraded"
    safe = True
    for f in findings:
        if at_least(f.severity, Severity.HIGH):
            safe = False
            break

    syntactic_error = False
    ml_total = 0
    ml_errored = 0
    for r in scanner_results:
        if r.scanner_name == "minimal":
            if r.error is not None:
                syntactic_error = True
            continue
        ml_total += 1
        if r.error is not None:
            ml_errored += 1

    if syntactic_error and fail_mode in ("degraded", "closed"):
        safe = False

    if ml_total == 0:
        return safe

    partial_failure = 0 < ml_errored < ml_total
    all_ml_failure = ml_errored == ml_total

    if fail_mode == "degraded":
        if partial_failure or all_ml_failure:
            safe = False
    elif fail_mode == "open":
        pass
    elif fail_mode == "closed" and (partial_failure or all_ml_failure):
        safe = False

    return safe


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


class Pipeline:
    def __init__(
        self,
        scanners: Sequence[Scanner] = (),
        *,
        config: PetasosConfig | None = None,
        on_audit: Callable[[AuditEvent], None] | None = None,
        on_alert: Callable[[Alert], None] | None = None,
        host_id: str = "",
        frequency_tracker: FrequencyTracker | None = None,
        secrets: Secrets | None = None,
    ) -> None:
        self._config = config if config is not None else PetasosConfig()
        self._secrets = secrets if secrets is not None else Secrets()
        require_hash_key(self._config, self._secrets)
        self._host_id = host_id
        if self._secrets.session_secret is not None and not host_id:
            raise ValueError("host_id is required when session_secret is configured")

        scanner_list = list(scanners)
        if sum(isinstance(s, SemgrepScanner) for s in scanner_list) > 1:
            raise ValueError("Only one Semgrep adapter is supported per Pipeline")
        for s in scanner_list:
            _validate_scanner(s)

        self._minimal_scanner: MinimalScanner | None = None
        self._ml_scanners: list[Scanner] = []

        for s in scanner_list:
            if self._minimal_scanner is None and getattr(s, "name", None) == "minimal":
                if isinstance(s, MinimalScanner):
                    self._minimal_scanner = s
                else:
                    self._ml_scanners.append(s)
            else:
                self._ml_scanners.append(s)

        if self._minimal_scanner is None:
            self._minimal_scanner = MinimalScanner(
                decode_encoded_payloads=self._config.normalization.decode_payloads
            )

        if frequency_tracker is not None:
            # PET-176 D1: an injected tracker and this pipeline must agree on
            # session_secret, or _frequency_hook's token/bare-string choice
            # (pipeline._config) and _resolve_session_id's enforcement
            # (tracker._session_secret) disagree and EVERY update() raises into
            # Stage 6's errors[] with a green-looking result.
            if frequency_tracker.requires_token != (self._secrets.session_secret is not None):
                raise ValueError(
                    "frequency_tracker.requires_token must match config.session_secret being set"
                )
            self._frequency_tracker = frequency_tracker
        else:
            self._frequency_tracker = FrequencyTracker(self._config, secrets=self._secrets)
        self._audit_emitter = AuditEmitter(self._config, on_audit=on_audit)
        self._alert_manager = AlertManager(self._config, on_alert=on_alert)

        # Per-scanner circuit-breaker state. Single-threaded asyncio access only.
        self._breaker_consecutive_timeouts: dict[str, int] = {}
        self._breaker_open_until: dict[str, float] = {}
        self._last_scan_durations: dict[str, float] = {}
        self._last_scan_errors: dict[str, str] = {}
        self._semgrep_lock = threading.Lock()

    @property
    def config(self) -> PetasosConfig:
        """The config tree this pipeline reads."""
        return self._config

    def reconfigure(self, new_config: PetasosConfig) -> ReconfigureResult:
        """Apply live settings and report the ones that need a restart.

        Secrets stay as they were. A malformed frequency weight map raises
        ``ValueError`` before any live state changes.
        """
        updated, result = apply_live(self._config, new_config)
        require_hash_key(updated, self._secrets)
        self._frequency_tracker.apply_config(updated)
        self._audit_emitter.apply_config(updated)
        self._alert_manager.apply_config(updated)
        assert self._minimal_scanner is not None
        self._minimal_scanner.set_decode_encoded_payloads(updated.normalization.decode_payloads)
        self._config = updated
        return result

    @property
    def host_id(self) -> str:
        return self._host_id

    def is_feature_enabled(self, feature_name: str) -> bool:
        return self._is_enabled(feature_name)

    def scanner_health(self) -> list[dict[str, Any]]:
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

    def add_audit_listener(self, callback: Callable[[AuditEvent], None]) -> None:
        """Register an additional audit event listener."""
        self._audit_emitter.add_listener(callback)

    def add_alert_listener(self, callback: Callable[[Alert], None]) -> None:
        """Register an additional alert listener."""
        self._alert_manager.add_listener(callback)

    def record_selfmod(self, session_id: str | None, finding: ScanFinding) -> None:
        """Alert + audit for a selfmod classification (PET-164 Decision 4).

        Sync, never throws. Frequency lives in the guard (Decision 3); this
        method does NOT touch the tracker. The alert bypasses the ``alerting``
        feature gate by construction; the audit sink is the sole config gate.
        """
        try:
            self._alert_manager.evaluate_selfmod(finding, session_id)
        except Exception:
            _logger.exception("record_selfmod: alert delivery failed")
        if self._is_enabled("audit"):
            try:
                synthetic = PipelineResult(
                    safe=True,
                    findings=(finding,),
                    errors=(),
                )
                self._audit_emitter.emit(synthetic, session_id, None, direction="outbound")
            except Exception:
                _logger.exception("record_selfmod: audit emit failed")

    def _is_enabled(self, feature_name: str) -> bool:
        config = self._config
        flags = {
            "frequency": config.frequency.enabled,
            "escalation": config.escalation.enabled,
            "tool_guard": config.tools.enabled,
            "audit": config.audit.enabled,
            "alerting": config.alerting.enabled,
        }
        if feature_name in flags:
            return flags[feature_name]
        return True

    def _rules_for(self) -> tuple[RulesConfig, tuple[str, ...]]:
        """Rules and extra entity types for this scan."""
        extra = self._config.scanners.presidio.entities_extra
        return self._config.rules, extra

    def _build_feature_status(self) -> MappingProxyType[str, str]:
        def _status(enabled: bool) -> str:
            return "enabled" if enabled else "disabled"

        config = self._config
        return MappingProxyType(
            {
                "frequency": _status(config.frequency.enabled),
                "escalation": _status(config.escalation.enabled),
                "profiles": "disabled",
                "tool_guard": _status(config.tools.enabled),
                "audit": _status(config.audit.enabled),
                "alerting": _status(config.alerting.enabled),
            }
        )

    def _build_result(
        self,
        *,
        safe: bool,
        findings: tuple[ScanFinding, ...],
        sanitized_content: str | None,
        scanner_results: tuple[ScanResult, ...],
        errors: tuple[str, ...],
        freq_result: FrequencyUpdateResult | None,
        escalation_tier: str | None,
    ) -> PipelineResult:
        return PipelineResult(
            safe=safe,
            findings=findings,
            sanitized_content=sanitized_content,
            scanner_results=scanner_results,
            errors=errors,
            escalation_tier=escalation_tier,
            session_score=(freq_result.current_score if freq_result is not None else None),
            feature_status=self._build_feature_status(),
            backend_coverage=_merge_backend_coverage(scanner_results),
        )

    async def _prepare_semgrep(
        self,
        original_text: str,
        *,
        segments: tuple[tuple[int, int], ...] | None = None,
        upstream_total_chars: int | None = None,
    ) -> PreparedSemgrepScan | None:
        scanner = next((s for s in self._ml_scanners if isinstance(s, SemgrepScanner)), None)
        if scanner is None:
            return None
        refusal = None
        with self._semgrep_lock:
            until = self._breaker_open_until.get("semgrep")
            if until is not None and time.monotonic() < until:
                refusal = "ScannerCircuitOpen: semgrep.cooldown"
            elif until is not None:
                self._breaker_open_until.pop("semgrep", None)
                self._breaker_consecutive_timeouts.pop("semgrep", None)

        return await scanner.prepare(
            original_text,
            binding=self,
            segments=segments,
            upstream_total_chars=upstream_total_chars,
            _refusal=refusal,
            _on_complete=self._record_semgrep,
        )

    def _record_semgrep(self, result: ScanResult) -> None:
        neutral = {
            "semgrep.queue_full",
            "semgrep.queue_deadline",
            "semgrep.lease_exhausted",
            "semgrep.prepared_capacity",
            "semgrep.lease_closed",
            "semgrep.probe_pending",
            "semgrep.prepared_invalid",
            "semgrep.invalid_envelope",
            "semgrep.cancelled",
            "ScannerCircuitOpen: semgrep.cooldown",
        }
        with self._semgrep_lock:
            self._last_scan_durations["semgrep"] = result.duration_ms
            if result.error:
                self._last_scan_errors["semgrep"] = result.error
            else:
                self._last_scan_errors.pop("semgrep", None)
            if result.error in neutral or (result.coverage and result.coverage.target_count == 0):
                return
            if result.error and result.error.startswith(_TIMEOUT_ERROR_PREFIX):
                count = self._breaker_consecutive_timeouts.get("semgrep", 0) + 1
                self._breaker_consecutive_timeouts["semgrep"] = count
                if count >= self._config.scanners.breaker_threshold:
                    self._breaker_open_until["semgrep"] = (
                        time.monotonic() + self._config.scanners.breaker_cooldown_seconds
                    )
            else:
                self._breaker_consecutive_timeouts.pop("semgrep", None)
                self._breaker_open_until.pop("semgrep", None)

    async def _scan_semgrep(self, original_text: str) -> ScanResult:
        token = await self._prepare_semgrep(original_text)
        assert token is not None
        try:
            return token.consume(self, original_text) or _semgrep_error("semgrep.prepared_invalid")
        finally:
            await token.discard()

    async def _inspect_with_prepared_semgrep(
        self,
        text: str,
        prepared: PreparedSemgrepScan | None,
        *,
        direction: Direction | None = None,
        session_id: str | None = None,
        weight_cap: float | None = None,
    ) -> PipelineResult:
        if prepared is None:
            if any(isinstance(s, SemgrepScanner) for s in self._ml_scanners):
                return PipelineResult(
                    safe=False, findings=(), errors=("semgrep.prepared_invalid",)
                )
            return await self.inspect(
                text,
                direction=direction,
                session_id=session_id,
                weight_cap=weight_cap,
            )
        try:
            result = prepared.consume(self, text)
            if result is None:
                return PipelineResult(
                    safe=False, findings=(), errors=("semgrep.prepared_invalid",)
                )
            rules, entities_extra = self._rules_for()
            return await self._inspect_inner(
                text,
                direction=direction or self._config.direction,
                session_id=session_id,
                rules=rules,
                entities_extra=entities_extra,
                weight_cap=weight_cap,
                prepared_semgrep=result,
            )
        except BaseException as exc:
            return PipelineResult(safe=False, findings=(), errors=(type(exc).__name__,))
        finally:
            await prepared.discard()

    async def inspect(
        self,
        text: str,
        *,
        direction: Direction | None = None,
        session_id: str | None = None,
        weight_cap: float | None = None,
    ) -> PipelineResult:
        resolved_direction: Direction = (
            direction if direction is not None else self._config.direction
        )

        try:
            rules, entities_extra = self._rules_for()
            return await self._inspect_inner(
                text,
                direction=resolved_direction,
                session_id=session_id,
                rules=rules,
                entities_extra=entities_extra,
                weight_cap=weight_cap,
            )
        except BaseException as exc:
            if not isinstance(exc, Exception):
                _logger.warning(
                    "Non-Exception caught at inspect() boundary: %s: %s",
                    type(exc).__name__,
                    exc,
                )
            error_msg = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
            return PipelineResult(
                safe=False,
                findings=(),
                errors=(error_msg,),
            )

    async def _inspect_inner(
        self,
        text: str,
        *,
        direction: Direction,
        session_id: str | None,
        rules: RulesConfig,
        entities_extra: tuple[str, ...],
        weight_cap: float | None = None,
        prepared_semgrep: ScanResult | None = None,
    ) -> PipelineResult:
        freq_result: FrequencyUpdateResult | None = None
        escalation_tier: str | None = None
        errors: list[str] = []

        # Stage 1: Normalize — each config toggle is honored independently
        # (PIPE-05). The old all-or-nothing guard skipped *all* normalization if
        # any single toggle was off; now disabling one stage leaves the rest
        # running.
        normalization = self._config.normalization
        norm_result = normalize(
            text,
            nfkc=normalization.nfkc,
            strip_zero_width=normalization.zero_width,
            map_homoglyphs=normalization.homoglyphs,
        )
        normalized_text = norm_result.normalized

        # Stage 1b: the syntactic pre-filter always uses the base minimal
        # scanner. Profile-driven suppression runs at Stage 4b (PET-109); no
        # profile-based scanner selection happens here.
        assert self._minimal_scanner is not None
        effective_scanner = self._minimal_scanner

        # Stage 2: Syntactic pre-filter (raw text)
        _t0 = time.monotonic()
        minimal_result = await effective_scanner.scan(
            text, direction=direction, session_id=session_id
        )
        self._last_scan_durations["minimal"] = (time.monotonic() - _t0) * 1000
        if minimal_result.error is not None:
            self._last_scan_errors["minimal"] = minimal_result.error
        else:
            self._last_scan_errors.pop("minimal", None)

        # Stage 3: Early exit (closed mode) — skip ML fan-out but still
        # run session hooks so audit/alerting sees critical findings.
        early_exit = False
        if self._config.fail_mode == "closed":
            has_critical = any(f.severity == Severity.CRITICAL for f in minimal_result.findings)
            if has_critical:
                early_exit = True

        # Stage 4: Fan-out scan. A prepared result survives the head early exit;
        # only unstarted scanner work is skipped.
        fanout_scanners = [
            s
            for s in self._ml_scanners
            if prepared_semgrep is None or not isinstance(s, SemgrepScanner)
        ]
        if early_exit:
            ml_results: list[ScanResult] = []
        elif fanout_scanners:
            tasks = [
                self._scan_semgrep(text)
                if isinstance(s, SemgrepScanner)
                else self._scan_with_breaker(
                    s,
                    normalized_text,
                    direction=direction,
                    session_id=session_id,
                    # PET-119: per-profile additive PII opt-ins, Presidio-only. A
                    # per-call concrete-type check (not a one-time partition like
                    # the minimal scanner): the extras are profile-dependent and
                    # recomputed each inspect(), and only PresidioScanner.scan
                    # accepts the keyword. None on the no-profile/non-Presidio path
                    # keeps today's exact behavior.
                    extra_entities=(
                        entities_extra
                        if entities_extra and isinstance(s, PresidioScanner)
                        else None
                    ),
                )
                for s in fanout_scanners
            ]
            raw_results = await asyncio.gather(*tasks, return_exceptions=True)
            ml_results = [
                _normalize_gather_result(r, getattr(s, "name", "unknown"))
                for r, s in zip(raw_results, fanout_scanners, strict=True)
            ]
        else:
            ml_results = []

        if prepared_semgrep is not None:
            ml_results.append(prepared_semgrep)
        all_results = [minimal_result] + ml_results

        # Stage 4b: Cross-scanner suppression (pre-merge; PET-109 D5). Drops
        # suppressed non-floor findings before overlap resolution so a suppressed
        # finding can neither evict a legitimate overlapping finding nor drive the
        # tier-3 net / frequency / escalation. Downstream consumers all read the
        # post-suppression set automatically — no per-consumer change.
        if rules.suppress:
            all_results = _suppress_scanner_findings(
                all_results,
                frozenset(rules.suppress),
                direction,
                rules.injection_floor_scope,
            )

        # Stage 5: Merge findings
        merged = merge_findings(all_results)

        # Stage 5a: Standalone tier-3 safety net (ESC-01)
        standalone_tier3 = _standalone_tier3_check(merged)

        # Stage 5b: Confidence floor filtering
        if rules.confidence_floor > 0.0:
            merged = tuple(f for f in merged if f.confidence >= rules.confidence_floor)

        # Stage 5c: Severity overrides (PIPE-07 guards; PET-109 D6/D8 downgrade).
        if rules.severity_overrides:
            overridden: list[ScanFinding] = []
            for f in merged:
                override = rules.severity_overrides.get(f.rule_id)
                if override is None:
                    # A structural rule cannot be retargeted, so it lands here.
                    # The floor branch below is reached only by injection rules.
                    overridden.append(f)
                    continue
                if _is_floor_rule(f.rule_id, direction, rules.injection_floor_scope):
                    # Floor rules (injection): escalate-only. Refuse a downgrade or
                    # no-op (keep original) — PET-54's threat, still covered.
                    try:
                        override_sev = Severity(override)
                    except ValueError:
                        overridden.append(f)
                        continue
                    if severity_rank(override_sev) > severity_rank(f.severity):
                        overridden.append(replace(f, severity=override_sev))  # escalate only
                    else:
                        overridden.append(f)  # refuse downgrade/equal
                else:
                    # Non-floor (e.g. petasos.presidio.*): any valid severity,
                    # including downgrade (PET-109 D8 narrows PET-54 to floor rules).
                    try:
                        override_sev = Severity(override)
                    except ValueError:
                        overridden.append(f)
                        continue
                    overridden.append(replace(f, severity=override_sev))
            merged = tuple(overridden)

        # Stage 6: Frequency hook
        try:
            freq_result = await self._frequency_hook(merged, session_id, weight_cap=weight_cap)
        except Exception as exc:
            errors.append(f"frequency hook: {exc}")

        # Stage 7: Escalation hook
        try:
            escalation_tier = await self._escalation_hook(freq_result, session_id)
        except Exception as exc:
            errors.append(f"escalation hook: {exc}")

        # Stage 8: Fail-mode enforcement
        safe = False if early_exit else _compute_safe(merged, all_results, self._config.fail_mode)

        # Stage 8b: Apply standalone tier-3 if triggered
        if standalone_tier3:
            safe = False
            if escalation_tier != "tier3":
                escalation_tier = "tier3"

        # Stage 9: Anonymize
        sanitized_content: str | None = None
        anonymization = self._config.anonymization
        if anonymization.enabled:
            pii_findings = [f for f in merged if f.finding_type == "pii"]
            # When entities is non-empty, anonymize only findings whose recovered
            # entity type is in the set (case-insensitive); empty () preserves
            # the "anonymize all" default. Narrowing only — detection and
            # `merged` are untouched.
            if anonymization.entities:
                from petasos.scanners.presidio import _recover_entity_type

                allowed = {e.upper() for e in anonymization.entities}
                pii_findings = [
                    f for f in pii_findings if _recover_entity_type(f.rule_id) in allowed
                ]
            if pii_findings:
                try:
                    from petasos.scanners.presidio import anonymize as _anonymize

                    sanitized_content = _anonymize(
                        normalized_text,
                        pii_findings,
                        mode=anonymization.mode,
                        hash_key=self._secrets.hash_key,
                    )
                except ImportError:
                    errors.append("presidio not installed: anonymization skipped")
                except Exception as exc:
                    errors.append(str(exc))

        scanner_results = tuple(all_results)
        pre_hook_error_count = len(errors)

        result = self._build_result(
            safe=safe,
            findings=merged,
            sanitized_content=sanitized_content,
            scanner_results=scanner_results,
            errors=tuple(errors),
            freq_result=freq_result,
            escalation_tier=escalation_tier,
        )

        # Stage 10: Audit hook
        try:
            audit_cb_error = await self._audit_hook(result, session_id, freq_result, direction)
            if audit_cb_error is not None:
                errors.append(audit_cb_error)
        except Exception as exc:
            errors.append(f"audit hook: {exc}")

        # Stage 11: Alert hook
        try:
            alert_cb_errors = await self._alert_hook(result, session_id, freq_result)
            errors.extend(alert_cb_errors)
        except Exception as exc:
            errors.append(f"alert hook: {exc}")

        # Stage 12: Return (rebuild if post-construction hooks added errors)
        if len(errors) > pre_hook_error_count:
            result = self._build_result(
                safe=safe,
                findings=merged,
                sanitized_content=sanitized_content,
                scanner_results=scanner_results,
                errors=tuple(errors),
                freq_result=freq_result,
                escalation_tier=escalation_tier,
            )
        return result

    async def _scan_with_breaker(
        self,
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

    async def _frequency_hook(
        self,
        findings: tuple[ScanFinding, ...],
        session_id: str | None,
        *,
        weight_cap: float | None = None,
    ) -> FrequencyUpdateResult | None:
        if not self._is_enabled("frequency"):
            return None
        if session_id is None:
            return None
        # PET-176 D2: validate the cap HERE, ahead of update(), then re-raise so
        # Stage 6 still records an errors[] entry. A malformed cap would
        # otherwise vanish into a green-looking PipelineResult (Stage 6 catches
        # into errors[], _compute_safe never reads errors). Validating ahead of
        # the call — rather than catching ValueError around it — keeps the
        # message honest: a bare `except ValueError` would also swallow
        # _resolve_session_id's HMAC / bare-string failures and blame a cap for
        # a token problem. update()'s own unconditional check remains the
        # contract; this hook only makes a *reachable* violation debuggable.
        if weight_cap is not None and (weight_cap < 0 or not math.isfinite(weight_cap)):
            sid_fp = hashlib.sha256(session_id.encode()).hexdigest()[:8]
            _logger.warning(
                "session %s...: rejected weight_cap %r (must be non-negative and "
                "finite); frequency update skipped for this scan",
                sid_fp,
                weight_cap,
            )
            raise ValueError(f"weight_cap must be non-negative and finite: {weight_cap!r}")
        rule_ids = [f.rule_id for f in findings]
        if self._secrets.session_secret is not None:
            token = self._frequency_tracker.mint_token(session_id, self._host_id)
            result = self._frequency_tracker.update(token, rule_ids, weight_cap=weight_cap)
        else:
            result = self._frequency_tracker.update(session_id, rule_ids, weight_cap=weight_cap)
        if result.rate_limited:
            sid_fp = hashlib.sha256(session_id.encode()).hexdigest()[:8]
            if rule_ids:
                # PET-176 D2: the backstop failing open on a scan that carried
                # findings is a WARNING, not an INFO curiosity.
                _logger.warning(
                    "session %s... rate-limited (frequency cap reached) on a scan "
                    "WITH findings; the session backstop is failing open",
                    sid_fp,
                )
            else:
                _logger.info("session %s... rate-limited (frequency cap reached)", sid_fp)
        return result

    async def _escalation_hook(
        self,
        freq_result: FrequencyUpdateResult | None,
        session_id: str | None,
    ) -> str | None:
        if not self._is_enabled("escalation"):
            return None
        if freq_result is None:
            return None
        return freq_result.tier

    async def _audit_hook(
        self,
        result: PipelineResult,
        session_id: str | None,
        freq_result: FrequencyUpdateResult | None,
        direction: Direction,
    ) -> str | None:
        if not self._is_enabled("audit"):
            return None
        # PET-136: thread the scan-level resolved direction into the audit payload.
        self._audit_emitter.emit(result, session_id, freq_result, direction=direction)
        return self._audit_emitter.last_callback_error

    async def _alert_hook(
        self,
        result: PipelineResult,
        session_id: str | None,
        freq_result: FrequencyUpdateResult | None,
    ) -> tuple[str, ...]:
        if not self._is_enabled("alerting"):
            return ()
        self._alert_manager.evaluate(result, session_id, freq_result)
        return self._alert_manager.callback_errors
