"""Backend-free tests for the composition gate. No Hermes, no ML runtime, no network."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

import pytest

from scripts import hermes_composition_gate as gate
from scripts import hermes_multiprofile_harness as harness

_STAGES = {name: "passed" for name in gate.REQUIRED_STAGES}


def _passed() -> dict[str, str]:
    return dict(_STAGES)


def test_matrix_selection_is_read_only(tmp_path: Path) -> None:
    """Selection keeps armed profiles, says why each other one is excluded, and edits no file."""
    live = tmp_path / "live"
    root_plugin = live / "plugins" / "petasos"
    root_plugin.mkdir(parents=True)
    (live / "config.yaml").write_text("petasos:\n  fail_mode: closed\n", encoding="utf-8")
    (root_plugin / "plugin.yaml").write_text("name: petasos\n", encoding="utf-8")
    (live / "gateway.parked").write_text("ignored for the root\n", encoding="utf-8")

    def home(name: str, config: str | None, *, plugin: bool, parked: bool) -> None:
        """Create one named profile home under the fake live root."""
        path = live / "profiles" / name
        path.mkdir(parents=True)
        if config is not None:
            (path / "config.yaml").write_text(config, encoding="utf-8")
        if plugin:
            plug = path / "plugins" / "petasos"
            plug.mkdir(parents=True)
            (plug / "plugin.yaml").write_text("name: petasos\n", encoding="utf-8")
        if parked:
            (path / "gateway.parked").write_text("parked\n", encoding="utf-8")

    home("armed", "petasos:\n  fail_mode: open\n", plugin=True, parked=False)
    home("missing", None, plugin=True, parked=False)
    home("bad", "{not yaml: [\n", plugin=True, parked=False)
    home("nosection", "plugins:\n  enabled: []\n", plugin=True, parked=False)
    home("nocopy", "petasos:\n  enabled: true\n", plugin=False, parked=False)
    home("parked", "petasos:\n  enabled: true\n", plugin=True, parked=True)
    extra = live / "notes.txt"
    extra.write_text("untouched\n", encoding="utf-8")
    before = {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in live.rglob("*")
        if path.is_file()
    }
    included, excluded = gate.select_matrix(live)
    after = {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in live.rglob("*")
        if path.is_file()
    }
    assert before == after
    assert [item["name"] for item in included] == ["default", "armed"]
    reasons = {item["name"]: item["reason"] for item in excluded}
    assert reasons["missing"] == "no_config"
    assert reasons["bad"] == "no_config"
    assert reasons["nosection"] == "no_section"
    assert reasons["nocopy"] == "no_plugin_copy"
    assert reasons["parked"] == "parked"
    assert "default" not in reasons

    def empty() -> int:
        gate.require_matrix([])
        return 0

    assert gate.guarded(empty) == 2


def test_section_copy_withholds_and_records_overrides() -> None:
    """The copied section drops secrets and unknown keys and records both forced overrides."""
    copied = gate.copy_section(
        {
            "fail_mode": "closed",
            "semgrep_enabled": False,
            "hash_key": "secret-hash",
            "session_secret": "c2VjcmV0",
            "host_id": "box",
            "not_a_field": 1,
        }
    )
    assert copied["section"]["fail_mode"] == "closed"
    assert copied["section"]["enabled"] is True
    assert copied["section"]["semgrep_enabled"] is True
    assert copied["overrides"]["enabled"] == [None, True]
    assert copied["overrides"]["semgrep_enabled"] == [False, True]
    assert set(copied["withheld_keys"]) == {"hash_key", "session_secret", "host_id", "not_a_field"}
    for key in ("hash_key", "session_secret", "host_id", "not_a_field"):
        assert key not in copied["section"]


def test_call_ids_are_unique_for_a_planned_run() -> None:
    """Every planned call has its own tool call id and turn id, which Hermes's hook gate needs."""
    plan = gate.plan_run_calls(["only"], warmup_rounds=2, approve_profiles=["only"])
    call_ids = [item["tool_call_id"] for item in plan]
    turn_ids = [item["turn_id"] for item in plan]
    assert len(call_ids) == len(set(call_ids))
    assert len(turn_ids) == len(set(turn_ids))
    for item in plan:
        assert item["task_id"] and item["session_id"] and item["tool_call_id"] and item["turn_id"]
        assert item["task_id"] == item["session_id"]
    load = [item for item in plan if item["tool_call_id"].startswith("load-only-")]
    three = load[:3]
    assert len({item["tool_call_id"] for item in three}) == 3
    assert len({item["turn_id"] for item in three}) == 3
    assert {item["session_id"] for item in three} == {"load-0", "load-1", "load-2"}
    assert any(item["tool_call_id"].startswith("approval-only-") for item in plan)
    assert any(item["session_id"].startswith("cold-") for item in plan)
    assert any(item["session_id"].startswith("neg-only") for item in plan)


