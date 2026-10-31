"""Two imported plugin copies capture distinct Hermes home overrides."""

from __future__ import annotations

import importlib.util
import logging
import sys
import threading
import types
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

    import pytest

_PLUGIN = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "deployment"
    / "reference_plugin"
    / "__init__.py"
)


class _Ctx:
    def register_hook(self, _name: str, _handler: object) -> None:
        return None


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, _PLUGIN)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _override(monkeypatch: pytest.MonkeyPatch, home: str) -> None:
    mod = types.ModuleType("hermes_constants")

    def _fn() -> str:
        return home

    mod.get_hermes_home_override = _fn  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "hermes_constants", mod)


def _write_enabled(home: Path, enabled: bool) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(
        f"petasos:\n  enabled: {str(enabled).lower()}\n", encoding="utf-8"
    )


def test_two_copies_capture_distinct_homes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each imported copy pins _session_resolution and _is_armed to its own home."""
    monkeypatch.setattr(threading.Thread, "start", lambda self: None)
    left = tmp_path / "left"
    right = tmp_path / "right"
    _write_enabled(left, False)
    _write_enabled(right, True)
    first = _load("petasos_ref_mux_left")
    second = _load("petasos_ref_mux_right")
    _override(monkeypatch, str(left))
    first.register(_Ctx())
    _override(monkeypatch, str(right))
    second.register(_Ctx())
    assert first._session_resolution is not None
    assert second._session_resolution is not None
    assert first._session_resolution.path == left / "config.yaml"
    assert second._session_resolution.path == right / "config.yaml"
    assert first._is_armed() is False
    assert second._is_armed() is True


def test_relative_override_warning_is_once_per_module_copy(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A relative override logs the warning once per plugin module copy."""
    monkeypatch.setattr(threading.Thread, "start", lambda self: None)
    _override(monkeypatch, "rel/home")
    first = _load("petasos_ref_warn_left")
    second = _load("petasos_ref_warn_right")
    with caplog.at_level(logging.WARNING, logger="petasos.plugin"):
        first.register(_Ctx())
        first.register(_Ctx())
        once = [
            r
            for r in caplog.records
            if r.getMessage().startswith("PETASOS_ARMED_RESOLUTION_WARNING ")
        ]
        assert len(once) == 1
        assert "tier=override" in once[0].getMessage()
        assert "reason=not_absolute" in once[0].getMessage()
        second.register(_Ctx())
        twice = [
            r
            for r in caplog.records
            if r.getMessage().startswith("PETASOS_ARMED_RESOLUTION_WARNING ")
        ]
        assert len(twice) == 2
