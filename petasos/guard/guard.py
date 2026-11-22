"""Evaluate tool-call policy in order."""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from petasos.config.secrets import Secrets
from petasos.guard.fanout import SpawnBudget, _fanout_cap
from petasos.guard.guardrail import CheckFailure, CheckFailures
from petasos.guard.params import _scan_params
from petasos.guard.selfmod import (
    SELFMOD_DEPTH_OVERFLOW_TARGET,
    _classify_selfmod,
    _raw_protected_entries,
    _surface,
    selfmod_target_paths,
)
from petasos.guard.tools import DEFAULT_TOOL_ALIASES
from petasos.model import ScanFinding, Severity
from petasos.normalize import canonicalize_tool_name
from petasos.session.escalation import evaluate_tier, max_tier

_logger = logging.getLogger("petasos.session.guard")
# Resolution sources that are Petasos's own calibrated values, not hand-written.
_BUILT_IN_SOURCES = frozenset({"default", "role", "level"})

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

    from petasos.config.sections import PetasosConfig
    from petasos.guard.surface import GuardrailSurface
    from petasos.hermes.home import HermesConfigResolution
    from petasos.pipeline import Pipeline
    from petasos.session.frequency import FrequencyTracker, SessionState
    from petasos.session.lineage import LineageRegistry


