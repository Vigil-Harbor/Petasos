"""Inspect text with explicit scanner errors and bounded session risk."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import threading
import time
from dataclasses import replace
from types import MappingProxyType
from typing import TYPE_CHECKING

from petasos.config.schema import ReconfigureResult, apply_live
from petasos.config.secrets import Secrets, require_hash_key
from petasos.config.sections import PetasosConfig, RulesConfig
from petasos.model import (
    _TIMEOUT_ERROR_PREFIX,
    Alert,
    AuditEvent,
    PipelineResult,
    ScanFinding,
    ScanResult,
    Severity,
    _validate_scanner,
    severity_rank,
)
from petasos.normalize import normalize
from petasos.pipeline.findings import (
    _compute_safe,
    _is_floor_rule,
    _merge_backend_coverage,
    _standalone_tier3_check,
    _suppress_scanner_findings,
    merge_findings,
)
from petasos.pipeline.health import _normalize_gather_result, _scan_with_breaker, scanner_health
from petasos.scanners.minimal import (
    MinimalScanner,
)
from petasos.scanners.presidio import PresidioScanner
from petasos.scanners.semgrep import SemgrepScanner
from petasos.scanners.semgrep.runtime import error_result as _semgrep_error
from petasos.session.alerting import AlertManager
from petasos.session.audit import AuditEmitter
from petasos.session.frequency import FrequencyTracker, FrequencyUpdateResult

_logger = logging.getLogger("petasos.pipeline")

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from petasos.model import Direction, Scanner
    from petasos.scanners.semgrep.adapter import PreparedSemgrepScan


class Pipeline:
    """Return inspection outcomes while containing scanner and hook failures."""

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
            # See docs/architecture/rationale.md, "Shared tracker token binding".
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
        """Return the host identity used for session binding and audit."""
        return self._host_id

    def is_feature_enabled(self, feature_name: str) -> bool:
        """Return whether a feature remains enabled in this pipeline."""
        return self._is_enabled(feature_name)

    scanner_health = scanner_health

    def add_audit_listener(self, callback: Callable[[AuditEvent], None]) -> None:
        """Register an additional audit event listener."""
        self._audit_emitter.add_listener(callback)

    def add_alert_listener(self, callback: Callable[[Alert], None]) -> None:
        """Register an additional alert listener."""
        self._alert_manager.add_listener(callback)

    def record_selfmod(self, session_id: str | None, finding: ScanFinding) -> None:
        """Emit self-modification audit and alert records without raising.

        The guard owns the associated risk update."""
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
        """Return findings, safety and errors without propagating inspection failures."""
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

        # Each normalization switch applies independently.
        normalization = self._config.normalization
        norm_result = normalize(
            text,
            nfkc=normalization.nfkc,
            strip_zero_width=normalization.zero_width,
            map_homoglyphs=normalization.homoglyphs,
        )
        normalized_text = norm_result.normalized

        # Suppression applies after the always-on syntactic pre-filter.
        assert self._minimal_scanner is not None
        effective_scanner = self._minimal_scanner

        _t0 = time.monotonic()
        minimal_result = await effective_scanner.scan(
            text, direction=direction, session_id=session_id
        )
        self._last_scan_durations["minimal"] = (time.monotonic() - _t0) * 1000
        if minimal_result.error is not None:
            self._last_scan_errors["minimal"] = minimal_result.error
        else:
            self._last_scan_errors.pop("minimal", None)

        # Critical early exits still need audit and alert hooks.
        early_exit = False
        if self._config.fail_mode == "closed":
            has_critical = any(f.severity == Severity.CRITICAL for f in minimal_result.findings)
            if has_critical:
                early_exit = True

        # Prepared results retain ownership; only unstarted work is skipped.
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
                    # Presidio alone accepts per-call entity extras so scope can change live.
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

        # See docs/architecture/rationale.md, "Pipeline ordering and attribution".
        if rules.suppress:
            all_results = _suppress_scanner_findings(
                all_results,
                frozenset(rules.suppress),
                direction,
                rules.injection_floor_scope,
            )

        merged = merge_findings(all_results)

        standalone_tier3 = _standalone_tier3_check(merged)

        if rules.confidence_floor > 0.0:
            merged = tuple(f for f in merged if f.confidence >= rules.confidence_floor)

        if rules.severity_overrides:
            overridden: list[ScanFinding] = []
            for f in merged:
                override = rules.severity_overrides.get(f.rule_id)
                if override is None:
                    # Structural findings bypass retargeting; the floor branch handles injection.
                    overridden.append(f)
                    continue
                if _is_floor_rule(f.rule_id, direction, rules.injection_floor_scope):
                    # Injection floor overrides can only promote severity.
                    try:
                        override_sev = Severity(override)
                    except ValueError:
                        overridden.append(f)
                        continue
                    if severity_rank(override_sev) > severity_rank(f.severity):
                        overridden.append(replace(f, severity=override_sev))
                    else:
                        overridden.append(f)
                else:
                    try:
                        override_sev = Severity(override)
                    except ValueError:
                        overridden.append(f)
                        continue
                    overridden.append(replace(f, severity=override_sev))
            merged = tuple(overridden)

        try:
            freq_result = await self._frequency_hook(merged, session_id, weight_cap=weight_cap)
        except Exception as exc:
            errors.append(f"frequency hook: {exc}")

        try:
            escalation_tier = await self._escalation_hook(freq_result, session_id)
        except Exception as exc:
            errors.append(f"escalation hook: {exc}")

        safe = False if early_exit else _compute_safe(merged, all_results, self._config.fail_mode)

        if standalone_tier3:
            safe = False
            if escalation_tier != "tier3":
                escalation_tier = "tier3"

        sanitized_content: str | None = None
        anonymization = self._config.anonymization
        if anonymization.enabled:
            pii_findings = [f for f in merged if f.finding_type == "pii"]
            # See docs/architecture/rationale.md, "Pipeline ordering and attribution".
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

        try:
            audit_cb_error = await self._audit_hook(result, session_id, freq_result, direction)
            if audit_cb_error is not None:
                errors.append(audit_cb_error)
        except Exception as exc:
            errors.append(f"audit hook: {exc}")

        try:
            alert_cb_errors = await self._alert_hook(result, session_id, freq_result)
            errors.extend(alert_cb_errors)
        except Exception as exc:
            errors.append(f"alert hook: {exc}")

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

    _scan_with_breaker = _scan_with_breaker

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
        # See docs/architecture/rationale.md, "Pipeline ordering and attribution".
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
                # A failed backstop on findings is a warning because risk accumulation is lost.
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
