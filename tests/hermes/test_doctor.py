"""Doctor reports what is protecting a profile, and what to do when it is not."""

from __future__ import annotations

import base64
import json
from typing import TYPE_CHECKING, Any

from petasos.cli import main
from petasos.enforce.types import ApprovalGrant
from petasos.hermes.doctor import examine, hermes_view, render_json, render_text
from tests.hermes.conftest import enabled_config, healthy_home, write_config, write_plugin

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _run(
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
    capsys: pytest.CaptureFixture[str],
) -> tuple[int, str]:
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    code = main(argv)
    return code, capsys.readouterr().out


def test_healthy_install_is_protected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Defaults, with the plugin on, are protected. The report says so in plain words."""
    home = healthy_home(tmp_path, monkeypatch)
    code, out = _run(monkeypatch, ["doctor", "--home", str(home)], capsys)

    assert code == 0
    assert "Protected. Petasos is checking tool calls for this agent." in out
    assert "Petasos 0.4.0" in out
    assert "Python" in out
    assert "Hermes 0.23.1 is new enough" in out
    assert "plugin files are in place" in out
    assert "plugin description matches" in out
    assert "set to run the Petasos plugin" in out
    assert "Hermes accepted the plugin files" in out
    assert "Job: general" in out
    assert "Strictness: balanced" in out
    assert "session secret is not set" in out
    assert "hash key is not set" in out
    assert "built-in text checks are running" in out
    assert "not installed" in out
    assert "turned off" in out
    assert "Hermes would ask a person" in out
    assert "Dangerous tool calls wait for a person to confirm them." in out
    assert "the general job" in out
    assert "Open. The agent can change guardrails with a fresh approval." in out
    assert "30 minutes" in out
    assert "places an agent could change" in out
    assert "Paths protected today" not in out
    assert "No injection scanner is active" not in out
    assert "pip install" not in out
    assert "petasos scanner add prompt_guard" in out
    assert "The Petasos tab should appear" in out


def test_fresh_home_is_not_protected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A home with nothing installed names the missing plugin and the install command."""
    code, out = _run(monkeypatch, ["doctor", "--home", str(tmp_path)], capsys)

    assert code == 2
    assert "Not protected. Petasos is not checking tool calls" in out
    assert "Hermes is not installed in this Python" in out
    assert "same Python Hermes uses" in out
    assert "plugin is not installed" in out
    assert f"petasos hermes install --home {tmp_path}" in out
    assert "not turned on in Hermes" in out


def test_two_problems_are_both_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A switched-off plugin and a bad job are both named, with a next step for each."""
    write_plugin(tmp_path)
    write_config(
        tmp_path,
        "plugins:\n"
        "  enabled:\n"
        "    - petasos\n"
        "  disabled:\n"
        "    - petasos\n"
        "  entries:\n"
        "    petasos:\n"
        "      settings:\n"
        "        role: nope\n",
    )
    code, out = _run(monkeypatch, ["doctor", "--home", str(tmp_path)], capsys)

    assert code == 2
    assert "Not protected." in out
    assert "switched-off list" in out
    assert "hermes plugins enable petasos" in out
    assert "nope" in out
    assert "falls back to its usual settings" in out
    assert "general, coding, research, support, or admin" in out


def test_manifest_mismatch_is_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A description that still names Petasos, but is not this version, is a warning."""
    home = healthy_home(tmp_path, monkeypatch)
    path = home / "plugins" / "petasos" / "plugin.yaml"
    edited = path.read_text(encoding="utf-8").replace("balanced", "balanced ")
    path.write_text(edited, encoding="utf-8")
    code, out = _run(monkeypatch, ["doctor", "--home", str(home)], capsys)

    assert code == 1
    assert "Protected, with warnings." in out
    assert "does not match this version" in out
    assert f"petasos hermes install --home {home}" in out


