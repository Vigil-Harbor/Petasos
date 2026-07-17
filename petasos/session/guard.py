from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, NamedTuple

from petasos._types import ScanFinding, Severity
from petasos.normalize import _NAMESPACE_PREFIX_RE as _NAMESPACE_PREFIX_RE
from petasos.normalize import canonicalize_tool_name
from petasos.session._safe_json import safe_json_dumps
from petasos.session.escalation import derive_tier, evaluate_tier, max_tier

_logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from petasos.config import PetasosConfig
    from petasos.pipeline import Pipeline
    from petasos.session.frequency import FrequencyTracker, SessionState
    from petasos.session.lineage import LineageRegistry
    from petasos.session.profiles import ResolvedProfile

READ_ONLY_TOOLS: frozenset[str] = frozenset(
    {
        "read_file",
        "search",
        "list_directory",
        "session_search",
        "web_search",
        "web_extract",
        "vision_analyze",
        "mcp_vigil_harbor_memory_search",
        "mcp_vigil_harbor_memory_fetch",
        "mcp_vigil_harbor_memory_list",
        "mcp_vigil_harbor_memory_query",
        "mcp_vigil_harbor_memory_sources",
        "mcp_vigil_harbor_memory_status",
        "mcp_plane_list_work_items",
        "mcp_plane_retrieve_work_item",
        "mcp_plane_retrieve_work_item_by_identifier",
        "mcp_plane_list_projects",
    }
)

_READ_ONLY_CANON: frozenset[str] = frozenset(
    c for c in (canonicalize_tool_name(t) for t in READ_ONLY_TOOLS) if c
)


class _SelfmodMatch(NamedTuple):
    rule_id: str
    target: str


# Recorded as the selfmod target when the fail-secure depth-overflow branch fires.
# Deliberately NOT an owned path: the overflow flag means the args could not be
# fully traversed, so no specific path was matched and naming one would mislead
# triage. Public-ish (no underscore) so the reference plugin and tests can
# recognize the sentinel without string-copying it.
SELFMOD_DEPTH_OVERFLOW_TARGET = "<argument-depth-overflow>"


DEFAULT_TOOL_ALIASES: MappingProxyType[str, str] = MappingProxyType(
    {
        "bash": "exec",
        "shell": "exec",
        "terminal": "exec",
        "file_read": "read",
        "read_file": "read",
        "file_write": "write",
        "write_file": "write",
        "web_fetch": "browser",
        "web_search": "browser",
        "http_request": "browser",
    }
)

_MAX_PARAM_TEXT_LEN = 1_000_000


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

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "allowed": self.allowed,
            "reason": self.reason,
            "findings": [f.to_dict() for f in self.findings],
            "tier": self.tier,
            "param_scan_unsafe": self.param_scan_unsafe,
            "param_scan_degraded": self.param_scan_degraded,
            "selfmod_target": self.selfmod_target,
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


class SpawnBudget:
    """Per-session rolling-window spawn counter for the delegation fan-out gate.

    PET-107 Option C. ``try_consume`` prunes the session's window, compares the
    live count to the (tier-adjusted) cap, and on pass appends the timestamp —
    all in one critical section so the read-check-append is atomic (closes the
    concurrent-spawn TOCTOU two children racing against a budget of 1).

    The consumed session's deque is dropped once its window empties; an amortized
    global sweep (at most once per ``window_seconds``) drops the deques of
    sessions that delegated once and were never touched again. Together these
    bound memory by the count of sessions that spawned within roughly the last
    window, not by every distinct session ever seen.
    """

    def __init__(self, window_seconds: float) -> None:
        self._window = window_seconds
        self._lock = threading.Lock()
        self._events: dict[str, deque[float]] = {}
        self._last_sweep = 0.0

    def set_window(self, seconds: float) -> None:
        """PET-126: rebind the rolling-window length in place.

        Rebinds ``_window`` only: never resets ``_last_sweep`` or ``_events``, so
        buffered spawn timestamps survive a reconfigure. A *shrink* simply
        re-interprets them against the smaller cutoff on the next ``try_consume``
        (older events expire sooner). Taken under ``_lock`` because ``try_consume``
        reads ``_window`` under the same lock.
        """
        with self._lock:
            self._window = seconds

    def try_consume(self, session_id: str, cap: int, now: float) -> bool:
        with self._lock:
            cutoff = now - self._window
            # Amortized global sweep (<= once per window): drop any session whose
            # entire window has expired. The per-session prune below only fires
            # when THAT session is consumed again, so without this a one-shot
            # delegate would leave a stale deque in _events forever and the map
            # would grow with distinct session IDs instead of active windows.
            if now - self._last_sweep >= self._window:
                stale = [sid for sid, ev in self._events.items() if not ev or ev[-1] <= cutoff]
                for sid in stale:
                    del self._events[sid]
                self._last_sweep = now
            dq = self._events.get(session_id)
            if dq is not None:
                while dq and dq[0] <= cutoff:
                    dq.popleft()
                if not dq:
                    del self._events[session_id]
                    dq = None
            count = len(dq) if dq is not None else 0
            if count >= cap:
                return False
            if dq is None:
                dq = deque()
                self._events[session_id] = dq
            dq.append(now)
            return True


