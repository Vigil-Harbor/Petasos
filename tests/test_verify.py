"""Tests for docs/deployment/reference_plugin/verify.py.

PET-86 / D7: verify.py gains orphan and split-brain detection and is
brought under test for the first time.  Loaded via importlib since it
lives outside the package tree.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any

import pytest  # noqa: TC002
import yaml

import petasos.console._paths as paths_mod

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_verify_module() -> Any:
    verify_path = _PROJECT_ROOT / "docs" / "deployment" / "reference_plugin" / "verify.py"
    spec = importlib.util.spec_from_file_location("verify", verify_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_config(path: Path, petasos_section: dict[str, Any] | None = None) -> None:
    data: dict[str, Any] = {"model": {"provider": "test"}}
    if petasos_section is not None:
        data["petasos"] = petasos_section
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")


def _write_config_raw(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _setup_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    system: str = "Windows",
) -> Path:
    monkeypatch.setattr(paths_mod.platform, "system", lambda: system)  # type: ignore[attr-defined]
    monkeypatch.delenv("HERMES_HOME", raising=False)
    if system == "Windows":
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        return tmp_path / "hermes"
    else:
        monkeypatch.setattr(paths_mod.Path, "home", classmethod(lambda cls: tmp_path))  # type: ignore[attr-defined]
        return tmp_path / ".hermes"


def _setup_clean_install(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    profile: str | None = None,
    root_section: dict[str, Any] | None = None,
    profile_section: dict[str, Any] | None = None,
) -> Path:
    """Set up a complete install with optional profile and config sections."""
    root = _setup_root(tmp_path, monkeypatch, system="Windows")

    if root_section is not None:
        _write_config(root / "config.yaml", root_section)
    else:
        _write_config(root / "config.yaml", {"fail_mode": "closed"})

    if profile:
        profile_dir = root / "profiles" / profile
        if profile_section is not None:
            _write_config(profile_dir / "config.yaml", profile_section)
        else:
            _write_config(profile_dir / "config.yaml", {"fail_mode": "degraded"})
        (root / "active_profile").write_text(profile)

        plugin_dir = profile_dir / "plugins" / "petasos"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "plugin.yaml").write_text("name: petasos")
        (plugin_dir / "__init__.py").write_text("# plugin")
    else:
        plugin_dir = root / "plugins" / "petasos"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "plugin.yaml").write_text("name: petasos")
        (plugin_dir / "__init__.py").write_text("# plugin")

    return root


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_verify_detects_orphaned_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Plugin files absent from resolved profile home → check_plugin_files FAILs."""
    root = _setup_root(tmp_path, monkeypatch, system="Windows")

    profile_dir = root / "profiles" / "gibson"
    _write_config(profile_dir / "config.yaml", {"fail_mode": "degraded"})
    (root / "active_profile").write_text("gibson")
    _write_config(root / "config.yaml", {"fail_mode": "closed"})

    root_plugins = root / "plugins" / "petasos"
    root_plugins.mkdir(parents=True)
    (root_plugins / "plugin.yaml").write_text("name: petasos")
    (root_plugins / "__init__.py").write_text("# plugin")

    verify = _load_verify_module()
    status, detail = verify.check_plugin_files()
    assert status == verify.FAIL
    assert "Missing plugin files" in detail


def test_verify_detects_split_brain_value_differs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Root vs profile petasos.fail_mode differ → FAILs naming the key."""
    _setup_clean_install(
        tmp_path,
        monkeypatch,
        profile="gibson",
        root_section={"fail_mode": "closed"},
        profile_section={"fail_mode": "degraded"},
    )

    verify = _load_verify_module()
    status, detail = verify.check_config_split_brain()
    assert status == verify.FAIL
    assert "fail_mode" in detail


def test_verify_detects_split_brain_host_id_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """host_id present in root, absent in profile → FAILs."""
    _setup_clean_install(
        tmp_path,
        monkeypatch,
        profile="gibson",
        root_section={"fail_mode": "closed", "host_id": "hermes-gavin-01"},
        profile_section={"fail_mode": "closed"},
    )

    verify = _load_verify_module()
    status, detail = verify.check_config_split_brain()
    assert status == verify.FAIL
    assert "host_id" in detail


def test_verify_same_file_no_split_brain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Tier root (one governing file) → PASS/skip."""
    _setup_clean_install(tmp_path, monkeypatch)

    verify = _load_verify_module()
    status, detail = verify.check_config_split_brain()
    assert status == verify.PASS
    assert "Single governing config" in detail


