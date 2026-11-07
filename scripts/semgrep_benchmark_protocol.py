"""Pinned S7 fixtures, case plan and fail-closed measurement accounting."""

from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
from pathlib import Path
from typing import Any

from scripts.semgrep_workloads import fragment, workload

WORKLOAD = "eight_outstanding_three_profiles_16k_128k_v2"
MANIFEST_SHA256 = "36b279d00a2551589a2ea1e7415eedecfee3c0a5a520d1436ce5ac9371e0fa40"


def summary(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {"runs": 0}
    ordered = sorted(values)
    return {
        "runs": len(values),
        "mean": statistics.mean(values),
        "p95": ordered[int((len(ordered) - 1) * 0.95)],
        "p99": ordered[int((len(ordered) - 1) * 0.99)],
        "max": max(values),
    }


def fixtures() -> tuple[dict[str, Any], dict[str, Any]]:
    raw = Path(__file__).with_name("semgrep_workloads_v2.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
        raise ValueError("fixture_manifest_digest")
    manifest = json.loads(raw)
    sources = {
        "single_16k": [fragment(16384)],
        "sixteen_128k_repeated": [fragment(8192)] * 16,
        "sixteen_128k_distinct": [fragment(8192, i * 1000) for i in range(16)],
    }
    result = {}
    for name, parts in sources.items():
        if workload(parts) != manifest["fixtures"][name]:
            raise ValueError("fixture_payload_mismatch")
        result[name] = {"text": "\n".join(parts), **manifest["fixtures"][name]}
    return manifest, result


def case_plan(runs: int) -> list[dict[str, Any]]:
    if runs < 100:
        raise ValueError("qualification requires at least 100 runs")
    bursts = math.ceil(runs / 8)

    def serial(name: str) -> dict[str, Any]:
        return {"name": name, "kind": "serial", "fixture": name, "planned": runs}

    def loaded(fixture: str) -> list[dict[str, Any]]:
        return [
            {
                "name": "eight_wide_" + fixture + "_" + topology + "_" + "_".join(map(str, dist)),
                "kind": "loaded",
                "fixture": fixture,
                "topology": topology,
                "distribution": dist,
                "bursts": bursts,
                "planned": bursts * 8,
            }
            for topology in ("shared_owner", "three_owners")
            for dist in ((3, 3, 2), (4, 2, 2), (8, 0, 0))
        ]

    return [
        serial("single_16k"),
        serial("sixteen_128k_repeated"),
        *loaded("single_16k"),
        {
            "name": "eight_replacements",
            "kind": "replacement",
            "fixture": "single_16k",
            "topology": "three_owners",
            "distribution": (8, 0, 0),
            "bursts": bursts,
            "planned": bursts * 8,
        },
        {"name": "preflight_1m", "kind": "preflight", "planned": runs},
        serial("sixteen_128k_distinct"),
        *loaded("sixteen_128k_distinct"),
    ]


def result_evidence(result: Any, fixture: dict[str, Any]) -> dict[str, Any]:
    """Never serialize messages or matched source, including on invalid results."""
    expected = fixture["expected_findings"]
    row: dict[str, Any] = {
        "expected_findings": len(expected),
        "observed_findings": 0,
        "expected_targets": len(fixture["segments"]),
        "completed_targets": 0,
        "error": None,
    }
    if result is None:
        row["error"] = "invalid_token"
        return row
    identities = sorted(
        [f.rule_id, f.position.start, f.position.end]
        for f in result.findings
        if f.position is not None
    )
    row["observed_findings"] = len(result.findings)
    row["findings"] = identities
    cov = result.coverage
    if cov is not None:
        row["coverage"] = cov.to_dict()
        row["completed_targets"] = cov.completed_target_count
    if result.error:
        # Only fixed scanner error codes, never arbitrary exception text.
        import re

        match = re.search(r"\bsemgrep\.[a-z_]+\b", result.error)
        row["error"] = match.group() if match else "scanner_error"
    elif (
        identities != sorted(expected)
        or len(identities) != len(result.findings)
        or any(f.position_basis != "original" for f in result.findings)
    ):
        row["error"] = "finding_mismatch"
    elif (
        cov is None
        or cov.status != "complete"
        or cov.reasons
        or cov.target_count != len(fixture["segments"])
        or cov.completed_target_count != cov.target_count
        or cov.total_chars != len(fixture["text"])
        or sorted([s.start, s.end] for s in cov.spans if s.status == "complete")
        != fixture["segments"]
    ):
        row["error"] = "coverage_mismatch"
    return row


def finish_case(case: dict[str, Any]) -> None:
    samples = [s for s in case["samples"] if not s["warmup"]]
    success = [s["seconds"] for s in samples if s.get("status") == "ok"]
    errors = [s["seconds"] for s in samples if s.get("status") == "error"]
    terminal = sum(s.get("status") in ("ok", "error") for s in samples)
    case["counts"] = {
        "planned": case["planned"],
        "started": len(samples),
        "completed": terminal,
        "errored": len(errors),
        "not_run": case["planned"] - len(samples),
        "unfinished": len(samples) - terminal,
    }
    case["successful_seconds"] = summary(success)
    case["failed_seconds"] = summary(errors)
    case["burst_maxima_seconds"] = {
        str(b): max(s["seconds"] for s in samples if s["burst"] == b and "seconds" in s)
        for b in sorted({s["burst"] for s in samples if "seconds" in s})
    }


def gate_failures(records: dict[str, Any]) -> list[str]:
    failures = []
    for case in records["workloads"].values():
        finish_case(case)
        name = case["name"]
        counts = case["counts"]
        if (
            counts["completed"] != counts["planned"]
            or counts["errored"]
            or case["errors"]
            or any(s.get("status") != "ok" for s in case["samples"])
            or not any(s["warmup"] for s in case["samples"])
        ):
            failures.append(name + ": incomplete/error samples")
        values = case["successful_seconds"]
        limits = (
            {"mean": 1.0, "p95": 1.2, "p99": 1.4}
            if case["kind"] == "serial" and case["fixture"] == "single_16k"
            else {"mean": 1.8, "p95": 2.0, "p99": 2.3}
            if case["kind"] == "serial"
            else {"p95": 0.05}
            if case["kind"] == "preflight"
            else {"p95": 5.0, "max": 8.0}
            if case["kind"] == "loaded" and case["fixture"] == "single_16k"
            else {"p95": 7.5, "max": 8.0}
        )
        for metric, limit in limits.items():
            value = values.get(metric)
            if value is None or not math.isfinite(value) or value > limit:
                failures.append(f"{name}.{metric} > {limit}s or missing")
        if case["kind"] != "preflight" and (
            not case.get("close") or any(c["status"] != "closed" for c in case["close"])
        ):
            failures.append(name + ": owned close incomplete")
        if case["kind"] in ("loaded", "replacement"):
            resources = case.get("resources", {})
            if not resources or resources.get("missing") or not resources.get("samples"):
                failures.append(name + ": resource evidence incomplete")
            for field in (
                "parent_rss_peak_bytes",
                "owned_rss_sampled_peak_bytes",
                "stdout_high_water_per_child_bytes",
                "control_loop_samples",
            ):
                if not resources.get(field):
                    failures.append(name + ": missing observation " + field)
            if resources.get("root_residue") != 0 or resources.get("live_owned_processes") != 0:
                failures.append(name + ": owned residue")
    if records.get("measurement_error"):
        failures.append("measurement did not complete")
    if records.get("implementation", {}).get("tracked_dirty", True):
        failures.append("tracked working tree is dirty")
    return failures


def checkpoint(path: Path, snapshot: str) -> None:
    """One writer; keep the last complete checkpoint if replace fails."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes((snapshot + "\n").encode("utf-8"))
    os.replace(temporary, path)
