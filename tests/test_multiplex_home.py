"""Two imported plugin copies capture distinct Hermes home overrides."""

from __future__ import annotations

import importlib.util
import logging
import os
import sys
import threading
import types
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType

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


def _override(
    monkeypatch: pytest.MonkeyPatch,
    home: str | None,
    *,
    key: object | None = None,
) -> None:
    mod = types.ModuleType("hermes_constants")

    def _fn() -> str | None:
        return home

    mod.get_hermes_home_override = _fn  # type: ignore[attr-defined]
    if key is not None:
        mod.hermes_home_key = key  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "hermes_constants", mod)


def _resolving_key(text: str) -> str:
    return os.path.normcase(str(Path(text).expanduser().resolve()))


def _link_dir(link: Path, real: Path) -> None:
    """Directory symlink, or a junction on Windows without the symlink privilege."""
    try:
        link.symlink_to(real, target_is_directory=True)
        return
    except OSError:
        if os.name != "nt":
            raise
    import _winapi

    _winapi.CreateJunction(str(real), str(link))


def _short_name(path: Path) -> str | None:
    """The Windows 8.3 spelling of ``path``, or None when unavailable."""
    if os.name != "nt":
        return None
    import ctypes

    windll = getattr(ctypes, "windll", None)
    if windll is None:
        return None
    buf = ctypes.create_unicode_buffer(4096)
    if not windll.kernel32.GetShortPathNameW(str(path), buf, 4096):
        return None
    return buf.value if buf.value != str(path) else None


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


def _freeze(monkeypatch: pytest.MonkeyPatch, module: object) -> None:
    monkeypatch.setattr(module.time, "monotonic", lambda: 1000.0)  # type: ignore[attr-defined]


def test_twelve_homes_keep_own_resolution_and_armed_bit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Twelve plugin copies each keep their own config path and armed bit."""
    monkeypatch.setattr(threading.Thread, "start", lambda self: None)
    copies = []
    for index in range(12):
        home = tmp_path / f"home-{index}"
        enabled = index % 2 == 0
        _write_enabled(home, enabled)
        mod = _load(f"petasos_ref_mux_{index}")
        _override(monkeypatch, str(home))
        mod.register(_Ctx())
        copies.append((mod, home, enabled))
    for _pass in range(2):
        for mod, home, enabled in copies:
            assert mod._session_resolution is not None
            assert mod._session_resolution.path == home / "config.yaml"
            assert mod._session_resolution.tier == "override"
            assert mod._is_armed() is enabled


def test_twelve_homes_reload_cache_does_not_false_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second reload pass over twelve unchanged homes returns None."""
    import petasos.console._reload as reload_mod
    from petasos.console._paths import HermesConfigResolution

    _freeze(monkeypatch, reload_mod)
    reload_mod._reset_reload_cache()
    resolutions = []
    for index in range(12):
        cfg = tmp_path / f"h{index}" / "config.yaml"
        cfg.parent.mkdir()
        cfg.write_text("petasos:\n  enabled: true\n", encoding="utf-8")
        resolutions.append(HermesConfigResolution(path=cfg, tier="override"))
    for res in resolutions:
        got = reload_mod.read_changed_section(res)
        assert got is not None
        reload_mod.commit_seen(got[1], res)
    for res in resolutions:
        assert reload_mod.read_changed_section(res) is None


def test_twelve_homes_armed_second_pass_does_not_reparse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Twelve armed homes do not re-parse inside the TTL on the second pass."""
    import petasos.console._armed as armed_mod
    from petasos.console._paths import HermesConfigResolution

    _freeze(monkeypatch, armed_mod)
    armed_mod._reset_armed_cache()
    homes = []
    for index in range(12):
        cfg = tmp_path / f"a{index}" / "config.yaml"
        cfg.parent.mkdir()
        enabled = index % 2 == 0
        cfg.write_text(f"petasos:\n  enabled: {str(enabled).lower()}\n", encoding="utf-8")
        homes.append((HermesConfigResolution(path=cfg, tier="override"), enabled))
    for res, enabled in homes:
        assert armed_mod.read_armed(res) is enabled
    calls = {"n": 0}
    real = armed_mod.__dict__["read_petasos_section"]

    def _counting(res: object) -> object:
        calls["n"] += 1
        return real(res)

    monkeypatch.setattr(armed_mod, "read_petasos_section", _counting)
    for res, enabled in homes:
        assert armed_mod.read_armed(res) is enabled
    assert calls["n"] == 0


def test_two_copies_do_not_share_degraded_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pending approve written on one plugin copy is invisible on the other."""
    monkeypatch.setattr(threading.Thread, "start", lambda self: None)
    first = _load("petasos_ref_pending_a")
    second = _load("petasos_ref_pending_b")
    first._note_degraded_approve_pending("sess", "hs", "turn", "tc")
    assert first._degraded_approve_pending[("hs", "turn", "tc")] == "sess"
    assert ("hs", "turn", "tc") not in second._degraded_approve_pending
    assert first._degraded_approve_pending is not second._degraded_approve_pending


