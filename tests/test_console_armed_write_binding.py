"""PET-185: the armed bit always describes the binding the toggle writes.

Regression for PET-185: PET-166 D1 served a scoped ``GET /api/armed`` from the
SELECTED profile's config while the unscoped arm toggle wrote the process
binding's config, so on a ``HERMES_HOME``-pinned dashboard with a named profile
selected an Unequip landed in one file and the banner kept repainting from the
other. ``get_armed`` now sources the bit from the write binding in every scope
state (all five rows of the spec's Design table), keeps ``read_scope``
scope-gated so the client's unscoped-arm predicate cannot oscillate, and leaves
every refusal contract untouched.

Modelled on ``tests/test_console_profile_scoped_reads.py``: same
``HERMES_HOME`` / ``LOCALAPPDATA`` / ``HOME`` monkeypatching, same
``_reset_armed_cache()`` discipline, same ``_assert_under`` path pinning so no
assertion can go vacuous. Handlers are driven directly.
"""

import logging
import os
import platform
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

pytest.importorskip("fastapi")

import petasos.console._armed as armed_mod  # noqa: E402
import petasos.console._paths as paths_mod  # noqa: E402
import petasos.console.server as server_mod  # noqa: E402
from petasos.config import PetasosConfig  # noqa: E402
from petasos.console.server import (  # noqa: E402
    ConsoleHandlers,
    ProfileNotEquippedError,
    ProfileNotFoundError,
)
from petasos.pipeline import Pipeline  # noqa: E402
from petasos.scanners.minimal import MinimalScanner  # noqa: E402

pytestmark = pytest.mark.anyio


def _make_handlers() -> ConsoleHandlers:
    return ConsoleHandlers(
        Pipeline(
            scanners=[MinimalScanner()],
            config=PetasosConfig(fail_mode="degraded"),
            host_id="test-host",
        )
    )


def _write_enabled(cfg: Path, enabled: bool) -> None:
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(f"petasos:\n  enabled: {str(enabled).lower()}\n", encoding="utf-8")
    armed_mod._reset_armed_cache()


