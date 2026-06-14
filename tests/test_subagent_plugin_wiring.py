"""PET-107: reference-plugin sub-agent hook wiring + graceful degradation.

Precondition 2 of the spec: if the host's ``subagent_start``/``subagent_stop``
hooks are unavailable (or only one of the pair registers), lineage-linked
escalation (A) no-ops (``lineage=None``) and only the delegation fan-out gate (C)
stays active — no edge store is created that would never be drained.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    import types

_REF_PLUGIN_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "deployment"
    / "reference_plugin"
    / "__init__.py"
)


def _import_reference_plugin() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        "petasos_reference_plugin_pet107", str(_REF_PLUGIN_PATH)
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeCtx:
    """Minimal Hermes plugin ctx that can reject named hooks (unknown-hook sim)."""

    def __init__(self, reject: set[str] | None = None) -> None:
        self.registered: list[str] = []
        self._reject = reject or set()

    def register_hook(self, name: str, handler: object) -> None:
        if name in self._reject:
            raise ValueError(f"unknown hook: {name!r}")
        self.registered.append(name)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("PETASOS_LICENSE_KEY", "PETASOS_SESSION_SECRET", "PETASOS_HASH_KEY"):
        monkeypatch.delenv(var, raising=False)


def _prep_init(mod: types.ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "_config", {})
    monkeypatch.setattr(mod, "_initialized", False)
    monkeypatch.setattr(mod, "_init_error", None)
    monkeypatch.setattr(mod, "_pipeline", None)
    monkeypatch.setattr(mod, "_guard", None)


# ---------------------------------------------------------------------------
# register(): hook availability detection
# ---------------------------------------------------------------------------


class TestHookRegistration:
    def test_both_hooks_registered_marks_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ref = _import_reference_plugin()
        monkeypatch.setattr(ref, "_load_config", lambda: {})
        monkeypatch.setattr(ref, "_deferred_init", lambda: None)  # neutralize bg thread
        ctx = _FakeCtx()
        ref.register(ctx)
        assert ref._subagent_hooks_available is True
        assert {"subagent_start", "subagent_stop"} <= set(ctx.registered)

    def test_stop_hook_rejected_degrades_to_C(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ref = _import_reference_plugin()
        monkeypatch.setattr(ref, "_load_config", lambda: {})
        monkeypatch.setattr(ref, "_deferred_init", lambda: None)
        ctx = _FakeCtx(reject={"subagent_stop"})
        ref.register(ctx)
        # start accepted, stop rejected → A NOT entered (start-only mode unsafe)
        assert ref._subagent_hooks_available is False
        assert "subagent_start" in ctx.registered
        assert "subagent_stop" not in ctx.registered
        # core hooks unaffected
        assert "pre_tool_call" in ctx.registered


# ---------------------------------------------------------------------------
# _deferred_init(): wiring honors the availability flag
# ---------------------------------------------------------------------------


class TestDeferredInitWiring:
    def test_subagent_hooks_available_wires_lineage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ref = _import_reference_plugin()
        _prep_init(ref, monkeypatch)
        monkeypatch.setattr(ref, "_subagent_hooks_available", True)
        ref._deferred_init()
        assert ref._lineage_registry is not None
        assert ref._guard is not None
        assert ref._guard._lineage is ref._lineage_registry  # A wired

    def test_lineage_unavailable_degrades_to_C(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ref = _import_reference_plugin()
        _prep_init(ref, monkeypatch)
        monkeypatch.setattr(ref, "_subagent_hooks_available", False)
        ref._deferred_init()
        assert ref._lineage_registry is None  # A no-ops, no edge store created
        assert ref._guard is not None
        assert ref._guard._lineage is None
        # C still active: delegate recognized + fan-out gate enabled
        assert "delegate_task" in ref._guard._delegate_tool_names
        assert ref._guard._config.delegate_fanout_enabled is True


# ---------------------------------------------------------------------------
# Hook handlers respect the trust boundary + lazy registry
# ---------------------------------------------------------------------------


class TestHookHandlers:
    def test_start_handler_noop_before_registry_ready(self) -> None:
        # A subagent_start firing before _deferred_init builds the registry is a
        # safe no-op (no crash).
        ref = _import_reference_plugin()
        assert ref._lineage_registry is None
        ref._subagent_start(parent_session_id="p", child_session_id="c")  # no raise

    def test_handlers_register_and_unregister_edges(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from petasos import LineageRegistry, PetasosConfig

        ref = _import_reference_plugin()
        registry = LineageRegistry(PetasosConfig())
        monkeypatch.setattr(ref, "_lineage_registry", registry)
        ref._subagent_start(parent_session_id="parent", child_session_id="child")
        assert registry.ancestors("child") == ["parent"]
        ref._subagent_stop(child_session_id="child")
        assert registry.ancestors("child") == []

    def test_start_handler_ignores_missing_ids(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from petasos import LineageRegistry, PetasosConfig

        ref = _import_reference_plugin()
        registry = LineageRegistry(PetasosConfig())
        monkeypatch.setattr(ref, "_lineage_registry", registry)
        ref._subagent_start(parent_session_id="", child_session_id="child")
        ref._subagent_start(parent_session_id="parent", child_session_id="")
        assert registry.ancestors("child") == []
