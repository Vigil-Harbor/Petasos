"""Cases an outside review found after the Windows path and native-shell work."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from petasos.guard.guardrail import recognize
from petasos.hermes.guardrail import hermes_surface

if TYPE_CHECKING:
    from pathlib import Path

    from petasos.guard.surface import GuardrailHit

windows_only = pytest.mark.skipif(os.name != "nt", reason="Windows path forms")


def _recognize(tmp_path: Path, command: str, *, cwd: str | None = None) -> GuardrailHit | None:
    """Judge a terminal command with an empty environment, so only ``cwd`` places a name."""
    home = tmp_path / "owned"
    (home / "plugins" / "petasos").mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text("plugins: {}\n", encoding="utf-8")
    package = tmp_path / "pkg" / "petasos"
    package.mkdir(parents=True, exist_ok=True)
    paths = [home / "config.yaml", home / "plugins" / "petasos"]
    surface = hermes_surface((str(path) for path in paths), roots=(str(home),))
    return recognize(
        "terminal",
        {"command": command},
        protected=(str(home / "config.yaml"),),
        surface=surface,
        package=(str(package),),
        environ={},
        cwd=str(home) if cwd is None else cwd,
    )


def _bash_form(path: Path) -> str:
    forward = path.as_posix()
    return "/" + forward[0].lower() + forward[2:]


@windows_only
@pytest.mark.parametrize(
    "template",
    [
        "rm {up}{home}/config.*",
        "cp /other/config.yaml {up}{home}",
        "cd {up}{home}; rm config.yaml",
        "rm -rf {up}{home}/plugins",
        "mv {up}{home} /tmp/gone",
    ],
)
def test_the_shells_reading_of_dots_reaches_every_kind_of_match(
    tmp_path: Path, template: str
) -> None:
    """A wildcard, a copy's landing place, a directory and ``cd`` all take both readings."""
    home = tmp_path / "owned"
    bash_home = _bash_form(home)
    up = "../" * len(bash_home.strip("/").split("/"))
    command = template.format(up=up, home=bash_home.lstrip("/"))
    assert _recognize(tmp_path, command) is not None, command


@pytest.mark.parametrize(
    "command",
    [
        "cmd //c cmd //c cmd //c cmd //c hermes plugins disable petasos",
        "cmd cmd cmd cmd hermes plugins disable petasos",
        "powershell -c powershell -c powershell -c powershell -c hermes plugins disable petasos",
    ],
)
def test_reading_a_native_shell_never_hides_a_listed_command(tmp_path: Path, command: str) -> None:
    hit = _recognize(tmp_path, command)
    assert hit is not None
    assert hit.kind == "plugin"


@pytest.mark.parametrize(
    "script",
    [
        "Get-Content config.yaml <# note #>; Set-Content config.yaml x",
        "Get-Content config.yaml <# one\ntwo #>\nSet-Content config.yaml x",
        "Set-Content config.yaml x",
        "Set-Content\x0bconfig.yaml x",
        "Set-Content\x0cconfig.yaml x",
        'Set-Content "${env:PETASOS_NOT_SET}config.yaml" x',
    ],
)
def test_powershell_text_the_first_tokenizer_misread(tmp_path: Path, script: str) -> None:
    """A block comment, uncommon white space, and a variable that is not set."""
    hit = _recognize(tmp_path, f"powershell -NoProfile -c '{script}'")
    assert hit is not None, script
    assert hit.kind == "settings"


@pytest.mark.parametrize(
    "script",
    [
        "Get-Content config.yaml <# Set-Content config.yaml x #>",
        "Get-Content config.yaml # Set-Content config.yaml x",
    ],
)
def test_a_writer_inside_a_comment_is_not_a_change(tmp_path: Path, script: str) -> None:
    assert _recognize(tmp_path, f"powershell -NoProfile -c '{script}'") is None


def test_a_native_shell_inside_a_nested_script_is_read_before_a_later_starter(
    tmp_path: Path,
) -> None:
    """At any depth, not only at the top of the line."""
    command = (
        "bash -c 'xargs -a /dev/null powershell -c \"hermes plugins disable petasos; #\" python'"
    )
    hit = _recognize(tmp_path, command)
    assert hit is not None
    assert hit.kind == "plugin"


