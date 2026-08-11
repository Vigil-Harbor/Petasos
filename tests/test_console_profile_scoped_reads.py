"""PET-166: profile-scoped console read surfaces.

Two-profile isolation, the 422/409 validation contracts, the non-destructive
bounded non-equipped read, sink/spool merge and dedup, the `foreign` attestation
domain, cursor scope-binding, and the binding-state matrix.

The module installs its own fixture that CLEARS the two autouse path overrides
from ``tests/conftest.py``. Both win unconditionally by design (so existing
single-binding tests are unaffected), which means a scoped read here would never
touch a real profile home: the isolation tests would fail confusingly and the
non-destructive / branch-parity tests would pass vacuously against the shared
override file. It also clears ``HERMES_HOME``, because
``resolve_hermes_config_path()`` checks that variable FIRST and an inherited
machine-scope pin (exactly what the field report found) would put the binding
outside the temp root and invert every isolation test's premise.
"""

import json
import math
import os
import platform
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")

import petasos.console._armed as armed_mod  # noqa: E402
import petasos.console._events as events_mod  # noqa: E402
import petasos.console._history as history_mod  # noqa: E402
import petasos.console._paths as paths_mod  # noqa: E402
import petasos.console.server as server_mod  # noqa: E402
from petasos.config import PetasosConfig  # noqa: E402
from petasos.console.server import (  # noqa: E402
    ConsoleHandlers,
    CursorScopeMismatchError,
    ProfileNotEquippedError,
    ProfileNotFoundError,
)
from petasos.pipeline import Pipeline  # noqa: E402
from petasos.scanners.minimal import MinimalScanner  # noqa: E402

pytestmark = pytest.mark.anyio

_SCOPED_ROUTES = ("scan-history", "armed-get", "armed-post", "health", "events")


def _sign(rec: dict[str, Any], key: bytes) -> str:
    """Stamp the same HMAC the spool writer does (mirrors _events.verify_event)."""
    import hashlib
    import hmac

    rest = {k: v for k, v in rec.items() if k != "sig"}
    preimage = json.dumps(rest, sort_keys=True, separators=(",", ":"), default=str)
    return hmac.new(key, preimage.encode("utf-8"), hashlib.sha256).hexdigest()


def _make_handlers(secret: bytes | None = None) -> ConsoleHandlers:
    return ConsoleHandlers(
        Pipeline(
            scanners=[MinimalScanner()],
            config=PetasosConfig(fail_mode="degraded", session_secret=secret),
            host_id="test-host",
        )
    )


def _sink_row(scan_id: str, ts: float, **extra: Any) -> dict[str, Any]:
    row: dict[str, Any] = {"scan_id": scan_id, "timestamp": ts, "safe": True, "source": "scan"}
    row.update(extra)
    return row


def _spool_event(scan_id: str, ts: float, **extra: Any) -> dict[str, Any]:
    ev: dict[str, Any] = {
        "scan_id": scan_id,
        "timestamp": ts,
        "event_type": "block",
        "session_id": "s1",
        "tool": "write_file",
    }
    ev.update(extra)
    return ev


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


class _Home:
    """One profile home plus writers for its four read segments."""

    def __init__(self, root: Path, name: str) -> None:
        self.name = name
        self.dir = root / "profiles" / name
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "config.yaml").write_text("petasos:\n  enabled: true\n", encoding="utf-8")

    @property
    def sink(self) -> Path:
        return self.dir / "petasos-scan-history.jsonl"

    @property
    def spool(self) -> Path:
        return self.dir / "petasos-enforcement.jsonl"

    def set_armed(self, armed: bool) -> None:
        (self.dir / "config.yaml").write_text(
            f"petasos:\n  enabled: {str(armed).lower()}\n", encoding="utf-8"
        )
        armed_mod._reset_armed_cache()

    def seed(
        self,
        sink: list[dict[str, Any]] | None = None,
        sink_rot: list[dict[str, Any]] | None = None,
        spool: list[dict[str, Any]] | None = None,
        spool_rot: list[dict[str, Any]] | None = None,
    ) -> None:
        if sink:
            _write_jsonl(self.sink, sink)
        if sink_rot:
            _write_jsonl(Path(str(self.sink) + ".rot"), sink_rot)
        if spool:
            _write_jsonl(self.spool, spool)
        if spool_rot:
            _write_jsonl(Path(str(self.spool) + ".rot"), spool_rot)


