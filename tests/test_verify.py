"""Tests for docs/deployment/reference_plugin/verify.py.

PET-86 / D7: verify.py gains orphan and split-brain detection and is
brought under test for the first time.  Loaded via importlib since it
lives outside the package tree.

PET-189: the config, feature, and arming rows are read from the deployed
config, built by the plugin's own builder; a structural pin keeps them there.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import re
import sys
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
    """A fresh verify module per call, so the PET-189 resolver memo starts empty.

    Registered in sys.modules before exec: @dataclass resolves string annotations
    (the module has `from __future__ import annotations`) through
    sys.modules[cls.__module__], which is None for an unregistered spec-loaded
    module. In deployment the script runs as __main__, which is always registered.
    Each call rebinds the same key to a new module object, so nothing is shared.
    """
    verify_path = _PROJECT_ROOT / "docs" / "deployment" / "reference_plugin" / "verify.py"
    spec = importlib.util.spec_from_file_location("verify", verify_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
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


def test_missing_build_scanners_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """PET-174 D7: a plugin newer than the library FAILs pre-flight.

    Asserted twice. The base-install shape (no ML extras) is the one that matters:
    ``check_scanner_imports`` returns WARN there and ``main()`` counts only FAIL,
    so a probe appended after the availability tally would be skipped on exactly
    the deployment where the skew boots the plugin unenforcing.
    """
    # sys.modules, not the package attribute: tests/test_scanner_init.py reimports
    # petasos.scanners and restores sys.modules from a snapshot, so the two can
    # point at different module objects. verify.py's function-local
    # `from petasos.scanners import ...` reads sys.modules.
    import sys

    import petasos.scanners  # noqa: F401

    scanners_pkg = sys.modules["petasos.scanners"]
    verify = _load_verify_module()

    monkeypatch.delattr(scanners_pkg, "build_scanners", raising=False)
    status, detail = verify.check_scanner_imports()
    assert status == verify.FAIL
    assert "build_scanners" in detail

    for class_name in ("LlmGuardScanner", "LlamaFirewallScanner", "PresidioScanner"):
        monkeypatch.delattr(scanners_pkg, class_name, raising=False)
    status, detail = verify.check_scanner_imports()
    assert status == verify.FAIL
    assert "build_scanners" in detail


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


# ---------------------------------------------------------------------------
# PET-189: the config, feature, and arming rows report the deployed config
# ---------------------------------------------------------------------------


def _reset_armed() -> None:
    """read_armed keeps a process-global mtime/size/TTL cache that a freshly
    loaded verify module does not reset."""
    import petasos.console._armed as armed_mod

    armed_mod._reset_armed_cache()


def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop every env var the plugin's config builder overlays, so a case's
    section is the only thing shaping the resulting config."""
    for var in (
        "PETASOS_HASH_KEY",
        "PETASOS_SESSION_SECRET",
        "PETASOS_AUDIT_FINDING",
        "PETASOS_LICENSE_KEY",
    ):
        monkeypatch.delenv(var, raising=False)


def _plugin_stub(tmp_path: Path, name: str, source: str) -> Path:
    """A stand-in sibling __init__.py, for the plugin-skew cases."""
    stub = tmp_path / name
    stub.write_text(source, encoding="utf-8")
    return stub


# --- Behavioural -----------------------------------------------------------


def test_check_features_names_disabled_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression for PET-189: the row named every feature 'available' over a
    config that turned two of them off."""
    _clean_env(monkeypatch)
    root = _setup_clean_install(
        tmp_path,
        monkeypatch,
        profile="gibson",
        root_section={"fail_mode": "closed"},
        profile_section={"tool_guard_enabled": False, "alert_enabled": False},
    )

    verify = _load_verify_module()
    status, detail = verify.check_features()
    assert status == verify.WARN
    assert "tool_guard" in detail
    assert "alerting" in detail
    assert "frequency" not in detail
    assert str(root / "profiles" / "gibson" / "config.yaml") in detail


def test_check_features_all_on_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """All five on in the deployed section → PASS naming path and tier."""
    _clean_env(monkeypatch)
    root = _setup_clean_install(
        tmp_path,
        monkeypatch,
        profile="gibson",
        root_section={"fail_mode": "closed"},
        profile_section={"fail_mode": "closed"},
    )

    verify = _load_verify_module()
    status, detail = verify.check_features()
    assert status == verify.PASS
    assert str(root / "profiles" / "gibson" / "config.yaml") in detail
    assert "tier=profile" in detail


def test_check_features_missing_section_reports_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No petasos: key at all → the row says it is reporting library defaults."""
    _clean_env(monkeypatch)
    root = _setup_root(tmp_path, monkeypatch, system="Windows")
    _write_config(root / "config.yaml", {"fail_mode": "closed"})
    profile_dir = root / "profiles" / "gibson"
    _write_config(profile_dir / "config.yaml", None)
    (root / "active_profile").write_text("gibson")

    verify = _load_verify_module()
    status, detail = verify.check_features()
    assert status == verify.WARN
    assert "library defaults" in detail
    assert "no usable petasos:" in detail

    status_cfg, detail_cfg = verify.check_config()
    assert status_cfg == verify.FAIL
    assert "No usable 'petasos:' section" in detail_cfg