def test_host_skip_is_per_stage() -> None:
    """A Hermes skip message fails only the stage it was logged in."""
    stages = ["cold-first", "warmup", "corpus", "load", "negative"]
    unrelated = {"setup": ["plugin loaded slowly"]}
    checks = gate.host_skip_checks(unrelated)
    assert checks[0]["ok"] is True
    for index, text in enumerate(gate.HOST_SKIP_TEXTS):
        by_stage: dict[str, list[str]] = {stage: [] for stage in stages}
        by_stage[stages[index]] = [f"Hook callback {text} in this stage"]
        found = {item["check"]: item["ok"] for item in gate.host_skip_checks(by_stage)}
        assert found[f"hooks.no_host_skip.{stages[index]}"] is False
        for stage in stages:
            if stage != stages[index]:
                assert found[f"hooks.no_host_skip.{stage}"] is True


def test_spool_reader_reports_line_numbers_and_honors_the_start() -> None:
    """The spool reader skips rows before the start count and numbers each bad line."""
    text = "\n".join(
        [
            json.dumps({"event_type": "old", "session_id": "before"}),
            "{torn",
            json.dumps(["not", "an", "object"]),
            json.dumps({"event_type": "quarantine", "session_id": "s"}),
            "{still torn",
            "null",
        ]
    )
    rows, bad = gate.read_spool_text(text, start_count=3)
    assert [row["event_type"] for row in rows] == ["quarantine"]
    assert bad == [(5, "torn"), (6, "not-object")]
    early_rows, early_bad = gate.read_spool_text(text, start_count=0)
    assert any(row["session_id"] == "before" for row in early_rows)
    assert (2, "torn") in early_bad
    ignored_rows, ignored_bad = gate.read_spool_text(text, start_count=6)
    assert ignored_rows == []
    assert ignored_bad == []


def test_check_file_keeps_the_last_check_when_a_probe_dies(tmp_path: Path) -> None:
    path = tmp_path / "checks-hooks.jsonl"
    gate.append_check(path, "hooks.boot", True, "")
    gate.append_check(path, "hooks.bound.1", False, "slow")
    checks = gate.with_completed("hooks", gate.read_checks(path), finished=False)
    assert checks[-1]["check"] == "hooks.completed"
    assert checks[-1]["ok"] is False
    assert checks[-1]["detail"]["last"] == "hooks.bound.1"
    verdict = gate.verdict_of(checks, stages={**_passed(), "hooks": "failed"})
    assert verdict["verdict"] == "no-go"
    assert "hooks.completed" in verdict["failed"]


def test_isolated_config_has_no_approval_or_timeout() -> None:
    config = gate.isolated_config({"fail_mode": "closed", "enabled": True})
    assert config["plugins"]["enabled"] == ["petasos"]
    assert config["gateway"]["multiplex_profiles"] is True
    assert config["petasos"]["fail_mode"] == "closed"
    assert "approvals" not in config
    assert "hook_callback_timeout" not in config["plugins"]


def test_corpus_file_shape() -> None:
    """The tracked corpus validates, has unique case ids, and carries measured margins."""
    corpus = gate.load_corpus()
    assert gate.validate_corpus(corpus) == []
    ids = [case["id"] for case in corpus["cases"]]
    assert len(ids) == len(set(ids))
    for case in corpus["cases"]:
        assert case["hook"] and case["class"] and case["tool"] and case["why"]
        if case["class"] in ("promptguard-only", "classic-injection", "pii-egress"):
            calibration = case["calibration"]
            assert calibration
            # Decision A8: a positive is admitted on a measured confidence at or above its bar.
            assert calibration["measured"] is True
            assert calibration["measured_confidence"] >= calibration["min_confidence"]
        else:
            assert case["calibration"] is None
    for name, block in corpus["profiles"].items():
        assert "assumes" in block
        for case in corpus["cases"]:
            rules = block["expect"][case["id"]]["rule_id"]
            assert isinstance(rules, list)
            if case["class"] == "classic-injection" and rules:
                assert len(rules) > 1
            elif rules:
                assert len(rules) == 1
        assert name in ("default", "gibson", "ops")


def test_expectation_lookup_uses_defaults_and_json_tuples() -> None:
    corpus = gate.load_corpus()
    missing = gate.expectation_problem(corpus, "no-such", {})
    assert missing is not None
    assert missing[0] == "corpus.no_expectations.no-such"
    defaults = gate.config_defaults()
    copied = {"fail_mode": "closed"}
    assert (
        gate.assumes_diff(
            {"fail_mode": "closed", "egress_sink_tools": defaults["egress_sink_tools"]},
            copied,
        )
        == []
    )
    differ = gate.assumes_diff({"fail_mode": "open", "tool_guard_enabled": True}, copied)
    assert differ == ["fail_mode"]
    problem = gate.expectation_problem(
        {"profiles": {"demo": {"assumes": {"fail_mode": "open"}, "expect": {}}}},
        "demo",
        copied,
    )
    assert problem is not None
    assert problem[0] == "corpus.assumes.demo"
    assert problem[1] == ["fail_mode"]