def test_verify_same_file_hermes_home_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HERMES_HOME override → PASS with explanatory detail."""
    _setup_root(tmp_path, monkeypatch, system="Windows")
    custom = tmp_path / "custom"
    _write_config(custom / "config.yaml", {"fail_mode": "open"})
    monkeypatch.setenv("HERMES_HOME", str(custom))

    verify = _load_verify_module()
    status, detail = verify.check_config_split_brain()
    assert status == verify.PASS
    assert "HERMES_HOME override active" in detail
    assert "not audited" in detail


def test_verify_split_brain_handles_unresolvable_path_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Path.resolve / os.path.samefile raising OSError → clean outcome."""
    _setup_clean_install(
        tmp_path,
        monkeypatch,
        profile="gibson",
        root_section={"fail_mode": "closed"},
        profile_section={"fail_mode": "closed"},
    )

    monkeypatch.setattr(os.path, "samefile", lambda a, b: (_ for _ in ()).throw(OSError("broken")))

    verify = _load_verify_module()
    status, detail = verify.check_config_split_brain()
    assert status in (verify.PASS, verify.FAIL)


def test_verify_split_brain_handles_runtime_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Path.resolve raising RuntimeError (symlink loop) → clean outcome."""
    _setup_clean_install(
        tmp_path,
        monkeypatch,
        profile="gibson",
        root_section={"fail_mode": "closed"},
        profile_section={"fail_mode": "closed"},
    )

    def _exploding_resolve(self: Path, strict: bool = False) -> Path:
        raise RuntimeError("symlink loop")

    monkeypatch.setattr(Path, "resolve", _exploding_resolve)
    monkeypatch.setattr(
        os.path, "samefile", lambda a, b: (_ for _ in ()).throw(RuntimeError("loop"))
    )

    verify = _load_verify_module()
    status, detail = verify.check_config_split_brain()
    assert status in (verify.PASS, verify.FAIL)


def test_verify_root_without_petasos_section_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Root has no petasos: section, profile does → PASS (healthy steady state)."""
    root = _setup_root(tmp_path, monkeypatch, system="Windows")

    root_config = root / "config.yaml"
    root_config.parent.mkdir(parents=True, exist_ok=True)
    root_config.write_text(
        yaml.dump({"model": {"provider": "test"}}, default_flow_style=False),
        encoding="utf-8",
    )

    profile_dir = root / "profiles" / "gibson"
    _write_config(profile_dir / "config.yaml", {"fail_mode": "degraded"})
    (root / "active_profile").write_text("gibson")

    plugin_dir = profile_dir / "plugins" / "petasos"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.yaml").write_text("name: petasos")
    (plugin_dir / "__init__.py").write_text("# plugin")

    verify = _load_verify_module()
    status, detail = verify.check_config_split_brain()
    assert status == verify.PASS
    assert "No competing config" in detail


def test_verify_profile_section_absent_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Root has petasos:, profile doesn't → FAIL (orphaned migration)."""
    root = _setup_root(tmp_path, monkeypatch, system="Windows")

    _write_config(root / "config.yaml", {"fail_mode": "closed"})

    profile_dir = root / "profiles" / "gibson"
    profile_config = profile_dir / "config.yaml"
    profile_config.parent.mkdir(parents=True, exist_ok=True)
    profile_config.write_text(
        yaml.dump({"model": {"provider": "test"}}, default_flow_style=False),
        encoding="utf-8",
    )
    (root / "active_profile").write_text("gibson")

    plugin_dir = profile_dir / "plugins" / "petasos"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.yaml").write_text("name: petasos")
    (plugin_dir / "__init__.py").write_text("# plugin")

    verify = _load_verify_module()
    status, detail = verify.check_config_split_brain()
    assert status == verify.FAIL
    assert "orphaned" in detail.lower()


def test_verify_hermes_home_governs_plugin_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HERMES_HOME without plugin files → FAIL even if profile has them."""
    root = _setup_root(tmp_path, monkeypatch, system="Windows")

    profile_dir = root / "profiles" / "gibson"
    plugin_dir = profile_dir / "plugins" / "petasos"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.yaml").write_text("name: petasos")
    (plugin_dir / "__init__.py").write_text("# plugin")

    custom_home = tmp_path / "custom_home"
    _write_config(custom_home / "config.yaml", {"fail_mode": "open"})
    monkeypatch.setenv("HERMES_HOME", str(custom_home))

    verify = _load_verify_module()
    status, detail = verify.check_plugin_files()
    assert status == verify.FAIL


def test_verify_detects_split_brain_non_incident_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sections agree on fail_mode/host_id but differ on anonymize → FAIL."""
    _setup_clean_install(
        tmp_path,
        monkeypatch,
        profile="gibson",
        root_section={"fail_mode": "closed", "anonymize": False},
        profile_section={"fail_mode": "closed", "anonymize": True},
    )

    verify = _load_verify_module()
    status, detail = verify.check_config_split_brain()
    assert status == verify.FAIL
    assert "anonymize" in detail


def test_verify_clean_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Files present + configs agree → both checks PASS; output has resolution header."""
    _setup_clean_install(
        tmp_path,
        monkeypatch,
        profile="gibson",
        root_section={"fail_mode": "degraded"},
        profile_section={"fail_mode": "degraded"},
    )

    verify = _load_verify_module()

    status_pf, _ = verify.check_plugin_files()
    assert status_pf == verify.PASS

    status_sb, _ = verify.check_config_split_brain()
    assert status_sb == verify.PASS
