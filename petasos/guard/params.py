"""Render and scan bounded tool-call parameters."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from petasos.limits import MAX_PARAM_TEXT_LEN
from petasos.session.safe_json import safe_json_dumps

_logger = logging.getLogger("petasos.session.guard")

if TYPE_CHECKING:
    from collections.abc import Mapping

    from petasos.guard.guard import ToolCallGuard
    from petasos.model import Direction, ScanFinding


# PET-190: the one direction both parameter scans use. Tool parameters are agent
# output (PET-94 Decision 2), so the outbound-only command family runs on them.
_MAX_PARAM_TEXT_LEN = MAX_PARAM_TEXT_LEN
PARAM_SCAN_DIRECTION: Final[Direction] = "outbound"


@dataclass(frozen=True)
class RenderedParams:
    """PET-190: scan text plus the length it had before the cap was applied."""

    text: str
    original_len: int
    segments: tuple[tuple[int, int], ...] | None = None

    @property
    def truncated(self) -> bool:
        return self.original_len > len(self.text)


def render_param_text(tool_params: Mapping[str, Any]) -> RenderedParams:
    """PET-190: the single derivation of scan text from a tool call's parameters.

    Both ``ToolCallGuard._scan_params`` and the reference plugin's
    ``_fallback_pre_tool_call`` call this, so cap and serialization cannot drift
    between the healthy and degraded paths. Falsy input renders empty. ``None``
    values are dropped, string values pass through raw (no JSON escaping between
    the scanner and the bytes the agent emitted), everything else goes through
    ``safe_json_dumps``, and the parts are newline-joined. Text over
    ``_MAX_PARAM_TEXT_LEN`` is cut there; the caller reads ``truncated`` and logs
    in its own vocabulary (PET-174 shape: the helper returns data, never logs).
    Never raises on a mapping; a non-mapping raises ``AttributeError`` into the
    caller's existing fail-secure handler.
    """
    if not tool_params:
        return RenderedParams("", 0, ())
    parts: list[str] = []
    for value in tool_params.values():
        if value is None:
            continue
        if isinstance(value, str):
            parts.append(value)
        else:
            parts.append(safe_json_dumps(value))
    text = "\n".join(parts)
    original_len = len(text)
    if original_len > _MAX_PARAM_TEXT_LEN:
        text = text[:_MAX_PARAM_TEXT_LEN]
    segments = []
    cursor = 0
    for part in parts:
        end = min(cursor + len(part), len(text))
        if cursor < end:
            segments.append((cursor, end))
        cursor += len(part) + 1
    return RenderedParams(text, original_len, tuple(segments))


async def _scan_params(
    self: ToolCallGuard,
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

        rendered = render_param_text(tool_params)
        if not rendered.text:
            return (), False, False
        if rendered.truncated:
            _logger.warning(
                "param text exceeds length cap (%d > %d chars), truncating; session=%s",
                rendered.original_len,
                _MAX_PARAM_TEXT_LEN,
                session_id,
            )
        param_text = rendered.text

        prepare = getattr(self._pipeline, "_prepare_semgrep", None)
        prepared = (
            None
            if prepare is None
            else await prepare(
                param_text,
                segments=rendered.segments,
                upstream_total_chars=rendered.original_len,
            )
        )
        try:
            if prepared is None:
                result = await self._pipeline.inspect(
                    param_text,
                    direction=PARAM_SCAN_DIRECTION,
                    session_id=session_id,
                    weight_cap=self.scan_weight_cap,
                )
            else:
                result = await self._pipeline._inspect_with_prepared_semgrep(
                    param_text,
                    prepared,
                    direction=PARAM_SCAN_DIRECTION,
                    session_id=session_id,
                    weight_cap=self.scan_weight_cap,
                )
        finally:
            if prepared is not None:
                await prepared.discard()

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
