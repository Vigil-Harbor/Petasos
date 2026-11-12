"""Self-modification weights cannot be disabled by a configured weight map."""

from __future__ import annotations

import pytest

from petasos.config.schema import from_mapping
from petasos.config.sections import PetasosConfig
from petasos.session.frequency import FrequencyTracker


@pytest.mark.parametrize(
    ("rule", "floor"),
    [("petasos.selfmod.config_write", 10.0), ("petasos.selfmod.config_ref", 3.0)],
)
def test_selfmod_weight_floors_override_zero_weights(rule: str, floor: float) -> None:
    """Pin selfmod weight floors override zero weights."""
    config = from_mapping(PetasosConfig, {"frequency": {"weights": {rule: 0.0}}})
    tracker = FrequencyTracker(config)
    result = tracker.update("session", [rule])
    assert result.current_score == floor
    state = tracker.get_state("session")
    assert state is not None and state.last_score == floor
