"""Warm and fallback enforcement scan the same outbound parameter text."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from petasos.config.sections import PetasosConfig
from petasos.enforce.fallback import scan_fallback
from petasos.guard.guard import ToolCallGuard
from petasos.limits import MAX_PARAM_TEXT_LEN
from petasos.model import ScanResult
from petasos.pipeline import Pipeline
from petasos.session.frequency import FrequencyTracker


class _WarmRecorder:
    name = "recorder"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def scan(
        self, text: str, *, direction: str = "inbound", session_id: str | None = None
    ) -> ScanResult:
        self.calls.append((text, direction))
        return ScanResult(self.name, ())


class _FallbackRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def scan(self, text: str, *, direction: str) -> ScanResult:
        self.calls.append((text, direction))
        return ScanResult("recorder", ())


def _ignore_event(**fields: object) -> None:
    pass


@pytest.mark.parametrize("capped", [False, True])
async def test_warm_and_fallback_scan_identical_text_outbound(capped: bool) -> None:
    args: dict[str, Any]
    if capped:
        args = {"value": "z" * (MAX_PARAM_TEXT_LEN + 1)}
        expected = "z" * MAX_PARAM_TEXT_LEN
    else:
        args = {"raw": "line one\nline two", "missing": None, "items": [1, 2]}
        expected = "line one\nline two\n[1, 2]"
    config = PetasosConfig()
    warm = _WarmRecorder()
    pipeline = Pipeline([warm], config=config)
    guard = ToolCallGuard(pipeline, FrequencyTracker(config), config, protected_paths=lambda: ())
    await guard.evaluate("write_file", args, "session")
    fallback = _FallbackRecorder()
    scanned = scan_fallback(
        "write_file",
        args,
        is_dangerous=lambda _name: True,
        session_id_for=lambda: "session",
        scanner_for=lambda: fallback,
        run=lambda result: result,
        logger=logging.getLogger(__name__),
        emit=_ignore_event,
    )
    assert scanned.outcome == "clean"
    assert warm.calls == fallback.calls == [(expected, "outbound")]