def test_check_features_malformed_section_reports_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """petasos: is a list, not a mapping → defaults, said out loud."""
    _clean_env(monkeypatch)
    root = _setup_root(tmp_path, monkeypatch, system="Windows")
    _write_config(root / "config.yaml", {"fail_mode": "closed"})
    profile_dir = root / "profiles" / "gibson"
    _write_config_raw(
        profile_dir / "config.yaml",
        "model:\n  provider: test\npetasos: [1, 2]\n",
    )
    (root / "active_profile").write_text("gibson")

    verify = _load_verify_module()
    status, detail = verify.check_features()
    assert status == verify.WARN
    assert "unreadable" in detail

    status_cfg, detail_cfg = verify.check_config()
    assert status_cfg == verify.FAIL
    assert "unreadable" in detail_cfg


def test_check_features_rejected_section_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A section the plugin's builder rejects is not a feature state worth reading."""
    _clean_env(monkeypatch)
    _setup_clean_install(
        tmp_path,
        monkeypatch,
        profile="gibson",
        root_section={"fail_mode": "closed"},
        profile_section={"fail_mode": "bogus"},
    )

    verify = _load_verify_module()
    status, detail = verify.check_features()
    assert status == verify.FAIL
    assert "rejected" in detail
    assert "bogus" in detail

    status_cfg, detail_cfg = verify.check_config()
    assert status_cfg == verify.FAIL
    assert "rejected" in detail_cfg
    assert "bogus" in detail_cfg


def test_check_features_ignores_license_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """All features are free; the license key must not move the row.

    Two independent module loads, not two calls on one module: the resolver
    memoises, so a second call would return the first answer and pass vacuously.
    """
    _clean_env(monkeypatch)
    _setup_clean_install(
        tmp_path,
        monkeypatch,
        profile="gibson",
        root_section={"fail_mode": "closed"},
        profile_section={"tool_guard_enabled": False, "alert_enabled": False},
    )

    monkeypatch.delenv("PETASOS_LICENSE_KEY", raising=False)
    without_key = _load_verify_module().check_features()

    monkeypatch.setenv("PETASOS_LICENSE_KEY", "not-a-real-jwt")
    with_key = _load_verify_module().check_features()

    assert without_key == with_key


def test_check_features_sibling_skew_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sibling plugin without the builder FAILs both rows, no local fallback."""
    _clean_env(monkeypatch)
    _setup_clean_install(
        tmp_path,
        monkeypatch,
        profile="gibson",
        root_section={"fail_mode": "closed"},
        profile_section={"fail_mode": "closed"},
    )

    verify = _load_verify_module()
    monkeypatch.setattr(
        verify, "_PLUGIN_INIT_PATH", _plugin_stub(tmp_path, "skewed_plugin.py", "# plugin\n")
    )

    for status, detail in (verify.check_config(), verify.check_features()):
        assert status == verify.FAIL
        assert "_build_config_from_section" in detail


def test_check_features_sibling_import_error_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plugin too new for the installed library FAILs with the import error."""
    _clean_env(monkeypatch)
    _setup_clean_install(
        tmp_path,
        monkeypatch,
        profile="gibson",
        root_section={"fail_mode": "closed"},
        profile_section={"fail_mode": "closed"},
    )

    verify = _load_verify_module()
    monkeypatch.setattr(
        verify,
        "_PLUGIN_INIT_PATH",
        _plugin_stub(
            tmp_path,
            "too_new_plugin.py",
            "from petasos.session.formatting import definitely_missing_symbol\n",
        ),
    )

    status, detail = verify.check_features()
    assert status == verify.FAIL
    assert "does not import" in detail