def test_match_function_fails_one_field_at_a_time() -> None:
    """One wrong field in a spool row or directive fails the match and is named."""
    row = {
        "session_id": "s",
        "event_type": "quarantine",
        "rule_id": "petasos.promptguard.injection",
        "param_scan_degraded": False,
    }
    expect = {
        "directive": "block",
        "event_type": "quarantine",
        "rule_id": ["petasos.promptguard.injection"],
    }
    base: dict[str, Any] = {
        "directive": "block",
        "home": "default",
        "session": "s",
        "rows_by_home": {"default": [row], "other": []},
        "verified": True,
    }
    assert gate.match_case(expect, **base) == (True, "ok")
    cases = {
        "directive": {**base, "directive": "pass"},
        "row-count": {**base, "rows_by_home": {"default": [row, dict(row)], "other": []}},
        "other-home": {**base, "rows_by_home": {"default": [row], "other": [dict(row)]}},
        "rule_id": {
            **base,
            "rows_by_home": {
                "default": [{**row, "rule_id": "petasos.other"}],
                "other": [],
            },
        },
        "param_scan_degraded": {
            **base,
            "rows_by_home": {
                "default": [{**row, "param_scan_degraded": True}],
                "other": [],
            },
        },
        "unverified": {**base, "verified": False},
    }
    for reason, kwargs in cases.items():
        ok, why = gate.match_case(
            expect,
            directive=kwargs["directive"],
            home=kwargs["home"],
            session=kwargs["session"],
            rows_by_home=kwargs["rows_by_home"],
            verified=kwargs["verified"],
        )
        assert ok is False
        assert why == reason
    body = "payload text"
    notice = "banner\n\n" + body
    unscanned = [{"session_id": "s", "event_type": "ingest_unscanned", "rule_id": None}]
    assert gate.classify_tool_result(notice, body, unscanned) == "unscanned"
    rows_by_home = {"default": unscanned}
    assert (
        gate.match_case(
            {"class": "annotated", "rule_id": ["x"]},
            return_class="unscanned",
            home="default",
            session="s",
            rows_by_home=rows_by_home,
            verified=True,
        )[0]
        is False
    )
    assert (
        gate.match_case(
            {"class": "clean", "rule_id": []},
            return_class="unscanned",
            home="default",
            session="s",
            rows_by_home=rows_by_home,
            verified=True,
        )[0]
        is False
    )


def test_cold_first_classifier() -> None:
    """Cold-first outcomes are allowed or refused by fail mode, directive and spool rows."""

    def quarantine(reason: str = "cold") -> dict[str, Any]:
        return {"event_type": "quarantine", "param_scan_degraded": True, "reason": reason}

    marker = {"event_type": "cold_start_degraded"}
    for mode in ("closed", "degraded"):
        got = gate.classify_cold_first(
            fail_mode=mode, directive="block", message="blocked", wall_s=1, rows=[quarantine()]
        )
        assert got["outcome"] == "fail_mode_block" and got["allowed"] is True
    refused = gate.classify_cold_first(
        fail_mode="open", directive="block", message="blocked", wall_s=1, rows=[quarantine()]
    )
    assert refused["outcome"] == "fail_mode_block" and refused["allowed"] is False
    for mode in ("open", "closed", "degraded"):
        got = gate.classify_cold_first(
            fail_mode=mode,
            directive="block",
            message="blocked",
            wall_s=1,
            rows=[quarantine("guard evaluation unavailable: evaluation_timeout")],
        )
        assert got["outcome"] == "evaluation_block" and got["allowed"] is True
        allowed = gate.classify_cold_first(
            fail_mode=mode, directive=None, message=None, wall_s=1, rows=[marker]
        )
        assert allowed["outcome"] == "pass" and allowed["allowed"] is True
        second = gate.classify_cold_first(
            fail_mode=mode, directive=None, message=None, wall_s=1, rows=[marker, dict(marker)]
        )
        assert second["allowed"] is False
        init = gate.classify_cold_first(
            fail_mode=mode,
            directive="block",
            message="blocked",
            wall_s=1,
            rows=[quarantine(), {"event_type": "init_failed"}],
        )
        assert init["reason"] == "init_failed"
        wall = gate.classify_cold_first(
            fail_mode=mode, directive=None, message=None, wall_s=30, rows=[]
        )
        assert wall["allowed"] is False
        timed = gate.classify_cold_first(
            fail_mode=mode, directive=None, message=gate.TIMEOUT_MESSAGE, wall_s=1, rows=[]
        )
        assert timed["allowed"] is False
    spool: list[dict[str, Any]] = []
    for session in ("a", "b", "c"):
        spool.append({"session_id": session, "event_type": "cold_start_degraded"})
        spool.append(
            {
                "session_id": session,
                "event_type": "quarantine",
                "param_scan_degraded": True,
                "reason": "cold",
            }
        )
    for session in ("a", "b", "c"):
        rows = [row for row in spool if row["session_id"] == session]
        got = gate.classify_cold_first(
            fail_mode="closed", directive="block", message="blocked", wall_s=1, rows=rows
        )
        assert got["outcome"] == "fail_mode_block" and got["allowed"] is True


