"""Tests for the Hermes config-path resolver and _load_config wiring.

PET-86: Profile-aware config resolution — HERMES_HOME → active_profile
pointer → v0.15 root fallback.  All tests use tmp_path + monkeypatch;
no real Hermes install required.
"""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Any

import pytest

import petasos.console._paths as paths_mod
from petasos.console._paths import (
    read_petasos_section,
    resolve_hermes_config_path,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_config(path: Path, petasos_section: dict[str, Any] | None = None) -> None:
    """Write a minimal Hermes config.yaml with an optional petasos: section."""
    import yaml

    data: dict[str, Any] = {"model": {"provider": "test"}}
    if petasos_section is not None:
        data["petasos"] = petasos_section
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")


def _setup_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    system: str = "Windows",
) -> Path:
    """Point hermes_root() at tmp_path and return it."""
    monkeypatch.setattr(paths_mod.platform, "system", lambda: system)  # type: ignore[attr-defined]
    if system == "Windows":
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        return tmp_path / "hermes"
    else:
        monkeypatch.setattr(paths_mod.Path, "home", classmethod(lambda cls: tmp_path))  # type: ignore[attr-defined]
        return tmp_path / ".hermes"


def _load_reference_plugin_module(project_root: Path) -> Any:
    """Import docs/deployment/reference_plugin/__init__.py by file path."""
    init_path = project_root / "docs" / "deployment" / "reference_plugin" / "__init__.py"
    spec = importlib.util.spec_from_file_location("reference_plugin", init_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Resolver tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("system", ["Windows", "Linux", "Darwin"])
def test_load_config_honors_hermes_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, system: str
) -> None:
    """HERMES_HOME set → config read from $HERMES_HOME/config.yaml."""
    _setup_root(tmp_path, monkeypatch, system=system)
    custom_home = tmp_path / "custom_home"
    _write_config(custom_home / "config.yaml", {"fail_mode": "open"})
    monkeypatch.setenv("HERMES_HOME", str(custom_home))

    res = resolve_hermes_config_path()
    assert res.tier == "hermes_home"
    assert res.path == custom_home / "config.yaml"
    assert res.warning is None

    section = read_petasos_section(res)
    assert section == {"fail_mode": "open"}


@pytest.mark.parametrize("system", ["Windows", "Linux", "Darwin"])
def test_load_config_resolves_active_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, system: str
) -> None:
    """active_profile names an existing profile dir → profile config wins."""
    monkeypatch.delenv("HERMES_HOME", raising=False)
    root = _setup_root(tmp_path, monkeypatch, system=system)

    _write_config(root / "config.yaml", {"fail_mode": "closed"})
    profile_dir = root / "profiles" / "gibson"
    _write_config(profile_dir / "config.yaml", {"fail_mode": "degraded"})
    (root / "active_profile").write_text("gibson")

    res = resolve_hermes_config_path()
    assert res.tier == "profile"
    assert res.path == profile_dir / "config.yaml"
    assert res.warning is None

    section = read_petasos_section(res)
    assert section["fail_mode"] == "degraded"


@pytest.mark.parametrize("system", ["Windows", "Linux", "Darwin"])
def test_load_config_falls_back_when_profile_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, system: str
) -> None:
    """active_profile names a nonexistent dir → root + warning."""
    monkeypatch.delenv("HERMES_HOME", raising=False)
    root = _setup_root(tmp_path, monkeypatch, system=system)

    _write_config(root / "config.yaml", {"fail_mode": "closed"})
    (root / "active_profile").write_text("phantom")

    res = resolve_hermes_config_path()
    assert res.tier == "root"
    assert res.warning is not None
    assert "phantom" in res.warning


def test_load_config_default_profile_uses_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """active_profile == "default" → root, no warning."""
    monkeypatch.delenv("HERMES_HOME", raising=False)
    root = _setup_root(tmp_path, monkeypatch, system="Windows")

    _write_config(root / "config.yaml", {"fail_mode": "closed"})
    (root / "active_profile").write_text("default")

    res = resolve_hermes_config_path()
    assert res.tier == "root"
    assert res.warning is None


def test_load_config_no_pointer_falls_back_to_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No active_profile file → root (even if profile dirs exist)."""
    monkeypatch.delenv("HERMES_HOME", raising=False)
    root = _setup_root(tmp_path, monkeypatch, system="Windows")

    _write_config(root / "config.yaml", {"fail_mode": "closed"})
    profile_dir = root / "profiles" / "gibson"
    _write_config(profile_dir / "config.yaml", {"fail_mode": "degraded"})

    res = resolve_hermes_config_path()
    assert res.tier == "root"
    assert res.warning is None


def test_load_config_profile_without_config_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Profile dir exists but has no config.yaml → tier=profile, caller warns."""
    monkeypatch.delenv("HERMES_HOME", raising=False)
    root = _setup_root(tmp_path, monkeypatch, system="Windows")

    _write_config(root / "config.yaml", {"fail_mode": "closed"})
    profile_dir = root / "profiles" / "gibson"
    profile_dir.mkdir(parents=True)
    (root / "active_profile").write_text("gibson")

    res = resolve_hermes_config_path()
    assert res.tier == "profile"
    assert not res.path.is_file()

    section = read_petasos_section(res)
    assert section == {}


