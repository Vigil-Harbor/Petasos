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


# ── PET-130: gateway session-bound armed/reload resolution ───────────────────


class _FakeCtx:
    def __init__(self) -> None:
        self.registered: list[str] = []

    def register_hook(self, name: str, fn: Any) -> None:
        self.registered.append(name)


def _make_resolution(path: Path, tier: Tier) -> Any:
    from petasos.console._paths import HermesConfigResolution

    return HermesConfigResolution(path=path, tier=tier)


def _split_armed(
    tmp_path: Path, *, profile_enabled: bool, root_enabled: bool
) -> tuple[Path, Path]:
    root_cfg = tmp_path / "root" / "config.yaml"
    profile_cfg = tmp_path / "profiles" / "gibson" / "config.yaml"
    _write_config(root_cfg, {"enabled": root_enabled})
    _write_config(profile_cfg, {"enabled": profile_enabled})
    return root_cfg, profile_cfg


def test_reload_shares_session_bound_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression for PET-130: the reload reader pinned to the session's profile reads
    # AND commits against the profile config even when ambient (HERMES_HOME) resolves
    # to root. The negative arm proves the res argument is load-bearing (the peek/
    # commit pairing invariant) rather than passing vacuously.
    root_cfg = tmp_path / "root" / "config.yaml"
    profile_cfg = tmp_path / "profiles" / "gibson" / "config.yaml"
    _write_config(root_cfg, {"profile_name": "root_profile"})
    _write_config(profile_cfg, {"profile_name": "gibson_profile"})
    monkeypatch.setenv("HERMES_HOME", str(root_cfg.parent))  # ambient -> root

    pinned = _make_resolution(profile_cfg, "profile")
    changed = read_changed_section(pinned)
    assert changed is not None
    section, key = changed
    assert section.get("profile_name") == "gibson_profile"  # profile, not root

    commit_seen(key, pinned)
    assert reload_mod._RELOAD_CACHE is not None
    assert reload_mod._RELOAD_CACHE[1].get("profile_name") == "gibson_profile"

    # Drop the res on commit: it re-resolves to ambient root and caches the WRONG
    # section -> the test fails here if the res argument were ever dropped.
    reload_mod._reset_reload_cache()
    commit_seen(key)
    assert reload_mod._RELOAD_CACHE is not None
    assert reload_mod._RELOAD_CACHE[1].get("profile_name") == "root_profile"


def test_profile_disarm_honored_over_global_armed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression for PET-130 (headline): profile disarmed (enabled:false) + global
    # armed (enabled:true); a gateway pinned to the profile reads DISARMED and passes
    # the next tool call through.
    import petasos.console._armed as armed_mod

    ref = _import_reference_plugin()
    root_cfg, profile_cfg = _split_armed(tmp_path, profile_enabled=False, root_enabled=True)
    monkeypatch.setenv("HERMES_HOME", str(root_cfg.parent))  # ambient -> root (armed)
    armed_mod._reset_armed_cache()
    monkeypatch.setattr(ref, "_session_resolution", _make_resolution(profile_cfg, "profile"))
    ref._reset_disarm_log()

    assert ref._is_armed() is False  # pinned to profile -> disarmed
    assert ref._pre_tool_call("shell", {"cmd": "x"}, task_id="s1") is None  # pass-through


def test_disarm_emits_disarmed_log_within_one_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Regression for PET-130: unequipping (profile enabled:false, gateway pinned to it)
    # emits exactly one PETASOS_DISARMED line and passes the very next call through.
    import petasos.console._armed as armed_mod

    ref = _import_reference_plugin()
    _root_cfg, profile_cfg = _split_armed(tmp_path, profile_enabled=False, root_enabled=True)
    armed_mod._reset_armed_cache()
    monkeypatch.setattr(ref, "_session_resolution", _make_resolution(profile_cfg, "profile"))
    ref._reset_disarm_log()

    with caplog.at_level(logging.WARNING, logger="petasos.plugin"):
        assert ref._pre_tool_call("shell", {"cmd": "x"}, task_id="s1") is None

    disarmed = [r for r in caplog.records if "PETASOS_DISARMED" in r.getMessage()]
    assert len(disarmed) == 1


def test_armed_resolution_logged_at_boot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Regression for PET-130 (D2): register() captures the session resolution and emits
    # a greppable line naming tier + path; the logged path equals the config-load path.
    ref = _import_reference_plugin()
    profile_dir = tmp_path / "profiles" / "gibson"
    _write_config(profile_dir / "config.yaml", {"enabled": True})
    monkeypatch.setenv("HERMES_HOME", str(profile_dir))
    monkeypatch.setattr(ref, "_deferred_init", lambda: None)  # neutralize bg thread

    with caplog.at_level(logging.INFO, logger="petasos.plugin"):
        ref.register(_FakeCtx())

    res_lines = [
        r.getMessage() for r in caplog.records if "PETASOS_ARMED_RESOLUTION" in r.getMessage()
    ]
    assert len(res_lines) == 1
    assert "tier=hermes_home" in res_lines[0]
    assert str(profile_dir / "config.yaml") in res_lines[0]

    assert ref._session_resolution is not None
    assert ref._session_resolution.path == profile_dir / "config.yaml"
    load_lines = [
        r.getMessage() for r in caplog.records if "loading config from" in r.getMessage()
    ]
    assert len(load_lines) == 1
    assert str(profile_dir / "config.yaml") in load_lines[0]  # one file, not two


def test_wrong_boot_resolution_stays_armed_and_logs_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Regression for PET-130 (corollary): if the gateway boots under the root/global
    # config (wrong) while the disarm lives in the profile, pinning preserves the wrong
    # file -> stays ARMED, but the D2 boot log names the root path loudly (a one-line
    # diagnosis, not a silent correction). The Hermes-launch fix is out of scope.
    import petasos.console._armed as armed_mod

    ref = _import_reference_plugin()
    root_cfg, _profile_cfg = _split_armed(tmp_path, profile_enabled=False, root_enabled=True)
    armed_mod._reset_armed_cache()
    monkeypatch.setenv("HERMES_HOME", str(root_cfg.parent))  # boots under root
    monkeypatch.setattr(ref, "_deferred_init", lambda: None)

    with caplog.at_level(logging.INFO, logger="petasos.plugin"):
        ref.register(_FakeCtx())

    assert ref._session_resolution is not None
    assert ref._session_resolution.path == root_cfg  # booted under the global config
    assert ref._is_armed() is True  # profile disarm NOT honored under a wrong boot
    res_lines = [
        r.getMessage() for r in caplog.records if "PETASOS_ARMED_RESOLUTION" in r.getMessage()
    ]
    assert len(res_lines) == 1
    assert str(root_cfg) in res_lines[0]  # names the wrong (root) file -> greppable
