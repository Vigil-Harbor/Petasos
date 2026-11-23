"""Console health carries the startup scanner build (PET-264).

Regression for PET-264: a refused Semgrep shows on console health with its reason token.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from petasos.config import PetasosConfig  # noqa: E402
from petasos.console import create_app  # noqa: E402
from petasos.console._standalone import build_dashboard_pipeline  # noqa: E402
from petasos.console.hermes import plugin_api  # noqa: E402
from petasos.console.server import ConsoleHandlers  # noqa: E402
from petasos.pipeline import Pipeline  # noqa: E402
from petasos.scanners.bootstrap import ScannerBuildStatus  # noqa: E402
from petasos.scanners.minimal import MinimalScanner  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Iterator

_STATUS_KEYS = ["scanner_id", "display_name", "outcome", "reason"]
_REFUSED = {
    "scanner_id": "semgrep",
    "display_name": "Semgrep",
    "outcome": "failed",
    "reason": "semgrep.host_lifecycle_unavailable",
}


@pytest.fixture(autouse=True)
def _reset_handlers() -> Iterator[None]:
    plugin_api._handlers = None
    yield
    plugin_api._handlers = None


def _predicate(body: dict[str, Any]) -> bool:
    dumped = json.dumps(body, default=str).lower()
    return (
        "semgrep" in dumped
        and "failed" in dumped
        and "semgrep.host_lifecycle_unavailable" in dumped
    )


def _assert_refused_record(body: dict[str, Any]) -> None:
    build = body["scanner_build"]
    assert build["available"] is True
    statuses = build["statuses"]
    assert [row["scanner_id"] for row in statuses] == [
        "llm_guard",
        "llama_firewall",
        "presidio",
        "prompt_guard",
        "semgrep",
    ]
    for row in statuses:
        assert list(row) == _STATUS_KEYS
    assert statuses[-1] == _REFUSED
    assert all(row["name"] != "semgrep" for row in body["scanners"])


def test_plugin_health_shows_refused_semgrep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plugin_api, "_load_config", PetasosConfig(semgrep_enabled=True).to_dict)
    plugin_api._self_init()
    app = FastAPI()
    app.include_router(plugin_api.router, prefix="/api/plugins/petasos")
    resp = TestClient(app).get("/api/plugins/petasos/health")
    assert resp.status_code == 200
    body = resp.json()
    assert _predicate(body) is True
    _assert_refused_record(body)
    assert body["pipeline"]["scanner_count"] == len(body["scanners"])


def test_standalone_health_shows_refused_semgrep() -> None:
    pipeline, scanner_build = build_dashboard_pipeline(
        PetasosConfig(semgrep_enabled=True).to_dict()
    )
    app = create_app(pipeline, scanner_build=scanner_build)
    resp = TestClient(app).get("/api/health")
    assert resp.status_code == 200
    _assert_refused_record(resp.json())


def test_health_without_build_record_is_unavailable() -> None:
    pipeline = Pipeline(scanners=[MinimalScanner()], config=PetasosConfig())
    plugin_api.init_handlers(pipeline)
    app = FastAPI()
    app.include_router(plugin_api.router, prefix="/api/plugins/petasos")
    resp = TestClient(app).get("/api/plugins/petasos/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["scanner_build"] == {"available": False, "statuses": None}
    assert _predicate(body) is False
    assert [row["name"] for row in body["scanners"]] == ["minimal"]
    assert body["pipeline"]["scanner_count"] == len(body["scanners"])


async def test_record_is_not_filtered_and_survives_reconfigure() -> None:
    pipeline = Pipeline(
        scanners=[MinimalScanner()],
        config=PetasosConfig(semgrep_enabled=False),
    )
    handlers = ConsoleHandlers(
        pipeline,
        scanner_build=(
            ScannerBuildStatus("llm_guard", "LLM Guard", "disabled", "disabled by config"),
            ScannerBuildStatus(
                "semgrep", "Semgrep", "failed", "semgrep.host_lifecycle_unavailable"
            ),
        ),
    )
    health = await handlers.get_health()
    assert health["scanner_build"]["available"] is True
    statuses = health["scanner_build"]["statuses"]
    assert statuses == [
        {
            "scanner_id": "llm_guard",
            "display_name": "LLM Guard",
            "outcome": "disabled",
            "reason": "disabled by config",
        },
        _REFUSED,
    ]
    pipeline.reconfigure(PetasosConfig(semgrep_enabled=True))
    again = await handlers.get_health()
    assert again["scanner_build"]["statuses"] == statuses
