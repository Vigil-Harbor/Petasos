"""Evaluate tool-call policy in order."""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from petasos.config.secrets import Secrets
from petasos.guard.fanout import SpawnBudget, _fanout_cap
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

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from petasos.config.sections import PetasosConfig
    from petasos.guard.surface import GuardrailSurface
    from petasos.hermes.home import HermesConfigResolution
    from petasos.pipeline import Pipeline
    from petasos.session.frequency import FrequencyTracker, SessionState
    from petasos.session.lineage import LineageRegistry


@dataclass(frozen=True)
class GuardResult:
    allowed: bool
    reason: str
    findings: tuple[ScanFinding, ...]
    tier: str
    param_scan_unsafe: bool
    # PET-112: True iff the param scan flipped unsafe AND a scanner errored, i.e. the
    # unsafe verdict is degraded-mode driven rather than finding-driven. Lets the plugin
    # honor the "ML failure blocks content" invariant independently of finding type
    # (degraded co-occurring with PII still blocks). Last + defaulted so every existing
    # construction stays valid. fail-mode-correct: gates on `not result.safe`, so
    # fail_mode="open" (scanner error doesn't flip safe) yields False → no block.
    param_scan_degraded: bool = False
    selfmod_target: str | None = None
    selfmod_finding: ScanFinding | None = None
    guardrail_kind: str | None = None

    def to_dict(self) -> dict[str, Any]:
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
        return d


_FEATURE_DISABLED = GuardResult(
    allowed=True,
    reason="feature disabled",
    findings=(),
    tier="none",
    param_scan_unsafe=False,
)


# PET-176 D3/D4: the per-scan weight step is min(tier1_prof, tier1_cfg) / this.
# 4 is calibrated, not arbitrary: divisor 3 stops tool dispatch after 6
# consecutive flagged ingestion reads (below the 8-read floor), divisor 5 drops
# the shipped cap to 3.0, losing sub-step benign immunity for a single
# 3.0-weight rule. See the PET-176 spec's D4 for the full derivation.
_SCAN_WEIGHT_CAP_DIVISOR: float = 4.0

# PET-176 D4 upper band: the raw weight of a maximally-poisoned 8,000-char scan
# window as measured for the ingestion seam. Once the per-scan step exceeds it,
# no scan can ever reach one step, every scan quantizes to 0.0, and the session
# backstop is inert without failing anything -- hence the tripwire.
_MAX_POISONED_SCAN_WEIGHT: float = 80.0


