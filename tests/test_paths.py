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

import os
import platform
from pathlib import Path
from typing import TYPE_CHECKING, Any

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
    root: Path, name: str, section: dict[str, Any] | None = None, *, active: bool = False
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


def test_regression_pet238_default_resolves_to_the_root_and_stays_off_the_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _point_root_at(tmp_path, monkeypatch)
    _write_profile(root, "alpha", {"fail_mode": "open"}, active=True)

    res = resolve_profile_config_path("default")
    assert res is not None
    assert res.tier == "root"
    assert res.path == root / "config.yaml"
    assert [p["name"] for p in list_hermes_profiles()] == ["alpha"]


def test_default_under_hermes_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _point_root_at(tmp_path / "unused", monkeypatch)
    custom = tmp_path / "custom"
    monkeypatch.setenv("HERMES_HOME", str(custom))
    res = resolve_profile_config_path("default")
    assert res is not None
    assert res.path == custom / "config.yaml"

    # A profile child's HERMES_HOME still belongs to its root.
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "root" / "profiles" / "ops"))
    res = resolve_profile_config_path("default")
    assert res is not None
    assert res.path == tmp_path / "root" / "config.yaml"


def _install_override(monkeypatch: pytest.MonkeyPatch, value: object) -> None:
    import sys
    import types

    mod = types.ModuleType("hermes_constants")
    if value is not _MISSING:

        def _fn() -> object:
            if isinstance(value, BaseException):
                raise value
            return value

        mod.get_hermes_home_override = _fn  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "hermes_constants", mod)


class _Missing:
    pass


_MISSING = _Missing()


def test_override_present_resolves_override_tier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A usable override is tier override and does not fall through."""
    home = tmp_path / "gibson"
    _install_override(monkeypatch, str(home))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "root"))
    res = resolve_hermes_config_path()
    assert res.tier == "override"
    assert res.warning is None
    assert res.path == home / "config.yaml"


def test_override_absent_with_hermes_home_is_hermes_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """None from an importable override keeps the HERMES_HOME tier."""
    _install_override(monkeypatch, None)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "task"))
    res = resolve_hermes_config_path()
    assert res.tier == "hermes_home"
    assert res.path == tmp_path / "task" / "config.yaml"


def test_override_absent_with_active_profile_keeps_profile_tier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An importable override of None does not delete the profile tier."""
    root = _point_root_at(tmp_path, monkeypatch)
    _write_profile(root, "cli", active=True)
    _install_override(monkeypatch, None)
    res = resolve_hermes_config_path()
    assert res.tier == "profile"
    assert res.path == root / "profiles" / "cli" / "config.yaml"


def test_hermes_constants_none_in_sys_modules_keeps_three_tiers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A blocked hermes_constants import falls through to HERMES_HOME."""
    import sys

    monkeypatch.setitem(sys.modules, "hermes_constants", None)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "standalone"))
    res = resolve_hermes_config_path()
    assert res.tier == "hermes_home"
    assert res.path == tmp_path / "standalone" / "config.yaml"


def test_unusable_override_falls_through_without_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Whitespace, a missing attribute, and a raising override fall through."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "env"))
    _install_override(monkeypatch, "   ")
    assert resolve_hermes_config_path().tier == "hermes_home"
    _install_override(monkeypatch, _MISSING)
    assert resolve_hermes_config_path().tier == "hermes_home"
    _install_override(monkeypatch, RuntimeError("boom"))
    res = resolve_hermes_config_path()
    assert res.tier == "hermes_home"
    assert res.path == tmp_path / "env" / "config.yaml"


def test_override_expands_user_and_vars(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """~/ and $VAR / %VAR% expand before config.yaml is joined."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("PET231_VAR", "expanded")
    _install_override(monkeypatch, "~/pet231")
    tilde = resolve_hermes_config_path()
    assert tilde.tier == "override"
    assert tilde.path == tmp_path / "pet231" / "config.yaml"
    _install_override(monkeypatch, "$PET231_VAR/home")
    dollar = resolve_hermes_config_path()
    assert dollar.path == Path("expanded") / "home" / "config.yaml"
    _install_override(monkeypatch, "%PET231_VAR%/home")
    percent = resolve_hermes_config_path()
    # expandvars expands %VAR% on Windows and leaves it literal elsewhere.
    assert percent.path == Path(os.path.expandvars("%PET231_VAR%/home")) / "config.yaml"


def test_relative_override_stays_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """A relative override stays tier override and does not fall through."""
    monkeypatch.setenv("HERMES_HOME", "/should/not/win")
    _install_override(monkeypatch, "rel/home")
    res = resolve_hermes_config_path()
    assert res.tier == "override"
    assert res.warning is None
    assert res.path == Path("rel/home") / "config.yaml"
    assert not res.path.is_absolute()


def test_use_override_false_ignores_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """use_override=False returns the env result while an override is set."""
    _install_override(monkeypatch, str(tmp_path / "override"))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "launch"))
    res = resolve_hermes_config_path(use_override=False)
    assert res.tier == "hermes_home"
    assert res.path == tmp_path / "launch" / "config.yaml"