def test_damaged_manifest_is_not_protected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A description Hermes cannot use is named as the reason the plugin may not load."""
    home = healthy_home(tmp_path, monkeypatch)
    manifest = home / "plugins" / "petasos" / "plugin.yaml"
    manifest.write_text("this is not a plugin\n", encoding="utf-8")
    code, out = _run(monkeypatch, ["doctor", "--home", str(home)], capsys)

    assert code == 2
    assert "damaged" in out
    assert f"petasos hermes install --home {home}" in out


def test_foreign_init_is_not_petasos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A directory whose Python file is not ours is not treated as installed."""
    target = tmp_path / "plugins" / "petasos"
    target.mkdir(parents=True)
    (target / "__init__.py").write_text("MemoryProvider = 1\n", encoding="utf-8")
    (target / "plugin.yaml").write_text(
        "name: petasos\nversion: '0'\ndescription: x\n",
        encoding="utf-8",
    )
    write_config(tmp_path, enabled_config())
    _code, out = _run(monkeypatch, ["doctor", "--home", str(tmp_path)], capsys)

    assert "would make Hermes skip it" in out or "not Petasos" in out


def test_protection_off_is_not_protected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A valid switch set to off means tool calls are not checked."""
    home = healthy_home(tmp_path, monkeypatch)
    write_config(home, enabled_config().replace("enabled: true", "enabled: false", 1))
    code, out = _run(monkeypatch, ["doctor", "--home", str(home)], capsys)

    assert code == 2
    assert "Protection is off." in out
    assert "not checked until protection is turned on" in out
    assert "Turn protection on" in out


def test_old_section_points_at_migrate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An old petasos: section is named, and the next step is the migrate command."""
    home = healthy_home(tmp_path, monkeypatch)
    text = enabled_config() + "petasos:\n  enabled: true\n  profile_name: general\n"
    write_config(home, text)
    code, out = _run(monkeypatch, ["doctor", "--home", str(home)], capsys)

    assert code == 1
    assert "old petasos: section" in out
    assert "does not read it" in out
    assert f"petasos config migrate --home {home}" in out


def test_old_section_alone_is_not_the_settings_in_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """With only the old section, the report says those settings are not in use."""
    write_plugin(tmp_path)
    write_config(
        tmp_path,
        "plugins:\n  enabled:\n    - petasos\npetasos:\n  profile_name: admin\n",
    )
    from tests.hermes.conftest import patch_hermes_ok

    patch_hermes_ok(monkeypatch)
    _code, out = _run(monkeypatch, ["doctor", "--home", str(tmp_path)], capsys)

    assert "does not read it" in out
    assert "Job: general" in out
    assert "petasos config migrate" in out


def test_env_placeholder_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A ${NAME} in a setting is named, because Hermes would replace it on read."""
    home = healthy_home(tmp_path, monkeypatch)
    write_config(
        home,
        "plugins:\n"
        "  enabled:\n"
        "    - petasos\n"
        "  entries:\n"
        "    petasos:\n"
        "      settings:\n"
        "        role: ${ROLE_NAME}\n",
    )
    code, out = _run(monkeypatch, ["doctor", "--home", str(home)], capsys)

    assert code == 1
    assert "${ROLE_NAME}" in out
    assert "plain text" in out or "Write the value itself" in out


def test_secret_values_are_never_printed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Set secrets are reported as set. The values do not appear."""
    home = healthy_home(tmp_path, monkeypatch)
    session = base64.b64encode(b"session-secret-value").decode("ascii")
    (home / ".env").write_text(
        f"PETASOS_SESSION_SECRET={session}\nPETASOS_HASH_KEY=hash-secret-value\n",
        encoding="utf-8",
    )
    code, out = _run(monkeypatch, ["doctor", "--json", "--home", str(home)], capsys)

    assert code == 0
    assert "session-secret-value" not in out
    assert session not in out
    assert "hash-secret-value" not in out
    payload = json.loads(out)
    assert payload["verdict"] == "protected"
    assert payload["exit_code"] == 0
    wanted = {"session_secret", "hash_key"}
    secrets = {row["id"]: row for row in payload["checks"] if row["id"] in wanted}
    assert secrets["session_secret"]["summary"].startswith("The session secret is set")
    assert secrets["hash_key"]["summary"].startswith("The hash key is set")