class ToolCallGuard:
    def __init__(
        self,
        pipeline: Pipeline,
        frequency_tracker: FrequencyTracker,
        config: PetasosConfig,
        *,
        exempt_param_scan: bool = True,
        lineage: LineageRegistry | None = None,
        home: HermesConfigResolution | None = None,
        secrets: Secrets | None = None,
        protected_paths: Callable[[], Iterable[str]] | None = None,
        guardrail_surface: Callable[[], GuardrailSurface] | None = None,
    ) -> None:
        self._pipeline = pipeline
        self._frequency_tracker = frequency_tracker
        self._config = config
        self._secrets = secrets if secrets is not None else Secrets()
        self._selfmod_home = home
        self._exempt_param_scan = exempt_param_scan
        # Lineage edge store. None leaves the chain walk and pinning off.
        self._lineage = lineage
        # When set, self-modification checks this set instead of discovering
        # a host layout. None keeps the discovery used by existing callers.
        self._protected_paths = protected_paths
        self._guardrail_surface = guardrail_surface

        # Delegate tool names are stored raw in config; normalize them once
        # here through the guard's own normalizer so recognition matches every
        # other tool name.
        self._delegate_tool_names = self._delegates_from(config)
        # A delegate must never be exempt — an exempt delegate would skip the
        # tier ladder, defeating the spray ceiling on the normal path.
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
        # PET-176 D3/D4: warn-once latch for the scan_weight_cap tripwires
        # (non-positive tier1 / sub-2.0 tier2:tier1 ratio / sub-3.0 step).
        # Plain boolean in the _selfmod_empty_warned / _ring_overflow_warned
        # idiom; reset in apply_config because the warned-about thresholds are
        # reconfigurable.
        self._cap_threshold_warned: bool = False

    def session_tier(self, session_id: str) -> str:
        """The tier enforcement uses for ``session_id``, including an inherited one.

        The same derivation ``evaluate`` reads. An internal failure is tier 3.
        """
        return self._derive_tier(session_id)

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

    def apply_config(self, new_config: PetasosConfig) -> None:
        """PET-126: live-reconfigure the guard in place (spec D2/D5).

        Calls ``validate_config`` FIRST, so a D8 violation or a malformed
        ``frequency_weights`` map aborts before any mutation. Then:

        - merge-preserves ``session_secret`` into the guard's OWN ``_config`` via
          ``replace(new_config, session_secret=<live>)`` so ``_read_state``'s mint
          decision stays in lockstep with the immutable tracker secret. A
          ``None``<->non-None presence flip would otherwise force tier3 fail-secure
          on every session (FREQ-03, Decision 2);
        - recomputes ``_delegate_tool_names`` through the guard's own normalizer;
        - resizes the ``_spawn_budget`` window in place (preserving counters);
        - delegates to ``_frequency_tracker.apply_config`` (which holds the
          tracker secret immutable). Since PET-176 D1 the tracker may be the
          pipeline's own injected instance rather than a guard-private one, in
          which case a reference-plugin reconfigure applies the same config to
          it twice; ``apply_config`` is idempotent over an already-validated
          config, so the second application is a no-op (D7).

        Preserved: ``SpawnBudget._events`` / ``_last_sweep``, the guard tracker's
        session/tombstone state, and ``_config.session_secret``.
        """
        self.validate_config(new_config)
        self._config = new_config
        self._delegate_tool_names = self._delegates_from(new_config)
        self._spawn_budget.set_window(new_config.tools.fanout.window_seconds)
        # Thresholds are reconfigurable, so the warned-about condition can
        # clear; re-arm the cap tripwire.
        self._cap_threshold_warned = False
        self._frequency_tracker.apply_config(self._config)

    @property
    def scan_weight_cap(self) -> float:
        """Per-scan weight STEP for large input (ingestion results, tool parameters).

        A capped scan contributes exactly this value or exactly 0.0, never
        anything between (PET-176 D2 quantizes rather than truncates). Sized so
        no single scan can cross a tier. The step is the config tree's tier 1
        divided by the cap divisor. A profile's tier thresholds are not read.
        """
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
        # D4's operator tripwires, on the GOVERNING axis (the tier2 read is what
        # stops tool dispatch). Denominator: the same min-of-both tier1 the cap
        # uses. Numerator: min-of-both tier2, NOT the guard-observed tier2 the
        # published identity uses -- min <= tier2_guard, so this can only
        # over-warn, never miss. Deliberate. Sits AFTER the tier1 <= 0 return,
        # or the division raises ZeroDivisionError out of a property read inside
        # _scan_params, whose bare `except Exception` would convert it into
        # "every tool call unsafe". Ratio is checked before either step band
        # because a sub-ratio configuration is the most urgent of the three.
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
        # Step 0: Feature gate
        if not self._pipeline.is_feature_enabled("tool_guard"):
            return _FEATURE_DISABLED

        # Step 1: Normalize tool name
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

        # Step 1.5: Selfmod classification (total; never raises; builds no state)
        selfmod = self._classify_selfmod(canon_pre_alias, tool_params)
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

        # Step 2: Derive tier
        tier = self._derive_tier(session_id)

        # Step 3: Tier 3 → block
        if tier == "tier3":
            return _finish(
                GuardResult(
                    allowed=False,
                    reason="session terminated (tier3)",
                    findings=(),
                    tier="tier3",
                    param_scan_unsafe=False,
                )
            )

        # Step 3.5: Delegation fan-out gate (PET-107 C).
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

        # Step 4: Exempt check
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

        # Step 5: Scan params
        findings, param_scan_unsafe, param_scan_degraded = await self._scan_params(
            tool_params, session_id
        )

        # Step 6: Tier 2 → block
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

        # Step 7: Tier 1 with unsafe → warn
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

        # Step 8: Clean / no tier → allow
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
        """Apply the selfmod frequency update to the guard's tracker (Decision 3).

        Since PET-176 D1 that tracker is the same one the pipeline's ingestion
        and parameter scans write, so selfmod weight composes into one
        per-session score. It stays deliberately UNCLAMPED: a selfmod finding is
        a single rule id from a parameter-sized scan, bounded at 10.0, and a
        config-write attempt moving a full tier step immediately is the designed
        response, not an accident of the PET-176 clamp.
        """
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
        # PET-118: canonicalize (strip→NFKC→homoglyph→casefold→ns-strip→strip) is the
        # alias-free shared primitive; alias resolution below layers on top of it. The
        # plugin's classification reuses canonicalize_tool_name WITHOUT this alias layer,
        # so the two normalizers never diverge (D-CANON / D-EQUIV).
        name = canonicalize_tool_name(tool_name)
        aliases = dict(self._config.tools.aliases)
        if aliases:
            raw_aliases = {**DEFAULT_TOOL_ALIASES, **aliases}
        else:
            raw_aliases = dict(DEFAULT_TOOL_ALIASES)
        # PET-121: canonicalize alias-map KEYS into the same space as `name`, so an alias keyed
        # with a camel / _tool-suffixed form still fires once the shared primitive strips the
        # suffix or splits the camel (incoming `custom_tool` -> `custom`; without this the raw
        # `custom_tool` key would silently never match). Default keys are canonical-stable, so
        # this is a no-op on them; profile keys collapsing to the same canonical form: last wins.
        combined = {canonicalize_tool_name(k): v for k, v in raw_aliases.items()}
        pre_alias = name
        resolved = combined.get(name, name)
        # GUARD-03: a PROFILE-INTRODUCED alias must not redirect onto an exempt key.
        # Default aliases (bash->exec) onto an operator-exempted target stay legal (D8).
        # Compare `name` against the profile's CANONICALIZED keys (PET-121: same space as name).
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

    def _state_to_tier(self, state: SessionState | None) -> str:
        if state is None:
            return "none"
        return evaluate_tier(state.last_score, self._config)

    def _read_state(self, session_id: str) -> SessionState | None:
        # Mirror the own-session path: with a session_secret set, get_state is
        # keyed by a per-id minted token, not the raw id (PET-31).
        if self._secrets.session_secret is not None:
            token = self._frequency_tracker.mint_token(session_id, self._pipeline.host_id)
            return self._frequency_tracker.get_state(token)
        return self._frequency_tracker.get_state(session_id)

    def _derive_own_tier(self, session_id: str) -> str:
        if self._frequency_tracker.is_terminated(session_id):
            return "tier3"
        return self._state_to_tier(self._read_state(session_id))

    def _derive_tier(self, session_id: str) -> str:
        # The whole derivation is wrapped fail-SECURE: any internal error — the
        # own-tier read (_read_state → mint_token can raise on a malformed
        # session_id or unset host_id when session_secret is set), a terminated
        # ancestor lookup, or a max_tier ValueError on an unexpected tier string
        # — logs and returns tier3, mirroring evaluate_tier. It must never escape
        # into the reference plugin's fail-OPEN evaluate catch.
        try:
            # Step 1: own tier (today's logic).
            own = self._derive_own_tier(session_id)
            # Step 2: no lineage data wired (host sub-agent hooks absent) → own
            # only. This is the graceful-degradation branch (lineage is None).
            if self._lineage is None:
                return own
            # Steps 3-4: a child's tier is max(own, worst ancestor) read LIVE at
            # evaluation time (D5). subagent_lineage_enabled gates the OPTIONAL
            # tier-1/2 inheritance, but a terminated ancestor's tier-3 floor (D4)
            # has NO config override — "Tier 3 escalation cannot be disabled" — so
            # the chain is still walked for tombstones even when the flag is off.
            inherit_full = self._config.tools.lineage.enabled
            anc_tiers: list[str] = []
            for aid in self._lineage.ancestors(session_id):
                if self._frequency_tracker.is_terminated(aid):
                    # Tombstone-backed: a terminated ancestor forces tier3 even
                    # post-eviction (closes orphaned termination) and even when
                    # full inheritance is config-disabled (D4 floor, no override).
                    anc_tiers.append("tier3")
                elif inherit_full:
                    anc_tiers.append(self._state_to_tier(self._read_state(aid)))
            return max_tier(own, *anc_tiers)
        except Exception:
            _logger.exception(
                "lineage tier derivation failed for session=%s — returning tier3 fail-secure",
                session_id,
            )
            return "tier3"

    _scan_params = _scan_params
