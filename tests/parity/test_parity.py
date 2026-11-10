"""Replay the corpus and fail when a verdict differs from the record."""

from __future__ import annotations

import difflib
import json
from typing import Any

from tests.parity.load import CORPUS_PATH, VERDICTS_PATH, dump, load_json
from tests.parity.record import replay

# Every syntactic rule, plus the two self-modification rules the guard emits.
# The record has to contain each of these at least once.
_PINNED_RULES: frozenset[str] = frozenset(
    {
        "petasos.selfmod.config_ref",
        "petasos.selfmod.config_write",
        "petasos.syntactic.command.alias-escape",
        "petasos.syntactic.command.decode-exec",
        "petasos.syntactic.command.destructive-recursive",
        "petasos.syntactic.command.fetch-exec",
        "petasos.syntactic.command.pipe-to-shell",
        "petasos.syntactic.encoding.base64-in-text",
        "petasos.syntactic.encoding.homoglyph-substitution",
        "petasos.syntactic.encoding.invisible-chars",
        "petasos.syntactic.encoding.rtl-override",
        "petasos.syntactic.injection.agent-directed-fetch",
        "petasos.syntactic.injection.disregard",
        "petasos.syntactic.injection.ignore-all",
        "petasos.syntactic.injection.ignore-previous",
        "petasos.syntactic.injection.inst-delimiter",
        "petasos.syntactic.injection.new-instructions",
        "petasos.syntactic.injection.role-switch-capability",
        "petasos.syntactic.injection.role-switch-only",
        "petasos.syntactic.injection.system-override",
        "petasos.syntactic.injection.system-prefix",
        "petasos.syntactic.injection.you-are-now",
        "petasos.syntactic.structural.binary-content",
        "petasos.syntactic.structural.excessive-depth",
        "petasos.syntactic.structural.oversized-payload",
    }
)

_MAX_DIFFS = 12


def _walk_rules(node: object, found: set[str]) -> None:
    if isinstance(node, dict):
        for value in node.values():
            _walk_rules(value, found)
        return
    if isinstance(node, list):
        if len(node) == 2 and isinstance(node[0], str) and node[0].startswith("petasos."):
            found.add(node[0])
        for item in node:
            _walk_rules(item, found)


def _case_diff(expected: object, actual: object) -> str:
    expected_lines = dump(expected).splitlines()
    actual_lines = dump(actual).splitlines()
    return "\n".join(
        difflib.unified_diff(
            expected_lines,
            actual_lines,
            fromfile="recorded",
            tofile="actual",
            lineterm="",
        )
    )


def _collect_diffs(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    diffs: list[str] = []
    for kind in ("text", "tool", "session"):
        expected_kind = expected.get(kind)
        actual_kind = actual.get(kind)
        if not isinstance(expected_kind, dict) or not isinstance(actual_kind, dict):
            diffs.append(f"{kind}: section missing or not an object")
            continue
        for profile in sorted(set(expected_kind) | set(actual_kind)):
            expected_profile = expected_kind.get(profile)
            actual_profile = actual_kind.get(profile)
            if expected_profile == actual_profile:
                continue
            if not isinstance(expected_profile, dict) or not isinstance(actual_profile, dict):
                diffs.append(f"{kind}/{profile}: profile block missing or not an object")
                continue
            for case_id in sorted(set(expected_profile) | set(actual_profile)):
                if expected_profile.get(case_id) == actual_profile.get(case_id):
                    continue
                diffs.append(
                    f"{kind} profile={profile} id={case_id}\n"
                    + _case_diff(expected_profile.get(case_id), actual_profile.get(case_id))
                )
                if len(diffs) >= _MAX_DIFFS:
                    return diffs
    return diffs


def test_verdicts_match_record() -> None:
    """The live syntactic verdicts equal the committed record."""
    corpus = load_json(CORPUS_PATH)
    expected = load_json(VERDICTS_PATH)
    actual = replay(corpus)
    diffs = _collect_diffs(expected, actual)
    if diffs:
        extra = ""
        if len(diffs) >= _MAX_DIFFS:
            extra = f"\n(stopped after {_MAX_DIFFS} differing cases)"
        raise AssertionError(
            "parity verdicts differ from tests/parity/verdicts.json\n\n"
            + "\n\n".join(diffs)
            + extra
        )


def test_record_covers_every_syntactic_rule() -> None:
    """Each pinned rule id appears in at least one recorded verdict."""
    recorded = load_json(VERDICTS_PATH)
    found: set[str] = set()
    _walk_rules(recorded, found)
    missing = sorted(_PINNED_RULES - found)
    assert not missing, "recorded verdicts never mention: " + ", ".join(missing)


def test_record_json_is_canonical() -> None:
    """The committed file is the canonical serialisation of its own object."""
    raw = VERDICTS_PATH.read_text(encoding="utf-8")
    assert raw == dump(json.loads(raw))
