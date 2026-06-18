"""PET-132: trusted live profile-swap re-bind (reference_plugin).

PET-130 pins the gateway's config resolution (``_session_resolution``) once at
``register()`` from the operator-trusted boot environment. PET-132 makes the pin
RE-establishable on a trusted profile change without a process restart: a
``_on_profile_change`` hook (and a re-runnable ``register()``) re-captures the
resolution from the trusted profile home, resets the ``(mtime,size)``-keyed
armed/reload caches, refreshes ``_config``, and hot-applies the new profile's
pipeline config via PET-126's ``_apply_reconfigure`` — all without ever re-reading
the agent-writable ``active_profile`` pointer (PET-125).

Harness mirrors ``test_console_reload.py``: a fresh plugin module per test (isolated
module globals) imported via ``importlib``, trusted ``profile_home`` tmp dirs built
with a ``config.yaml``, a ``_FakeCtx`` capturing ``register_hook`` calls, and an
autouse fixture that resets the SHARED singleton caches the importlib re-import does
not touch (``_armed`` / ``_reload``). Live-pipeline assertions run the dispatched
apply synchronously (the repo's ``_run_async -> asyncio.run`` idiom) so the
non-deterministic loop dispatch does not flake the test.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

import petasos.console._armed as armed_mod
import petasos.console._reload as reload_mod
from petasos.config import PetasosConfig
from petasos.normalize import canonicalize_tool_name
from petasos.pipeline import Pipeline
from petasos.scanners.minimal import MinimalScanner
from petasos.session.frequency import FrequencyTracker
from petasos.session.guard import ToolCallGuard

if TYPE_CHECKING:
    import types
    from collections.abc import Iterator

    from petasos.console._paths import Tier


_REF_PLUGIN_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "deployment"
    / "reference_plugin"
    / "__init__.py"
)


def _import_reference_plugin() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        "petasos_reference_plugin_pet132", str(_REF_PLUGIN_PATH)
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_config(path: Path, petasos_section: dict[str, Any] | None) -> None:
    import yaml

    data: dict[str, Any] = {"model": {"provider": "test"}}
    if petasos_section is not None:
        data["petasos"] = petasos_section
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")


def _profile_home(tmp_path: Path, name: str, section: dict[str, Any] | None) -> Path:
    """Build an absolute profile home ``<tmp>/profiles/<name>`` with a ``config.yaml``."""
    home = tmp_path / "profiles" / name
    _write_config(home / "config.yaml", section)
    return home


def _make_resolution(path: Path, tier: Tier = "profile") -> Any:
    from petasos.console._paths import HermesConfigResolution

    return HermesConfigResolution(path=path, tier=tier)


def _same_config(actual: Path, home: Path) -> bool:
    """True if ``actual`` names ``<home>/config.yaml``, robust to per-platform path
    normalization (the hook path resolve()s the home; the register/HERMES_HOME path does
    not)."""
    return actual.resolve(strict=False) == (home / "config.yaml").resolve(strict=False)


def _install_sync_dispatch(ref: types.ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the dispatched ``_apply_reconfigure`` synchronously (fresh loop) so live-path
    assertions are deterministic — the repo's established ``_run_async -> asyncio.run``
    idiom (``test_console_reload.py``). Exercises the real ``_apply_live`` /
    ``_apply_reconfigure``; only the loop-dispatch mechanism is stubbed."""

    def _sync(cfg: Any, on_success: Any, on_error: Any) -> None:
        try:
            asyncio.run(ref._apply_reconfigure(cfg))
        except Exception as exc:
            on_error(exc)
        else:
            on_success()

    monkeypatch.setattr(ref, "_dispatch_reconfigure", _sync)


