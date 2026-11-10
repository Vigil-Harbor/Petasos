"""Regenerate ``verdicts.json`` from ``corpus.json``.

Run from the repository root::

    .venv/bin/python -m tests.parity.record

Re-running this is only legitimate for a deliberate behaviour change.
Two runs against an unchanged tree write byte-identical output.
"""

from __future__ import annotations

from typing import Any

from tests.parity.adapter import batch, evaluate_tool_call, run_session, scan_text
from tests.parity.load import CORPUS_PATH, PROFILES, VERDICTS_PATH, dump, load_json, text_of


def replay(corpus: dict[str, Any]) -> dict[str, Any]:
    """Replay every corpus case under every built-in profile and no profile."""
    text_cases = corpus["text"]
    tool_cases = corpus["tool"]
    session_cases = corpus["session"]
    if not isinstance(text_cases, list) or not isinstance(tool_cases, list):
        raise TypeError("corpus text and tool sections must be arrays")
    if not isinstance(session_cases, list):
        raise TypeError("corpus session section must be an array")

    text_out: dict[str, dict[str, Any]] = {}
    tool_out: dict[str, dict[str, Any]] = {}
    session_out: dict[str, dict[str, Any]] = {}
    with batch():
        for profile in PROFILES:
            per_text: dict[str, Any] = {}
            for case in text_cases:
                if not isinstance(case, dict) or not isinstance(case.get("id"), str):
                    raise TypeError("text case needs a string id")
                scanned = text_of(case)
                per_text[case["id"]] = {
                    "inbound": scan_text(scanned, direction="inbound", profile=profile),
                    "outbound": scan_text(scanned, direction="outbound", profile=profile),
                }
            text_out[profile] = per_text

            per_tool: dict[str, Any] = {}
            for case in tool_cases:
                if not isinstance(case, dict) or not isinstance(case.get("id"), str):
                    raise TypeError("tool case needs a string id")
                tool = case.get("tool")
                args = case.get("args")
                if not isinstance(tool, str) or not isinstance(args, dict):
                    raise TypeError("tool case needs a string tool and an args object")
                per_tool[case["id"]] = evaluate_tool_call(tool, args, profile=profile)
            tool_out[profile] = per_tool

            per_session: dict[str, Any] = {}
            for case in session_cases:
                if not isinstance(case, dict) or not isinstance(case.get("id"), str):
                    raise TypeError("session case needs a string id")
                steps = case.get("steps")
                if not isinstance(steps, list):
                    raise TypeError("session case needs a steps array")
                per_session[case["id"]] = run_session(steps, profile=profile)
            session_out[profile] = per_session

    return {"session": session_out, "text": text_out, "tool": tool_out}


def main() -> None:
    """Write ``verdicts.json`` next to this file."""
    corpus = load_json(CORPUS_PATH)
    VERDICTS_PATH.write_text(dump(replay(corpus)), encoding="utf-8")


if __name__ == "__main__":
    main()