@dataclass(frozen=True)
class GuardResult:
    """Report a tool-call decision and the findings supporting it."""

    allowed: bool
    reason: str
    findings: tuple[ScanFinding, ...]
    tier: str
    param_scan_unsafe: bool
    # See docs/architecture/rationale.md, "Parameter scan degradation".
    param_scan_degraded: bool = False
    selfmod_target: str | None = None
    selfmod_finding: ScanFinding | None = None
    guardrail_kind: str | None = None
    guardrail_check_failed: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return the decision as JSON-serialisable data."""
        d: dict[str, Any] = {
            "allowed": self.allowed,
            "reason": self.reason,
            "findings": [f.to_dict() for f in self.findings],
            "tier": self.tier,
            "param_scan_unsafe": self.param_scan_unsafe,
            "param_scan_degraded": self.param_scan_degraded,
            "selfmod_target": self.selfmod_target,
            "guardrail_kind": self.guardrail_kind,
        }
        if self.selfmod_finding is not None:
            d["selfmod_finding"] = self.selfmod_finding.to_dict()
        else:
            d["selfmod_finding"] = None
        if self.guardrail_check_failed:
            d["guardrail_check_failed"] = True
        return d


_FEATURE_DISABLED = GuardResult(
    allowed=True,
    reason="feature disabled",
    findings=(),
    tier="none",
    param_scan_unsafe=False,
)

_TERMINATED = GuardResult(
    allowed=False,
    reason="session terminated (tier3)",
    findings=(),
    tier="tier3",
    param_scan_unsafe=False,
)


# See docs/architecture/rationale.md, "Scan contribution calibration".
_SCAN_WEIGHT_CAP_DIVISOR: float = 4.0

# See docs/architecture/rationale.md, "Scan contribution calibration".
_MAX_POISONED_SCAN_WEIGHT: float = 80.0


class ToolCallGuard:
    """Evaluate tool calls with risk, lineage and guardrail enforcement."""

    def __init__(
        self,
        pipeline: Pipeline,
        frequency_tracker: FrequencyTracker,
        config: PetasosConfig,
        *,
        origin: Mapping[str, str] | None = None,
        exempt_param_scan: bool = True,
        lineage: LineageRegistry | None = None,
        home: HermesConfigResolution | None = None,
        secrets: Secrets | None = None,
        protected_paths: Callable[[], Iterable[str]] | None = None,
        guardrail_surface: Callable[[], GuardrailSurface] | None = None,
        check_failures: CheckFailures | None = None,
    ) -> None:
        self._pipeline = pipeline
        self._frequency_tracker = frequency_tracker
        self._config = config
        self._origin = dict(origin) if origin is not None else {}
        self._secrets = secrets if secrets is not None else Secrets()
        self._selfmod_home = home
        self._exempt_param_scan = exempt_param_scan
        self._lineage = lineage
        # Explicit protected paths avoid host-layout discovery for adapter calls.
        self._protected_paths = protected_paths
        self._guardrail_surface = guardrail_surface
        self._check_failures = check_failures if check_failures is not None else CheckFailures()

        self._delegate_tool_names = self._delegates_from(config)
        # Exempt delegates would bypass the tier ladder and fan-out ceiling.
        self._reject_exempt_delegates(self._delegate_tool_names, config)
        if config.tools.fanout.enabled and not self._delegate_tool_names:
            _logger.warning(
                "delegate_fanout_enabled but delegate_tool_names is empty (or all normalized "
                "away) — the delegation fan-out gate is inert"
            )
        self._spawn_budget = SpawnBudget(config.tools.fanout.window_seconds)

    @property
    def config(self) -> PetasosConfig:
        """The config tree this guard reads."""
        return self._config

    def _delegates_from(self, config: PetasosConfig) -> frozenset[str]:
        return frozenset(
            n for n in (self._normalize_tool_name(raw) for raw in config.tools.delegate_names) if n
        )

    def _reject_exempt_delegates(self, delegates: frozenset[str], config: PetasosConfig) -> None:
        exempt_overlap = delegates & set(config.tools.exempt)
        if exempt_overlap:
            raise ValueError(
                f"delegate tool name(s) {sorted(exempt_overlap)} appear in the profile "
                f"exempt list; a delegate must not be exempt (it would skip the tier ladder)"
            )
        self._selfmod_owned_cache: tuple[float, frozenset[str]] = (0.0, frozenset())
        self._selfmod_empty_warned: bool = False
        # Threshold changes rearm the once-only cap diagnostics.
        self._cap_threshold_warned: bool = False

    def session_tier(self, session_id: str, *, include_rolling: bool = False) -> str:
        """The tier enforcement uses for ``session_id``, including an inherited one.

        Command deferral includes rolling-count promotion. The general guard
        ladder retains its recorded score-only behaviour. Failures are tier 3.
        """
        return self._derive_tier(session_id, include_rolling=include_rolling)

    def forget_protected_paths(self) -> None:
        """Drop the cached owned-path set so the next check reads it again."""
        self._selfmod_owned_cache = (0.0, frozenset())

    _surface = _surface

    selfmod_target_paths = selfmod_target_paths

    _raw_protected_entries = _raw_protected_entries

    _EXTRACT_OVERFLOW = "\x00__PETASOS_DEPTH_OVERFLOW__"

    @staticmethod
    def _extract_leaf_strings(value: Any, depth: int = 0) -> list[str]:
        if depth > 32:
            return [ToolCallGuard._EXTRACT_OVERFLOW]
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            out: list[str] = []
            for v in value.values():
                out.extend(ToolCallGuard._extract_leaf_strings(v, depth + 1))
            return out
        if isinstance(value, (list, tuple)):
            out = []
            for item in value:
                out.extend(ToolCallGuard._extract_leaf_strings(item, depth + 1))
            return out
        return []

    _classify_selfmod = _classify_selfmod

    def validate_config(self, new_config: PetasosConfig) -> None:
        """Dry-run validation of a candidate config: raises, never mutates.

        A delegate tool must never also be exempt. This runs before
        ``apply_config`` changes anything. The tracker's weight parse is the
        other check, and it runs when the tracker applies the same config.
        """
        self._reject_exempt_delegates(self._delegates_from(new_config), new_config)

    def apply_config(
        self, new_config: PetasosConfig, *, origin: Mapping[str, str] | None = None
    ) -> None:
        """Apply guard settings while preserving risk, spawn history and secret binding.

        Delegate/exemption validation precedes changes. The shared tracker applies
        its own staged weight validation without replacing session state."""
        self.validate_config(new_config)
        self._config = new_config
        self._origin = dict(origin) if origin is not None else {}
        self._delegate_tool_names = self._delegates_from(new_config)
        self._spawn_budget.set_window(new_config.tools.fanout.window_seconds)
        # Thresholds are reconfigurable, so the warned-about condition can
        # clear; re-arm the cap tripwire.
        self._cap_threshold_warned = False
        self._frequency_tracker.apply_config(self._config)

    @property
    def scan_weight_cap(self) -> float:
        """Return the quantized risk step for ingestion and parameter scans.

        See docs/architecture/rationale.md, "Scan contribution calibration"."""
        tier1 = float(self._config.escalation.tier1)
        if tier1 <= 0:
            # A zero tier 1 still validates when the three scores ascend.
            # derive_tier already returns at least tier 1 for every
            # non-negative score, so contributing nothing is coherent.
            if not self._cap_threshold_warned:
                self._cap_threshold_warned = True
                _logger.warning(
                    "non-positive tier1 threshold (%r) — per-scan clamp set to 0.0; "
                    "large-input scans will not accumulate",
                    tier1,
                )
            return 0.0
        # Built-in layers are calibrated as a whole; diagnose custom thresholds.
        if all(
            self._origin.get(f"escalation.{tier}") in _BUILT_IN_SOURCES
            for tier in ("tier1", "tier2")
        ):
            return tier1 / _SCAN_WEIGHT_CAP_DIVISOR
        # See docs/architecture/rationale.md, "Scan contribution calibration".
        if not self._cap_threshold_warned:
            tier2 = float(self._config.escalation.tier2)
            cap = tier1 / _SCAN_WEIGHT_CAP_DIVISOR
            if tier2 / tier1 < 2.0:
                self._cap_threshold_warned = True
                _logger.warning(
                    "tier2/tier1 ratio %.2f is below the recommended 2.0: as few as %d "
                    "consecutive flagged reads can stop tool dispatch once a session "
                    "reaches tier2 (recommended floor: 8)",
                    tier2 / tier1,
                    math.ceil(_SCAN_WEIGHT_CAP_DIVISOR * tier2 / tier1),
                )
            elif cap <= 3.0:
                self._cap_threshold_warned = True
                _logger.warning(
                    "tier1 %.1f gives a per-scan step of %.3f, at or below the lowest "
                    "syntactic rule weight (3.0): single-rule false positives will "
                    "accumulate instead of being absorbed",
                    tier1,
                    cap,
                )
            elif cap > _MAX_POISONED_SCAN_WEIGHT:
                self._cap_threshold_warned = True
                _logger.warning(
                    "tier1 %.1f gives a per-scan step of %.3f, above the maximally-poisoned "
                    "scan window (%.1f): every large-input scan quantizes to zero, leaving "
                    "the ingestion-path session backstop inert",
                    tier1,
                    cap,
                    _MAX_POISONED_SCAN_WEIGHT,
                )
        return tier1 / _SCAN_WEIGHT_CAP_DIVISOR

    async def evaluate(
        self,
        tool_name: str,
        tool_params: dict[str, Any],
        session_id: str,
    ) -> GuardResult:
        """Return a tool-call decision with guardrail, tier and parameter findings."""
        if not self._pipeline.is_feature_enabled("tool_guard"):
            # Tier 3 has no off switch: a terminated conversation stays blocked.
            if self._derive_tier(session_id) == "tier3":
                return _TERMINATED
            return _FEATURE_DISABLED

        canon_pre_alias = canonicalize_tool_name(tool_name)
        normalized_name = self._normalize_tool_name(tool_name)
        if not normalized_name:
            return GuardResult(
                allowed=False,
                reason="invalid tool name: empty after normalization",
                findings=(),
                tier="none",
                param_scan_unsafe=False,
            )

        selfmod = self._classify_selfmod(canon_pre_alias, tool_params)
        check_failed = isinstance(selfmod, CheckFailure)
        if isinstance(selfmod, CheckFailure):
            self._check_failures.note(session_id, selfmod)
            selfmod = None
        selfmod_finding: ScanFinding | None = None
        if selfmod is not None:
            sev = (
                Severity.CRITICAL
                if selfmod.rule_id == "petasos.selfmod.config_write"
                else Severity.HIGH
            )
            if selfmod.target == SELFMOD_DEPTH_OVERFLOW_TARGET:
                # Fail-secure overflow: the args exceeded the traversal depth cap,
                # so no owned path was actually matched. The message must say that
                # rather than claim a specific target.
                msg = (
                    "Self-tamper heuristic: tool argument nesting exceeded the "
                    "traversal depth cap (fail-secure flag; no owned path matched)"
                )
            else:
                msg = f"Self-tamper attempt targeting {selfmod.target}"
            selfmod_finding = ScanFinding(
                rule_id=selfmod.rule_id,
                finding_type="selfmod",
                severity=sev,
                confidence=1.0,
                message=msg,
                scanner_name="tool_guard",
            )

        def _finish(result: GuardResult) -> GuardResult:
            """Attach the selfmod fields and record the attempt at whichever exit fires.

            A tier3 exit skips the frequency-weight update (the session is already
            terminated); the alert/audit channel still records the attempt.
            """
            if check_failed:
                result = replace(result, guardrail_check_failed=True)
                if result.allowed and self._config.fail_mode != "open":
                    result = replace(result, allowed=False, reason="guardrail check could not run")
            if selfmod is None or selfmod_finding is None:
                return result
            result = replace(
                result,
                selfmod_target=selfmod.target,
                selfmod_finding=selfmod_finding,
                guardrail_kind=selfmod.kind,
            )
            if result.tier != "tier3":
                self._record_selfmod_weight(session_id, selfmod_finding)
            self._pipeline.record_selfmod(session_id, selfmod_finding)
            return result

        tier = self._derive_tier(session_id)

        if tier == "tier3":
            return _finish(_TERMINATED)

        if self._config.tools.fanout.enabled and normalized_name in self._delegate_tool_names:
            cap = self._fanout_cap(tier)
            if not self._spawn_budget.try_consume(session_id, cap, time.monotonic()):
                return _finish(
                    GuardResult(
                        allowed=False,
                        reason="delegate fan-out budget exceeded",
                        findings=(),
                        tier=tier,
                        param_scan_unsafe=False,
                    )
                )

        if normalized_name in self._config.tools.exempt:
            if not self._exempt_param_scan:
                return _finish(
                    GuardResult(
                        allowed=True,
                        reason="tool exempt per profile",
                        findings=(),
                        tier=tier,
                        param_scan_unsafe=False,
                    )
                )
            findings, param_scan_unsafe, param_scan_degraded = await self._scan_params(
                tool_params, session_id
            )
            return _finish(
                GuardResult(
                    allowed=True,
                    reason="exempt-with-scan",
                    findings=findings,
                    tier=tier,
                    param_scan_unsafe=param_scan_unsafe,
                    param_scan_degraded=param_scan_degraded,
                )
            )

        findings, param_scan_unsafe, param_scan_degraded = await self._scan_params(
            tool_params, session_id
        )

        if tier == "tier2":
            return _finish(
                GuardResult(
                    allowed=False,
                    reason="tier2: tool calls blocked",
                    findings=findings,
                    tier="tier2",
                    param_scan_unsafe=param_scan_unsafe,
                    param_scan_degraded=param_scan_degraded,
                )
            )

        if tier == "tier1":
            return _finish(
                GuardResult(
                    allowed=True,
                    reason="tier1: allowed with warnings",
                    findings=findings,
                    tier="tier1",
                    param_scan_unsafe=param_scan_unsafe,
                    param_scan_degraded=param_scan_degraded,
                )
            )

        return _finish(
            GuardResult(
                allowed=True,
                reason="allowed",
                findings=findings,
                tier=tier,
                param_scan_unsafe=param_scan_unsafe,
                param_scan_degraded=param_scan_degraded,
            )
        )

    def _record_selfmod_weight(self, session_id: str, finding: ScanFinding) -> None:
        """Record unclamped self-change risk in the shared tracker.

        See docs/architecture/rationale.md, "Scan contribution calibration"."""
        try:
            if self._frequency_tracker.requires_token:
                token = self._frequency_tracker.mint_token(session_id, self._pipeline.host_id)
                self._frequency_tracker.update(token, [finding.rule_id])
            else:
                self._frequency_tracker.update(session_id, [finding.rule_id])
        except Exception:
            _logger.warning(
                "selfmod frequency update failed for session=%s", session_id, exc_info=True
            )

    def _normalize_tool_name(self, tool_name: str) -> str:
        # See docs/architecture/rationale.md, "Tool alias canonicalization".
        name = canonicalize_tool_name(tool_name)
        aliases = dict(self._config.tools.aliases)
        if aliases:
            raw_aliases = {**DEFAULT_TOOL_ALIASES, **aliases}
        else:
            raw_aliases = dict(DEFAULT_TOOL_ALIASES)
        # See docs/architecture/rationale.md, "Tool alias canonicalization".
        combined = {canonicalize_tool_name(k): v for k, v in raw_aliases.items()}
        pre_alias = name
        resolved = combined.get(name, name)
        # Configured aliases cannot redirect to exempt targets; built-in aliases may.
        if (
            resolved != pre_alias
            and name in {canonicalize_tool_name(k) for k in aliases}
            and resolved.strip().casefold() in self._config.tools.exempt
        ):
            _logger.warning(
                "profile alias %r -> %r blocked: target is exempt (GUARD-03)",
                pre_alias,
                resolved,
            )
            resolved = pre_alias
        return resolved.strip().casefold()

    _fanout_cap = _fanout_cap

    def _state_to_tier(self, state: SessionState | None, *, include_rolling: bool = False) -> str:
        if include_rolling:
            return self._frequency_tracker.tier_for_state(state)
        if state is None:
            return "none"
        return evaluate_tier(state.last_score, self._config)

    def _read_state(self, session_id: str) -> SessionState | None:
        # Authenticated trackers require minted tokens for ancestor reads too.
        if self._secrets.session_secret is not None:
            token = self._frequency_tracker.mint_token(session_id, self._pipeline.host_id)
            return self._frequency_tracker.get_state(token)
        return self._frequency_tracker.get_state(session_id)

    def _derive_own_tier(self, session_id: str, *, include_rolling: bool = False) -> str:
        if self._frequency_tracker.is_terminated(session_id):
            return "tier3"
        return self._state_to_tier(self._read_state(session_id), include_rolling=include_rolling)

    def _derive_tier(self, session_id: str, *, include_rolling: bool = False) -> str:
        # See docs/architecture/rationale.md, "Inherited guard tiers".
        try:
            own = self._derive_own_tier(session_id, include_rolling=include_rolling)
            # No registry means own-tier enforcement only.
            if self._lineage is None:
                return own
            # See docs/architecture/rationale.md, "Inherited guard tiers".
            inherit_full = self._config.tools.lineage.enabled
            anc_tiers: list[str] = []
            for aid in self._lineage.ancestors(session_id):
                if self._frequency_tracker.is_terminated(aid):
                    # Ancestor termination survives eviction and cannot be disabled.
                    anc_tiers.append("tier3")
                elif inherit_full:
                    anc_tiers.append(
                        self._state_to_tier(self._read_state(aid), include_rolling=include_rolling)
                    )
            return max_tier(own, *anc_tiers)
        except Exception:
            _logger.exception(
                "lineage tier derivation failed for session=%s — returning tier3 fail-secure",
                session_id,
            )
            return "tier3"

    _scan_params = _scan_params
