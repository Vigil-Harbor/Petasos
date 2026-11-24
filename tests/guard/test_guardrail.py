"""Recognition of a guardrail change: paths, commands, disguises, and misses."""

from __future__ import annotations

import ntpath
import os
import shlex
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from petasos.guard import guardrail, shell_parse
from petasos.guard.guardrail import recognize
from petasos.guard.paths import normalize_path_text
from petasos.guard.shell_parse import _parse
from petasos.guard.surface import CommandRule
from petasos.hermes.guardrail import hermes_surface

if TYPE_CHECKING:
    from pathlib import Path

    from petasos.guard.surface import GuardrailHit, GuardrailSurface


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
    surface = hermes_surface((str(path) for path in paths), roots=(str(home),))
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
    assert (
        _hit(tmp_path, "terminal", {"command": f"cat {(home / 'config.yaml').as_posix()}"}) is None
    )
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
        "hermes plugins remove petasos",
        "hermes plugins rm petasos",
        "hermes plugins uninstall petasos",
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
        ("petasos hermes pin --write --home /tmp/profile", "plugin"),
        ("petasos hermes unpin --write --accept-profile-changes", "plugin"),
        ("hermes petasos pin --write", "plugin"),
        ("hermes petasos unpin --write --accept-profile-changes", "plugin"),
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
    config = (home / "config.yaml").as_posix()

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
    assert kind_of(f"cp {config} {(tmp_path / 'copy.yaml').as_posix()}") is None


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


def test_sed_in_place_edits_the_config(tmp_path: Path) -> None:
    home, *_rest = _home(tmp_path)
    command = f"sed -i 's/enabled: true/enabled: false/' {(home / 'config.yaml').as_posix()}"
    hit = _hit(tmp_path, "terminal", {"command": command})
    assert hit is not None and hit.kind == "settings"


def test_execute_code_open_writes_the_config(tmp_path: Path) -> None:
    home, *_rest = _home(tmp_path)
    code = f"open('{(home / 'config.yaml').as_posix()}','w').write('x')"
    hit = _hit(tmp_path, "execute_code", {"code": code})
    assert hit is not None and hit.kind == "settings"


def test_execute_code_subprocess_list_disables_the_plugin(tmp_path: Path) -> None:
    code = "import subprocess; subprocess.run(['hermes','plugins','disable','petasos'])"
    hit = _hit(tmp_path, "execute_code", {"code": code})
    assert hit is not None and hit.kind == "plugin"


def test_execute_code_os_system_disables_the_plugin(tmp_path: Path) -> None:
    code = "import os; os.system('hermes plugins disable petasos')"
    hit = _hit(tmp_path, "execute_code", {"code": code})
    assert hit is not None and hit.kind == "plugin"


def test_backslash_before_a_letter_still_names_hermes(tmp_path: Path) -> None:
    hit = _hit(tmp_path, "terminal", {"command": r"her\mes plugins disable petasos"})
    assert hit is not None and hit.kind == "plugin"


def test_quotes_joined_inside_a_word_still_name_the_command(tmp_path: Path) -> None:
    for command in ('her""mes plugins disable petasos', "h'e'rmes plu\\gins disable petasos"):
        hit = _hit(tmp_path, "terminal", {"command": command})
        assert hit is not None and hit.kind == "plugin", command


def test_plugins_update_and_install_replace_the_plugin(tmp_path: Path) -> None:
    update = _hit(tmp_path, "terminal", {"command": "hermes plugins update petasos"})
    install = _hit(
        tmp_path,
        "terminal",
        {"command": "hermes plugins install file:///tmp/other#petasos"},
    )
    assert update is not None and update.kind == "plugin"
    assert install is not None and install.kind == "plugin"


def test_perl_in_place_edits_the_config(tmp_path: Path) -> None:
    home, *_rest = _home(tmp_path)
    command = f"perl -i -pe 's/a/b/' {(home / 'config.yaml').as_posix()}"
    hit = _hit(tmp_path, "terminal", {"command": command})
    assert hit is not None and hit.kind == "settings"


def test_append_redirect_writes_the_config(tmp_path: Path) -> None:
    home, *_rest = _home(tmp_path)
    hit = _hit(tmp_path, "terminal", {"command": f"echo x >> {(home / 'config.yaml').as_posix()}"})
    assert hit is not None and hit.kind == "settings"


def test_tee_append_writes_the_config(tmp_path: Path) -> None:
    home, *_rest = _home(tmp_path)
    hit = _hit(
        tmp_path, "terminal", {"command": f"echo x | tee -a {(home / 'config.yaml').as_posix()}"}
    )
    assert hit is not None and hit.kind == "settings"


def test_install_mode_writes_the_config(tmp_path: Path) -> None:
    home, *_rest = _home(tmp_path)
    command = f"install -m 644 /tmp/other.yaml {(home / 'config.yaml').as_posix()}"
    hit = _hit(tmp_path, "terminal", {"command": command})
    assert hit is not None and hit.kind == "settings"


def test_symlink_force_replaces_the_config(tmp_path: Path) -> None:
    home, *_rest = _home(tmp_path)
    hit = _hit(
        tmp_path, "terminal", {"command": f"ln -sf /tmp/other {(home / 'config.yaml').as_posix()}"}
    )
    assert hit is not None and hit.kind == "settings"


def test_moving_the_plugin_directory_is_a_change(tmp_path: Path) -> None:
    home, *_rest = _home(tmp_path)
    hit = _hit(
        tmp_path,
        "terminal",
        {"command": f"mv {(home / 'plugins' / 'petasos').as_posix()} /tmp/away"},
    )
    assert hit is not None and hit.kind == "plugin"


def test_truncate_and_chmod_recursive_change_a_protected_path(tmp_path: Path) -> None:
    home, *_rest = _home(tmp_path)
    truncated = _hit(
        tmp_path, "terminal", {"command": f"truncate -s 0 {(home / 'config.yaml').as_posix()}"}
    )
    chmod = _hit(
        tmp_path,
        "terminal",
        {"command": f"chmod -R a+r {(home / 'plugins' / 'petasos').as_posix()}"},
    )
    assert truncated is not None and truncated.kind == "settings"
    assert chmod is not None and chmod.kind == "plugin"


def test_a_symlink_and_a_parent_directory_still_name_the_config(tmp_path: Path) -> None:
    home, package, surface, env = _home(tmp_path)
    config = home / "config.yaml"
    link = tmp_path / "via-link.yaml"
    try:
        link.symlink_to(config)
    except OSError:
        pytest.skip("symlink not permitted")
    nested = home / "nested"
    nested.mkdir()

    def kind_of(command: str) -> str | None:
        found = recognize(
            "terminal",
            {"command": command},
            surface=surface,
            package=(str(package),),
            environ=env,
            cwd=str(tmp_path),
        )
        return None if found is None else found.kind

    assert kind_of(f"rm {link}") == "settings"
    assert kind_of(f"rm {nested / '..' / 'config.yaml'}") == "settings"


