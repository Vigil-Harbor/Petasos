"""PET-125: optional standalone-console-API auth token.

Pins the bounded code change for the self-disarm / self-tamper hardening: an
off-by-default ``auth_token`` on ``build_app`` that gates ``/api/*`` behind an
``Authorization: Bearer <token>`` credential. Default (no token) behavior must
be byte-for-byte identical to today, so the zero-config local operator workflow
is unbroken.

The armed bit is driven through a monkeypatched in-memory holder rather than a
real config file — the file-backed read/write path is already covered by
``test_console_armed.py``; here the subject under test is the auth gate, so the
assertions stay on "the bit was/wasn't flipped" without disk or cache timing.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import pytest

pytest.importorskip("fastapi")

import petasos  # noqa: E402
from petasos.config import PetasosConfig  # noqa: E402
from petasos.console.server import build_app  # noqa: E402
from petasos.pipeline import Pipeline  # noqa: E402
from petasos.scanners.minimal import MinimalScanner  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator


def _make_pipeline() -> Pipeline:
    return Pipeline(scanners=[MinimalScanner()], config=PetasosConfig(fail_mode="degraded"))


@pytest.fixture()
def armed_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, bool]]:
    """Back ``read_armed``/``write_armed`` with an in-memory holder.

    The handlers import both names function-locally from
    ``petasos.console._armed``, so patching the attributes on that module is what
    the route bodies resolve at call time.
    """
    state = {"armed": True}

    def _read() -> bool:
        return state["armed"]

    def _write(value: bool) -> bool:
        state["armed"] = value
        return True

    monkeypatch.setattr("petasos.console._armed.read_armed", _read)
    monkeypatch.setattr("petasos.console._armed.write_armed", _write)
    yield state


def _client(app: Any) -> Any:
    from fastapi.testclient import TestClient

    return TestClient(app)


# ── default: no token => identical to today ──────────────────────────────────


def test_console_auth_disabled_by_default_preserves_current_behavior(
    armed_state: dict[str, bool],
) -> None:
    tc = _client(build_app(_make_pipeline()))

    assert tc.get("/api/health").status_code == 200

    r = tc.post("/api/armed", json={"armed": False})
    assert r.status_code == 200
    assert armed_state["armed"] is False  # the bit was flipped, no auth required

    assert tc.get("/").status_code == 200


# ── auth on: /api/* gated ─────────────────────────────────────────────────────


def test_api_rejected_without_token_when_auth_enabled(armed_state: dict[str, bool]) -> None:
    tc = _client(build_app(_make_pipeline(), auth_token="secret"))

    assert tc.post("/api/armed", json={"armed": False}).status_code == 401
    assert tc.get("/api/config").status_code == 401
    assert armed_state["armed"] is True  # never flipped — the request never reached the handler


def test_api_accepted_with_valid_token(armed_state: dict[str, bool]) -> None:
    tc = _client(build_app(_make_pipeline(), auth_token="secret"))

    ok = tc.post(
        "/api/armed",
        json={"armed": False},
        headers={"Authorization": "Bearer secret"},
    )
    assert ok.status_code == 200
    assert armed_state["armed"] is False

    # A wrong token does not flip the bit back.
    armed_state["armed"] = True
    bad = tc.post(
        "/api/armed",
        json={"armed": False},
        headers={"Authorization": "Bearer wrong"},
    )
    assert bad.status_code == 401
    assert armed_state["armed"] is True


@pytest.mark.parametrize(
    "header",
    [
        None,  # missing header
        "Basic abc",  # wrong scheme
        "Bearer",  # no credential, no trailing space
        "bearer secret",  # lowercase scheme (case-sensitive)
        "Bearer wrong",  # valid shape, wrong credential
    ],
)
def test_malformed_authorization_header_is_401_not_500(
    armed_state: dict[str, bool], header: str | None
) -> None:
    tc = _client(build_app(_make_pipeline(), auth_token="secret"))
    headers = {"Authorization": header} if header is not None else {}

    r = tc.post("/api/armed", json={"armed": False}, headers=headers)
    assert r.status_code == 401  # never 500 — parsing never raises before the decision
    assert armed_state["armed"] is True


def test_non_api_route_allowed_while_api_route_gated_when_auth_enabled(
    armed_state: dict[str, bool],
) -> None:
    # The load-bearing assertion for the /api/-prefix scoping: the dependency runs
    # for GET / and takes the early-allow branch, so the operator still gets a page
    # while every /api/* route is gated.
    tc = _client(build_app(_make_pipeline(), auth_token="secret"))

    assert tc.get("/").status_code == 200
    assert tc.get("/api/health").status_code == 401


def test_sse_requires_token_when_auth_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    # The real SSE generator is an unbounded ``while True`` that emits nothing
    # until a 15s keepalive (_sse.py), and this TestClient buffers the stream
    # open rather than returning status at connect — so a live open would hang.
    # Patch the generator to be finite; the auth dependency runs before the body
    # either way, so the negative 401 is unaffected and the positive 200 is fast.
    async def _finite(self: object, q: object) -> AsyncIterator[str]:
        yield "event: ping\ndata: {}\n\n"

    monkeypatch.setattr("petasos.console._sse.SSEBroadcaster.stream", _finite)
    app = build_app(_make_pipeline(), auth_token="secret")

    # Negative: the dependency runs before the StreamingResponse body generator,
    # so a missing token yields a clean 401 rather than a half-open stream.
    assert _client(app).get("/api/events").status_code == 401

    # Positive: a valid token reaches the SSE route.
    r = _client(app).get("/api/events", headers={"Authorization": "Bearer secret"})
    assert r.status_code == 200


# ── normalization: blank disables, non-blank compared verbatim ────────────────


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_or_whitespace_token_disables_auth_at_every_entry_point(
    armed_state: dict[str, bool], caplog: pytest.LogCaptureFixture, blank: str
) -> None:
    with caplog.at_level(logging.WARNING, logger="petasos.console.server"):
        tc = _client(build_app(_make_pipeline(), auth_token=blank))
        # Ungated: a no-token request to an /api route still succeeds.
        assert tc.get("/api/health").status_code == 200

    assert any("set but blank" in rec.message for rec in caplog.records)


def test_token_with_surrounding_whitespace_is_compared_verbatim(
    armed_state: dict[str, bool],
) -> None:
    # A non-blank token is stored verbatim; .strip() decides on/off only.
    tc = _client(build_app(_make_pipeline(), auth_token=" tok "))

    # The credential after "Bearer " is exactly " tok " — matches verbatim.
    exact = tc.get("/api/health", headers={"Authorization": "Bearer  tok "})
    assert exact.status_code == 200

    # A trimmed credential does not match.
    trimmed = tc.get("/api/health", headers={"Authorization": "Bearer tok"})
    assert trimmed.status_code == 401


def test_openapi_version_matches_package() -> None:
    # Regression for PET-141: the OpenAPI version tracks petasos.__version__ on
    # BOTH construction paths (untokened and PET-125 tokened), so the single
    # _version local (D3) keeps the two branches and the package from drifting.
    assert build_app(_make_pipeline()).version == petasos.__version__
    assert build_app(_make_pipeline(), auth_token="t").version == petasos.__version__
