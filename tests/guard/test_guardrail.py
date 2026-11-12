"""Recognition of a guardrail change: paths, commands, disguises, and misses."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from petasos.guard.guardrail import recognize
from petasos.guard.paths import normalize_path_text
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


def test_sed_in_place_edits_the_config(tmp_path: Path) -> None:
    home, *_rest = _home(tmp_path)
    command = f"sed -i 's/enabled: true/enabled: false/' {home / 'config.yaml'}"
    hit = _hit(tmp_path, "terminal", {"command": command})
    assert hit is not None and hit.kind == "settings"


def test_execute_code_open_writes_the_config(tmp_path: Path) -> None:
    home, *_rest = _home(tmp_path)
    code = f"open('{home / 'config.yaml'}','w').write('x')"
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
    command = f"perl -i -pe 's/a/b/' {home / 'config.yaml'}"
    hit = _hit(tmp_path, "terminal", {"command": command})
    assert hit is not None and hit.kind == "settings"


def test_append_redirect_writes_the_config(tmp_path: Path) -> None:
    home, *_rest = _home(tmp_path)
    hit = _hit(tmp_path, "terminal", {"command": f"echo x >> {home / 'config.yaml'}"})
    assert hit is not None and hit.kind == "settings"


def test_tee_append_writes_the_config(tmp_path: Path) -> None:
    home, *_rest = _home(tmp_path)
    hit = _hit(tmp_path, "terminal", {"command": f"echo x | tee -a {home / 'config.yaml'}"})
    assert hit is not None and hit.kind == "settings"


def test_install_mode_writes_the_config(tmp_path: Path) -> None:
    home, *_rest = _home(tmp_path)
    command = f"install -m 644 /tmp/other.yaml {home / 'config.yaml'}"
    hit = _hit(tmp_path, "terminal", {"command": command})
    assert hit is not None and hit.kind == "settings"


def test_symlink_force_replaces_the_config(tmp_path: Path) -> None:
    home, *_rest = _home(tmp_path)
    hit = _hit(tmp_path, "terminal", {"command": f"ln -sf /tmp/other {home / 'config.yaml'}"})
    assert hit is not None and hit.kind == "settings"


def test_moving_the_plugin_directory_is_a_change(tmp_path: Path) -> None:
    home, *_rest = _home(tmp_path)
    hit = _hit(tmp_path, "terminal", {"command": f"mv {home / 'plugins' / 'petasos'} /tmp/away"})
    assert hit is not None and hit.kind == "plugin"


def test_truncate_and_chmod_recursive_change_a_protected_path(tmp_path: Path) -> None:
    home, *_rest = _home(tmp_path)
    truncated = _hit(tmp_path, "terminal", {"command": f"truncate -s 0 {home / 'config.yaml'}"})
    chmod = _hit(tmp_path, "terminal", {"command": f"chmod -R a+r {home / 'plugins' / 'petasos'}"})
    assert truncated is not None and truncated.kind == "settings"
    assert chmod is not None and chmod.kind == "plugin"


def test_a_symlink_and_a_parent_directory_still_name_the_config(tmp_path: Path) -> None:
    home, package, surface, env = _home(tmp_path)
    config = home / "config.yaml"
    link = tmp_path / "via-link.yaml"
    link.symlink_to(config)
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
    code = f"# see {home / 'config.yaml'}\nprint('ok')\n"
    assert _hit(tmp_path, "execute_code", {"code": code}) is None


def test_powershell_get_content_reads_and_set_content_writes(tmp_path: Path) -> None:
    home, *_rest = _home(tmp_path)
    config = home / "config.yaml"
    assert _hit(tmp_path, "terminal", {"command": f"powershell Get-Content {config}"}) is None
    written = _hit(tmp_path, "terminal", {"command": f"powershell Set-Content {config} x"})
    assert written is not None and written.kind == "settings"


def test_echo_and_printf_do_not_act_on_a_path_argument(tmp_path: Path) -> None:
    home, *_rest = _home(tmp_path)
    config = home / "config.yaml"
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
        "pip install requests",
        "hermes config set display.theme teal",
        "git commit -m 'docs: hermes gateway restart steps'",
        "echo 'hermes plugins disable petasos' > /tmp/notes.txt",
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
    quoted = f"echo 'see {home / 'config.yaml'}' > /tmp/notes"
    assert _hit(tmp_path, "terminal", {"command": quoted}) is None
    assert _hit(tmp_path, "terminal", {"command": f"grep enabled {home / 'config.yaml'}"}) is None
    copied = f"cp {home / 'config.yaml'} /tmp/backup.yaml"
    assert _hit(tmp_path, "terminal", {"command": copied}) is None
    assert _hit(tmp_path, "read_file", {"path": str(home / "config.yaml")}) is None
    assert _hit(tmp_path, "terminal", {"command": f"cat {home / 'config.yaml'}"}) is None


def _at(tmp_path: Path, command: str, cwd: Path | None = None) -> GuardrailHit | None:
    """Judge a terminal command. ``{home}`` and ``{config}`` are filled in."""
    home, package, surface, env = _home(tmp_path)
    text = command.replace("{home}", str(home)).replace("{config}", str(home / "config.yaml"))
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
