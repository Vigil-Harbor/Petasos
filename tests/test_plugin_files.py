"""PET-236: the file-based predictor, against fake plugin folders.

Real Hermes modules are compared with this predictor in the hand-run harness
(scripts/hermes_multiprofile_harness.py), not here.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

import petasos.console._paths as paths_mod
import petasos.console._plugin_files as pf
from petasos.console._paths import HermesConfigResolution
from petasos.console._plugin_files import is_hermes_home, protection_status

ENABLED = "plugins:\n  enabled:\n  - petasos\n"


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # hermes_root() ignores HERMES_HOME, so every path to the real root is moved too.
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "empty"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("HOME", str(tmp_path / "user"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "user"))


def _folder(
    plugins: Path,
    name: str,
    manifest: str | None = "name: petasos\n",
    *,
    init: bool = True,
    filename: str = "plugin.yaml",
) -> Path:
    folder = plugins / name
    folder.mkdir(parents=True)
    if manifest is not None:
        (folder / filename).write_text(manifest, encoding="utf-8")
    if init:
        (folder / "__init__.py").write_text("", encoding="utf-8")
    return folder


def _home(tmp_path: Path, config: str | None = ENABLED) -> Path:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    if config is not None:
        (home / "config.yaml").write_text(config, encoding="utf-8")
    return home


# ── Status, in order ─────────────────────────────────────────────────────────


def test_clean_copy_can_load(tmp_path: Path) -> None:
    home = _home(tmp_path)
    copy = _folder(home / "plugins", "petasos")
    found = protection_status(home)
    assert found.status == "hook_can_load"
    assert found.winner == copy
    assert found.claimants == ()
    assert found.next_steps == ""
    assert "can load" in found.detail


def test_regression_pet236_bak_sibling_wins_and_is_flagged(tmp_path: Path) -> None:
    home = _home(tmp_path)
    _folder(home / "plugins", "petasos")
    bak = _folder(home / "plugins", "petasos.bak-20260728")
    found = protection_status(home)
    assert found.status == "shadowed"
    assert found.winner == bak
    assert found.claimants == (bak,)


def test_loser_sorting_before_petasos_is_still_a_claimant(tmp_path: Path) -> None:
    home = _home(tmp_path)
    loser = _folder(home / "plugins", "backup-petasos")
    copy = _folder(home / "plugins", "petasos")
    found = protection_status(home)
    assert found.status == "shadowed"
    assert found.winner == copy
    assert found.claimants == (loser,)


def test_nested_backup_is_a_claimant_but_never_the_winner(tmp_path: Path) -> None:
    home = _home(tmp_path)
    copy = _folder(home / "plugins", "petasos")
    nested = _folder(home / "plugins" / "old", "petasos-copy")
    found = protection_status(home)
    assert found.status == "shadowed"
    assert found.winner == copy
    assert found.claimants == (nested,)


def test_two_backups_both_named(tmp_path: Path) -> None:
    home = _home(tmp_path)
    _folder(home / "plugins", "petasos")
    a = _folder(home / "plugins", "petasos.bak-1")
    b = _folder(home / "plugins", "petasos.bak-2")
    found = protection_status(home)
    assert found.claimants == (a, b)
    assert found.winner == b


def test_shadowed_outranks_not_enabled(tmp_path: Path) -> None:
    home = _home(tmp_path, "plugins:\n  enabled: []\n")
    _folder(home / "plugins", "petasos")
    _folder(home / "plugins", "petasos.bak-1")
    assert protection_status(home).status == "shadowed"


def test_winner_with_no_init_is_no_copy(tmp_path: Path) -> None:
    home = _home(tmp_path)
    _folder(home / "plugins", "petasos", init=False)
    assert protection_status(home).status == "no_copy"


def test_disabled_beats_enabled(tmp_path: Path) -> None:
    home = _home(tmp_path, "plugins:\n  enabled: [petasos]\n  disabled: [petasos]\n")
    _folder(home / "plugins", "petasos")
    assert protection_status(home).status == "not_enabled"


def test_scalar_enabled_counts_as_nothing(tmp_path: Path) -> None:
    home = _home(tmp_path, "plugins:\n  enabled: petasos\n")
    _folder(home / "plugins", "petasos")
    found = protection_status(home)
    assert found.status == "not_enabled"
    assert found.configured is False


def test_unhashable_enabled_entry_counts_as_nothing(tmp_path: Path) -> None:
    home = _home(tmp_path, "plugins:\n  enabled:\n  - petasos\n  - {a: 1}\n")
    _folder(home / "plugins", "petasos")
    assert protection_status(home).status == "not_enabled"


def test_petasos_section_counts_as_configured(tmp_path: Path) -> None:
    home = _home(tmp_path, "petasos:\n  enabled: true\n")
    assert protection_status(home).configured is True


def test_empty_config_is_not_a_config_failure(tmp_path: Path) -> None:
    home = _home(tmp_path, "")
    _folder(home / "plugins", "petasos")
    assert protection_status(home).status == "not_enabled"


# ── Selection rules ──────────────────────────────────────────────────────────


def test_manifest_with_no_name_claims_the_folder_name(tmp_path: Path) -> None:
    home = _home(tmp_path)
    copy = _folder(home / "plugins", "petasos", "version: 1\n")
    _folder(home / "plugins", "petasos.old", "version: 1\n")
    found = protection_status(home)
    assert found.status == "hook_can_load"
    assert found.winner == copy


def test_empty_manifest_claims_the_folder_name(tmp_path: Path) -> None:
    home = _home(tmp_path)
    copy = _folder(home / "plugins", "petasos", "")
    assert protection_status(home).winner == copy


def test_plugin_yml_fallback(tmp_path: Path) -> None:
    home = _home(tmp_path)
    copy = _folder(home / "plugins", "petasos", filename="plugin.yml")
    assert protection_status(home).winner == copy


def test_malformed_manifest_is_skipped_and_not_recursed(tmp_path: Path) -> None:
    home = _home(tmp_path)
    copy = _folder(home / "plugins", "petasos")
    bad = _folder(home / "plugins", "zzz", "{not yaml: [")
    _folder(bad, "nested")  # a folder with a manifest file, even a bad one, is not walked
    found = protection_status(home)
    assert found.status == "hook_can_load"
    assert found.winner == copy


def test_regression_pet236_duplicate_key_manifest_is_no_manifest(tmp_path: Path) -> None:
    # Hermes's parser raises on a duplicate key and loads no hook; PyYAML keeps the last one.
    home = _home(tmp_path)
    _folder(home / "plugins", "petasos", "name: petasos\nname: petasos\n")
    found = protection_status(home)
    assert found.status == "no_copy"
    assert found.winner is None


def test_nested_duplicate_key_manifest_is_no_manifest(tmp_path: Path) -> None:
    home = _home(tmp_path)
    _folder(home / "plugins", "petasos", "name: petasos\nmeta:\n  a: 1\n  a: 2\n")
    assert protection_status(home).status == "no_copy"


def test_duplicate_key_config_is_a_config_failure(tmp_path: Path) -> None:
    home = _home(tmp_path, "plugins:\n  enabled: [petasos]\nplugins:\n  enabled: []\n")
    _folder(home / "plugins", "petasos")
    assert protection_status(home).status == "unknown"


def test_yaml_merge_keys_are_not_duplicates(tmp_path: Path) -> None:
    home = _home(tmp_path)
    _folder(home / "plugins", "petasos", "base: &b {x: 1}\na: {<<: *b}\nb: {<<: *b}\n")
    assert protection_status(home).status == "hook_can_load"


def test_regression_pet236_repeated_merge_key_is_a_duplicate(tmp_path: Path) -> None:
    # Hermes raises on a second << in one mapping; PyYAML would merge both.
    manifest = "a: &a {x: 1}\nb: &b {y: 2}\nc:\n  <<: *a\n  <<: *b\n"
    home = _home(tmp_path)
    _folder(home / "plugins", "petasos", manifest)
    assert protection_status(home).status == "no_copy"


def test_repeated_merge_key_in_config_is_a_config_failure(tmp_path: Path) -> None:
    config = (
        "base1: &a {enabled: [petasos]}\nbase2: &b {disabled: []}\nplugins:\n  <<: *a\n  <<: *b\n"
    )
    home = _home(tmp_path, config)
    _folder(home / "plugins", "petasos")
    assert protection_status(home).status == "unknown"


def test_bom_manifest(tmp_path: Path) -> None:
    home = _home(tmp_path)
    copy = _folder(home / "plugins", "other")
    (copy / "plugin.yaml").write_bytes(b"\xef\xbb\xbfname: petasos\n")
    assert protection_status(home).winner == copy


@pytest.mark.parametrize("skipped", ["__pycache__", ".claude-plugin"])
def test_skipped_folders_claim_nothing(tmp_path: Path, skipped: str) -> None:
    home = _home(tmp_path)
    _folder(home / "plugins", skipped)
    assert protection_status(home).status == "no_copy"


def test_plugin_named_file_is_not_a_folder(tmp_path: Path) -> None:
    home = _home(tmp_path)
    (home / "plugins").mkdir()
    (home / "plugins" / "petasos").write_text("", encoding="utf-8")
    assert protection_status(home).status == "no_copy"


def test_plugins_as_a_file_is_no_copy(tmp_path: Path) -> None:
    home = _home(tmp_path)
    (home / "plugins").write_text("", encoding="utf-8")
    assert protection_status(home).status == "no_copy"


def test_listing_oserror_is_no_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = _home(tmp_path)
    (home / "plugins").mkdir()

    def boom(self: Path) -> None:
        raise OSError("denied")

    monkeypatch.setattr(Path, "iterdir", boom)
    assert protection_status(home).status == "no_copy"


# ── unknown ──────────────────────────────────────────────────────────────────


def test_malformed_config_is_unknown(tmp_path: Path) -> None:
    home = _home(tmp_path, "{not yaml: [")
    _folder(home / "plugins", "petasos")
    found = protection_status(home)
    assert found.status == "unknown"
    assert "config.yaml" in found.detail


def test_non_mapping_config_is_unknown(tmp_path: Path) -> None:
    home = _home(tmp_path, "- a\n- b\n")
    assert protection_status(home).status == "unknown"


def test_malformed_config_does_not_hide_a_backup(tmp_path: Path) -> None:
    home = _home(tmp_path, "{not yaml: [")
    _folder(home / "plugins", "petasos")
    _folder(home / "plugins", "petasos.bak-1")
    assert protection_status(home).status == "shadowed"


def test_none_on_both_sides_does_not_compare_equal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _home(tmp_path)
    _folder(home / "plugins", "petasos")
    monkeypatch.setattr(pf, "_resolved_normcase", lambda path: None)
    assert protection_status(home).status == "unknown"


def test_injected_exception_never_escapes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(home: Path, profile: str | None) -> None:
        raise RuntimeError("surprise")

    monkeypatch.setattr(pf, "_status_from_files", boom)
    found = protection_status(_home(tmp_path))
    assert found.status == "unknown"
    assert "RuntimeError" in found.detail


# ── Path comparison ──────────────────────────────────────────────────────────


@pytest.mark.skipif(sys.platform != "win32", reason="case-insensitive paths")
def test_case_insensitive_comparison_on_windows(tmp_path: Path) -> None:
    home = _home(tmp_path)
    _folder(home / "plugins", "PETASOS")
    assert protection_status(home).status == "hook_can_load"


def test_symlinked_copy_compares_equal(tmp_path: Path) -> None:
    home = _home(tmp_path)
    (home / "plugins").mkdir()
    real = _folder(tmp_path / "elsewhere", "copy")
    try:
        os.symlink(real, home / "plugins" / "petasos", target_is_directory=True)
    except OSError:
        pytest.skip("symlinks need privileges on this host")
    assert protection_status(home).status == "hook_can_load"


# ── is_hermes_home ───────────────────────────────────────────────────────────


def _binding(home: Path, tier: paths_mod.Tier = "hermes_home") -> HermesConfigResolution:
    return HermesConfigResolution(path=home / "config.yaml", tier=tier)


@pytest.mark.parametrize("marker", ["plugins", "profiles", "sessions", "memories"])
def test_folder_markers(tmp_path: Path, marker: str) -> None:
    home = _home(tmp_path, None)
    (home / marker).mkdir()
    assert is_hermes_home(_binding(home)) is True


@pytest.mark.parametrize("marker", ["gateway_state.json", "logs/agent.log"])
def test_file_markers(tmp_path: Path, marker: str) -> None:
    home = _home(tmp_path, None)
    (home / marker).parent.mkdir(parents=True, exist_ok=True)
    (home / marker).write_text("", encoding="utf-8")
    assert is_hermes_home(_binding(home)) is True


def test_config_and_spool_are_not_markers(tmp_path: Path) -> None:
    home = _home(tmp_path)
    (home / "petasos-enforcement.jsonl").write_text("", encoding="utf-8")
    assert is_hermes_home(_binding(home)) is False


def test_regression_pet236_never_run_profile_is_a_hermes_home(tmp_path: Path) -> None:
    home = _home(tmp_path, None)
    for name in ("memories", "sessions", "skills", "skins", "logs", "plans", "workspace"):
        (home / name).mkdir()
    assert is_hermes_home(_binding(home)) is True


def test_hermes_home_binding_ignores_a_marked_root(tmp_path: Path) -> None:
    home = _home(tmp_path)
    root = paths_mod.hermes_root()
    (root / "plugins").mkdir(parents=True)
    assert is_hermes_home(_binding(home)) is False
    assert is_hermes_home(_binding(home, "profile")) is True


# ── next_steps ───────────────────────────────────────────────────────────────


def _root_with_source() -> Path:
    root = paths_mod.hermes_root()
    _folder(root / "plugins", "petasos")
    return root


@pytest.fixture(params=[True, False], ids=["powershell", "posix"])
def shell(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> bool:
    windows: bool = request.param
    monkeypatch.setattr(pf, "_is_windows", lambda: windows)
    return windows


def test_no_copy_prints_the_exact_commands(tmp_path: Path, shell: bool) -> None:
    root = _root_with_source()
    home = root / "profiles" / "ops"
    home.mkdir(parents=True)
    steps = protection_status(home, profile="ops").next_steps
    source, target = root / "plugins" / "petasos", home / "plugins" / "petasos"
    if shell:
        assert f"New-Item -ItemType Directory -Force '{home / 'plugins'}'" in steps
        assert f"Copy-Item -Recurse -LiteralPath '{source}' -Destination '{target}'" in steps
    else:
        assert f"mkdir -p '{home / 'plugins'}'" in steps
        assert f"cp -R '{source}' '{target}'" in steps
    assert "hermes -p ops plugins enable petasos" in steps
    assert "Restart the gateway." in steps
    assert steps.endswith(pf._INTENDED_SENTENCE)


def test_not_enabled_prints_enable_and_closing_sentence(tmp_path: Path) -> None:
    home = _home(tmp_path, "")
    _folder(home / "plugins", "petasos")
    steps = protection_status(home, profile="ops").next_steps
    assert "hermes -p ops plugins enable petasos" in steps
    assert steps.endswith(pf._INTENDED_SENTENCE)


def test_shadowed_creates_its_destination_first(tmp_path: Path, shell: bool) -> None:
    home = _home(tmp_path)
    _folder(home / "plugins", "petasos")
    bak = _folder(home / "plugins", "petasos.bak-1")
    steps = protection_status(home, profile="gibson").next_steps
    backups = home / "petasos-plugin-backups"
    lines = steps.splitlines()
    assert str(backups) in lines[0]
    assert ("New-Item" if shell else "mkdir") in lines[0]
    assert str(bak) in lines[1]
    if shell:  # a claimant named petasos[1] must not act as a wildcard pattern
        assert lines[1].startswith(f"Move-Item -LiteralPath '{bak}' -Destination ")
    assert "rename one first" in steps
    assert "still loads" in steps
    assert pf._INTENDED_SENTENCE not in steps


def test_unknown_names_what_to_read(tmp_path: Path) -> None:
    home = _home(tmp_path, "{not yaml: [")
    found = protection_status(home)
    assert str(home / "config.yaml") in found.next_steps
    assert "re-run" in found.next_steps
    assert pf._INTENDED_SENTENCE not in found.next_steps


def test_hook_can_load_has_no_steps(tmp_path: Path) -> None:
    home = _home(tmp_path)
    _folder(home / "plugins", "petasos")
    assert protection_status(home).next_steps == ""


@pytest.mark.parametrize("profile", ["default", None])
def test_root_home_names_default_under_an_active_profile(profile: str | None) -> None:
    root = paths_mod.hermes_root()
    root.mkdir(parents=True)
    (root / "active_profile").write_text("gibson\n", encoding="utf-8")
    _folder(root / "plugins", "petasos")
    steps = protection_status(root, profile=profile).next_steps
    assert "hermes -p default plugins enable petasos" in steps


def test_custom_home_gets_no_hermes_command_and_no_root_copy(tmp_path: Path) -> None:
    _root_with_source()
    home = _home(tmp_path, "")
    steps = protection_status(home).next_steps
    assert "hermes " not in steps
    assert str(paths_mod.hermes_root()) not in steps
    assert str(home / "config.yaml") in steps
    assert str(home / "plugins") in steps
    assert steps.endswith(pf._INTENDED_SENTENCE)


def test_path_with_a_space_and_dollar_is_quoted_literally(tmp_path: Path, shell: bool) -> None:
    home = _home(tmp_path / "a b$c")
    _folder(home / "plugins", "petasos")
    _folder(home / "plugins", "petasos.bak-1")
    steps = protection_status(home, profile="ops").next_steps
    assert f"'{home / 'petasos-plugin-backups'}'" in steps


def test_profile_name_with_a_space_is_quoted(shell: bool) -> None:
    home = paths_mod.hermes_root() / "profiles" / "my ops"
    home.mkdir(parents=True)
    (home / "plugins").mkdir()
    _root_with_source()
    steps = protection_status(home, profile="my ops").next_steps
    assert "hermes -p 'my ops' plugins enable petasos" in steps


def test_embedded_quote_is_escaped_per_shell(shell: bool) -> None:
    assert pf._quote("it's") == ("'it''s'" if shell else "'it'\\''s'")


def test_existing_partial_target_says_remove_or_move(tmp_path: Path) -> None:
    _root_with_source()
    home = paths_mod.hermes_root() / "profiles" / "ops"
    _folder(home / "plugins", "petasos", init=False)
    steps = protection_status(home, profile="ops").next_steps
    assert "Remove" in steps
    assert "petasos-plugin-backups" in steps
    assert "renamed folder would still claim" in steps


def test_home_with_no_plugins_folder_still_gets_the_mkdir(tmp_path: Path) -> None:
    _root_with_source()
    home = paths_mod.hermes_root() / "profiles" / "ops"
    home.mkdir(parents=True)
    assert str(home / "plugins") in protection_status(home, profile="ops").next_steps


def test_no_source_folder_says_install_in_root_first() -> None:
    home = paths_mod.hermes_root() / "profiles" / "ops"
    home.mkdir(parents=True)
    steps = protection_status(home, profile="ops").next_steps
    assert "Install Petasos in the root first" in steps


def test_source_equal_to_target_says_install_in_root_first() -> None:
    root = paths_mod.hermes_root()
    _folder(root / "plugins", "petasos", init=False)
    steps = protection_status(root, profile="default").next_steps
    assert "Install Petasos in the root first" in steps