class ToolCallGuard:
    def __init__(
        self,
        pipeline: Pipeline,
        frequency_tracker: FrequencyTracker,
        config: PetasosConfig,
        profile: ResolvedProfile | None = None,
        *,
        exempt_param_scan: bool = True,
        lineage: LineageRegistry | None = None,
    ) -> None:
        self._pipeline = pipeline
        self._frequency_tracker = frequency_tracker
        self._config = config
        self._profile = profile
        self._exempt_param_scan = exempt_param_scan
        # PET-107 A: lineage edge store (None → chain walk + pinning disabled,
        # behavior is byte-for-byte today's).
        self._lineage = lineage

        # PET-107 C: delegate tool names are stored RAW in config; normalize
        # them once here through the guard's OWN _normalize_tool_name (never a
        # parallel normalizer) so recognition at Step 3.5 matches the same
        # casefold/homoglyph/alias/namespace handling applied to every tool.
        self._delegate_tool_names: frozenset[str] = frozenset(
            n for n in (self._normalize_tool_name(raw) for raw in config.delegate_tool_names) if n
        )
        # D8: a delegate must never be exempt — an exempt delegate would skip the
        # tier ladder, defeating the spray ceiling on the normal path.
        if self._profile is not None:
            exempt_overlap = self._delegate_tool_names & self._profile.tool_exempt_list
            if exempt_overlap:
                raise ValueError(
                    f"delegate tool name(s) {sorted(exempt_overlap)} appear in the profile "
                    f"exempt list; a delegate must not be exempt (it would skip the tier ladder)"
                )
        if config.delegate_fanout_enabled and not self._delegate_tool_names:
            _logger.warning(
                "delegate_fanout_enabled but delegate_tool_names is empty (or all normalized "
                "away) — the delegation fan-out gate is inert"
            )
        self._spawn_budget = SpawnBudget(config.delegate_fanout_window_seconds)
        self._selfmod_owned_cache: tuple[float, frozenset[str]] = (0.0, frozenset())
        self._selfmod_empty_warned: bool = False

    def selfmod_target_paths(self) -> frozenset[str]:
        """Build the owned-path set from ``_paths.py`` resolvers with 1 s TTL cache."""
        now = time.monotonic()
        ts, cached = self._selfmod_owned_cache
        if now - ts < 1.0 and cached:
            return cached
        try:
            from petasos.console._paths import (
                list_hermes_profiles,
                resolve_hermes_config_path,
                spool_path,
                spool_rot_path,
            )

            raw_entries: list[str] = []
            res = resolve_hermes_config_path()
            raw_entries.append(str(res.path))
            for prof in list_hermes_profiles():
                raw_entries.append(prof["path"])
            raw_entries.append(spool_path())
            raw_entries.append(spool_rot_path())

            result: set[str] = set()
            for raw in raw_entries:
                p = Path(raw)
                if not p.is_absolute():
                    continue
                try:
                    resolved = str(p.resolve(strict=False))
                except OSError:
                    continue
                parts = Path(resolved).parts
                if len(parts) < 3:
                    continue
                result.add(os.path.normcase(resolved))

            owned = frozenset(result)
            if not owned and not self._selfmod_empty_warned:
                _logger.warning("selfmod_target_paths: owned set is empty after hygiene")
                self._selfmod_empty_warned = True
            if owned:
                self._selfmod_empty_warned = False
            self._selfmod_owned_cache = (now, owned)
            return owned
        except Exception:
            _logger.debug("selfmod_target_paths: failed to build owned set", exc_info=True)
            return cached or frozenset()

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

    def _classify_selfmod(
        self, canon_pre_alias: str, tool_params: dict[str, Any]
    ) -> _SelfmodMatch | None:
        """Total: never raises. Returns the match or None."""
        try:
            if canon_pre_alias in _READ_ONLY_CANON:
                return None
            owned = self.selfmod_target_paths()
            if not owned:
                return None

            def _has_sep(s: str) -> bool:
                return "/" in s or "\\" in s or os.sep in s

            top_level_strs: list[str] = []
            all_parts: list[str] = []
            for value in tool_params.values():
                if value is None:
                    continue
                if isinstance(value, str):
                    top_level_strs.append(value)
                    all_parts.append(value)
                else:
                    all_parts.extend(self._extract_leaf_strings(value))

            overflow = self._EXTRACT_OVERFLOW in all_parts
            if overflow:
                return _SelfmodMatch(
                    rule_id="petasos.selfmod.config_ref",
                    target=SELFMOD_DEPTH_OVERFLOW_TARGET,
                )

            any_sep = any(_has_sep(p) for p in all_parts)
            if not any_sep:
                return None

            def _normalize_for_compare(s: str) -> str:
                s = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), s)
                s = s.replace("\\\\", "/").replace("\\", "/").replace("/", os.sep)
                s = os.path.normcase(s)
                try:
                    p = Path(s)
                    if p.is_absolute():
                        s = os.path.normcase(str(p.resolve(strict=False)))
                except (OSError, ValueError):
                    pass
                return s

            for tls in top_level_strs:
                normed = _normalize_for_compare(tls)
                for entry in owned:
                    if normed == entry:
                        return _SelfmodMatch(rule_id="petasos.selfmod.config_write", target=entry)

            for part in all_parts:
                normed = _normalize_for_compare(part)
                for entry in owned:
                    if entry in normed:
                        return _SelfmodMatch(rule_id="petasos.selfmod.config_ref", target=entry)

            return None
        except Exception:
            _logger.warning("selfmod classifier error for tool=%s", canon_pre_alias, exc_info=True)
            return None

    def validate_config(self, new_config: PetasosConfig) -> None:
        """Dry-run validation of a candidate config: raises, never mutates (D5/D8).

        Two guard-only invariants that ``PetasosConfig.__post_init__`` does not
        cover, run here BEFORE any commit so ``apply_config`` is all-or-nothing:

        1. D8 exempt-overlap: a delegate tool must never also be profile-exempt (an
           exempt delegate would skip the tier ladder). Mirrors the ``__init__``
           check against the candidate's normalized delegate set.
        2. ``frequency_weights`` parse trial: the full glob-position and
           non-negative/finite weight validation lives in ``FrequencyTracker``,
           not in ``__post_init__``. Trial-parse the candidate so a malformed map
           is caught here, before the guard's tracker is reconfigured.
        """
        if self._profile is not None:
            candidate_delegates = frozenset(
                n
                for n in (self._normalize_tool_name(raw) for raw in new_config.delegate_tool_names)
                if n
            )
            exempt_overlap = candidate_delegates & self._profile.tool_exempt_list
            if exempt_overlap:
                raise ValueError(
                    f"delegate tool name(s) {sorted(exempt_overlap)} appear in the profile "
                    f"exempt list; a delegate must not be exempt (it would skip the tier ladder)"
                )
        # Weight-parse trial: a throwaway FrequencyTracker re-runs the full weight
        # validation with no side effects beyond the parse, so a malformed
        # frequency_weights map raises here, before any commit.
        from petasos.session.frequency import FrequencyTracker

        FrequencyTracker(new_config)

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
        - delegates to its OWN ``_frequency_tracker.apply_config`` (which holds the
          tracker secret immutable).

        Preserved: ``SpawnBudget._events`` / ``_last_sweep``, the guard tracker's
        session/tombstone state, and ``_config.session_secret``.
        """
        self.validate_config(new_config)
        self._config = replace(new_config, session_secret=self._config.session_secret)
        self._delegate_tool_names = frozenset(
            n
            for n in (self._normalize_tool_name(raw) for raw in new_config.delegate_tool_names)
            if n
        )
        self._spawn_budget.set_window(new_config.delegate_fanout_window_seconds)
        self._frequency_tracker.apply_config(self._config)

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

        # Step 2: Derive tier
        tier = self._derive_tier(session_id)

        # Step 3: Tier 3 → block
        if tier == "tier3":
            result = GuardResult(
                allowed=False,
                reason="session terminated (tier3)",
                findings=(),
                tier="tier3",
                param_scan_unsafe=False,
                selfmod_target=selfmod.target if selfmod else None,
                selfmod_finding=selfmod_finding,
            )
            if selfmod is not None:
                self._pipeline.record_selfmod(session_id, selfmod_finding)  # type: ignore[arg-type]
            return result

        # Step 3.5: Delegation fan-out gate (PET-107 C).
        if self._config.delegate_fanout_enabled and normalized_name in self._delegate_tool_names:
            cap = self._fanout_cap(tier)
            if not self._spawn_budget.try_consume(session_id, cap, time.monotonic()):
                result = GuardResult(
                    allowed=False,
                    reason="delegate fan-out budget exceeded",
                    findings=(),
                    tier=tier,
                    param_scan_unsafe=False,
                    selfmod_target=selfmod.target if selfmod else None,
                    selfmod_finding=selfmod_finding,
                )
                if selfmod is not None and selfmod_finding is not None:
                    self._record_selfmod_weight(session_id, selfmod_finding)
                    self._pipeline.record_selfmod(session_id, selfmod_finding)
                return result

        # Step 4: Exempt check
        if self._profile and normalized_name in self._profile.tool_exempt_list:
            if not self._exempt_param_scan:
                result = GuardResult(
                    allowed=True,
                    reason="tool exempt per profile",
                    findings=(),
                    tier=tier,
                    param_scan_unsafe=False,
                    selfmod_target=selfmod.target if selfmod else None,
                    selfmod_finding=selfmod_finding,
                )
                if selfmod is not None and selfmod_finding is not None:
                    self._record_selfmod_weight(session_id, selfmod_finding)
                    self._pipeline.record_selfmod(session_id, selfmod_finding)
                return result
            findings, param_scan_unsafe, param_scan_degraded = await self._scan_params(
                tool_params, session_id
            )
            result = GuardResult(
                allowed=True,
                reason="exempt-with-scan",
                findings=findings,
                tier=tier,
                param_scan_unsafe=param_scan_unsafe,
                param_scan_degraded=param_scan_degraded,
                selfmod_target=selfmod.target if selfmod else None,
                selfmod_finding=selfmod_finding,
            )
            if selfmod is not None and selfmod_finding is not None:
                self._record_selfmod_weight(session_id, selfmod_finding)
                self._pipeline.record_selfmod(session_id, selfmod_finding)
            return result

        # Step 5: Scan params
        findings, param_scan_unsafe, param_scan_degraded = await self._scan_params(
            tool_params, session_id
        )

        # Step 6: Tier 2 → block
        if tier == "tier2":
            result = GuardResult(
                allowed=False,
                reason="tier2: tool calls blocked",
                findings=findings,
                tier="tier2",
                param_scan_unsafe=param_scan_unsafe,
                param_scan_degraded=param_scan_degraded,
                selfmod_target=selfmod.target if selfmod else None,
                selfmod_finding=selfmod_finding,
            )
            if selfmod is not None and selfmod_finding is not None:
                self._record_selfmod_weight(session_id, selfmod_finding)
                self._pipeline.record_selfmod(session_id, selfmod_finding)
            return result

        # Step 7: Tier 1 with unsafe → warn
        if tier == "tier1":
            result = GuardResult(
                allowed=True,
                reason="tier1: allowed with warnings",
                findings=findings,
                tier="tier1",
                param_scan_unsafe=param_scan_unsafe,
                param_scan_degraded=param_scan_degraded,
                selfmod_target=selfmod.target if selfmod else None,
                selfmod_finding=selfmod_finding,
            )
            if selfmod is not None and selfmod_finding is not None:
                self._record_selfmod_weight(session_id, selfmod_finding)
                self._pipeline.record_selfmod(session_id, selfmod_finding)
            return result

        # Step 8: Clean / no tier → allow
        result = GuardResult(
            allowed=True,
            reason="allowed",
            findings=findings,
            tier=tier,
            param_scan_unsafe=param_scan_unsafe,
            param_scan_degraded=param_scan_degraded,
            selfmod_target=selfmod.target if selfmod else None,
            selfmod_finding=selfmod_finding,
        )
        if selfmod is not None and selfmod_finding is not None:
            self._record_selfmod_weight(session_id, selfmod_finding)
            self._pipeline.record_selfmod(session_id, selfmod_finding)
        return result

    def _record_selfmod_weight(self, session_id: str, finding: ScanFinding) -> None:
        """Apply the selfmod frequency update to the guard's own tracker (Decision 3)."""
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
        if self._profile and self._profile.tool_alias_map:
            raw_aliases = {**DEFAULT_TOOL_ALIASES, **self._profile.tool_alias_map}
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
            and self._profile
            and name in {canonicalize_tool_name(k) for k in self._profile.tool_alias_map}
            and resolved.strip().casefold() in self._profile.tool_exempt_list
        ):
            _logger.warning(
                "profile alias %r -> %r blocked: target is exempt (GUARD-03)",
                pre_alias,
                resolved,
            )
            resolved = pre_alias
        return resolved.strip().casefold()

    def _fanout_cap(self, tier: str) -> int:
        """Tier-adjusted fan-out cap. tier3 is already blocked at Step 3, so it
        never reaches here; tier2 is tightest (1) and is also blocked at Step 6,
        so Step 3.5 only accounts the attempt for a tier-2 delegate."""
        base = self._config.delegate_max_fanout_per_window
        if tier == "tier1":
            return max(1, base // 2)
        if tier == "tier2":
            return 1
        return base  # none / below-threshold

    def _state_to_tier(self, state: SessionState | None) -> str:
        if state is None:
            return "none"
        if self._profile and self._profile.tier_thresholds:
            t = self._profile.tier_thresholds
            return derive_tier(state.last_score, t.tier1, t.tier2, t.tier3)
        return evaluate_tier(state.last_score, self._config)

    def _read_state(self, session_id: str) -> SessionState | None:
        # Mirror the own-session path: with a session_secret set, get_state is
        # keyed by a per-id minted token, not the raw id (PET-31).
        if self._config.session_secret is not None:
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
            inherit_full = self._config.subagent_lineage_enabled
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

    async def _scan_params(
        self,
        tool_params: dict[str, Any],
        session_id: str,
    ) -> tuple[tuple[ScanFinding, ...], bool, bool]:
        # PET-112: returns (findings, param_scan_unsafe, param_scan_degraded). The third
        # element is True only when the unsafe verdict co-occurs with a scanner error
        # (degraded-mode), so the plugin can block on degradation regardless of finding
        # type. The two error early-returns force degraded=True regardless of fail_mode —
        # a deliberate fail-safe on guard-internal/hook failure; the fail-mode-correct
        # `not result.safe` gate applies to the normal finding-driven path only.
        try:
            if not tool_params:
                return (), False, False

            parts: list[str] = []
            for value in tool_params.values():
                if value is None:
                    continue
                if isinstance(value, str):
                    parts.append(value)
                else:
                    parts.append(safe_json_dumps(value))

            param_text = "\n".join(parts)
            if not param_text:
                return (), False, False

            if len(param_text) > _MAX_PARAM_TEXT_LEN:
                _logger.warning(
                    "param text exceeds length cap (%d > %d chars), truncating; session=%s",
                    len(param_text),
                    _MAX_PARAM_TEXT_LEN,
                    session_id,
                )
                param_text = param_text[:_MAX_PARAM_TEXT_LEN]

            result = await self._pipeline.inspect(
                param_text, direction="outbound", session_id=session_id
            )

            if result.errors and not result.findings:
                _logger.warning(
                    "param scan errored without findings, marking unsafe; error_count=%d",
                    len(result.errors),
                )
                return (), True, True

            param_scan_unsafe = not result.safe
            scanner_errored = any(r.error is not None for r in result.scanner_results)
            param_scan_degraded = param_scan_unsafe and scanner_errored
            findings = result.findings
            return findings, param_scan_unsafe, param_scan_degraded
        except Exception:
            _logger.exception("_scan_params failed unexpectedly, marking unsafe")
            return (), True, True
