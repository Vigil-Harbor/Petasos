"""Prepared code scans compose once with ordinary library policy."""

import asyncio
import hashlib
import os
import time
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from petasos import PetasosConfig, Pipeline, Position, ScanFinding, ScanResult, Severity
from petasos.pipeline import merge_findings
from petasos.scanners.semgrep import SemgrepLifecycleOwner, SemgrepScanner
from petasos.session.guard import render_param_text
from petasos.session.ingest import HEAD_CHARS, scan_ingestion_result
from tests._semgrep_helpers import require


def test_second_merge_cannot_evict_original_semgrep_finding() -> None:
    code = ScanFinding(
        "petasos.semgrep.python.dynamic_code",
        "unsafe_code",
        Severity.MEDIUM,
        1,
        "Dynamic code evaluation call.",
        "semgrep",
        Position(3, 20),
        position_basis="original",
    )
    legacy = ScanFinding(
        "legacy", "injection", Severity.HIGH, 1, "Legacy", "minimal", Position(0, 30)
    )
    merged = merge_findings(
        (ScanResult("head", (code, legacy)), ScanResult("sweep", (legacy, code)))
    )
    assert merged.count(code) == 1
    assert legacy in merged


@pytest.fixture(autouse=True)
def _abstract_ownership_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    if not os.environ.get("SEMGREP_ENGINE_PATH"):
        monkeypatch.setattr("petasos.scanners.semgrep.supported_platform", lambda: True)


@pytest.mark.parametrize(
    "fail_mode,safe", [("open", True), ("degraded", False), ("closed", False)]
)
async def test_missing_owned_engine_obeys_failure_policy_but_no_code_stays_safe(
    fail_mode: Any, safe: bool
) -> None:
    async with SemgrepLifecycleOwner() as owner:
        scanner = SemgrepScanner(owner=owner)
        pipeline = Pipeline([scanner], config=PetasosConfig(fail_mode=fail_mode))
        result = await pipeline.inspect("eval(data)")
        assert result.safe is safe
        assert require(result.backend_coverage)["semgrep"].status == "error"
        result = await pipeline.inspect("Hello.")
        assert result.safe
        assert require(result.backend_coverage)["semgrep"].status == "no_targets"


async def test_prepared_policy_exactly_once_and_wrong_owner_has_no_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with SemgrepLifecycleOwner() as owner:
        scanner = SemgrepScanner(owner=owner)
        pipeline = Pipeline([scanner])
        other = Pipeline([scanner])
        own_hook, other_hook = AsyncMock(return_value=None), AsyncMock(return_value=None)
        monkeypatch.setattr(pipeline, "_frequency_hook", own_hook)
        monkeypatch.setattr(other, "_frequency_hook", other_hook)
        token = require(await pipeline._prepare_semgrep("hello"))
        assert own_hook.await_count == 0
        invalid = await other._inspect_with_prepared_semgrep("hello", token)
        assert invalid.errors == ("semgrep.prepared_invalid",)
        assert other_hook.await_count == 0
        # The failed cross-owner attempt retires the token rather than replaying.
        replay = await pipeline._inspect_with_prepared_semgrep("hello", token)
        assert replay.errors == ("semgrep.prepared_invalid",)
        token = require(await pipeline._prepare_semgrep("hello"))
        await pipeline._inspect_with_prepared_semgrep("hello", token, weight_cap=2)
        assert own_hook.await_count == 1
        await pipeline._inspect_with_prepared_semgrep("hello", token)
        assert own_hook.await_count == 1


async def test_policy_reconfigure_preserves_restart_settings_and_live_token() -> None:
    async with SemgrepLifecycleOwner() as owner:
        scanner = SemgrepScanner(owner=owner)
        config = PetasosConfig(semgrep_enabled=True)
        pipeline = Pipeline([scanner], config=config)
        token = require(await pipeline._prepare_semgrep("eval(data)"))
        pipeline.reconfigure(
            replace(
                config, semgrep_enabled=False, semgrep_request_timeout_seconds=2, fail_mode="open"
            )
        )
        assert pipeline.config.semgrep_enabled
        assert pipeline.config.semgrep_request_timeout_seconds == 8
        result = await pipeline._inspect_with_prepared_semgrep("eval(data)", token)
        assert result.safe