def test_negative_rule() -> None:
    """With PromptGuard absent, closed and degraded block, and open passes."""
    closed = gate.negative_expectation(tool_guard_enabled=True, fail_mode="closed")
    degraded = gate.negative_expectation(tool_guard_enabled=True, fail_mode="degraded")
    opened = gate.negative_expectation(tool_guard_enabled=True, fail_mode="open")
    disabled = gate.negative_expectation(tool_guard_enabled=False, fail_mode="closed")
    assert closed["directive"] == "block" and closed["event_type"] == "quarantine"
    assert closed["param_scan_degraded"] is True and closed["rule_id"] is None
    assert closed["reason"] == "param scan degraded"
    assert degraded["directive"] == "block"
    assert opened["directive"] == "pass" and opened["event_type"] is None
    assert disabled["recorded_as"] == "guard_disabled" and disabled["directive"] == "pass"
    for item in (closed, degraded, opened, disabled):
        assert item["health"]["status"] == "unavailable"
        assert item["health"]["last_error_nonempty"] is True
    hidden = {
        "fail_mode": "closed",
        "blocked": True,
        "c01_matched": False,
        "c04_matched": True,
    }
    shown = {
        "fail_mode": "degraded",
        "blocked": True,
        "c01_matched": True,
        "c04_matched": True,
    }
    assert gate.negative_block_shown([hidden]) is False
    assert gate.negative_block_shown([shown]) is True
    assert gate.negative_block_shown([]) is False


def test_health_mapping() -> None:
    assert gate.HEALTH_TABLE["disabled"]["build"] == "disabled"
    assert gate.HEALTH_TABLE["disabled"]["runtime"] is None
    assert gate.HEALTH_TABLE["disabled"]["console"] is None
    assert gate.HEALTH_TABLE["package_absent"]["build"] == "degraded"
    assert gate.HEALTH_TABLE["package_absent"]["runtime"] == "unavailable"
    assert gate.HEALTH_TABLE["package_absent"]["console"] == "unavailable"
    assert gate.HEALTH_TABLE["usable"]["build"] == "verified"
    assert gate.HEALTH_TABLE["usable"]["runtime"] == "healthy"
    assert gate.HEALTH_TABLE["usable"]["console"] == "healthy"
    semgrep = gate.HEALTH_TABLE["semgrep_refused"]
    assert semgrep["build"] == "failed"
    assert semgrep["reason"] == "semgrep.host_lifecycle_unavailable"
    assert semgrep["runtime"] is None
    assert semgrep["console"] == "semgrep.host_lifecycle_unavailable"


def test_verdict_ignores_info_timing_and_unexercised_approval() -> None:
    assert gate.verdict_of([{"check": "a", "ok": True}], stages=_passed())["verdict"] == "go"
    failed = gate.verdict_of([{"check": "corpus.default.C01", "ok": False}], stages=_passed())
    assert failed["verdict"] == "no-go"
    assert failed["failed"] == ["corpus.default.C01"]
    stage1 = {
        "stage1": "failed",
        "hooks": "skipped",
        "cold": "skipped",
        "negative": "skipped",
        "dash": "skipped",
    }
    skipped = gate.verdict_of([{"check": "stage1.bootstrap", "ok": False}], stages=stage1)
    assert skipped["verdict"] == "no-go"
    assert skipped["skipped"] == ["hooks", "cold", "negative", "dash"]
    checks = [
        {"check": "a", "ok": True},
        {"check": "approval.exercised", "ok": False},
        {"check": "timing.load.p95", "ok": False},
        {"check": "info.semgrep_refusal_log_lines", "ok": False},
    ]
    assert gate.verdict_of(checks, stages=_passed())["verdict"] == "go"


def test_redaction_rewrites_spellings_and_passes_an_oserror(tmp_path: Path) -> None:
    """Redaction rewrites every spelling of a root and the sweep refuses what is left."""
    home = tmp_path / "HomeBox"
    live = tmp_path / "LiveRoot"
    work = tmp_path / "WorkDir"
    tree = tmp_path / "TreeDir"
    for path in (home, live, work, tree):
        path.mkdir()
    roots = [
        ("<home>", str(home)),
        ("<live>", str(live)),
        ("<workdir>", str(work)),
        ("<tree>", str(tree)),
    ]
    needles = {
        "home": str(home),
        "live": str(live),
        "workdir": str(work),
        "tree": str(tree),
        "hostname": "deskbox",
        "username": "al",
    }
    for placeholder, raw in roots:
        label = placeholder.strip("<>")
        for spelling in gate.path_spellings(raw):
            assert gate.sweep_text(f"see {spelling} end", **needles) == (
                "home" if label == "home" else label if label != "workdir" else "workdir"
            )
            rewritten = gate.rewrite_text(f"see {spelling} end", roots)
            assert placeholder in rewritten
            assert gate.sweep_text(rewritten, **needles) is None
    target = home / "secret.txt"
    detail = str(OSError(13, "denied", str(target)))
    clean = gate.rewrite({"checks": [{"detail": detail}]}, roots)
    assert gate.sweep(clean, **needles) is None
    assert gate.sweep("algebra is a word", **{**needles, "username": "al"}) is None
    assert gate.sweep("notes\\al\\file", **needles) == "user"
    published = gate.publish_row({"event_type": "quarantine", "sig": "abc", "sig_verified": True})
    assert "sig" not in published
    assert published["sig_verified"] is True