def test_code_names_the_config_through_home_and_the_environment(tmp_path: Path) -> None:
    cases = (
        'open(os.path.expanduser("~/hermes/config.yaml"), "w").write("x")',
        'open(Path.home() / "hermes" / "config.yaml", "w").write("x")',
        'open(os.environ["HERMES_HOME"] + "/config.yaml", "w").write("x")',
        'open(os.path.join(os.getenv("HERMES_HOME"), "config.yaml"), "w").write("x")',
    )
    for code in cases:
        hit = _hit(tmp_path, "execute_code", {"code": code})
        assert hit is not None and hit.kind == "settings", code


def test_a_comment_that_names_the_config_is_not_a_change(tmp_path: Path) -> None:
    home, *_rest = _home(tmp_path)
    code = f"# see {(home / 'config.yaml').as_posix()}\nprint('ok')\n"
    assert _hit(tmp_path, "execute_code", {"code": code}) is None


def test_powershell_get_content_reads_and_set_content_writes(tmp_path: Path) -> None:
    home, *_rest = _home(tmp_path)
    config = (home / "config.yaml").as_posix()
    assert _hit(tmp_path, "terminal", {"command": f"powershell Get-Content {config}"}) is None
    written = _hit(tmp_path, "terminal", {"command": f"powershell Set-Content {config} x"})
    assert written is not None and written.kind == "settings"


def test_echo_and_printf_do_not_act_on_a_path_argument(tmp_path: Path) -> None:
    home, *_rest = _home(tmp_path)
    config = (home / "config.yaml").as_posix()
    assert _hit(tmp_path, "terminal", {"command": f"echo see {config}"}) is None
    assert _hit(tmp_path, "terminal", {"command": f"printf '%s' {config}"}) is None
    redirected = _hit(tmp_path, "terminal", {"command": f"echo see > {config}"})
    assert redirected is not None and redirected.kind == "settings"


def test_help_on_a_hermes_or_petasos_command_is_not_a_change(tmp_path: Path) -> None:
    assert _hit(tmp_path, "terminal", {"command": "hermes plugins update --help"}) is None
    assert _hit(tmp_path, "terminal", {"command": "hermes plugins update -h"}) is None
    assert _hit(tmp_path, "terminal", {"command": "petasos config set --help"}) is None


def test_opening_the_config_to_read_it_is_not_a_change(tmp_path: Path) -> None:
    home, *_rest = _home(tmp_path)
    config = home / "config.yaml"
    reads = (
        f"open('{config}').read()",
        f"open('{config}', 'r').read()",
        f"open('{config}', 'rb')",
        f"open('{config}', 'rt')",
        f"with open('{config}') as handle: handle.read()",
        f"Path('{config}').read_text()",
        f"Path('{config}').read_bytes()",
        f"pathlib.Path('{config}').exists()",
        f"Path('{config}').is_file()",
        f"Path('{config}').stat()",
    )
    for code in reads:
        assert _hit(tmp_path, "execute_code", {"code": code}) is None, code


def test_other_uses_of_the_config_in_code_are_changes(tmp_path: Path) -> None:
    home, *_rest = _home(tmp_path)
    config = home / "config.yaml"
    writes = (
        f"open('{config}', 'w').write('x')",
        f"open('{config}', 'a').write('x')",
        f"open('{config}', mode).write('x')",
        f"with open('{config}', 'w') as handle: handle.write('x')",
        f"target = '{config}'",
        f"print('{config}')",
        f"Path('{config}').write_text('x')",
        f"open('{config}').read(); open('{config}', 'w').write('x')",
    )
    for code in writes:
        hit = _hit(tmp_path, "execute_code", {"code": code})
        assert hit is not None and hit.kind == "settings", code


def test_a_path_assembled_in_a_variable_is_not_seen(tmp_path: Path) -> None:
    """The pieces are not written next to the lookup. That stays a gap."""
    code = 'root = os.environ["HERMES_HOME"]\nopen(root + "/config.yaml", "w").write("x")'
    assert _hit(tmp_path, "execute_code", {"code": code}) is None


@pytest.mark.parametrize(
    ("command", "kind"),
    [
        ("hermes plugins install petasos", "plugin"),
        ("hermes plugins install --force file:///tmp/other#petasos", "plugin"),
        ("hermes plugins update", "plugin"),
        ("hermes plugins update --yes", "plugin"),
        ("hermes plugins rm petasos", "plugin"),
        ("hermes plugins uninstall petasos", "plugin"),
        ("hermes plugins adopt petasos", "plugin"),
        ("hermes plugins trust-update-url petasos", "plugin"),
        ("hermes plugins auto-update on", "plugin"),
        ("hermes plugins autoupdate off", "plugin"),
        ("hermes plugins pack install /tmp/pack.yaml", "plugin"),
        ("hermes gateway start", "plugin"),
        ("hermes gateway run --replace", "plugin"),
        ("hermes update", "plugin"),
        ("hermes update --yes", "plugin"),
        ("hermes profile use other", "plugin"),
        ("hermes profile delete other", "plugin"),
        ("hermes profile rename old new", "plugin"),
        ("hermes profile update other --force-config", "settings"),
        ("hermes config edit", "settings"),
        ("hermes config migrate", "settings"),
        ("hermes config set plugins.auto_apply true", "plugin"),
        ("hermes --ignore-user-config", "plugin"),
        ("hermes --profile other chat", "plugin"),
        ("hermes -p other plugins list", "plugin"),
        ("HERMES_HOME=/tmp/other hermes plugins list", "plugin"),
        ("HERMES_MANAGED_DIR=/tmp/other hermes", "plugin"),
        ("export HERMES_HOME=/tmp/other", "plugin"),
        ("export HERMES_MANAGED_DIR=/tmp/other", "plugin"),
        ("export HERMES_IGNORE_USER_CONFIG=1", "plugin"),
        ("HERMES_IGNORE_USER_CONFIG=1 hermes chat", "plugin"),
    ],
)
def test_each_enumerated_hermes_command(tmp_path: Path, command: str, kind: str) -> None:
    hit = _hit(tmp_path, "terminal", {"command": command})
    assert hit is not None and hit.kind == kind, command