def test_a_long_repetitive_line_is_worked_out_once_per_distinct_word(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The line is judged from several starting words. The path work must not repeat."""
    from petasos.guard import paths

    worked = 0
    find = paths._find_path

    def counting(*args: object, **kwargs: object) -> object:
        nonlocal worked
        worked += 1
        return find(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(paths, "_find_path", counting)
    assert _recognize(tmp_path, "x powershell -c x bash -c nope " * 344) is None
    assert worked < 100


def test_a_native_shell_after_a_run_of_ordinary_starters_is_still_read(tmp_path: Path) -> None:
    """The first pass runs out of depth here, and only the second reaches the PowerShell."""
    command = (
        'a bash -c x b bash -c x c bash -c x d powershell -c "hermes plugins disable petasos"'
    )
    hit = _recognize(tmp_path, command)
    assert hit is not None
    assert hit.kind == "plugin"


def test_a_remembered_answer_does_not_outlive_a_changed_variable(tmp_path: Path) -> None:
    """Within one recognition a variable that changes is a new question."""
    from petasos.guard import paths

    home = tmp_path / "owned"
    home.mkdir()
    config = home / "config.yaml"
    owned = paths._Owned({paths.normalize_path_text(str(config)): "settings"}, ())
    env = {"TARGET": str(tmp_path / "elsewhere.txt")}
    assert paths._match_path("$TARGET", owned, env, str(tmp_path)) is None
    env["TARGET"] = str(config)
    assert paths._match_path("$TARGET", owned, env, str(tmp_path)) is not None
    env["HOME"] = str(home)
    assert paths._match_path("elsewhere.txt", owned, env, str(tmp_path)) is None
    assert paths._match_path("config.yaml", owned, env, str(tmp_path)) is not None


def test_a_remembered_relative_name_follows_a_changed_home(tmp_path: Path) -> None:
    """The same relative name, asked again after only HOME or HERMES_HOME moved."""
    from petasos.guard import paths

    home = tmp_path / "owned"
    home.mkdir()
    config = home / "config.yaml"
    owned = paths._Owned({paths.normalize_path_text(str(config)): "settings"}, ())
    cwd = str(tmp_path / "work")
    for key in ("HOME", "HERMES_HOME"):
        owned.seen.clear()
        env = {key: str(tmp_path / "other")}
        assert paths._match_path("config.yaml", owned, env, cwd) is None
        env[key] = str(home)
        assert paths._match_path("config.yaml", owned, env, cwd) is not None


def test_words_that_expand_alike_are_not_one_question(tmp_path: Path) -> None:
    """A brace group written out and one held in a variable name different paths."""
    from petasos.guard import paths

    sample = tmp_path / "sample.txt"
    owned = paths._Owned({paths.normalize_path_text(str(sample)): "settings"}, ())
    env = {"LABEL": "{sample,other}.txt"}
    cwd = str(tmp_path)
    assert paths._match_path("{sample,other}.txt", owned, env, cwd, hedge=False) is not None
    # The shell does not brace-expand a variable's value, so this names no protected file.
    assert paths._match_path("$LABEL", owned, env, cwd, hedge=False) is None
    owned.seen.clear()
    assert paths._match_path("$LABEL", owned, env, cwd, hedge=False) is None
    assert paths._match_path("{sample,other}.txt", owned, env, cwd, hedge=False) is not None


def test_a_name_joined_by_a_brace_group_is_part_of_the_question(tmp_path: Path) -> None:
    """``$A{B,C}`` reads ``$AB`` and ``$AC``, so a change to ``AB`` is a new question."""
    from petasos.guard import paths

    config = tmp_path / "config.yaml"
    owned = paths._Owned({paths.normalize_path_text(str(config)): "settings"}, ())
    env = {"AB": str(tmp_path / "elsewhere.txt")}
    assert paths._match_path("$A{B,C}", owned, env, str(tmp_path), hedge=False) is None
    env["AB"] = str(config)
    assert paths._match_path("$A{B,C}", owned, env, str(tmp_path), hedge=False) is not None
