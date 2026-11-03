"""PET-223: refused-approvals queue, reviewed file, routes, and command excerpt."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import importlib.util
import json
import logging
import os
import platform
import sys
import types
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

pytest.importorskip("fastapi")

import petasos.console._approvals as approvals  # noqa: E402
import petasos.console._events as events  # noqa: E402
import petasos.console._history as history  # noqa: E402
import petasos.console._paths as paths_mod  # noqa: E402
import petasos.console.hermes.plugin_api as plugin_mod  # noqa: E402
import petasos.console.server as server  # noqa: E402
from petasos._types import ScanFinding, Severity  # noqa: E402
from petasos.config import PetasosConfig  # noqa: E402
from petasos.pipeline import Pipeline  # noqa: E402
from petasos.scanners.minimal import MinimalScanner  # noqa: E402
from petasos.session.guard import GuardResult  # noqa: E402

pytestmark = pytest.mark.anyio

_PLUGIN = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "deployment"
    / "reference_plugin"
    / "__init__.py"
)


def _handlers(secret: bytes | None = None) -> server.ConsoleHandlers:
    return server.ConsoleHandlers(
        Pipeline(
            scanners=[MinimalScanner()],
            config=PetasosConfig(fail_mode="degraded", session_secret=secret),
            host_id="test-host",
        )
    )


def _row(scan_id: str, ts: float = 1_700_000_000.0, **extra: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "source": "enforcement",
        "event_type": "approval",
        "phase": "response",
        "choice": "deny",
        "scan_id": scan_id,
        "timestamp": ts,
        "session_key": "sk",
        "turn_id": "turn",
        "tool_call_id": "call",
        "rule_id": "plugin_rule:petasos.syntactic.command.fetch-exec",
        "tool": "terminal",
        "command": "rm -rf build",
        "description": 'command="rm -rf build"',
        "surface": "cli",
        "provenance": "genuine",
        "coalesced": False,
    }
    row.update(extra)
    return row


def _items(rows: list[Any], reviewed: frozenset[str] = frozenset()) -> dict[str, Any]:
    return approvals.refused_items(rows, reviewed)


def _sign(record: dict[str, Any], key: bytes) -> dict[str, Any]:
    body = dict(record)
    preimage = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    body["sig"] = hmac.new(key, preimage.encode("utf-8"), hashlib.sha256).hexdigest()
    return body


def _load_plugin() -> Any:
    spec = importlib.util.spec_from_file_location("petasos_reference_plugin_pet223", _PLUGIN)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _install_redactor(monkeypatch: pytest.MonkeyPatch, fn: Any) -> None:
    redact_mod = cast("Any", types.ModuleType("agent.redact"))
    redact_mod.redact_sensitive_text = fn
    if "agent" not in sys.modules:
        monkeypatch.setitem(sys.modules, "agent", types.ModuleType("agent"))
    monkeypatch.setitem(sys.modules, "agent.redact", redact_mod)


class _Finding:
    def __init__(self, finding_type: str) -> None:
        self.finding_type = finding_type


class _Result:
    def __init__(self, findings: tuple[Any, ...] = ()) -> None:
        self.findings = findings


# ── Derivation ────────────────────────────────────────────────────────────


def test_refusal_choices_are_items_and_approvals_are_not() -> None:
    refusals = ["deny", "timeout", "cancelled", "notify_failed", "smart_deny"]
    approvals_choices = ["once", "session", "always", "smart_approve"]
    got = _items(
        [_row(f"e-r{i}", choice=choice) for i, choice in enumerate(refusals)]
        + [
            _row(f"e-a{i}", choice=choice, tool_call_id=f"a{i}")
            for i, choice in enumerate(approvals_choices)
        ]
    )
    assert sorted(item["choice"] for item in got["items"]) == sorted(refusals)
    assert got["total"] == 5


def test_unknown_choices_are_counted_not_queued() -> None:
    choices: list[Any] = [None, "", "maybe", "transport_timeout", 7]
    got = _items([_row(f"e-u{i}", choice=choice) for i, choice in enumerate(choices)])
    assert got["items"] == []
    assert got["unknown"] == 5


def test_smart_deny_override_shapes() -> None:
    key = {"session_key": "sk", "turn_id": "turn", "tool_call_id": "call", "rule_id": "pat"}

    def bundle(*rows: dict[str, Any]) -> dict[str, Any]:
        return _items(list(rows))

    denied = bundle(
        _row("e-sd", 10, choice="smart_deny", surface="smart", **key),
        _row("e-rq", 11, phase="request", choice=None, surface="cli", **key),
        _row("e-once", 12, choice="once", surface="cli", **key),
    )
    assert denied["items"] == []

    human_deny = bundle(
        _row("e-sd2", 10, choice="smart_deny", surface="smart", **key),
        _row("e-rq2", 11, phase="request", choice=None, surface="cli", **key),
        _row("e-deny", 12, choice="deny", surface="cli", **key),
    )
    assert len(human_deny["items"]) == 1
    assert human_deny["items"][0]["choice"] == "deny"
    assert human_deny["items"][0]["overrode_smart_deny"] is True

    alone = bundle(_row("e-sd3", 10, choice="smart_deny", surface="smart", **key))
    assert len(alone["items"]) == 1

    other_key = bundle(
        _row("e-sd4", 10, choice="smart_deny", surface="smart", **key),
        _row(
            "e-rq4",
            11,
            phase="request",
            choice=None,
            surface="cli",
            rule_id="other",
            **{k: v for k, v in key.items() if k != "rule_id"},
        ),
        _row(
            "e-once4",
            12,
            choice="once",
            surface="cli",
            rule_id="other",
            **{k: v for k, v in key.items() if k != "rule_id"},
        ),
    )
    assert any(item["choice"] == "smart_deny" for item in other_key["items"])

    transport = bundle(
        _row("e-sd5", 10, choice="smart_deny", surface="smart", **key),
        _row("e-tr", 11, phase="request", choice=None, surface="transport:x", **key),
        _row("e-tt", 12, choice="transport_timeout", surface="cli", **key),
    )
    assert any(item["choice"] == "smart_deny" for item in transport["items"])
    assert transport["unknown"] == 1

    same_ts = bundle(
        _row("e-req", 5, phase="request", choice=None, surface="cli", **key),
        _row("e-sden", 5, choice="smart_deny", surface="smart", **key),
        _row("e-sreq", 5, phase="request", choice=None, surface="smart", **key),
        _row("e-ok", 5, choice="once", surface="cli", **key),
    )
    assert not any(item["choice"] == "smart_deny" for item in same_ts["items"])

    fallback = bundle(
        _row("e-b1", 1, choice="smart_deny", surface="smart", **key),
        _row("e-b2", 2, phase="request", choice=None, surface="cli", **key),
        _row("e-b3", 3, choice="transport_timeout", surface="cli", **key),
        _row("e-b4", 4, phase="request", choice=None, surface="cli", **key),
        _row("e-b5", 5, choice="once", surface="cli", **key),
    )
    assert not any(item["choice"] == "smart_deny" for item in fallback["items"])

    reused = bundle(
        _row("e-u1", 1, choice="smart_deny", surface="smart", **key),
        _row("e-u2", 2, phase="request", choice=None, surface="cli", **key),
        _row("e-u3", 3, choice="transport_timeout", surface="cli", **key),
        _row("e-u4", 4, phase="request", choice=None, surface="smart", **key),
        _row("e-u5", 5, phase="request", choice=None, surface="cli", **key),
        _row("e-u6", 6, choice="once", surface="cli", **key),
    )
    assert any(item["choice"] == "smart_deny" for item in reused["items"])


def test_tuple_reuse_keeps_every_refusal() -> None:
    key = {"session_key": "sk", "turn_id": "turn", "tool_call_id": "call"}
    later_once = _items(
        [
            _row("e-d", 1, choice="deny", command="rm old", **key),
            _row("e-r", 2, phase="request", choice=None, **key),
            _row("e-o", 3, choice="once", command="ls", **key),
        ]
    )
    assert [item["item_id"] for item in later_once["items"]] == ["e-d"]
    smart = _items(
        [
            _row("e-d2", 1, choice="deny", **key),
            _row("e-s", 2, choice="smart_approve", **key),
        ]
    )
    assert [item["item_id"] for item in smart["items"]] == ["e-d2"]
    both = _items(
        [
            _row("e-a", 1, choice="deny", **key),
            _row("e-b", 2, choice="deny", **key),
        ]
    )
    assert {item["item_id"] for item in both["items"]} == {"e-a", "e-b"}


def test_pending_counts_paired_non_smart_rows() -> None:
    key = {"session_key": "sk", "turn_id": "turn", "tool_call_id": "call"}
    waiting = _items([_row("e-rq", 1, phase="request", choice=None, **key)])
    assert waiting["pending"] == 1
    assert waiting["items"] == []
    answered = _items(
        [
            _row("e-rs", 2, phase="response", choice="deny", **key),
            _row("e-rq2", 2, phase="request", choice=None, **key),
        ]
    )
    assert answered["pending"] == 0
    escalate = _items(
        [
            _row("e-sm", 1, phase="request", choice=None, surface="smart", **key),
            _row("e-hr", 2, phase="request", choice=None, surface="cli", **key),
            _row("e-ha", 3, phase="response", choice="once", surface="cli", **key),
        ]
    )
    assert escalate["pending"] == 0


def test_unpaired_rows_do_not_hide_or_pend() -> None:
    denied = _items(
        [
            _row("e-d", 1, choice="deny", turn_id="", tool_call_id="call"),
            _row("e-o", 2, choice="once", turn_id="", tool_call_id="call"),
        ]
    )
    assert [item["item_id"] for item in denied["items"]] == ["e-d"]
    empty_call = _items(
        [
            _row("e-d2", 1, choice="deny", tool_call_id="", turn_id="turn"),
            _row("e-o2", 2, choice="once", tool_call_id="", turn_id="turn"),
        ]
    )
    assert [item["item_id"] for item in empty_call["items"]] == ["e-d2"]
    pending = _items([_row("e-rq", 1, phase="request", choice=None, turn_id="")])
    assert pending["pending"] == 0


def test_coalesced_follower_is_its_own_item() -> None:
    got = _items(
        [
            _row("e-1", 1, choice="deny", tool_call_id="a"),
            _row("e-2", 2, choice="deny", tool_call_id="b", coalesced=True),
        ]
    )
    follower = next(item for item in got["items"] if item["item_id"] == "e-2")
    assert follower["coalesced"] is True


def test_origin_from_pattern_key() -> None:
    petasos = _items([_row("e-1", rule_id="plugin_rule:petasos.syntactic.command.fetch-exec")])
    assert petasos["items"][0]["origin"] == "petasos"
    assert petasos["items"][0]["petasos_rule"] == "petasos.syntactic.command.fetch-exec"
    other = _items([_row("e-2", rule_id="plugin_rule:other.rule")])
    assert other["items"][0]["origin"] == "plugin"
    assert other["items"][0]["petasos_rule"] is None
    hermes = _items([_row("e-3", rule_id="destructive-recursive")])
    assert hermes["items"][0]["origin"] == "hermes"
    assert hermes["items"][0]["petasos_rule"] is None


def test_unverifiable_rows_cannot_remove_a_refusal() -> None:
    kept = _items(
        [
            _row("e-d", 1, choice="deny", provenance="genuine"),
            _row("e-o", 2, choice="once", provenance="unverifiable"),
        ]
    )
    assert [item["item_id"] for item in kept["items"]] == ["e-d"]
    forged = _items([_row("e-f", 1, choice="deny", provenance="unverifiable")])
    assert forged["items"][0]["provenance"] == "unverifiable"


def test_cap_window_and_approval_count() -> None:
    rows = [_row(f"e-{i:04d}", ts=float(i + 10)) for i in range(1001)]
    got = _items(rows)
    assert len(got["items"]) == 1000
    assert got["total"] == 1001
    assert len(got["items_by_id"]) == 1001
    window = _items(
        rows
        + [
            {
                "source": "enforcement",
                "event_type": "block",
                "scan_id": "e-block",
                "timestamp": 1.5,
                "provenance": "genuine",
            },
            _row("e-old-forged", 1, choice="deny", provenance="unverifiable"),
        ]
    )
    assert window["window_oldest"] == 1.5
    assert window["approval_rows"] == 1002
    empty = _items(
        [
            {
                "source": "enforcement",
                "event_type": "block",
                "scan_id": "e-only",
                "timestamp": 3.0,
                "provenance": "genuine",
            }
        ]
    )
    assert empty["approval_rows"] == 0


def test_cap_ranks_trusted_unreviewed_first() -> None:
    rows = [
        _row(f"e-u{i:04d}", ts=10_000 + i, choice="deny", provenance="unverifiable")
        for i in range(1000)
    ]
    rows.append(_row("e-real", 1, choice="deny", provenance="genuine"))
    got = _items(rows)
    assert any(item["item_id"] == "e-real" for item in got["items"])
    assert got["unverifiable_count"] == 1000
    reviewed_ids = [f"e-n{i:04d}" for i in range(1000)]
    mixed = [_row(scan_id, ts=100 + i, choice="deny") for i, scan_id in enumerate(reviewed_ids)]
    mixed.append(_row("e-old", 1, choice="deny"))
    ranked = _items(mixed, reviewed=frozenset(reviewed_ids))
    assert any(item["item_id"] == "e-old" for item in ranked["items"])


def test_malformed_rows_do_not_raise_and_share_orderable_key() -> None:
    valid = _row("e-ok", 5, choice="deny", tool="terminal")
    junk: list[Any] = [
        "nope",
        None,
        True,
        _row("e-bool", ts=True),
        _row("e-inf", ts=float("inf")),
        _row("e-huge", ts=10**400),
        {"timestamp": 1, "scan_id": 5, "source": "enforcement", "event_type": "approval"},
        _row("", 1),
        _row("x" * 129, 1),
        _row(
            "e-badfields",
            4,
            session_key=["x"],
            tool_call_id={"a": 1},
            rule_id=3,
            tool={},
            description=True,
            command=[{}],
            coalesced="yes",
        ),
    ]
    got = _items([valid, *junk])
    assert "e-ok" in {item["item_id"] for item in got["items"]}
    assert "e-bool" not in {item["item_id"] for item in got["items"]}
    assert "" not in {item["item_id"] for item in got["items"]}
    bad = next(item for item in got["items"] if item["item_id"] == "e-badfields")
    assert bad["tool"] is None
    assert bad["description"] is None
    assert bad["command"] is None
    assert bad["coalesced"] is False
    assert history.orderable_key({"timestamp": True, "scan_id": "e"}) is None
    assert history.orderable_key({"timestamp": float("inf"), "scan_id": "e"}) is None
    assert history.orderable_key({"timestamp": 10**400, "scan_id": "e"}) is None
    assert history.orderable_key({"timestamp": 1.0, "scan_id": ""}) == (1.0, "")


# ── Reads ─────────────────────────────────────────────────────────────────


async def test_restart_reads_the_sink() -> None:
    history.append_history_row(_row("e-timeout", choice="timeout"), None)
    fresh = _handlers()
    got = await fresh.get_refused_approvals(None)
    assert any(item["item_id"] == "e-timeout" for item in got["items"])


async def test_sink_provenance_keeps_a_forged_once_from_hiding_deny() -> None:
    secret = b"s" * 32
    writer = _handlers(secret)
    deny = _sign(
        {
            "event_type": "approval",
            "phase": "response",
            "choice": "deny",
            "scan_id": "e-deny",
            "timestamp": 10.0,
            "session_key": "sk",
            "turn_id": "turn",
            "tool_call_id": "call",
            "rule_id": "plugin_rule:petasos.x",
            "session_id": "sess",
        },
        writer._spool_key or b"",
    )
    forged = {
        "event_type": "approval",
        "phase": "response",
        "choice": "once",
        "scan_id": "e-once",
        "timestamp": 11.0,
        "session_key": "sk",
        "turn_id": "turn",
        "tool_call_id": "call",
        "rule_id": "plugin_rule:petasos.x",
        "sig": "00" * 32,
    }
    await writer._surface_enforcement_event(deny)
    await writer._surface_enforcement_event(forged)
    fresh = _handlers(secret)
    got = await fresh.get_refused_approvals(None)
    assert any(item["item_id"] == "e-deny" for item in got["items"])
    fresh.scan_history.push(
        _row("e-deny", 10, choice="once", provenance="unverifiable", phase="response")
    )
    again = await fresh.get_refused_approvals(None)
    deny_item = next(item for item in again["items"] if item["item_id"] == "e-deny")
    assert deny_item["choice"] == "deny"


async def test_truncated_sink_and_missing_state_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    history._HISTORY_CAP_BYTES = 10
    sink = history._history_path()
    Path(sink).write_bytes(b"x" * 50)
    handler = _handlers()
    handler.scan_history.push(_row("e-ring", 5))
    got = await handler.get_refused_approvals(None)
    assert got["truncated"] is True
    assert any(item["item_id"] == "e-ring" for item in got["items"])

    history._HISTORY_CAP_BYTES = 2_000_000
    rot = sink + ".rot"
    Path(rot).write_text("", encoding="utf-8")
    real_open = open

    def _open(path: Any, *args: Any, **kwargs: Any) -> Any:
        if str(path).endswith(".rot"):
            raise PermissionError("held")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", _open)
    probed = _handlers()
    probed.scan_history.push(_row("e-ring2", 6))
    held = await probed.get_refused_approvals(None)
    assert held["truncated"] is True
    monkeypatch.undo()

    warned = _handlers()
    warned._history_sink_warned = True
    flagged = await warned.get_refused_approvals(None)
    assert flagged["truncated"] is True

    approvals._REVIEWED_PATH_OVERRIDE = str(tmp_path / "missing" / "reviewed.json")
    bare = _handlers()
    state = await bare.get_refused_approvals(None)
    assert state["review_write"]["reason"] == "no_state_dir"


@pytest.fixture()
def profiles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    saved_spool = paths_mod._SPOOL_PATH_OVERRIDE
    saved_hist = history._HISTORY_PATH_OVERRIDE
    saved_reviewed = approvals._REVIEWED_PATH_OVERRIDE
    paths_mod._SPOOL_PATH_OVERRIDE = None
    history._HISTORY_PATH_OVERRIDE = None
    approvals._REVIEWED_PATH_OVERRIDE = None
    monkeypatch.delenv("HERMES_HOME", raising=False)
    if platform.system() == "Windows":
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    else:
        monkeypatch.setenv("HOME", str(tmp_path))
    root = paths_mod.hermes_root()
    for name in ("alpha", "beta"):
        folder = root / "profiles" / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "config.yaml").write_text("petasos:\n  enabled: true\n", encoding="utf-8")
    (root / "active_profile").write_text("alpha", encoding="utf-8")
    try:
        yield root
    finally:
        paths_mod._SPOOL_PATH_OVERRIDE = saved_spool
        history._HISTORY_PATH_OVERRIDE = saved_hist
        approvals._REVIEWED_PATH_OVERRIDE = saved_reviewed


async def test_non_equipped_keeps_unverifiable_and_foreign_marks(
    profiles: Path, caplog: pytest.LogCaptureFixture
) -> None:
    beta = profiles / "profiles" / "beta"
    sink = beta / "petasos-scan-history.jsonl"
    spool = beta / "petasos-enforcement.jsonl"
    deny = _row("e-foreign-deny", 10, provenance="genuine")
    once = _row("e-foreign-once", 11, choice="once", provenance="unverifiable")
    sink.write_text(
        json.dumps(deny) + "\n" + json.dumps(once) + "\n",
        encoding="utf-8",
    )
    spool_row = _row("e-spool-deny", 12, provenance="foreign")
    spool.write_text(json.dumps(spool_row) + "\n", encoding="utf-8")
    other = b"other-secret"
    ids = ["e-foreign-deny"]
    payload = {"v": 1, "ids": ids}
    payload["sig"] = hmac.new(
        approvals.reviewed_key(other),
        json.dumps({"v": 1, "ids": ids}, sort_keys=True, separators=(",", ":")).encode(),
        hashlib.sha256,
    ).hexdigest()
    (beta / "petasos-approvals-reviewed.json").write_text(json.dumps(payload), encoding="utf-8")
    handler = _handlers(b"this-secret")
    with caplog.at_level(logging.WARNING):
        got = await handler.get_refused_approvals("beta")
    ids_out = {item["item_id"] for item in got["items"]}
    assert "e-foreign-deny" in ids_out
    assert "e-spool-deny" in ids_out
    assert all(
        item["provenance"] == "foreign" or item["provenance"] == "unverifiable"
        for item in got["items"]
    )
    deny_item = next(item for item in got["items"] if item["item_id"] == "e-foreign-deny")
    assert deny_item["provenance"] == "foreign"
    assert got["reviewed_integrity"] == "foreign"
    assert deny_item["reviewed"] is True
    assert "PETASOS_APPROVAL_REVIEWED_UNVERIFIABLE" not in caplog.text


def _spool_lines(*rows: dict[str, Any]) -> None:
    path = events._spool_path()
    Path(path).write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


async def test_poisoned_spool_does_not_wedge_reads() -> None:
    good_a = _row("e-a", 1)
    good_b = _row("e-b", 2, tool_call_id="other")
    poison = [
        {"event_type": []},
        good_a,
        {"event_type": {}},
        {
            "event_type": "block",
            "scan_id": "e-list",
            "timestamp": 3,
            "command": ["not", "a", "string"],
        },
        good_b,
    ]
    _spool_lines(*poison)
    handler = _handlers()
    got = await handler.get_refused_approvals(None)
    hist = await handler.get_scan_history()
    assert {item["item_id"] for item in got["items"]} >= {"e-a", "e-b"}
    types_seen = {entry.get("event_type") for entry in hist["entries"]}
    assert None in types_seen
    offset = handler._enforcement_offset
    again = _handlers()
    again._enforcement_offset = offset
    again._enforcement_spool_path = handler._enforcement_spool_path
    # A fresh handlers starts at offset 0. Assert the first drain consumed the file.
    assert offset == Path(events._spool_path()).stat().st_size
    before = list(handler.scan_history.to_list())
    await handler.get_refused_approvals(None)
    assert len(handler.scan_history.to_list()) == len(before)


async def test_per_record_guard_skips_one_row_and_keeps_the_rot(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    secret = b"k" * 16

    async def _case(rot: bool) -> None:
        handler = _handlers(secret)
        real = handler._record_scan

        def boom(summary: dict[str, Any]) -> None:
            if summary.get("scan_id") == "e-bad":
                raise RuntimeError("boom")
            real(summary)

        monkeypatch.setattr(handler, "_record_scan", boom)
        bad = _sign(
            {
                "event_type": "approval",
                "phase": "response",
                "choice": "deny",
                "scan_id": "e-bad",
                "timestamp": 2.0,
                "session_key": "sk",
                "turn_id": "t",
                "tool_call_id": "c",
            },
            handler._spool_key or b"",
        )
        before = _sign(
            {
                "event_type": "approval",
                "phase": "response",
                "choice": "deny",
                "scan_id": "e-before",
                "timestamp": 1.0,
                "session_key": "sk",
                "turn_id": "t",
                "tool_call_id": "b",
                "sig_placeholder": 0,
            },
            b"",
        )
        before["sig"] = "ff" * 32
        after = _sign(
            {
                "event_type": "approval",
                "phase": "response",
                "choice": "deny",
                "scan_id": "e-after",
                "timestamp": 3.0,
                "session_key": "sk",
                "turn_id": "t",
                "tool_call_id": "a",
            },
            handler._spool_key or b"",
        )
        live = events._spool_path()
        if rot:
            rot_path = live + events._ROT_SUFFIX
            Path(rot_path).write_text(
                json.dumps(before) + "\n" + json.dumps(bad) + "\n" + json.dumps(after) + "\n",
                encoding="utf-8",
            )
        else:
            Path(live).write_text(
                json.dumps(before) + "\n" + json.dumps(bad) + "\n" + json.dumps(after) + "\n",
                encoding="utf-8",
            )
        with caplog.at_level(logging.WARNING):
            await handler._drain_enforcement_into_history()
        ids = {row.get("scan_id") for row in handler.scan_history.to_list()}
        assert "e-before" in ids
        assert "e-after" in ids
        assert "e-bad" not in ids
        assert "PETASOS_ENFORCEMENT_RECORD_SKIPPED scan_id=e-bad" in caplog.text
        caplog.clear()
        await handler._drain_enforcement_into_history()
        assert "PETASOS_ENFORCEMENT_RECORD_SKIPPED" not in caplog.text
        if rot:
            assert not os.path.exists(live + events._ROT_SUFFIX)

    await _case(False)
    await _case(True)

    handler = _handlers()

    async def _cancel(_ev: dict[str, Any]) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(handler, "_surface_enforcement_event", _cancel)
    Path(events._spool_path()).write_text(json.dumps(_row("e-c", 1)) + "\n", encoding="utf-8")
    with pytest.raises(asyncio.CancelledError):
        await handler._drain_enforcement_into_history()


async def test_mark_beyond_the_display_cap() -> None:
    secret = b"m" * 16
    handler = _handlers(secret)
    handler._review_auth_configured = True
    old = _row("e-old", 1, command="rm -rf build", rule_id="plugin_rule:petasos.old")
    newer = [_row(f"e-n{i:04d}", ts=10 + i) for i in range(1000)]
    history.append_history_row(old, handler._history_key)
    for row in newer:
        history.append_history_row(row, handler._history_key)
    marked = await handler.mark_approval_reviewed("e-old", None)
    assert marked["changed"] is True
    await handler._drain_enforcement_into_history()
    audit = next(
        row
        for row in handler.scan_history.to_list()
        if row.get("event_type") == "approval_reviewed"
    )
    assert audit["command"] == "rm -rf build"
    assert audit["rule_id"] == "plugin_rule:petasos.old"
    assert audit["item_id"] == "e-old"


# ── Reviewed set ──────────────────────────────────────────────────────────


def _write_reviewed(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload) if not isinstance(payload, str) else payload, encoding="utf-8"
    )


def test_read_reviewed_table(tmp_path: Path) -> None:
    path = tmp_path / "reviewed.json"
    missing, status = approvals.read_reviewed(str(path), b"k")
    assert (missing, status) == (set(), "absent")

    path.write_text("{", encoding="utf-8")
    assert approvals.read_reviewed(str(path), b"k")[1] == "unreadable"
    path.write_bytes(b"x" * (1_000_001))
    assert approvals.read_reviewed(str(path), b"k")[1] == "unreadable"
    path.write_text(json.dumps({"v": 1, "ids": [1]}), encoding="utf-8")
    assert approvals.read_reviewed(str(path), b"k")[1] == "unreadable"
    path.write_text(json.dumps({"v": 2, "ids": ["a"]}), encoding="utf-8")
    assert approvals.read_reviewed(str(path), b"k")[1] == "unsupported_version"
    path.write_text(json.dumps({"v": 1, "ids": ["a"]}), encoding="utf-8")
    ids, foreign = approvals.read_reviewed(str(path), b"k", foreign=True)
    assert foreign == "foreign" and ids == {"a"}
    ids, unattested = approvals.read_reviewed(str(path), None)
    assert unattested == "unattested" and ids == {"a"}
    key = approvals.reviewed_key(b"secret")
    signed = {"v": 1, "ids": ["a"]}
    signed["sig"] = hmac.new(
        key,
        json.dumps({"v": 1, "ids": ["a"]}, sort_keys=True, separators=(",", ":")).encode(),
        hashlib.sha256,
    ).hexdigest()
    path.write_text(json.dumps(signed), encoding="utf-8")
    ids, genuine = approvals.read_reviewed(str(path), key)
    assert genuine == "genuine" and ids == {"a"}
    signed["sig"] = "00" * 32
    path.write_text(json.dumps(signed), encoding="utf-8")
    ids, bad = approvals.read_reviewed(str(path), key)
    assert bad == "unverifiable" and ids == set()
    path.write_text(json.dumps({"v": 1, "ids": ["a"], "sig": "é"}), encoding="utf-8")
    ids, non_ascii = approvals.read_reviewed(str(path), key)
    assert non_ascii == "unverifiable" and ids == set()

    # stat raises: io_error. Point at a directory entry and patch stat via the path's parent.
    real_stat = os.stat

    def _stat(target: Any, *args: Any, **kwargs: Any) -> Any:
        if str(target) == str(path):
            raise OSError("busy")
        return real_stat(target, *args, **kwargs)

    # Use a file that exists so FileNotFound is not the branch under test.
    path.write_text("{}", encoding="utf-8")
    monkey = pytest.MonkeyPatch()
    monkey.setattr(os, "stat", _stat)
    try:
        assert approvals.read_reviewed(str(path), key)[1] == "io_error"
    finally:
        monkey.undo()


async def test_reviewed_warnings_are_one_shot(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "reviewed.json"
    approvals._REVIEWED_PATH_OVERRIDE = str(path)
    key = approvals.reviewed_key(b"secret")
    path.write_text(json.dumps({"v": 1, "ids": ["a"], "sig": "bad"}), encoding="utf-8")
    handler = _handlers(b"secret")
    assert handler._reviewed_key == key
    with caplog.at_level(logging.WARNING):
        await handler.get_refused_approvals(None)
        await handler.get_refused_approvals(None)
    assert caplog.text.count("PETASOS_APPROVAL_REVIEWED_UNVERIFIABLE") == 1
    assert "session secret changed" in caplog.text
    caplog.clear()
    path.write_text("{", encoding="utf-8")
    fresh = _handlers(b"secret")
    with caplog.at_level(logging.WARNING):
        await fresh.get_refused_approvals(None)
        await fresh.get_refused_approvals(None)
    assert caplog.text.count("PETASOS_APPROVAL_REVIEWED_UNREADABLE") == 1


async def test_prune_and_second_mark() -> None:
    secret = b"p" * 16
    handler = _handlers(secret)
    handler._review_auth_configured = True
    history.append_history_row(_row("e-live", 2, choice="deny"), handler._history_key)
    history.append_history_row(
        _row("e-other", 3, choice="timeout", tool_call_id="other"), handler._history_key
    )
    path = approvals.reviewed_path()
    approvals.write_reviewed(path, {"e-gone", "e-live"}, handler._reviewed_key)
    marked = await handler.mark_approval_reviewed("e-other", None)
    assert marked["changed"] is True
    stored, status = approvals.read_reviewed(path, handler._reviewed_key)
    assert "e-gone" not in stored
    assert "e-other" in stored
    assert "e-live" in stored
    assert status == "genuine"
    spool_before = (
        Path(events._spool_path()).stat().st_size if Path(events._spool_path()).exists() else 0
    )
    again = await handler.mark_approval_reviewed("e-other", None)
    assert again["changed"] is False
    spool_after = (
        Path(events._spool_path()).stat().st_size if Path(events._spool_path()).exists() else 0
    )
    assert spool_after == spool_before

    history._HISTORY_CAP_BYTES = 8
    sink = history._history_path()
    Path(sink).write_bytes(b"y" * 40)
    gated = _handlers(secret)
    gated._review_auth_configured = True
    gated.scan_history.push(_row("e-ring", 3))
    approvals.write_reviewed(path, {"e-stale"}, gated._reviewed_key)
    await gated.mark_approval_reviewed("e-ring", None)
    kept, _status = approvals.read_reviewed(path, gated._reviewed_key)
    assert "e-stale" in kept
    history._HISTORY_CAP_BYTES = 2_000_000


async def test_emit_failure_refuses_and_retries(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    handler = _handlers(b"e" * 16)
    handler._review_auth_configured = True
    history.append_history_row(_row("e-1", 1), handler._history_key)
    path = approvals.reviewed_path()
    monkeypatch.setattr(events, "emit_console_event", lambda *_a, **_k: False)
    with caplog.at_level(logging.WARNING), pytest.raises(server.ReviewRefusedError) as caught:
        await handler.mark_approval_reviewed("e-1", None)
    assert caught.value.status == 503
    assert not Path(path).exists()
    assert "PETASOS_APPROVAL_REVIEW_UNRECORDED" in caplog.text
    monkeypatch.setattr(events, "emit_console_event", events.emit_console_event)
    # The lambda replaced the function. Restore by reloading the attribute from the module
    # is already the original if we undo. monkeypatch undoes at teardown, so call the real one.
    monkeypatch.undo()
    marked = await handler.mark_approval_reviewed("e-1", None)
    assert marked["changed"] is True


async def test_reviewed_read_failures_write_no_audit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    handler = _handlers(b"e" * 16)
    handler._review_auth_configured = True
    history.append_history_row(_row("e-1", 1), handler._history_key)
    path = Path(approvals.reviewed_path())

    real_stat = os.stat

    def blocked(target: Any, *args: Any, **kwargs: Any) -> Any:
        if os.path.normcase(str(target)) == os.path.normcase(str(path)):
            raise OSError("busy")
        return real_stat(target, *args, **kwargs)

    path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(os, "stat", blocked)
    with pytest.raises(server.ReviewRefusedError) as io_err:
        await handler.mark_approval_reviewed("e-1", None)
    assert io_err.value.status == 503
    monkeypatch.undo()
    path.write_text(json.dumps({"v": 2, "ids": []}), encoding="utf-8")
    with pytest.raises(server.ReviewRefusedError) as version:
        await handler.mark_approval_reviewed("e-1", None)
    assert version.value.status == 503
    approvals._REVIEWED_PATH_OVERRIDE = str(tmp_path / "nope" / "reviewed.json")
    with pytest.raises(server.ReviewRefusedError) as missing:
        await handler.mark_approval_reviewed("e-1", None)
    assert missing.value.status == 503
    assert (
        not Path(events._spool_path()).exists()
        or b"approval_reviewed" not in Path(events._spool_path()).read_bytes()
    )


async def test_replace_failure_leaves_no_temp(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    handler = _handlers(b"e" * 16)
    handler._review_auth_configured = True
    approvals._REVIEWED_PATH_OVERRIDE = str(tmp_path / "reviewed.json")
    history.append_history_row(_row("e-1", 1), handler._history_key)

    def _boom(*_a: Any, **_k: Any) -> None:
        raise PermissionError("no")

    monkeypatch.setattr(os, "replace", _boom)
    with caplog.at_level(logging.WARNING), pytest.raises(server.ReviewRefusedError):
        await handler.mark_approval_reviewed("e-1", None)
    assert "PETASOS_APPROVAL_REVIEW_WRITE_FAILED" in caplog.text
    temps = list(tmp_path.glob("*.tmp"))
    assert temps == []


async def test_audit_row_drains_genuine_and_is_not_a_queue_item() -> None:
    secret = b"a" * 24
    handler = _handlers(secret)
    handler._review_auth_configured = True
    history.append_history_row(_row("e-1", 1), handler._history_key)
    await handler.mark_approval_reviewed("e-1", None)
    fresh = _handlers(secret)
    got = await fresh.get_refused_approvals(None)
    hist = await fresh.get_scan_history()
    audit = next(row for row in hist["entries"] if row.get("event_type") == "approval_reviewed")
    assert audit["provenance"] == "genuine"
    assert audit["item_id"] == "e-1"
    assert all(item["item_id"] != audit["scan_id"] for item in got["items"])
    sink_rows, _ = history.read_history_page(history._history_path(), before=None, limit=50)
    sink_audit = next(row for row in sink_rows if row.get("event_type") == "approval_reviewed")
    assert sink_audit["item_id"] == "e-1"


# ── Routes ────────────────────────────────────────────────────────────────


def _pipeline(secret: bytes | None = None) -> Pipeline:
    return Pipeline(
        scanners=[MinimalScanner()],
        config=PetasosConfig(fail_mode="degraded", session_secret=secret),
        host_id="test-host",
    )


@pytest.fixture(params=["standalone", "plugin"])
def client(request: pytest.FixtureRequest) -> Iterator[tuple[Any, str, str]]:
    from fastapi.testclient import TestClient

    token = "console-token"
    plugin_mod._handlers = None
    if request.param == "standalone":
        from petasos.console.server import build_app

        with TestClient(build_app(_pipeline(b"route-secret"), auth_token=token)) as tc:
            yield tc, "/api", token
    else:
        from fastapi import FastAPI

        from petasos.console.hermes.plugin_api import init_handlers, router

        init_handlers(_pipeline(b"route-secret"))
        app = FastAPI()
        app.include_router(router, prefix="/api/plugins/petasos")
        with TestClient(app) as tc:
            yield tc, "/api/plugins/petasos", ""


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


def test_route_statuses(client: tuple[Any, str, str], profiles: Path) -> None:
    tc, base, token = client
    headers = _auth(token)
    unknown = tc.get(base + "/approvals/refused", params={"profile": "ghost"}, headers=headers)
    assert unknown.status_code == 422
    bad_mark = tc.post(
        base + "/approvals/reviewed",
        params={"profile": "ghost"},
        json={"item_id": "e-x"},
        headers=headers,
    )
    assert bad_mark.status_code == 422
    not_equipped = tc.post(
        base + "/approvals/reviewed",
        json={"item_id": "e-x", "profile": "beta"},
        headers=headers,
    )
    assert not_equipped.status_code == 409
    disagree = tc.post(
        base + "/approvals/reviewed",
        params={"profile": "alpha"},
        json={"item_id": "e-x", "profile": "beta"},
        headers=headers,
    )
    assert disagree.status_code == 422
    bad_id = tc.post(
        base + "/approvals/reviewed",
        json={"item_id": 5},
        headers=headers,
    )
    assert bad_id.status_code == 422
    missing = tc.post(
        base + "/approvals/reviewed",
        json={"item_id": "e-missing"},
        headers=headers,
    )
    assert missing.status_code == 422


def test_query_profile_on_reviewed_write_is_honored(
    client: tuple[Any, str, str], profiles: Path
) -> None:
    tc, base, token = client
    # No item in the equipped window: a ghost query is 422, an equipped query is 422
    # on the item rather than 409. That is the PET-238 distinction.
    equipped = tc.post(
        base + "/approvals/reviewed",
        params={"profile": "alpha"},
        json={"item_id": "e-missing"},
        headers=_auth(token),
    )
    assert equipped.status_code == 422
    assert equipped.json()["detail"][0]["field"] == "item_id"


def test_standalone_token_gate(profiles: Path) -> None:
    from fastapi.testclient import TestClient

    from petasos.console.server import build_app

    with TestClient(build_app(_pipeline())) as open_tc:
        refused = open_tc.get("/api/approvals/refused")
        assert refused.status_code == 200
        assert refused.json()["review_write"] == {"available": False, "reason": "no_console_token"}
        denied = open_tc.post("/api/approvals/reviewed", json={"item_id": "e-x"})
        assert denied.status_code == 403
    with TestClient(build_app(_pipeline(), auth_token="tok")) as gated:
        missing = gated.post("/api/approvals/reviewed", json={"item_id": "e-x"})
        assert missing.status_code == 401
        present = gated.post(
            "/api/approvals/reviewed",
            json={"item_id": "e-x"},
            headers={"Authorization": "Bearer tok"},
        )
        assert present.status_code == 422
    assert any(
        getattr(route, "path", "") == "/approvals/reviewed" for route in plugin_mod.router.routes
    )
    from petasos.console.server import build_app as _build

    app = _build(_pipeline())
    standalone_paths = {getattr(route, "path", "") for route in app.routes}
    assert "/api/approvals/reviewed" in standalone_paths
    assert "/approvals/reviewed" not in standalone_paths


# ── Plugin excerpt ────────────────────────────────────────────────────────


def _plugin(monkeypatch: pytest.MonkeyPatch) -> Any:
    calls: list[tuple[Any, ...]] = []

    def redact(text: str, force: bool = False, redact_url_credentials: bool = False) -> str:
        calls.append((text, force, redact_url_credentials))
        if text.startswith("api_key="):
            return "api_key=***"
        masked = text
        token = "ghp_" + ("a" * 18) + ("b" * 18)
        if token in masked:
            masked = masked.replace(token, "***")
        return masked

    _install_redactor(monkeypatch, redact)
    module = _load_plugin()
    module._redact_calls = calls
    return module


def _excerpt(module: Any, args: object, findings: tuple[Any, ...] = ()) -> str:
    text = module._approval_command_excerpt(args, _Result(findings))
    if not isinstance(text, str):
        raise AssertionError("excerpt is not str")
    return text


def test_command_excerpt_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _plugin(monkeypatch)
    one = _excerpt(module, {"command": "rm -rf build"})
    assert one == 'command="rm -rf build"'
    two = _excerpt(module, {"command": "rm -rf build", "workdir": "/srv"})
    assert two == 'command="rm -rf build" workdir="/srv"'
    recorded = module._redact_calls
    assert ("command=rm -rf build", True, True) in recorded
    assert ("workdir=/srv", True, True) in recorded
    message = module._approve_return("terminal", "s", "petasos.syntactic.command.fetch-exec", one)
    assert message["message"].endswith(
        "Rule: petasos.syntactic.command.fetch-exec. "
        'Command (from tool arguments): command="rm -rf build"'
    )
    degraded = module._approve_return("terminal", "s", "petasos.degraded", one)
    assert (
        "Parameter scan is unreliable (petasos.degraded). Command (from tool arguments):"
        in degraded["message"]
    )


def test_excerpt_withheld_cut_and_escaping(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _plugin(monkeypatch)
    pii = _excerpt(module, {"command": "rm"}, (_Finding("pii"),))
    assert pii == "withheld (PII in parameters)"
    monkeypatch.delitem(sys.modules, "agent.redact", raising=False)
    monkeypatch.delitem(sys.modules, "agent", raising=False)
    blocked = types.ModuleType("agent")
    monkeypatch.setitem(sys.modules, "agent", blocked)
    assert _excerpt(module, {"command": "rm"}) == "withheld (redactor unavailable)"
    _plugin(monkeypatch)
    module = _plugin(monkeypatch)
    assert _excerpt(module, ["rm -rf build"]) == "withheld (excerpt unavailable)"
    assert _excerpt(module, {}) == "(no parameters)"
    long = "a" * 500
    cut = _excerpt(module, {"command": long})
    body, suffix = cut.split(" (+", 1)
    assert len(body) == 160
    assert body == 'command="' + ("a" * 150) + '"'
    assert suffix.startswith("350 chars not shown)")
    second = _excerpt(module, {"command": "a" * 150, "workdir": "/srv"})
    assert second.endswith("(+12 chars not shown)")
    assert "workdir" not in second.split(" (+", 1)[0]
    newline = _excerpt(module, {"command": "echo safe # comment\nrm -rf /home/user/project"})
    assert newline == 'command="echo safe # comment\\nrm -rf /home/user/project"'
    quotes = _excerpt(module, {"command": 'echo "$(rm -rf x)"'})
    assert quotes == 'command="echo \\"$(rm -rf x)\\""'
    controls = _excerpt(module, {"command": "a\u0085b\u2028c\u2029d"})
    assert "\\u0085" in controls and "\\u2028" in controls and "\\u2029" in controls
    hidden = _excerpt(module, {"command": "rm\x1b\x00\u202e\u200bbuild"})
    assert hidden.endswith(" (invisible characters removed)")
    assert "\x1b" not in hidden and "\u202e" not in hidden and "\u200b" not in hidden
    both = _excerpt(module, {"command": ("a" * 500) + "\x1b"})
    assert both.endswith(" (invisible characters removed)")
    assert "(+" in both and both.index("(+") < both.index("(invisible")
    keyed = _excerpt(module, {"command": "x", "api_key": "b" * 32})
    assert "b" * 32 not in keyed
    with_url = _excerpt(module, {"command": "x", "api_key": "c" * 32, "url": "https://host/x"})
    assert "c" * 32 not in with_url
    long_key = "k" * 300
    shown = _excerpt(module, {long_key: "v"})
    head, rest = shown.split(" (+", 1)
    assert len(head) == 160
    n = int(rest.split(" ", 1)[0])
    assert n == (300 - 158) + 1 + 1
    nested_esc = _excerpt(module, {"env": {"note": "\x1b"}})
    assert "\x1b" not in nested_esc
    assert not nested_esc.endswith(" (invisible characters removed)")
    odd_key = _excerpt(module, {"x\n": ""})
    assert odd_key.startswith('"x\\n"=')
    cafe = _excerpt(module, {"meta": {"name": "café"}})
    assert "café" in cafe
    assert "\\u00e9" not in cafe
    split = "ghp_" + ("a" * 18) + "\u2066" + ("b" * 18)
    masked = _excerpt(module, {"command": split})
    assert split not in masked
    assert "ghp_" + ("a" * 18) + ("b" * 18) not in masked
    assert masked.endswith(" (invisible characters removed)")
    nested = _excerpt(module, {"env": {"TOKEN": split}})
    assert split.replace("\u2066", "") not in nested
    assert nested.endswith(" (invisible characters removed)")


def test_rule_key_is_unchanged_by_the_excerpt(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _plugin(monkeypatch)
    monkeypatch.setattr(module, "_rule_always_approved", lambda _key: False)
    finding = ScanFinding(
        rule_id="petasos.syntactic.command.fetch-exec",
        finding_type="command",
        severity=Severity.HIGH,
        confidence=1.0,
        message="finding",
        scanner_name="minimal",
    )
    result = GuardResult(
        allowed=True,
        reason="allowed",
        findings=(finding,),
        tier="none",
        param_scan_unsafe=True,
        param_scan_degraded=False,
    )
    out = module._dangerous_tool_directive(
        "terminal",
        {"command": "rm -rf build"},
        "s",
        result,
        False,
        "approve",
        True,
        False,
    )
    assert out is not None
    assert out["rule_key"] == finding.rule_id
    assert out["action"] == "approve"


@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("control", [chr(1), chr(10), chr(0x2066)])
def test_excerpt_redacts_original_vault_value(
    monkeypatch: pytest.MonkeyPatch, nested: bool, control: str
) -> None:
    secret = "synthetic-vault" + control + "-password-example"
    calls: list[str] = []

    def redact(text: str, **kwargs: bool) -> str:
        assert kwargs == {"force": True, "redact_url_credentials": True}
        calls.append(text)
        return text.replace(secret, "[redacted-vault]")

    _install_redactor(monkeypatch, redact)
    args = {"command": {"items": [secret]} if nested else secret}
    before = json.dumps(args)
    shown = _excerpt(_load_plugin(), args)
    assert secret in calls  # the host sees original bytes, before escaping or joining
    assert "[redacted-vault]" in shown
    assert "password-example" not in shown
    assert not shown.startswith("withheld")
    assert json.dumps(args) == before


def test_excerpt_nested_field_context_and_original_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    opaque = "synthetic-opaque-value"
    secret_key = "synthetic" + chr(1) + "-secret-key"

    def redact(text: str, **_kwargs: bool) -> str:
        if text == "password=" + opaque:
            return "password=[redacted-field]"
        return text.replace(secret_key, "[redacted-key]")

    _install_redactor(monkeypatch, redact)
    args = {"env": {"password": [opaque], secret_key: 1}}
    before = json.dumps(args)
    shown = _excerpt(_load_plugin(), args)
    assert "[redacted-field]" in shown
    assert "[redacted-key]" in shown
    assert opaque not in shown
    assert "secret-key" not in shown
    assert json.dumps(args) == before


@pytest.mark.parametrize("bad_result", [None, 42, RuntimeError("synthetic-secret")])
def test_excerpt_leaf_redaction_failure_withholds(
    monkeypatch: pytest.MonkeyPatch, bad_result: object
) -> None:
    def redact(_text: str, **_kwargs: bool) -> Any:
        if isinstance(bad_result, Exception):
            raise bad_result
        return bad_result

    _install_redactor(monkeypatch, redact)
    shown = _excerpt(_load_plugin(), {"env": {"password": "synthetic-secret"}})
    assert shown.startswith("withheld")
    assert "synthetic-secret" not in shown


@pytest.mark.parametrize("shape", ["cycle", "depth", "nodes", "characters", "object"])
def test_excerpt_unsafe_structure_withholds(monkeypatch: pytest.MonkeyPatch, shape: str) -> None:
    module = _plugin(monkeypatch)
    value: Any = []
    if shape == "cycle":
        value.append(value)
    elif shape == "depth":
        for _ in range(module._EXCERPT_MAX_DEPTH + 1):
            value = [value]
    elif shape == "nodes":
        value = [0] * module._EXCERPT_MAX_NODES
    elif shape == "characters":
        value = "x" * (module._MAX_PARAM_TEXT_LEN + 1)
    else:
        value = object()
    assert _excerpt(module, {"command": value}) == "withheld (excerpt unavailable)"


def test_description_cap_is_400() -> None:
    module = _load_plugin()
    assert module._APPROVAL_DESCRIPTION_MAX == server._MAX_APPROVAL_DESCRIPTION_LEN == 400
    assert module._APPROVAL_FIELD_MAX == server._MAX_REASON_LEN
    text = "d" * 450
    assert module._approval_text(text, limit=module._APPROVAL_DESCRIPTION_MAX) == "d" * 400
    summary = server._enforcement_summary({"event_type": "approval", "description": text})
    assert summary["description"] == "d" * 400
    assert summary["item_id"] is None
    reviewed = server._enforcement_summary(
        {"event_type": "approval_reviewed", "item_id": "e-1", "description": text}
    )
    assert reviewed["item_id"] == "e-1"
