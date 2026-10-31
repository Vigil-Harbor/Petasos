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
# PET-236: load identity
# ---------------------------------------------------------------------------


class _NoHooksCtx:
    def register_hook(self, *_args: object, **_kwargs: object) -> None:
        return None


def _identity_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if "PETASOS_PLUGIN_IDENTITY" in r.getMessage()]


def _register_without_init_thread(ref: types.ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    class _Thread:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            return None

        def start(self) -> None:
            return None

    monkeypatch.setattr(ref.threading, "Thread", _Thread)
    ref.register(_NoHooksCtx())


def test_register_logs_one_identity_line_per_call(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    ref = _import_reference_plugin()
    with caplog.at_level(logging.INFO, logger="petasos.plugin"):
        _register_without_init_thread(ref, monkeypatch)
        assert len(_identity_lines(caplog)) == 1
        _register_without_init_thread(ref, monkeypatch)
    lines = _identity_lines(caplog)
    assert len(lines) == 2
    assert str(_REF_PLUGIN_PATH.parent) in lines[0]
    assert lines[0].rsplit("sha256=", 1)[1] != "unavailable"


def test_identity_hash_read_error_logs_unavailable_and_register_continues(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    ref = _import_reference_plugin()
    real_read = Path.read_bytes

    def fail_on_plugin(self: Path) -> bytes:
        if self.name == "__init__.py":
            raise OSError("denied")
        return real_read(self)

    monkeypatch.setattr(Path, "read_bytes", fail_on_plugin)
    with caplog.at_level(logging.INFO, logger="petasos.plugin"):
        _register_without_init_thread(ref, monkeypatch)
    assert _identity_lines(caplog)[0].endswith("sha256=unavailable")
    assert ref._hooks_registered is True


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
        assert any("backend unusable" in m for m in messages), (
            f"Expected 'backend unusable' in logs, got: {messages}"
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
        assert any("backend verified" in m or "backend unusable" in m for m in messages), (
            f"Expected probe-based log ('backend verified' or 'backend unusable'), got: {messages}"
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
        assert any("backend unusable" in m for m in messages), (
            f"Expected 'backend unusable' in logs, got: {messages}"
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
        assert any("backend verified" in m or "backend unusable" in m for m in messages), (
            f"Expected probe-based log ('backend verified' or 'backend unusable'), got: {messages}"
        )