@pytest.mark.parametrize(
    "command",
    [
        "hermes plugins list",
        "hermes config get plugins.enabled",
        "petasos doctor",
        "hermes plugins disable kanban",
        "hermes plugins enable petasos",
        "/opt/hermes/bin/hermes plugins enable petasos",
        "hermes plugins enable kanban",
        "pip install requests",
        "hermes config set display.theme teal",
        "git commit -m 'docs: hermes gateway restart steps'",
        "hermes plugins auto-update",
        "hermes plugins update kanban",
        "hermes plugins install other",
        "hermes plugins adopt kanban",
        "hermes plugins check-updates",
        "hermes plugins pack show /tmp/pack.yaml",
        "hermes profile list",
        "hermes profile create extra",
        "hermes profile update other",
        "hermes config show",
        "hermes gateway status",
        "hermes gateway stop",
        "hermes gateway run",
        "hermes update --check",
        "hermes update --plan",
        "HERMES_HOME=/tmp/other echo hi",
    ],
)
def test_reads_and_other_plugins_are_not_changes(tmp_path: Path, command: str) -> None:
    assert _hit(tmp_path, "terminal", {"command": command}) is None, command


def test_a_note_that_mentions_the_config_is_not_a_change(tmp_path: Path) -> None:
    home, *_rest = _home(tmp_path)
    quoted = f"echo 'see {(home / 'config.yaml').as_posix()}' > /tmp/notes"
    assert _hit(tmp_path, "terminal", {"command": quoted}) is None
    assert (
        _hit(
            tmp_path, "terminal", {"command": f"grep enabled {(home / 'config.yaml').as_posix()}"}
        )
        is None
    )
    copied = f"cp {(home / 'config.yaml').as_posix()} /tmp/backup.yaml"
    assert _hit(tmp_path, "terminal", {"command": copied}) is None
    assert _hit(tmp_path, "read_file", {"path": str(home / "config.yaml")}) is None
    assert (
        _hit(tmp_path, "terminal", {"command": f"cat {(home / 'config.yaml').as_posix()}"}) is None
    )


def _at(tmp_path: Path, command: str, cwd: Path | None = None) -> GuardrailHit | None:
    """Judge a terminal command. ``{home}`` and ``{config}`` are filled in."""
    home, package, surface, env = _home(tmp_path)
    text = command.replace("{home}", home.as_posix()).replace(
        "{config}", (home / "config.yaml").as_posix()
    )
    return recognize(
        "terminal",
        {"command": text},
        protected=(str(home / "config.yaml"),),
        surface=surface,
        package=(str(package),),
        environ=env,
        cwd=str(tmp_path if cwd is None else cwd),
    )


@pytest.mark.parametrize(
    "command",
    [
        "petasos doctor",
        "petasos --version",
        "python -m petasos doctor",
        "hermes petasos doctor",
        "pip show petasos",
    ],
)
def test_the_command_word_and_a_verb_are_not_paths(tmp_path: Path, command: str) -> None:
    """In a source checkout the working directory holds a ``petasos`` directory."""
    checkout = tmp_path / "pkg"
    assert _at(tmp_path, command, cwd=checkout) is None
    removed = _at(tmp_path, "rm -rf petasos", cwd=checkout)
    assert removed is not None and removed.kind == "package"


@pytest.mark.parametrize(
    "command",
    [
        "true & hermes plugins disable petasos",
        "(hermes plugins disable petasos)",
        "{ hermes plugins disable petasos; }",
        "if true; then hermes plugins disable petasos; fi",
        "for i in 1; do hermes plugins disable petasos; done",
        "! hermes plugins disable petasos",
        "timeout 5 hermes plugins disable petasos",
        "timeout -s KILL 5 hermes plugins disable petasos",
        "exec hermes plugins disable petasos",
        "env -u FOO hermes plugins disable petasos",
        'eval "hermes plugins disable petasos"',
        "echo $(hermes plugins disable petasos)",
        "echo `hermes plugins disable petasos`",
        "timeout 5 sh -c 'hermes plugins disable petasos'",
        "hermes --profile=other chat",
    ],
)
def test_shell_structure_does_not_hide_the_command(tmp_path: Path, command: str) -> None:
    hit = _at(tmp_path, command)
    assert hit is not None and hit.kind == "plugin", command


@pytest.mark.parametrize(
    "command",
    [
        "> {config}",
        "hermes --help > {config}",
        "true &> {config}",
        "true & rm {config}",
        "(rm {config})",
    ],
)
def test_a_redirect_or_a_background_command_still_writes(tmp_path: Path, command: str) -> None:
    hit = _at(tmp_path, command)
    assert hit is not None and hit.kind == "settings", command


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf {home}/plugins",
        "rm -rf {home}",
        "mv {home} /tmp/gone",
        "chmod -R 000 {home}/plugins",
        "find {home} -name '*.yaml' -delete",
        "rm -rf {home}/plugins/*",
        "rm {home}/config.*",
        "rm {home}/{config.yaml,notes.txt}",
        "cd {home}/plugins && rm -rf petasos",
        "cp /tmp/evil/config.yaml {home}/",
        "mv /tmp/evil/config.yaml {home}",
        "cp -r /tmp/evil/ {home}/",
    ],
)
def test_a_directory_that_holds_a_protected_path_is_a_change(tmp_path: Path, command: str) -> None:
    assert _at(tmp_path, command) is not None, command


@pytest.mark.parametrize(
    "command",
    [
        "ls {home}",
        "cd {home} && ls",
        "cd {home} && hermes plugins list",
        "du -sh {home}",
        "cp -r {home} /tmp/backup",
        "cp notes.txt {home}/",
        "rm {home}/*.txt",
        "rm -rf /",
        "rm -rf ~",
        "git add .",
        "timeout 5 cat {config}",
        "if grep -q petasos {config}; then echo yes; fi",
        "! grep -q petasos {config}",
        "sudo cat {config}",
    ],
)
def test_reads_and_directories_above_the_home_are_not_changes(
    tmp_path: Path, command: str
) -> None:
    assert _at(tmp_path, command) is None, command


def test_a_tool_that_moves_a_directory_is_a_change(tmp_path: Path) -> None:
    home, _package, _surface, _env = _home(tmp_path)
    moved = _hit(tmp_path, "move_file", {"source": str(home / "plugins"), "destination": "/tmp/x"})
    assert moved is not None and moved.kind == "plugin"
    assert _hit(tmp_path, "write_file", {"path": str(home / "notes.md"), "content": "x"}) is None