class _Env:
    def __init__(self, root: Path, alpha: _Home, beta: _Home) -> None:
        self.root = root
        self.alpha = alpha
        self.beta = beta

    def activate(self, name: str) -> None:
        (self.root / "active_profile").write_text(name, encoding="utf-8")
        armed_mod._reset_armed_cache()


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[_Env]:
    # Clear both autouse overrides so a scoped read reaches a real profile home,
    # restoring them on teardown (they are module globals the conftest fixtures
    # also restore, so ordering is safe either way).
    saved_spool = paths_mod._SPOOL_PATH_OVERRIDE
    saved_hist = history_mod._HISTORY_PATH_OVERRIDE
    saved_cap = server_mod._FOREIGN_SPOOL_READ_CAP
    paths_mod._SPOOL_PATH_OVERRIDE = None
    history_mod._HISTORY_PATH_OVERRIDE = None

    monkeypatch.delenv("HERMES_HOME", raising=False)
    if platform.system() == "Windows":
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    else:
        monkeypatch.setenv("HOME", str(tmp_path))
    root = paths_mod.hermes_root()
    (root / "profiles").mkdir(parents=True, exist_ok=True)
    e = _Env(root, _Home(root, "alpha"), _Home(root, "beta"))
    e.activate("alpha")
    armed_mod._reset_armed_cache()
    try:
        yield e
    finally:
        paths_mod._SPOOL_PATH_OVERRIDE = saved_spool
        history_mod._HISTORY_PATH_OVERRIDE = saved_hist
        server_mod._FOREIGN_SPOOL_READ_CAP = saved_cap
        armed_mod._reset_armed_cache()


def _assert_under(path: str, home: _Home) -> None:
    """Every isolation assertion also pins the resolved path under the intended
    home, so a re-armed override can never make one vacuous."""
    assert os.path.normcase(str(home.dir)) in os.path.normcase(path)


# ── Isolation, merge, and bounds ──────────────────────────────────────────


async def test_scan_history_serves_selected_profile(env: _Env) -> None:
    env.alpha.seed(sink=[_sink_row("s-alpha", 100.0)])
    env.beta.seed(sink=[_sink_row("s-beta", 200.0)])
    h = _make_handlers()
    beta_res = paths_mod.resolve_profile_config_path("beta")
    _assert_under(history_mod._history_path(beta_res), env.beta)

    out = await h.get_scan_history(profile="beta")
    ids = [r["scan_id"] for r in out["entries"]]
    assert ids == ["s-beta"]
    assert out["read_scope"]["state"] == "not_equipped"
    assert out["read_scope"]["selected"] == "beta"
    assert out["read_scope"]["equipped"] == "alpha"
    assert out["read_scope"]["live"] is False


async def test_scan_history_absent_profile_is_unchanged(env: _Env) -> None:
    # D2, the byte-identity fence: no parameter -> the equipped ring window with the
    # pre-change keys, an UNPREFIXED next_before, and none of the new keys.
    h = _make_handlers()
    h._record_scan({"scan_id": "s-ring", "timestamp": 500.0, "safe": True})
    out = await h.get_scan_history()
    assert set(out) == {"entries", "next_before", "older_truncated"}
    assert [r["scan_id"] for r in out["entries"]] == ["s-ring"]
    assert out["next_before"] is not None and "|" not in out["next_before"]


async def test_non_equipped_read_is_non_destructive(env: _Env) -> None:
    env.beta.seed(spool=[_spool_event("e-b1", 10.0)], spool_rot=[_spool_event("e-b2", 5.0)])
    rot = Path(str(env.beta.spool) + ".rot")
    before_live = env.beta.spool.read_bytes()
    before_rot = rot.read_bytes()
    h = _make_handlers()
    off_before = h._enforcement_offset

    await h.get_scan_history(profile="beta")

    assert env.beta.spool.read_bytes() == before_live
    assert rot.exists() and rot.read_bytes() == before_rot
    assert h._enforcement_offset == off_before
    assert not env.beta.sink.exists()  # nothing appended to beta


async def test_non_equipped_read_includes_rotated_spool(env: _Env) -> None:
    env.beta.seed(spool_rot=[_spool_event("e-rot", 7.0)])
    rot = Path(str(env.beta.spool) + ".rot")
    h = _make_handlers()
    out = await h.get_scan_history(profile="beta")
    assert [r["scan_id"] for r in out["entries"]] == ["e-rot"]
    assert rot.exists()


