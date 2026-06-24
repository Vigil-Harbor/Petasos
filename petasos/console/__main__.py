"""Standalone Petasos console entrypoint — ``python -m petasos.console`` (PET-153).

The out-of-process supervised console (Decision D1): a launchable, supervisable
server that does not depend on Hermes's plugin-backend mount policy and lives
outside the update-wiped Hermes install tree. An OS supervisor (Windows Task
Scheduler / macOS launchd) owns the lifecycle; this module only provides the
entrypoint. See ``docs/deployment/hermes-desktop.md`` for the supervisor
registration runbook.

Import discipline (mandatory): fastapi/uvicorn **and** ``plugin_api`` are imported
lazily inside ``main()``, never at module top. ``plugin_api`` imports fastapi at
its own module top, so importing it here at module scope would transitively
re-poison the fastapi-free lane. Keeping those imports inside ``main()`` lets the
durability test ``import petasos.console.__main__`` with no fastapi present.
"""

from __future__ import annotations

import argparse
import importlib.util
import logging
import sys

logger = logging.getLogger("petasos.dashboard")

# Stable ERROR tripwire token (greppable in supervisor logs) for a failed start.
_START_FAILED = "PETASOS_CONSOLE_START_FAILED"

_DEFAULT_PORT = 8384


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="petasos.console",
        description=(
            "Run the standalone Petasos console on 127.0.0.1. The bearer token is "
            "read only from the PETASOS_CONSOLE_TOKEN environment variable (never a "
            "flag, to keep it out of process listings and shell history)."
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=_DEFAULT_PORT,
        help=f"TCP port to bind on 127.0.0.1 (default {_DEFAULT_PORT}).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Resolve config, build the read-only pipeline, and serve the console.

    Returns a process exit code: 0 on clean shutdown, non-zero on a usage error,
    a missing ``console`` extra, or a bind failure.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    port: int = args.port
    if port < 1 or port > 65535:
        # Reject 0 (and out-of-range): an ephemeral port yields an unfindable console.
        print(
            f"--port must be between 1 and 65535; got {port}. "
            f"Port 0 (ephemeral) yields an unfindable console.",
            file=sys.stderr,
        )
        return 2

    # Lazy, both-dependency import guard: the entrypoint needs the `console` extra
    # (fastapi + uvicorn) to serve. Probe both so a partial install (one present,
    # the other absent) gets an actionable message, not a raw ImportError traceback.
    for module_name in ("fastapi", "uvicorn"):
        if importlib.util.find_spec(module_name) is None:
            print(
                f"Petasos console requires the '{module_name}' package, which is not "
                f'installed. Install the console extra: pip install "petasos[console]"',
                file=sys.stderr,
            )
            return 1

    # Lazy imports (keep this module's top fastapi-free). plugin_api imports fastapi
    # transitively; resolve config through it so the standalone and dashboard paths
    # read config identically (the existing `loading config from ... [tier=...]` line
    # is emitted here, matching the agent's diagnostic).
    import os

    from petasos.console import serve
    from petasos.console._standalone import build_dashboard_pipeline
    from petasos.console.hermes import plugin_api

    raw_config = plugin_api._load_config()
    pipeline = build_dashboard_pipeline(raw_config)

    # Startup self-check (greppable tripwire). Both flags are sourced from EFFECTIVE
    # state, not raw env presence, so a blank-token or malformed-secret slip is
    # reported as the off-state it actually produces — exactly the misconfiguration
    # the tripwire exists to catch.
    token = os.environ.get("PETASOS_CONSOLE_TOKEN")
    auth_on = token is not None and token.strip() != ""
    attestation_on = pipeline.config.session_secret is not None

    # Banner logged at INFO immediately before serve(). serve() blocks in
    # uvicorn.run and builds the app internally, so the banner and the bind-failure
    # handler must both sit here in main() around the serve() call (a FastAPI
    # startup event never fires on a pre-bind OSError).
    logger.info(
        "petasos console starting: bind=127.0.0.1:%s auth=%s attestation=%s",
        port,
        "on" if auth_on else "off",
        "on" if attestation_on else "off",
    )
    try:
        serve(pipeline, port=port)
    except (OSError, SystemExit) as exc:
        logger.error(
            "%s: console failed to start on 127.0.0.1:%s: %s",
            _START_FAILED,
            port,
            exc,
        )
        print(
            f"port {port} already in use; a previous console instance may still be "
            f"running. Stop and replace the existing petasos-console supervisor task "
            f"before starting a new one (see the deployment runbook).",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
