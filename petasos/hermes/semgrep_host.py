"""Whether Hermes can run Semgrep, and the sentences a person reads about that.

False until a later package runs the engine. Callers in the adapter read
:func:`semgrep_can_run` and do not decide on their own. The library still
accepts ``on``. A hand-written Required keeps failing closed.
"""

from __future__ import annotations

SEMGREP_ENABLED = "scanners.semgrep.enabled"

SEMGREP_CANNOT_RUN = "Semgrep cannot run inside Hermes yet."

# ``auto`` asks for the check. Inside Hermes the check never runs, and under
# the usual fail mode that blocks tool calls that change things.
SEMGREP_AUTO_LABEL = "Not used, and blocks changes"

SEMGREP_ON_LABEL = "Required (cannot run yet)"

SEMGREP_OFF_COMMAND = "petasos config set scanners.semgrep.enabled off"

SEMGREP_SET_ON_REFUSED = "Semgrep cannot run inside Hermes yet, so it cannot be set to Required."

SEMGREP_LEFT_ON_REFUSED = (
    "Semgrep is set to Required and cannot run inside Hermes yet, so this was not saved. "
    f"Set it to Never with: {SEMGREP_OFF_COMMAND}"
)

SEMGREP_REQUIRED_BLOCKING = (
    "It is set to Required, so Petasos is blocking tool calls that change things. "
    "Read-only tool calls still run."
)

SEMGREP_AUTO_BLOCKING = (
    "Semgrep is not used inside Hermes. It is set to run when installed, and tool "
    "calls that change things are blocked. Read-only tool calls still run."
)

SEMGREP_ADD_REFUSED = (
    "Semgrep cannot run inside Hermes yet, so it was not added. It would not check any code."
)


def semgrep_can_run() -> bool:
    """False until Hermes runs the Semgrep engine."""
    return False


def semgrep_enabled(config: object) -> str | None:
    """``auto``, ``on``, or ``off`` from a resolved config, or None."""
    scanners = getattr(config, "scanners", None)
    section = getattr(scanners, "semgrep", None)
    value = getattr(section, "enabled", None)
    if value in ("auto", "on", "off"):
        return str(value)
    return None


def save_refusal(before: str | None, after: str | None) -> str | None:
    """Why a document that would leave Semgrep Required cannot be saved.

    None when the result is not Required, or when Hermes can run Semgrep.
    Setting it to Required and leaving an existing Required in place while
    something else changes are different sentences. The second says how to
    turn it off, so a form does not write a document the save would refuse.
    """
    if semgrep_can_run() or after != "on":
        return None
    if before == "on":
        return SEMGREP_LEFT_ON_REFUSED
    return SEMGREP_SET_ON_REFUSED
