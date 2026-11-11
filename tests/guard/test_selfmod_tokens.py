"""The guard records self-modification with both keyed and keyless trackers."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from petasos.config.schema import from_mapping
from petasos.config.secrets import Secrets
from petasos.config.sections import PetasosConfig
from petasos.guard.guard import ToolCallGuard
from petasos.pipeline import Pipeline
from petasos.session.frequency import FrequencyTracker

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("secret", [None, b"k" * 32])
async def test_selfmod_updates_a_tracker_without_the_frequency_feature(
    tmp_path: Path, secret: bytes | None
) -> None:
    config = from_mapping(PetasosConfig, {"frequency": {"enabled": False}})
    secrets = Secrets(session_secret=secret)
    pipeline = Pipeline(config=config, secrets=secrets, host_id="test-host")
    tracker = FrequencyTracker(config, secrets=secrets)
    protected = tmp_path / "config.yaml"
    guard = ToolCallGuard(
        pipeline, tracker, config, secrets=secrets, protected_paths=lambda: [str(protected)]
    )
    result = await guard.evaluate("write_file", {"path": str(protected)}, "session")
    assert result.selfmod_finding is not None
    session = tracker.mint_token("session", "test-host") if secret else "session"
    state = tracker.get_state(session)
    assert state is not None and state.last_score >= 10.0
