"""Compare Petasos's ask predicate with Hermes's command gate.

Run this file with the sandbox interpreter, through ``bin/with-sandbox``.
Every command is a string passed to a function. Nothing is executed.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any

if __name__ == "__main__" and __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.hermes_host.sandbox_guard import sandbox_root

DANGEROUS = "rm -rf /tmp/petasos-s2-not-a-real-target"
HARDLINE = "rm -rf /"
BENIGN = "echo ok"
PROMPTS: list[str] = []
_ENV = (
    "HERMES_INTERACTIVE",
    "HERMES_CRON_SESSION",
    "HERMES_SINGLE_QUERY_SESSION",
    "HERMES_SESSION_PLATFORM",
    "HERMES_EXEC_ASK",
    "TERMINAL_ENV",
    "TERMINAL_DOCKER_VOLUMES",
    "TERMINAL_DOCKER_MOUNT_CWD_TO_WORKSPACE",
)


def _load(name: str) -> Any:
    return importlib.import_module(name)


def _callback(command: str, _description: str, **_kwargs: Any) -> str:
    PROMPTS.append(command[:200])
    return "deny"


def _reset() -> None:
    PROMPTS.clear()
    for name in _ENV:
        os.environ.pop(name, None)
    approval = _load("tools.approval")
    approval.disable_session_yolo(approval.get_current_session_key(default=""))


def _approvals(**fields: Any) -> None:
    config = _load("hermes_cli.config")
    loaded = config.load_config()
    if not isinstance(loaded, dict):
        loaded = {}
    approvals: dict[str, Any] = {"mode": "manual"}
    approvals.update(fields)
    loaded["approvals"] = approvals
    config.save_config(loaded)


def _gate(command: str) -> dict[str, Any]:
    approval = _load("tools.approval")
    terminal = _load("tools.terminal_tool")
    config = terminal._get_env_config()
    env_type = config["env_type"] if isinstance(config.get("env_type"), str) else "local"
    host_access = bool(terminal._docker_has_host_access(config))
    from petasos.hermes.host import command_will_be_asked

    asked = command_will_be_asked(command)
    verdict = approval.check_all_command_guards(
        command,
        env_type,
        approval_callback=_callback,
        has_host_access=host_access,
    )
    approved = bool(verdict.get("approved")) if isinstance(verdict, dict) else False
    return {
        "asked": asked,
        "approved": approved,
        "prompted": bool(PROMPTS),
        "env_type": env_type,
        "host_access": host_access,
    }


def _case(name: str, command: str, **setup: object) -> dict[str, Any]:
    _reset()
    interactive = bool(setup.pop("interactive", False))
    yolo = bool(setup.pop("yolo", False))
    # What the stand-in for Hermes's guardian model answers, when one is used.
    smart = setup.pop("smart", None)
    env = setup.pop("env", {})
    terminal_env = setup.pop("terminal_env", None)
    volumes = setup.pop("volumes", None)
    if not isinstance(env, dict):
        raise SystemExit("env must be a mapping")
    _approvals(**setup)
    if interactive:
        os.environ["HERMES_INTERACTIVE"] = "1"
    for key, value in env.items():
        os.environ[str(key)] = str(value)
    if isinstance(terminal_env, str):
        os.environ["TERMINAL_ENV"] = terminal_env
    if isinstance(volumes, str):
        os.environ["TERMINAL_DOCKER_VOLUMES"] = volumes
    guardian = None
    real = None
    if isinstance(smart, str):
        # The gate calls the name it imported, so that is the one to replace.
        # The real function would send the command to a model.
        guardian = _load("tools.approval")
        real = guardian._smart_verdict
        guardian._smart_verdict = lambda *_args, **_kwargs: smart
    try:
        yolo_token = None
        if yolo:
            # An empty session key is never yolo. Bind one, then turn it on.
            context = _load("tools.approval_context")
            approval = _load("tools.approval")
            yolo_token = context.set_current_session_key("ask-harness")
            approval.enable_session_yolo("ask-harness")
        try:
            row = _gate(command)
        finally:
            if yolo_token is not None:
                approval = _load("tools.approval")
                context = _load("tools.approval_context")
                approval.disable_session_yolo("ask-harness")
                context.reset_current_session_key(yolo_token)
    finally:
        if guardian is not None and real is not None:
            guardian._smart_verdict = real
    row["name"] = name
    return row


def _missing(kind: str) -> dict[str, Any]:
    """The gate can still prompt after the predicate's detector is gone."""
    _reset()
    _approvals()
    os.environ["HERMES_INTERACTIVE"] = "1"
    detection = _load("tools.approval_detection")
    original = detection.detect_dangerous_command
    if kind == "raises":

        def boom(_command: str) -> tuple[bool, None, None]:
            raise RuntimeError("detector moved")

        detection.detect_dangerous_command = boom
    else:
        del detection.detect_dangerous_command
    try:
        row = _gate(DANGEROUS)
    finally:
        detection.detect_dangerous_command = original
    row["name"] = kind
    return row


def ask_cases() -> dict[str, Any]:
    """One row per gate situation. The command string is never executed."""
    sandbox_root()
    rows = [
        _case("interactive", DANGEROUS, interactive=True),
        _case("benign", BENIGN, interactive=True),
        _case("petasos_only", "echo x | zsh", interactive=True),
        _case("headless", DANGEROUS),
        _case("mode_off", DANGEROUS, interactive=True, mode="off"),
        _case("yolo", DANGEROUS, interactive=True, yolo=True),
        _case("smart_escalates", DANGEROUS, interactive=True, mode="smart", smart="escalate"),
        _case("smart_approves", DANGEROUS, interactive=True, mode="smart", smart="approve"),
        _case(
            "cron_approve",
            DANGEROUS,
            interactive=True,
            cron_mode="approve",
            env={"HERMES_CRON_SESSION": "1"},
        ),
        _case(
            "cron_deny",
            DANGEROUS,
            interactive=True,
            cron_mode="deny",
            env={"HERMES_CRON_SESSION": "1"},
        ),
        _case(
            "single_query_approve",
            DANGEROUS,
            interactive=True,
            single_query_mode="approve",
            env={"HERMES_SINGLE_QUERY_SESSION": "1"},
        ),
        _case(
            "unattended_approve",
            DANGEROUS,
            unattended_mode="approve",
            env={"HERMES_SESSION_PLATFORM": "webhook"},
        ),
        _case("docker", DANGEROUS, interactive=True, terminal_env="docker"),
        _case("docker_hardline", HARDLINE, interactive=True, terminal_env="docker"),
        _case(
            "docker_host",
            DANGEROUS,
            interactive=True,
            terminal_env="docker",
            volumes='["/tmp/petasos-s2-not-a-mount:/workspace"]',
        ),
        _case("hardline", HARDLINE, interactive=True),
        _missing("raises"),
        _missing("missing"),
    ]
    return {"cases": rows}


def main() -> None:
    request = json.load(sys.stdin)
    if request.get("action") != "ask":
        raise SystemExit(f"unknown action {request.get('action')}")
    json.dump(ask_cases(), sys.stdout)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