async def test_equipped_drain_still_runs_under_a_scoped_read(env: _Env) -> None:
    # D3: the drain is hoisted above the branch — we always drain our own binding.
    env.alpha.seed(spool=[_spool_event("e-alpha", 42.0)])
    env.beta.seed(sink=[_sink_row("s-beta", 1.0)])
    h = _make_handlers()
    broadcast: list[str] = []

    async def _spy(event_type: str, data: dict[str, Any]) -> None:
        broadcast.append(event_type)

    h.sse.broadcast = _spy  # type: ignore[method-assign]
    await h.get_scan_history(profile="beta")

    assert h._enforcement_offset > 0  # alpha's offset advanced
    assert "scan_result" in broadcast  # and its event was surfaced
    assert h._scans_total == 1


async def test_sink_and_spool_merge_dedups_by_scan_id(env: _Env) -> None:
    env.beta.seed(
        sink=[_sink_row("e-dup", 10.0, source="enforcement", detail_marker="sink")],
        spool=[_spool_event("e-dup", 10.0)],
    )
    h = _make_handlers()
    out = await h.get_scan_history(profile="beta")
    assert len(out["entries"]) == 1
    assert out["entries"][0].get("detail_marker") == "sink"  # sink wins (determinism)


async def test_duplicate_across_sink_segments_dedups(env: _Env) -> None:
    env.beta.seed(sink=[_sink_row("s-x", 3.0)], sink_rot=[_sink_row("s-x", 3.0)])
    h = _make_handlers()
    out = await h.get_scan_history(profile="beta")
    assert [r["scan_id"] for r in out["entries"]] == ["s-x"]


async def test_unorderable_rows_are_dropped(env: _Env) -> None:
    env.beta.seed(
        spool=[
            {"timestamp": 1.0},  # no scan_id
            _spool_event("e-str", "nope"),  # type: ignore[arg-type]
            {"scan_id": "e-nots"},  # no timestamp
            _spool_event("e-bool", True),
            _spool_event("e-ok", 9.0),
        ]
    )
    with open(env.beta.spool, "a", encoding="utf-8") as f:
        f.write("[1, 2, 3]\n")  # a non-dict line
    h = _make_handlers()
    out = await h.get_scan_history(profile="beta")
    assert [r["scan_id"] for r in out["entries"]] == ["e-ok"]


async def test_out_of_range_timestamp_is_dropped_not_raised(env: _Env) -> None:
    # The crash lives INSIDE read_history_page's own key computation, which sits
    # outside every try in that function, so it fires before the merge filter runs.
    env.beta.seed(sink=[_sink_row("s-huge", 0.0), _sink_row("s-ok", 4.0)])
    with open(env.beta.sink, "a", encoding="utf-8") as f:
        f.write(json.dumps({"scan_id": "s-big", "timestamp": 10**400}) + "\n")
    h = _make_handlers()
    out = await h.get_scan_history(profile="beta")
    ids = [r["scan_id"] for r in out["entries"]]
    assert "s-big" not in ids
    assert set(ids) == {"s-huge", "s-ok"}


def test_read_history_page_drops_unfloatable_timestamp(tmp_path: Path) -> None:
    p = tmp_path / "sink.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        f.write(json.dumps({"scan_id": "a", "timestamp": 10**400}) + "\n")
        f.write('{"scan_id": "b", "timestamp": Infinity}\n')
        f.write('{"scan_id": "c", "timestamp": NaN}\n')
        f.write(json.dumps({"scan_id": "d", "timestamp": 1.0}) + "\n")
    rows, _ = history_mod.read_history_page(str(p), before=None, limit=10)
    assert [r["scan_id"] for r in rows] == ["d"]
    assert all(math.isfinite(float(r["timestamp"])) for r in rows)


async def test_equipped_scoped_read_reports_spool_truncated_false(env: _Env) -> None:
    h = _make_handlers()
    out = await h.get_scan_history(profile="alpha")
    assert out["read_scope"]["state"] == "equipped"
    assert out["spool_truncated"] is False  # present, not absent
    assert "has_older" not in out  # non-equipped branch only (D12)


async def test_merged_page_orders_by_timestamp_scan_id(env: _Env) -> None:
    env.beta.seed(
        sink=[_sink_row("s-a", 1.0), _sink_row("s-c", 3.0)],
        spool=[_spool_event("e-b", 2.0), _spool_event("e-d", 3.0)],
    )
    h = _make_handlers()
    out = await h.get_scan_history(profile="beta")
    assert [r["scan_id"] for r in out["entries"]] == ["s-c", "e-d", "e-b", "s-a"]