@pytest.mark.parametrize(
    "command",
    [
        "pip install petasos==0.1.0",
        "pip install -U 'petasos[all]'",
        "pip install 'petasos<0.5'",
        "pip install git+https://example.com/x/petasos.git@main",
        "pip install ./dist/petasos-0.1.0-py3-none-any.whl",
        "uv pip install petasos==0.1",
        "uv add petasos==0.1",
        "uv remove petasos",
        "uv tool uninstall petasos",
    ],
)
def test_a_version_or_a_source_still_names_the_package(tmp_path: Path, command: str) -> None:
    hit = _at(tmp_path, command)
    assert hit is not None and hit.kind == "package", command


def test_another_package_is_not_the_package(tmp_path: Path) -> None:
    for command in ("pip install requests==2.0", "pip install petasosx", "uv add httpx"):
        assert _at(tmp_path, command) is None, command


@pytest.mark.parametrize(
    "command",
    [
        "python3 - <<'EOF'\nopen('{config}', 'w').write('x')\nEOF",
        "node - <<EOF\nrequire('fs').rmSync('{config}')\nEOF",
        """node -e "require('fs').writeFileSync('{config}', '')\"""",
        """perl -e 'unlink "{config}"'""",
        "sed -n 'w {config}' /tmp/evil.yaml",
    ],
)
def test_program_text_given_to_an_interpreter_is_read(tmp_path: Path, command: str) -> None:
    hit = _at(tmp_path, command)
    assert hit is not None and hit.kind == "settings", command


def test_a_here_document_that_only_reads_is_not_a_change(tmp_path: Path) -> None:
    assert _at(tmp_path, "python3 - <<'EOF'\nprint(open('{config}').read())\nEOF") is None


@pytest.mark.parametrize(
    "command",
    [
        "hermes config set command_allowlist '[]'",
        "hermes config unset command_allowlist",
        "hermes config set command_allowlist.0 replacement",
        "hermes config unset command_allowlist.0",
        "hermes config set approvals.timeout 120",
        "hermes config set approvals.mode off",
        "hermes config unset approvals",
        "hermes config set --force command_allowlist '[ordinary]'",
        'hermes config set command_allowlist "$(printf hidden)"',
        "hermes approvals suggest --apply 1,2",
        "hermes approvals suggest --apply=1",
        "hermes approvals suggest --ap=1",
        "hermes approvals suggest --a 1",
        "hermes setup --reset --non-interactive",
        "hermes setup --res",
        "hermes import /tmp/backup.zip --force",
        "hermes profile install /tmp/profile --force",
        "hermes profile install /tmp/profile --f",
        "hermes profile update demo --for",
    ],
)
def test_permanent_approval_list_changes(tmp_path: Path, command: str) -> None:
    hit = _hit(tmp_path, "terminal", {"command": command})
    assert hit is not None
    assert hit.kind == "settings"


@pytest.mark.parametrize(
    "command",
    [
        "hermes config get command_allowlist",
        "hermes config get approvals.mode",
        "hermes approvals suggest",
        "hermes approvals suggest --json --days 1",
        "hermes approvals test -- echo ok",
        "hermes backup --quick",
        "hermes setup model",
        "hermes profile install /tmp/profile",
    ],
)
def test_permanent_approval_list_reads(tmp_path: Path, command: str) -> None:
    assert _hit(tmp_path, "terminal", {"command": command}) is None


@pytest.mark.parametrize(
    "command",
    [
        "hermes --json config set command_allowlist '[]'",
        "ai.hermes config set command_allowlist '[]'",
        "/Applications/Hermes.app/Contents/MacOS/ai.hermes config unset command_allowlist",
        "hermes.exe config set command_allowlist '[]'",
        r"C:\Tools\hermes.exe config set command_allowlist '[]'",
        "python -u -m hermes_cli.main config set command_allowlist x",
        "python3 -X dev -B -m hermes_cli config unset command_allowlist",
        "python -um hermes_cli.main config set command_allowlist x",
        "python -m hermes_cli.main config set command_allowlist '[]'",
        "python3.11 -m hermes_cli config unset command_allowlist",
        "/opt/venv/bin/python -mhermes_cli.main setup --reset",
        "H=hermes; $H config set command_allowlist '[]'",
        "$H config set approvals.mode off",
        "$H config unset approvals",
        "alias h=hermes; h config set command_allowlist '[]'",
    ],
)
def test_hermes_invocation_spellings_change_settings(tmp_path: Path, command: str) -> None:
    hit = _hit(tmp_path, "terminal", {"command": command})
    assert hit is not None and hit.kind == "settings"


@pytest.mark.parametrize(
    ("command", "kind"),
    [
        ("python -m hermes_cli.main plugins disable petasos", "plugin"),
        ("ai.hermes import x.zip", "settings"),
        ("hermes --json approvals suggest --apply", "settings"),
    ],
)
def test_other_rules_use_hermes_invocation_forms(tmp_path: Path, command: str, kind: str) -> None:
    hit = _hit(tmp_path, "terminal", {"command": command})
    assert hit is not None and hit.kind == kind


@pytest.mark.parametrize("option", ["--json", "-x", "--flag=value"])
@pytest.mark.parametrize(
    ("command", "kind"),
    [
        ("config unset command_allowlist", "settings"),
        ("plugins disable petasos", "plugin"),
        ("import x.zip", "settings"),
        ("approvals suggest --apply", "settings"),
        ("setup --reset", "settings"),
        ("petasos scanner remove presidio", "settings"),
    ],
)
@pytest.mark.parametrize("launcher", ["hermes", "ai.hermes", "python -m hermes_cli.main"])
def test_hermes_invocations_reach_command_rules(
    tmp_path: Path, launcher: str, option: str, command: str, kind: str
) -> None:
    hit = _hit(tmp_path, "terminal", {"command": f"{launcher} {option} {command}"})
    assert hit is not None and hit.kind == kind


@pytest.mark.parametrize(
    "option",
    [
        "--profile",
        "-p",
        "--config",
        "--model",
        "-m",
        "--provider",
        "--reasoning",
        "--toolsets",
        "-t",
        "--resume",
        "-r",
        "--skills",
        "-s",
        "--oneshot",
        "-z",
        "--usage-file",
        "--in",
        "--cpu-profile",
    ],
)
def test_hermes_global_options_consume_their_values(tmp_path: Path, option: str) -> None:
    command = f"hermes {option} work config unset command_allowlist"
    assert _hit(tmp_path, "terminal", {"command": command}) is not None
    if option not in {"--profile", "-p"}:
        # A value that happens to be a verb does not become the subcommand.
        read = f"hermes {option} config set command_allowlist x"
        assert _hit(tmp_path, "terminal", {"command": read}) is None


