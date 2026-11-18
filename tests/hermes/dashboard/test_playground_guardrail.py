"""Guardrail trials respect the configured policy without recording attempts."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from petasos.config.layers import resolve
from petasos.enforce.types import ApprovalGrant
from petasos.hermes.dashboard.playground import try_input
from petasos.pipeline import Pipeline
from petasos.session.frequency import FrequencyTracker

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("mode,expected", [("never", "block"), ("approve", "approve")])
@pytest.mark.parametrize("unattended", [False, True])
async def test_guardrail_preview_respects_policy_without_recording_an_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str, expected: str, unattended: bool
) -> None:
    protected = tmp_path / "config.yaml"
    live = FrequencyTracker(resolve({}).config)
    before = live.update("live", ["petasos.syntactic.injection.ignore-previous"])
    records: list[object] = []
    monkeypatch.setattr(Pipeline, "record_selfmod", lambda *args: records.append(args))
    monkeypatch.setattr(
        "petasos.hermes.dashboard.playground.approval_grant",
        lambda: ApprovalGrant(yolo=unattended),
    )
    body = await try_input(
        {"overrides": {"tools": {"self_change": mode}}},
        tool="write_file",
        arguments={"path": str(protected), "content": "hello"},
        protected_paths=lambda: (str(protected),),
        registry=(),
        redactor=lambda text, **_kw: text,
    )
    assert body["decision"] == ("block" if unattended else expected)
    assert body["message"]
    state = live.get_state("live")
    assert state is not None and state.last_score == before.current_score
    assert live.get_state("petasos-playground") is None
    assert records == []
    assert not protected.exists()
    assert not list(tmp_path.glob("*.jsonl"))
