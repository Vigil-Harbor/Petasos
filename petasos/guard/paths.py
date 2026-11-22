"""Match owned paths, directories, and wildcard forms."""

from __future__ import annotations

import fnmatch
import os
import posixpath
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from petasos.guard.surface import _KINDS, GuardrailHit, GuardrailSurface

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


_MAX_BRACES = 64
_GLOB = re.compile(r"[*?\[]")
_BRACES = re.compile(r"\{([^{}]*,[^{}]*)\}")
_BASH_DRIVE = re.compile(r"/(?:(?:cygdrive|mnt)/)?([A-Za-z])(/.*)?")
_DRIVE_PREFIX = re.compile(r"[A-Za-z]:")


@dataclass(frozen=True, slots=True)
class _Owned:
    """Protected paths with their kinds, and the roots they are kept in."""

    paths: Mapping[str, str]
    roots: tuple[str, ...]


def normalize_path_text(text: str) -> str:
    """The guard's path comparison: unicode escapes, slashes, then a resolved absolute path.

    A relative path is not resolved. That is the comparison the existing
    self-modification check uses, and this function stays identical to it.
    """
    cleaned = re.sub(r"\\u([0-9a-fA-F]{4})", lambda match: chr(int(match.group(1), 16)), text)
    cleaned = cleaned.replace("\\\\", "/").replace("\\", "/")
    if os.name == "nt":
        # The long-path and device prefixes name the same file as the plain drive path.
        if cleaned.startswith(("//?/", "//./")) and cleaned[5:6] == ":":
            cleaned = cleaned[4:]
        cleaned = _native_drive(cleaned)
    cleaned = os.path.normcase(cleaned.replace("/", os.sep))
    try:
        path = Path(cleaned)
        if path.is_absolute():
            cleaned = os.path.normcase(str(path.resolve(strict=False)))
    except (OSError, ValueError, RuntimeError):
        pass
    return cleaned


def _native_drive(text: str) -> str:
    """``/c/Users/x`` as ``c:/Users/x``. Anything else is returned unchanged.

    Hermes runs its Windows terminal and file tools through Git Bash, where
    drive C is the directory ``/c``. Cygwin and WSL spell it ``/cygdrive/c``
    and ``/mnt/c``. Applied on Windows only.
    """
    match = _BASH_DRIVE.fullmatch(text)
    if match is None:
        return text
    return f"{match.group(1)}:{match.group(2) or '/'}"


def _owned(
    protected: Iterable[str],
    surface: GuardrailSurface,
    package: Iterable[str],
) -> _Owned:
    """Normalised path to its kind. A later label does not hide an earlier one.

    The environment the package is installed in is a root, so removing that
    environment is recognised.
    """
    found: dict[str, str] = {}
    roots = {normalize_path_text(str(raw)) for raw in surface.roots}
    environment = normalize_path_text(sys.prefix)
    for raw in package:
        key = normalize_path_text(str(raw))
        found.setdefault(key, "package")
        if _within(key, (environment,)):
            roots.add(environment)
    for raw in protected:
        key = normalize_path_text(str(raw))
        found.setdefault(key, _infer_kind(key))
    for kind, paths in surface.paths.items():
        if kind not in _KINDS:
            continue
        for raw in paths:
            found[normalize_path_text(str(raw))] = kind
    return _Owned(found, tuple(sorted(roots)))


def _within(candidate: str, roots: Iterable[str]) -> bool:
    """True when ``candidate`` is one of ``roots`` or is inside one."""
    for root in roots:
        prefix = root if root.endswith(os.sep) else root + os.sep
        if candidate == root or candidate.startswith(prefix):
            return True
    return False


def _infer_kind(path: str) -> str:
    name = Path(path).name.casefold()
    parts = [part.casefold() for part in Path(path).parts]
    if name in {"config.yaml", ".env"}:
        return "settings"
    if "petasos-enforcement" in name or name.endswith(".jsonl") or name.endswith(".jsonl.rot"):
        return "record"
    if name == "active_profile" or "plugins" in parts:
        return "plugin"
    return "settings"


def _match_path(
    raw: str,
    owned: _Owned,
    env: Mapping[str, str],
    cwd: str,
    *,
    above: bool = False,
    hedge: bool = True,
) -> GuardrailHit | None:
    """``raw`` as a protected path, or as something inside one.

    A relative name is tried against the working directory, then against
    ``HERMES_HOME`` and ``HOME``, because the directory the command really
    runs in is not known. ``hedge=False`` keeps only the working directory.
    ``above`` also matches a directory inside a root that holds a protected
    path, and a wildcard there that covers one, against the working
    directory only.
    """
    if not raw.strip():
        return None
    for variant in _brace_variants(raw):
        candidates = _expand_path(variant, env, cwd)
        for candidate in candidates if hedge else candidates[:1]:
            located = _kind_of(candidate, owned)
            if located is not None:
                return GuardrailHit(*located)
        if not above:
            continue
        kind = _holds(candidates[0], owned)
        if kind is None and _GLOB.search(variant):
            kind = _glob_kind(candidates[0], owned)
        if kind is not None:
            return GuardrailHit(kind, candidates[0])
    return None