def test_check_features_sibling_corrupt_copy_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A truncated hand-synced copy names the path and the exception class."""
    _clean_env(monkeypatch)
    _setup_clean_install(
        tmp_path,
        monkeypatch,
        profile="gibson",
        root_section={"fail_mode": "closed"},
        profile_section={"fail_mode": "closed"},
    )

    verify = _load_verify_module()
    stub = _plugin_stub(tmp_path, "corrupt_plugin.py", "def f(:\n")
    monkeypatch.setattr(verify, "_PLUGIN_INIT_PATH", stub)

    status, detail = verify.check_features()
    assert status == verify.FAIL
    assert "SyntaxError" in detail
    assert str(stub) in detail


def test_check_armed_disarmed_warns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """petasos.enabled: false → the run says the deployment enforces nothing."""
    _clean_env(monkeypatch)
    _reset_armed()
    _setup_clean_install(
        tmp_path,
        monkeypatch,
        profile="gibson",
        root_section={"enabled": False},
        profile_section={"enabled": False},
    )

    verify = _load_verify_module()
    status, detail = verify.check_armed()
    assert status == verify.WARN
    assert "DISARMED" in detail
    assert "Unequipped" in detail


def test_check_armed_explicit_true_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit enabled: true reads differently from the fail-secure default."""
    _clean_env(monkeypatch)
    _reset_armed()
    _setup_clean_install(
        tmp_path,
        monkeypatch,
        profile="gibson",
        root_section={"enabled": True},
        profile_section={"enabled": True},
    )

    verify = _load_verify_module()
    status, detail = verify.check_armed()
    assert status == verify.PASS
    assert "enabled is true" in detail


def test_check_armed_default_passes_with_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No enabled key → armed, and the row says it is the default that armed it."""
    _clean_env(monkeypatch)
    _reset_armed()
    _setup_clean_install(
        tmp_path,
        monkeypatch,
        profile="gibson",
        root_section={"fail_mode": "closed"},
        profile_section={"fail_mode": "closed"},
    )

    verify = _load_verify_module()
    status, detail = verify.check_armed()
    assert status == verify.PASS
    assert "fail-secure default" in detail


def test_check_armed_missing_file_warns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """read_armed is fail-secure True on a file it cannot stat, so a PASS here
    would report a bit nothing ever read."""
    _clean_env(monkeypatch)
    _reset_armed()
    _setup_root(tmp_path, monkeypatch, system="Windows")

    verify = _load_verify_module()
    status, detail = verify.check_armed()
    assert status == verify.WARN
    assert "fail-secure default" in detail
    assert "no config file" in detail


def test_check_armed_malformed_section_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unreadable petasos: section arms fail-secure; say so rather than PASS."""
    _clean_env(monkeypatch)
    _reset_armed()
    root = _setup_root(tmp_path, monkeypatch, system="Windows")
    _write_config_raw(root / "config.yaml", "model:\n  provider: test\npetasos: [1, 2]\n")

    verify = _load_verify_module()
    status, detail = verify.check_armed()
    assert status == verify.WARN
    assert "unreadable" in detail


def test_check_armed_non_bool_enabled_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """enabled: "yes" is not the boolean the console writes; name the raw value."""
    _clean_env(monkeypatch)
    _reset_armed()
    root = _setup_root(tmp_path, monkeypatch, system="Windows")
    _write_config_raw(
        root / "config.yaml",
        'model:\n  provider: test\npetasos:\n  enabled: "yes"\n',
    )

    verify = _load_verify_module()
    status, detail = verify.check_armed()
    assert status == verify.WARN
    assert "not a boolean" in detail
    assert "'yes'" in detail


def test_verify_main_prints_new_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The report carries a Plugin header, an Arming state row, and a WARN tally."""
    _clean_env(monkeypatch)
    _reset_armed()
    root = _setup_clean_install(
        tmp_path,
        monkeypatch,
        profile="gibson",
        root_section={"enabled": False},
        profile_section={"enabled": False},
    )
    profile_config = str(root / "profiles" / "gibson" / "config.yaml")

    verify = _load_verify_module()
    rc = verify.main()
    out = capsys.readouterr().out

    assert "  Plugin: " in out
    assert "Feature activation" in out
    assert "Arming state" in out
    assert profile_config in out
    # Env vars are unset here, so the run FAILs and says so.
    assert rc == 1
    assert "FAILED" in out.strip().splitlines()[-1]

    # Same deployment with the required env present: no FAIL, but the RESULT line
    # must not read as an unqualified all-clear while the deployment is disarmed.
    _reset_armed()
    monkeypatch.setenv("PETASOS_SESSION_SECRET", "c2VjcmV0")
    monkeypatch.setenv("PETASOS_HASH_KEY", "hash-key")
    verify2 = _load_verify_module()
    rc2 = verify2.main()
    out2 = capsys.readouterr().out
    assert rc2 == 0
    last = out2.strip().splitlines()[-1]
    match = re.fullmatch(r"RESULT: All checks passed \((\d+) warning\(s\), review above\)", last)
    assert match is not None, last
    assert int(match.group(1)) >= 1


# --- Parity ----------------------------------------------------------------


def test_resolved_config_matches_plugin_builder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One derivation: verify.py's config IS the plugin builder's output.

    The section is one the pre-PET-189 check_config could not build at all (its
    from_dict raises without a hash key), so this discriminates the builder from
    both the old path and bare defaults.
    """
    _clean_env(monkeypatch)
    section = {
        "fail_mode": "closed",
        "anonymize": True,
        "redaction_mode": "hash",
        "alert_enabled": False,
    }
    _setup_clean_install(
        tmp_path,
        monkeypatch,
        profile="gibson",
        root_section=dict(section),
        profile_section=dict(section),
    )
    monkeypatch.delenv("PETASOS_HASH_KEY", raising=False)
    monkeypatch.setenv("PETASOS_AUDIT_FINDING", "1")

    plugin_spec = importlib.util.spec_from_file_location(
        "petasos_reference_plugin_pet189",
        _PROJECT_ROOT / "docs" / "deployment" / "reference_plugin" / "__init__.py",
    )
    assert plugin_spec is not None and plugin_spec.loader is not None
    plugin = importlib.util.module_from_spec(plugin_spec)
    plugin_spec.loader.exec_module(plugin)

    verify = _load_verify_module()
    resolved = verify.resolve_deployed_config()

    assert resolved.origin == "section"
    assert resolved.config == plugin._build_config_from_section(dict(section))
    # The two overlays the old check_config had drifted on.
    assert resolved.config.anonymize is False
    assert resolved.config.audit_emit_findings is True


