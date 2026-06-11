"""Log-honesty tests for both init surfaces (PET-87).

Verifies that:
- reference_plugin._deferred_init logs probe verdicts
- plugin_api._self_init logs probe verdicts
- Neither surface emits "scanner loaded" when backends are absent
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    import types
    from collections.abc import Iterator

# ---------------------------------------------------------------------------
# reference_plugin import via file path
# ---------------------------------------------------------------------------

_REF_PLUGIN_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "deployment"
    / "reference_plugin"
    / "__init__.py"
)


def _import_reference_plugin() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        "petasos_reference_plugin", str(_REF_PLUGIN_PATH)
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("PETASOS_LICENSE_KEY", "PETASOS_SESSION_SECRET", "PETASOS_HASH_KEY"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def _reset_plugin_api() -> Iterator[None]:
    """Ensure plugin_api._handlers is reset after each test."""
    yield
    try:
        from petasos.console.hermes import plugin_api

        plugin_api._handlers = None
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Blocked-backend helpers
# ---------------------------------------------------------------------------

_BLOCKED_SCANNER_MODULES: dict[str, None] = {
    "llm_guard": None,
    "llm_guard.input_scanners": None,
    "llamafirewall": None,
    "presidio_analyzer": None,
    "presidio_anonymizer": None,
}


# ---------------------------------------------------------------------------
# Tests: reference plugin
# ---------------------------------------------------------------------------


class TestReferencePluginInitLogging:
    def test_backend_missing_logs_probe_verdict(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ref = _import_reference_plugin()
        monkeypatch.setattr(ref, "_config", {})
        monkeypatch.setattr(ref, "_initialized", False)
        monkeypatch.setattr(ref, "_init_error", None)
        monkeypatch.setattr(ref, "_pipeline", None)
        monkeypatch.setattr(ref, "_guard", None)

        with patch.dict("sys.modules", _BLOCKED_SCANNER_MODULES), caplog.at_level(logging.DEBUG):
            ref._deferred_init()

        messages = [r.message for r in caplog.records]
        assert any("backend missing" in m for m in messages), (
            f"Expected 'backend missing' in logs, got: {messages}"
        )
        assert not any("scanner loaded" in m.lower() for m in messages), (
            f"Should not see 'scanner loaded' with blocked backends: {messages}"
        )

    def test_backend_available_logs_verified(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ref = _import_reference_plugin()
        monkeypatch.setattr(ref, "_config", {})
        monkeypatch.setattr(ref, "_initialized", False)
        monkeypatch.setattr(ref, "_init_error", None)
        monkeypatch.setattr(ref, "_pipeline", None)
        monkeypatch.setattr(ref, "_guard", None)

        with caplog.at_level(logging.DEBUG):
            ref._deferred_init()

        messages = [r.message for r in caplog.records]
        assert not any("scanner loaded" in m.lower() for m in messages), (
            f"Should not see old 'scanner loaded' wording: {messages}"
        )
        assert any("backend verified" in m or "backend missing" in m for m in messages), (
            f"Expected probe-based log ('backend verified' or 'backend missing'), got: {messages}"
        )


# ---------------------------------------------------------------------------
# Tests: plugin_api
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not importlib.util.find_spec("fastapi"),
    reason="fastapi not installed",
)
class TestPluginApiInitLogging:
    def test_backend_missing_logs_probe_verdict(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from petasos.console.hermes import plugin_api

        monkeypatch.setattr(plugin_api, "_handlers", None)
        monkeypatch.setattr(plugin_api, "_load_config", lambda: {})

        with patch.dict("sys.modules", _BLOCKED_SCANNER_MODULES), caplog.at_level(logging.DEBUG):
            plugin_api._self_init()

        messages = [r.message for r in caplog.records]
        assert any("backend missing" in m for m in messages), (
            f"Expected 'backend missing' in logs, got: {messages}"
        )
        assert not any("Dashboard loaded scanner" in m for m in messages), (
            f"Old wording 'Dashboard loaded scanner' should not appear: {messages}"
        )

    def test_backend_available_logs_verified(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from petasos.console.hermes import plugin_api

        monkeypatch.setattr(plugin_api, "_handlers", None)
        monkeypatch.setattr(plugin_api, "_load_config", lambda: {})

        with caplog.at_level(logging.DEBUG):
            plugin_api._self_init()

        messages = [r.message for r in caplog.records]
        assert not any("Dashboard loaded scanner" in m for m in messages), (
            f"Old wording 'Dashboard loaded scanner' should not appear: {messages}"
        )
        assert any("backend verified" in m or "backend missing" in m for m in messages), (
            f"Expected probe-based log ('backend verified' or 'backend missing'), got: {messages}"
        )
