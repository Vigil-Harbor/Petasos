"""PET-200: HIGH+ calibration freeze, detection, and retain pins.

Regression for PET-200: unmeasured widening of the inverted ingestion surface.
Regression for PET-218: real enforcement events must agree with the handler.
Regression for PET-219: helper findings fill the schema-2 columns.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from petasos import PetasosConfig, Pipeline
from petasos._types import Direction, ScanFinding, ScanResult, Severity
from petasos.console._events import drain_enforcement_events
from petasos.session.ingest import HEAD_CHARS, IngestionCoverage, IngestionScanResult

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
    with harness.isolated_observation(ref):
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
    original = plugin._observation_scan

    async def _errors(*args: Any, **kwargs: Any) -> Any:
        result = await original(*args, **kwargs)
        return replace(result, errors=("boom",))

    monkeypatch.setattr(plugin, "_observation_scan", _errors)
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


def test_plane_split_visible_counts_ignore_helper_marks(harness: Any) -> None:
    # Regression for PET-218: the handler plane does not fill helper columns.
    acc = harness.CellAccum()
    acc.add("ingest_flagged", 1.0, "injection.ignore-previous", "HIGH")
    assert acc.flagged_high_plus == 1
    assert acc.flagged_critical_only == 0
    assert acc.flagged_medium_plus == 0
    assert acc.unavailable_with_findings == 0
    assert acc.pii_suppressed == 0
    acc.add("ingest_flagged", 1.0, "structural.excessive-depth", "CRITICAL")
    assert acc.flagged_high_plus == 2
    assert acc.flagged_critical_only == 1
    assert acc.flagged_medium_plus == 0
    acc.record_helper("clean", _capture(_finding("encoding", Severity.MEDIUM)), _Blocks())
    assert acc.flagged_medium_plus == 1
    assert acc.flagged_high_plus == 2
    assert acc.helper_samples == 1
    bare = harness.CellAccum()
    bare.add("ingest_flagged", 1.0, "injection.ignore-previous", "HIGH")
    cell = harness._finalize_cell("F-file", "S0", "planted-positive", bare)
    assert cell["flagged_high_plus"] == 1
    assert cell["flagged_medium_plus"] is None
    assert cell["unavailable_with_findings"] is None
    assert cell["pii_suppressed"] is None


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


def _finding(finding_type: str, severity: Severity) -> ScanFinding:
    return ScanFinding(
        rule_id=f"petasos.test.{finding_type}",
        finding_type=finding_type,
        severity=severity,
        confidence=1.0,
        message="probe",
        scanner_name="helper-probe",
    )


def _capture(*findings: ScanFinding) -> IngestionScanResult:
    return IngestionScanResult(
        findings=findings,
        coverage=IngestionCoverage(
            regime="full",
            scanned_chars=1,
            total_chars=1,
            head_chars=1,
            chunk_count=1,
        ),
        head=None,
        errors=(),
    )


class _Blocks:
    @staticmethod
    def _blocks(severity: Severity) -> bool:
        return severity in {Severity.HIGH, Severity.CRITICAL}


class _ProbeScanner:
    def __init__(self, finding: ScanFinding) -> None:
        self._finding = finding

    @property
    def name(self) -> str:
        return "helper-probe"

    async def scan(
        self,
        text: str,
        *,
        direction: Direction = "inbound",
        session_id: str | None = None,
    ) -> ScanResult:
        del text, direction, session_id
        return ScanResult(scanner_name=self.name, findings=(self._finding,))


def _loaded(
    harness: Any, pipeline: Pipeline | None = None
) -> tuple[Any, asyncio.AbstractEventLoop]:
    loop = asyncio.new_event_loop()
    pipe = pipeline if pipeline is not None else Pipeline(config=PetasosConfig())
    return harness.load_plugin(pipe, loop), loop


def _close(loop: asyncio.AbstractEventLoop) -> None:
    loop.close()


def test_planted_high_sample_writes_one_correlated_event(harness: Any) -> None:
    # Regression for PET-218: a HIGH+ banner and one real ingest_flagged line agree.
    ref, loop = _loaded(harness)
    try:
        with harness.isolated_observation(ref) as spool:
            bucket = harness.CellAccum()
            observed = harness.observe_sample(
                ref,
                spool,
                bucket,
                index=0,
                tool_name="read_file",
                payload=harness.PLANTED_PHRASE,
                task_id="pet200-planted",
            )
    finally:
        _close(loop)
    assert observed.outcome == "ingest_flagged"
    assert observed.gaps == []
    assert observed.severity == "HIGH"
    assert observed.rule_id == "injection.ignore-previous"
    flagged = [event for event in observed.events if event.get("event_type") == "ingest_flagged"]
    assert len(flagged) == 1
    assert flagged[0]["session_id"] == "pet200-planted"
    assert flagged[0]["rule_id"] == "petasos.syntactic.injection.ignore-previous"
    assert flagged[0]["severity"] == "HIGH"
    assert bucket.rule_histogram == {"injection.ignore-previous": 1}
    assert bucket.flagged_high_plus == 1


def test_benign_clean_sample_has_no_event_and_zero_helpers(harness: Any) -> None:
    # Regression for PET-218: a clean handler return is observed emptiness.
    ref, loop = _loaded(harness)
    try:
        with harness.isolated_observation(ref) as spool:
            bucket = harness.CellAccum()
            observed = harness.observe_sample(
                ref,
                spool,
                bucket,
                index=0,
                tool_name="read_file",
                payload="the content" * 10,
                task_id="pet200-clean",
            )
    finally:
        _close(loop)
    assert observed.outcome == "clean"
    assert observed.gaps == []
    assert observed.events == []
    cell = harness._finalize_cell("F-file", "S0", "benign", bucket)
    assert cell["flagged_medium_plus"] == 0
    assert cell["unavailable_with_findings"] == 0
    assert cell["pii_suppressed"] == 0
    assert cell["flagged_high_plus"] == 0


def _patch_unavailable(monkeypatch: pytest.MonkeyPatch, ref: Any, *, clock: float = 30.0) -> None:
    monkeypatch.setattr(ref.time, "monotonic", lambda: clock)
    original = ref._observation_scan

    async def _errors(*args: Any, **kwargs: Any) -> Any:
        result = await original(*args, **kwargs)
        return replace(result, errors=("boom",))

    monkeypatch.setattr(ref, "_observation_scan", _errors)


def test_forced_unavailable_writes_one_unscanned_event(
    harness: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression for PET-218: unavailable agrees with one correlated ingest_unscanned.
    ref, loop = _loaded(harness)
    _patch_unavailable(monkeypatch, ref)
    try:
        with harness.isolated_observation(ref) as spool:
            bucket = harness.CellAccum()
            observed = harness.observe_sample(
                ref,
                spool,
                bucket,
                index=0,
                tool_name="read_file",
                payload="the content" * 10,
                task_id="pet200-unavail",
            )
    finally:
        _close(loop)
    assert observed.outcome == "unavailable"
    assert observed.gaps == []
    assert bucket.flagged_high_plus == 0
    unscanned = [
        event for event in observed.events if event.get("event_type") == "ingest_unscanned"
    ]
    assert len(unscanned) == 1
    assert unscanned[0]["session_id"] == "pet200-unavail"
    assert not any(event.get("event_type") == "ingest_flagged" for event in observed.events)


def test_unavailable_with_findings_stays_unflagged(
    harness: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression for PET-219: findings on an unavailable scan do not become HIGH+.
    ref, loop = _loaded(harness)
    _patch_unavailable(monkeypatch, ref)
    try:
        with harness.isolated_observation(ref) as spool:
            bucket = harness.CellAccum()
            observed = harness.observe_sample(
                ref,
                spool,
                bucket,
                index=0,
                tool_name="read_file",
                payload=harness.PLANTED_PHRASE,
                task_id="pet200-unavail-findings",
            )
    finally:
        _close(loop)
    assert observed.outcome == "unavailable"
    assert observed.gaps == []
    assert bucket.unavailable_with_findings == 1
    assert bucket.flagged_high_plus == 0
    assert not any(event.get("event_type") == "ingest_flagged" for event in observed.events)


def test_helper_only_medium_increments_medium_not_high(harness: Any) -> None:
    # Regression for PET-219: a non-blocking MEDIUM finding is helper-only.
    pipeline = Pipeline(
        scanners=(_ProbeScanner(_finding("encoding", Severity.MEDIUM)),),
        config=PetasosConfig(),
    )
    ref, loop = _loaded(harness, pipeline)
    try:
        with harness.isolated_observation(ref) as spool:
            bucket = harness.CellAccum()
            observed = harness.observe_sample(
                ref,
                spool,
                bucket,
                index=0,
                tool_name="read_file",
                payload="garden notes for the north stall",
                task_id="pet200-medium",
            )
    finally:
        _close(loop)
    assert observed.outcome == "clean"
    assert observed.gaps == []
    assert bucket.flagged_medium_plus == 1
    assert bucket.flagged_high_plus == 0
    assert not any(event.get("event_type") == "ingest_flagged" for event in observed.events)


def test_pii_only_is_suppressed_without_a_banner(harness: Any) -> None:
    # Regression for PET-219: blocking PII is withheld from the banner and the spool.
    pipeline = Pipeline(
        scanners=(_ProbeScanner(_finding("pii", Severity.HIGH)),),
        config=PetasosConfig(),
    )
    ref, loop = _loaded(harness, pipeline)
    try:
        with harness.isolated_observation(ref) as spool:
            bucket = harness.CellAccum()
            observed = harness.observe_sample(
                ref,
                spool,
                bucket,
                index=0,
                tool_name="read_file",
                payload="garden notes for the north stall",
                task_id="pet200-pii",
            )
    finally:
        _close(loop)
    assert observed.outcome == "clean"
    assert observed.gaps == []
    assert bucket.pii_suppressed == 1
    assert bucket.flagged_high_plus == 0
    assert bucket.flagged_medium_plus == 0
    assert not any(event.get("event_type") == "ingest_flagged" for event in observed.events)


def test_cross_sample_clean_ignores_earlier_flagged_event(harness: Any) -> None:
    # Regression for PET-218: a later clean sample does not inherit an earlier event.
    ref, loop = _loaded(harness)
    try:
        with harness.isolated_observation(ref) as spool:
            flagged = harness.CellAccum()
            clean = harness.CellAccum()
            first = harness.observe_sample(
                ref,
                spool,
                flagged,
                index=0,
                tool_name="read_file",
                payload=harness.PLANTED_PHRASE,
                task_id="pet200-0",
            )
            second = harness.observe_sample(
                ref,
                spool,
                clean,
                index=1,
                tool_name="read_file",
                payload="the content" * 10,
                task_id="pet200-1",
            )
    finally:
        _close(loop)
    assert first.outcome == "ingest_flagged"
    assert first.gaps == []
    assert second.outcome == "clean"
    assert second.gaps == []
    assert second.events == []
    cell = harness._finalize_cell("F-file", "S0", "benign", clean)
    assert cell["flagged_high_plus"] == 0
    assert cell["flagged_medium_plus"] == 0
    assert cell["pii_suppressed"] == 0
    assert flagged.flagged_high_plus == 1


def test_parser_collapses_spool_noise(harness: Any, tmp_path: Path) -> None:
    # Regression for PET-218: agreement uses collapsed attributable lines only.
    task = "pet200-9"
    line = {
        "session_id": task,
        "event_type": "ingest_flagged",
        "rule_id": "petasos.syntactic.injection.ignore-previous",
        "severity": "HIGH",
    }
    foreign = {
        "session_id": "other-session",
        "event_type": "ingest_flagged",
        "rule_id": "petasos.syntactic.injection.other",
        "severity": "HIGH",
    }
    path = tmp_path / "spool.jsonl"
    path.write_bytes(
        b"{not json}\n"
        + json.dumps(foreign).encode()
        + b"\n"
        + json.dumps(line).encode()
        + b"\n"
        + json.dumps(line).encode()
        + b"\n"
    )
    events, _offset = drain_enforcement_events(str(path), 0)
    assert (
        harness.attribute_new_events(
            events,
            task_id=task,
            outcome="ingest_flagged",
            rule_id="injection.ignore-previous",
            severity="HIGH",
            earlier_unscanned=False,
        )
        == "agreed"
    )
    other = dict(line)
    other["rule_id"] = "petasos.syntactic.injection.other"
    assert (
        harness.attribute_new_events(
            [line, other],
            task_id=task,
            outcome="ingest_flagged",
            rule_id="injection.ignore-previous",
            severity="HIGH",
            earlier_unscanned=False,
        )
        == "agreement"
    )


def test_cadence_second_unavailable_reuses_the_earlier_line(
    harness: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression for PET-218: a suppressed repeat agrees and does not recount the first row.
    ref, loop = _loaded(harness)
    _patch_unavailable(monkeypatch, ref)
    try:
        with harness.isolated_observation(ref) as spool:
            first_bucket = harness.CellAccum()
            second_bucket = harness.CellAccum()
            payload = "the content" * 10
            first = harness.observe_sample(
                ref,
                spool,
                first_bucket,
                index=0,
                tool_name="read_file",
                payload=payload,
                task_id="pet200-cadence",
            )
            snapshot = (
                first_bucket.n,
                first_bucket.unavailable_n,
                first_bucket.flagged_high_plus,
                first_bucket.helper_samples,
            )
            second = harness.observe_sample(
                ref,
                spool,
                second_bucket,
                index=1,
                tool_name="read_file",
                payload=payload,
                task_id="pet200-cadence",
            )
            stored, _offset = drain_enforcement_events(spool, 0)
    finally:
        _close(loop)
    assert first.outcome == "unavailable"
    assert second.outcome == "unavailable"
    assert first.gaps == []
    assert second.gaps == []
    assert (
        first_bucket.n,
        first_bucket.unavailable_n,
        first_bucket.flagged_high_plus,
        first_bucket.helper_samples,
    ) == snapshot
    unscanned = [event for event in stored if event.get("event_type") == "ingest_unscanned"]
    assert len(unscanned) == 1
    assert unscanned[0]["session_id"] == "pet200-cadence"


def test_isolated_observation_restores_sentinel_after_an_exception(
    harness: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Regression for PET-218: a failed run leaves the operator spool and cadence untouched.
    import petasos.console._events as events
    import petasos.console._paths as paths

    sentinel = tmp_path / "sentinel.jsonl"
    sentinel.write_bytes(b"MARKER\n")
    paths._SPOOL_PATH_OVERRIDE = str(sentinel)
    saved_key = events._SPOOL_KEY
    ref, loop = _loaded(harness)
    ref._last_ingest_unscanned_log["keep"] = 1.5
    before = dict(ref._last_ingest_unscanned_log)

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("resolve_hermes_config_path")

    monkeypatch.setattr(paths, "resolve_hermes_config_path", _boom)
    parent: Path | None = None
    try:
        with (
            pytest.raises(RuntimeError, match="forced"),
            harness.isolated_observation(ref) as spool,
        ):
            parent = Path(spool).parent
            raw = ref._transform_tool_result(
                tool_name="read_file",
                result=harness.PLANTED_PHRASE,
                task_id="pet200-sentinel",
            )
            assert harness.classify_handler_return(raw) == "ingest_flagged"
            raise RuntimeError("forced")
    finally:
        _close(loop)
    assert parent is not None
    assert not parent.exists()
    assert sentinel.read_bytes() == b"MARKER\n"
    assert str(sentinel) == paths._SPOOL_PATH_OVERRIDE
    assert events._SPOOL_KEY is saved_key
    assert dict(ref._last_ingest_unscanned_log) == before


def test_helper_missing_exits_3_without_replacing_out(
    harness: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Regression for PET-218: an unobserved sample is a gap, not a numeric zero.
    async def _raise(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("no result")

    monkeypatch.setattr("petasos.session.ingest.scan_ingestion_result", _raise)
    ref, loop = _loaded(harness)
    try:
        with harness.isolated_observation(ref) as spool:
            bucket = harness.CellAccum()
            observed = harness.observe_sample(
                ref,
                spool,
                bucket,
                index=0,
                tool_name="read_file",
                payload="the content" * 10,
                task_id="pet200-missing",
            )
    finally:
        _close(loop)
    assert observed.outcome == "unavailable"
    assert any(gap.reason == "helper_missing" for gap in observed.gaps)
    cell = harness._finalize_cell("F-file", "S0", "benign", bucket)
    assert cell["flagged_medium_plus"] is None
    assert cell["unavailable_with_findings"] is None
    assert cell["pii_suppressed"] is None
    seeded = tmp_path / "out.json"
    seeded.write_bytes(b'{"keep": true}\n')
    seed = seeded.read_bytes()
    missing = tmp_path / "missing.json"
    code = harness.main(
        ["--config", "base", "--phase", "baseline", "--out", str(seeded), "--limit", "1"]
    )
    assert code == 3
    assert seeded.read_bytes() == seed
    missing_code = harness.main(
        ["--config", "base", "--phase", "baseline", "--out", str(missing), "--limit", "1"]
    )
    assert missing_code == 3
    assert not missing.exists()


def test_schema_smoke_partial_run_is_observed(harness: Any) -> None:
    # Regression for PET-218: a limited run can still be fully observed.
    report = harness.run_table_a(
        phase="baseline",
        git_sha=harness.git_head(),
        manifest=harness.load_manifest(),
        limit=2,
    )
    assert report["schema_version"] == 2
    assert report["measurement"] == "partial"
    assert report["observation"] == "complete"
    assert report["cells"]
    for cell in report["cells"]:
        assert isinstance(cell["flagged_medium_plus"], int)
        assert isinstance(cell["unavailable_with_findings"], int)
        assert isinstance(cell["pii_suppressed"], int)
    ml = harness.build_ml_report(phase="baseline", git_sha="abc", manifest_sha="def")
    assert ml["schema_version"] == 2
    assert ml["measurement"] == "not_measured"
    assert ml["observation"] == "not_measured"
    assert ml["cells"] == []
