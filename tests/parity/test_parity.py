"""Replay the corpus and fail when a verdict differs from the record."""

from __future__ import annotations

import difflib
import json
from typing import Any

from tests.parity.load import (
    ALL_PROFILES,
    CORPUS_PATH,
    VERDICTS_PATH,
    compact_verdicts,
    dump,
    dump_verdicts,
    expand_args,
    expand_value,
    expand_verdicts,
    load_json,
)
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
    recorded = load_json(VERDICTS_PATH)
    assert recorded.get("profiles") == list(ALL_PROFILES)
    expected = expand_verdicts(recorded)
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
    """The committed file is the canonical one-line-per-case serialisation."""
    raw = VERDICTS_PATH.read_text(encoding="utf-8")
    assert raw == dump_verdicts(json.loads(raw))


def test_each_case_occupies_one_line() -> None:
    """A diff of the record can show a changed case without neighbouring noise."""
    raw = VERDICTS_PATH.read_text(encoding="utf-8")
    corpus = load_json(CORPUS_PATH)
    ids = [case["id"] for case in corpus["text"]]
    ids += [case["id"] for case in corpus["tool"]]
    ids += [case["id"] for case in corpus["session"]]
    for case_id in ids:
        needle = f'"{case_id}":'
        hits = [line for line in raw.splitlines() if line.strip().startswith(needle)]
        assert len(hits) == 1, case_id


def test_large_param_cases_bracket_the_scan_cap() -> None:
    """The two large tool arguments sit on either side of the one-million-character cap."""
    corpus = load_json(CORPUS_PATH)
    lengths: list[int] = []
    for case in corpus["tool"]:
        categories = case.get("categories", [])
        if not isinstance(categories, list) or "param-large" not in categories:
            continue
        args = case.get("args")
        if not isinstance(args, dict):
            raise TypeError("large tool case needs an args object")
        expanded = expand_args(args)
        content = expanded.get("content")
        if not isinstance(content, str):
            raise TypeError("large tool case stores its payload on content")
        lengths.append(len(content))
    assert any(length < 1_000_000 for length in lengths)
    assert any(length > 1_000_000 for length in lengths)


def test_tool_and_session_categories_are_populated() -> None:
    """Each guard input class the corpus claims to pin has more than a couple of cases."""
    corpus = load_json(CORPUS_PATH)
    counts: dict[str, int] = {}
    for kind in ("tool", "session"):
        cases = corpus[kind]
        if not isinstance(cases, list):
            raise TypeError(kind)
        for case in cases:
            categories = case.get("categories", [])
            if not isinstance(categories, list):
                raise TypeError("categories must be a list")
            for category in categories:
                if not isinstance(category, str):
                    raise TypeError("category must be a string")
                counts[category] = counts.get(category, 0) + 1
    required = {
        "name-case": 3,
        "name-camel": 3,
        "name-suffix": 3,
        "name-homoglyph": 3,
        "name-zerowidth": 3,
        "name-mcp": 3,
        "name-empty": 3,
        "name-unknown": 3,
        "name-alias": 3,
        "class-readonly": 3,
        "class-dangerous": 3,
        "class-ingestion": 3,
        "class-delegate": 3,
        "class-egress": 3,
        "param-nested": 3,
        "param-list": 3,
        "param-key": 3,
        "param-nonstring": 3,
        "param-large": 2,
        "param-encoded": 3,
        "param-injection": 3,
        "param-command": 3,
        "param-encoding": 3,
        "param-structural": 3,
        "selfmod-exact": 3,
        "selfmod-ref": 3,
        "selfmod-near": 3,
        "selfmod-relative": 3,
        "selfmod-tilde": 3,
        "selfmod-env": 3,
        "selfmod-traversal": 3,
        "selfmod-symlink": 3,
        "fanout-base": 1,
        "fanout-tier": 1,
        "fanout-name": 3,
        "tier-tool": 3,
        "tier-text": 1,
        "tier-mix": 1,
        "tier3-harmless": 1,
    }
    missing = {
        name: counts.get(name, 0)
        for name, floor in required.items()
        if counts.get(name, 0) < floor
    }
    assert not missing, missing


def test_compact_round_trip() -> None:
    """Expanding a compact document restores every profile, including matches."""
    verdict = {"allowed": True, "tier": "none"}
    other = {"allowed": False, "tier": "tier2"}
    expanded: dict[str, Any] = {
        "session": {name: {"s": verdict} for name in ALL_PROFILES},
        "text": {name: {"t": {"inbound": verdict}} for name in ALL_PROFILES},
        "tool": {name: {"g": verdict} for name in ALL_PROFILES},
    }
    expanded["tool"]["admin"] = {"g": other}
    expanded["tool"]["plugin:admin"] = {"g": other}
    compact = compact_verdicts(expanded)
    assert "differs" in compact["tool"]["g"]
    assert expand_verdicts(compact) == expanded
    # expand_value is part of the corpus contract; a plain value survives it.
    assert expand_value("notes") == "notes"
