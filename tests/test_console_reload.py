"""PET-126: cross-process config reload (petasos.console._reload).

The tests drive ``read_changed_section`` / ``commit_seen`` against a tmp config
via ``HERMES_HOME`` (tier-1 resolution; no real Hermes install).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import pytest

import petasos.console._reload as reload_mod
from petasos.console._reload import commit_seen, read_changed_section

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


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
    for var in ("PETASOS_SESSION_SECRET", "PETASOS_HASH_KEY"):
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
    assert reload_mod._RELOAD_CACHE == {}  # key not advanced


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


def test_reload_cache_slots_are_per_path(tmp_path: Path) -> None:
    """Two paths that share a stat key each report their own section."""
    from petasos.hermes.home import HermesConfigResolution

    def _write(path: Path, name: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Same byte length so a forced mtime can collide the stat key.
        path.write_text(f"petasos:\n  profile_name: {name}\n", encoding="utf-8")

    left = tmp_path / "left" / "config.yaml"
    right = tmp_path / "right" / "config.yaml"
    _write(left, "aaaa")
    _write(right, "bbbb")
    stamp = left.stat()
    os.utime(right, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    assert left.stat().st_size == right.stat().st_size
    assert left.stat().st_mtime_ns == right.stat().st_mtime_ns

    left_res = HermesConfigResolution(path=left, tier="hermes_home")
    right_res = HermesConfigResolution(path=right, tier="profile")
    got_left = read_changed_section(left_res)
    got_right = read_changed_section(right_res)
    assert got_left is not None and got_right is not None
    assert got_left[0].get("profile_name") == "aaaa"
    assert got_right[0].get("profile_name") == "bbbb"
    assert isinstance(got_left[1], tuple)
    assert len(got_left[1]) == 2
    assert all(isinstance(part, int) for part in got_left[1])
    commit_seen(got_left[1], left_res)
    commit_seen(got_right[1], right_res)
    reload_mod._reset_reload_cache()
    assert reload_mod._RELOAD_CACHE == {}


def test_reload_and_armed_resolve_same_path() -> None:
    # Both caches must anchor on the SAME resolver so write and read never diverge.
    import petasos.console._armed as armed_mod

    reload_fn = reload_mod.resolve_hermes_config_path  # type: ignore[attr-defined]
    armed_fn = armed_mod.resolve_hermes_config_path  # type: ignore[attr-defined]
    assert reload_fn is armed_fn
