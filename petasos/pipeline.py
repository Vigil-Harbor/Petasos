from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from petasos._types import (
    PipelineResult,
    ScanFinding,
    ScanResult,
    Severity,
)
from petasos.config import PetasosConfig
from petasos.normalize import normalize
from petasos.premium.frequency import FrequencyTracker, FrequencyUpdateResult
from petasos.premium.profiles import ProfileResolver, ResolvedProfile
from petasos.scanners.minimal import MinimalScanner

if TYPE_CHECKING:
    from collections.abc import Sequence

    from petasos._types import Direction, Scanner

_SEVERITY_RANK: dict[Severity, int] = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
    Severity.INFO: 4,
}

_SCANNER_TIMEOUT = 30.0


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
            if nxt.confidence > current.confidence:
                current = nxt
            elif nxt.confidence == current.confidence:
                nxt_rank = _SEVERITY_RANK.get(nxt.severity, 999)
                cur_rank = _SEVERITY_RANK.get(current.severity, 999)
                if nxt_rank < cur_rank:
                    current = nxt
                elif nxt_rank == cur_rank:
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
    safe = True
    for f in findings:
        if f.severity in (Severity.CRITICAL, Severity.HIGH):
            safe = False
            break

    ml_total = 0
    ml_errored = 0
    for r in scanner_results:
        if r.scanner_name == "minimal":
            continue
        ml_total += 1
        if r.error is not None:
            ml_errored += 1

    if ml_total == 0:
        return safe

    partial_failure = 0 < ml_errored < ml_total
    all_ml_failure = ml_errored == ml_total

    if fail_mode == "degraded":
        if all_ml_failure:
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
) -> ScanResult:
    sname = getattr(scanner, "name", "unknown")
    t0 = time.perf_counter()
    try:
        return await asyncio.wait_for(
            scanner.scan(normalized_text, direction=direction, session_id=session_id),
            timeout=_SCANNER_TIMEOUT,
        )
    except Exception as exc:
        elapsed = (time.perf_counter() - t0) * 1000
        return ScanResult(
            scanner_name=sname,
            findings=(),
            duration_ms=elapsed,
            error=str(exc),
        )


