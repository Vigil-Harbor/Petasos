"""Recognise a tool call that would change a guardrail.

The guard stays host-agnostic. A host supplies the paths and the command
patterns that belong to it. Petasos's own package files and its own commands
are recognised here. A shell command that names a protected path is a change
unless the program is a plain reader and is used as one. So is a command that
names a directory holding a protected path, or a wildcard that covers one,
when that directory is inside a root the host names (its home). A directory
further up, such as ``/``, is left to the destructive-command rules. A
redirect into a protected path is always a change. A path that only appears
inside text the command writes somewhere else is not.

Program text (``execute_code``, ``python``, and ``python -c``) is not read as
a shell line. Embedded commands are judged as shell, and any protected path
the text names is a change. Python is not treated as read-only.

Recognition is the plain forms and the cheap disguises: quotes joined inside
a word, a backslash before an ordinary character, an environment-variable
prefix, ``sh -c``, ``eval``, a program started by another (``timeout 5 hermes
...``), a relative path, a ``cd`` earlier in the same command, ``~``,
``$HERMES_HOME``, a subshell, and commands chained with ``&&``, ``||``, ``;``,
``&`` or ``|``. It is not a sandbox. Encoded payloads, aliases, command
substitution inside double quotes, and a path assembled at runtime from
separate pieces are not matched."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from petasos.guard.paths import _match_path, _Owned, _owned
from petasos.guard.program import _is_code_tool
from petasos.guard.shell import _command_change, _judge_code
from petasos.guard.shell_parse import _program
from petasos.guard.surface import GuardrailHit, GuardrailSurface, package_roots

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


_READ_TOOLS = frozenset(
    {
        "file_read",
        "read",
        "read_file",
        "read_terminal",
        "search_files",
        "vision_analyze",
        "web_extract",
        "web_search",
    }
)
_PATH_KEYS = frozenset(
    {
        "dest",
        "destination",
        "dir",
        "directory",
        "file",
        "file_path",
        "filename",
        "filepath",
        "new_path",
        "old_path",
        "path",
        "source",
        "src",
        "target",
    }
)
_COMMAND_KEYS = frozenset({"cmd", "code", "command", "input", "script"})
_WRITE_TOOLS = frozenset(
    {
        "chmod",
        "create_file",
        "delete_file",
        "edit_file",
        "file_write",
        "move_file",
        "patch",
        "write",
        "write_file",
    }
)
# Tools that remove or move a whole directory, so a directory that holds a
# protected path counts.
_TREE_TOOLS = frozenset({"chmod", "delete_file", "move_file"})


def recognize(
    tool: str,
    params: Mapping[str, object],
    *,
    protected: Iterable[str] = (),
    surface: GuardrailSurface | None = None,
    package: Iterable[str] | None = None,
    environ: Mapping[str, str] | None = None,
    cwd: str | None = None,
) -> GuardrailHit | None:
    """The first guardrail change in ``params``, or ``None``.

    ``protected`` is the host's path set, used when ``surface`` does not label
    a path. A labelled path keeps its label. ``package`` defaults to the
    installed package directory.
    """
    if _program(tool) in _READ_TOOLS or tool in _READ_TOOLS:
        return None
    host = surface if surface is not None else GuardrailSurface()
    env = os.environ if environ is None else environ
    work = os.getcwd() if cwd is None else cwd
    owned = _owned(protected, host, package if package is not None else package_roots())
    if _is_code_tool(tool):
        for text in _command_texts(params):
            hit = _judge_code(text, owned, host, env, work)
            if hit is not None:
                return hit
        return None
    path_hit = _path_change(tool, params, owned, env, work, host.command_tools)
    if path_hit is not None:
        return path_hit
    if _program(tool) not in host.command_tools and tool not in host.command_tools:
        return None
    for text in _command_texts(params):
        hit = _command_change(text, owned, host, env, work)
        if hit is not None:
            return hit
    return None


def _path_change(
    tool: str,
    params: Mapping[str, object],
    owned: _Owned,
    env: Mapping[str, str],
    cwd: str,
    command_tools: frozenset[str],
) -> GuardrailHit | None:
    if _program(tool) in command_tools or tool in command_tools:
        return None
    above = _program(tool) in _TREE_TOOLS
    for key, value in params.items():
        if key not in _PATH_KEYS or not isinstance(value, str):
            continue
        hit = _match_path(value, owned, env, cwd, above=above)
        if hit is not None:
            return hit
    return None


def _command_texts(params: Mapping[str, object]) -> list[str]:
    texts: list[str] = []
    for key, value in params.items():
        if key not in _COMMAND_KEYS:
            continue
        if isinstance(value, str):
            texts.append(value)
        elif isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value):
            texts.append(" ".join(value))
    return texts
