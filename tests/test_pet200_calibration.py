"""PET-200: HIGH+ calibration freeze, detection, and retain pins.

Regression for PET-200: unmeasured widening of the inverted ingestion surface.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from petasos import PetasosConfig, Pipeline
from petasos._types import Severity
from petasos.session.ingest import HEAD_CHARS

_REPO = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO / "scripts" / "pet200_calibrate.py"
_TEMPLATES = _REPO / "tests" / "fixtures" / "pet200" / "templates"


def _load_harness() -> Any:
    spec = importlib.util.spec_from_file_location("pet200_calibrate", str(_SCRIPT))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pet200_calibrate"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def harness() -> Any:
    return _load_harness()


@pytest.fixture(scope="module")
def plugin(harness: Any) -> Any:
    loop = asyncio.new_event_loop()
    pipeline = Pipeline(config=PetasosConfig())
    ref = harness.load_plugin(pipeline, loop)
    ref._pet200_loop = loop
    yield ref
    loop.close()


def _transform(plugin: Any, tool_name: str, payload: str, task_id: str) -> object:
    return plugin._transform_tool_result(tool_name=tool_name, result=payload, task_id=task_id)


def test_freeze_pin_manifest_and_templates(harness: Any, plugin: Any) -> None:
    manifest = harness.load_manifest()
    assert manifest["generator_version"] == "pet200-v1"
    assert manifest["planted_phrase"] == harness.PLANTED_PHRASE
    assert manifest["seed"] == 200

    for name, digest in manifest["templates"].items():
        path = _TEMPLATES / name
        assert path.is_file(), name
        assert harness.file_sha256(path) == digest
        assert "\\" not in name

    for entry in manifest["in_repo_paths"]:
        rel = entry["path"]
        assert "\\" not in rel
        path = _REPO / rel
        assert path.is_file(), rel
        assert harness.file_sha256(path) == entry["sha256"]
        text = harness.read_utf8(path)
        assert harness.label_path(rel, text) == "benign"

    sample = harness.Sample(
        family="F-browser",
        stratum="S0",
        label="benign",
        index=0,
        tool_name="browser_navigate",
        offset="none",
    )
    a = harness.generate_payload(sample, manifest, generated=True)
    b = harness.generate_payload(sample, manifest, generated=True)
    assert a == b
    assert 1 <= len(a) <= HEAD_CHARS

    for name, tool in (
        ("browser.html", "browser_navigate"),
        ("mcp.json", "mcp__some_server__some_tool"),
        ("stdout.txt", "terminal"),
    ):
        payload = harness.read_utf8(_TEMPLATES / name)
        assert harness.PLANTED_PHRASE not in payload
        out = _transform(plugin, tool, payload, f"pet200-template-{name}")
        assert out is None, name


def test_planted_s0_s1_head_offset_flags_each_family(harness: Any, plugin: Any) -> None:
    # Regression for PET-200: planted phrase at head must still banner HIGH+.
    manifest = harness.load_manifest()
    for family in harness.FAMILIES:
        sample = harness.Sample(
            family=family,
            stratum="S0",
            label="planted-positive",
            index=0,
            tool_name=harness._tool_for(family, 0),
            offset="head",
        )
        payload = harness.generate_payload(sample, manifest, generated=True)
        assert harness.PLANTED_PHRASE in payload
        out = _transform(plugin, sample.tool_name, payload, f"pet200-plant-head-{family}")
        assert harness.classify_handler_return(out) == "ingest_flagged"
        assert isinstance(out, str)
        assert "Top finding:" in out
        _rule, severity = harness.parse_top_finding(out)
        assert severity in {"HIGH", "CRITICAL"}


def test_planted_beyond_head_flags_each_family(harness: Any, plugin: Any) -> None:
    # Regression for PET-200: syntactic sweep still finds a phrase past the inspect head.
    manifest = harness.load_manifest()
    for family in harness.FAMILIES:
        sample = harness.Sample(
            family=family,
            stratum="S1",
            label="planted-positive",
            index=0,
            tool_name=harness._tool_for(family, 0),
            offset="beyond_head",
        )
        payload = harness.generate_payload(sample, manifest, generated=True)
        assert payload.find(harness.PLANTED_PHRASE) >= HEAD_CHARS
        out = _transform(plugin, sample.tool_name, payload, f"pet200-plant-beyond-{family}")
        assert harness.classify_handler_return(out) == "ingest_flagged"


def test_unavailable_is_not_clean(
    harness: Any, plugin: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = plugin.scan_ingestion_result

    async def _errors(*args: Any, **kwargs: Any) -> Any:
        result = await original(*args, **kwargs)
        return replace(result, errors=("boom",))

    monkeypatch.setattr(plugin, "scan_ingestion_result", _errors)
    out = _transform(plugin, "read_file", "the content" * 10, "pet200-unavail")
    outcome = harness.classify_handler_return(out)
    assert outcome == "unavailable"
    assert outcome != "ingest_flagged"
    assert outcome != "clean"
    acc = harness.CellAccum()
    acc.add(outcome, 1.0, None, None)
    assert acc.unavailable_n == 1
    assert acc.flagged_high_plus == 0
    assert acc.n - acc.unavailable_n == 0


def test_config_labels_base_and_missing_extras(harness: Any) -> None:
    git_sha = "deadbeef"
    manifest_sha = "abc"
    ml = harness.build_ml_report(phase="baseline", git_sha=git_sha, manifest_sha=manifest_sha)
    assert ml["config_label"] == "ml:"
    assert "llm-guard" not in ml["config_label"]
    names = {row["name"] for row in ml["extras_status"]}
    assert names == {"llm-guard", "llamafirewall", "presidio"}
    for row in ml["extras_status"]:
        assert row["status"] == f"not measured — extras-{row['name']} unavailable"
    assert ml["cells"] == []

    report = harness.run_table_a(
        phase="baseline",
        git_sha=harness.git_head(),
        manifest=harness.load_manifest(),
        limit=0,
    )
    assert report["config_label"] == "base"
    assert report["config_label"] != "ml"
    assert ml["policy_recommendation"]["kind"] == "insufficient_evidence"
    assert ml["policy_recommendation"]["reason"] == "not_measured"
    assert report["measurement"] == "partial"
    assert report["policy_recommendation"]["kind"] == "insufficient_evidence"
    assert report["policy_recommendation"]["reason"] == "partial"


def test_benign_s0_smoke_no_planted_phrase(harness: Any, plugin: Any) -> None:
    manifest = harness.load_manifest()
    for family in harness.FAMILIES:
        for i in range(8):
            sample = harness.Sample(
                family=family,
                stratum="S0",
                label="benign",
                index=i,
                tool_name=harness._tool_for(family, i),
                offset="none",
            )
            payload = harness.generate_payload(sample, manifest, generated=True)
            assert sample.label == "benign"
            assert harness.PLANTED_PHRASE not in payload
            assert 1 <= len(payload) <= HEAD_CHARS


def test_f_mcp_wire_name_is_scanned(harness: Any, plugin: Any) -> None:
    from petasos.session.guard import NON_INGESTING_TOOLS

    tool = "mcp__some_server__some_tool"
    assert tool not in NON_INGESTING_TOOLS
    manifest = harness.load_manifest()
    sample = harness.Sample(
        family="F-mcp",
        stratum="S0",
        label="planted-positive",
        index=1,
        tool_name=tool,
        offset="head",
    )
    payload = harness.generate_payload(sample, manifest, generated=True)
    out = _transform(plugin, tool, payload, "pet200-mcp-name")
    assert harness.classify_handler_return(out) == "ingest_flagged"


def test_f_file_tests_path_never_benign(harness: Any) -> None:
    planted = harness.PLANTED_PHRASE
    assert harness.label_path("tests/fixtures/poison.txt", planted) != "benign"
    assert harness.label_path("tests/test_minimal_scanner.py", planted) == "constructed-positive"
    assert harness.label_path("LICENSE", "MIT License") == "benign"


def test_no_gate_edit_block_rank(plugin: Any) -> None:
    # Regression for PET-200: retain HIGH+; this PR must not retune _BLOCK_RANK.
    high_rank = plugin._SEVERITY_RANK[Severity.HIGH]
    assert high_rank == plugin._BLOCK_RANK


def test_banner_token_classification(harness: Any, plugin: Any) -> None:
    c = harness.classify_handler_return
    assert c(None) == "clean"
    assert c("Petasos could not scan the content below (scanner unavailable).") == "unavailable"
    flagged = (
        "[Petasos] Output from tool 'read_file'. scanned.\n"
        "Top finding: injection.ignore-previous (HIGH)"
    )
    assert c(flagged) == "ingest_flagged"
    ceiling = (
        "[Petasos] Output from tool 'read_file'. "
        "Petasos scanned the first 1,000,000 characters of the content below. "
        "The remainder was not scanned.\n"
        "Coverage: ceiling."
    )
    assert c(ceiling) == "ceiling_clean"
    assert "Top finding:" not in ceiling

    manifest = harness.load_manifest()
    sample = harness.Sample(
        family="F-stdout",
        stratum="S-ceiling",
        label="benign",
        index=0,
        tool_name="terminal",
        offset="none",
    )
    payload = harness.generate_payload(sample, manifest, generated=True)
    assert len(payload) == 1_000_001
    out = _transform(plugin, "terminal", payload, "pet200-ceiling")
    outcome = c(out)
    assert outcome in {"ceiling_clean", "unavailable"}
    acc = harness.CellAccum()
    acc.add(outcome, 1.0, None, None)
    assert acc.flagged_high_plus == 0


def test_f_file_listed_paths_are_passthrough_or_not_benign(harness: Any, plugin: Any) -> None:
    manifest = harness.load_manifest()
    for entry in manifest["in_repo_paths"]:
        rel = entry["path"]
        payload = harness.read_utf8(_REPO / rel)
        out = _transform(plugin, "read_file", payload, f"pet200-file-{rel}")
        if out is None:
            assert harness.label_path(rel, payload) == "benign"
        else:
            assert harness.label_path(rel, payload) != "benign"


def test_generated_s0_inert_and_no_console_js_as_html(harness: Any, plugin: Any) -> None:
    manifest = harness.load_manifest()
    for family in harness.FAMILIES:
        sample = harness.Sample(
            family=family,
            stratum="S0",
            label="benign",
            index=3,
            tool_name=harness._tool_for(family, 3),
            offset="none",
        )
        payload = harness.generate_payload(sample, manifest, generated=True)
        template_name = harness.FAMILY_TEMPLATE[family]
        if template_name is not None:
            committed = harness.read_utf8(_TEMPLATES / template_name)
            assert payload != committed
        out = _transform(plugin, sample.tool_name, payload, f"pet200-gen-s0-{family}")
        assert out is None, family

    for entry in manifest["in_repo_paths"]:
        rel = entry["path"]
        assert not rel.startswith("petasos/console/static/") or not rel.endswith(".js")
    assert not any(
        rel.endswith(".js") and "console/static" in rel
        for rel in (e["path"] for e in manifest["in_repo_paths"])
    )


def test_wilson_null_when_n_eff_zero(harness: Any) -> None:
    assert harness.wilson95(0, 0) is None
    interval = harness.wilson95(0, 200)
    assert interval is not None
    assert interval["low"] == 0.0
    assert interval["low"] <= interval["centre"] <= interval["high"] <= 1.0
    assert 0.018 < interval["high"] < 0.019
    stratum = harness.wilson95(0, 100)
    assert stratum is not None
    assert stratum["low"] == 0.0
    assert 0.036 < stratum["high"] < 0.038
    # S2 n=30 undershoots 0; a saturated n=5 overshoots 1. Both must clamp.
    undershoot = harness.wilson95(0, 30)
    assert undershoot is not None
    assert undershoot["low"] == 0.0
    assert 0.0 < undershoot["centre"] <= undershoot["high"] <= 1.0
    saturated = harness.wilson95(5, 5)
    assert saturated is not None
    assert saturated["high"] == 1.0
    assert 0.0 <= saturated["low"] <= saturated["centre"] <= 1.0


def test_ingest_flagged_counts_medium_plus(harness: Any) -> None:
    acc = harness.CellAccum()
    acc.add("ingest_flagged", 1.0, "injection.ignore-previous", "HIGH")
    assert acc.flagged_high_plus == 1
    assert acc.flagged_medium_plus == 1
    assert acc.flagged_critical_only == 0
    acc.add("ingest_flagged", 1.0, "injection.ignore-previous", "CRITICAL")
    assert acc.flagged_high_plus == 2
    assert acc.flagged_medium_plus == 2
    assert acc.flagged_critical_only == 1
    acc.add("clean", 1.0, None, None)
    assert acc.flagged_high_plus == 2
    assert acc.flagged_medium_plus == 2
    acc.add("ingest_flagged", 1.0, "injection.ignore-previous", "MEDIUM")
    assert acc.flagged_high_plus == 3
    assert acc.flagged_medium_plus == 3
    assert acc.flagged_critical_only == 1


def test_planted_payloads_stay_in_stratum(harness: Any) -> None:
    manifest = harness.load_manifest()
    planted = 0
    for sample in harness.iter_samples():
        if sample.label != "planted-positive":
            continue
        planted += 1
        payload = harness.generate_payload(sample, manifest, generated=True)
        lo, hi = harness.STRATUM_BOUNDS[sample.stratum]
        assert lo <= len(payload) <= hi, (sample, len(payload), lo, hi)
        assert harness.PLANTED_PHRASE in payload
        if sample.offset == "beyond_head":
            assert payload.find(harness.PLANTED_PHRASE) >= harness.BEYOND_HEAD_OFFSET
    assert planted == 40


def _benign_core_cell(
    family: str, stratum: str, *, n_eff: int, flagged: int = 0
) -> dict[str, Any]:
    return {
        "family": family,
        "stratum": stratum,
        "label": "benign",
        "n": n_eff,
        "n_eff": n_eff,
        "flagged_high_plus": flagged,
        "rule_histogram": {},
    }


def _complete_core(harness: Any, *, n_eff: int = 100, flagged: int = 0) -> list[dict[str, Any]]:
    cells: list[dict[str, Any]] = []
    for family in harness.FAMILIES:
        cells.append(_benign_core_cell(family, "S0", n_eff=n_eff, flagged=flagged))
        cells.append(_benign_core_cell(family, "S1", n_eff=n_eff, flagged=flagged))
    return cells


def test_empty_cells_do_not_retain(harness: Any) -> None:
    rec = harness.policy_from_cells([])
    assert rec["kind"] == "insufficient_evidence"
    assert rec["reason"] == "empty"


def test_partial_run_does_not_retain(harness: Any) -> None:
    rec = harness.policy_from_cells(_complete_core(harness), complete=False)
    assert rec["kind"] == "insufficient_evidence"
    assert rec["reason"] == "partial"


def test_all_unavailable_core_does_not_retain(harness: Any) -> None:
    rec = harness.policy_from_cells(_complete_core(harness, n_eff=0))
    assert rec["kind"] == "insufficient_evidence"
    assert rec["reason"] == "unavailable"
    assert rec["families"] == list(harness.FAMILIES)


def test_one_unavailable_family_does_not_retain(harness: Any) -> None:
    cells: list[dict[str, Any]] = []
    for family in harness.FAMILIES:
        n_eff = 0 if family == "F-browser" else 100
        cells.append(_benign_core_cell(family, "S0", n_eff=n_eff))
        cells.append(_benign_core_cell(family, "S1", n_eff=n_eff))
    rec = harness.policy_from_cells(cells)
    assert rec["kind"] == "insufficient_evidence"
    assert rec["reason"] == "unavailable"
    assert rec["families"] == ["F-browser"]


def test_s0_only_core_does_not_retain(harness: Any) -> None:
    # Regression (CodeRabbit #187): one S0 cell per family with no S1 evidence
    # used to satisfy the family-presence check and retain HIGH+. Every
    # required family must have exactly both S0 and S1 benign strata.
    cells = [_benign_core_cell(family, "S0", n_eff=100) for family in harness.FAMILIES]
    rec = harness.policy_from_cells(cells)
    assert rec["kind"] == "insufficient_evidence"
    assert rec["reason"] == "partial"
    assert rec["families"] == list(harness.FAMILIES)


def test_one_family_missing_s1_does_not_retain(harness: Any) -> None:
    cells: list[dict[str, Any]] = []
    for family in harness.FAMILIES:
        cells.append(_benign_core_cell(family, "S0", n_eff=100))
        if family != "F-stdout":
            cells.append(_benign_core_cell(family, "S1", n_eff=100))
    rec = harness.policy_from_cells(cells)
    assert rec["kind"] == "insufficient_evidence"
    assert rec["reason"] == "partial"
    assert rec["families"] == ["F-stdout"]


def test_measured_complete_core_retains(harness: Any) -> None:
    rec = harness.policy_from_cells(_complete_core(harness, n_eff=100, flagged=0))
    assert rec == {"kind": "retain_high_plus"}


def test_finalized_helper_only_fields_are_not_measured(harness: Any) -> None:
    acc = harness.CellAccum()
    acc.add("ingest_flagged", 1.0, "injection.ignore-previous", "HIGH")
    cell = harness._finalize_cell("F-file", "S0", "planted-positive", acc)
    assert cell["flagged_high_plus"] == 1
    assert cell["flagged_critical_only"] == 0
    assert cell["flagged_medium_plus"] is None
    assert cell["unavailable_with_findings"] is None
    assert cell["pii_suppressed"] is None