@pytest.mark.parametrize("system", ["Windows", "Linux", "Darwin"])
def test_load_config_falls_back_to_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, system: str
) -> None:
    """No env, no profiles → v0.15 root path used."""
    monkeypatch.delenv("HERMES_HOME", raising=False)
    root = _setup_root(tmp_path, monkeypatch, system=system)

    _write_config(root / "config.yaml", {"fail_mode": "open"})

    res = resolve_hermes_config_path()
    assert res.tier == "root"
    assert res.path == root / "config.yaml"


# ---------------------------------------------------------------------------
# Hostile-input parametrize (each case is its own test)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "case_name, setup, expected_tier",
    [
        ("empty_localappdata", "empty_localappdata", "root"),
        ("hermes_home_at_file", "hermes_home_at_file", "hermes_home"),
        ("hermes_home_relative", "hermes_home_relative", "hermes_home"),
        ("hermes_home_empty", "hermes_home_empty", "root"),
        ("hermes_home_whitespace", "hermes_home_whitespace", "root"),
        ("active_profile_is_dir", "active_profile_is_dir", "root"),
        ("active_profile_binary", "active_profile_binary", "root"),
        ("active_profile_whitespace", "active_profile_whitespace", "root"),
        ("profiles_name_is_file", "profiles_name_is_file", "root"),
        ("unresolvable_home", "unresolvable_home", "root"),
    ],
)
def test_resolver_never_raises_on_hostile_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case_name: str,
    setup: str,
    expected_tier: str,
) -> None:
    monkeypatch.setattr(paths_mod.platform, "system", lambda: "Windows")  # type: ignore[attr-defined]
    monkeypatch.delenv("HERMES_HOME", raising=False)

    if setup == "empty_localappdata":
        monkeypatch.setenv("LOCALAPPDATA", "")
        monkeypatch.setattr(paths_mod.Path, "home", classmethod(lambda cls: tmp_path))  # type: ignore[attr-defined]
    elif setup == "hermes_home_at_file":
        file_path = tmp_path / "a_file"
        file_path.write_text("not a dir")
        monkeypatch.setenv("HERMES_HOME", str(file_path))
    elif setup == "hermes_home_relative":
        monkeypatch.setenv("HERMES_HOME", "relative/path")
    elif setup == "hermes_home_empty":
        monkeypatch.setenv("HERMES_HOME", "")
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    elif setup == "hermes_home_whitespace":
        monkeypatch.setenv("HERMES_HOME", "   ")
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    elif setup == "active_profile_is_dir":
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        root = tmp_path / "hermes"
        root.mkdir(parents=True)
        ap = root / "active_profile"
        ap.mkdir()
    elif setup == "active_profile_binary":
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        root = tmp_path / "hermes"
        root.mkdir(parents=True)
        (root / "active_profile").write_bytes(b"\x80\x81\x82\xff")
    elif setup == "active_profile_whitespace":
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        root = tmp_path / "hermes"
        root.mkdir(parents=True)
        (root / "active_profile").write_text("   \n  ")
    elif setup == "profiles_name_is_file":
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        root = tmp_path / "hermes"
        root.mkdir(parents=True)
        (root / "active_profile").write_text("myprofile")
        profiles = root / "profiles"
        profiles.mkdir()
        (profiles / "myprofile").write_text("I am a file, not a dir")
    elif setup == "unresolvable_home":
        monkeypatch.setenv("LOCALAPPDATA", "")
        monkeypatch.setattr(
            paths_mod.Path,  # type: ignore[attr-defined]
            "home",
            classmethod(lambda cls: (_ for _ in ()).throw(RuntimeError("no home"))),
        )

    res = resolve_hermes_config_path()
    assert res.tier == expected_tier


def test_pointer_content_followed_verbatim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pointer with path separators or .. is joined verbatim."""
    monkeypatch.delenv("HERMES_HOME", raising=False)
    root = _setup_root(tmp_path, monkeypatch, system="Linux")

    root.mkdir(parents=True, exist_ok=True)
    nested = root / "profiles" / "a" / "b"
    nested.mkdir(parents=True)
    (root / "active_profile").write_text("a/b")

    res = resolve_hermes_config_path()
    assert res.tier == "profile"
    assert "a" in str(res.path) and "b" in str(res.path)


def test_hermes_home_dir_without_config_is_unconditional_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HERMES_HOME dir without config.yaml → tier hermes_home, profile NOT read."""
    root = _setup_root(tmp_path, monkeypatch, system="Windows")
    monkeypatch.delenv("HERMES_HOME", raising=False)

    custom_home = tmp_path / "custom_no_config"
    custom_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(custom_home))

    profile_dir = root / "profiles" / "gibson"
    _write_config(profile_dir / "config.yaml", {"fail_mode": "degraded"})
    (root / "active_profile").write_text("gibson")

    res = resolve_hermes_config_path()
    assert res.tier == "hermes_home"
    assert not res.path.is_file()

    section = read_petasos_section(res)
    assert section == {}


