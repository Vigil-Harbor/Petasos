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


# Both parameter paths scan outbound content so command detection applies.
_MAX_PARAM_TEXT_LEN = MAX_PARAM_TEXT_LEN
PARAM_SCAN_DIRECTION: Final[Direction] = "outbound"


@dataclass(frozen=True)
class RenderedParams:
    """Retain capped scan text and its original length."""

    text: str
    original_len: int
    segments: tuple[tuple[int, int], ...] | None = None

    @property
    def truncated(self) -> bool:
        """Return whether parameter text exceeds the retained scan prefix."""
        return self.original_len > len(self.text)


def render_param_text(tool_params: Mapping[str, Any]) -> RenderedParams:
    """Render a bounded parameter prefix shared by normal and fallback scans.

    Falsy input is empty; None values are omitted and strings stay unescaped.
    Other values use safe JSON. Non-mappings raise into the caller guard."""
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
    # See docs/architecture/rationale.md, "Parameter scan degradation".
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
