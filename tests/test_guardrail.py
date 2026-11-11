"""Recognition of a guardrail change: paths, commands, disguises, and misses."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from petasos.hermes.guardrail import hermes_surface
from petasos.session.guardrail import (
    GuardrailHit,
    GuardrailSurface,
    normalize_path_text,
    recognize,
)

if TYPE_CHECKING:
    from pathlib import Path


def _home(tmp_path: Path) -> tuple[Path, Path, GuardrailSurface, dict[str, str]]:
    home = tmp_path / "hermes"
    (home / "plugins" / "petasos").mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text("plugins: {}\n", encoding="utf-8")
    (home / ".env").write_text("PETASOS_SESSION_SECRET=x\n", encoding="utf-8")
    (home / "active_profile").write_text("default\n", encoding="utf-8")
    (home / "petasos-enforcement.jsonl").write_text("", encoding="utf-8")
    package = tmp_path / "pkg" / "petasos"
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    paths = [
        home / "config.yaml",
        home / ".env",
        home / "plugins" / "petasos",
        home / "active_profile",
        home / "petasos-enforcement.jsonl",
    ]
    surface = hermes_surface(str(path) for path in paths)
    env = {"HERMES_HOME": str(home), "HOME": str(tmp_path)}
    return home, package, surface, env


def _hit(tmp_path: Path, tool: str, params: dict[str, object]) -> GuardrailHit | None:
    home, package, surface, env = _home(tmp_path)
    return recognize(
        tool,
        params,
        protected=(str(home / "config.yaml"),),
        surface=surface,
        package=(str(package),),
        environ=env,
        cwd=str(tmp_path),
    )


@pytest.mark.parametrize(
    ("tool", "params", "kind"),
    [
        ("write_file", {"path": "config.yaml", "content": "x"}, "settings"),
        ("patch", {"path": ".env", "content": "x"}, "settings"),
        ("write_file", {"path": "plugins/petasos/plugin.yaml"}, "plugin"),
        ("write_file", {"path": "active_profile"}, "plugin"),
        ("write_file", {"path": "petasos-enforcement.jsonl"}, "record"),
        ("delete_file", {"path": "plugins/petasos/__init__.py"}, "plugin"),
    ],
)
def test_protected_paths_are_changes(
    tmp_path: Path, tool: str, params: dict[str, str], kind: str
) -> None:
    home, package, surface, env = _home(tmp_path)
    if tool == "write_file" and params["path"] == "plugins/petasos/plugin.yaml":
        params = {"path": str(home / "plugins" / "petasos" / "plugin.yaml")}
    elif "path" in params and not os.path.isabs(str(params["path"])):
        params = {"path": str(home / str(params["path"]))}
    hit = recognize(
        tool,
        params,
        surface=surface,
        package=(str(package),),
        environ=env,
        cwd=str(tmp_path),
    )
    assert hit is not None
    assert hit.kind == kind


def test_package_file_write_is_a_package_change(tmp_path: Path) -> None:
    _home_path, package, surface, env = _home(tmp_path)
    hit = recognize(
        "write_file",
        {"path": str(package / "__init__.py"), "content": "x"},
        surface=surface,
        package=(str(package),),
        environ=env,
        cwd=str(tmp_path),
    )
    assert hit is not None
    assert hit.kind == "package"


def test_reading_a_protected_file_is_not_a_change(tmp_path: Path) -> None:
    home, *_rest = _home(tmp_path)
    assert _hit(tmp_path, "read_file", {"path": str(home / "config.yaml")}) is None
    assert _hit(tmp_path, "terminal", {"command": f"cat {home / 'config.yaml'}"}) is None
    assert _hit(tmp_path, "terminal", {"command": "hermes plugins list"}) is None
    assert _hit(tmp_path, "terminal", {"command": "hermes config get plugins.enabled"}) is None
    assert _hit(tmp_path, "terminal", {"command": "petasos doctor"}) is None
    assert _hit(tmp_path, "terminal", {"command": "hermes petasos doctor"}) is None


def test_words_written_to_another_file_are_not_a_change(tmp_path: Path) -> None:
    notes = tmp_path / "notes.txt"
    hit = _hit(
        tmp_path,
        "write_file",
        {"path": str(notes), "content": "hermes plugins disable petasos"},
    )
    assert hit is None


@pytest.mark.parametrize(
    "command",
    [
        "hermes plugins disable petasos",
        "hermes plugins enable petasos",
        "hermes plugins remove petasos",
        "hermes plugins disable --all",
        "hermes plugins disable -a",
        'hermes plugins disable "petasos"',
        "hermes 'plugins' disable petasos",
        "FOO=1 hermes plugins disable petasos",
        "sh -c 'hermes plugins disable petasos'",
        "bash -lc 'hermes plugins disable petasos'",
        "sudo hermes plugins disable petasos",
        "echo ok && hermes plugins disable petasos",
        "hermes plugins disable petasos; echo done",
        "hermes plugins disable petasos | tee /tmp/log",
        "command hermes plugins disable petasos",
        "/usr/local/bin/hermes plugins disable petasos",
    ],
)
def test_plugin_commands_and_cheap_disguises(tmp_path: Path, command: str) -> None:
    hit = _hit(tmp_path, "terminal", {"command": command})
    assert hit is not None
    assert hit.kind == "plugin"


@pytest.mark.parametrize(
    ("command", "kind"),
    [
        ("hermes --safe-mode", "plugin"),
        ("hermes chat --safe-mode", "plugin"),
        ("HERMES_SAFE_MODE=1 hermes plugins list", "plugin"),
        ("export HERMES_SAFE_MODE=true", "plugin"),
        ("hermes gateway restart", "plugin"),
        ("hermes config set plugins.enabled '[]'", "plugin"),
        ("hermes config set plugins.disabled '[petasos]'", "plugin"),
        ("hermes config set plugins.hook_callback_timeout 0", "plugin"),
        ("hermes config set plugins.entries.petasos.settings.enabled false", "settings"),
        ("hermes config unset plugins.entries.petasos.settings.role", "settings"),
        ("petasos config migrate", "settings"),
        ("petasos config set role general", "settings"),
        ("petasos scanner add presidio", "settings"),
        ("petasos scanner remove presidio", "settings"),
        ("petasos hermes install", "plugin"),
        ("petasos hermes pin", "plugin"),
        ("petasos hermes unpin", "plugin"),
        ("hermes petasos config migrate", "settings"),
        ("hermes petasos scanner remove presidio", "settings"),
        ("hermes petasos install", "plugin"),
        ("pip uninstall -y petasos", "package"),
        ("pip install petasos", "package"),
        ("uv pip uninstall petasos", "package"),
        ("uv pip install --upgrade petasos", "package"),
        ("python -m pip uninstall petasos", "package"),
        ("python -c 'import os; os.system(\"hermes plugins disable petasos\")'", "plugin"),
    ],
)
def test_the_listed_commands(tmp_path: Path, command: str, kind: str) -> None:
    tool = "execute_code" if command.startswith("python -c") else "terminal"
    hit = _hit(tmp_path, tool, {"command": command, "code": command})
    assert hit is not None and hit.kind == kind


def test_shell_path_disguises(tmp_path: Path) -> None:
    home, package, surface, env = _home(tmp_path)
    config = str(home / "config.yaml")

    def hit(command: str, cwd: str | None = None) -> GuardrailHit | None:
        return recognize(
            "terminal",
            {"command": command},
            surface=surface,
            package=(str(package),),
            environ=env,
            cwd=cwd or str(tmp_path),
        )

    def kind_of(command: str, cwd: str | None = None) -> str | None:
        found = hit(command, cwd)
        return None if found is None else found.kind

    assert kind_of(f"rm {config}") == "settings"
    assert kind_of(f"rm -rf {config}") == "settings"
    assert kind_of(f"chmod 644 {config}") == "settings"
    assert kind_of(f"mv {config} /tmp/away") == "settings"
    assert kind_of(f"echo x > {config}") == "settings"
    assert kind_of("rm config.yaml", cwd=str(home)) == "settings"
    assert kind_of("rm ~/hermes/config.yaml") == "settings"
    assert kind_of('rm "$HERMES_HOME/config.yaml"') == "settings"
    assert kind_of(f"cat {config}") is None
    assert kind_of(f"cp {config} {tmp_path / 'copy.yaml'}") is None


def test_a_different_plugin_and_a_mention_do_not_match(tmp_path: Path) -> None:
    assert _hit(tmp_path, "terminal", {"command": "hermes plugins disable other"}) is None
    assert _hit(tmp_path, "terminal", {"command": "echo hermes plugins disable petasos"}) is None
    quiet = "HERMES_SAFE_MODE=0 hermes plugins list"
    assert _hit(tmp_path, "terminal", {"command": quiet}) is None
    assert (
        _hit(
            tmp_path,
            "execute_code",
            {"code": 'print("hermes plugins disable petasos")'},
        )
        is None
    )


def test_normalize_path_text_matches_the_guard() -> None:
    text = "C:\\tmp\\petasos\\config.yaml"
    assert normalize_path_text(text) == normalize_path_text(text.replace("\\", "/"))
