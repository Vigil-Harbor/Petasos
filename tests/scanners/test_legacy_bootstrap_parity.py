"""Registration parity between compose() and build_scanners().

Deleted with the old bootstrap at the cutover.

Two named differences, and no others, in the spread below:

1. ``auto`` and the package is not installed. ``build_scanners`` registers
   PromptGuard and Presidio anyway, and their scans error, so a base install
   blocks all content under the default fail mode. ``compose`` leaves them
   out. That is the enablement-table change.

2. Semgrep enabled with no lifecycle owner. ``build_scanners`` reports
   ``failed`` and registers nothing, so fail mode does not see Semgrep.
   ``compose`` reports ``unavailable`` and registers ``UnavailableScanner``,
   because ``unavailable`` is always in the list. The scan error is
   ``semgrep.host_lifecycle_unavailable``, the text ``build_scanners`` used.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from petasos.config import PetasosConfig as LegacyConfig
from petasos.config.layers import resolve
from petasos.config.migrate import migrate
from petasos.scanners.bootstrap import build_scanners
from petasos.scanners.minimal import MinimalScanner
from petasos.scanners.registry import BuildContext, Composition, UnavailableScanner, compose
from petasos.scanners.semgrep import SemgrepLifecycleOwner

_LIFECYCLE_REASON = "semgrep.host_lifecycle_unavailable"


@dataclass(frozen=True)
class _Case:
    name: str
    legacy: LegacyConfig
    flat: dict[str, Any]


_CASES = (
    _Case("defaults", LegacyConfig(), {}),
    _Case(
        "prompt_guard disabled",
        LegacyConfig(disabled_scanners=("prompt_guard",)),
        {"disabled_scanners": ["prompt_guard"]},
    ),
    _Case(
        "presidio disabled",
        LegacyConfig(disabled_scanners=("presidio",)),
        {"disabled_scanners": ["presidio"]},
    ),
    _Case(
        "semgrep disabled",
        LegacyConfig(disabled_scanners=("semgrep",)),
        {"disabled_scanners": ["semgrep"]},
    ),
    _Case(
        "all three disabled",
        LegacyConfig(disabled_scanners=("prompt_guard", "presidio", "semgrep")),
        {"disabled_scanners": ["prompt_guard", "presidio", "semgrep"]},
    ),
    _Case(
        "semgrep enabled",
        LegacyConfig(semgrep_enabled=True),
        {"semgrep_enabled": True},
    ),
    _Case(
        "semgrep enabled and disabled",
        LegacyConfig(semgrep_enabled=True, disabled_scanners=("semgrep",)),
        {"semgrep_enabled": True, "disabled_scanners": ["semgrep"]},
    ),
    _Case(
        "semgrep enabled, others disabled",
        LegacyConfig(
            semgrep_enabled=True,
            disabled_scanners=("prompt_guard", "presidio"),
        ),
        {"semgrep_enabled": True, "disabled_scanners": ["prompt_guard", "presidio"]},
    ),
    _Case(
        "decode off",
        LegacyConfig(decode_encoded_payloads=False),
        {"decode_encoded_payloads": False},
    ),
    _Case(
        "presidio narrowed",
        LegacyConfig(presidio_entities=("EMAIL_ADDRESS",), presidio_score_threshold=0.5),
        {"presidio_entities": ["EMAIL_ADDRESS"], "presidio_score_threshold": 0.5},
    ),
)

_WITH_OWNER = (
    _CASES[5],
    _CASES[7],
)


def _aligned(old_names: list[str], new: Composition) -> list[str]:
    """Old names, minus quiet ``auto`` scanners, plus the lifecycle stand-in."""
    quiet = {status.id for status in new.statuses if status.state == "not_installed"}
    names = [name for name in old_names if name not in quiet]
    for status in new.statuses:
        if (
            status.id == "semgrep"
            and status.state == "unavailable"
            and status.reason == _LIFECYCLE_REASON
            and status.id not in names
        ):
            names.append(status.id)
    return names


def _pair(
    case: _Case,
    *,
    lifecycle: SemgrepLifecycleOwner | None,
    key: object | None,
) -> tuple[list[str], Composition]:
    old, _statuses = build_scanners(
        case.legacy,
        semgrep_lifecycle=lifecycle,
        semgrep_scheduling_key=key,
    )
    new = compose(
        resolve(migrate(case.flat).settings).config,
        BuildContext(semgrep_lifecycle=lifecycle, semgrep_scheduling_key=key),
    )
    assert isinstance(old[0], MinimalScanner)
    assert isinstance(new.scanners[0], MinimalScanner)
    assert old[0]._decode_encoded_payloads is new.scanners[0]._decode_encoded_payloads
    return [scanner.name for scanner in old], new


@pytest.mark.parametrize("case", _CASES, ids=[case.name for case in _CASES])
def test_registration_matches_except_the_named_differences(case: _Case) -> None:
    old_names, new = _pair(case, lifecycle=None, key=None)
    assert [scanner.name for scanner in new.scanners] == _aligned(old_names, new)


def test_auto_and_not_installed_is_the_deliberate_omission() -> None:
    """A base install used to register both optional scanners and then error."""
    old_names, new = _pair(_CASES[0], lifecycle=None, key=None)
    assert old_names == ["minimal", "presidio", "prompt_guard"]
    assert [scanner.name for scanner in new.scanners] == ["minimal"]
    omitted = {status.id for status in new.statuses if status.state == "not_installed"}
    assert omitted == {"presidio", "prompt_guard"}


def test_semgrep_without_a_lifecycle_owner_is_registered() -> None:
    """0.5 left this scanner out. unavailable means it is in the list."""
    case = _CASES[7]
    old_names, new = _pair(case, lifecycle=None, key=None)
    assert old_names == ["minimal"]
    assert [scanner.name for scanner in new.scanners] == ["minimal", "semgrep"]
    status = next(item for item in new.statuses if item.id == "semgrep")
    assert status.state == "unavailable"
    assert status.reason == _LIFECYCLE_REASON
    stand_in = new.scanners[-1]
    assert isinstance(stand_in, UnavailableScanner)
    assert stand_in.reason == _LIFECYCLE_REASON


@pytest.mark.parametrize("case", _WITH_OWNER, ids=[case.name for case in _WITH_OWNER])
async def test_semgrep_with_a_lifecycle_owner_matches(case: _Case) -> None:
    async with SemgrepLifecycleOwner() as owner:
        old_names, new = _pair(case, lifecycle=owner, key=object())
    assert [scanner.name for scanner in new.scanners] == _aligned(old_names, new)
    semgrep = next(item for item in new.statuses if item.id == "semgrep")
    assert semgrep.state == "unavailable"
    assert semgrep.reason != _LIFECYCLE_REASON
    assert "semgrep" in old_names
    assert "semgrep" in [scanner.name for scanner in new.scanners]
