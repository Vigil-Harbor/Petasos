"""Regenerate ``outcomes.json`` from ``scenarios.json``.

Run from the repository root::

    .venv/bin/python -m tests.enforce_parity.record

Re-running this is only legitimate for a deliberate behaviour change.
Two runs against an unchanged tree write byte-identical output.
"""

from __future__ import annotations

from typing import Any

from tests.enforce_parity.load import (
    OUTCOME_VERSION,
    OUTCOMES_PATH,
    SCENARIOS_PATH,
    dump_outcomes,
    expand_scenario,
    load_json,
)
from tests.enforce_parity.plugin_adapter import PluginOracle


def replay_all() -> dict[str, Any]:
    """Replay every scenario and return the outcome document."""
    corpus = load_json(SCENARIOS_PATH)
    scenarios = corpus.get("scenarios")
    if not isinstance(scenarios, list):
        raise TypeError("scenarios must be a list")
    oracle = PluginOracle()
    recorded: dict[str, Any] = {}
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            raise TypeError("scenario must be an object")
        prepared = expand_scenario(scenario)
        scenario_id = prepared.get("id")
        if not isinstance(scenario_id, str):
            raise TypeError("scenario id must be a string")
        if scenario_id in recorded:
            raise ValueError(f"duplicate scenario id {scenario_id!r}")
        recorded[scenario_id] = oracle.replay(prepared)
    return {"scenarios": recorded, "version": OUTCOME_VERSION}


def main() -> None:
    """Write ``outcomes.json`` next to this file."""
    OUTCOMES_PATH.write_text(dump_outcomes(replay_all()), encoding="utf-8")


if __name__ == "__main__":
    main()
