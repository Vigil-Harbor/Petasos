from __future__ import annotations

import logging
import re
import threading
import time
import unicodedata
from collections import deque
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from petasos.normalize import _HOMOGLYPH_TABLE
from petasos.session._safe_json import safe_json_dumps
from petasos.session.escalation import derive_tier, evaluate_tier, max_tier

_logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from petasos._types import ScanFinding
    from petasos.config import PetasosConfig
    from petasos.pipeline import Pipeline
    from petasos.session.frequency import FrequencyTracker, SessionState
    from petasos.session.lineage import LineageRegistry
    from petasos.session.profiles import ResolvedProfile

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

_NAMESPACE_PREFIX_RE = re.compile(r"^(?:mcp__[a-zA-Z0-9_]+?__|hermes__)")

_MAX_PARAM_TEXT_LEN = 1_000_000


@dataclass(frozen=True)
class GuardResult:
    allowed: bool
    reason: str
    findings: tuple[ScanFinding, ...]
    tier: str
    param_scan_unsafe: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "findings": [f.to_dict() for f in self.findings],
            "tier": self.tier,
            "param_scan_unsafe": self.param_scan_unsafe,
        }


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

    The per-session deque is dropped once its window empties, so memory is bound
    by the count of sessions that have spawned within ``window_seconds``.
    """

    def __init__(self, window_seconds: float) -> None:
        self._window = window_seconds
        self._lock = threading.Lock()
        self._events: dict[str, deque[float]] = {}

    def try_consume(self, session_id: str, cap: int, now: float) -> bool:
        with self._lock:
            cutoff = now - self._window
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
        normalized_name = self._normalize_tool_name(tool_name)
        if not normalized_name:
            return GuardResult(
                allowed=False,
                reason="invalid tool name: empty after normalization",
                findings=(),
                tier="none",
                param_scan_unsafe=False,
            )

        # Step 2: Derive tier
        tier = self._derive_tier(session_id)

        # Step 3: Tier 3 → block
        if tier == "tier3":
            return GuardResult(
                allowed=False,
                reason="session terminated (tier3)",
                findings=(),
                tier="tier3",
                param_scan_unsafe=False,
            )

        # Step 3.5: Delegation fan-out gate (PET-107 C). Runs AFTER the tier-3
        # block and BEFORE the Step-4 exempt check so the budget applies
        # regardless of exempt status (D8 guarantees a delegate is never exempt,
        # so this governs spawn-attempt accounting, not an exempt bypass). The
        # budget counts ATTEMPTS — a spawn later blocked by param-scan-unsafe
        # still consumed budget, since a session spamming delegate_task is
        # exactly the spray to rate-limit regardless of per-call content outcome.
        if self._config.delegate_fanout_enabled and normalized_name in self._delegate_tool_names:
            cap = self._fanout_cap(tier)
            if not self._spawn_budget.try_consume(session_id, cap, time.monotonic()):
                return GuardResult(
                    allowed=False,
                    reason="delegate fan-out budget exceeded",
                    findings=(),
                    tier=tier,
                    param_scan_unsafe=False,
                )

        # Step 4: Exempt check
        if self._profile and normalized_name in self._profile.tool_exempt_list:
            if not self._exempt_param_scan:
                return GuardResult(
                    allowed=True,
                    reason="tool exempt per profile",
                    findings=(),
                    tier=tier,
                    param_scan_unsafe=False,
                )
            findings, param_scan_unsafe = await self._scan_params(tool_params, session_id)
            return GuardResult(
                allowed=True,
                reason="exempt-with-scan",
                findings=findings,
                tier=tier,
                param_scan_unsafe=param_scan_unsafe,
            )

        # Step 5: Scan params
        findings, param_scan_unsafe = await self._scan_params(tool_params, session_id)

        # Step 6: Tier 2 → block
        if tier == "tier2":
            return GuardResult(
                allowed=False,
                reason="tier2: tool calls blocked",
                findings=findings,
                tier="tier2",
                param_scan_unsafe=param_scan_unsafe,
            )

        # Step 7: Tier 1 with unsafe → warn
        if tier == "tier1":
            return GuardResult(
                allowed=True,
                reason="tier1: allowed with warnings",
                findings=findings,
                tier="tier1",
                param_scan_unsafe=param_scan_unsafe,
            )

        # Step 8: Clean / no tier → allow
        return GuardResult(
            allowed=True,
            reason="allowed",
            findings=findings,
            tier=tier,
            param_scan_unsafe=param_scan_unsafe,
        )

    def _normalize_tool_name(self, tool_name: str) -> str:
        name = tool_name.strip()
        name = unicodedata.normalize("NFKC", name)
        name = name.translate(_HOMOGLYPH_TABLE)
        name = name.casefold()
        name = _NAMESPACE_PREFIX_RE.sub("", name)
        if self._profile and self._profile.tool_alias_map:
            combined = {**DEFAULT_TOOL_ALIASES, **self._profile.tool_alias_map}
        else:
            combined = dict(DEFAULT_TOOL_ALIASES)
        pre_alias = name
        resolved = combined.get(name, name)
        # GUARD-03: a PROFILE-INTRODUCED alias must not redirect onto an exempt key.
        # Default aliases (bash->exec) onto an operator-exempted target stay legal (D8).
        if (
            resolved != pre_alias
            and self._profile
            and name in self._profile.tool_alias_map
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
        # Step 1: own tier (today's logic). Computed outside the fail-secure
        # wrapper so its existing error behavior is preserved.
        own = self._derive_own_tier(session_id)
        # Step 2: lineage off / disabled → own only (byte-for-byte today's).
        if self._lineage is None or not self._config.subagent_lineage_enabled:
            return own
        # Steps 3-4: a child's tier is max(own, worst ancestor) read LIVE at
        # evaluation time (D5). The whole chain walk is wrapped fail-SECURE — an
        # internal error (including a max_tier ValueError on an unexpected tier
        # string) logs and returns tier3, mirroring evaluate_tier; it must never
        # escape into the reference plugin's fail-OPEN evaluate catch.
        try:
            anc_tiers: list[str] = []
            for aid in self._lineage.ancestors(session_id):
                if self._frequency_tracker.is_terminated(aid):
                    # Tombstone-backed: a terminated ancestor forces tier3 even
                    # post-eviction (closes orphaned termination).
                    anc_tiers.append("tier3")
                else:
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
    ) -> tuple[tuple[ScanFinding, ...], bool]:
        try:
            if not tool_params:
                return (), False

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
                return (), False

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
                return (), True

            param_scan_unsafe = not result.safe
            findings = result.findings
            return findings, param_scan_unsafe
        except Exception:
            _logger.exception("_scan_params failed unexpectedly, marking unsafe")
            return (), True