@pytest.mark.parametrize(
    "option",
    [
        "-p work",
        "--profile work",
        "--profile=work",
        "-m some-model",
        "--mod some-model",
        "--reas high",
        "-wm some-model",
        "-c",
        "-c session",
        "--continue session",
        "--cont session",
        "-c --yolo",
        "--yolo --tui -w",
        "-s a -s b",
        "--",
    ],
)
@pytest.mark.parametrize("program", ["hermes", "h", "$H", "$HERMES_BIN"])
def test_hermes_global_option_forms_before_the_verb(
    tmp_path: Path, program: str, option: str
) -> None:
    """Hermes's parser reads these as options, so the verb still follows.

    For ``hermes`` itself a profile option is also a change of its own.
    """
    command = f"{program} {option} config set command_allowlist x"
    assert _hit(tmp_path, "terminal", {"command": command}) is not None, command


@pytest.mark.parametrize("option", ["-p work", "--profile work", "--profile=work"])
def test_a_profile_after_the_verb_is_set_aside(tmp_path: Path, option: str) -> None:
    """Hermes removes the profile option wherever it is before reading the rest."""
    command = f"h config set {option} command_allowlist x"
    hit = _hit(tmp_path, "terminal", {"command": command})
    assert hit is not None and hit.kind == "settings"


@pytest.mark.parametrize("option", ["--model", "-m"])
def test_an_unknown_program_option_value_is_not_its_verb(tmp_path: Path, option: str) -> None:
    # An abbreviated or clustered form (``--mod``, ``-wm``) is still matched:
    # the reading that gives only exact options a value is kept as well.
    command = f"h {option} config set command_allowlist x"
    assert _hit(tmp_path, "terminal", {"command": command}) is None


@pytest.mark.parametrize(
    "key",
    [
        "command_allowlist",
        "command_allowlist.0",
        "approvals",
        "approvals.timeout",
        "plugins.entries.petasos",
        "plugins.entries.petasos.settings.enabled",
        "plugins.enabled",
        "plugins.disabled",
        "plugins.hook_callback_timeout",
        "plugins.auto_apply",
        "plugins",
        "plugins.entries",
        "plugins.review_note",
        "plugins.entries.petasos_other",
    ],
)
@pytest.mark.parametrize("verb", ["set", "unset"])
def test_unknown_program_only_guards_listed_config_keys(
    tmp_path: Path, key: str, verb: str
) -> None:
    hit = _hit(tmp_path, "terminal", {"command": f"h config {verb} --force {key} x"})
    assert hit is not None


@pytest.mark.parametrize(
    "command",
    [
        "hermes --json config show",
        "python -m hermes_cli.main config get command_allowlist",
        "python -m other_cli config set command_allowlist x",
        "python -mother_cli config set command_allowlist x",
        "ai.hermes approvals suggest",
        "git config set core.editor vim",
        "git config set command_allowlist x",
        "/usr/bin/git config unset plugins.enabled",
        "npm config set command_allowlist x",
        "h plugins disable petasos",
        "h import x.zip",
        "h setup --reset",
        "h approvals suggest --apply",
        "h config edit",
        "h config set model x",
        "h config set command_allowlist_backup x",
        "h config set plugins_backup x",
        "h config set approvals_backup x",
        "h config get command_allowlist",
    ],
)
def test_invocation_recognition_leaves_reads_and_unrelated_programs(
    tmp_path: Path, command: str
) -> None:
    assert _hit(tmp_path, "terminal", {"command": command}) is None


@pytest.mark.parametrize(
    "command",
    [
        "echo 'hermes plugins disable petasos' > /tmp/notes.txt",
        "grep -r 'hermes config set command_allowlist' docs/",
        "printf %s 'hermes config set command_allowlist x'",
        "echo 'then run: $H -p work config set approvals.mode off'",
        "ssh host 'hermes config unset petasos'",
        "echo \"sh -c 'hermes config edit'\"",
        # In quoted text any program word before ``config set`` and a guarded
        # key counts, as in the 0.5.0 guard: the program is not resolved there.
        "echo 'git config set command_allowlist x'",
    ],
)
def test_a_configuration_write_inside_quoted_text_is_a_change(
    tmp_path: Path, command: str
) -> None:
    """Quoted text may be run later, so a configuration write in it is a change.

    This is conservative: text kept only as data is reported too.
    """
    hit = _hit(tmp_path, "terminal", {"command": command})
    assert hit is not None and hit.kind in {"settings", "plugin"}, command


@pytest.mark.parametrize(
    "command",
    [
        "git commit -m 'docs: hermes gateway restart steps'",
        "echo 'hermes config get command_allowlist'",
        "echo 'hermes config set display.theme teal'",
        "echo 'hermes plugins list'",
    ],
)
def test_quoted_text_without_a_configuration_write_is_not_a_change(
    tmp_path: Path, command: str
) -> None:
    assert _hit(tmp_path, "terminal", {"command": command}) is None


def test_quoted_text_nested_within_the_limit_is_read(tmp_path: Path) -> None:
    # Each level quotes the one inside it, so the text grows quickly.
    text = "hermes config set command_allowlist x"
    for _ in range(5):
        text = "echo " + shlex.quote(text)
    hit = _hit(tmp_path, "terminal", {"command": text})
    assert hit is not None and hit.target == "hermes config set command_allowlist"


@pytest.mark.parametrize(
    ("command", "kind"),
    [
        ("hermes config set command_allowlist x # --help", "settings"),
        ("hermes config set command_allowlist x #-h", "settings"),
        ("hermes config set command_allowlist -- --help", "settings"),
        ("hermes config edit --help", "settings"),
        ("hermes config edit -h", "settings"),
        ("hermes config migrate --help", "settings"),
        ("hermes config set approvals.mode off --help", "settings"),
        ("hermes import x.zip -h", "settings"),
        ("hermes setup --reset --help", "settings"),
        ("hermes approvals suggest --apply --help", "settings"),
        ("hermes profile install /tmp/profile --force --help", "settings"),
        ("hermes config set plugins.enabled x --help", "plugin"),
        ("hermes plugins disable petasos --help", "plugin"),
        ("ai.hermes plugins disable petasos --help", "plugin"),
        ("python -m hermes_cli.main plugins disable petasos --help", "plugin"),
        ("hermes plugins uninstall petasos -h", "plugin"),
        ("hermes plugins auto-update on --help", "plugin"),
        ("hermes plugins autoupdate off -h", "plugin"),
        ("hermes plugins install petasos --enable --help", "plugin"),
        ("hermes plugins install petasos --en -h", "plugin"),
        ("hermes plugins pack install /tmp/pack.yaml --help", "plugin"),
        ("hermes plugins enable petasos --allow-tool-override --help", "settings"),
    ],
)
def test_a_help_flag_does_not_clear_a_configuration_write(
    tmp_path: Path, command: str, kind: str
) -> None:
    hit = _hit(tmp_path, "terminal", {"command": command})
    assert hit is not None and hit.kind == kind, command


