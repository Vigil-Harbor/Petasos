"""The pin holds fixed leaves through each real Hermes write surface."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from petasos.config.schema import leaves
from petasos.config.sections import PetasosConfig
from tests.hermes_host.client import Sandbox, call
from tests.hermes_host.marks import requires_hermes_sandbox

pytestmark = requires_hermes_sandbox
_HARNESS = Path(__file__).with_name("pin_harness.py")


def _call(box: Sandbox, action: str, **values: Any) -> dict[str, Any]:
    return call(box, {"action": action, **values}, harness=_HARNESS, timeout=240)


def test_partial_pin_leaves_siblings_and_empty_mapping_entries_writable(
    installed: Sandbox,
) -> None:
    result = _call(installed, "partial")
    assert result == {
        "sibling": False,
        "api_empty_mapping_child": None,
        "empty_mapping_child": "terminal",
        "pinned_leaf": "never",
    }


@pytest.mark.parametrize("method", ["api", "hermes_config", "petasos_config", "form"])
def test_writes_do_not_change_fixed_leaves(installed: Sandbox, method: str) -> None:
    pinned = _call(installed, "pin")
    assert pinned["code"] == 0
    assert pinned["document"]["model"] == {"default": "sandbox-only"}
    assert {"plugins.enabled", "plugins.disabled", "plugins.hook_callback_timeout"} <= set(
        pinned["keys"]
    )
    assert pinned["doctor"]["state"] == "writable"
    result = _call(installed, "writes", method=method)
    assert result["before"] == result["after"]
    if method in {"hermes_config", "petasos_config"}:
        assert result["actual_cli"] != 0
    if method in {"api", "hermes_config"}:
        assert len(result["refusals"]) >= len(leaves(PetasosConfig))
    elif method == "petasos_config":
        assert all(attempt["code"] != 0 for attempt in result["attempts"])


def test_hermes_merges_new_entries_into_pinned_groups_and_petasos_does_not_use_them(
    installed: Sandbox,
) -> None:
    """Hermes's own view takes a profile's new entries. Petasos reads the pin whole."""
    _call(installed, "pin")
    result = _call(installed, "hand_edit")
    before, after = result["before"], result["after"]
    assert (
        after["enabled"] is True
        and after["role"] == before["role"]
        and after["level"] == before["level"]
    )
    assert after["overrides"]["rules"]["severity_overrides"]["probe"] == "low"
    assert after["overrides"]["tools"]["aliases"]["probe"] == "terminal"
    assert after["overrides"]["frequency"]["weights"]["probe"] == 0.0
    for group in ("rules", "tools", "frequency"):
        before["overrides"][group] = after["overrides"][group]
    assert before == after
    assert result["bound_armed"] is True and result["bound_error"] is None
    assert result["pin"]["profile_differences"] and result["switch"] is True
    for used in (result["used_bound"], result["used_unbound"]):
        assert used is not None
        assert used["armed"] is True
        assert "probe" not in used["severity_overrides"]
        assert "probe" not in used["aliases"]
        assert used["weights"] is None
    assert result["pin"]["open_groups"] == [] and result["pin"]["unset_values"] == []


def test_disable_does_not_unload_petasos_and_unpin_restores_profile_writes(
    installed: Sandbox,
) -> None:
    pinned = _call(installed, "pin")
    result = _call(installed, "disable")
    assert result["code"] == 0, result
    again = _call(installed, "loaded")
    assert again["loaded"] is True and again["values"] == pinned["values"]
    refused = _call(installed, "unpin")
    assert refused["code"] == 2 and "--accept-profile-changes" in refused["text"]
    removed = _call(installed, "unpin", accept=True)
    assert removed["code"] == 0
    restored = _call(installed, "unpinned")
    assert restored["enabled"] is False
    assert restored["keys"] == ["model.default"]


def test_pinned_unset_values_do_not_replace_profile_groups(installed: Sandbox) -> None:
    _call(installed, "pin")
    result = _call(installed, "nullable")
    before = result["before"]["overrides"]
    after = result["after"]["overrides"]
    for group, key in (("scanners", "presidio"), ("scanners", "semgrep")):
        for name, value in before[group][key].items():
            if value is None:
                assert after[group][key][name] == {"probe": 0.0}
    assert before["frequency"]["weights"] is None
    assert after["frequency"]["weights"] == {"probe": 0.0}


@pytest.mark.parametrize("raw,expected", [(0, 0.0), (-1, 30.0), (9000, 600.0)])
def test_hook_timeout_is_pinned_at_hermes_effective_value(
    installed: Sandbox, raw: int, expected: float
) -> None:
    result = _call(installed, "timeout", raw=raw)
    assert result["code"] == 0 and result["refused"] is True
    assert result["effective"] == expected


def test_redirected_machine_pin_is_a_failure(installed: Sandbox) -> None:
    _call(installed, "pin")
    result = _call(installed, "redirect")
    assert result["pin"]["state"] == "not_in_force"
    assert any(c["id"] == "pin" and c["status"] == "fail" for c in result["checks"])


@pytest.mark.parametrize("defined", [True, False])
def test_pin_freezes_expanded_values_and_refuses_unresolved_references(
    installed: Sandbox, defined: bool
) -> None:
    result = _call(installed, "references", defined=defined)
    if defined:
        assert result["code"] == 0 and result["language"] == "fr"
        assert result["wrote"] is True
    else:
        assert result["code"] == 2 and "environment reference" in result["text"]
        assert result["wrote"] is False