async def test_older_truncated_uses_merged_oldest(env: _Env) -> None:
    # The spool holds the oldest row, so forwarding read_history_page's own flag
    # would report a true bottom above it.
    env.beta.seed(sink=[_sink_row("s-new", 100.0)], spool=[_spool_event("e-old", 1.0)])
    h = _make_handlers()
    head = await h.get_scan_history(limit=1, profile="beta")
    assert [r["scan_id"] for r in head["entries"]] == ["s-new"]
    page = await h.get_scan_history(limit=1, before=head["next_before"], profile="beta")
    assert [r["scan_id"] for r in page["entries"]] == ["e-old"]
    assert page["older_truncated"] is False
    bottom = await h.get_scan_history(limit=1, before=page["next_before"], profile="beta")
    assert bottom["entries"] == []
    # The merged bottom is a true bottom, not a rotation loss: the cursor is not
    # older than the merged global oldest, so older_truncated stays False.
    assert bottom["older_truncated"] is False


async def test_branches_agree_when_spool_empty(env: _Env) -> None:
    rows = [_sink_row(f"s-{i}", float(i)) for i in range(5)]
    env.beta.seed(sink=rows)
    h = _make_handlers()
    merged = await h.get_scan_history(profile="beta")
    direct, _ = history_mod.read_history_page(str(env.beta.sink), before=None, limit=100)
    assert [r["scan_id"] for r in merged["entries"]] == [r["scan_id"] for r in direct]


async def test_oversized_foreign_spool_is_bounded(env: _Env) -> None:
    server_mod._FOREIGN_SPOOL_READ_CAP = 400
    env.beta.seed(spool=[_spool_event(f"e-{i}", float(i), pad="x" * 60) for i in range(20)])
    assert os.path.getsize(env.beta.spool) > 400
    h = _make_handlers()
    out = await h.get_scan_history(profile="beta")
    assert out["spool_truncated"] is True
    assert out["entries"]  # the tail was read
    assert len(out["entries"]) < 20  # and the head was clipped
    # No leading partial line survived: every row parsed with a real scan_id.
    assert all(str(r["scan_id"]).startswith("e-") for r in out["entries"])


def test_spool_window_without_newline_yields_no_events(env: _Env) -> None:
    server_mod._FOREIGN_SPOOL_READ_CAP = 20
    env.beta.spool.write_text("x" * 500, encoding="utf-8")
    events, truncated = server_mod.read_spool_tail(str(env.beta.spool))
    assert events == []
    assert truncated is True


def test_subcap_spool_without_newline_is_not_truncated(env: _Env) -> None:
    # A sub-cap file holding one in-flight partial line: no events, and NOT
    # truncated — the retention notice must not render over benign torn bytes.
    server_mod._FOREIGN_SPOOL_READ_CAP = 2_000_000
    env.beta.spool.write_text("x" * 500, encoding="utf-8")
    events, truncated = server_mod.read_spool_tail(str(env.beta.spool))
    assert events == []
    assert truncated is False


# ── Validation contracts ──────────────────────────────────────────────────


@pytest.mark.parametrize("route", _SCOPED_ROUTES)
async def test_unknown_profile_422_on_every_scoped_route(env: _Env, route: str) -> None:
    h = _make_handlers()
    with pytest.raises(ProfileNotFoundError):
        if route == "scan-history":
            await h.get_scan_history(profile="ghost")
        elif route == "armed-get":
            await h.get_armed(profile="ghost")
        elif route == "armed-post":
            await h.set_armed(False, profile="ghost")
        elif route == "health":
            await h.get_health(profile="ghost")
        else:
            h.resolve_events_scope("ghost")


@pytest.mark.parametrize("name", ["nfd", "nfc"])
async def test_unknown_profile_422_unicode_normalization(env: _Env, name: str) -> None:
    # D7: matching is byte-exact; NFD and NFC forms of one name are distinct, so a
    # macOS-decomposed leaf name is a known non-member. Pinned, not incidental.
    _Home(env.root, "café")  # NFC on disk
    h = _make_handlers()
    probe = "café" if name == "nfc" else "café"
    if name == "nfc":
        out = await h.get_scan_history(profile=probe)
        assert out["read_scope"]["selected"] == probe
    else:
        with pytest.raises(ProfileNotFoundError):
            await h.get_scan_history(profile=probe)


@pytest.mark.parametrize("blank", ["", " "])
async def test_blank_profile_422(env: _Env, blank: str) -> None:
    # A blank value reaches the membership gate and 422s; it never serves equipped.
    h = _make_handlers()
    with pytest.raises(ProfileNotFoundError):
        await h.get_scan_history(profile=blank)


