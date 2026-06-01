from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from dataclasses import replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, ClassVar

from petasos._types import (
    Alert,
    AuditEvent,
    PipelineResult,
    ScanFinding,
    ScanResult,
    Severity,
    _validate_scanner,
)
from petasos.config import PetasosConfig
from petasos.normalize import normalize
from petasos.scanners.minimal import MinimalScanner
from petasos.session.alerting import AlertManager
from petasos.session.audit import AuditEmitter
from petasos.session.frequency import FrequencyTracker, FrequencyUpdateResult
from petasos.session.license import LicenseClaims, LicenseState, LicenseValidator
from petasos.session.profiles import ProfileResolver, ResolvedProfile

_logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from petasos._types import Direction, Scanner

_SEVERITY_RANK: dict[Severity, int] = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
    Severity.INFO: 4,
}

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

    positioned: list[ScanFinding] = []
    unpositioned: list[ScanFinding] = []
    for f in all_findings:
        if f.position is not None:
            positioned.append(f)
        else:
            unpositioned.append(f)

    if not positioned:
        return tuple(unpositioned)

    positioned.sort(key=lambda f: f.position.start)  # type: ignore[union-attr]

    surviving: list[ScanFinding] = []
    current = positioned[0]

    for nxt in positioned[1:]:
        assert current.position is not None
        assert nxt.position is not None
        if nxt.position.start < current.position.end:
            nxt_rank = _SEVERITY_RANK.get(nxt.severity, 999)
            cur_rank = _SEVERITY_RANK.get(current.severity, 999)
            if nxt_rank < cur_rank:
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
    return tuple(surviving) + tuple(unpositioned)


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
        if f.severity in (Severity.CRITICAL, Severity.HIGH):
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
) -> ScanResult:
    sname = getattr(scanner, "name", "unknown")
    t0 = time.perf_counter()
    try:
        return await asyncio.wait_for(
            scanner.scan(normalized_text, direction=direction, session_id=session_id),
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
        profile: str | ResolvedProfile | None = None,
        on_audit: Callable[[AuditEvent], None] | None = None,
        on_alert: Callable[[Alert], None] | None = None,
        host_id: str = "",
    ) -> None:
        self._config = replace(config) if config is not None else PetasosConfig()
        self._host_id = host_id
        if self._config.session_secret is not None and not host_id:
            raise ValueError("host_id is required when session_secret is configured")
        self._license_validator = LicenseValidator()
        self._license_state = LicenseState.INACTIVE
        self._license_claims: LicenseClaims | None = None

        scanner_list = list(scanners)
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
            self._minimal_scanner = MinimalScanner()

        self._frequency_tracker = FrequencyTracker(self._config)
        self._profile_resolver = ProfileResolver()
        self._default_profile: ResolvedProfile | None = self._resolve_profile(profile)
        self._audit_emitter = AuditEmitter(self._config, on_audit=on_audit)
        self._alert_manager = AlertManager(self._config, on_alert=on_alert)

        # Per-scanner circuit-breaker state (PIPE-03). Single-threaded asyncio
        # access only — same threading contract as license state (see activate()).
        self._breaker_consecutive_timeouts: dict[str, int] = {}
        self._breaker_open_until: dict[str, float] = {}

        # Auto-activation from the process environment for supporter/compliance
        # recognition. License state is tracked but does not gate features.
        env_key = os.environ.get("PETASOS_LICENSE_KEY")
        if env_key:
            self.activate(env_key)

    @property
    def config(self) -> PetasosConfig:
        return self._config

    def activate(self, key: str) -> LicenseState:
        """Validate a license key for supporter/compliance recognition.

        License state is tracked but does not gate feature execution — all
        features are controlled by config toggles. The key serves as a
        supporter token or future compliance tier marker.

        Threading (PIPE-10): license state is mutated non-atomically. Petasos is
        single-threaded asyncio; do not call ``activate``/``deactivate`` from a
        thread other than the one driving the event loop while a scan is in
        flight. Accepted residual — no lock.
        """
        state, claims = self._license_validator.validate(key)
        self._license_state = state
        self._license_claims = claims if state == LicenseState.VALID else None
        return state

    def deactivate(self) -> None:
        """Reset license state to INACTIVE.

        Does not affect feature availability — features are controlled by
        config toggles. Threading: not synchronized — see ``activate``.
        """
        self._license_state = LicenseState.INACTIVE
        self._license_claims = None

    @property
    def host_id(self) -> str:
        return self._host_id

    def is_feature_enabled(self, feature_name: str) -> bool:
        return self._is_enabled(feature_name)

    _FEATURE_GATES: ClassVar[dict[str, str]] = {
        "frequency": "frequency_enabled",
        "escalation": "escalation_enabled",
        "tool_guard": "tool_guard_enabled",
        "audit": "audit_enabled",
        "alerting": "alert_enabled",
    }

    def _is_enabled(self, feature_name: str) -> bool:
        attr = self._FEATURE_GATES.get(feature_name)
        if attr is not None:
            return bool(getattr(self._config, attr, True))
        return True

    def _resolve_profile(self, profile: str | ResolvedProfile | None) -> ResolvedProfile | None:
        if isinstance(profile, ResolvedProfile):
            return profile
        if isinstance(profile, str):
            return self._profile_resolver.resolve(profile)
        if self._config.profile_name:
            return self._profile_resolver.resolve(self._config.profile_name)
        return None

    def _build_feature_status(self) -> MappingProxyType[str, str]:
        def _status(config_attr: str) -> str:
            return "enabled" if getattr(self._config, config_attr, True) else "disabled"

        return MappingProxyType(
            {
                "frequency": _status("frequency_enabled"),
                "escalation": _status("escalation_enabled"),
                "profiles": "enabled" if self._default_profile is not None else "disabled",
                "tool_guard": _status("tool_guard_enabled"),
                "audit": _status("audit_enabled"),
                "alerting": _status("alert_enabled"),
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
        )

    async def inspect(
        self,
        text: str,
        *,
        direction: Direction | None = None,
        session_id: str | None = None,
        profile: str | ResolvedProfile | dict[str, Any] | None = None,
    ) -> PipelineResult:
        resolved_direction: Direction = (
            direction if direction is not None else self._config.direction
        )

        try:
            active_profile = self._default_profile
            if profile is not None:
                if isinstance(profile, ResolvedProfile):
                    active_profile = profile
                elif isinstance(profile, (str, dict)):
                    active_profile = self._profile_resolver.resolve(profile)

            return await self._inspect_inner(
                text,
                direction=resolved_direction,
                session_id=session_id,
                active_profile=active_profile,
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
        active_profile: ResolvedProfile | None,
    ) -> PipelineResult:
        freq_result: FrequencyUpdateResult | None = None
        escalation_tier: str | None = None
        errors: list[str] = []

        # Stage 1: Normalize — each config toggle is honored independently
        # (PIPE-05). The old all-or-nothing guard skipped *all* normalization if
        # any single toggle was off; now disabling one stage leaves the rest
        # running.
        norm_result = normalize(
            text,
            nfkc=self._config.normalize_nfkc,
            strip_zero_width=self._config.strip_zero_width,
            map_homoglyphs=self._config.map_homoglyphs,
            detect_rtl=self._config.detect_rtl_override,
        )
        normalized_text = norm_result.normalized

        # Stage 1b: Profile hook → effective scanner
        effective_scanner = await self._profile_hook(active_profile)

        # Stage 2: Syntactic pre-filter (raw text)
        minimal_result = await effective_scanner.scan(
            text, direction=direction, session_id=session_id
        )

        # Stage 3: Early exit (closed mode) — skip ML fan-out but still
        # run session hooks so audit/alerting sees critical findings.
        early_exit = False
        if self._config.fail_mode == "closed":
            has_critical = any(f.severity == Severity.CRITICAL for f in minimal_result.findings)
            if has_critical:
                early_exit = True

        # Stage 4: Fan-out scan
        if early_exit:
            ml_results: list[ScanResult] = []
        elif self._ml_scanners:
            tasks = [
                self._scan_with_breaker(
                    s, normalized_text, direction=direction, session_id=session_id
                )
                for s in self._ml_scanners
            ]
            raw_results = await asyncio.gather(*tasks, return_exceptions=True)
            ml_results = [
                _normalize_gather_result(r, getattr(s, "name", "unknown"))
                for r, s in zip(raw_results, self._ml_scanners, strict=True)
            ]
        else:
            ml_results = []

        all_results = [minimal_result] + ml_results

        # Stage 5: Merge findings
        merged = merge_findings(all_results)

        # Stage 5a: Standalone tier-3 safety net (ESC-01)
        standalone_tier3 = _standalone_tier3_check(merged)

        # Stage 5b: Confidence floor filtering
        if active_profile is not None and active_profile.confidence_floor > 0.0:
            merged = tuple(f for f in merged if f.confidence >= active_profile.confidence_floor)

        # Stage 5c: Severity overrides (PIPE-07 guards)
        if active_profile is not None and active_profile.severity_overrides:
            overridden: list[ScanFinding] = []
            for f in merged:
                override = active_profile.severity_overrides.get(f.rule_id)
                if override is not None:
                    if f.rule_id.startswith(_STRUCTURAL_RULE_PREFIX):
                        overridden.append(f)
                        continue
                    try:
                        override_sev = Severity(override)
                    except ValueError:
                        overridden.append(f)
                        continue
                    override_rank = _SEVERITY_RANK.get(override_sev, 999)
                    current_rank = _SEVERITY_RANK.get(f.severity, 999)
                    if override_rank > current_rank:
                        overridden.append(f)
                    else:
                        overridden.append(replace(f, severity=override_sev))
                else:
                    overridden.append(f)
            merged = tuple(overridden)

        # Stage 6: Frequency hook
        try:
            freq_result = await self._frequency_hook(merged, session_id)
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
        if self._config.anonymize:
            pii_findings = [f for f in merged if f.finding_type == "pii"]
            if pii_findings:
                try:
                    from petasos.scanners.presidio import anonymize as _anonymize

                    sanitized_content = _anonymize(
                        normalized_text,
                        pii_findings,
                        mode=self._config.redaction_mode,
                        hash_key=self._config.hash_key,
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
            audit_cb_error = await self._audit_hook(result, session_id, freq_result)
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
    ) -> ScanResult:
        """Run one ML scanner under the consecutive-timeout circuit breaker (PIPE-03).

        Advisory only: while a scanner's breaker is open it is short-circuited to
        an error ScanResult for the cooldown window instead of being re-awaited.
        This never throws and never bypasses the syntactic pre-filter, so the
        never-throws and fail-mode invariants hold — in degraded mode a tripped
        breaker still blocks content (the error counts toward _compute_safe).
        Single-threaded asyncio access only (see activate() threading contract).
        """
        sname = getattr(scanner, "name", "unknown")
        threshold = self._config.scanner_circuit_breaker_threshold

        open_until = self._breaker_open_until.get(sname)
        if open_until is not None:
            if time.monotonic() < open_until:
                return ScanResult(
                    scanner_name=sname,
                    findings=(),
                    duration_ms=0.0,
                    error=(
                        f"{_BREAKER_OPEN_ERROR_PREFIX}: short-circuited after "
                        f"{threshold} consecutive timeouts"
                    ),
                )
            # Cooldown expired — clear the old streak so the scanner must
            # accumulate a fresh consecutive-timeout run to reopen the breaker.
            self._breaker_consecutive_timeouts.pop(sname, None)
            self._breaker_open_until.pop(sname, None)

        result = await _scan_one(
            scanner,
            normalized_text,
            direction=direction,
            session_id=session_id,
            timeout=self._config.scanner_timeout_seconds,
        )

        if result.error is not None and result.error.startswith(_TIMEOUT_ERROR_PREFIX):
            count = self._breaker_consecutive_timeouts.get(sname, 0) + 1
            self._breaker_consecutive_timeouts[sname] = count
            if count >= threshold:
                self._breaker_open_until[sname] = (
                    time.monotonic() + self._config.scanner_circuit_breaker_cooldown_seconds
                )
        else:
            # Any non-timeout outcome (success or a different error) breaks the
            # consecutive-timeout streak and re-closes the breaker.
            self._breaker_consecutive_timeouts.pop(sname, None)
            self._breaker_open_until.pop(sname, None)
        return result

    async def _profile_hook(
        self,
        profile: ResolvedProfile | None,
    ) -> MinimalScanner:
        assert self._minimal_scanner is not None
        if profile is None:
            return self._minimal_scanner
        if not profile.suppress_rules:
            return self._minimal_scanner
        return self._minimal_scanner.with_suppress_rules(profile.suppress_rules)

    async def _frequency_hook(
        self, findings: tuple[ScanFinding, ...], session_id: str | None
    ) -> FrequencyUpdateResult | None:
        if not self._is_enabled("frequency"):
            return None
        if session_id is None:
            return None
        rule_ids = [f.rule_id for f in findings]
        if self._config.session_secret is not None:
            token = self._frequency_tracker.mint_token(session_id, self._host_id)
            result = self._frequency_tracker.update(token, rule_ids)
        else:
            result = self._frequency_tracker.update(session_id, rule_ids)
        if result.rate_limited:
            sid_fp = hashlib.sha256((session_id or "").encode()).hexdigest()[:8]
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
    ) -> str | None:
        if not self._is_enabled("audit"):
            return None
        self._audit_emitter.emit(result, session_id, freq_result)
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