def test_two_copies_do_not_share_disarm_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A disarmed tool call on one copy does not move the other copy's disarm state."""
    monkeypatch.setattr(threading.Thread, "start", lambda self: None)
    left = tmp_path / "disarm-a"
    right = tmp_path / "disarm-b"
    _write_enabled(left, False)
    _write_enabled(right, True)
    first = _load("petasos_ref_disarm_a")
    second = _load("petasos_ref_disarm_b")
    _override(monkeypatch, str(left))
    first.register(_Ctx())
    _override(monkeypatch, str(right))
    second.register(_Ctx())
    assert first._pre_tool_call("shell", {"cmd": "x"}, task_id="s1") is None
    assert first._bypass_counts.get("s1") == 1
    assert first._last_disarm_log != 0.0
    assert second._bypass_counts == {}
    assert second._last_disarm_log == 0.0


def _mismatch_lines(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if "reason=home_mismatch" in r.getMessage()]


def test_hook_mismatch_warns_once_per_pair_and_keeps_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A disarmed hook warns once per home pair and does not move the capture."""
    import petasos.console._paths as paths_mod

    real_resolve = paths_mod.resolve_hermes_config_path
    monkeypatch.setattr(threading.Thread, "start", lambda self: None)
    home_a = tmp_path / "warn-a"
    home_b = tmp_path / "warn-b"
    home_c = tmp_path / "warn-c"
    for home, enabled in ((home_a, False), (home_b, True), (home_c, False)):
        _write_enabled(home, enabled)
    first = _load("petasos_ref_mismatch_a")
    _override(monkeypatch, str(home_a))
    first.register(_Ctx())
    captured = first._session_resolution
    calls = {"n": 0}

    def _boom(*_args: object, **_kwargs: object) -> None:
        calls["n"] += 1
        raise RuntimeError("resolve_hermes_config_path called")

    monkeypatch.setattr(paths_mod, "resolve_hermes_config_path", _boom)
    _override(monkeypatch, str(home_b))
    with caplog.at_level(logging.WARNING, logger="petasos.plugin"):
        first._pre_tool_call("shell", {"cmd": "x"}, task_id="s1")
        first._pre_tool_call("shell", {"cmd": "y"}, task_id="s1")
        assert len(_mismatch_lines(caplog)) == 1
    assert first._session_resolution is captured
    assert captured is not None
    assert captured.path == home_a / "config.yaml"
    assert first._is_armed() is False
    assert calls["n"] == 0
    monkeypatch.setattr(paths_mod, "resolve_hermes_config_path", real_resolve)
    second = _load("petasos_ref_mismatch_c")
    _override(monkeypatch, str(home_c))
    second.register(_Ctx())
    _override(monkeypatch, str(home_b))
    with caplog.at_level(logging.WARNING, logger="petasos.plugin"):
        second._pre_tool_call("shell", {"cmd": "z"}, task_id="s2")
        assert len(_mismatch_lines(caplog)) == 2


def test_hook_mismatch_silent_when_home_matches_or_probe_is_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A matching override or a missing override logs no home-mismatch warning."""
    monkeypatch.setattr(threading.Thread, "start", lambda self: None)
    home = tmp_path / "same"
    _write_enabled(home, False)
    mod = _load("petasos_ref_mismatch_same")
    _override(monkeypatch, str(home))
    mod.register(_Ctx())
    with caplog.at_level(logging.WARNING, logger="petasos.plugin"):
        mod._pre_tool_call("shell", {"cmd": "x"}, task_id="s1")
        assert _mismatch_lines(caplog) == []
        _override(monkeypatch, None)
        mod._pre_tool_call("shell", {"cmd": "y"}, task_id="s1")
        assert _mismatch_lines(caplog) == []