@pytest.mark.parametrize(
    "command",
    [
        "hermes plugins update petasos # --help",
        "hermes plugins update -- --help",
        "petasos config set x # --help",
        "HERMES_HOME=/tmp/other hermes chat # -h",
        "hermes gateway restart #note --help",
    ],
)
def test_a_help_word_after_a_comment_or_operands_is_not_help(tmp_path: Path, command: str) -> None:
    assert _hit(tmp_path, "terminal", {"command": command}) is not None, command


@pytest.mark.parametrize(
    ("command", "flag"),
    [
        ("hermes plugins enable petasos --allow-tool-override", "--allow-tool-override"),
        ("hermes plugins enable petasos --no-allow-tool-override", "--no-allow-tool-override"),
        ("hermes plugins enable --allow-tool petasos", "--allow-tool-override"),
        ("hermes plugins enable petasos --a", "--allow-tool-override"),
        ("hermes plugins enable petasos --no-a", "--no-allow-tool-override"),
    ],
)
def test_granting_or_revoking_tool_override_on_enable_is_a_change(
    tmp_path: Path, command: str, flag: str
) -> None:
    hit = _hit(tmp_path, "terminal", {"command": command})
    assert hit is not None and hit.kind == "settings", command
    # A revocation is reported as one, not as the grant.
    assert hit.target == f"hermes plugins enable {flag}", command


@pytest.mark.parametrize(
    "command",
    [
        "hermes plugins enable all",
        "hermes plugins enable --all",
        "hermes plugins enable -a",
        "hermes plugins enable '*'",
        "hermes plugins enable petasos==1",
        "hermes plugins enable 'petasos[all]'",
        "hermes plugins enable git+https://example.com/org/petasos.git",
        "hermes plugins enable git+https://example.com/org/petasos.git@main",
        "hermes plugins enable ./dist/petasos-0.1-py3-none-any.whl",
        "hermes plugins enable /tmp/petasos-0.1.tar.gz",
        "hermes plugins enable petasos kanban",
        "hermes plugins enable kanban petasos",
        "hermes plugins enable petasos --force",
        "hermes plugins enable --force petasos",
        "hermes plugins enable Petasos",
        "hermes plugins enable PETASOS",
        "hermes plugins ENABLE petasos",
        "hermes -v plugins enable petasos",
        "hermes -p work plugins enable petasos",
        "hermes --verbose plugins enable petasos",
        "ai.hermes plugins enable petasos",
        "python -m hermes_cli plugins enable petasos",
    ],
)
def test_enable_beyond_the_plain_plugin_name_is_a_change(tmp_path: Path, command: str) -> None:
    # ``--all`` is also an abbreviation of ``--allow-tool-override``.
    assert _hit(tmp_path, "terminal", {"command": command}) is not None, command


@pytest.mark.parametrize(
    "command",
    [
        "sudo hermes plugins enable petasos",
        "timeout 5 hermes plugins enable petasos",
        "env hermes plugins enable petasos",
        "nice hermes plugins enable petasos",
        "PIP_INDEX_URL=https://example.test/simple hermes plugins enable petasos",
        "HERMES plugins enable petasos",
        "Hermes plugins enable petasos",
        "hermes plugins enable petasos ''",
        "hermes plugins enable git+https://example.test/org/petasos@feature/x",
    ],
)
def test_enable_counts_as_plain_only_when_written_plainly(tmp_path: Path, command: str) -> None:
    assert _hit(tmp_path, "terminal", {"command": command}) is not None, command


@pytest.mark.parametrize(
    "command",
    ["hermes.exe plugins enable petasos", "C:/Hermes/hermes.exe plugins enable petasos"],
)
def test_suffixed_enable_is_a_change_where_the_suffix_names_hermes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    """On Windows ``hermes.exe`` runs Hermes; that spelling is still not the plain one."""
    monkeypatch.setattr(shell_parse, "os", SimpleNamespace(name="nt", path=os.path))
    assert shell_parse._program("hermes.exe") == "hermes"
    assert _hit(tmp_path, "terminal", {"command": command}) is not None, command


@pytest.mark.parametrize(
    "command",
    [
        "hermes plugins enable petasos",
        "/opt/hermes/bin/hermes plugins enable petasos",
        "/hermes plugins enable petasos",
        "  hermes plugins enable petasos  ",
        "  /opt/hermes/bin/hermes plugins enable petasos\t",
        "hermes plugins enable petasos\n",
        "\nhermes plugins enable petasos\n\n",
    ],
)
def test_plain_enable_as_the_whole_command_is_not_a_change(tmp_path: Path, command: str) -> None:
    assert _hit(tmp_path, "terminal", {"command": command}) is None, command


@pytest.mark.parametrize(
    "command",
    [
        "cd /tmp && hermes plugins enable petasos",
        "cd /tmp; hermes plugins enable petasos",
        "hermes plugins list\nhermes plugins enable petasos",
        "hermes plugins enable petasos\nhermes plugins list",
        "hermes plugins enable petasos; true",
        "hermes plugins enable petasos &",
        "hermes plugins enable petasos | cat",
        "cat <<EOF\nnote\nEOF\nhermes plugins enable petasos",
        "hermes  plugins enable petasos",
        "hermes plugins  enable petasos",
        "hermes plugins enable\tpetasos",
        "hermes plugins enable petasos # note",
        "hermes plugins enable petasos\r",
        "'hermes' plugins enable petasos",
        "hermes plugins enable \\petasos",
        "~/bin/hermes plugins enable petasos",
        "bin/hermes plugins enable petasos",
        "./hermes plugins enable petasos",
        "/opt//hermes plugins enable petasos",
        "/opt/$HOME/hermes plugins enable petasos",
        "/opt/hermes/bin/hermes.exe plugins enable petasos",
        "/opt/hermes/bin/Hermes plugins enable petasos",
    ],
)
def test_plain_enable_with_anything_else_is_a_change(tmp_path: Path, command: str) -> None:
    """Only the whole command text, written plainly, is the plain enable."""
    assert _hit(tmp_path, "terminal", {"command": command}) is not None, command