def test_warning_implies_root_tier(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Whenever warning is non-None, tier must be root."""
    monkeypatch.delenv("HERMES_HOME", raising=False)
    root = _setup_root(tmp_path, monkeypatch, system="Windows")
    root.mkdir(parents=True, exist_ok=True)
    (root / "active_profile").write_text("ghost")

    res = resolve_hermes_config_path()
    assert res.warning is not None
    assert res.tier == "root"


# ---------------------------------------------------------------------------
# _load_config / read_petasos_section tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        "not: yaml: {{",
        "[1, 2, 3]",
        'petasos: "closed"',
    ],
    ids=["garbage_yaml", "yaml_list", "petasos_scalar"],
)
def test_load_config_never_raises_on_bad_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str
) -> None:
    monkeypatch.delenv("HERMES_HOME", raising=False)
    root = _setup_root(tmp_path, monkeypatch, system="Windows")
    config_path = root / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(content, encoding="utf-8")

    res = resolve_hermes_config_path()
    section = read_petasos_section(res)
    assert section == {}


def test_load_config_split_brain_uses_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Root and profile configs disagree on fail_mode → profile wins."""
    monkeypatch.delenv("HERMES_HOME", raising=False)
    root = _setup_root(tmp_path, monkeypatch, system="Windows")

    _write_config(root / "config.yaml", {"fail_mode": "closed"})
    profile_dir = root / "profiles" / "gibson"
    _write_config(profile_dir / "config.yaml", {"fail_mode": "degraded"})
    (root / "active_profile").write_text("gibson")

    res = resolve_hermes_config_path()
    section = read_petasos_section(res)
    assert section["fail_mode"] == "degraded"


# ---------------------------------------------------------------------------
# Logging (D4)
# ---------------------------------------------------------------------------


def test_resolved_path_logged_at_info(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """plugin_api._load_config logs resolved path + tier at INFO."""
    fastapi = pytest.importorskip("fastapi")  # noqa: F841

    monkeypatch.delenv("HERMES_HOME", raising=False)
    root = _setup_root(tmp_path, monkeypatch, system="Windows")
    _write_config(root / "config.yaml", {"fail_mode": "closed"})

    import petasos.console.hermes.plugin_api as mod

    with caplog.at_level(logging.INFO, logger="petasos.dashboard"):
        mod._load_config()

    assert any("loading config from" in r.message and "tier=" in r.message for r in caplog.records)


def test_resolved_path_logged_warning_on_dangling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Dangling active_profile emits WARNING via caller."""
    fastapi = pytest.importorskip("fastapi")  # noqa: F841

    monkeypatch.delenv("HERMES_HOME", raising=False)
    root = _setup_root(tmp_path, monkeypatch, system="Windows")
    root.mkdir(parents=True, exist_ok=True)
    _write_config(root / "config.yaml", {"fail_mode": "closed"})
    (root / "active_profile").write_text("phantom")

    import petasos.console.hermes.plugin_api as mod

    with caplog.at_level(logging.WARNING, logger="petasos.dashboard"):
        mod._load_config()

    assert any("profile resolution" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# Reference plugin parity
# ---------------------------------------------------------------------------


def test_reference_plugin_same_resolution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """reference_plugin._load_config returns same content+type as plugin_api."""
    fastapi = pytest.importorskip("fastapi")  # noqa: F841

    monkeypatch.delenv("HERMES_HOME", raising=False)
    root = _setup_root(tmp_path, monkeypatch, system="Windows")
    _write_config(root / "config.yaml", {"fail_mode": "degraded", "anonymize": True})

    import petasos.console.hermes.plugin_api as plugin_api_mod

    plugin_result = plugin_api_mod._load_config()

    project_root = Path(__file__).resolve().parent.parent
    ref_mod = _load_reference_plugin_module(project_root)
    ref_result = ref_mod._load_config()

    assert isinstance(plugin_result, dict)
    assert isinstance(ref_result, dict)
    assert plugin_result == ref_result


def test_reference_plugin_parity_missing_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both return {} when config.yaml is missing."""
    fastapi = pytest.importorskip("fastapi")  # noqa: F841

    monkeypatch.delenv("HERMES_HOME", raising=False)
    root = _setup_root(tmp_path, monkeypatch, system="Windows")
    root.mkdir(parents=True, exist_ok=True)

    import petasos.console.hermes.plugin_api as plugin_api_mod

    plugin_result = plugin_api_mod._load_config()

    project_root = Path(__file__).resolve().parent.parent
    ref_mod = _load_reference_plugin_module(project_root)
    ref_result = ref_mod._load_config()

    assert plugin_result == {} or plugin_result == ref_result
    assert isinstance(ref_result, dict)
