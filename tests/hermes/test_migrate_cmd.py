"""Migrate shows the new settings, and writes them only through Hermes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from petasos.cli import main
from tests.hermes.conftest import write_plugin

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_show_prints_settings_and_hides_the_secret(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The readable form, the paste block, and the dropped secret are shown. The value is not."""
    secret = "super-secret-value"
    (tmp_path / "config.yaml").write_text(
        "petasos:\n"
        "  enabled: true\n"
        "  profile_name: code_generation\n"
        f"  session_secret: {secret}\n"
        "  host_id: old-host\n",
        encoding="utf-8",
    )
    code, out, _err = _run(["config", "migrate", "--home", str(tmp_path)], capsys)

    assert code == 0
    assert "Job: coding" in out
    assert "role: coding" in out
    assert "level: balanced" in out
    assert "Nothing was written" in out
    assert "session_secret" in out
    assert "PETASOS_SESSION_SECRET" in out
    assert secret not in out
    assert "host_id" in out
    assert (tmp_path / "config.yaml").read_text(encoding="utf-8").count(secret) == 1


def test_write_is_refused_when_something_was_not_copied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An unknown setting blocks --write until --proceed. The old section stays."""
    (tmp_path / "config.yaml").write_text(
        "petasos:\n  enabled: true\n  not_a_field: 1\n",
        encoding="utf-8",
    )
    calls: list[dict[str, Any]] = []

    def remember(values: dict[str, Any], *, plugin_dir: Path) -> None:
        calls.append({"values": values, "plugin_dir": plugin_dir})

    monkeypatch.setattr("petasos.hermes.migrate_cmd.write_settings", remember)
    code, out, _err = _run(["config", "migrate", "--home", str(tmp_path), "--write"], capsys)

    assert code == 2
    assert calls == []
    assert "not_a_field" in out
    assert "Nothing was written" in out
    assert "--proceed" in out
    assert "not_a_field" in (tmp_path / "config.yaml").read_text(encoding="utf-8")


def test_proceed_stores_through_the_writer_and_leaves_the_section(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """--write --proceed calls Hermes's writer and tells the user how to remove the old section."""
    write_plugin(tmp_path)
    (tmp_path / "config.yaml").write_text(
        "petasos:\n  enabled: true\n  not_a_field: 1\n  profile_name: research\n",
        encoding="utf-8",
    )
    calls: list[dict[str, Any]] = []

    def remember(values: dict[str, Any], *, plugin_dir: Path) -> None:
        calls.append({"values": dict(values), "plugin_dir": plugin_dir})

    monkeypatch.setattr("petasos.hermes.migrate_cmd.write_settings", remember)
    code, out, _err = _run(
        ["config", "migrate", "--home", str(tmp_path), "--write", "--proceed"],
        capsys,
    )

    assert code == 0
    assert calls[0]["values"]["role"] == "research"
    assert calls[0]["plugin_dir"] == tmp_path / "plugins" / "petasos"
    assert "Hermes stored the new settings" in out
    assert "delete the petasos: block" in out
    assert "not_a_field" in (tmp_path / "config.yaml").read_text(encoding="utf-8")


def test_write_refuses_to_store_required_semgrep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An old semgrep_enabled true would become Required, so --write stores nothing."""
    write_plugin(tmp_path)
    original = "petasos:\n  enabled: true\n  semgrep_enabled: true\n"
    (tmp_path / "config.yaml").write_text(original, encoding="utf-8")
    calls: list[dict[str, Any]] = []

    def remember(values: dict[str, Any], *, plugin_dir: Path) -> None:
        calls.append(dict(values))

    monkeypatch.setattr("petasos.hermes.migrate_cmd.write_settings", remember)
    code, out, _err = _run(["config", "migrate", "--home", str(tmp_path), "--write"], capsys)

    assert code == 2
    assert calls == []
    assert "cannot be set to Required" in out
    assert "Nothing was written" in out
    assert (tmp_path / "config.yaml").read_text(encoding="utf-8") == original


def test_clean_write_without_hermes_does_not_edit_the_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A clean migration still refuses to write the config itself when Hermes is absent."""
    write_plugin(tmp_path)
    original = "petasos:\n  enabled: true\n  profile_name: general\n"
    (tmp_path / "config.yaml").write_text(original, encoding="utf-8")
    code, out, _err = _run(["config", "migrate", "--home", str(tmp_path), "--write"], capsys)

    assert code == 2
    assert "does not edit the config file itself" in out
    assert (tmp_path / "config.yaml").read_text(encoding="utf-8") == original


def test_missing_plugin_tells_the_user_to_install_first(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Storing settings needs the plugin directory Hermes reads the description from."""
    (tmp_path / "config.yaml").write_text(
        "petasos:\n  enabled: true\n",
        encoding="utf-8",
    )
    code, out, _err = _run(["config", "migrate", "--home", str(tmp_path), "--write"], capsys)

    assert code == 2
    assert "petasos hermes install" in out
    assert "petasos:" in (tmp_path / "config.yaml").read_text(encoding="utf-8")


def test_no_section_is_a_quiet_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A profile with no old section has nothing to convert."""
    (tmp_path / "config.yaml").write_text("plugins:\n  enabled: []\n", encoding="utf-8")
    code, out, _err = _run(["config", "migrate", "--home", str(tmp_path)], capsys)

    assert code == 0
    assert "No old petasos: section" in out


def test_yaml_reader_missing_is_explained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without a YAML reader the command says so and does not pretend the section was empty."""
    (tmp_path / "config.yaml").write_text("petasos:\n  enabled: true\n", encoding="utf-8")
    monkeypatch.setattr("petasos.hermes.host.load_module", lambda _name: None)
    code, out, _err = _run(["config", "migrate", "--home", str(tmp_path)], capsys)

    assert code == 2
    assert "no YAML reader" in out


def test_usage_without_a_command_is_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    """The bare command, and a group with no action, explain what to type."""
    assert main([]) == 2
    assert "doctor" in capsys.readouterr().err
    assert main(["hermes"]) == 2
    assert "hermes install" in capsys.readouterr().err
    assert main(["config"]) == 2
    assert "config set" in capsys.readouterr().err