def test_evidence_write_is_atomic_and_labeled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "composition-demo.json"

    def explode(src: str | Path, dst: str | Path) -> None:
        del src, dst
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", explode)
    with pytest.raises(OSError):
        gate.write_text_atomic(path, "{}\n")
    assert not path.exists()
    monkeypatch.undo()
    gate.write_text_atomic(path, "{}\n")
    assert path.read_text(encoding="utf-8") == "{}\n"
    assert gate.evidence_name("demo") == "composition-demo.json"

    def bad_label() -> int:
        gate.require_label("Nope")
        return 0

    assert gate.guarded(bad_label) == 2
    blocked = tmp_path / "composition-blocked.json"
    with pytest.raises(gate.SweepError):
        gate.commit_evidence(
            blocked,
            {"note": "deskbox"},
            roots=[],
            home=str(tmp_path / "h"),
            live=str(tmp_path / "l"),
            workdir=str(tmp_path / "w"),
            tree=str(tmp_path / "t"),
            hostname="deskbox",
            username="zz",
        )
    assert not blocked.exists()


def test_wheel_and_tree_and_workdir(tmp_path: Path) -> None:
    """Preflight refuses a wheel that differs from the tree, a wrong name, and a bad workdir."""
    tree = tmp_path / "tree"
    member = b"x = 1\n"
    (tree / "petasos").mkdir(parents=True)
    (tree / "petasos" / "__init__.py").write_bytes(member)
    wheel = tmp_path / gate.WHEEL_NAME
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("petasos/__init__.py", member)
        archive.writestr("README", b"ignored")
    assert gate.wheel_failures(wheel, tree) == []
    (tree / "petasos" / "__init__.py").write_bytes(b"x = 2\n")
    assert any(item.startswith("changed member") for item in gate.wheel_failures(wheel, tree))
    (tree / "petasos" / "__init__.py").unlink()
    assert any(item.startswith("missing from tree") for item in gate.wheel_failures(wheel, tree))
    wrong = tmp_path / "petasos-0.4.0-py3-none-any.whl"
    wrong.write_bytes(wheel.read_bytes())
    assert gate.wheel_failures(wrong, tree) == ["wrong file name"]
    assert gate.release_diff_ok([]) is True
    assert gate.release_diff_ok(["petasos/__init__.py"]) is True
    assert gate.release_diff_ok(["petasos/config.py"]) is False
    assert gate.release_diff_ok(["petasos/__init__.py", "petasos/config.py"]) is False

    def spaced() -> int:
        gate.require_workdir(Path("C:/has space/work"))
        return 0

    def comma() -> int:
        gate.require_workdir(Path("C:/has,comma/work"))
        return 0

    assert gate.guarded(spaced) == 2
    assert gate.guarded(comma) == 2


def test_load_plan_and_barrier_abort() -> None:
    """Eight calls are spread over the profiles, and one failed worker aborts the barrier."""
    assert gate.load_bindings(1) == [0, 0, 0, 0, 0, 0, 0, 0]
    assert gate.load_bindings(3) == [0, 1, 2, 0, 1, 2, 0, 1]
    assert gate.load_bindings(8) == list(range(8))
    assert gate.load_bindings(10) == list(range(8))
    assert all(0 <= item < 10 for item in gate.load_bindings(10))

    def make(index: int) -> Any:
        """Build a worker that fails for index 0 and waits at the barrier otherwise."""

        def worker(barrier: Any) -> None:
            """Raise for index 0, else wait at the barrier."""
            if index == 0:
                raise RuntimeError("boom")
            barrier.wait()

        return worker

    errors = gate.run_outstanding([make(index) for index in range(8)])
    assert errors and "boom" in errors[0]
    assert (not errors) is False


def test_exit_codes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gate, "STAGE", "wipe")

    def boom() -> int:
        raise RuntimeError("boom")

    assert gate.guarded(boom) == 6
    assert "unexpected error during wipe" in capsys.readouterr().out

    def busy() -> int:
        raise gate.PreflightError("isolated root busy: locked")

    assert gate.guarded(busy) == 2
    root = tmp_path / "hermes"
    (root / "installs").mkdir(parents=True)

    def deny(path: Path) -> None:
        raise PermissionError(path)

    monkeypatch.setattr(shutil, "rmtree", deny)
    with pytest.raises(gate.PreflightError, match="isolated root busy"):
        gate.wipe_isolated(root)