def test_unreadable_session_secret_is_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A session secret that is not base64 is named, without printing the value."""
    home = healthy_home(tmp_path, monkeypatch)
    (home / ".env").write_text("PETASOS_SESSION_SECRET=not base64!\n", encoding="utf-8")
    code, out = _run(monkeypatch, ["doctor", "--home", str(home)], capsys)

    assert code == 1
    assert "cannot read it" in out
    assert "not base64!" not in out
    assert "base64" in out


def test_hash_key_is_required_when_hiding_uses_a_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Hashed hiding without the key names the missing environment variable."""
    home = healthy_home(tmp_path, monkeypatch)
    write_config(
        home,
        "plugins:\n"
        "  enabled:\n"
        "    - petasos\n"
        "  entries:\n"
        "    petasos:\n"
        "      settings:\n"
        "        enabled: true\n"
        "        role: general\n"
        "        level: balanced\n"
        "        overrides:\n"
        "          anonymization:\n"
        "            mode: hash\n",
    )
    code, out = _run(monkeypatch, ["doctor", "--home", str(home)], capsys)

    assert code == 1
    assert "hash key is not set" in out
    assert "PETASOS_HASH_KEY" in out
    assert str(home / ".env") in out


def test_unavailable_scanner_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A check that was asked for and cannot run is named, with what to do."""
    home = healthy_home(tmp_path, monkeypatch)
    write_config(
        home,
        "plugins:\n"
        "  enabled:\n"
        "    - petasos\n"
        "  entries:\n"
        "    petasos:\n"
        "      settings:\n"
        "        enabled: true\n"
        "        role: general\n"
        "        level: balanced\n"
        "        overrides:\n"
        "          scanners:\n"
        "            semgrep:\n"
        '              enabled: "on"\n',
    )
    code, out = _run(monkeypatch, ["doctor", "--home", str(home)], capsys)

    assert code == 1
    assert "Semgrep cannot run inside Hermes yet." in out
    assert "It is set to Required, so tool calls that change things wait for a person." in out
    assert "petasos config set scanners.semgrep.enabled off" in out
    assert "semgrep.host_lifecycle_unavailable" not in out
    assert "lifecycle" not in out.casefold()


def test_approve_without_a_person_is_called_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A job that asks for confirmation says so when Hermes would not ask."""
    home = healthy_home(tmp_path, monkeypatch)
    write_config(home, enabled_config(role="coding"))
    monkeypatch.setattr(
        "petasos.hermes.host.approval_grant",
        lambda: ApprovalGrant(mode_off=True),
    )
    code, out = _run(monkeypatch, ["doctor", "--home", str(home)], capsys)

    assert code == 1
    assert "confirm" in out
    assert "without asking" in out
    assert "approvals are turned off" in out