def _wire_live(
    ref: types.ModuleType, monkeypatch: pytest.MonkeyPatch, section: dict[str, Any]
) -> tuple[Any, Any]:
    """Build a real live pipeline + guard from ``section`` and mark the module
    initialized, so the re-bind worker takes its live-apply branch deterministically."""
    cfg = ref._build_config_from_section(section)
    pipe = Pipeline(scanners=[MinimalScanner()], config=cfg)
    tracker = FrequencyTracker(cfg)
    guard = ToolCallGuard(pipe, tracker, cfg, lineage=None)
    monkeypatch.setattr(ref, "_pipeline", pipe)
    monkeypatch.setattr(ref, "_guard", guard)
    monkeypatch.setattr(ref, "_lineage_registry", None)
    monkeypatch.setattr(ref, "_initialized", True)
    monkeypatch.setattr(ref, "_init_error", None)
    monkeypatch.setattr(
        ref,
        "_egress_sink_tools",
        frozenset(c for c in (canonicalize_tool_name(t) for t in cfg.egress_sink_tools) if c),
    )
    _install_sync_dispatch(ref, monkeypatch)
    return pipe, guard


class _FakeCtx:
    """Minimal Hermes plugin ctx; captures registered hook names and can reject some."""

    def __init__(self, reject: set[str] | None = None) -> None:
        self.registered: list[str] = []
        self._reject = reject or set()

    def register_hook(self, name: str, handler: object) -> None:
        if name in self._reject:
            raise ValueError(f"unknown hook: {name!r}")
        self.registered.append(name)


@pytest.fixture(autouse=True)
def _reset(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    # The (mtime_ns, size)-keyed singleton caches live in the SHARED _armed / _reload
    # modules, which importlib does not re-import per test — reset so a fresh tmp file
    # can't be served a coincidentally-matching stale key.
    armed_mod._reset_armed_cache()
    reload_mod._reset_reload_cache()
    for var in ("PETASOS_SESSION_SECRET", "PETASOS_HASH_KEY", "PETASOS_LICENSE_KEY"):
        monkeypatch.delenv(var, raising=False)
    yield
    armed_mod._reset_armed_cache()
    reload_mod._reset_reload_cache()


# ── headline + cache coherence ────────────────────────────────────────────────


def test_rebind_honors_new_profile_disarm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression for PET-132: boot-bound to W (enabled:true); a trusted re-bind to X
    # (enabled:false) is honored within one call — _is_armed() False, binding names X,
    # and the next _pre_tool_call passes through.
    ref = _import_reference_plugin()
    w_home = _profile_home(tmp_path, "w", {"enabled": True})
    x_home = _profile_home(tmp_path, "x", {"enabled": False})
    monkeypatch.setattr(ref, "_session_resolution", _make_resolution(w_home / "config.yaml"))
    assert ref._is_armed() is True  # booted armed on W

    ref._on_profile_change(profile_name="x", profile_home=str(x_home))

    assert _same_config(ref._session_resolution.path, x_home)
    assert ref._is_armed() is False
    assert ref._pre_tool_call("shell", {"cmd": "x"}, task_id="s1") is None  # pass-through


def test_rebind_survives_mtime_size_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression for PET-132 (Decision 5): after a W->X re-pin, a stale armed bit cached
    # under a (mtime_ns, size) key that COLLIDES with X's key would, without the cache
    # reset, serve W's value. Simulate that exact collision and assert the re-bind's
    # _reset_armed_cache() makes X's real disarm win over the colliding key.
    ref = _import_reference_plugin()
    w_home = _profile_home(tmp_path, "w", {"enabled": True})
    x_home = _profile_home(tmp_path, "x", {"enabled": False})
    x_res = _make_resolution(x_home / "config.yaml")
    monkeypatch.setattr(ref, "_session_resolution", _make_resolution(w_home / "config.yaml"))

    st = (x_home / "config.yaml").stat()
    x_key = (st.st_mtime_ns, st.st_size)
    # Seed the armed cache as if W's armed bit were cached under X's exact key (collision).
    armed_mod._ARMED_CACHE = (x_key, True, time.monotonic())
    # Control: with the stale entry present, a read at X's key HITS and returns True.
    assert armed_mod.read_armed(x_res) is True

    ref._on_profile_change(profile_name="x", profile_home=str(x_home))

    # The re-bind reset the cache, so X is re-stat'd and its disarm wins over the collision.
    assert ref._is_armed() is False


def test_rebind_reapplies_full_pipeline_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression for PET-132 (Decision 4/5): a live re-bind re-applies the new profile's
    # FULL pipeline config (fail_mode + egress set) via _apply_reconfigure, not just the
    # armed bit; and the on-success commit_seen settles the reload cache so no redundant
    # re-apply is queued on the next call.
    ref = _import_reference_plugin()
    w_section = {"enabled": True, "fail_mode": "degraded", "egress_sink_tools": ["w_tool"]}
    pipe, _guard = _wire_live(ref, monkeypatch, w_section)
    w_home = _profile_home(tmp_path, "w", {"enabled": True, "fail_mode": "degraded"})
    x_home = _profile_home(
        tmp_path, "x", {"enabled": True, "fail_mode": "closed", "egress_sink_tools": ["x_tool"]}
    )
    monkeypatch.setattr(ref, "_session_resolution", _make_resolution(w_home / "config.yaml"))
    assert pipe.config.fail_mode == "degraded"
    assert ref._is_egress_sink("w_tool") is True
    assert ref._is_egress_sink("x_tool") is False

    ref._on_profile_change(profile_name="x", profile_home=str(x_home))

    assert _same_config(ref._session_resolution.path, x_home)
    assert pipe.config.fail_mode == "closed"  # X's pipeline policy is live
    assert ref._is_egress_sink("x_tool") is True  # X's egress set is live
    assert ref._is_egress_sink("w_tool") is False  # W's is gone
    # commit_seen settled the reload cache on X -> the next reconfigure check is a no-op.
    assert reload_mod.read_changed_section(ref._session_resolution) is None


# ── the PET-125 boundary survives the swap ──────────────────────────────────────


def test_rebind_is_operator_trusted_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression for PET-132 / PET-125: the re-bind identity comes ONLY from the trusted
    # payload. An in-session agent rewriting active_profile / HERMES_HOME must not move the
    # binding, and the worker must never consult resolve_hermes_config_path or
    # read_active_profile. A sentinel on both fails the test if the re-bind path hits them.
    import petasos.console._paths as paths_mod

    ref = _import_reference_plugin()
    w_home = _profile_home(tmp_path, "w", {"enabled": True})
    x_home = _profile_home(tmp_path, "x", {"enabled": False})
    monkeypatch.setattr(ref, "_session_resolution", _make_resolution(w_home / "config.yaml"))

    def _boom(*a: Any, **k: Any) -> Any:
        raise AssertionError("re-bind re-derived identity from agent-writable state (PET-125)")

    monkeypatch.setattr(paths_mod, "resolve_hermes_config_path", _boom)
    monkeypatch.setattr(paths_mod, "read_active_profile", _boom)
    # An agent points HERMES_HOME at a profile it controls; the re-bind must ignore it.
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "attacker_controlled"))

    ref._on_profile_change(profile_name="x", profile_home=str(x_home))

    assert _same_config(ref._session_resolution.path, x_home)  # trusted payload, not env
    assert ref._is_armed() is False  # X's disarm, not the attacker's HERMES_HOME