def test_probe_exit_4_writes_no_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tree = Path(__file__).resolve().parents[1]
    wheel = tmp_path / "petasos-0.5.0-py3-none-any.whl"
    wheel.write_bytes(b"placeholder")
    live = tmp_path / "live"
    (live / "hermes-agent").mkdir(parents=True)
    work = tmp_path / "work"
    work.mkdir()
    # An older evidence file for the same label must not survive a run that writes none.
    (work / "composition-probe4.json").write_text("stale", encoding="utf-8")
    monkeypatch.setattr(gate, "_require_release", lambda _tree: None)
    monkeypatch.setattr(gate, "wheel_failures", lambda _wheel, _tree: [])
    monkeypatch.setattr(gate, "_git", lambda _tree, *_args: "")
    monkeypatch.setattr(
        gate,
        "_read_stamp",
        lambda _live: {"baseVersion": "0.22.5", "displayVersion": "0.22.5"},
    )
    monkeypatch.setattr("petasos.scanners.prompt_guard._snapshot_complete", lambda: True)
    monkeypatch.setattr(
        gate,
        "select_matrix",
        lambda _live: (
            [{"name": "default", "path": live, "section": {"fail_mode": "closed"}}],
            [],
        ),
    )

    # drive() and the fake below assign these module globals; registering them restores both.
    monkeypatch.setattr(gate, "STAGE", gate.STAGE)
    monkeypatch.setattr(harness, "_BOOTSTRAP_CODE", harness._BOOTSTRAP_CODE)

    def fake_prepare(*_args: object, **_kwargs: object) -> str:
        harness._BOOTSTRAP_CODE = 0
        tools = work / "composition" / "localappdata" / "hermes" / "tools"
        return str(tools / "python" / "python.exe")

    monkeypatch.setattr(harness, "prepare_store_python", fake_prepare)
    monkeypatch.setattr(gate, "_launch", lambda *_args, **_kwargs: 4)
    code = gate.drive(
        [
            "probe4",
            str(tree),
            "--wheel",
            str(wheel),
            "--hermes-python",
            sys.executable,
            "--hermes-root",
            str(live),
            "--workdir",
            str(work),
            "--hf-cache",
            str(tmp_path / "hf"),
        ]
    )
    assert code == 4
    assert not (work / "composition-probe4.json").exists()


def test_base_env_keeps_pathext(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A child without PATHEXT cannot resolve git.exe, which failed the first gating run."""
    monkeypatch.setenv("PATHEXT", ".COM;.EXE")
    env = harness.base_env(
        tmp_path / "tree",
        tmp_path / "live",
        tmp_path / "run" / "localappdata" / "hermes",
        tmp_path / "run",
        tmp_path / "work",
        "label",
    )
    assert env["PATHEXT"] == ".COM;.EXE"


def test_harness_refactor_and_gate_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tree = Path(__file__).resolve().parents[1]
    side = tmp_path / "side.jsonl"
    plain = tmp_path / "plain"
    harness.install_plugin(tree, plain, side)
    assert not (plain / "plugins" / "petasos" / "pyproject.toml").exists()
    flagged = tmp_path / "flagged"
    harness.install_plugin(tree, flagged, side, manifest=True)
    assert (flagged / "plugins" / "petasos" / "pyproject.toml").is_file()
    snippet = (flagged / "plugins" / "petasos" / "dashboard" / "plugin_api.py").read_text(
        encoding="utf-8"
    )
    assert "'version': _p.__version__" in snippet
    live = tmp_path / "live"
    root = tmp_path / "run" / "localappdata" / "hermes"
    run = tmp_path / "run"
    work = tmp_path / "work"
    on_path = harness.base_env(tree, live, root, run, work, "label", tree_on_path=True)
    off_path = harness.base_env(tree, live, root, run, work, "label", tree_on_path=False)
    assert on_path["PYTHONPATH"] == os.pathsep.join([str(tree), str(live / "hermes-agent")])
    assert off_path["PYTHONPATH"] == str(live / "hermes-agent")
    env = gate.child_env(
        tree,
        live,
        root,
        run,
        work,
        "label",
        hf_cache=tmp_path / "hf",
        matrix=tmp_path / "matrix.json",
        wheel=tmp_path / "wheel.whl",
        hooks_checks=tmp_path / "hooks.jsonl",
    )
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert env["HERMES_RUNTIME_DIR"] == str(root / "tools")
    assert "HERMES_RUNTIME_DIR" not in off_path
    assert str(tree) not in env["PYTHONPATH"].split(os.pathsep)
    home = tmp_path / "isolated"
    other = tmp_path / "other-live"
    home.mkdir()
    other.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("PET_HARNESS_LIVE_ROOT", str(other))
    seen: list[tuple[str, bool]] = []

    def record(name: str, ok: bool, detail: object) -> None:
        del detail
        seen.append((name, ok))

    before = list(harness.RESULTS)
    with pytest.raises(SystemExit) as caught:
        harness.stop_if_live_deps(record=record)
    assert caught.value.code == 4
    assert seen == [
        ("provenance.root_not_live", True),
        ("provenance.deps_from_fake_root", False),
    ]
    assert before == harness.RESULTS


def _checks_into(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "checks.jsonl"
    monkeypatch.setenv("PET_GATE_CHECK_FILE", str(path))
    monkeypatch.setattr(gate, "_FAILED", [])
    return path


class _Finding:
    def __init__(self, rule_id: str, confidence: float) -> None:
        self.rule_id = rule_id
        self.confidence = confidence


class _Result:
    def __init__(self, findings: list[_Finding]) -> None:
        self.findings = findings
        self.error = None


class _Scanner:
    def __init__(self, name: str, findings: list[_Finding]) -> None:
        self.name = name
        self._findings = findings

    async def scan(self, text: str) -> _Result:
        return _Result(self._findings)


class _Pipeline:
    def __init__(self, scanners: list[_Scanner]) -> None:
        self._minimal_scanner = None
        self._ml_scanners = scanners


class _Plugin:
    def __init__(self, scanners: list[_Scanner]) -> None:
        self._pipeline = _Pipeline(scanners)


def test_margin_is_checked_on_every_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each profile's own scanners are checked against every calibrated margin."""
    # Regression for PET-261: one profile's passing scan must not stand in for another's.
    path = _checks_into(tmp_path, monkeypatch)
    rule = gate.ML_RULES["presidio"]
    corpus = {
        "cases": [
            {
                "id": "C06",
                "payload": "Email ada.lovelace@example.com now",
                "calibration": {"backend": "presidio", "min_confidence": 0.85},
            },
            {"id": "C01", "payload": "git status", "calibration": None},
        ]
    }
    homes = [{"name": "default"}, {"name": "ops"}, {"name": "bare"}, {"name": "unloaded"}]
    mods = {
        "default": _Plugin([_Scanner("presidio", [_Finding(rule, 1.0)])]),
        "ops": _Plugin([_Scanner("presidio", [])]),
        "bare": _Plugin([]),
        "unloaded": None,
    }
    gate._margins(homes, mods, corpus)
    seen = {row["check"]: row["ok"] for row in gate.read_checks(path)}
    assert seen == {
        "corpus.margin.C06.default": True,
        "corpus.margin.C06.ops": False,
        "corpus.margin.C06.bare": False,
        "corpus.margin.C06.unloaded": False,
    }


def test_approval_rows_are_exactly_request_then_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gate, "_row_verified", lambda row: bool(row.get("signed", True)))
    rule = "plugin_rule:petasos.syntactic.command.fetch-exec"
    request = {"event_type": "approval", "phase": "request", "rule_id": rule}
    response = {"event_type": "approval", "phase": "response", "rule_id": rule, "choice": "once"}
    assert gate.approval_rows_ok([request, response])[0] is True
    extra = {"event_type": "quarantine", "rule_id": rule}
    assert gate.approval_rows_ok([request, response, extra])[0] is False
    assert gate.approval_rows_ok([request, extra, response])[0] is False
    assert gate.approval_rows_ok([response, request])[0] is False
    assert gate.approval_rows_ok([request])[0] is False
    assert gate.approval_rows_ok([])[0] is False
    assert gate.approval_rows_ok([request, {**response, "choice": "deny"}])[0] is False
    assert gate.approval_rows_ok([request, {**response, "rule_id": "other"}])[0] is False
    assert gate.approval_rows_ok([request, {**response, "signed": False}])[0] is False


