"""A profile name selects one directory under profiles/ and nothing else."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from petasos.hermes.target import profile_home, resolve_target

if TYPE_CHECKING:
    from pathlib import Path


def test_a_plain_name_is_a_directory_under_profiles(tmp_path: Path) -> None:
    assert profile_home(tmp_path, "work") == tmp_path / "profiles" / "work"


def test_default_is_the_home_with_no_profile(tmp_path: Path) -> None:
    assert profile_home(tmp_path, "default") == tmp_path
    assert profile_home(tmp_path / "profiles" / "work", "default") == tmp_path


@pytest.mark.parametrize(
    "name",
    [
        "..",
        "../escape",
        "a/b",
        "a\\b",
        # On Windows a drive letter makes the name relative to that drive,
        # so joining it to profiles/ leaves the Hermes home.
        "D:elsewhere",
        "C:..",
        "C:..:",
        "C:",
    ],
)
def test_a_name_that_could_leave_profiles_is_refused(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError, match="not a single directory name"):
        profile_home(tmp_path, name)


def test_the_profile_flag_refuses_a_drive_letter(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not a single directory name"):
        resolve_target(home=str(tmp_path), profile="D:elsewhere")
