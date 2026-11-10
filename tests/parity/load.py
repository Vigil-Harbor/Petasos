"""Load the parity corpus and serialise verdict documents.

The corpus is plain JSON. A text case is either a ``text`` string or a
``repeat`` pair ``[fragment, count]`` used for the one oversized payload,
which is expanded at load time and is not stored expanded.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

HERE = Path(__file__).resolve().parent
CORPUS_PATH = HERE / "corpus.json"
VERDICTS_PATH = HERE / "verdicts.json"

# ``none`` is the unbound profile. The other five are the built-in names.
# ``plugin:<name>`` binds the pipeline to that profile and builds the guard
# without one, which is how the reference plugin constructs ``ToolCallGuard``.
# Only admin and research set tier thresholds, so only those two change a
# guard verdict relative to passing the profile through.
PROFILES: tuple[str, ...] = (
    "none",
    "general",
    "code_generation",
    "research",
    "customer_service",
    "admin",
)
PLUGIN_PROFILES: tuple[str, ...] = ("plugin:admin", "plugin:research")
ALL_PROFILES: tuple[str, ...] = PROFILES + PLUGIN_PROFILES

_KINDS: tuple[str, ...] = ("session", "text", "tool")


def load_json(path: Path) -> dict[str, Any]:
    """Read a JSON object from ``path``."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"{path.name} must be a JSON object")
    return cast("dict[str, Any]", data)


def text_of(case: dict[str, Any]) -> str:
    """Return the text a corpus case scans."""
    repeat = case.get("repeat")
    if repeat is not None:
        if (
            not isinstance(repeat, list)
            or len(repeat) != 2
            or not isinstance(repeat[0], str)
            or not isinstance(repeat[1], int)
        ):
            raise TypeError("repeat must be a [string, int] pair")
        return repeat[0] * repeat[1]
    text = case.get("text")
    if not isinstance(text, str):
        raise TypeError("text case needs a string 'text' or a 'repeat' pair")
    return text


