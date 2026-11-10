"""Scanner, approval, and suggestion lines for the doctor.

Suggestions are written for a Hermes home. The registry's own wording stays
host-agnostic and is not shown here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from petasos.hermes.doctor_model import Check, Status
from petasos.hermes.doctor_support import join_reasons, paths_summary
from petasos.hermes.plugin import protected_paths
from petasos.scanners.registry import REGISTRY, BuildContext, compose, fix_for

if TYPE_CHECKING:
    from petasos.config.layers import Resolved
    from petasos.scanners.registry import Composition, ScannerSpec, ScannerStatus

_SCANNER_JOB = {
    "presidio": "personal information",
    "prompt_guard": "hidden instructions, with a model",
    "semgrep": "risky code",
}
_PII_ROLES = frozenset({"support", "admin"})


def _add_command(scanner_id: str) -> str:
    return f"petasos scanner add {scanner_id}"


def scanner_report(
    resolved: Resolved | None,
    *,
    registry: tuple[ScannerSpec, ...] = REGISTRY,
) -> tuple[tuple[Check, ...], tuple[str, ...], tuple[dict[str, object], ...]]:
    """Scanner checks, Hermes-worded suggestions, and the status rows.

    One composition feeds all three, so the text, the JSON, and the dashboard
    cannot disagree about what is running.
    """
    if resolved is None:
        return (
            (
                Check(
                    id="scanners",
                    status="info",
                    summary="The checks were not listed, because the settings could not be used.",
                ),
            ),
            (),
            (_syntactic_row(),),
        )
    try:
        composition = compose(resolved.config, BuildContext(), registry=registry)
    except Exception as exc:
        row: dict[str, object] = {
            "id": "scanners",
            "label": "Optional scanners",
            "state": "unavailable",
            "reason": "The scanners could not be checked.",
            "fix": "Try again. If it keeps happening, the detail is in the log.",
            "extra": None,
        }
        none: tuple[str, ...] = ()
        return (
            (
                Check(
                    id="scanners",
                    status="fail",
                    summary="The checks could not be built.",
                    meaning=str(exc) or type(exc).__name__,
                    next_step="Run petasos doctor again after the message above is fixed.",
                ),
            ),
            none,
            (_syntactic_row(), row),
        )
    checks = [
        Check(
            id="scanner_builtin",
            status="ok",
            summary=("The built-in text checks are running. They look for hidden instructions."),
        )
    ]
    rows: list[dict[str, object]] = [_syntactic_row()]
    for status in composition.statuses:
        kind, summary, meaning, step = _scanner_line(status)
        checks.append(
            Check(
                id=f"scanner_{status.id}",
                status=kind,
                summary=summary,
                meaning=meaning,
                next_step=step,
            )
        )
        rows.append(_scanner_row(status))
    return tuple(checks), hermes_suggestions(composition, resolved.settings.role), tuple(rows)


def approval_check(resolved: Resolved | None, *, hermes_available: bool) -> Check:
    """Whether a dangerous tool call is blocked, or handed to Hermes to ask."""
    if resolved is None:
        return Check(
            id="approval",
            status="info",
            summary="Dangerous tool calls were not checked. The settings could not be used.",
        )
    posture = resolved.config.tools.dangerous_posture
    if posture != "approve":
        return Check(
            id="approval",
            status="ok",
            summary="Dangerous tool calls are blocked. Hermes is not asked to approve them.",
        )
    if not hermes_available:
        return Check(
            id="approval",
            status="warn",
            summary="Dangerous tool calls are handed to Hermes for a person to confirm.",
            meaning=(
                "This Python cannot see Hermes, so it cannot tell whether Hermes "
                "would ask, refuse, or allow the call without asking."
            ),
            next_step="Run petasos doctor with the same Python Hermes uses.",
        )
    from petasos.hermes.host import approval_grant

    grant = approval_grant()
    reasons: list[str] = []
    if grant.mode_off:
        reasons.append("approvals are turned off")
    if grant.yolo:
        reasons.append("confirmation is switched off for this process")
    if grant.context:
        reasons.append("this is a scheduled or unattended run that approves on its own")
    if reasons:
        because = join_reasons(reasons)
        return Check(
            id="approval",
            status="warn",
            summary=(
                "You asked for a person to confirm dangerous tool calls. "
                f"Hermes would allow them without asking, because {because}."
            ),
            meaning="A person who expects to be asked will not be asked.",
            next_step=(
                "Turn Hermes approvals back on, and turn off unattended approval, "
                "or change the job so dangerous tool calls are blocked."
            ),
        )
    return Check(
        id="approval",
        status="ok",
        summary=(
            "Dangerous tool calls are handed to Hermes. "
            "Hermes would ask a person. If nobody is there to answer, Hermes refuses the call."
        ),
    )


def guardrail_check(paths: tuple[str, ...]) -> Check:
    """The self-protection line. The path list itself is not part of the sentence."""
    return Check(
        id="guardrail",
        status="info",
        summary=paths_summary(paths),
        meaning=(
            "Whether a change needs a person's approval, is refused, "
            "or is locked by an administrator is not reported yet."
        ),
    )


def current_paths() -> tuple[str, ...]:
    """Protected paths for the home the caller has already selected."""
    try:
        return tuple(sorted(protected_paths()))
    except Exception:
        return ()


def hermes_suggestions(composition: Composition, role: str | None) -> tuple[str, ...]:
    """What is missing, in the same plain register as the rest of the report.

    The built-in checks already look for hidden instructions. The prompt-guard
    line says the model is missing, and how to add it where Hermes will see it.
    """
    lines: list[str] = []
    if not _capability_active(composition, "injection"):
        lines.append(
            "The extra model that looks for hidden instructions is not installed. "
            "The built-in checks still run. "
            "Add it: " + _add_command("prompt_guard")
        )
    if role in _PII_ROLES and not _capability_active(composition, "pii"):
        lines.append(
            f"The {role} job has no extra check for personal information. "
            "The built-in checks do not look for it. "
            "Add it: " + _add_command("presidio")
        )
    return tuple(lines)


def _capability_active(composition: Composition, capability: str) -> bool:
    return any(
        status.state == "active" and capability in status.detects
        for status in composition.statuses
    )


def _scanner_line(status: ScannerStatus) -> tuple[Status, str, str, str]:
    job = _SCANNER_JOB.get(status.id, status.label)
    if status.state == "active":
        return "ok", f"{status.label} is running. It checks for {job}.", "", ""
    if status.state == "off":
        return "ok", f"{status.label} is turned off. It would check for {job}.", "", ""
    if status.state == "not_installed":
        return (
            "ok",
            f"{status.label} is not installed, so it is not part of the checks.",
            f"It would check for {job}. The built-in checks still run.",
            "",
        )
    if status.missing:
        return (
            "warn",
            f"{status.label} is turned on but not installed.",
            f"It would check for {job}. A check that is turned on and cannot run "
            "counts as failed, so tool calls are held back until it is added or turned off.",
            f"Add it: {_add_command(status.id)}. Or turn it off in Settings.",
        )
    reason = status.reason or "no reason was reported"
    return (
        "warn",
        f"{status.label} is installed but cannot be used.",
        reason,
        "Fix that check, or turn it off, then run petasos doctor again.",
    )


def _syntactic_row() -> dict[str, object]:
    return {
        "id": "syntactic",
        "label": "Basic checks",
        "state": "active",
        "reason": None,
        "fix": None,
        "extra": None,
    }


def _scanner_row(status: ScannerStatus) -> dict[str, object]:
    return {
        "id": status.id,
        "label": status.label,
        "state": status.state,
        "reason": _hermes_reason(status),
        "fix": _hermes_fix(status),
        "extra": status.extra,
    }


def _hermes_reason(status: ScannerStatus) -> str | None:
    # The registry's own reason for a missing package names pip, which is the
    # wrong instruction inside Hermes. The fix carries the right one.
    if status.missing:
        return f"{status.label} is not installed."
    return status.reason


def _hermes_fix(status: ScannerStatus) -> str | None:
    text = fix_for(status)
    if text is None:
        return None
    if status.reason == "semgrep.host_lifecycle_unavailable":
        return (
            "Semgrep needs Hermes to run it, and this process cannot. "
            "Turn Semgrep off, or use it where Hermes is running the agent."
        )
    if status.extra is not None and "pip install" in text:
        return _add_command(status.id)
    return text