async def test_supplied_ingest_token_never_prepares_twice(monkeypatch: pytest.MonkeyPatch) -> None:
    async with SemgrepLifecycleOwner() as owner:
        pipeline = Pipeline([SemgrepScanner(owner=owner)])
        token = require(await pipeline._prepare_semgrep("hello"))
        monkeypatch.setattr(
            pipeline, "_prepare_semgrep", AsyncMock(side_effect=AssertionError("second prepare"))
        )
        result = await scan_ingestion_result(pipeline, "hello", _semgrep_prepared=token)
        assert not result.errors
        assert require(result.backend_coverage)["semgrep"].status == "no_targets"


async def test_supplied_ingest_token_rejects_changed_tail_with_same_head() -> None:
    async with SemgrepLifecycleOwner() as owner:
        pipeline = Pipeline([SemgrepScanner(owner=owner)])
        text = "a" * HEAD_CHARS + "original tail"
        token = require(await pipeline._prepare_semgrep(text))
        result = await scan_ingestion_result(
            pipeline, "a" * HEAD_CHARS + "changed tail", _semgrep_prepared=token
        )
        assert any("semgrep.prepared_invalid" in error for error in result.errors)
        assert result.head is None
        assert token._text is None


async def test_missing_engine_no_target_token_cannot_be_reused_for_code() -> None:
    async with SemgrepLifecycleOwner() as owner:
        pipeline = Pipeline([SemgrepScanner(owner=owner)])
        token = require(await pipeline._prepare_semgrep("Hello."))
        result = await pipeline._inspect_with_prepared_semgrep("eval(data)", token)
        assert result.errors == ("semgrep.prepared_invalid",)


@pytest.fixture
async def real_pipeline() -> AsyncIterator[Pipeline]:
    engine = os.environ.get("SEMGREP_ENGINE_PATH")
    if not engine:
        pytest.skip("isolated engine required")
    with open(engine, "rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    async with SemgrepLifecycleOwner() as owner:
        scanner = SemgrepScanner(owner=owner, engine_path=engine, engine_sha256=digest)
        deadline = time.monotonic() + 8
        while scanner.availability()[1] == "semgrep.probe_pending" and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
        assert scanner.availability() == (True, None)
        yield Pipeline([scanner], config=PetasosConfig(scanner_timeout_seconds=0.001))


async def test_real_ingest_scans_beyond_head_and_survives_second_merge(
    real_pipeline: Pipeline,
) -> None:
    text = "Ordinary prose. " * 400 + "\n```python\neval(data)\n```"
    assert text.index("eval") > HEAD_CHARS
    result = await scan_ingestion_result(real_pipeline, text)
    findings = [f for f in result.findings if f.scanner_name == "semgrep"]
    assert len(findings) == 1
    assert require(findings[0].position).start == text.index("eval")
    assert require(result.backend_coverage)["semgrep"].total_chars == len(text)
    assert not any(r.error for r in require(result.head).scanner_results)


async def test_real_patch_parts_preserve_original_offsets_and_action_independence(
    real_pipeline: Pipeline,
) -> None:
    rendered = render_param_text(
        {
            "path": r"C:\project\app.py",
            "old_string": "    def handle(self):\n        return eval(old)",
            "new_string": "    def handle(self):\n        return eval(new)",
        }
    )
    token = require(
        await real_pipeline._prepare_semgrep(rendered.text, segments=rendered.segments)
    )
    result = await real_pipeline._inspect_with_prepared_semgrep(
        rendered.text, token, direction="outbound"
    )
    findings = [f for f in result.findings if f.scanner_name == "semgrep"]
    assert {require(f.position).start for f in findings} == {
        rendered.text.index("eval(old)"),
        rendered.text.index("eval(new)"),
    }
    assert not any(r.error for r in result.scanner_results)
