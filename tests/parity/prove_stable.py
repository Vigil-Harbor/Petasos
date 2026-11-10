"""Show that compacting the record did not change an existing case's verdict.

The old file is the expanded document (kind, profile, case id). The new file
is the compact document next to this module. Comparison is by case id and
profile, for the cases and profiles the old file already had.

Run from the repository root::

    git show <baseline>:tests/parity/verdicts.json > /tmp/old-verdicts.json
    .venv/bin/python -m tests.parity.prove_stable /tmp/old-verdicts.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from tests.parity.load import VERDICTS_PATH, expand_verdicts


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"{path} must be a JSON object")
    return data


def _legacy_profiles(document: dict[str, Any]) -> list[str]:
    text = document["text"]
    if not isinstance(text, dict) or not text:
        raise TypeError("old verdicts have no text section")
    return sorted(text)


def compare(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """Return mismatch descriptions. An empty list means the old verdicts survived."""
    expanded = expand_verdicts(new)
    mismatches: list[str] = []
    for kind in ("text", "tool", "session"):
        old_kind = old[kind]
        if not isinstance(old_kind, dict):
            raise TypeError(f"old {kind} section must be an object")
        for profile, cases in old_kind.items():
            if not isinstance(cases, dict):
                raise TypeError(f"old {kind}/{profile} must be an object")
            new_profile = expanded[kind].get(profile)
            if not isinstance(new_profile, dict):
                mismatches.append(f"{kind}/{profile}: missing from the compact record")
                continue
            for case_id, verdict in cases.items():
                if case_id not in new_profile:
                    mismatches.append(f"{kind}/{profile}/{case_id}: dropped")
                    continue
                if new_profile[case_id] != verdict:
                    mismatches.append(f"{kind}/{profile}/{case_id}: verdict changed")
    return mismatches


def main() -> None:
    """Compare a legacy verdict file to the compact record and exit non-zero on a change."""
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m tests.parity.prove_stable OLD_VERDICTS.json")
    old = _load(Path(sys.argv[1]))
    new = _load(VERDICTS_PATH)
    mismatches = compare(old, new)
    profiles = _legacy_profiles(old)
    counts = {kind: len(old[kind][profiles[0]]) for kind in ("text", "tool", "session")}
    if mismatches:
        sys.stdout.write("\n".join(mismatches[:30]) + "\n")
        raise SystemExit(f"{len(mismatches)} verdicts changed")
    sys.stdout.write(
        "unchanged "
        + " ".join(f"{kind}={count}" for kind, count in counts.items())
        + f" profiles={len(profiles)}\n"
    )


if __name__ == "__main__":
    main()