def test_rebind_rejects_unsafe_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Regression for PET-132 (Decision 2/6): empty, relative, file-not-dir, and
    # non-existent profile_home each leave the boot binding intact, stay armed, and emit
    # PETASOS_REBIND_SKIPPED. _session_resolution is never left None.
    ref = _import_reference_plugin()
    w_home = _profile_home(tmp_path, "w", {"enabled": True})
    boot = _make_resolution(w_home / "config.yaml")
    monkeypatch.setattr(ref, "_session_resolution", boot)

    a_file = tmp_path / "a_file"
    a_file.write_text("x", encoding="utf-8")
    bad_inputs: list[Any] = [
        "",  # empty
        "relative/profile",  # relative (non-absolute on every platform)
        str(a_file),  # absolute but a file, not a directory
        str(tmp_path / "does_not_exist"),  # absolute but missing
    ]
    if sys.platform == "win32":
        # A bare backslash-separated relative path is non-absolute on Windows (no drive /
        # UNC root); gated to win32 so it tests Windows separator policy on Windows rather
        # than passing for the wrong reason on POSIX.
        bad_inputs.append("profiles\\gibson")

    for bad in bad_inputs:
        ref._reset_rebind_log()  # each rejection must be independently attributable
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="petasos.plugin"):
            ref._on_profile_change(profile_name="x", profile_home=bad)
        assert ref._session_resolution is boot  # binding object unchanged
        assert ref._is_armed() is True  # stays armed on W
        skipped = [r for r in caplog.records if "PETASOS_REBIND_SKIPPED" in r.getMessage()]
        assert len(skipped) == 1, f"no skip log for {bad!r}"