def test_output_paths_must_stay_outside_the_live_root(tmp_path: Path) -> None:
    live = tmp_path / "live" / "hermes"
    live.mkdir(parents=True)
    work = tmp_path / "work"
    work.mkdir()
    root = work / "composition" / "localappdata" / "hermes"
    gate.require_outside_live(work, root, live)

    def refused(*paths: Path) -> bool:
        def call() -> int:
            gate.require_outside_live(*paths)
            return 0

        return gate.guarded(call) == 2

    inside = live / "scratch"
    assert refused(inside, inside / "composition" / "localappdata" / "hermes", live)
    assert refused(live, live / "composition" / "localappdata" / "hermes", live)
    assert refused(tmp_path, tmp_path / "composition" / "localappdata" / "hermes", live)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    assert refused(work, outside / "hermes", live)
    root.parent.mkdir(parents=True)
    _link_dir(live, root)
    assert refused(work, root, live)


def _link_dir(target: Path, link: Path) -> None:
    """A directory link the test account can always make: a junction on Windows."""
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


def test_tool_store_stays_inside_the_isolated_root(tmp_path: Path) -> None:
    live = tmp_path / "live" / "hermes"
    (live / "tools" / "python").mkdir(parents=True)
    work = tmp_path / "work"
    root = work / "composition" / "localappdata" / "hermes"
    own = root / "tools" / "python-3.14" / "python.exe"
    own.parent.mkdir(parents=True)
    own.write_bytes(b"")
    assert gate.store_is_isolated(str(own), root)
    assert gate.store_is_isolated("\\\\?\\" + str(own), root)
    assert not gate.store_is_isolated("", root)
    assert not gate.store_is_isolated(str(live / "tools" / "python" / "python.exe"), root)
    assert not gate.store_is_isolated(str(root / "installs" / "python.exe"), root)
    gate.require_outside_live(work, root, live)
    # A kept tools/ that links to the live store is refused before Hermes can install into it.
    shutil.rmtree(root / "tools")
    _link_dir(live / "tools", root / "tools")
    with pytest.raises(gate.PreflightError, match="isolated tool store"):
        gate.require_outside_live(work, root, live)


