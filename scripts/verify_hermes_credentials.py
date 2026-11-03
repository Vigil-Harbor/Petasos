"""Offline integration evidence against an explicitly supplied Hermes checkout.

Run with the host's Python using -S -B; dependency activation/updating is excluded.
Only synthetic values and temporary profiles are used. No gateway is started.
"""

from __future__ import annotations

import argparse
import asyncio
import contextvars
import hashlib
import importlib
import importlib.util
import json
import logging
import os
import platform
import socket
import subprocess
import sys
import tempfile
import threading
import types
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any


def revision(root: Path) -> str:
    return subprocess.check_output(
        ["git", "-c", f"safe.directory={root.as_posix()}", "-C", str(root), "rev-parse", "HEAD"],
        text=True,
    ).strip()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(root: Path, hermes: Path, scratch: Path, rounds: int) -> dict[str, Any]:
    # Windows's first platform query can invoke `ver`; warm its stdlib cache
    # before disabling subprocesses for the integration path.
    platform.uname()
    # Do not inherit provider credentials or real profile/config locations.
    keep = {
        k: v
        for k, v in os.environ.items()
        if k.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP"}
    }
    os.environ.clear()
    os.environ.update(keep)
    for name in ("HERMES_HOME", "HOME", "USERPROFILE", "LOCALAPPDATA", "APPDATA"):
        os.environ[name] = str(scratch / "launch")
    (scratch / "launch").mkdir()
    sys.path[:0] = [str(root), str(hermes)]

    # Importing the host entrypoint normally activates/repairs dependencies. This
    # one explicit shim excludes startup installation, not routing or redaction.
    bootstrap = types.ModuleType("hermes_bootstrap")
    bootstrap._happy_eyeballs_create_connection = socket.create_connection  # type: ignore[attr-defined]
    sys.modules["hermes_bootstrap"] = bootstrap
    attempts: list[str] = []

    def audit(event: str, args: tuple[Any, ...]) -> None:
        if event == "subprocess.Popen":
            attempts.append("subprocess")
            raise RuntimeError("external processes disabled in verification")
        if event == "socket.connect":
            address = args[1]
            if not isinstance(address, tuple) or address[0] not in ("127.0.0.1", "::1"):
                attempts.append("network")
                raise RuntimeError("external network disabled in verification")

    logging.disable(logging.CRITICAL)
    host: Any = importlib.import_module("gateway.run")
    plugins: Any = importlib.import_module("hermes_cli.plugins")
    lifecycle: Any = importlib.import_module("hermes_cli.lifecycle")
    approval: Any = importlib.import_module("tools.approval")
    wait: Any = importlib.import_module("tools.approval_gateway_wait")
    approval_context: Any = importlib.import_module("tools.approval_context")
    redact: Any = importlib.import_module("agent.redact")
    secrets: Any = importlib.import_module("agent.secret_scope")
    constants: Any = importlib.import_module("hermes_constants")
    from petasos.console import _approvals, _events, _history, _paths
    from petasos.console.server import _enforcement_summary, _history_disk_row

    # Imports may query local version metadata with git. Enforce the I/O guard
    # for all profile setup, dispatch, redaction and persistence below.
    sys.addaudithook(audit)
    # First-party telemetry is outside this probe; plugin dispatch stays real.
    lifecycle._observe = lambda *_args, **_kwargs: None
    secrets.set_multiplex_active(True)
    runner = host.GatewayRunner.__new__(host.GatewayRunner)
    profiles: dict[str, Any] = {}
    observations: list[dict[str, Any]] = []
    plugin_path = root / "docs/deployment/reference_plugin/__init__.py"
    loop_thread = threading.get_ident()
    barrier = threading.Barrier(2, timeout=10)

    def check_context(label: str) -> None:
        profile = profiles[label]
        assert constants.hermes_home_key(constants.get_hermes_home()) == constants.hermes_home_key(
            profile["home"]
        )
        assert secrets.get_secret("PROBE_PROFILE_ID") == label
        assert plugins.get_plugin_manager() is profile["manager"]
        other = profiles["B" if label == "A" else "A"]["secret"]
        assert redact.redact_sensitive_text(other, force=True) == other
        assert redact.redact_sensitive_text(profile["secret"], force=True) != profile["secret"]
        known = "ghp_" + "A" * 32
        assert redact.redact_sensitive_text(known) == known
        assert profile["plugin"]._redact_display_text(known, 200)[1] == "redacted"

    def register_profile(label: str) -> None:
        home = scratch / label
        home.mkdir()
        (home / "config.yaml").write_text(
            "plugins:\n  hook_callback_timeout: 5\napprovals:\n  timeout: 0\n", encoding="utf-8"
        )
        secret = f"synthetic-{label}" + chr(1) + "-opaque-vault-password"
        scope = {"PROBE_PROFILE_ID": label, "HERMES_REDACT_SECRETS": "false"}
        with host._profile_runtime_scope(home, prepared_secret_scope=scope):
            manager = plugins.get_plugin_manager()
            # Register only the test callbacks; no installed plugins or scanners.
            manager._discovered = True
            spec = importlib.util.spec_from_file_location(f"credential_probe_{label}", plugin_path)
            assert spec and spec.loader
            plugin: Any = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(plugin)
            resolution = _paths.HermesConfigResolution(home / "config.yaml", "hermes_home")
            plugin._session_resolution = resolution
            spool = Path(_paths.spool_path(resolution))
            key = f"synthetic-signing-key-{label}".encode()
            _events.set_spool_key(key, path=str(spool))
            profiles[label] = dict(
                home=home,
                scope=scope,
                manager=manager,
                plugin=plugin,
                secret=secret,
                spool=spool,
                key=key,
            )
            redact.register_vault_redaction_value(secret)

            def gate(**kwargs: Any) -> dict[str, Any]:
                check_context(label)
                assert threading.get_ident() != kwargs["caller_thread"]
                barrier.wait()
                before = json.dumps(kwargs["args"])
                excerpt = plugin._approval_command_excerpt(
                    kwargs["args"], types.SimpleNamespace(findings=())
                )
                assert "opaque-vault-password" not in excerpt
                assert "masked locally" in excerpt
                assert json.dumps(kwargs["args"]) == before
                assert plugin._emit_enforcement_event(
                    session_id=kwargs["session_id"],
                    tool="terminal",
                    event_type="quarantine",
                    reason=secret,
                )
                observations.append(dict(profile=label, seam="bounded_plugin_worker", passed=True))
                directive: dict[str, Any] = plugin._approve_return(
                    "terminal", kwargs["session_id"], "petasos.probe", excerpt
                )
                return directive

            def observer(phase: str, **kwargs: Any) -> None:
                check_context(label)
                assert threading.get_ident() != loop_thread
                handler = (
                    plugin._pre_approval_request
                    if phase == "request"
                    else plugin._post_approval_response
                )
                handler(**kwargs)
                observations.append(dict(profile=label, seam=phase, passed=True))

            manager._hooks["pre_tool_call"] = [gate]
            manager._hooks["pre_approval_request"] = [lambda **kw: observer("request", **kw)]
            manager._hooks["post_approval_response"] = [lambda **kw: observer("response", **kw)]

    for label in ("A", "B"):
        register_profile(label)

    def turn(label: str, outcome: str, index: int) -> dict[str, Any]:
        check_context(label)
        assert threading.get_ident() != loop_thread
        profile = profiles[label]
        session = f"{label}-{outcome}-{index}"
        tokens = approval_context.set_current_observability_context(
            session_id=session, turn_id=session + "-turn", tool_call_id=session + "-call"
        )
        session_token = approval_context.set_current_session_key(session)
        try:
            directives = lifecycle.invoke_hook(
                "pre_tool_call",
                args={"command": {"nested": [profile["secret"]]}},
                tool_name="terminal",
                session_id=session,
                caller_thread=threading.get_ident(),
                tool_call_id=session + "-call",
            )
            assert len(directives) == 1 and directives[0]["action"] == "approve"

            def notify(_data: dict[str, Any]) -> None:
                if outcome == "deny":
                    assert approval.resolve_gateway_approval(session, "deny") == 1
                elif outcome == "notify_failed":
                    raise RuntimeError("synthetic notification failure")

            result = wait._await_gateway_decision(
                session,
                notify,
                {
                    "command": profile["secret"],
                    "description": profile["secret"],
                    "pattern_key": "plugin_rule:petasos.probe",
                },
            )
            if outcome == "deny":
                assert result["resolved"] is True and result["choice"] == "deny"
            elif outcome == "timeout":
                assert result["resolved"] is False and result["choice"] is None
            else:
                assert result.get("notify_failed") is True
            return dict(profile=label, outcome=outcome, round=index, passed=True)
        finally:
            approval_context.reset_current_session_key(session_token)
            approval_context.reset_current_observability_context(tokens)

    async def scenario(label: str, outcome: str, index: int) -> dict[str, Any]:
        p = profiles[label]
        with host._profile_runtime_scope(p["home"], prepared_secret_scope=p["scope"]):
            result: dict[str, Any] = await runner._run_in_executor_with_context(
                turn, label, outcome, index
            )
            return result

    async def exercise() -> tuple[list[Any], dict[str, bool]]:
        results: list[Any] = []
        for index in range(rounds):
            for outcome in ("deny", "timeout", "notify_failed"):
                results.extend(
                    await asyncio.gather(
                        scenario("A", outcome, index), scenario("B", outcome, index)
                    )
                )

        # Deliberately lose context through the same executor; the oracle must see it.
        def lost_context() -> dict[str, bool]:
            p = profiles["A"]
            return {
                "wrong_home_detected": constants.hermes_home_key(constants.get_hermes_home())
                != constants.hermes_home_key(p["home"]),
                "opaque_value_unmasked": redact.redact_sensitive_text(p["secret"], force=True)
                == p["secret"],
                "wrong_manager_detected": plugins.get_plugin_manager() is not p["manager"],
            }

        with host._profile_runtime_scope(
            profiles["A"]["home"], prepared_secret_scope=profiles["A"]["scope"]
        ):
            negative = await asyncio.get_running_loop().run_in_executor(
                runner._get_executor(), contextvars.Context().run, lost_context
            )
        assert all(negative.values())
        return results, negative

    try:
        results, negative = asyncio.run(exercise())
    finally:
        runner._get_executor().shutdown(wait=True)
    expected = rounds * 3
    assert len(observations) == expected * 2 * 3
    scanned = 0

    def measured_redact(text: str, **options: bool) -> str:
        nonlocal scanned
        scanned += len(text)
        result: str = redact.redact_sensitive_text(text, **options)
        return result

    started = perf_counter()
    try:
        profiles["A"]["plugin"]._excerpt_redact_arguments(
            {"command": {"k" * 500_000: ["a"] * 4000}}, measured_redact
        )
        raise AssertionError("amplifying payload was not withheld")
    except ValueError as error:
        assert str(error) == "excerpt redaction exceeds character budget"
    resource_check = dict(
        withheld=True,
        redactor_input_characters=scanned,
        seconds=round(perf_counter() - started, 6),
    )
    assert scanned <= profiles["A"]["plugin"]._MAX_PARAM_TEXT_LEN
    persistence = []
    for label, p in profiles.items():
        # Drain each profile separately, like a console bound to that profile.
        rows = [json.loads(line) for line in p["spool"].read_text(encoding="utf-8").splitlines()]
        assert len(rows) == expected * 3
        spool_key = _events._derive_spool_key(p["key"])
        other_key = _events._derive_spool_key(profiles["B" if label == "A" else "A"]["key"])
        history = p["home"] / "history.jsonl"
        _history._reset_history_state(str(history))
        history_key = _history._derive_history_key(p["key"])
        for row in rows:
            assert _events.verify_event(row, spool_key)
            assert not _events.verify_event(row, other_key)
            assert row["session_id"].startswith(label + "-")
            assert row["credential_redaction"] == "redacted"
            if row["event_type"] == "approval":
                assert row["turn_id"] == row["session_id"] + "-turn"
                assert row["tool_call_id"] == row["session_id"] + "-call"
            summary = _enforcement_summary(row, provenance="genuine")
            assert _history.append_history_row(_history_disk_row(summary), history_key)
        stored = [json.loads(line) for line in history.read_text().splitlines()]
        assert all(_history.verify_history_row(row, history_key) for row in stored)
        assert "opaque-vault-password" not in p["spool"].read_text()
        assert "opaque-vault-password" not in history.read_text()
        responses = [row for row in stored if row.get("phase") == "response"]
        assert sorted(row["choice"] for row in responses) == sorted(
            ["deny", "timeout", "notify_failed"] * rounds
        )
        queued = _approvals.refused_items(stored, frozenset())["items"]
        assert len(queued) == expected
        assert all(row["credential_redaction"] == "redacted" for row in queued)
        persistence.append(
            dict(
                profile=label,
                spool_rows=len(rows),
                history_rows=len(stored),
                refused_items=len(queued),
                signatures_valid=True,
                other_profile_key_rejected=True,
                secrets_absent=True,
                identifiers_preserved=True,
            )
        )
    assert not attempts, "external I/O was attempted"
    return dict(
        scenarios=results,
        hook_observations=len(observations),
        negative_control=negative,
        forced_redaction_with_preference_off=True,
        resource_check=resource_check,
        persistence=persistence,
        external_io_attempts=attempts,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes-source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--site-packages", type=Path)
    parser.add_argument("--rounds", type=int, default=5)
    args = parser.parse_args()
    if not sys.flags.no_site:
        parser.error("use -S -B to exclude automatic host startup activation")
    if not __debug__:
        parser.error("assertions must be enabled; do not use -O")
    if not 1 <= args.rounds <= 100:
        parser.error("rounds must be between 1 and 100")
    root = Path(__file__).resolve().parents[1]
    hermes = args.hermes_source.resolve()
    output = args.output.resolve()
    site = args.site_packages or Path(sys.executable).parents[1] / "Lib/site-packages"
    sys.path.append(str(site))
    receipt: dict[str, Any] = {
        "schema": 1,
        "utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version.split()[0],
        "hermes_commit": revision(hermes),
        "petasos_commit": revision(root),
        "harness_sha256": digest(Path(__file__)),
        "petasos_plugin_sha256": digest(root / "docs/deployment/reference_plugin/__init__.py"),
        "petasos_sources_sha256": {
            name: digest(root / name)
            for name in (
                "petasos/console/_paths.py",
                "petasos/console/_events.py",
                "petasos/console/_history.py",
                "petasos/console/_approvals.py",
                "petasos/console/server.py",
            )
        },
        "host_sources_sha256": {
            name: digest(hermes / name)
            for name in (
                "gateway/run.py",
                "gateway/turn_executor.py",
                "hermes_cli/plugins.py",
                "hermes_cli/plugins_dispatch.py",
                "hermes_cli/lifecycle.py",
                "tools/approval_context.py",
                "tools/approval_gateway_wait.py",
                "tools/approval.py",
                "agent/redact.py",
                "agent/secret_scope.py",
            )
        },
        "fixture_seams": [
            "Startup bootstrap/updater excluded",
            "Synthetic prepared secret scopes and registered values",
            "Only fixture callbacks registered; plugin discovery/scanner startup excluded",
            "First-party lifecycle telemetry disabled",
            "Pre-tool callback invokes actual excerpt/enforcement helpers; no model/scanner",
            "History writers exercised sequentially after concurrent spool writes",
        ],
        "limits": [
            "Offline source integration, not a deployed gateway or Desktop smoke test",
            "No actual password-manager retrieval, provider authentication or credential rotation",
            "Does not exercise routing admission/profile selection or every gateway turn surface",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="credential-gateway-", dir=output.parent) as directory:
        receipt["results"] = verify(root, hermes, Path(directory), args.rounds)
    receipt["passed"] = True
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "passed": True,
                "scenarios": len(receipt["results"]["scenarios"]),
                "receipt": str(output),
            }
        )
    )


if __name__ == "__main__":
    main()