async def test_deleted_profile_422(env: _Env) -> None:
    h = _make_handlers()
    await h.get_scan_history(profile="beta")  # resolves while it exists
    (env.beta.dir / "config.yaml").unlink()
    with pytest.raises(ProfileNotFoundError):
        await h.get_scan_history(profile="beta")


async def test_case_variant_profile_422(env: _Env) -> None:
    h = _make_handlers()
    with pytest.raises(ProfileNotFoundError):
        await h.get_scan_history(profile="BETA")


async def test_profile_without_config_yaml_422(env: _Env) -> None:
    (env.root / "profiles" / "fresh").mkdir(parents=True, exist_ok=True)
    h = _make_handlers()
    with pytest.raises(ProfileNotFoundError):
        await h.get_scan_history(profile="fresh")


@pytest.mark.parametrize("name", ["../beta", "..", "/etc", "beta/../alpha"])
async def test_traversal_name_rejected(env: _Env, name: str) -> None:
    h = _make_handlers()
    with pytest.raises(ProfileNotFoundError):
        await h.get_scan_history(profile=name)


async def test_foreign_cursor_rejected(env: _Env) -> None:
    # alpha is equipped, so its scoped head read serves the ring; either way the
    # token it mints is scope-bound to alpha and must not page beta.
    env.beta.seed(sink=[_sink_row("s-b", 2.0)])
    h = _make_handlers()
    h._record_scan({"scan_id": "s-a", "timestamp": 1.0, "safe": True})
    alpha_page = await h.get_scan_history(profile="alpha")
    assert alpha_page["next_before"] is not None
    with pytest.raises(CursorScopeMismatchError):
        await h.get_scan_history(before=alpha_page["next_before"], profile="beta")


async def test_unscoped_cursor_replayed_under_no_scope_is_422(env: _Env) -> None:
    # D2's one named body-level exception: a prefixed token with NO parameter is a
    # 422, where today any unparseable token is a 200 empty page.
    env.beta.seed(sink=[_sink_row("s-b", 2.0)])
    h = _make_handlers()
    page = await h.get_scan_history(profile="beta")
    with pytest.raises(CursorScopeMismatchError):
        await h.get_scan_history(before=page["next_before"])


async def test_unprefixed_cursor_under_a_scope_is_422(env: _Env) -> None:
    # The other direction: an unprefixed token WITH a profile must not fall
    # through to the shipped two-segment parse and return a plausible page.
    env.beta.seed(sink=[_sink_row("s-b", 2.0)])
    h = _make_handlers()
    with pytest.raises(CursorScopeMismatchError):
        await h.get_scan_history(before="2.0~s-b", profile="beta")


async def test_unscoped_cursor_format_unchanged(env: _Env) -> None:
    h = _make_handlers()
    h._record_scan({"scan_id": "s-ring", "timestamp": 7.0, "safe": True})
    out = await h.get_scan_history()
    assert out["next_before"] == "7.0~s-ring"


async def test_equipped_named_cursor_round_trips(env: _Env) -> None:
    # An INTEGER timestamp survives the float() coercion in the mint, so the token
    # round-trips against the parser.
    h = _make_handlers()
    h._record_scan({"scan_id": "s-1", "timestamp": 5, "safe": True})
    h._record_scan({"scan_id": "s-2", "timestamp": 6, "safe": True})
    page = await h.get_scan_history(limit=1, before=None, profile="alpha")
    tok = page["next_before"]
    assert tok is not None and tok.startswith("alpha|")
    cursor, status = server_mod._parse_history_cursor(tok, "alpha")
    assert status == "ok"
    assert cursor is not None and cursor[0] == 6.0


@pytest.mark.parametrize("sid", ["e-a|b", "e-a~b", "e-a~b|c", "e-a%b"])
def test_delimiter_bearing_scan_id_round_trips(sid: str) -> None:
    tok = server_mod._history_cursor_token({"timestamp": 1.5, "scan_id": sid}, "beta")
    assert tok is not None
    # Exactly one structural delimiter of each kind survives the escape.
    assert tok.count("|") == 1
    assert tok.count("~") == 1
    cursor, status = server_mod._parse_history_cursor(tok, "beta")
    assert status == "ok"
    assert cursor == (1.5, sid)


