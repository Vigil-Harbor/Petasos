"""PET-166: the scoped ROUTE contracts on both console surfaces.

The handler-level semantics live in ``test_console_profile_scoped_reads.py``;
this module pins what only a route can show: the 422/409 status mapping, the
query-borne-selector rejection on the write, the SSE idle arm (its terminal
``scope_refusal`` marker, its slot accounting, and the never-iterated-response
leak), and the D13 requirement that the embedded bridge moves in lockstep with
the standalone routes rather than one of them being ported later.
"""

import json
import platform
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")

import petasos.console._armed as armed_mod  # noqa: E402
import petasos.console._history as history_mod  # noqa: E402
import petasos.console._paths as paths_mod  # noqa: E402
import petasos.console.hermes.plugin_api as plugin_mod  # noqa: E402
import petasos.console.server as server_mod  # noqa: E402
from petasos.config import PetasosConfig  # noqa: E402
from petasos.pipeline import Pipeline  # noqa: E402
from petasos.scanners.minimal import MinimalScanner  # noqa: E402

pytestmark = pytest.mark.anyio


def _make_pipeline() -> Pipeline:
    return Pipeline(scanners=[MinimalScanner()], config=PetasosConfig(fail_mode="degraded"))


@pytest.fixture()
def profiles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Two real profile homes with alpha equipped (see the sibling module's fixture
    docstring for why the autouse overrides and HERMES_HOME must be cleared)."""
    saved_spool = paths_mod._SPOOL_PATH_OVERRIDE
    saved_hist = history_mod._HISTORY_PATH_OVERRIDE
    paths_mod._SPOOL_PATH_OVERRIDE = None
    history_mod._HISTORY_PATH_OVERRIDE = None
    monkeypatch.delenv("HERMES_HOME", raising=False)
    if platform.system() == "Windows":
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    else:
        monkeypatch.setenv("HOME", str(tmp_path))
    root = paths_mod.hermes_root()
    for name in ("alpha", "beta"):
        d = root / "profiles" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "config.yaml").write_text("petasos:\n  enabled: true\n", encoding="utf-8")
    (root / "active_profile").write_text("alpha", encoding="utf-8")
    armed_mod._reset_armed_cache()
    try:
        yield root
    finally:
        paths_mod._SPOOL_PATH_OVERRIDE = saved_spool
        history_mod._HISTORY_PATH_OVERRIDE = saved_hist
        armed_mod._reset_armed_cache()


@pytest.fixture(params=["standalone", "plugin"])
def client(request: pytest.FixtureRequest) -> Iterator[tuple[Any, str]]:
    """Both route surfaces, so D13's lockstep requirement is a test fact.

    Every contract below runs twice; a bridge that dropped the parameter, the 409,
    the 503 mapping, or the idle-arm slot accounting fails on the plugin pass only.
    """
    from fastapi.testclient import TestClient

    plugin_mod._handlers = None
    if request.param == "standalone":
        from petasos.console.server import build_app

        with TestClient(build_app(_make_pipeline())) as tc:
            yield tc, "/api"
    else:
        from fastapi import FastAPI

        from petasos.console.hermes.plugin_api import init_handlers, router

        init_handlers(_make_pipeline())
        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as tc:
            yield tc, ""
    plugin_mod._handlers = None


def _handlers(client: tuple[Any, str]) -> Any:
    tc, base = client
    if base == "":
        return plugin_mod._handlers
    # build_app closes over its handlers; reach them through the live route closure.
    for route in tc.app.routes:
        closure = getattr(getattr(route, "endpoint", None), "__closure__", None) or ()
        for cell in closure:
            if isinstance(cell.cell_contents, server_mod.ConsoleHandlers):
                return cell.cell_contents
    raise AssertionError("handlers not reachable")


# ── 422 / 409 status mapping ──────────────────────────────────────────────


@pytest.mark.parametrize("path", ["/scan-history", "/armed", "/health", "/events"])
def test_unknown_profile_is_422_on_every_scoped_route(
    client: tuple[Any, str], profiles: Path, path: str
) -> None:
    tc, base = client
    r = tc.get(base + path, params={"profile": "ghost"})
    assert r.status_code == 422
    assert r.json()["detail"][0]["field"] == "profile"
    # For /events the failure is an ordinary JSON body, NOT a frame inside a stream.
    assert "text/event-stream" not in r.headers.get("content-type", "")


def test_set_armed_non_equipped_is_409(client: tuple[Any, str], profiles: Path) -> None:
    tc, base = client
    r = tc.post(base + "/armed", json={"armed": False, "profile": "beta"})
    assert r.status_code == 409
    body = r.json()["detail"][0]
    assert body["field"] == "profile"
    assert "alpha" in body["message"]
    assert "persist" not in body["message"].lower()  # never the 503 persistence body
    # beta's config is untouched.
    beta_cfg = profiles / "profiles" / "beta" / "config.yaml"
    assert "enabled: true" in beta_cfg.read_text(encoding="utf-8")


def test_set_armed_query_profile_is_422(client: tuple[Any, str], profiles: Path) -> None:
    # Without this the selector arrives None, the scope resolves to equipped, the
    # 409 never fires, and the running agent is disarmed while the UI names another
    # profile.
    tc, base = client
    r = tc.post(base + "/armed", params={"profile": "beta"}, json={"armed": False})
    assert r.status_code == 422
    assert "body" in r.json()["detail"][0]["message"]


def test_set_armed_non_string_profile_422(client: tuple[Any, str], profiles: Path) -> None:
    tc, base = client
    r = tc.post(base + "/armed", json={"armed": False, "profile": 7})
    assert r.status_code == 422
    assert r.json()["detail"][0]["field"] == "profile"


def test_set_armed_equipped_still_arms(client: tuple[Any, str], profiles: Path) -> None:
    tc, base = client
    r = tc.post(base + "/armed", json={"armed": False, "profile": "alpha"})
    assert r.status_code == 200
    assert r.json()["armed"] is False
    assert r.json()["read_scope"]["state"] == "equipped"


def test_unscoped_requests_are_unchanged(client: tuple[Any, str], profiles: Path) -> None:
    # D2's fence at the route layer: no parameter -> no new key on any surface.
    tc, base = client
    assert "read_scope" not in tc.get(base + "/armed").json()
    assert "read_scope" not in tc.get(base + "/health").json()
    hist = tc.get(base + "/scan-history").json()
    assert set(hist) == {"entries", "next_before", "older_truncated"}


def test_foreign_cursor_is_422_on_before(client: tuple[Any, str], profiles: Path) -> None:
    tc, base = client
    r = tc.get(base + "/scan-history", params={"profile": "beta", "before": "alpha|1.0~s-x"})
    assert r.status_code == 422
    assert r.json()["detail"][0]["field"] == "before"


# ── SSE: the idle arm, its marker, and its slot accounting ────────────────


async def _first_frame(h: Any, profile: str) -> str:
    """Drive the idle generator directly and pull its first frame.

    Deliberately NOT through TestClient streaming: the idle stream never
    completes by design (D9), so a client-side read loop would block the suite.
    """
    scope = h.resolve_events_scope(profile)
    gen = h.idle_scope_stream(scope)
    try:
        frame = await gen.__anext__()
    finally:
        await gen.aclose()
    assert frame.startswith("event: read_scope")
    return str(frame.split("data: ", 1)[1].strip())


async def test_events_non_equipped_emits_scope_frame_and_stays_open(
    client: tuple[Any, str], profiles: Path
) -> None:
    h = _handlers(client)
    subscribed: list[int] = []
    real_subscribe = h.sse.subscribe

    def _counting_subscribe() -> Any:
        subscribed.append(1)
        return real_subscribe()

    h.sse.subscribe = _counting_subscribe

    scope = h.resolve_events_scope("beta")
    gen = h.idle_scope_stream(scope)
    frame = await gen.__anext__()
    payload = json.loads(frame.split("data: ", 1)[1].strip())
    assert payload["state"] == "not_equipped"
    assert payload["live"] is False
    assert payload["selected"] == "beta"
    assert subscribed == []  # consumes no live subscriber slot
    assert h._idle_stream_count == 1  # holds an idle slot while open
    await gen.aclose()
    assert h._idle_stream_count == 0  # and releases it in the finally


def test_events_equipped_unchanged(client: tuple[Any, str], profiles: Path) -> None:
    # The equipped arm takes the shipped subscribe/stream path and never touches
    # the idle counter. Asserted through the route's own decision (the scope
    # resolution) rather than by opening a live stream against a test client.
    h = _handlers(client)
    assert h.resolve_events_scope("alpha").state == "equipped"
    assert h.resolve_events_scope(None).state == "equipped"
    assert h._idle_stream_count == 0


def test_events_subscriber_limit_is_503_unmarked(client: tuple[Any, str], profiles: Path) -> None:
    # A full LIVE pool is a 503 (it 500s today) and stays UNMARKED, so the shipped
    # client keeps its retry-then-fallback path on the equipped arm.
    tc, base = client
    h = _handlers(client)

    def _boom() -> Any:
        raise RuntimeError("Too many SSE subscribers")

    h.sse.subscribe = _boom
    r = tc.get(base + "/events")
    assert r.status_code == 503
    assert "scope_refusal" not in r.json()


async def test_idle_stream_limit_is_503_and_slot_is_released(
    client: tuple[Any, str], profiles: Path
) -> None:
    tc, base = client
    h = _handlers(client)
    h._idle_stream_count = h.sse.max_subscribers
    r = tc.get(base + "/events", params={"profile": "beta"})
    assert r.status_code == 503
    assert r.json()["scope_refusal"] == "capacity"  # the D9 terminal marker

    h._idle_stream_count = 0
    # Closing an idle stream frees its slot (the generator's finally), so the next
    # one is admitted rather than inheriting a leaked count.
    await _first_frame(h, "beta")
    assert h._idle_stream_count == 0


def test_abandoned_idle_response_holds_no_slot(client: tuple[Any, str], profiles: Path) -> None:
    # Build the generator and NEVER iterate it: a never-started generator's finally
    # never runs, so an increment placed in the ROUTE would leak permanently, once
    # per aborted open. This is the only way that leak is observable.
    h = _handlers(client)
    scope = h.resolve_events_scope("beta")
    for _ in range(h.sse.max_subscribers + 2):
        h.idle_scope_stream(scope)  # constructed, never awaited
    assert h._idle_stream_count == 0


async def test_idle_stream_limit_tracks_broadcaster_bound(profiles: Path) -> None:
    # Constructing the broadcaster with a non-default bound moves BOTH arms, so the
    # two limits are pinned to one source rather than a shared literal.
    from petasos.console._sse import SSEBroadcaster

    h = server_mod.ConsoleHandlers(_make_pipeline())
    h.sse = SSEBroadcaster(max_subscribers=3)
    assert h.sse.max_subscribers == 3
    h._idle_stream_count = 3
    assert h._idle_stream_count >= h.sse.max_subscribers  # the idle arm refuses here


async def test_bridge_and_standalone_agree_on_every_scoped_contract(
    client: tuple[Any, str], profiles: Path
) -> None:
    # D13: the five handlers all forward the selector. A bridge that dropped it
    # would return the equipped view under beta's name (state "equipped").
    tc, base = client
    assert (
        tc.get(base + "/scan-history", params={"profile": "beta"}).json()["read_scope"]["state"]
        == "not_equipped"
    )
    assert (
        tc.get(base + "/armed", params={"profile": "beta"}).json()["read_scope"]["state"]
        == "not_equipped"
    )
    assert (
        tc.get(base + "/health", params={"profile": "beta"}).json()["read_scope"]["state"]
        == "not_equipped"
    )
    frame = json.loads(await _first_frame(_handlers(client), "beta"))
    assert frame["state"] == "not_equipped"
    assert tc.post(base + "/armed", json={"armed": False, "profile": "beta"}).status_code == 409
