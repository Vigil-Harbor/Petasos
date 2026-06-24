"""PET-153 standalone console: shared-builder parity, route/auth smoke, and the
``python -m petasos.console`` entrypoint contract.

fastapi-dependent (the served app + TestClient + the entrypoint's serve() path),
so the whole module ``importorskip``s fastapi and runs on the ``[dev,console]`` CI
``test`` job. The fastapi-free recurrence guards live in
``test_console_packaging_durability.py``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import pytest

pytest.importorskip("fastapi")

from petasos.console import create_app  # noqa: E402
from petasos.console._standalone import build_dashboard_pipeline  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Iterator

_DASHBOARD_LOGGER = "petasos.dashboard"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip the env knobs the builder/entrypoint read, so each test controls them
    explicitly and an ambient value (a live deployment's secret) can't leak in."""
    for var in (
        "PETASOS_LICENSE_KEY",
        "PETASOS_SESSION_SECRET",
        "PETASOS_HASH_KEY",
        "PETASOS_CONSOLE_TOKEN",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def _reset_plugin_api() -> Iterator[None]:
    """Reset plugin_api._handlers after each test (mirrors test_plugin_init_logging)."""
    yield
    try:
        from petasos.console.hermes import plugin_api

        plugin_api._handlers = None
    except Exception:
        pass


def _client(app: Any) -> Any:
    # No context manager: the lifespan enforcement-tailer stays dormant (matches the
    # existing console-test idiom), so routing is exercised without a background task.
    from fastapi.testclient import TestClient

    return TestClient(app)


def _dashboard_logs(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == _DASHBOARD_LOGGER]


# --------------------------------------------------------------------------- #
# Shared builder parity (extraction + logger pin guard)
# --------------------------------------------------------------------------- #


def test_builder_and_self_init_agree(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """``build_dashboard_pipeline({})`` and ``plugin_api._self_init()`` (with
    ``_load_config`` -> ``{}``) build equivalent pipelines and emit the SAME
    ``petasos.dashboard`` log lines. The scanner roster is encoded in the
    self-initialized summary line, so comparing the full log sequence guards both
    the roster parity and the logger/message pin against drift."""
    from petasos.console.hermes import plugin_api

    caplog.clear()
    with caplog.at_level(logging.INFO, logger=_DASHBOARD_LOGGER):
        builder_pipeline = build_dashboard_pipeline({})
    builder_logs = _dashboard_logs(caplog)

    assert builder_pipeline.host_id == "dashboard"
    assert any("'minimal'" in line for line in builder_logs), (
        f"MinimalScanner must appear in the summary roster; got {builder_logs}"
    )

    captured: dict[str, Any] = {}

    def _capture(pipeline: Any) -> None:
        captured["pipeline"] = pipeline

    monkeypatch.setattr(plugin_api, "_load_config", lambda: {})
    monkeypatch.setattr(plugin_api, "init_handlers", _capture)

    caplog.clear()
    with caplog.at_level(logging.INFO, logger=_DASHBOARD_LOGGER):
        plugin_api._self_init()
    self_init_logs = _dashboard_logs(caplog)

    assert captured["pipeline"].host_id == "dashboard"
    # Same dashboard log lines from both construction paths (no drift between the
    # extracted builder and the in-place _self_init it replaced).
    assert builder_logs == self_init_logs


# --------------------------------------------------------------------------- #
# Builder attestation parity (the env-secret-in-the-builder seam)
# --------------------------------------------------------------------------- #


def test_builder_attestation_on_with_valid_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """A valid base64 ``PETASOS_SESSION_SECRET`` lands as bytes on the built
    pipeline's config, so the standalone ``__main__`` path attests spool reads
    identically to the embedded dashboard. Closes the attestation gap at the builder
    seam."""
    import base64

    secret = base64.b64encode(b"\x01" * 32).decode()
    monkeypatch.setenv("PETASOS_SESSION_SECRET", secret)

    pipeline = build_dashboard_pipeline({})
    assert pipeline.config.session_secret is not None


def test_builder_attestation_off_with_invalid_secret(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """An invalid base64 secret leaves ``session_secret`` None and logs the WARNING
    (session binding disabled), rather than silently attesting against garbage."""
    # A single data character is an invalid base64 length and reliably raises.
    monkeypatch.setenv("PETASOS_SESSION_SECRET", "a")

    with caplog.at_level(logging.WARNING, logger=_DASHBOARD_LOGGER):
        pipeline = build_dashboard_pipeline({})

    assert pipeline.config.session_secret is None
    assert any("not valid base64" in line for line in _dashboard_logs(caplog))


# --------------------------------------------------------------------------- #
# Route mounting + auth parity on the decoupled server
# --------------------------------------------------------------------------- #


def test_routes_mounted_not_404() -> None:
    """``create_app(build_dashboard_pipeline({}))`` mounts the data routes: a mounted
    route answers 200/422, never 404. Distinguishes "mounted" from a bare miss."""
    tc = _client(create_app(build_dashboard_pipeline({})))

    assert tc.get("/api/health").status_code != 404
    assert tc.get("/api/config").status_code != 404
    assert tc.get("/api/armed").status_code != 404
    assert tc.post("/api/scan", json={"text": "hello"}).status_code != 404


def test_auth_parity_token_set() -> None:
    """With a token set, an unauthenticated ``/api/*`` call to the decoupled server
    is rejected (401), not silently served on 127.0.0.1; an authenticated call is
    served; and the static index stays ungated (D1 'not silently served')."""
    tc = _client(create_app(build_dashboard_pipeline({}), auth_token="t"))

    assert tc.get("/api/config").status_code == 401
    assert tc.get("/api/config", headers={"Authorization": "Bearer t"}).status_code == 200
    assert tc.get("/").status_code == 200


def test_blank_token_runs_auth_off_with_warning(caplog: pytest.LogCaptureFixture) -> None:
    """A set-but-blank token disables auth with one PET-125 WARNING (the
    misconfiguration the runbook cautions against)."""
    with caplog.at_level(logging.WARNING, logger="petasos.console.server"):
        tc = _client(create_app(build_dashboard_pipeline({}), auth_token=""))
        assert tc.get("/api/config").status_code == 200

    assert any("set but blank" in r.message for r in caplog.records)


def test_auth_off_when_unset() -> None:
    """No token (env unset) leaves ``/api/*`` reachable on localhost, parity with the
    in-tab plugin-API bypass."""
    tc = _client(create_app(build_dashboard_pipeline({})))
    assert tc.get("/api/config").status_code == 200


# --------------------------------------------------------------------------- #
# Entrypoint contract (main())
# --------------------------------------------------------------------------- #


def test_main_plumbs_port_and_resolves_env_token(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """``main(["--port","9000"])`` plumbs the port into uvicorn and resolves the env
    token (the startup banner reports ``auth=on``). uvicorn.run is patched so no real
    bind happens."""
    import petasos.console.__main__ as console_main

    calls: dict[str, Any] = {}

    def _fake_run(app: Any, **kwargs: Any) -> None:
        calls.update(kwargs)

    monkeypatch.setattr("uvicorn.run", _fake_run)
    monkeypatch.setenv("PETASOS_CONSOLE_TOKEN", "tok")

    with caplog.at_level(logging.INFO, logger=_DASHBOARD_LOGGER):
        rc = console_main.main(["--port", "9000"])

    assert rc == 0
    assert calls.get("host") == "127.0.0.1"
    assert calls.get("port") == 9000
    assert any("auth=on" in line for line in _dashboard_logs(caplog))


def test_main_rejects_port_zero(capsys: pytest.CaptureFixture[str]) -> None:
    """``--port 0`` is rejected with an actionable message and a non-zero return (an
    ephemeral port yields an unfindable console)."""
    import petasos.console.__main__ as console_main

    rc = console_main.main(["--port", "0"])
    assert rc != 0
    assert "port" in capsys.readouterr().err.lower()


@pytest.mark.parametrize("missing", ["fastapi", "uvicorn"])
def test_main_missing_console_extra(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], missing: str
) -> None:
    """A partial/absent ``console`` extra (fastapi or uvicorn missing) yields an
    actionable message naming the missing module and the install command, plus a
    non-zero return, not a raw ImportError traceback."""
    import importlib.util

    import petasos.console.__main__ as console_main

    real_find_spec = importlib.util.find_spec

    def _fake_find_spec(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == missing:
            return None
        return real_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "find_spec", _fake_find_spec)

    rc = console_main.main(["--port", "9001"])
    assert rc != 0
    err = capsys.readouterr().err
    assert missing in err
    assert "petasos[console]" in err


def test_main_bind_failure_is_actionable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A bind ``OSError`` (port in use) yields the port-in-use message and a non-zero
    return, and logs the stable ``PETASOS_CONSOLE_START_FAILED`` ERROR tripwire."""
    import petasos.console.__main__ as console_main

    def _boom(app: Any, **kwargs: Any) -> None:
        raise OSError("address already in use")

    monkeypatch.setattr("uvicorn.run", _boom)

    with caplog.at_level(logging.ERROR, logger=_DASHBOARD_LOGGER):
        rc = console_main.main(["--port", "9002"])

    assert rc != 0
    assert "already in use" in capsys.readouterr().err
    assert any("PETASOS_CONSOLE_START_FAILED" in r.getMessage() for r in caplog.records)