def test_cursor_scope_name_is_escaped() -> None:
    tok = server_mod._history_cursor_token({"timestamp": 1.0, "scan_id": "s-a"}, "we|ird~name")
    assert tok is not None and tok.count("|") == 1 and tok.count("~") == 1
    assert server_mod._parse_history_cursor(tok, "we|ird~name")[1] == "ok"


# ── Armed ─────────────────────────────────────────────────────────────────


async def test_armed_reads_selected_profile(env: _Env) -> None:
    env.alpha.set_armed(True)
    env.beta.set_armed(False)
    h = _make_handlers()
    assert (await h.get_armed(profile="alpha"))["armed"] is True
    assert (await h.get_armed(profile="beta"))["armed"] is False
    assert (await h.get_armed())["armed"] is True  # unscoped -> the equipped binding


async def test_armed_cache_not_confused_by_identical_stat_key(env: _Env) -> None:
    # Two configs with equal size and forced-equal mtime: the pre-PET-166 stat-only
    # key would serve one profile's bit for the other.
    env.alpha.set_armed(True)
    env.beta.set_armed(False)
    a_cfg, b_cfg = env.alpha.dir / "config.yaml", env.beta.dir / "config.yaml"
    # Equal SIZE with both values still real booleans: pad the shorter one with a
    # comment so a bool-vs-garbage difference cannot be what the test observes.
    a_cfg.write_text("petasos:\n  enabled: true  #pad\n", encoding="utf-8")
    b_cfg.write_text("petasos:\n  enabled: false #pad\n", encoding="utf-8")
    st = a_cfg.stat()
    os.utime(b_cfg, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert b_cfg.stat().st_size == a_cfg.stat().st_size
    assert b_cfg.stat().st_mtime_ns == a_cfg.stat().st_mtime_ns
    armed_mod._reset_armed_cache()

    h = _make_handlers()
    assert (await h.get_armed(profile="alpha"))["armed"] is True
    assert (await h.get_armed(profile="beta"))["armed"] is False
    assert (await h.get_armed(profile="alpha"))["armed"] is True


def test_armed_cache_bounded(env: _Env) -> None:
    armed_mod._reset_armed_cache()
    now = time.monotonic()
    for i in range(armed_mod._ARMED_CACHE_MAX + 4):
        armed_mod._cache_store((f"p{i}", i, i), True, now)
    assert len(armed_mod._ARMED_CACHE) == armed_mod._ARMED_CACHE_MAX
    assert ("p0", 0, 0) not in armed_mod._ARMED_CACHE  # oldest evicted
    assert ("p11", 11, 11) in armed_mod._ARMED_CACHE  # newest retained


async def test_set_armed_non_equipped_is_409(env: _Env) -> None:
    before = (env.beta.dir / "config.yaml").read_bytes()
    h = _make_handlers()
    with pytest.raises(ProfileNotEquippedError) as exc:
        await h.set_armed(False, profile="beta")
    assert "alpha" in str(exc.value)  # names the equipped profile
    assert "persist" not in str(exc.value).lower()  # not the 503 persistence body
    assert (env.beta.dir / "config.yaml").read_bytes() == before


async def test_set_armed_equipped_unchanged(env: _Env) -> None:
    h = _make_handlers()
    result, ok = await h.set_armed(False, profile="alpha")
    assert ok is True
    assert result["armed"] is False and result["persisted"] is True
    assert result["read_scope"]["state"] == "equipped"
    assert armed_mod.read_armed(paths_mod.resolve_profile_config_path("alpha")) is False


async def test_set_armed_unscoped_shape_is_unchanged(env: _Env) -> None:
    h = _make_handlers()
    result, ok = await h.set_armed(False)
    assert ok is True
    assert result == {"armed": False, "persisted": True}  # D2: no new keys


# ── Attestation domain (D15) ──────────────────────────────────────────────


async def test_spool_rows_verified_with_spool_key(env: _Env) -> None:
    # Regression fence on the EQUIPPED branch: a correctly signed spool row is
    # `genuine`, never `unverifiable`. Pins shipped PET-139 behavior.
    h = _make_handlers(secret=b"secret-value-for-testing-0123456")
    key = events_mod._derive_spool_key(b"secret-value-for-testing-0123456")
    ev = _spool_event("e-signed", 12.0)
    ev["sig"] = _sign(ev, key)
    _write_jsonl(env.alpha.spool, [ev])
    out = await h.get_scan_history()
    assert [r["provenance"] for r in out["entries"]] == ["genuine"]


async def test_non_equipped_rows_are_foreign(env: _Env) -> None:
    h = _make_handlers(secret=b"secret-value-for-testing-0123456")
    other = events_mod._derive_spool_key(b"another-profiles-secret-value-00")
    ev = _spool_event("e-beta", 3.0)
    ev["sig"] = _sign(ev, other)
    env.beta.seed(sink=[_sink_row("s-beta", 4.0, sig="deadbeef")], spool=[ev])

    out = await h.get_scan_history(profile="beta")
    assert {r["provenance"] for r in out["entries"]} == {"foreign"}
    assert all("sig" not in r for r in out["entries"])  # the sink row's sig is stripped


async def test_non_equipped_read_does_not_touch_integrity_state(env: _Env) -> None:
    h = _make_handlers(secret=b"secret-value-for-testing-0123456")
    env.beta.seed(
        spool=[
            _spool_event("e-unsigned", 3.0),
            _spool_event("e-selfmod", 4.0, event_type="selfmod_attempt"),
        ]
    )
    await h.get_scan_history(profile="beta")
    assert list(h._integrity_recent) == []
    assert h._selfmod_total == 0
    assert h._block_tally == {}
    assert h._integrity_preflight_emitted is False
    assert (await h.get_health())["integrity"]["window_size"] == 0


# ── Scope reporting and binding states ────────────────────────────────────


async def test_read_scope_shape_identical_across_surfaces(env: _Env) -> None:
    h = _make_handlers()
    hist = await h.get_scan_history(profile="beta")
    armed = await h.get_armed(profile="beta")
    health = await h.get_health(profile="beta")
    idle = server_mod._read_scope_payload(h.resolve_events_scope("beta"))
    keys = {"selected", "equipped", "equipped_tier", "live", "state"}
    for payload in (hist["read_scope"], armed["read_scope"], health["read_scope"], idle):
        assert set(payload) == keys
    assert hist["read_scope"] == armed["read_scope"] == health["read_scope"] == idle


async def test_read_scope_absent_when_unscoped(env: _Env) -> None:
    h = _make_handlers()
    assert "read_scope" not in await h.get_scan_history()
    assert "spool_truncated" not in await h.get_scan_history()
    assert "read_scope" not in await h.get_armed()
    assert "read_scope" not in await h.get_health()


async def test_has_older_reflects_the_merged_clamp(env: _Env) -> None:
    limit = 5
    env.beta.seed(sink=[_sink_row(f"s-{i:02d}", float(i)) for i in range(limit + 3)])
    h = _make_handlers()
    out = await h.get_scan_history(limit=limit, profile="beta")
    assert out["has_older"] is True

    env2_rows = [_sink_row(f"t-{i:02d}", float(i)) for i in range(limit - 1)]
    _write_jsonl(env.alpha.dir.parent / "gamma" / "petasos-scan-history.jsonl", env2_rows)
    _Home(env.root, "gamma")
    _write_jsonl(env.root / "profiles" / "gamma" / "petasos-scan-history.jsonl", [])
    small = await h.get_scan_history(limit=limit, profile="gamma")
    assert small["has_older"] is False
    assert small["next_before"] is not None  # the two are not the same signal
    # And absent on the equipped and unscoped payloads (D2/D12).
    assert "has_older" not in await h.get_scan_history(profile="alpha")
    assert "has_older" not in await h.get_scan_history()


async def test_health_reports_scope_and_does_not_fabricate(env: _Env) -> None:
    h = _make_handlers()
    h._record_scan({"scan_id": "s-1", "timestamp": 1.0, "safe": True})
    scoped = await h.get_health(profile="beta")
    unscoped = await h.get_health()
    assert scoped["read_scope"]["state"] == "not_equipped"
    # Every process fact is reported identically: health is NOT per-profile.
    assert scoped["pipeline"] == unscoped["pipeline"]
    assert scoped["scanners"] == unscoped["scanners"]


async def test_hermes_home_inside_profiles_is_equipped(
    env: _Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    # D16: HERMES_HOME pointed inside profiles/ resolves to tier hermes_home with a
    # path byte-equal to the profile's, so PATH equality (not tier) decides.
    monkeypatch.setenv("HERMES_HOME", str(env.beta.dir))
    armed_mod._reset_armed_cache()
    h = _make_handlers()
    out = await h.get_scan_history(profile="beta")
    assert out["read_scope"]["state"] == "equipped"
    assert out["read_scope"]["equipped"] == "beta"
    assert out["read_scope"]["equipped_tier"] == "profile"
    assert out["read_scope"]["live"] is True


async def test_hermes_home_outside_profiles_has_no_equipped_name(
    env: _Env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "config.yaml").write_text("petasos:\n  enabled: true\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(outside))
    armed_mod._reset_armed_cache()
    h = _make_handlers()
    out = await h.get_scan_history(profile="beta")
    assert out["read_scope"]["equipped"] is None
    assert out["read_scope"]["equipped_tier"] == "hermes_home"
    # An UNSCOPED post still arms (the only arming target that exists).
    _, ok = await h.set_armed(False)
    assert ok is True


async def test_root_tier_scope_reports_tier(env: _Env) -> None:
    (env.root / "active_profile").unlink()
    (env.root / "config.yaml").write_text("petasos:\n  enabled: true\n", encoding="utf-8")
    armed_mod._reset_armed_cache()
    h = _make_handlers()
    out = await h.get_scan_history(profile="beta")
    assert out["read_scope"]["equipped"] is None
    assert out["read_scope"]["equipped_tier"] == "root"


async def test_unresolvable_equipped_path_is_unknown_and_still_allows_unscoped_arm(
    env: _Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = paths_mod._resolved_normcase
    equipped_cfg = env.alpha.dir / "config.yaml"

    def _fake(path: Path) -> str | None:
        if os.path.normcase(str(path)) == os.path.normcase(str(equipped_cfg)):
            return None  # the EQUIPPED side fails to resolve
        return real(path)

    monkeypatch.setattr(server_mod, "_resolved_normcase", _fake)
    h = _make_handlers()
    out = await h.get_scan_history(profile="beta")
    assert out["read_scope"]["state"] == "unknown"
    assert out["read_scope"]["live"] is False  # reads take the non-equipped branch
    _, ok = await h.set_armed(False)  # arming remains available, unscoped
    assert ok is True


async def test_both_paths_unresolvable_is_not_equipped(
    env: _Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    # D10 step 4 ordering: a flat comparison would read None == None as equipped and
    # let a scoped disarm through the D6 guard into the running agent's config.
    monkeypatch.setattr(server_mod, "_resolved_normcase", lambda _p: None)
    h = _make_handlers()
    out = await h.get_scan_history(profile="beta")
    assert out["read_scope"]["state"] != "equipped"
    with pytest.raises(ProfileNotEquippedError):
        await h.set_armed(False, profile="beta")


async def test_ring_cleared_on_binding_change(env: _Env) -> None:
    h = _make_handlers()
    await h.get_scan_history()  # first drain adopts alpha's spool
    h._record_scan({"scan_id": "s-alpha-ring", "timestamp": 9.0, "safe": True})
    total_before = h._scans_total

    env.activate("beta")  # the binding moves
    out = await h.get_scan_history(profile="beta")
    assert [r["scan_id"] for r in out["entries"]] == []
    assert h._scans_total == total_before  # lifetime counters survive


async def test_first_drain_does_not_clear_the_ring(env: _Env) -> None:
    # Embedded Hermes runs no preflight drain, so the FIRST drain of every process
    # takes the binding-change branch by construction. An unguarded clear would wipe
    # a pre-drain playground row here (and pass under standalone's preflight).
    h = _make_handlers()
    h._record_scan({"scan_id": "s-playground", "timestamp": 3.0, "safe": True})
    out = await h.get_scan_history()
    assert [r["scan_id"] for r in out["entries"]] == ["s-playground"]


async def test_unscoped_read_logs_scope_tripwire_once_embedded_only(
    env: _Env, caplog: pytest.LogCaptureFixture
) -> None:
    h = _make_handlers()
    with caplog.at_level("INFO", logger="petasos.console.server"):
        await h.get_scan_history()  # standalone: no flag, no line
        assert "PETASOS_SCOPE_UNSCOPED_READ" not in caplog.text
        h._embedded = True
        await h.get_scan_history()
        await h.get_armed()
        await h.get_health()
    assert caplog.text.count("PETASOS_SCOPE_UNSCOPED_READ") == 1


async def test_scope_tripwire_silent_without_an_active_profile(
    env: _Env, caplog: pytest.LogCaptureFixture
) -> None:
    # Two profiles, none active: D16's legitimate equipped_name-is-null configuration,
    # where the client correctly omits the selector. Not a stale bundle.
    (env.root / "active_profile").unlink()
    armed_mod._reset_armed_cache()
    h = _make_handlers()
    h._embedded = True
    with caplog.at_level("INFO", logger="petasos.console.server"):
        await h.get_scan_history()
    assert "PETASOS_SCOPE_UNSCOPED_READ" not in caplog.text