def test_stop_hosts_calls_shutdown_and_reports_failures() -> None:
    """Every host is shut down, a missing one is skipped, and a failure is reported by name."""
    calls: list[str] = []

    class Host:
        def __init__(self, name: str, fail: bool = False) -> None:
            self.name = name
            self.fail = fail

        def shutdown(self) -> None:
            """Record the call and fail when asked to."""
            calls.append(self.name)
            if self.fail:
                raise RuntimeError("stuck")

    failed = gate.stop_hosts(
        {"a": Host("a"), "b": Host("b", fail=True), "c": None, "d": Host("d")}
    )
    assert calls == ["a", "b", "d"]
    assert failed == ["b: RuntimeError: stuck"]


def test_kill_tree_child_output_is_decoded_as_utf8(tmp_path: Path) -> None:
    # The child writes raw UTF-8 bytes: "caf", e-acute, space, check mark, newline.
    raw = [99, 97, 102, 195, 169, 32, 226, 156, 147, 10]
    code = f"import sys; sys.stdout.buffer.write(bytes({raw}))"
    done = harness._run_bounded(
        [sys.executable, "-c", code],
        env=dict(os.environ),
        cwd=tmp_path,
        timeout=60,
        capture=True,
        kill_tree=True,
    )
    assert done.returncode == 0
    assert done.stdout == "caf\u00e9 \u2713\n"


_SLEEPER = "import time; time.sleep(60)"
_SPAWN = (
    "import subprocess, sys; "
    f"p = subprocess.Popen([sys.executable, '-c', {_SLEEPER!r}], "
    "stdout=sys.stdout, stderr=sys.stderr); print(p.pid, flush=True); "
)


def test_kill_tree_returns_when_a_grandchild_keeps_the_pipes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A grandchild that holds the pipes cannot keep the call past its bound."""
    # The child exits at once and leaves a grandchild holding both pipes for a minute.
    monkeypatch.setattr(harness, "_PUMP_JOIN_SECONDS", 0.5)
    started = time.monotonic()
    done = harness._run_bounded(
        [sys.executable, "-c", _SPAWN],
        env=dict(os.environ),
        cwd=tmp_path,
        timeout=60,
        capture=True,
        kill_tree=True,
    )
    elapsed = time.monotonic() - started
    grandchild = int(done.stdout.split()[0])
    if sys.platform == "win32":
        harness._kill_process_tree(grandchild)
    else:
        os.kill(grandchild, signal.SIGKILL)
    assert done.returncode == 0
    assert elapsed < 30


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_kill_tree_ends_the_whole_group_on_posix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # With the grandchild dead the pipes close and the pumps finish at once. A surviving
    # grandchild would hold both joins for the full bound.
    monkeypatch.setattr(harness, "_PUMP_JOIN_SECONDS", 30.0)
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        harness._run_bounded(
            [sys.executable, "-c", _SPAWN + "import time; time.sleep(60)"],
            env=dict(os.environ),
            cwd=tmp_path,
            timeout=3,
            capture=True,
            kill_tree=True,
        )
    assert time.monotonic() - started < 20


def test_session_env_names_the_isolated_tool_store(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The printed session environment names the isolated tool store and no secret value."""
    root = tmp_path / "localappdata" / "hermes"
    gate._print_session_env(root, tmp_path, tmp_path / "live", tmp_path / "hf")
    lines = capsys.readouterr().out.splitlines()
    assert f"HERMES_RUNTIME_DIR={root / 'tools'}" in lines
    assert f"HERMES_HOME={root}" in lines
    assert not any("k" * 64 in line for line in lines)


def test_stale_evidence_is_removed_before_a_later_preflight_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gate, "STAGE", gate.STAGE)
    live = tmp_path / "live"
    (live / "hermes-agent").mkdir(parents=True)
    work = tmp_path / "work"
    work.mkdir()
    stale = work / "composition-again.json"
    stale.write_text("stale", encoding="utf-8")
    argv = [
        "again",
        str(tmp_path / "tree"),
        "--wheel",
        str(tmp_path / "missing.whl"),
        "--hermes-python",
        sys.executable,
        "--hermes-root",
        str(live),
        "--workdir",
        str(work),
    ]
    assert gate.guarded(lambda: gate.drive(argv)) == 2
    assert not stale.exists()


def test_driver_schema_must_match_the_release_tree(tmp_path: Path) -> None:
    """Preflight stops when the driver's config schema is not the release tree's."""
    checkout = tmp_path / "driver"
    tree = tmp_path / "release"
    for base in (checkout, tree):
        (base / "petasos").mkdir(parents=True)
    (checkout / "petasos" / "config.py").write_bytes(b"a: int = 1\nb: int = 2\n")
    (tree / "petasos" / "config.py").write_bytes(b"a: int = 1\r\nb: int = 2\r\n")
    gate.require_same_schema(tree, checkout)
    # A field only the release tree has would be withheld from the copied section.
    (tree / "petasos" / "config.py").write_bytes(b"a: int = 1\nb: int = 2\nc: int = 3\n")
    with pytest.raises(gate.PreflightError, match="differs between the driver checkout"):
        gate.require_same_schema(tree, checkout)
    (checkout / "petasos" / "config.py").unlink()
    with pytest.raises(gate.PreflightError, match="cannot read"):
        gate.require_same_schema(tree, checkout)
