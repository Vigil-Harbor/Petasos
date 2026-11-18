"""Text and JSON views of one doctor report.

Both views read the report. Neither invents a fact the other does not have.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from petasos.hermes.doctor_model import Report, Status

_MARK = {"ok": "[ok]", "warn": "[~~]", "fail": "[!!]", "info": "[??]"}
_COLOUR = {"ok": "32", "warn": "33", "fail": "31", "info": "36"}


def report_payload(report: Report) -> dict[str, object]:
    """The JSON object. The text view prints the same sentences."""
    return {
        "verdict": report.verdict,
        "exit_code": report.exit_code,
        "summary": headline(report),
        "home": str(report.home),
        "home_reason": report.home_reason,
        "checks": [
            {
                "id": check.id,
                "status": check.status,
                "summary": check.summary,
                "meaning": check.meaning,
                "next_step": check.next_step,
                "detail": list(check.detail),
            }
            for check in report.checks
        ],
        "suggestions": list(report.suggestions),
        "protected_paths": list(report.protected_paths),
        "paths_summary": report.paths_summary,
        "detail": report.detail,
    }


def render_json(report: Report) -> str:
    """The report as a JSON object, including the path list."""
    return json.dumps(report_payload(report), indent=2, sort_keys=True) + "\n"


def render_text(report: Report, *, verbose: bool, color: bool) -> str:
    """The report a person reads. Colour is applied only to the marks.

    The protected-path list is printed only when ``verbose`` is true. The
    default output keeps ``paths_summary``.
    """
    lines = [headline(report), f"Home: {report.home} ({report.home_reason})", ""]
    for check in report.checks:
        lines.append(f"{_paint(_MARK[check.status], check.status, color=color)}  {check.summary}")
        if check.meaning:
            for extra in check.meaning.splitlines():
                lines.append(f"      {extra}")
        if verbose:
            for extra in check.detail:
                lines.append(f"      {extra}")
        if verbose and check.id == "guardrail":
            if report.protected_paths:
                lines.append("      Paths protected today:")
                for path in report.protected_paths:
                    lines.append(f"      - {path}")
            else:
                lines.append("      No protected paths could be listed.")
    if report.suggestions:
        lines.append("")
        lines.append("Suggestions")
        for suggestion in report.suggestions:
            lines.append(f"- {suggestion}")
    problems = [
        check for check in report.checks if check.status in {"warn", "fail"} and check.next_step
    ]
    if problems:
        lines.append("")
        lines.append("What to do")
        for check in problems:
            lines.append(f"- {check.summary}")
            if check.meaning:
                lines.append(f"  {check.meaning}")
            lines.append(f"  Next: {check.next_step}")
    if verbose:
        lines.append("")
        lines.extend(_verbose_lines(report))
    return "\n".join(lines) + "\n"


def headline(report: Report) -> str:
    """The first line, from the verdict."""
    if report.verdict == "protected":
        return "Protected. Petasos is checking tool calls for this agent."
    if report.verdict == "protected_with_warnings":
        return (
            "Protected, with warnings. Petasos is checking tool calls, "
            "and something below needs a look."
        )
    return "Not protected. Petasos is not checking tool calls for this agent."


def _verbose_lines(report: Report) -> list[str]:
    lines = ["Detail"]
    detail = report.detail
    for key in ("petasos_version", "python", "python_path", "hermes_version", "minimum_hermes"):
        lines.append(f"  {key}: {detail.get(key)}")
    for key in ("plugin_dir", "config_path", "env_path"):
        lines.append(f"  {key}: {detail.get(key)}")
    resolved = detail.get("resolved")
    if isinstance(resolved, list) and resolved:
        lines.append("  Resolved settings (path, value, where it came from):")
        for row in resolved:
            if not isinstance(row, dict):
                continue
            lines.append(
                "    "
                f"{row.get('path')} = {json.dumps(row.get('value'), default=str)} "
                f"({row.get('origin')})"
            )
    return lines


def _paint(mark: str, status: Status, *, color: bool) -> str:
    if not color:
        return mark
    code = _COLOUR[status]
    return f"\033[{code}m{mark}\033[0m"
