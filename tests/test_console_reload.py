"""PET-126: cross-process config reload (petasos.console._reload) + gateway wiring.

The _reload unit tests drive ``read_changed_section`` / ``commit_seen`` against a
tmp config via ``HERMES_HOME`` (tier-1 resolution; no real Hermes install). The
gateway tests import the reference plugin and exercise ``_build_config_from_section``
and ``_maybe_reconfigure`` (two-phase apply, fail-safe keep-last-good).
"""

from __future__ import annotations

import asyncio
import base64
import importlib.util
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

import petasos.console._reload as reload_mod
from petasos.config import PetasosConfig
from petasos.console._reload import commit_seen, read_changed_section
from petasos.pipeline import Pipeline
from petasos.scanners.minimal import MinimalScanner
from petasos.session.frequency import FrequencyTracker
from petasos.session.guard import ToolCallGuard

if TYPE_CHECKING:
    import types
    from collections.abc import Iterator


_REF_PLUGIN_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "deployment"
    / "reference_plugin"
    / "__init__.py"
)


def _import_reference_plugin() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        "petasos_reference_plugin_pet126", str(_REF_PLUGIN_PATH)
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


@pytest.fixture(autouse=True)
def _reset(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    # Cache is keyed by (mtime_ns, size), not path — reset so a fresh tmp file
    # can't be served a coincidentally-matching stale key.
    reload_mod._reset_reload_cache()
    for var in ("PETASOS_SESSION_SECRET", "PETASOS_HASH_KEY", "PETASOS_LICENSE_KEY"):
        monkeypatch.delenv(var, raising=False)
    yield
    reload_mod._reset_reload_cache()


@pytest.fixture()
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    return tmp_path / "config.yaml"


# ── _reload: change detection + peek/commit ──────────────────────────────────


def test_reload_picks_up_changed_section_within_ttl(cfg: Path) -> None:
    _write_config(cfg, petasos_section={"profile_name": "general"})
    res = read_changed_section()
    assert res is not None
    section, _key = res
    assert section.get("profile_name") == "general"


def test_reload_ignores_unchanged_file(cfg: Path) -> None:
    _write_config(cfg, petasos_section={"profile_name": "general"})
    res = read_changed_section()
    assert res is not None
    commit_seen(res[1])
    # Same (mtime, size) within TTL after a commit -> no change.
    assert read_changed_section() is None


def test_reload_apply_failure_reattempts(cfg: Path) -> None:
    # Regression for PET-126 (edge-cases F-2): without commit_seen the same change
    # is re-offered, so a failed apply can never silently pin a stale config.
    _write_config(cfg, petasos_section={"profile_name": "general"})
    r1 = read_changed_section()
    assert r1 is not None
    r2 = read_changed_section()  # no commit -> re-attempt
    assert r2 is not None
    assert r2[1] == r1[1]
    commit_seen(r1[1])
    assert read_changed_section() is None  # committed -> quiet


def test_reload_same_size_same_tick_change_observed(
    cfg: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    # TTL=0 so the section-compare (not the mtime/size key) is the change signal.
    monkeypatch.setattr(reload_mod, "_RELOAD_TTL_S", 0.0)
    _write_config(cfg, petasos_section={"profile_name": "general"})
    res1 = read_changed_section()
    assert res1 is not None
    commit_seen(res1[1])
    st = cfg.stat()

    # Rewrite to a same-byte-size value, then force the same mtime tick.
    _write_config(cfg, petasos_section={"profile_name": "relaxed"})
    os.utime(cfg, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert cfg.stat().st_size == st.st_size

    res2 = read_changed_section()
    assert res2 is not None
    assert res2[0].get("profile_name") == "relaxed"


def test_reload_empty_section_is_noop(cfg: Path) -> None:
    # A wiped petasos: section (Windows UI model switcher, D-WIN) is "no change".
    _write_config(cfg, petasos_section={})
    assert read_changed_section() is None
    assert reload_mod._RELOAD_CACHE is None  # key not advanced


def test_reload_wiped_section_keeps_last_good(cfg: Path) -> None:
    _write_config(cfg, petasos_section={"profile_name": "general"})
    res = read_changed_section()
    assert res is not None
    commit_seen(res[1])
    # The model switcher removes the petasos: section entirely.
    _write_config(cfg, petasos_section=None)
    assert read_changed_section() is None  # last-good kept, never reset to defaults


def test_reload_malformed_yaml_keeps_last_good(cfg: Path) -> None:
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("petasos: : : not valid yaml ::\n", encoding="utf-8")
    assert read_changed_section() is None


def test_reload_and_armed_resolve_same_path() -> None:
    # Both caches must anchor on the SAME resolver so write and read never diverge.
    import petasos.console._armed as armed_mod

    reload_fn = reload_mod.resolve_hermes_config_path  # type: ignore[attr-defined]
    armed_fn = armed_mod.resolve_hermes_config_path  # type: ignore[attr-defined]
    assert reload_fn is armed_fn


# ── gateway: _build_config_from_section env overlay (Decision 10) ─────────────


def test_build_config_from_section_preserves_env_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = _import_reference_plugin()
    secret = b"x" * 32
    monkeypatch.setenv("PETASOS_SESSION_SECRET", base64.b64encode(secret).decode())
    monkeypatch.setenv("PETASOS_HASH_KEY", "secret-key")

    built = ref._build_config_from_section({"redaction_mode": "hash", "anonymize": True})
    assert built.session_secret == secret
    assert built.hash_key == "secret-key"
    assert built.anonymize is True  # hash_key present -> no defang

    # Without hash_key, a redaction_mode=hash section downgrades to anonymize=False
    # (matching boot), rather than raising.
    monkeypatch.delenv("PETASOS_HASH_KEY", raising=False)
    downgraded = ref._build_config_from_section({"redaction_mode": "hash", "anonymize": True})
    assert downgraded.anonymize is False
    assert downgraded.redaction_mode == "hash"


# ── gateway: _maybe_reconfigure two-phase apply + fail-safe ───────────────────


def _wire_gateway(
    ref: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> tuple[Pipeline, ToolCallGuard]:
    cfg = PetasosConfig(fail_mode="degraded")
    pipe = Pipeline(scanners=[MinimalScanner()], config=cfg)
    tracker = FrequencyTracker(cfg)
    guard = ToolCallGuard(pipe, tracker, cfg, lineage=None)
    monkeypatch.setattr(ref, "_pipeline", pipe)
    monkeypatch.setattr(ref, "_guard", guard)
    monkeypatch.setattr(ref, "_lineage_registry", None)
    monkeypatch.setattr(ref, "_initialized", True)
    # Run the apply coroutine inline instead of on the background loop thread.
    monkeypatch.setattr(ref, "_run_async", lambda coro: asyncio.run(coro))
    return pipe, guard


def test_maybe_reconfigure_applies_pipeline_and_guard_atomically(
    cfg: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ref = _import_reference_plugin()
    pipe, guard = _wire_gateway(ref, monkeypatch)

    # A clean change applies to BOTH the pipeline and the guard (Decision 4).
    _write_config(cfg, petasos_section={"fail_mode": "closed"})
    ref._maybe_reconfigure()
    assert pipe.config.fail_mode == "closed"
    assert guard._config.fail_mode == "closed"

    # A config that passes from_dict but fails guard.validate_config (malformed
    # frequency_weights) aborts in phase 1 -> neither object is mutated.
    reload_mod._reset_reload_cache()
    before_pipe = pipe.config
    before_guard = guard._config
    _write_config(cfg, petasos_section={"frequency_weights": {"x": -1.0}})
    ref._maybe_reconfigure()
    assert pipe.config is before_pipe
    assert guard._config is before_guard


def test_reload_failure_log_rate_limited(
    cfg: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    ref = _import_reference_plugin()
    ref._reset_reload_logs()
    # A persistently-malformed section re-detects every call (never committed).
    _write_config(cfg, petasos_section={"redaction_mode": "bogus"})

    with caplog.at_level(logging.WARNING, logger="petasos.plugin"):
        ref._maybe_reconfigure()
        ref._maybe_reconfigure()
        ref._maybe_reconfigure()

    fails = [r for r in caplog.records if "PETASOS_RELOAD_FAILED" in r.getMessage()]
    assert len(fails) == 1  # rate-limited to one per 30s window, not one per call
