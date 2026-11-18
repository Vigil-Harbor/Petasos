"""Doctor and guardrails agree with real Hermes's live profile discovery."""

from __future__ import annotations

from pathlib import Path

from tests.hermes_host.client import Sandbox, call
from tests.hermes_host.marks import requires_hermes_sandbox

pytestmark = requires_hermes_sandbox
_HARNESS = Path(__file__).with_name("profiles_harness.py")


def test_only_live_profiles_are_named_and_every_loaded_profile_is_watched(
    installed: Sandbox,
) -> None:
    profiles = installed.home / "profiles"
    for name in (".deleted", ".git.retired-x", "gone", "default", "Upper", "alpha"):
        directory = profiles / name
        directory.mkdir(parents=True)
        (directory / "config.yaml").touch()
    (profiles / ".deleted" / "gone").touch()
    (profiles / "empty").mkdir()
    (profiles / "beta").mkdir()
    (profiles / "beta" / "SOUL.md").symlink_to(installed.home / "missing-identity")

    result = call(installed, {}, harness=_HARNESS)
    assert result["hermes"] == ["default", "alpha", "beta"]
    assert result["petasos"] == ["alpha", "beta"]
    assert all(result["watched"].values())
    assert result["first_write"] is True
    assert result["own_home_free"] is True
    assert str(profiles) not in result["paths"]
    for name in (".deleted", ".git.retired-x", "gone", "default", "Upper"):
        assert str(profiles / name) not in result["verbose"]
    # A folder that can still become a profile keeps its settings files protected.
    assert str(profiles / "empty" / "config.yaml") in result["paths"]


def test_all_hermes_identity_markers_and_linked_profiles_stay_watched(
    installed: Sandbox,
) -> None:
    profiles = installed.home / "profiles"
    profiles.mkdir()
    for index, marker in enumerate(
        ("config.yaml", ".env", "SOUL.md", "profile.yaml", "auth.json", "state.db")
    ):
        for kind in ("file", "linked", "dangling", "cycle"):
            directory = profiles / f"profile-{index}-{kind}"
            directory.mkdir()
            if kind == "file":
                (directory / marker).touch()
            else:
                target = installed.home / f"identity-{index}-{kind}"
                if kind == "linked":
                    target.touch()
                elif kind == "cycle":
                    target = directory / marker
                (directory / marker).symlink_to(target)
    linked = installed.home / "linked-profile"
    linked.mkdir()
    (linked / "SOUL.md").touch()
    (profiles / "linked").symlink_to(linked, target_is_directory=True)

    result = call(installed, {}, harness=_HARNESS)
    assert len(result["petasos"]) == 25
    assert result["hermes"] == ["default", *result["petasos"]]
    assert all(result["watched"].values())