def test_rebind_to_absolute_windows_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression for PET-132 (brief D-WIN positive path): a well-formed ABSOLUTE profile
    # home (the real Hermes payload shape) is accepted and moves the binding — proving
    # _validated_profile_home does not over-reject absolute homes.
    ref = _import_reference_plugin()
    w_home = _profile_home(tmp_path, "w", {"enabled": True})
    x_home = _profile_home(tmp_path, "gibson", {"enabled": False})
    monkeypatch.setattr(ref, "_session_resolution", _make_resolution(w_home / "config.yaml"))
    assert x_home.is_absolute()  # tmp_path is absolute on every platform

    ref._on_profile_change(profile_name="gibson", profile_home=str(x_home))

    assert _same_config(ref._session_resolution.path, x_home)
    assert ref._is_armed() is False


def test_rebind_to_sectionless_profile_keeps_lastgood(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Regression for PET-132 (Decision 5 / _apply_live None path): re-bind to an X whose
    # config.yaml has NO petasos: section -> the binding moves and _is_armed() reflects X
    # (fail-secure True), the live pipeline keeps W's last-good policy, and a
    # PETASOS_REBIND_CONFIG_STALE line is emitted (never silent).
    ref = _import_reference_plugin()
    pipe, _guard = _wire_live(ref, monkeypatch, {"enabled": True, "fail_mode": "closed"})
    w_home = _profile_home(tmp_path, "w", {"enabled": True, "fail_mode": "closed"})
    x_home = _profile_home(tmp_path, "x", None)  # config.yaml with no petasos: section
    monkeypatch.setattr(ref, "_session_resolution", _make_resolution(w_home / "config.yaml"))
    ref._reset_rebind_log()

    with caplog.at_level(logging.WARNING, logger="petasos.plugin"):
        ref._on_profile_change(profile_name="x", profile_home=str(x_home))

    assert _same_config(ref._session_resolution.path, x_home)  # binding moved
    assert ref._is_armed() is True  # X has no petasos: section -> read_armed fail-secure True
    assert pipe.config.fail_mode == "closed"  # W's last-good pipeline policy kept
    stale = [r for r in caplog.records if "PETASOS_REBIND_CONFIG_STALE" in r.getMessage()]
    assert len(stale) == 1


# ── init-window correctness ─────────────────────────────────────────────────────


def test_rebind_during_init_window_builds_new_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Regression for PET-132 (Decision 3 case 2, both interleavings): the in-_init_lock
    # branch decision is race-free.
    # (a) Worker wins the race (init not yet started): the re-bind stages X into _config
    #     under _init_lock; _deferred_init then builds the pipeline from X, no second
    #     petasos-init thread spawned by the hook path.
    ref = _import_reference_plugin()
    w_home = _profile_home(tmp_path, "w", {"enabled": True, "fail_mode": "degraded"})
    x_home = _profile_home(tmp_path, "x", {"enabled": True, "fail_mode": "closed"})
    monkeypatch.setattr(ref, "_config", {"enabled": True, "fail_mode": "degraded"})
    monkeypatch.setattr(ref, "_initialized", False)
    monkeypatch.setattr(ref, "_init_error", None)
    monkeypatch.setattr(ref, "_pipeline", None)
    monkeypatch.setattr(ref, "_guard", None)
    monkeypatch.setattr(ref, "_session_resolution", _make_resolution(w_home / "config.yaml"))

    with caplog.at_level(logging.INFO, logger="petasos.plugin"):
        ref._on_profile_change(profile_name="x", profile_home=str(x_home))
    pending = [r for r in caplog.records if "PETASOS_REBIND_PENDING_INIT" in r.getMessage()]
    assert len(pending) == 1  # init-window branch taken
    assert _same_config(ref._session_resolution.path, x_home)
    assert ref._config.get("fail_mode") == "closed"  # X staged for _deferred_init
    assert ref._init_thread_started is False  # the hook path spawns no init thread

    ref._deferred_init()  # now let init build from the staged profile
    assert ref._initialized is True
    assert ref._pipeline is not None
    assert ref._pipeline.config.fail_mode == "closed"  # built from X, not W

    # (b) Init completes first, THEN the re-bind fires: the worker observes _initialized
    #     True and takes the live apply, so the pipeline reflects the new profile.
    ref2 = _import_reference_plugin()
    pipe2, _g2 = _wire_live(ref2, monkeypatch, {"enabled": True, "fail_mode": "degraded"})
    w2_home = _profile_home(tmp_path, "w2", {"enabled": True, "fail_mode": "degraded"})
    y_home = _profile_home(tmp_path, "y", {"enabled": True, "fail_mode": "open"})
    monkeypatch.setattr(ref2, "_session_resolution", _make_resolution(w2_home / "config.yaml"))

    ref2._on_profile_change(profile_name="y", profile_home=str(y_home))
    assert _same_config(ref2._session_resolution.path, y_home)
    assert pipe2.config.fail_mode == "open"  # live apply built from Y


def test_rebind_initwindow_malformed_profile_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Regression for PET-132 (Deferred symmetry / attributability): a re-bind during the
    # init window to an X whose petasos: section is non-empty but fails PetasosConfig
    # validation stages X; _deferred_init then falls back to PetasosConfig() defaults. The
    # PENDING_INIT line is honest about the validate-or-defaults fork (this impl did not
    # adopt the optional pre-validate; that option would emit CONFIG_STALE instead).
    ref = _import_reference_plugin()
    w_home = _profile_home(tmp_path, "w", {"enabled": True})
    # redaction_mode is constrained; an invalid value fails _build_config_from_section.
    x_home = _profile_home(tmp_path, "x", {"enabled": True, "redaction_mode": "bogus"})
    monkeypatch.setattr(ref, "_config", {"enabled": True})
    monkeypatch.setattr(ref, "_initialized", False)
    monkeypatch.setattr(ref, "_init_error", None)
    monkeypatch.setattr(ref, "_pipeline", None)
    monkeypatch.setattr(ref, "_guard", None)
    monkeypatch.setattr(ref, "_session_resolution", _make_resolution(w_home / "config.yaml"))

    with caplog.at_level(logging.INFO, logger="petasos.plugin"):
        ref._on_profile_change(profile_name="x", profile_home=str(x_home))
        pending = [r for r in caplog.records if "PETASOS_REBIND_PENDING_INIT" in r.getMessage()]
        assert len(pending) == 1
        ref._deferred_init()

    assert ref._initialized is True
    assert ref._pipeline is not None
    # malformed X -> _deferred_init fell back to PetasosConfig() defaults (fail-secure).
    assert ref._pipeline.config.redaction_mode == PetasosConfig().redaction_mode


def test_session_start_does_not_rebind(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression for PET-132: _on_session_start carries no profile and must never move the
    # binding or re-resolve config (locks out the naive fix).
    import petasos.console._paths as paths_mod

    ref = _import_reference_plugin()
    w_home = _profile_home(tmp_path, "w", {"enabled": True})
    boot = _make_resolution(w_home / "config.yaml")
    monkeypatch.setattr(ref, "_session_resolution", boot)

    def _boom(*a: Any, **k: Any) -> Any:
        raise AssertionError("on_session_start must not re-resolve config")

    monkeypatch.setattr(paths_mod, "resolve_hermes_config_path", _boom)

    ref._on_session_start(session_id="s1", model="m", platform="p")

    assert ref._session_resolution is boot  # binding unchanged


# ── re-runnable register() (forced-rediscovery route) ───────────────────────────


def test_register_idempotent_rebind(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression for PET-132 (Decision 3): two register() calls under different profile
    # homes leave exactly one set of hooks, spawn the init thread once, end on the second
    # profile's config, and leak no prior-profile state.
    ref = _import_reference_plugin()

    spawns: list[str] = []

    class _NoStartThread:
        # Records construction and never runs the target, so init stays deterministic and
        # fast and the spawn count is observable (Decision 3: spawned exactly once).
        def __init__(
            self, *a: Any, target: Any = None, name: str = "", daemon: bool = False, **k: Any
        ) -> None:
            spawns.append(name)

        def start(self) -> None:
            pass

    monkeypatch.setattr(ref.threading, "Thread", _NoStartThread)

    w_home = _profile_home(tmp_path, "w", {"enabled": True, "fail_mode": "degraded"})
    x_home = _profile_home(tmp_path, "x", {"enabled": True, "fail_mode": "closed"})
    ctx = _FakeCtx()

    monkeypatch.setenv("HERMES_HOME", str(w_home))
    ref.register(ctx)
    monkeypatch.setenv("HERMES_HOME", str(x_home))
    ref.register(ctx)  # forced-rediscovery re-register under the new profile env

    for hook in ("pre_tool_call", "post_tool_call", "on_session_start", "on_profile_change"):
        assert ctx.registered.count(hook) == 1  # no duplicate hooks
    assert ref._init_thread_started is True
    assert spawns.count("petasos-init") == 1  # init thread spawned exactly once
    assert _same_config(ref._session_resolution.path, x_home)  # ended on X, no leaked W
    assert ref._config.get("fail_mode") == "closed"


# ── observability + attributability ─────────────────────────────────────────────


def test_rebind_reemits_armed_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Regression for PET-132 (Decision 6): a successful re-bind re-emits
    # PETASOS_ARMED_RESOLUTION tier= path= naming the new profile (mirrors the PET-130
    # boot line) so the active binding stays greppable after a swap.
    ref = _import_reference_plugin()
    w_home = _profile_home(tmp_path, "w", {"enabled": True})
    x_home = _profile_home(tmp_path, "x", {"enabled": True})
    monkeypatch.setattr(ref, "_session_resolution", _make_resolution(w_home / "config.yaml"))

    with caplog.at_level(logging.INFO, logger="petasos.plugin"):
        ref._on_profile_change(profile_name="x", profile_home=str(x_home))

    res_lines = [
        r.getMessage() for r in caplog.records if "PETASOS_ARMED_RESOLUTION" in r.getMessage()
    ]
    assert len(res_lines) == 1
    assert "tier=profile" in res_lines[0]
    assert str((x_home / "config.yaml").resolve(strict=False)) in res_lines[0]


def test_rebind_log_not_suppressed_by_reload_clock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Regression for PET-132 (Decision 6): the re-bind logs use a DEDICATED clock, so a
    # routine PET-126 reload failure cannot suppress a one-shot re-bind attribution line
    # within the same rate-limit window.
    ref = _import_reference_plugin()
    _pipe, _guard = _wire_live(ref, monkeypatch, {"enabled": True, "fail_mode": "degraded"})
    ref._reset_reload_logs()
    ref._reset_rebind_log()

    w_home = _profile_home(tmp_path, "w", {"redaction_mode": "bogus"})
    monkeypatch.setattr(ref, "_session_resolution", _make_resolution(w_home / "config.yaml"))

    with caplog.at_level(logging.WARNING, logger="petasos.plugin"):
        # 1) Routine reload failure on the boot binding (malformed section -> build fails).
        ref._maybe_reconfigure()
        # 2) A re-bind whose new profile is also malformed -> PETASOS_REBIND_CONFIG_STALE,
        #    within the same window. Different clock -> not suppressed.
        x_home = _profile_home(tmp_path, "x", {"redaction_mode": "also_bogus"})
        ref._on_profile_change(profile_name="x", profile_home=str(x_home))

    reload_fail = [r for r in caplog.records if "PETASOS_RELOAD_FAILED" in r.getMessage()]
    rebind_stale = [r for r in caplog.records if "PETASOS_REBIND_CONFIG_STALE" in r.getMessage()]
    assert len(reload_fail) == 1
    assert len(rebind_stale) == 1


# ── concurrency ─────────────────────────────────────────────────────────────────


def test_concurrent_rebinds_converge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression for PET-132 (Decision 7): two re-binds (X then Y) from two threads end
    # with _session_resolution and the live pipeline config in agreement (the last re-pin
    # under _rebind_lock wins for both); and a trailing re-bind whose apply FAILS resets
    # the reload cache (on_error) so a stale committed key cannot suppress the next read.
    ref = _import_reference_plugin()
    pipe, _guard = _wire_live(ref, monkeypatch, {"enabled": True, "fail_mode": "degraded"})
    w_home = _profile_home(tmp_path, "w", {"enabled": True, "fail_mode": "degraded"})
    x_home = _profile_home(tmp_path, "x", {"enabled": True, "fail_mode": "closed"})
    y_home = _profile_home(tmp_path, "y", {"enabled": True, "fail_mode": "open"})
    monkeypatch.setattr(ref, "_session_resolution", _make_resolution(w_home / "config.yaml"))

    barrier = threading.Barrier(2)
    errors: list[Exception] = []

    def _fire(home: Path) -> None:
        try:
            barrier.wait(timeout=2.0)
            ref._on_profile_change(profile_home=str(home))
        except Exception as exc:  # noqa: BLE001 — record, assert empty later
            errors.append(exc)

    t1 = threading.Thread(target=_fire, args=(x_home,))
    t2 = threading.Thread(target=_fire, args=(y_home,))
    t1.start()
    t2.start()
    t1.join(timeout=2.0)
    t2.join(timeout=2.0)
    assert not t1.is_alive() and not t2.is_alive(), "rebind workers did not finish"
    assert errors == [], f"worker errors: {errors!r}"

    expected = {
        (x_home / "config.yaml").resolve(strict=False): "closed",
        (y_home / "config.yaml").resolve(strict=False): "open",
    }
    final = ref._session_resolution.path.resolve(strict=False)
    assert pipe.config.fail_mode == expected[final]  # binding and config agree

    # Sub-case: a trailing re-bind whose apply FAILS must reset the reload cache (on_error),
    # so a stale committed key from a superseded re-bind cannot suppress the next re-read.
    reset_calls = {"n": 0}
    real_reset = reload_mod._reset_reload_cache

    def _counting_reset() -> None:
        reset_calls["n"] += 1
        real_reset()

    def _raise_apply(_cfg: Any) -> Any:
        raise RuntimeError("forced apply failure")

    monkeypatch.setattr(reload_mod, "_reset_reload_cache", _counting_reset)
    monkeypatch.setattr(ref, "_apply_reconfigure", _raise_apply)
    z_home = _profile_home(tmp_path, "z", {"enabled": True, "fail_mode": "closed"})

    ref._on_profile_change(profile_home=str(z_home))

    assert _same_config(ref._session_resolution.path, z_home)  # binding still moved
    # worker-top reset + on_error reset: the failed apply must additionally reset the cache.
    assert reset_calls["n"] >= 2
    assert reload_mod._RELOAD_CACHE is None  # not left committed to a superseded profile


# ── the documented interim contract (no Hermes signal yet) ──────────────────────


def test_no_trusted_signal_means_restart_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Regression for PET-132 (Decision 8): a host whose register_hook rejects
    # on_profile_change degrades cleanly — _try_register_hook returns False, a warning is
    # logged, the boot binding is intact and armed, and register() does not crash.
    ref = _import_reference_plugin()
    monkeypatch.setattr(ref, "_deferred_init", lambda: None)  # neutralize bg thread
    w_home = _profile_home(tmp_path, "w", {"enabled": True})
    monkeypatch.setenv("HERMES_HOME", str(w_home))
    ctx = _FakeCtx(reject={"on_profile_change"})

    with caplog.at_level(logging.WARNING, logger="petasos.plugin"):
        ref.register(ctx)  # must not raise

    assert "on_profile_change" not in ctx.registered
    assert "pre_tool_call" in ctx.registered  # core hooks unaffected
    assert ref._session_resolution is not None
    assert _same_config(ref._session_resolution.path, w_home)  # boot binding intact
    assert ref._is_armed() is True
    rejected = [
        r for r in caplog.records if "register_hook(on_profile_change) rejected" in r.getMessage()
    ]
    assert len(rejected) == 1
