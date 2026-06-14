"""Tests for the console scan routes' error-envelope hardening (PET-99 D8).

The console scan endpoints (standalone ``/api/scan`` and the Hermes plugin
``/scan``) share ``ConsoleHandlers.run_scan``. Both routes wrap that call in a
try/except that returns a structured ``{"detail": [{field, message}]}`` 500
envelope instead of a bare unhandled 500, so the frontend always receives
readable text (the D3/D5 legibility contract) regardless of where a failure
originates. ``Pipeline.inspect`` is contractually never-throwing; this envelope
is defense-in-depth at the HTTP boundary for any non-pipeline failure
(serialization, broadcast, future code).

Mirrors ``tests/test_console_validation.py`` — same params-based ``client``
fixture so each assertion runs once per route flavor (the route-parity test) —
but builds the TestClient with ``raise_server_exceptions=False`` so a *regressed*
(un-enveloped) handler exception surfaces as an observable 500 response the
assertions can fail cleanly against, rather than being re-raised into the test.
"""

from collections.abc import Iterator

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from petasos.config import PetasosConfig  # noqa: E402
from petasos.pipeline import Pipeline  # noqa: E402
from petasos.scanners.minimal import MinimalScanner  # noqa: E402

_SCAN_TEXT = "hello world this is a test"


def _make_pipeline() -> Pipeline:
    return Pipeline(
        scanners=[MinimalScanner()],
        config=PetasosConfig(fail_mode="degraded"),
    )


@pytest.fixture(params=["standalone", "plugin"])
def client(request: pytest.FixtureRequest) -> Iterator[tuple[TestClient, str]]:
    """Yield (test_client, scan_path) for each console route flavor.

    Carries its own copy of the plugin-handler reset (pattern from
    tests/test_plugin_api_sse.py — fixtures are not importable across modules).
    ``raise_server_exceptions=False`` is a deliberate departure from
    test_console_validation.py: it keeps an unhandled 500 observable instead of
    re-raised, so a regression that drops the D8 envelope fails the assertion
    cleanly rather than erroring the test.
    """
    import petasos.console.hermes.plugin_api as plugin_mod

    plugin_mod._handlers = None
    if request.param == "standalone":
        from petasos.console.server import build_app

        tc = TestClient(build_app(_make_pipeline()), raise_server_exceptions=False)
        yield tc, "/api/scan"
    else:
        from petasos.console.hermes.plugin_api import init_handlers, router

        init_handlers(_make_pipeline())
        app = FastAPI()
        app.include_router(router)
        tc = TestClient(app, raise_server_exceptions=False)
        yield tc, "/scan"
    plugin_mod._handlers = None


def test_valid_scan_returns_200(client: tuple[TestClient, str]) -> None:
    """Sanity anchor: the un-monkeypatched route returns a well-formed 200, so
    the error-shape test below is witnessing the except branch, not a broken
    fixture."""
    tc, path = client
    resp = tc.post(path, json={"text": _SCAN_TEXT})
    assert resp.status_code == 200
    assert "result" in resp.json()


def test_scan_error_payload_shape(
    client: tuple[TestClient, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression for PET-99 D8: a handler-level exception yields a *structured*
    500 (``{"detail": [{field, message}]}``), never a bare/unstructured 500.

    Monkeypatches the shared ``ConsoleHandlers.run_scan`` (the call both routes
    wrap) to raise; both route flavors must convert it to the readable envelope
    so the playground's scanErrorBlock always has selectable text to render.
    """
    from petasos.console.server import ConsoleHandlers

    async def _boom(self: object, *args: object, **kwargs: object) -> dict[str, object]:
        raise RuntimeError("synthetic scan failure")

    monkeypatch.setattr(ConsoleHandlers, "run_scan", _boom)

    tc, path = client
    resp = tc.post(path, json={"text": _SCAN_TEXT})

    assert resp.status_code == 500
    body = resp.json()
    detail = body.get("detail")
    assert isinstance(detail, list) and detail, f"expected non-empty detail list, got {body!r}"
    first = detail[0]
    assert isinstance(first, dict)
    assert first.get("field") == "scan"
    # str(exc) is surfaced verbatim (internal operator console) — the readable
    # text the operator needs is present, not swallowed into a generic 500.
    assert "synthetic scan failure" in first.get("message", "")