def test_hook_mismatch_symlink_home_does_not_warn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A symlink whose resolved key matches the capture logs no mismatch warning."""
    monkeypatch.setattr(threading.Thread, "start", lambda self: None)
    real = tmp_path / "real"
    link = tmp_path / "link"
    _write_enabled(real, False)
    _link_dir(link, real)
    mod = _load("petasos_ref_mismatch_link")
    _override(monkeypatch, str(real.resolve()), key=_resolving_key)
    mod.register(_Ctx())
    _override(monkeypatch, str(link), key=_resolving_key)
    with caplog.at_level(logging.WARNING, logger="petasos.plugin"):
        mod._pre_tool_call("shell", {"cmd": "x"}, task_id="s1")
        assert _mismatch_lines(caplog) == []


def test_hook_mismatch_tilde_hermes_home_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A ~/ HERMES_HOME capture warns against the expanded hook home."""
    monkeypatch.setattr(threading.Thread, "start", lambda self: None)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    home = tmp_path / "tilde-home"
    _write_enabled(home, False)
    # read_armed stats the unexpanded capture. That path is relative, so the
    # file has to exist from this cwd or the read fails secure and the stubbed
    # init thread never finishes.
    _write_enabled(tmp_path / "~" / "tilde-home", False)
    monkeypatch.setenv("HERMES_HOME", "~/tilde-home")
    mod = _load("petasos_ref_mismatch_tilde")
    _override(monkeypatch, None)
    mod.register(_Ctx())
    captured = mod._session_resolution
    assert captured is not None
    assert captured.tier == "hermes_home"
    _override(monkeypatch, str(home))
    with caplog.at_level(logging.WARNING, logger="petasos.plugin"):
        mod._pre_tool_call("shell", {"cmd": "x"}, task_id="s1")
        lines = _mismatch_lines(caplog)
        assert len(lines) == 1
        message = lines[0].getMessage()
        assert f"captured={captured.path.parent}" in message
        assert f"hook={home}" in message
    assert mod._session_resolution is captured
    assert not captured.path.is_absolute()


def test_hook_mismatch_absent_path_is_not_memoized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """An absent hook path is not memoized, and a later existing path stores the captured key."""
    monkeypatch.setattr(threading.Thread, "start", lambda self: None)
    real = tmp_path / "absent-real"
    missing = tmp_path / "absent-link"
    _write_enabled(real, False)
    mod = _load("petasos_ref_mismatch_absent")
    _override(monkeypatch, str(real.resolve()), key=_resolving_key)
    mod.register(_Ctx())
    captured_key = _resolving_key(str(real.resolve()))
    _override(monkeypatch, str(missing), key=_resolving_key)
    with caplog.at_level(logging.WARNING, logger="petasos.plugin"):
        mod._pre_tool_call("shell", {"cmd": "x"}, task_id="s1")
    assert str(missing) not in mod._home_mismatch_key_memo
    _link_dir(missing, real)
    with caplog.at_level(logging.WARNING, logger="petasos.plugin"):
        mod._pre_tool_call("shell", {"cmd": "y"}, task_id="s1")
    assert mod._home_mismatch_key_memo[str(missing)] == captured_key


def test_hook_mismatch_captured_through_link_does_not_warn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A home captured through a link keys like its target, so neither spelling warns."""
    monkeypatch.setattr(threading.Thread, "start", lambda self: None)
    real = tmp_path / "captured-real"
    link = tmp_path / "captured-link"
    _write_enabled(real, False)
    _link_dir(link, real)
    mod = _load("petasos_ref_mismatch_captured_link")
    _override(monkeypatch, str(link), key=_resolving_key)
    mod.register(_Ctx())
    captured = mod._session_resolution
    assert captured is not None
    assert captured.path == link / "config.yaml"
    with caplog.at_level(logging.WARNING, logger="petasos.plugin"):
        mod._pre_tool_call("shell", {"cmd": "x"}, task_id="s1")
        _override(monkeypatch, str(real), key=_resolving_key)
        mod._pre_tool_call("shell", {"cmd": "y"}, task_id="s1")
        assert _mismatch_lines(caplog) == []
    assert mod._session_resolution is captured


def test_hook_mismatch_fallback_key_resolves_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Without hermes_home_key, the fallback key still resolves a linked hook home."""
    monkeypatch.setattr(threading.Thread, "start", lambda self: None)
    real = tmp_path / "fallback-real"
    link = tmp_path / "fallback-link"
    _write_enabled(real, False)
    _link_dir(link, real)
    mod = _load("petasos_ref_mismatch_fallback")
    _override(monkeypatch, str(real))
    mod.register(_Ctx())
    _override(monkeypatch, str(link))
    with caplog.at_level(logging.WARNING, logger="petasos.plugin"):
        mod._pre_tool_call("shell", {"cmd": "x"}, task_id="s1")
        assert _mismatch_lines(caplog) == []


@pytest.mark.skipif(os.name != "nt", reason="Windows path spellings")
def test_hook_mismatch_windows_spellings_do_not_warn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Case, slash direction and the 8.3 short name of the captured home never warn."""
    monkeypatch.setattr(threading.Thread, "start", lambda self: None)
    real = tmp_path / "Spelled-Home"
    _write_enabled(real, False)
    mod = _load("petasos_ref_mismatch_spellings")
    _override(monkeypatch, str(real), key=_resolving_key)
    mod.register(_Ctx())
    spellings = [str(real).upper().replace(os.sep, "/"), str(real).lower()]
    short = _short_name(real)
    if short is not None:
        spellings.append(short)
    with caplog.at_level(logging.WARNING, logger="petasos.plugin"):
        for spelling in spellings:
            _override(monkeypatch, spelling, key=_resolving_key)
            mod._pre_tool_call("shell", {"cmd": "x"}, task_id="s1")
        assert _mismatch_lines(caplog) == []