class _Env:
    """Hermes root plus two profile homes; ``pin_root`` reproduces the live-box leg."""

    def __init__(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.root = root
        self._monkeypatch = monkeypatch
        self.root_cfg = root / "config.yaml"
        self.alpha_dir = root / "profiles" / "alpha"
        self.beta_dir = root / "profiles" / "beta"
        self.alpha_cfg = self.alpha_dir / "config.yaml"
        self.beta_cfg = self.beta_dir / "config.yaml"
        _write_enabled(self.alpha_cfg, True)
        _write_enabled(self.beta_cfg, True)

    def activate(self, name: str) -> None:
        (self.root / "active_profile").write_text(name, encoding="utf-8")
        armed_mod._reset_armed_cache()

    def pin_root(self) -> None:
        """Pin ``HERMES_HOME`` to the root home (the ``-p default`` dashboard launch).

        Reproduces the live-box precondition: ``resolve_hermes_config_path()``
        returns the root ``config.yaml`` at ``tier="hermes_home"`` while
        ``list_hermes_profiles()`` reports ``is_active=False`` for every member.
        """
        self._monkeypatch.setenv("HERMES_HOME", str(self.root))
        armed_mod._reset_armed_cache()


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[_Env]:
    monkeypatch.delenv("HERMES_HOME", raising=False)
    if platform.system() == "Windows":
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    else:
        monkeypatch.setenv("HOME", str(tmp_path))
    root = paths_mod.hermes_root()
    (root / "profiles").mkdir(parents=True, exist_ok=True)
    e = _Env(root, monkeypatch)
    e.activate("alpha")
    armed_mod._reset_armed_cache()
    try:
        yield e
    finally:
        armed_mod._reset_armed_cache()


def _assert_under(path: str, directory: Path) -> None:
    """Pin a resolved path under the intended home so no assertion goes vacuous."""
    assert os.path.normcase(str(directory)) in os.path.normcase(path)


# ── T1: the live-box repro (the headline regression pin) ─────────────────


async def test_unequip_sticks_on_root_pinned_dashboard(env: _Env) -> None:
    # Regression for PET-185: Unequip on a HERMES_HOME-pinned dashboard with a
    # named profile selected must be visible on the next read of the same route.
    _write_enabled(env.root_cfg, True)
    env.pin_root()
    # The precondition the brief verified on the live box; if this fails the rest
    # of the suite is testing a different configuration.
    scope = server_mod._resolve_read_scope("alpha")
    assert scope.equipped_name is None
    assert scope.state == "not_equipped"
    alpha_before = env.alpha_cfg.read_bytes()

    h = _make_handlers()
    _, ok = await h.set_armed(False)
    assert ok is True
    # The navigate-away-and-back sequence reduced to its two calls.
    assert (await h.get_armed(profile="alpha"))["armed"] is False
    loaded = yaml.safe_load(env.root_cfg.read_text(encoding="utf-8"))
    assert loaded["petasos"]["enabled"] is False
    assert env.alpha_cfg.read_bytes() == alpha_before


# ── T2: read and write address the same file ──────────────────────────────


async def test_read_and_write_resolve_the_same_file(
    env: _Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_enabled(env.root_cfg, True)
    env.pin_root()
    rec: list[paths_mod.HermesConfigResolution] = []
    real = paths_mod.resolve_hermes_config_path

    def _recording() -> paths_mod.HermesConfigResolution:
        res = real()
        rec.append(res)
        return res

    # Patch the symbol AS IMPORTED INTO _armed: that is what makes the test
    # observe the real call each side makes, not a path the test computed itself.
    monkeypatch.setattr(armed_mod, "resolve_hermes_config_path", _recording)

    h = _make_handlers()
    await h.get_armed(profile="alpha")
    await h.set_armed(False)
    # REQUIRED, and the reason the test is not vacuous: with the pre-PET-185
    # read_armed(scope.resolution) in place the read leg short-circuits at
    # _armed.py:73 and never reaches the resolver, leaving one recorded call.
    assert len(rec) == 2
    # Read-then-write by drive order; with the arity assertion this uniquely
    # identifies both legs, so no per-call-site tagging wrapper is needed.
    assert len({os.path.normcase(str(r.path)) for r in rec}) == 1
    _assert_under(str(rec[0].path), env.root)


# ── T3: equipped_name null (the D16 row) ──────────────────────────────────


async def test_null_equipped_name_serves_root_bit_not_selected(env: _Env) -> None:
    _write_enabled(env.root_cfg, True)
    _write_enabled(env.alpha_cfg, False)  # opposed values: no coincidence can pass
    env.pin_root()
    h = _make_handlers()
    assert (await h.get_armed(profile="alpha"))["armed"] is True  # root's bit
    assert (await h.get_armed())["armed"] is True


# ── T4: not_equipped with equipped_name non-null ──────────────────────────


async def test_not_equipped_named_serves_equipped_bit(env: _Env) -> None:
    env.activate("alpha")
    _write_enabled(env.alpha_cfg, True)
    _write_enabled(env.beta_cfg, False)
    h = _make_handlers()
    out = await h.get_armed(profile="beta")
    assert out["armed"] is True  # alpha's bit (the write target), not beta's
    assert out["read_scope"]["state"] == "not_equipped"
    assert out["read_scope"]["equipped"] == "alpha"


# ── T5: the equipped state is unaffected ──────────────────────────────────


async def test_equipped_state_unaffected(env: _Env) -> None:
    env.activate("alpha")
    h = _make_handlers()
    for bit in (True, False):
        _write_enabled(env.alpha_cfg, bit)
        out = await h.get_armed(profile="alpha")
        assert out["armed"] is bit
        assert out["read_scope"]["state"] == "equipped"


# ── T6: the unknown state, non-vacuously ──────────────────────────────────


async def test_unknown_state_serves_ambient_bit(
    env: _Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Force `unknown` the way the existing suite does: unresolvable EQUIPPED path
    # only, both config files fully readable. A genuinely unresolvable path would
    # make read_armed fail its stat() and return the fail-secure True, and the
    # assertion could not distinguish "ambient bit" from "error default".
    env.activate("alpha")
    _write_enabled(env.alpha_cfg, False)  # ambient binding
    _write_enabled(env.beta_cfg, True)  # selected profile, opposed
    real = paths_mod._resolved_normcase
    equipped_cfg = env.alpha_cfg

    def _fake(path: Path) -> str | None:
        if os.path.normcase(str(path)) == os.path.normcase(str(equipped_cfg)):
            return None  # the EQUIPPED side fails to resolve
        return real(path)

    monkeypatch.setattr(server_mod, "_resolved_normcase", _fake)
    h = _make_handlers()
    out = await h.get_armed(profile="beta")
    assert out["read_scope"]["state"] == "unknown"
    # Reachable only by actually reading the ambient file, not the error default.
    assert out["armed"] is False


# ── T7: anti-oscillation pin ──────────────────────────────────────────────


async def test_read_scope_rides_scoped_reads_and_only_scoped_reads(env: _Env) -> None:
    env.activate("alpha")
    h = _make_handlers()
    scoped = await h.get_armed(profile="beta")
    assert "read_scope" in scoped
    unscoped = await h.get_armed()
    assert set(unscoped) == {"armed"}
    assert isinstance(unscoped["armed"], bool)
    # Stable inputs for Pet.armScopeView across consecutive reads; the client-side
    # fixed point itself is the JS suite's to pin.
    again = await h.get_armed(profile="beta")
    assert again["read_scope"] == scoped["read_scope"]


# ── T8: unchanged refusals ────────────────────────────────────────────────


async def test_refusal_contracts_unchanged(env: _Env) -> None:
    # Deliberate duplication of existing coverage: these are the invariants most
    # likely to be collaterally broken by a change in get_armed.
    env.activate("alpha")
    h = _make_handlers()
    with pytest.raises(ProfileNotFoundError):
        await h.get_armed(profile="ghost")
    before = env.beta_cfg.read_bytes()
    with pytest.raises(ProfileNotEquippedError):
        await h.set_armed(False, profile="beta")
    assert env.beta_cfg.read_bytes() == before


# ── T9: the D20 tripwire still fires, exactly once ────────────────────────


async def test_unscoped_read_tripwire_fires_once(
    env: _Env, caplog: pytest.LogCaptureFixture
) -> None:
    env.activate("alpha")  # two profiles, one active, no selector
    h = _make_handlers()
    h._embedded = True
    with caplog.at_level(logging.INFO, logger="petasos.console.server"):
        # Twice on the same handler instance: the latch is per-instance, so a
        # single call would satisfy "not twice" trivially and pin nothing.
        await h.get_armed()
        await h.get_armed()
    hits = [r for r in caplog.records if "PETASOS_SCOPE_UNSCOPED_READ" in r.getMessage()]
    assert len(hits) == 1
    assert hits[0].levelno == logging.INFO