def dump(payload: object) -> str:
    """Serialise ``payload`` so two calls return the same bytes."""
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def expand_value(value: Any) -> Any:
    """Expand a compact corpus node. Ordinary JSON values pass through.

    A one-key object ``{"$repeat": [text, count]}`` becomes that text repeated.
    ``$prefix`` and ``$suffix`` are optional. ``{"$join": [parts]}`` concatenates
    parts that expand to strings. ``{"$bytes": text}`` becomes UTF-8 bytes.
    ``{"$nest": n}`` and ``{"$listnest": n}`` build ``n`` wrappers around ``$leaf``.
    """
    if isinstance(value, dict):
        keys = set(value)
        if "$repeat" in keys and keys <= {"$repeat", "$prefix", "$suffix"}:
            return _expand_repeat(value)
        if keys == {"$join"}:
            return _expand_join(value["$join"])
        if keys == {"$bytes"}:
            raw = value["$bytes"]
            if not isinstance(raw, str):
                raise TypeError("$bytes must be a string")
            return raw.encode("utf-8")
        if "$nest" in keys and keys <= {"$nest", "$leaf"}:
            return _expand_wrapped(value["$nest"], value.get("$leaf", "x"), wrap="dict")
        if "$listnest" in keys and keys <= {"$listnest", "$leaf"}:
            return _expand_wrapped(value["$listnest"], value.get("$leaf", "x"), wrap="list")
        return {key: expand_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [expand_value(item) for item in value]
    return value


def expand_args(args: dict[str, Any]) -> dict[str, Any]:
    """Return tool arguments with compact nodes expanded. Does not mutate ``args``."""
    expanded = expand_value(args)
    if not isinstance(expanded, dict):
        raise TypeError("tool args must expand to an object")
    return expanded


def _expand_repeat(value: dict[str, Any]) -> str:
    pair = value["$repeat"]
    prefix = value.get("$prefix", "")
    suffix = value.get("$suffix", "")
    if (
        not isinstance(pair, list)
        or len(pair) != 2
        or not isinstance(pair[0], str)
        or not isinstance(pair[1], int)
        or isinstance(pair[1], bool)
        or not isinstance(prefix, str)
        or not isinstance(suffix, str)
    ):
        raise TypeError("$repeat must be a [string, int] pair with string prefix and suffix")
    return f"{prefix}{pair[0] * pair[1]}{suffix}"


def _expand_join(parts: object) -> str:
    if not isinstance(parts, list):
        raise TypeError("$join must be a list")
    chunks: list[str] = []
    for part in parts:
        expanded = expand_value(part)
        if not isinstance(expanded, str):
            raise TypeError("$join parts must expand to strings")
        chunks.append(expanded)
    return "".join(chunks)


def _expand_wrapped(depth: object, leaf: object, *, wrap: str) -> Any:
    if not isinstance(depth, int) or isinstance(depth, bool) or depth < 0:
        raise TypeError("nest depth must be a non-negative int")
    node: Any = leaf
    for _ in range(depth):
        node = {"k": node} if wrap == "dict" else [node]
    return node


def _blob(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _majority(by_profile: dict[str, Any], profiles: tuple[str, ...]) -> tuple[str, Any]:
    """Return the profile name and verdict shared by the most profiles.

    Ties break toward the earliest name in ``profiles``.
    """
    groups: dict[str, list[str]] = {}
    blobs: dict[str, Any] = {}
    for name in profiles:
        blob = _blob(by_profile[name])
        groups.setdefault(blob, []).append(name)
        blobs[blob] = by_profile[name]

    def rank(blob: str) -> tuple[int, int]:
        names = groups[blob]
        return (-len(names), profiles.index(names[0]))

    best = min(groups, key=rank)
    return groups[best][0], blobs[best]


def compact_verdicts(
    expanded: dict[str, Any], profiles: tuple[str, ...] = ALL_PROFILES
) -> dict[str, Any]:
    """Store each case once, plus only the profiles whose verdict differs.

    ``expanded`` is ``kind -> profile -> case id -> verdict``, the shape
    ``replay`` produces. The base verdict is the one shared by the most
    profiles. ``base`` names one profile that has it, so a diff shows which
    arrangement the stored verdict came from.
    """
    document: dict[str, Any] = {"profiles": list(profiles)}
    for kind in _KINDS:
        block = expanded[kind]
        if not isinstance(block, dict):
            raise TypeError(f"{kind} section must be an object")
        cases: dict[str, Any] = {}
        ids: set[str] = set()
        for profile in profiles:
            profile_block = block[profile]
            if not isinstance(profile_block, dict):
                raise TypeError(f"{kind}/{profile} must be an object")
            ids.update(profile_block)
        for case_id in sorted(ids):
            by_profile = {profile: block[profile][case_id] for profile in profiles}
            base_name, verdict = _majority(by_profile, profiles)
            differs = {
                profile: by_profile[profile]
                for profile in profiles
                if profile != base_name and by_profile[profile] != verdict
            }
            row: dict[str, Any] = {"base": base_name, "verdict": verdict}
            if differs:
                row["differs"] = differs
            cases[case_id] = row
        document[kind] = cases
    return document


def expand_verdicts(document: dict[str, Any]) -> dict[str, Any]:
    """Expand a compact verdict document to ``kind -> profile -> case id``."""
    profiles = document.get("profiles")
    if not isinstance(profiles, list) or not all(isinstance(name, str) for name in profiles):
        raise TypeError("verdicts profiles must be a list of strings")
    expanded: dict[str, Any] = {}
    for kind in _KINDS:
        block = document.get(kind)
        if not isinstance(block, dict):
            raise TypeError(f"{kind} section must be an object")
        per_profile: dict[str, dict[str, Any]] = {name: {} for name in profiles}
        for case_id in sorted(block):
            row = block[case_id]
            if (
                not isinstance(row, dict)
                or "verdict" not in row
                or not isinstance(row.get("base"), str)
            ):
                raise TypeError(f"{kind}/{case_id} must have base and verdict")
            differs = row.get("differs", {})
            if not isinstance(differs, dict):
                raise TypeError(f"{kind}/{case_id} differs must be an object")
            if row["base"] in differs:
                raise ValueError(f"{kind}/{case_id} lists its base profile in differs")
            for name in profiles:
                per_profile[name][case_id] = differs[name] if name in differs else row["verdict"]
        expanded[kind] = per_profile
    return expanded


def dump_verdicts(document: dict[str, Any]) -> str:
    """Serialise a compact verdict document, one line per case, ids sorted."""
    profiles = document.get("profiles")
    if not isinstance(profiles, list):
        raise TypeError("verdicts profiles must be a list")
    lines = ["{", '  "profiles": ' + json.dumps(profiles, ensure_ascii=False) + ","]
    sections: list[str] = []
    for kind in _KINDS:
        rows = document.get(kind)
        if not isinstance(rows, dict):
            raise TypeError(f"{kind} section must be an object")
        body: list[str] = []
        ids = sorted(rows)
        for index, case_id in enumerate(ids):
            comma = "," if index < len(ids) - 1 else ""
            payload = json.dumps(
                rows[case_id], sort_keys=True, ensure_ascii=False, separators=(",", ":")
            )
            body.append(f"    {json.dumps(case_id, ensure_ascii=False)}: {payload}{comma}")
        sections.append(f'  "{kind}": {{\n' + "\n".join(body) + "\n  }")
    lines.append(",\n".join(sections))
    lines.append("}")
    return "\n".join(lines) + "\n"