@pytest.mark.parametrize(
    "command",
    [
        "bash -c 'hermes plugins enable petasos'",
        "sh -c 'hermes plugins enable petasos'",
        "sh -c 'true; hermes plugins enable petasos'",
        "eval hermes plugins enable petasos",
        "eval 'hermes plugins enable petasos'",
        'eval "hermes plugins enable petasos"',
        "echo $(hermes plugins enable petasos)",
        "echo $(true; hermes plugins enable petasos; true)",
        "echo `hermes plugins enable petasos`",
        "cat <(hermes plugins enable petasos)",
        "(hermes plugins enable petasos)",
        "sudo $(true) hermes plugins enable petasos",
        "bash <<EOF\nhermes plugins enable petasos\nEOF",
        "bash <<EOF\nhermes plugins enable petasos",
        "python -c \"import os; os.system('hermes plugins enable petasos')\"",
        "python -c \"import subprocess; subprocess.run(['hermes','plugins','enable','petasos'])\"",
        "f() {\nhermes plugins enable petasos\n}\nf",
        "f()\n{\n  hermes plugins enable petasos\n}",
        "{ hermes plugins enable petasos; }",
        "{\nhermes plugins enable petasos\n}",
        "bash <<EOF \nhermes plugins enable petasos\nEOF \nhermes plugins enable petasos",
        "bash <<'EOF'\nhermes plugins enable petasos\n EOF\nhermes plugins enable petasos",
        "bash <<'-'\nhermes plugins enable petasos\n-",
        "bash <<.\nhermes plugins enable petasos\n.",
        "# (\nhermes plugins enable petasos",
        "true # (\nhermes plugins enable petasos",
        "cat <<EOF\n(\nEOF\nhermes plugins enable petasos",
        "cat <<EOF\n`\nEOF\nhermes plugins enable petasos",
    ],
)
def test_plain_enable_read_again_is_a_change(tmp_path: Path, command: str) -> None:
    """A script, a body or a document that runs the plain command is a change."""
    assert _hit(tmp_path, "terminal", {"command": command}) is not None, command


@pytest.mark.parametrize(
    "argv",
    [
        ["hermes", "plugins", "enable", "petasos"],
        ["hermes plugins enable petasos"],
        ("hermes", "plugins", "enable", "petasos"),
    ],
)
def test_plain_enable_as_an_argument_list_is_a_change(tmp_path: Path, argv: object) -> None:
    assert _hit(tmp_path, "terminal", {"command": argv}) is not None


@pytest.mark.parametrize(
    "command",
    [
        " " * 100_001 + "hermes plugins disable petasos",
        "echo " + "a" * 100_000 + "; hermes plugins enable petasos",
        "true; " * 64 + "hermes plugins enable petasos",
    ],
    ids=["blanks", "long-word", "many-commands"],
)
def test_a_change_after_a_long_prefix_is_read(tmp_path: Path, command: str) -> None:
    """Every command in the text is read, however long the text is."""
    assert _hit(tmp_path, "terminal", {"command": command}) is not None


def _windows_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shell_parse, "os", SimpleNamespace(name="nt", path=ntpath))
    monkeypatch.setattr(guardrail, "os", SimpleNamespace(name="nt", environ=os.environ))


@pytest.mark.parametrize(
    "command",
    [
        r"C:\Tools\hermes plugins enable petasos",
        "C:/Tools/hermes plugins enable petasos",
    ],
)
def test_windows_drive_path_is_not_plain_on_posix(tmp_path: Path, command: str) -> None:
    if os.name == "nt":
        pytest.skip("this host is Windows")
    assert _hit(tmp_path, "terminal", {"command": command}) is not None, command


@pytest.mark.parametrize(
    "command",
    [
        r"C:\Tools\hermes plugins enable petasos",
        "C:/Tools/hermes plugins enable petasos",
        r"d:\hermes plugins enable petasos",
        "hermes plugins enable petasos",
        "/opt/hermes/bin/hermes plugins enable petasos",
    ],
)
def test_windows_drive_path_is_plain_on_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    _windows_host(monkeypatch)
    assert _hit(tmp_path, "terminal", {"command": command}) is None, command


@pytest.mark.parametrize(
    "command",
    [
        "C:hermes plugins enable petasos",
        r"C:Tools\hermes plugins enable petasos",
        r"C:\Tools\hermes.exe plugins enable petasos",
        r"C:\Tools\Hermes plugins enable petasos",
        r"C:\Tools/hermes plugins enable petasos",
        r"C:\Tools\hermes plugins enable petasos & ver",
    ],
)
def test_other_windows_program_words_are_a_change_on_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    _windows_host(monkeypatch)
    assert _hit(tmp_path, "terminal", {"command": command}) is not None, command


@pytest.mark.parametrize(
    "command",
    [
        "hermes plugins enable all --help",
        "hermes plugins enable all -h",
        "hermes plugins enable petasos==1 --help",
        "hermes plugins enable petasos --help",
        "hermes plugins enable -a -h",
        "hermes plugins enable petasos other --help",
    ],
)
def test_help_does_not_clear_enable(tmp_path: Path, command: str) -> None:
    hit = _hit(tmp_path, "terminal", {"command": command})
    assert hit is not None and hit.target == "hermes plugins enable", command


def test_help_with_the_override_flag_is_still_the_override_write(tmp_path: Path) -> None:
    for flag in ("--allow-tool-override", "--no-allow-tool-override"):
        command = f"hermes plugins enable all {flag} --help"
        hit = _hit(tmp_path, "terminal", {"command": command})
        assert hit is not None and hit.target == f"hermes plugins enable {flag}", command


def test_a_very_long_command_is_not_plain(tmp_path: Path) -> None:
    padding = " ".join(["x"] * 3000)
    text = f"hermes plugins enable petasos {padding}"
    assert guardrail._plain_command(text, windows=False) is None
    assert _hit(tmp_path, "terminal", {"command": text}) is not None


def test_a_very_long_text_is_not_split_for_the_plain_check() -> None:
    class _NoSplit(str):
        def strip(self, chars: str | None = None) -> str:
            return _NoSplit(str.strip(self, chars))

        def split(self, sep: str | None = None, maxsplit: int = -1) -> list[str]:
            raise AssertionError("split called on long text")

    long_text = _NoSplit("hermes plugins enable petasos " + "y " * 5000)
    assert guardrail._plain_command(long_text, windows=False) is None


def test_command_rule_fields_keep_their_positions() -> None:
    rule = CommandRule(
        "settings",
        ("hermes", "x"),
        "label",
        "name",
        "tail",
        True,
        ("on",),
        "--flag",
        ("--check",),
        True,
        False,
    )
    assert rule.kind == "settings"
    assert rule.words == ("hermes", "x")
    assert rule.label == "label"
    assert rule.name == "name"
    assert rule.tail == "tail"
    assert rule.bare is True
    assert rule.one_of == ("on",)
    assert rule.requires_flag == "--flag"
    assert rule.unless_flags == ("--check",)
    assert rule.unknown_program is True
    assert rule.help_clears is False
    assert rule.except_exact == ()