def test_session_feature_table_matches_pipeline() -> None:
    """verify.py's display names must be the pipeline's gate names, order included."""
    from petasos import Pipeline

    verify = _load_verify_module()
    assert tuple(Pipeline._FEATURE_GATES.items()) == verify._SESSION_FEATURES


# --- Structural (D7) -------------------------------------------------------

_CONFIG_ROWS = ("check_config", "check_features", "resolve_deployed_config")


def _is_petasos_config_call(node: ast.AST) -> bool:
    """True for ``PetasosConfig(...)`` and ``PetasosConfig.from_dict(...)``."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "PetasosConfig"
    if isinstance(func, ast.Attribute) and func.attr == "from_dict":
        return isinstance(func.value, ast.Name) and func.value.id == "PetasosConfig"
    return False


def check_no_literal_config(source: str) -> list[str]:
    """Violations of D7 in *source*; empty list means clean.

    Pure over source text, so it can be exercised on a synthetic that does
    violate, and never passes over an empty node set: a missing or duplicated
    function is itself a violation.
    """
    tree = ast.parse(source)
    violations: list[str] = []
    for name in _CONFIG_ROWS:
        defs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name]
        if len(defs) != 1:
            violations.append(
                f"{name}: expected exactly one function definition, found {len(defs)}"
            )
            continue
        calls: list[ast.Call] = [
            n for n in ast.walk(defs[0]) if isinstance(n, ast.Call) and _is_petasos_config_call(n)
        ]
        if name == "resolve_deployed_config":
            # One bare PetasosConfig() is allowed here: the rejected-section
            # fallback mirroring the plugin's own swallow.
            if len(calls) > 1:
                violations.append(f"{name}: {len(calls)} PetasosConfig constructions, expected 1")
            for call in calls:
                if call.args or call.keywords:
                    violations.append(
                        f"{name}: PetasosConfig at line {call.lineno} takes arguments;"
                        " only a defaults-only fallback is allowed"
                    )
        elif calls:
            violations.append(
                f"{name}: constructs PetasosConfig at line {calls[0].lineno};"
                " this row must report the deployed config, not a literal"
            )
    return violations


def test_config_rows_construct_no_literal_config() -> None:
    """Regression for PET-189: the row reported a config it had built itself."""
    verify_source = (
        _PROJECT_ROOT / "docs" / "deployment" / "reference_plugin" / "verify.py"
    ).read_text(encoding="utf-8")
    assert check_no_literal_config(verify_source) == []


def test_config_rows_checker_rejects_synthetic_literal() -> None:
    """The checker has teeth, and cannot pass vacuously."""
    violating = """
def check_config():
    return resolve_deployed_config()


def check_features():
    config = PetasosConfig(fail_mode="closed", tool_guard_enabled=True)
    return config


def resolve_deployed_config():
    return PetasosConfig()
"""
    violations = check_no_literal_config(violating)
    assert any("check_features" in v and "constructs PetasosConfig" in v for v in violations)

    absent = """
def check_config():
    return resolve_deployed_config()


def resolve_deployed_config():
    return PetasosConfig()
"""
    violations_absent = check_no_literal_config(absent)
    assert any("check_features" in v and "expected exactly one" in v for v in violations_absent)