def _brace_variants(word: str) -> list[str]:
    """``a/{b,c}`` as ``a/b`` and ``a/c``. A word with no such group is itself."""
    pending = [word]
    done: list[str] = []
    while pending and len(done) + len(pending) <= _MAX_BRACES:
        item = pending.pop()
        match = _BRACES.search(item)
        if match is None:
            done.append(item)
            continue
        for option in match.group(1).split(","):
            pending.append(item[: match.start()] + option + item[match.end() :])
    return done + pending


def _holds(candidate: str, owned: _Owned) -> str | None:
    """The kind of a protected path beneath ``candidate``, a directory inside a root."""
    if not _within(candidate, owned.roots):
        return None
    prefix = candidate if candidate.endswith(os.sep) else candidate + os.sep
    for entry, kind in owned.paths.items():
        if entry.startswith(prefix):
            return kind
    return None


def _glob_kind(pattern: str, owned: _Owned) -> str | None:
    """The kind of a protected path the wildcard covers, holds, or reaches into.

    Compared one path segment at a time. As in a shell, a wildcard does not
    match a name that starts with a dot unless the pattern writes the dot.
    The pattern has to reach a root: ``/home/*`` is not read as the home
    beneath it.
    """
    wanted = Path(pattern).parts
    if not any(_covers(wanted, Path(root).parts, whole=True) for root in owned.roots):
        return None
    for entry, kind in owned.paths.items():
        if _covers(wanted, Path(entry).parts, whole=False):
            return kind
    return None


def _covers(wanted: tuple[str, ...], have: tuple[str, ...], *, whole: bool) -> bool:
    """True when the pattern's segments match the path's, as far as both go.

    ``whole`` also needs the pattern to be at least as long as the path.
    """
    if whole and len(wanted) < len(have):
        return False
    return all(_segment_matches(part, glob) for part, glob in zip(have, wanted, strict=False))


def _segment_matches(part: str, glob: str) -> bool:
    if part.startswith(".") and not glob.startswith("."):
        return False
    return fnmatch.fnmatchcase(part, glob)


def _kind_of(candidate: str, owned: _Owned) -> tuple[str, str] | None:
    direct = owned.paths.get(candidate)
    if direct is not None:
        return direct, candidate
    for entry, kind in owned.paths.items():
        prefix = entry if entry.endswith(os.sep) else entry + os.sep
        if candidate.startswith(prefix):
            return kind, candidate
    return None


def _expand_path(raw: str, env: Mapping[str, str], cwd: str) -> list[str]:
    text = raw.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1]
    text = _expand_vars(text, env)
    if text == "~" or text.startswith("~/"):
        home = env.get("HOME", "")
        if home:
            text = str(Path(home) / text[2:]) if text.startswith("~/") else home
        else:
            text = os.path.expanduser(text)
    elif text.startswith("~"):
        text = os.path.expanduser(text)
    if os.name == "nt":
        # Before the absolute test: Windows reads "/c/x" as a path on the current drive.
        text = text.replace("\\", "/")
        if text.startswith("/") and not text.startswith("//"):
            text = posixpath.normpath(text)
        text = _native_drive(text)
    bases = [text]
    if not os.path.isabs(text):
        roots = [cwd]
        roots.extend(
            root for root in (env.get(key, "") for key in ("HERMES_HOME", "HOME")) if root
        )
        bases = [os.path.join(root, text) for root in roots]
        if os.name == "nt" and not _DRIVE_PREFIX.match(text):
            # A native program and the shell read ``..`` differently, so both
            # readings are candidates. The native ones stay first.
            bases.extend(_bash_join(root, text) for root in roots)
    return [normalize_path_text(item) for item in bases]


def _bash_join(root: str, text: str) -> str:
    """The relative ``text`` under ``root`` as Git Bash joins it.

    There ``..`` climbs out of a drive's directory: from ``/c/work``,
    ``../../c/x`` is ``/c/x``. Windows itself stops at the drive.
    """
    base = root.replace("\\", "/")
    drive = _DRIVE_PREFIX.match(base)
    if drive is not None:
        base = "/" + base[0] + base[2:]
    return _native_drive(posixpath.normpath(posixpath.join(base, text)))


def _expand_vars(text: str, env: Mapping[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1) or match.group(2)
        return env.get(name, match.group(0))

    return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)", replace, text)
