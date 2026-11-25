"""Match a command's words against a command rule."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from petasos.guard.mutations import _NAME_END

if TYPE_CHECKING:
    from petasos.guard.surface import CommandRule

# Words that name every plugin.
_ALL_NAMES = frozenset({"*", "--all", "-a", "all"})


def _rule_matches(argv: tuple[str, ...], rule: CommandRule) -> bool:
    """True when ``argv`` matches ``rule``. The caller has matched the program."""
    if len(argv) < len(rule.words):
        return False
    for index in range(1, len(rule.words)):
        if argv[index].casefold() != rule.words[index].casefold():
            return False
    if rule.requires_flag is not None and not any(
        word == rule.requires_flag or word.startswith(rule.requires_flag + "=") for word in argv
    ):
        return False
    if rule.unless_flags and any(flag in argv for flag in rule.unless_flags):
        return False
    rest = argv[len(rule.words) :]
    positionals = [word for word in rest if not word.startswith("-")]
    if rule.no_positionals and _targets(positionals):
        return False
    if rule.tail is not None:
        # Hermes splits a key at each ``.``: ``approvals_backup`` is another key.
        key = positionals[0].casefold() if positionals else ""
        tail = rule.tail.casefold()
        if key != tail and not key.startswith(tail + "."):
            return False
    if rule.one_of:
        allowed = {item.casefold() for item in rule.one_of}
        if not positionals or positionals[0].casefold() not in allowed:
            return False
    if rule.name is None:
        return True
    if any(_names_plugin(word, rule.name) for word in rest):
        return True
    return rule.bare and not _targets(positionals)


def _targets(positionals: list[str]) -> list[str]:
    """The positionals before the first word that starts with ``#``.

    The parser does not model comments and keeps every word, so such a word
    may begin a comment that holds the rest. Neither it nor what follows is
    taken as naming a target. This only decides whether a command with no
    target matches; a word anywhere that names the plugin still matches.
    """
    for index, word in enumerate(positionals):
        if word.startswith("#"):
            return positionals[:index]
    return positionals


def _names_plugin(word: str, name: str) -> bool:
    """True when ``word`` names the plugin, everything, or a source for it.

    A version, an extra or a reference after the name still names it
    (``petasos==0.1``, ``petasos[all]``, ``.../petasos.git@main``), and so
    does a built file for it (``petasos-0.1-py3-none-any.whl``).
    """
    folded = word.casefold()
    wanted = name.casefold()
    if folded in _ALL_NAMES:
        return True
    if "#" in word and word.rsplit("#", 1)[-1].strip("/").casefold() == wanted:
        return True
    for piece in (folded, folded.rstrip("/").rsplit("/", 1)[-1], *_repository(folded)):
        head = _NAME_END.split(piece, maxsplit=1)[0].removesuffix(".git")
        if head == wanted or re.match(re.escape(wanted) + r"-\d", head):
            return True
    return False


def _repository(source: str) -> tuple[str, str]:
    """The last part of a source's repository path, with its revision set aside.

    A revision follows the repository after ``@`` or ``#`` and may itself
    hold ``/`` (``.../petasos@feature/x``). The path starts after a URL's
    host or an scp-style ``host:``, so a user before the host is not taken
    for a revision. Both the first ``@`` or ``#`` in the path and pip's
    reading, the fragment and then the last ``@``, are tried.
    """
    scheme = source.find("://")
    if scheme >= 0:
        slash = source.find("/", scheme + 3)
        path = source[slash:] if slash >= 0 else ""
    else:
        colon, slash = source.find(":"), source.find("/")
        path = source[colon + 1 :] if colon >= 0 and (slash < 0 or colon < slash) else source
    first = re.split(r"[@#]", path, maxsplit=1)[0]
    last = path.split("#", 1)[0].rsplit("@", 1)[0]
    return first.rstrip("/").rsplit("/", 1)[-1], last.rstrip("/").rsplit("/", 1)[-1]
