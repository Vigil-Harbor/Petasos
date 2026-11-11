"""Run authored Python examples and command help without a live Hermes install.

Package installs and the real-Hermes install route need external dependencies;
those remain operator actions. Command examples are checked through their
actual CLI help; scalar-setting examples also execute with an in-memory host
writer. Read-only doctor and install previews also run against an empty
temporary home, with Hermes imports explicitly unavailable.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PAGES = (
    ROOT / "README.md",
    ROOT / "CLAUDE.md",
    *sorted((ROOT / "docs" / "usage").glob("*.md")),
    *sorted((ROOT / "docs" / "deployment").glob("*.md")),
    ROOT / "docs" / "security-hardening-checklist.md",
)
FENCES = re.compile(r"^```(\w+)\n(.*?)^```", re.MULTILINE | re.DOTALL)
PYTHON = [
    pytest.param(path, index, body, id=f"{path.relative_to(ROOT)}:{index}")
    for path in PAGES
    for index, (language, body) in enumerate(FENCES.findall(path.read_text(encoding="utf-8")))
    if language == "python"
]
COMMANDS = sorted(
    {
        snippet
        for path in PAGES
        for snippet in re.findall(r"`([^`\n]+)`", path.read_text(encoding="utf-8"))
        if snippet.startswith("petasos ")
    }
    | {
        line
        for path in PAGES
        for language, body in FENCES.findall(path.read_text(encoding="utf-8"))
        if language == "bash"
        for line in body.splitlines()
        if line.startswith("petasos ")
    }
)


def _environment(tmp_path: Path) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("HERMES_")}
    env.update(
        HOME=str(tmp_path),
        USERPROFILE=str(tmp_path),
        LOCALAPPDATA=str(tmp_path / "AppData" / "Local"),
        HERMES_HOME=str(tmp_path / "hermes"),
        HERMES_MANAGED_DIR=str(tmp_path / "managed"),
        HF_HOME=str(tmp_path / "models"),
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        PYTHONPATH=str(ROOT),
    )
    return env


def _run(code: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=_environment(tmp_path),
        capture_output=True,
        text=True,
        timeout=45,
    )


@pytest.mark.parametrize(("path", "index", "body"), PYTHON)
def test_python_example(path: Path, index: int, body: str, tmp_path: Path) -> None:
    completed = _run(body, tmp_path)
    assert completed.returncode == 0, f"{path}:{index}\n{completed.stdout}\n{completed.stderr}"


@pytest.mark.parametrize("command", COMMANDS)
def test_command_example_help(command: str, tmp_path: Path) -> None:
    args = shlex.split(command)[1:]
    if "--help" not in args:
        args.append("--help")
    completed = _run(
        f"from petasos.hermes.commands import main\nraise SystemExit(main({args!r}))\n",
        tmp_path,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.startswith("usage: petasos "), completed.stdout


@pytest.mark.parametrize("args", [["doctor", "--json"], ["hermes", "install", "--dry-run"]])
def test_read_only_commands_on_empty_home(args: list[str], tmp_path: Path) -> None:
    # No ambient Hermes reader may inspect a machine-level location or launch
    # a plugin. This is the missing-host path, not a substitute host validator.
    completed = _run(
        "import sys\n"
        "sys.modules['hermes_cli'] = None\n"
        "sys.modules['hermes_constants'] = None\n"
        "from petasos.hermes.commands import main\n"
        f"raise SystemExit(main({args!r}))\n",
        tmp_path,
    )
    if args[0] == "doctor":
        assert completed.returncode == 2, completed.stderr
        report = json.loads(completed.stdout)
        assert report["verdict"] == "not_protected"
        assert Path(report["home"]) == tmp_path / "hermes"
        assert any(check["next_step"] for check in report["checks"])
    else:
        assert completed.returncode == 0, completed.stderr
        assert "Dry run. Nothing was written." in completed.stdout
    assert not (tmp_path / "hermes").exists()
    assert not (tmp_path / "managed").exists()


@pytest.mark.parametrize(
    "command",
    [
        command
        for command in COMMANDS
        if shlex.split(command)[1:3] == ["config", "set"] and "--help" not in command
    ],
)
def test_setting_example_runs_through_validation(
    command: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from petasos import resolve
    from petasos.hermes.commands import main

    plugin = tmp_path / "plugins" / "petasos"
    plugin.mkdir(parents=True)
    (plugin / "plugin.yaml").write_text("name: petasos\n", encoding="utf-8")
    saved: list[dict[str, object]] = []

    def remember(values: dict[str, object], *, plugin_dir: Path) -> None:
        assert plugin_dir == plugin
        saved.append(values)

    # Only the host boundary is replaced. The documented command, argument
    # coercion, config resolution and change reporting all execute normally.
    monkeypatch.setattr("petasos.hermes.config_set.pinned_settings", lambda: None)
    monkeypatch.setattr("petasos.hermes.config_set.write_settings", remember)
    assert main([*shlex.split(command)[1:], "--home", str(tmp_path)]) == 0
    assert len(saved) == 1
    resolve(saved[0])
