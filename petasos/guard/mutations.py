"""Recognize shell writes and distinguish plain readers."""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

from petasos.guard.paths import _match_path, _Owned
from petasos.guard.program import _code_names_path
from petasos.guard.shell_parse import _program

if TYPE_CHECKING:
    from collections.abc import Mapping

    from petasos.guard.surface import GuardrailHit


# A shell program is a reader only when it is used as one. Anything else that
# names a protected path fails closed and asks. ``rg`` is included as a grep.
_READERS = frozenset(
    {
        "[",
        "b2sum",
        "bzgrep",
        "cat",
        "cd",
        "cksum",
        "cmp",
        "diff",
        "du",
        "egrep",
        "fgrep",
        "file",
        "find",
        "grep",
        "head",
        "jq",
        "less",
        "ls",
        "md5",
        "md5sum",
        "more",
        "popd",
        "pushd",
        "readlink",
        "realpath",
        "rg",
        "rgrep",
        "sha1sum",
        "sha224sum",
        "sha256sum",
        "sha384sum",
        "sha512sum",
        "shasum",
        "stat",
        "sum",
        "tail",
        "test",
        "tree",
        "wc",
        "xzgrep",
        "yq",
        "zegrep",
        "zfgrep",
        "zgrep",
    }
)
_IN_PLACE = frozenset({"-i", "--in-place", "--inplace"})
_FIND_WRITES = frozenset(
    {
        "-delete",
        "-exec",
        "-execdir",
        "-fls",
        "-fprint",
        "-fprint0",
        "-fprintf",
        "-ok",
        "-okdir",
    }
)
# Last positional is the path written, unless ``-t`` names it. A protected
# source with an unprotected destination is a read. ``install`` and ``ln``
# have that same shape. ``rsync --remove-source-files`` deletes the source.
_COPIES = frozenset({"cp", "install", "ln", "rsync", "scp"})
# Their words are verbs and names, and the forms that change a guardrail are
# listed as rules. Only a word written as a path is read as one.
_VERB_PROGRAMS = frozenset({"hermes", "petasos", "pip", "uv"})
# An argument is program text, so a protected path anywhere inside it counts.
_INTERPRETERS = frozenset(
    {
        "awk",
        "bun",
        "deno",
        "gawk",
        "lua",
        "mawk",
        "node",
        "nodejs",
        "osascript",
        "perl",
        "php",
        "ruby",
        "sed",
    }
)
_COPY_DEST_FLAGS = frozenset({"-t", "--target-directory"})
# PowerShell read cmdlets. A write cmdlet in the same command is not a read.
_PS_READS = frozenset(
    {
        "gc",
        "gci",
        "get-childitem",
        "get-content",
        "get-filehash",
        "get-item",
        "gi",
        "resolve-path",
        "select-string",
        "sls",
        "test-path",
    }
)
_PS_WRITES = frozenset(
    {
        "ac",
        "add-content",
        "clear-content",
        "clc",
        "copy-item",
        "del",
        "erase",
        "move-item",
        "new-item",
        "out-file",
        "rd",
        "remove-item",
        "rename-item",
        "ri",
        "rmdir",
        "sc",
        "set-content",
        "set-item",
    }
)
_NAME_END = re.compile(r"[=<>!~\[;@\s]")


def _mutation(
    argv: tuple[str, ...],
    redirects: tuple[str, ...],
    owned: _Owned,
    env: Mapping[str, str],
    cwd: str,
) -> GuardrailHit | None:
    """A protected path this command acts on, unless the program only reads it.

    The command word itself is never a path the command acts on.
    """
    for target in redirects:
        hit = _match_path(target, owned, env, cwd)
        if hit is not None:
            return hit
    if not argv:
        return None
    program = _program(argv[0])
    if program in _TEXT_ONLY or _powershell_reads(program, argv):
        return None
    if program == "dd":
        return _dd_hit(argv, owned, env, cwd)
    if program in _COPIES or program == "mv":
        return _copy_hit(argv, owned, env, cwd, moves=program == "mv")
    if _reads(program, argv):
        return None
    words = _operands(argv)
    if program in _VERB_PROGRAMS:
        words = [word for word in words if _written_as_path(word)]
    for word in words:
        hit = _match_path(word, owned, env, cwd, above=True)
        if hit is not None:
            return hit
    if program in _INTERPRETERS:
        for word in argv[1:]:
            hit = _code_names_path(word, owned, env, cwd)
            if hit is not None:
                return hit
    return None


