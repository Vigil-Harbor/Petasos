"""The sentence about a required check that cannot run matches what happens.

The doctor and the dashboard tell a person what becomes of tool calls while
a required check is missing. These run the enforcer in that state under each
fail mode and each dangerous-action setting, and hold the words to it.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from petasos.config.secrets import Secrets
from petasos.config.sections import PetasosConfig
from petasos.enforce import (
    Allow,
    Block,
    Enforcer,
    HostInfo,
    ManualClock,
    SettingsSnapshot,
    ToolCall,
)
from petasos.enforce.decisions import Approve
from petasos.hermes.doctor_advice import held_consequence
from petasos.scanners.registry import BuildContext, compose

if TYPE_CHECKING:
    from pathlib import Path

_CHANGES_THINGS = ("write_file", "terminal")
_READ_ONLY = ("read_file", "web_search")
_ARGS = {"content": "hello", "path": "notes.txt", "command": "ls", "query": "weather"}


def _config(fail_mode: str, posture: str) -> PetasosConfig:
    config = replace(PetasosConfig(), fail_mode=fail_mode)  # type: ignore[arg-type]
    config = replace(config, tools=replace(config.tools, dangerous_posture=posture))  # type: ignore[arg-type]
    scanners = config.scanners
    required = replace(scanners.prompt_guard, enabled="on")
    return replace(config, scanners=replace(scanners, prompt_guard=required))


@pytest.mark.parametrize("fail_mode", ["open", "degraded", "closed"])
@pytest.mark.parametrize("posture", ["block", "approve"])
def test_the_stated_consequence_is_what_the_enforcer_does(
    tmp_path: Path, fail_mode: str, posture: str
) -> None:
    """Pin the stated consequence is what the enforcer does."""
    config = _config(fail_mode, posture)
    states = {row.id: row.state for row in compose(config, BuildContext()).statuses}
    if states["prompt_guard"] != "unavailable":
        pytest.skip("PromptGuard can run here, so a required check is not missing")
    snapshot = SettingsSnapshot(armed=True, config=config, secrets=Secrets(), token=1, error=None)
    enforcer = Enforcer(
        lambda: snapshot,
        host=HostInfo(subagent_hooks=False, approve_directive=True),
        clock=ManualClock(monotonic=1_000.0),
        spool_path=str(tmp_path / "events.jsonl"),
    )
    enforcer.start()
    enforcer.settle(20)
    try:
        decisions = {
            tool: enforcer.tool_call(ToolCall(tool=tool, args=_ARGS, session=f"s-{tool}"))
            for tool in (*_CHANGES_THINGS, *_READ_ONLY)
        }
    finally:
        enforcer.close()

    stated = held_consequence(fail_mode, posture)
    for tool in _READ_ONLY:
        assert isinstance(decisions[tool], Allow), tool
    if not stated["holds"]:
        expected: type = Allow
        assert "still run" in str(stated["sentence"])
    elif posture == "approve":
        expected = Approve
        assert "person" in str(stated["sentence"])
    else:
        expected = Block
        assert "blocked" in str(stated["sentence"])
    for tool in _CHANGES_THINGS:
        assert isinstance(decisions[tool], expected), tool
