"""Pin total Hermes home resolution and traversal-guarded profile selection.

See docs/architecture/rationale.md, "Hermes registration ownership"."""

from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import yaml

from petasos.hermes.home import (
    hermes_root,
    list_hermes_profiles,
    resolve_hermes_config_path,
    resolve_profile_config_path,
)


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
    (root / "profiles" / "not_a_profile").mkdir()

    profiles = list_hermes_profiles()
    by_name = {p["name"]: p for p in profiles}
    assert set(by_name) == {"alpha", "beta"}
    assert all(p["tier"] == "profile" for p in profiles)
    assert by_name["alpha"]["is_active"] is True
    assert by_name["beta"]["is_active"] is False
    assert Path(by_name["alpha"]["path"]) == resolve_hermes_config_path().path


def test_list_hermes_profiles_failsoft_missing_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HERMES_HOME", raising=False)
    if platform.system() == "Windows":
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "empty"))
    else:
        monkeypatch.setenv("HOME", str(tmp_path / "empty"))
    assert list_hermes_profiles() == []


def test_only_live_named_profiles_are_listed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _point_root_at(tmp_path, monkeypatch)
    for name in (".deleted", ".git.retired-x", "gone", "default", "Upper", "alpha"):
        _write_profile(root, name)
    (root / "profiles" / "empty").mkdir()
    (root / "profiles" / ".deleted" / "gone").touch()
    beta = root / "profiles" / "beta"
    beta.mkdir()
    (beta / "SOUL.md").touch()

    assert [p["name"] for p in list_hermes_profiles()] == ["alpha", "beta"]
    assert resolve_profile_config_path("gone") is None
    assert resolve_profile_config_path("empty") is None
    selected = resolve_profile_config_path("beta")
    assert selected is not None and selected.path == beta / "config.yaml"


@pytest.mark.parametrize(
    "marker", ["config.yaml", ".env", "SOUL.md", "profile.yaml", "auth.json", "state.db"]
)
@pytest.mark.parametrize("kind", ["file", "symlink", "dangling", "cycle", "directory"])
def test_profile_identity_markers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, marker: str, kind: str
) -> None:
    root = _point_root_at(tmp_path, monkeypatch)
    profile = root / "profiles" / "alpha"
    profile.mkdir()
    target = tmp_path / "identity"
    if kind == "file":
        (profile / marker).touch()
    elif kind == "directory":
        (profile / marker).mkdir()
    else:
        if kind == "symlink":
            target.touch()
        elif kind == "cycle":
            target = profile / marker
        (profile / marker).symlink_to(target)
    assert [p["name"] for p in list_hermes_profiles()] == (
        [] if kind == "directory" else ["alpha"]
    )


@pytest.mark.parametrize("name", ["a", "0", "a_b-9", "a" * 64, "a" * 65, "Upper", "-bad"])
def test_profile_id_grammar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    root = _point_root_at(tmp_path, monkeypatch)
    _write_profile(root, name)
    expected = [name] if name in {"a", "0", "a_b-9", "a" * 64} else []
    assert [p["name"] for p in list_hermes_profiles()] == expected


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


def test_a_profiles_default_folder_is_not_listed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _point_root_at(tmp_path, monkeypatch)
    _write_profile(root, "alpha", {"fail_mode": "open"}, active=True)
    _write_profile(root, "default", {"fail_mode": "closed"}, active=False)

    assert [p["name"] for p in list_hermes_profiles()] == ["alpha"]
    res = resolve_profile_config_path("default")
    assert res is not None
    assert res.path == root / "config.yaml"


def test_default_under_hermes_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _point_root_at(tmp_path / "unused", monkeypatch)
    custom = tmp_path / "custom"
    monkeypatch.setenv("HERMES_HOME", str(custom))
    res = resolve_profile_config_path("default")
    assert res is not None
    assert res.path == custom / "config.yaml"

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
    # Windows expands percent-delimited variables; POSIX leaves them literal.
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


def test_windows_root_uses_localappdata_and_absorbs_a_missing_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert hermes_root() == tmp_path / "hermes"

    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    def _no_home() -> Path:
        raise RuntimeError("no home")

    monkeypatch.setattr(Path, "home", _no_home)
    assert hermes_root() == Path("hermes")


def test_a_bad_profile_pointer_falls_back_to_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _point_root_at(tmp_path, monkeypatch)
    (root / "active_profile").write_text("default", encoding="utf-8")
    from petasos.hermes.home import read_active_profile, resolve_active_profile_dir

    assert read_active_profile(root) is None
    (root / "active_profile").write_bytes(b"\xff")
    assert read_active_profile(root) is None
    (root / "active_profile").write_text("ghost", encoding="utf-8")
    res = resolve_hermes_config_path(use_override=False)
    assert res.tier == "root"
    assert res.warning is not None
    assert "ghost" in res.warning

    def _boom(self: Path, strict: bool = False) -> Path:
        raise OSError("unresolvable")

    monkeypatch.setattr(Path, "resolve", _boom)
    directory, warning = resolve_active_profile_dir(root)
    assert directory is None
    assert warning is not None
    assert "could not be resolved" in warning


def test_petasos_section_read_distinguishes_empty_from_broken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from petasos.hermes.home import (
        display_path,
        read_petasos_section,
        read_petasos_section_checked,
    )

    root = _point_root_at(tmp_path, monkeypatch)
    res = resolve_hermes_config_path(use_override=False)
    assert read_petasos_section_checked(res) == ({}, True)
    res.path.parent.mkdir(parents=True, exist_ok=True)
    res.path.write_text("", encoding="utf-8")
    assert read_petasos_section_checked(res) == ({}, True)
    res.path.write_text("- 1\n", encoding="utf-8")
    assert read_petasos_section_checked(res) == ({}, False)
    res.path.write_text("other: 1\n", encoding="utf-8")
    assert read_petasos_section_checked(res) == ({}, True)
    res.path.write_text("petasos:\n", encoding="utf-8")
    assert read_petasos_section_checked(res) == ({}, True)
    res.path.write_text("petasos: [1]\n", encoding="utf-8")
    assert read_petasos_section_checked(res) == ({}, False)
    res.path.write_text("{", encoding="utf-8")
    assert read_petasos_section_checked(res) == ({}, False)
    res.path.write_text("petasos:\n  fail_mode: open\n", encoding="utf-8")
    assert read_petasos_section(res) == {"fail_mode": "open"}
    home = os.path.expanduser("~")
    shown = display_path(home + os.sep + "petasos-check")
    assert shown == "~" + os.sep + "petasos-check"
    assert root.is_dir()


if TYPE_CHECKING:
    import pathlib


def test_active_profile_traversal_is_rejected(tmp_path: pathlib.Path) -> None:
    from petasos.hermes.home import resolve_active_profile_dir

    (tmp_path / "profiles").mkdir()
    (tmp_path / "active_profile").write_text("../../evil")
    resolved, warning = resolve_active_profile_dir(tmp_path)
    assert resolved is None
    assert warning is not None and "escapes" in warning