def _written_as_path(word: str) -> bool:
    return "/" in word or os.sep in word or word.startswith(("~", ".", "$"))


def _powershell_reads(program: str, argv: tuple[str, ...]) -> bool:
    """True when ``powershell`` or ``pwsh`` is only running a read cmdlet."""
    if program not in {"powershell", "pwsh"}:
        return False
    words = [word.casefold() for word in argv[1:]]
    if any(word in _PS_WRITES for word in words):
        return False
    return any(word in _PS_READS for word in words)


def _reads(program: str, argv: tuple[str, ...]) -> bool:
    """True when ``program`` is on the reader list and this invocation only reads."""
    if program not in _READERS:
        return False
    if program in {"jq", "yq"} and _in_place(argv):
        return False
    writing = program == "find" and any(word in _FIND_WRITES for word in argv[1:])
    return not writing


def _in_place(argv: tuple[str, ...]) -> bool:
    for word in argv[1:]:
        if word in _IN_PLACE or word.startswith("--in-place=") or word.startswith("--inplace="):
            return True
    return False


def _dd_hit(
    argv: tuple[str, ...],
    owned: _Owned,
    env: Mapping[str, str],
    cwd: str,
) -> GuardrailHit | None:
    """``of=`` writes. ``if=`` only reads."""
    for word in argv[1:]:
        if word.startswith("of="):
            hit = _match_path(word[3:], owned, env, cwd)
            if hit is not None:
                return hit
    return None


def _copy_hit(
    argv: tuple[str, ...],
    owned: _Owned,
    env: Mapping[str, str],
    cwd: str,
    *,
    moves: bool = False,
) -> GuardrailHit | None:
    """A read only when every protected path is a source that stays where it is.

    The destination counts when it is protected, and when a source would land
    on a protected path inside it (``cp /tmp/config.yaml ~/.hermes/``).
    """
    destination, sources, removes_source = _copy_ends(argv)
    if moves or removes_source:
        for source in sources:
            hit = _match_path(source, owned, env, cwd, above=True)
            if hit is not None:
                return hit
    if destination is None:
        return None
    hit = _match_path(destination, owned, env, cwd)
    if hit is not None:
        return hit
    for source in sources:
        landed = os.path.join(destination, os.path.basename(source))
        hit = _match_path(landed, owned, env, cwd, above=True, hedge=False)
        if hit is not None:
            return hit
    return None


def _copy_ends(argv: tuple[str, ...]) -> tuple[str | None, list[str], bool]:
    """Destination, sources, and whether the source is deleted afterwards."""
    positionals: list[str] = []
    destination: str | None = None
    removes_source = False
    index = 1
    while index < len(argv):
        word = argv[index]
        if word == "--":
            positionals.extend(argv[index + 1 :])
            break
        if word == "--remove-source-files":
            removes_source = True
            index += 1
            continue
        if word.startswith("--") and "=" in word:
            flag, value = word.split("=", 1)
            if flag in _COPY_DEST_FLAGS:
                destination = value
            index += 1
            continue
        if word in _COPY_DEST_FLAGS and index + 1 < len(argv):
            destination = argv[index + 1]
            index += 2
            continue
        if word.startswith("-"):
            index += 1
            continue
        positionals.append(word)
        index += 1
    if destination is None and positionals:
        destination = positionals[-1]
        positionals = positionals[:-1]
    return destination, positionals, removes_source


def _operands(argv: tuple[str, ...]) -> list[str]:
    """Words the program receives, skipping flags. ``--`` ends the flags."""
    words: list[str] = []
    index = 1
    while index < len(argv):
        word = argv[index]
        if word == "--":
            words.extend(argv[index + 1 :])
            break
        if word.startswith("-"):
            bound = _bound_path(word)
            if bound:
                words.append(bound)
            index += 1
            continue
        words.append(word)
        index += 1
    return words


def _bound_path(word: str) -> str | None:
    """The path glued to an option (``--output=path``, ``-o/path``), if any."""
    if word.startswith("--") and "=" in word:
        return word.split("=", 1)[1]
    if word.startswith("-") and not word.startswith("--") and len(word) > 2:
        rest = word[2:]
        return rest[1:] if rest.startswith("=") else rest
    return None


_TEXT_ONLY = frozenset(
    {
        ":",
        "basename",
        "dirname",
        "echo",
        "expr",
        "false",
        "printf",
        "pwd",
        "seq",
        "sleep",
        "true",
        "uname",
        "uptime",
        "whoami",
        "yes",
    }
)