@pytest.mark.parametrize(
    "command",
    [
        "hermes config set approvals_backup example",
        "hermes config set command_allowlist_backup x",
        "hermes config unset plugins_extra",
        "h config set pluginsx.enabled y",
    ],
)
def test_a_config_key_matches_only_at_a_segment_boundary(tmp_path: Path, command: str) -> None:
    assert _hit(tmp_path, "terminal", {"command": command}) is None, command


@pytest.mark.parametrize(
    ("command", "kind"),
    [
        ("hermes plugins update # note", "plugin"),
        ("hermes plugins update #note", "plugin"),
        ("hermes plugins update\t# note", "plugin"),
        ("hermes plugins update kanban # petasos", "plugin"),
        ("hermes approvals suggest --help # --apply", "settings"),
        ("hermes config get approvals # hermes config set command_allowlist x", "settings"),
        ("echo hi # note\nhermes plugins disable petasos", "plugin"),
        ("echo hi # note; hermes plugins disable petasos", "plugin"),
        ("echo hi # note && hermes plugins disable petasos", "plugin"),
        ("hermes plugins disable a#b petasos", "plugin"),
        ("hermes plugins disable '#x' petasos", "plugin"),
        ('hermes plugins disable "# x" petasos', "plugin"),
        ("hermes plugins disable \\#x petasos", "plugin"),
        ("hermes plugins disable ''#x petasos", "plugin"),
        ("echo `hermes plugins disable #x petasos`", "plugin"),
        ("echo $(hermes plugins disable #x petasos)", "plugin"),
        ("echo $( (true); hermes plugins disable #x petasos)", "plugin"),
    ],
)
def test_a_hash_word_hides_no_word_after_it(tmp_path: Path, command: str, kind: str) -> None:
    # Comments are not parsed: a word starting with ``#`` and the words after
    # it are read like any others, so they can still make a change.
    hit = _hit(tmp_path, "terminal", {"command": command})
    assert hit is not None and hit.kind == kind, command


@pytest.mark.parametrize(
    "command",
    [
        "echo $(true) # hermes config set approvals x",
        "echo `true` # hermes config set approvals x",
        "# hermes plugins disable petasos",
    ],
)
def test_a_command_written_after_a_hash_still_counts(tmp_path: Path, command: str) -> None:
    assert _hit(tmp_path, "terminal", {"command": command}) is not None, command


@pytest.mark.parametrize(
    "command",
    [
        'echo hi # say "a; b"\nhermes plugins disable petasos',
        "echo hi # note 'a; b'\nhermes plugins disable petasos",
    ],
)
def test_a_quoted_separator_after_a_hash_hides_no_later_line(tmp_path: Path, command: str) -> None:
    hit = _hit(tmp_path, "terminal", {"command": command})
    assert hit is not None and hit.kind == "plugin", command
    assert ("hermes", "plugins", "disable", "petasos") in [s.argv for s in _parse(command)]


@pytest.mark.parametrize(
    ("argv", "kind"),
    [
        (["hermes", "plugins", "disable", "#x", "petasos"], "plugin"),
        (["hermes", "approvals", "suggest", "#x", "--apply"], "settings"),
    ],
)
def test_a_hash_argument_in_an_argv_list_is_kept(
    tmp_path: Path, argv: list[str], kind: str
) -> None:
    assert [s.argv for s in _parse(" ".join(argv))] == [tuple(argv)]
    hit = _hit(tmp_path, "terminal", {"command": argv})
    assert hit is not None and hit.kind == kind, argv
    words = ", ".join(repr(word) for word in argv)
    script = f'python -c "import subprocess; subprocess.run([{words}])"'
    hit = _hit(tmp_path, "terminal", {"command": script})
    assert hit is not None and hit.kind == kind, script


@pytest.mark.parametrize(
    "command",
    ["hermes plugins disable ''\\\n#x petasos", "hermes plugins disable '' \\\n#x petasos"],
)
def test_a_line_continuation_before_a_hash_word_keeps_it(tmp_path: Path, command: str) -> None:
    assert [s.argv for s in _parse(command)] == [("hermes", "plugins", "disable", "#x", "petasos")]
    hit = _hit(tmp_path, "terminal", {"command": command})
    assert hit is not None and hit.kind == "plugin", command


@pytest.mark.parametrize(
    "command",
    [
        "echo $(hermes plugins update # note)",
        "echo `hermes plugins update # note`",
        "echo $(hermes plugins update #note)",
        "echo `hermes plugins update #`",
    ],
)
def test_a_hash_word_inside_a_substitution_is_not_a_plugin_name(
    tmp_path: Path, command: str
) -> None:
    # A shell may read ``#`` there as a comment, so no plugin is named and
    # every installed plugin is updated.
    hit = _hit(tmp_path, "terminal", {"command": command})
    assert hit is not None and hit.kind == "plugin", command


def test_a_named_plugin_update_still_names_only_that_plugin(tmp_path: Path) -> None:
    assert _hit(tmp_path, "terminal", {"command": "hermes plugins update kanban"}) is None
    assert _hit(tmp_path, "terminal", {"command": "echo $(hermes plugins update kanban)"}) is None


def test_a_quoted_name_starting_with_a_hash(tmp_path: Path) -> None:
    # Quoting is gone by the time a word is judged, so ``'#weird'`` reads as
    # a possible comment. Disabling it names no plugin of ours either way.
    assert _hit(tmp_path, "terminal", {"command": "hermes plugins disable '#weird'"}) is None
    # Updating it reads as updating every plugin.
    hit = _hit(tmp_path, "terminal", {"command": "hermes plugins update '#weird'"})
    assert hit is not None and hit.kind == "plugin"


@pytest.mark.parametrize(
    "command",
    [
        "echo " + "config " * 20000,
        "; ".join(["echo config"] * 100000),
        "; ".join(["h config"] * 100000),
        "! " * 50000 + "hermes",
        "{ " * 50000 + "hermes",
        "env " + "-u X " * 20000,
    ],
    ids=["config-words", "echo-segments", "unknown-segments", "bang", "brace", "env-options"],
)
def test_recognition_cost_stays_linear_in_command_length(tmp_path: Path, command: str) -> None:
    # A quadratic step takes several seconds on these at the length cap.
    start = time.perf_counter()
    _hit(tmp_path, "terminal", {"command": command})
    assert time.perf_counter() - start < 2.0
