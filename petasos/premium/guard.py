from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from petasos.premium.escalation import evaluate_tier

_logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from petasos._types import ScanFinding
    from petasos.config import PetasosConfig
    from petasos.pipeline import Pipeline
    from petasos.premium.frequency import FrequencyTracker
    from petasos.premium.profiles import ResolvedProfile

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


_PREMIUM_INACTIVE = GuardResult(
    allowed=True,
    reason="premium inactive",
    findings=(),
    tier="none",
    param_scan_unsafe=False,
)


class ToolCallGuard:
    def __init__(
        self,
        pipeline: Pipeline,
        frequency_tracker: FrequencyTracker,
        config: PetasosConfig,
        profile: ResolvedProfile | None = None,
    ) -> None:
        self._pipeline = pipeline
        self._frequency_tracker = frequency_tracker
        self._config = config
        self._profile = profile

    async def evaluate(
        self,
        tool_name: str,
        tool_params: dict[str, Any],
        session_id: str,
    ) -> GuardResult:
        # Step 0: Premium gate
        if not self._pipeline.is_premium_active("tool_guard"):
            return _PREMIUM_INACTIVE

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

        # Step 4: Exempt check
        if self._profile and normalized_name in self._profile.tool_exempt_list:
            return GuardResult(
                allowed=True,
                reason="tool exempt per profile",
                findings=(),
                tier=tier,
                param_scan_unsafe=False,
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
        # 1a. Case-fold
        name = tool_name.lower()
        # 1b. Strip namespace prefix
        name = _NAMESPACE_PREFIX_RE.sub("", name)
        # 1c. Map aliases
        if self._profile and self._profile.tool_alias_map:
            combined = {**DEFAULT_TOOL_ALIASES, **self._profile.tool_alias_map}
        else:
            combined = dict(DEFAULT_TOOL_ALIASES)
        name = combined.get(name, name)
        # 1d. Strip whitespace
        name = name.strip()
        return name

    def _derive_tier(self, session_id: str) -> str:
        state = self._frequency_tracker.get_state(session_id)
        if state is None:
            return "none"
        if state.terminated:
            return "tier3"
        if self._profile and self._profile.tier_thresholds:
            t = self._profile.tier_thresholds
            if state.last_score >= t.tier3:
                return "tier3"
            if state.last_score >= t.tier2:
                return "tier2"
            if state.last_score >= t.tier1:
                return "tier1"
            return "none"
        return evaluate_tier(state.last_score, self._config)

    async def _scan_params(
        self,
        tool_params: dict[str, Any],
        session_id: str,
    ) -> tuple[tuple[ScanFinding, ...], bool]:
        if not tool_params:
            return (), False

        parts: list[str] = []
        for value in tool_params.values():
            if value is None:
                continue
            if isinstance(value, str):
                parts.append(value)
            else:
                try:
                    parts.append(json.dumps(value))
                except TypeError:
                    parts.append(str(value))

        param_text = "\n".join(parts)
        if not param_text:
            return (), False

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