def test_approve_asks_when_hermes_would_ask(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """When Hermes would ask, the report says a missing person means a refusal."""
    home = healthy_home(tmp_path, monkeypatch)
    write_config(home, enabled_config(role="coding"))
    monkeypatch.setattr(
        "petasos.hermes.host.approval_grant",
        lambda: ApprovalGrant(),
    )
    code, out = _run(monkeypatch, ["doctor", "--home", str(home)], capsys)

    assert code == 0
    assert "would ask a person" in out
    assert "refuses the call" in out


def test_missing_hermes_names_this_python(tmp_path: Path) -> None:
    """With Hermes absent, the Hermes line says so and names this interpreter."""
    view = hermes_view()
    assert view.status == "warn"
    assert "not installed" in view.summary
    report = examine(tmp_path, home_reason="the home you named with --home")
    text = render_text(report, verbose=False, color=False)
    assert "not installed in this Python" in text
    assert "Install Petasos into the same Python Hermes uses" in text


def test_old_hermes_fails_the_version_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Hermes older than the plugin's minimum is a failure, with the upgrade step."""

    class _Manifest:
        @staticmethod
        def running_hermes_version() -> str:
            return "0.18.0"

    real = __import__("petasos.hermes.host", fromlist=["load_module"]).load_module

    def load(name: str) -> Any:
        if name == "hermes_cli.plugins_manifest":
            return _Manifest()
        return real(name)

    monkeypatch.setattr("petasos.hermes.host.load_module", load)
    view = hermes_view()
    assert view.status == "fail"
    assert "0.18.0" in view.summary
    assert "0.23.1" in view.next_step


def test_plugin_load_failure_is_quoted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """When Hermes rejects the plugin, the report quotes Hermes and is not protected."""
    write_plugin(tmp_path)
    write_config(tmp_path, enabled_config())

    def view() -> Any:
        from petasos.hermes.doctor import HermesView

        return HermesView(
            status="ok",
            summary="Hermes 0.23.1 is new enough for this plugin.",
            version="0.23.1",
        )

    class _Report:
        ok = False
        failures = ["plugin.yaml missing required field(s): description"]

    class _Validate:
        @staticmethod
        def validate_plugin_dir(path: Path) -> _Report:
            del path
            return _Report()

    real = __import__("petasos.hermes.host", fromlist=["load_module"]).load_module

    def load(name: str) -> Any:
        if name == "hermes_cli.plugin_validate":
            return _Validate()
        return real(name)

    monkeypatch.setattr("petasos.hermes.doctor.hermes_view", view)
    monkeypatch.setattr("petasos.hermes.host.load_module", load)
    code, out = _run(monkeypatch, ["doctor", "--home", str(tmp_path)], capsys)

    assert code == 2
    assert "did not accept the plugin" in out
    assert "missing required field(s): description" in out
    assert "petasos hermes install" in out


def test_yaml_reader_missing_is_explained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A config that cannot be parsed because no YAML reader is present says how to run."""
    write_plugin(tmp_path)
    write_config(tmp_path, enabled_config())
    monkeypatch.setattr("petasos.hermes.host.load_module", lambda _name: None)
    code, out = _run(monkeypatch, ["doctor", "--home", str(tmp_path)], capsys)

    assert code == 2
    assert "cannot read Hermes's config file" in out
    assert "same Python Hermes uses" in out


def test_json_and_verbose_carry_the_detail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """JSON has the verdict and the checks. Verbose names a path and where a value came from."""
    home = healthy_home(tmp_path, monkeypatch)
    write_config(home, enabled_config(role="coding"))
    code, out = _run(monkeypatch, ["doctor", "--json", "--home", str(home)], capsys)
    payload = json.loads(out)
    assert code == 0
    assert payload["verdict"] == "protected"
    assert payload["home"] == str(home)
    assert payload["home_reason"] == "the home you named with --home"
    assert any(row["id"] == "guardrail" for row in payload["checks"])
    assert "plugins/petasos" in " ".join(payload["protected_paths"])
    origins = {row["path"]: row["origin"] for row in payload["detail"]["resolved"]}
    assert origins["tools.dangerous_posture"] == "role"

    code, verbose = _run(monkeypatch, ["doctor", "--verbose", "--home", str(home)], capsys)
    assert code == 0
    assert "tools.dangerous_posture" in verbose
    assert "role" in verbose
    assert "python_path" in verbose


def test_home_selection_says_which_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """With no flags, the home is HERMES_HOME when that is set, and the report says so."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    code, out = _run(monkeypatch, ["doctor"], capsys)
    assert code == 2
    assert "HERMES_HOME environment variable" in out
    assert str(tmp_path) in out


def test_profile_flag_selects_the_profile_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """--profile names a directory under profiles/, and a path escape is rejected."""
    code, out = _run(
        monkeypatch,
        ["doctor", "--home", str(tmp_path), "--profile", "work"],
        capsys,
    )
    assert code == 2
    assert str(tmp_path / "profiles" / "work") in out
    assert "profile work" in out

    code = main(["doctor", "--home", str(tmp_path), "--profile", "../escape"])
    assert code == 2
    assert "not a single directory name" in capsys.readouterr().err


def test_text_and_json_share_one_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every sentence in the JSON object is the sentence the text prints."""
    home = healthy_home(tmp_path, monkeypatch)
    report = examine(home, home_reason="the home you named with --home")
    text = render_text(report, verbose=False, color=False)
    verbose = render_text(report, verbose=True, color=False)
    payload = json.loads(render_json(report))
    assert payload["summary"] in text
    assert payload["paths_summary"] in text
    for check in payload["checks"]:
        assert check["summary"] in text
    for suggestion in payload["suggestions"]:
        assert suggestion in text
    assert payload["protected_paths"]
    assert "Paths protected today" not in text
    assert "Paths protected today" in verbose
    for path in payload["protected_paths"]:
        assert path in verbose


def test_a_redundant_override_is_not_called_custom(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An override that matches the role and level is not described as custom."""
    home = healthy_home(tmp_path, monkeypatch)
    write_config(
        home,
        "plugins:\n"
        "  enabled:\n"
        "    - petasos\n"
        "  entries:\n"
        "    petasos:\n"
        "      settings:\n"
        "        enabled: true\n"
        "        role: general\n"
        "        level: balanced\n"
        "        overrides:\n"
        "          fail_mode: degraded\n",
    )
    code, out = _run(monkeypatch, ["doctor", "--home", str(home)], capsys)

    assert code == 0
    assert "custom setting" not in out
    payload = json.loads(_run(monkeypatch, ["doctor", "--json", "--home", str(home)], capsys)[1])
    origins = {row["path"]: row["origin"] for row in payload["detail"]["resolved"]}
    assert origins["fail_mode"] == "override"


def test_a_real_override_is_a_sentence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A value the role would not have chosen is named, and the line starts with a capital."""
    home = healthy_home(tmp_path, monkeypatch)
    write_config(home, enabled_config(role="coding"))
    monkeypatch.setattr(
        "petasos.hermes.host.approval_grant",
        lambda: ApprovalGrant(),
    )
    code, out = _run(monkeypatch, ["doctor", "--home", str(home)], capsys)

    assert code == 0
    assert "Dangerous tool calls wait for a person to confirm them." in out
    assert "\ndangerous tool calls" not in out
    assert "the coding job" in out


def test_two_result_rewriters_are_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """When security-guidance is also on, the report says Petasos's note is dropped."""
    home = healthy_home(tmp_path, monkeypatch)
    text = enabled_config().replace(
        "    - petasos\n",
        "    - security-guidance\n    - petasos\n",
        1,
    )
    write_config(home, text)
    code, out = _run(monkeypatch, ["doctor", "--home", str(home)], capsys)

    assert code == 1
    assert "security-guidance" in out
    assert "first" in out
    assert "Tool calls are still checked" in out
    assert "hermes plugins disable security-guidance" in out


def test_missing_dashboard_files_mean_no_tab(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A current plugin without the dashboard files warns that the tab will not appear."""
    home = healthy_home(tmp_path, monkeypatch)
    dashboard = home / "plugins" / "petasos" / "dashboard"
    for path in dashboard.iterdir():
        path.unlink()
    code, out = _run(monkeypatch, ["doctor", "--home", str(home)], capsys)

    assert code == 1
    assert "tab will not appear" in out
    assert "manifest.json" in out


def test_colour_is_not_the_only_mark(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Colour wraps the mark. The mark text is still there when colour is on."""
    home = healthy_home(tmp_path, monkeypatch)
    report = examine(home, home_reason="the home you named with --home")
    coloured = render_text(report, verbose=False, color=True)
    plain = render_text(report, verbose=False, color=False)
    assert "[ok]" in coloured
    assert "\033[32m[ok]\033[0m" in coloured
    assert "\033[" not in plain


def test_a_required_scanner_that_is_not_installed_says_so_and_how_to_add_it() -> None:
    """Pin a required scanner that is not installed says so and how to add it."""
    from petasos.config.layers import resolve
    from petasos.hermes.doctor_advice import scanner_report

    resolved = resolve({"overrides": {"scanners": {"prompt_guard": {"enabled": "on"}}}})

    checks, _suggestions, rows = scanner_report(resolved)
    text = " ".join(f"{check.summary} {check.meaning} {check.next_step}" for check in checks)
    row = next(item for item in rows if item["id"] == "prompt_guard")

    assert "PromptGuard is turned on but not installed." in text
    assert "installed but cannot be used" not in text
    assert "petasos scanner add prompt_guard" in text
    assert row["reason"] == "PromptGuard is not installed."
    assert "pip install" not in str(row["reason"]) + str(row["fix"])
    assert row["fix"] == "petasos scanner add prompt_guard"


def test_a_scanner_whose_model_is_missing_keeps_its_own_reason() -> None:
    """Pin a scanner whose model is missing keeps its own reason."""
    from petasos.hermes.doctor_advice import _scanner_row
    from petasos.scanners.registry import ScannerStatus

    status = ScannerStatus(
        id="prompt_guard",
        state="unavailable",
        reason="PromptGuard model unavailable. Accept the model terms, then download it.",
        extra="prompt-guard",
        detects=frozenset({"injection"}),
        label="PromptGuard",
        missing=True,
    )

    row = _scanner_row(status, {"holds": True, "title": "t", "sentence": "s"})

    assert row["reason"] == status.reason