class Pipeline:
    def __init__(
        self,
        scanners: Sequence[Scanner] = (),
        *,
        config: PetasosConfig | None = None,
        profile: str | ResolvedProfile | None = None,
    ) -> None:
        self._config = config.copy() if config is not None else PetasosConfig()
        self._premium_active = False

        scanner_list = list(scanners)
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

    @property
    def config(self) -> PetasosConfig:
        return self._config

    def activate(self) -> None:
        self._premium_active = True

    def deactivate(self) -> None:
        self._premium_active = False

    def is_premium_active(self, feature_name: str) -> bool:
        return self._check_premium(feature_name)

    def _check_premium(self, feature_name: str) -> bool:
        return self._premium_active

    def _resolve_profile(
        self, profile: str | ResolvedProfile | None
    ) -> ResolvedProfile | None:
        if isinstance(profile, ResolvedProfile):
            return profile
        if isinstance(profile, str):
            return self._profile_resolver.resolve(profile)
        if self._config.profile_name:
            return self._profile_resolver.resolve(self._config.profile_name)
        return None

    def _build_premium_features(self) -> MappingProxyType[str, str]:
        active = self._premium_active
        return MappingProxyType(
            {
                "frequency": "unlocked" if active and self._config.frequency_enabled else "locked",
                "escalation": "unlocked"
                if active and self._config.escalation_enabled
                else "locked",
                "profiles": "unlocked"
                if active and self._default_profile is not None
                else "locked",
                "tool_guard": "unlocked"
                if active and self._config.tool_guard_enabled
                else "locked",
                "audit": "locked",
                "alerting": "locked",
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
            premium_features=self._build_premium_features(),
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

        active_profile = self._default_profile
        if profile is not None:
            if isinstance(profile, ResolvedProfile):
                active_profile = profile
            elif isinstance(profile, (str, dict)):
                active_profile = self._profile_resolver.resolve(profile)

        try:
            return await self._inspect_inner(
                text,
                direction=resolved_direction,
                session_id=session_id,
                active_profile=active_profile,
            )
        except Exception as exc:
            return PipelineResult(
                safe=False,
                findings=(),
                errors=(str(exc),),
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

        # Stage 1: Normalize
        any_toggle_off = not (
            self._config.normalize_nfkc
            and self._config.strip_zero_width
            and self._config.map_homoglyphs
            and self._config.detect_rtl_override
        )
        if any_toggle_off:
            normalized_text = text
        else:
            norm_result = normalize(text)
            normalized_text = norm_result.normalized

        # Stage 1b: Profile hook → effective scanner
        effective_scanner = await self._premium_profile_hook(active_profile)

        # Stage 2: Syntactic pre-filter (raw text)
        minimal_result = await effective_scanner.scan(
            text, direction=direction, session_id=session_id
        )

        # Stage 3: Early exit (closed mode) — skip ML fan-out but still
        # run premium hooks so audit/alerting sees critical findings.
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
                _scan_one(s, normalized_text, direction=direction, session_id=session_id)
                for s in self._ml_scanners
            ]
            ml_results = list(await asyncio.gather(*tasks))
        else:
            ml_results = []

        all_results = [minimal_result] + ml_results

        # Stage 5: Merge findings
        merged = merge_findings(all_results)

        # Stage 5b: Confidence floor filtering
        if (
            active_profile is not None
            and self._check_premium("profiles")
            and active_profile.confidence_floor > 0.0
        ):
            merged = tuple(
                f for f in merged if f.confidence >= active_profile.confidence_floor
            )

        # Stage 5c: Severity overrides
        if (
            active_profile is not None
            and self._check_premium("profiles")
            and active_profile.severity_overrides
        ):
            overridden: list[ScanFinding] = []
            for f in merged:
                override = active_profile.severity_overrides.get(f.rule_id)
                if override is not None:
                    overridden.append(replace(f, severity=Severity(override)))
                else:
                    overridden.append(f)
            merged = tuple(overridden)

        # Stage 6: Premium frequency hook
        try:
            freq_result = await self._premium_frequency_hook(merged, session_id)
        except Exception as exc:
            errors.append(f"frequency hook: {exc}")

        # Stage 7: Premium escalation hook
        try:
            escalation_tier = await self._premium_escalation_hook(freq_result, session_id)
        except Exception as exc:
            errors.append(f"escalation hook: {exc}")

        # Stage 8: Fail-mode enforcement
        safe = False if early_exit else _compute_safe(merged, all_results, self._config.fail_mode)

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

        # Stage 10: Premium audit hook
        try:
            await self._premium_audit_hook(result, session_id)
        except Exception as exc:
            errors.append(f"audit hook: {exc}")

        # Stage 11: Premium alert hook
        try:
            await self._premium_alert_hook(result, session_id)
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

    async def _premium_profile_hook(
        self,
        profile: ResolvedProfile | None,
    ) -> MinimalScanner:
        assert self._minimal_scanner is not None
        if profile is None:
            return self._minimal_scanner
        if not self._check_premium("profiles"):
            return self._minimal_scanner
        if not profile.suppress_rules:
            return self._minimal_scanner
        return self._minimal_scanner.with_suppress_rules(profile.suppress_rules)

    async def _premium_frequency_hook(
        self, findings: tuple[ScanFinding, ...], session_id: str | None
    ) -> FrequencyUpdateResult | None:
        if not self._check_premium("frequency"):
            return None
        if not self._config.frequency_enabled:
            return None
        if session_id is None:
            return None
        rule_ids = [f.rule_id for f in findings]
        return self._frequency_tracker.update(session_id, rule_ids)

    async def _premium_escalation_hook(
        self,
        freq_result: FrequencyUpdateResult | None,
        session_id: str | None,
    ) -> str | None:
        if not self._check_premium("escalation"):
            return None
        if not self._config.escalation_enabled:
            return None
        if freq_result is None:
            return None
        return freq_result.tier

    async def _premium_audit_hook(self, result: PipelineResult, session_id: str | None) -> None:
        pass

    async def _premium_alert_hook(self, result: PipelineResult, session_id: str | None) -> None:
        pass
