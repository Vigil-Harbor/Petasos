"""PET-146: tests for the Hermes-profile enumeration helpers in
``petasos.console._paths``.

``list_hermes_profiles`` enumerates ``profiles/*/config.yaml`` under the Hermes
root, marking the active binding by a normalized-path compare; it is fail-soft
(``[]`` on a missing/unreadable ``profiles/`` dir) and never raises.
``resolve_profile_config_path`` resolves one named member, traversal-guarded,
returning ``None`` for a non-member.

The helpers read the Hermes root from the environment at call time
(``hermes_root()``: ``%LOCALAPPDATA%\\hermes`` on Windows, ``~/.hermes`` on
POSIX), so these tests redirect the platform-appropriate env var to a ``tmp_path``
sandbox rather than monkeypatching internals.
"""

from __future__ import annotations

import platform
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from petasos.console._paths import (
    hermes_root,
    list_hermes_profiles,
    resolve_hermes_config_path,
    resolve_profile_config_path,
)

if TYPE_CHECKING:
    import pytest


def _point_root_at(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ``hermes_root()`` into *tmp_path* for the current platform.

    Returns the resolved root dir (``<tmp>/hermes`` on Windows, ``<tmp>/.hermes``
    on POSIX), with ``HERMES_HOME`` cleared so the active-profile pointer governs.
    """
    monkeypatch.delenv("HERMES_HOME", raising=False)
    if platform.system() == "Windows":
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    else:
        monkeypatch.setenv("HOME", str(tmp_path))
    root = hermes_root()
    (root / "profiles").mkdir(parents=True, exist_ok=True)
    return root


def _write_profile(
    root: Path, name: str, section: dict | None = None, *, active: bool = False
) -> Path:
    pdir = root / "profiles" / name
    pdir.mkdir(parents=True, exist_ok=True)
    cfg_path = pdir / "config.yaml"
    cfg_path.write_text(yaml.safe_dump({"petasos": section or {}}), encoding="utf-8")
    if active:
        (root / "active_profile").write_text(name, encoding="utf-8")
    return cfg_path


def test_list_hermes_profiles_enumerates_and_marks_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _point_root_at(tmp_path, monkeypatch)
    _write_profile(root, "alpha", {"fail_mode": "open"}, active=True)
    _write_profile(root, "beta", {"fail_mode": "closed"})
    # A bare dir with no config.yaml must be skipped (not every dir is a profile).
    (root / "profiles" / "not_a_profile").mkdir()

    profiles = list_hermes_profiles()
    by_name = {p["name"]: p for p in profiles}
    assert set(by_name) == {"alpha", "beta"}
    assert all(p["tier"] == "profile" for p in profiles)
    # Active marked by normalized-path equality against the live binding, not a
    # leaf-name compare.
    assert by_name["alpha"]["is_active"] is True
    assert by_name["beta"]["is_active"] is False
    assert Path(by_name["alpha"]["path"]) == resolve_hermes_config_path().path


def test_list_hermes_profiles_failsoft_missing_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Point the root somewhere with no profiles/ dir at all.
    monkeypatch.delenv("HERMES_HOME", raising=False)
    if platform.system() == "Windows":
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "empty"))
    else:
        monkeypatch.setenv("HOME", str(tmp_path / "empty"))
    # Never raises; yields [] so the caller folds in active-only.
    assert list_hermes_profiles() == []


def test_resolve_profile_config_path_member_and_traversal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _point_root_at(tmp_path, monkeypatch)
    _write_profile(root, "alpha", {"fail_mode": "open"}, active=True)

    res = resolve_profile_config_path("alpha")
    assert res is not None
    assert res.tier == "profile"
    assert res.warning is None
    assert res.path == root / "profiles" / "alpha" / "config.yaml"

    # Non-member names are rejected (no traversal): unknown leaf and a ../ escape.
    assert resolve_profile_config_path("does_not_exist") is None
    assert resolve_profile_config_path("../../etc") is None
    assert resolve_profile_config_path("..") is None
