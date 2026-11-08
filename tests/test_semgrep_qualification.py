import hashlib
import json
from pathlib import Path

import pytest

from petasos.scanners import _semgrep_qualification as q
from petasos.scanners._semgrep_engine import ENGINE_VERSION


async def test_benchmark_error_diagnostics_are_bounded_and_omit_paths() -> None:
    import errno
    import importlib.util

    script = Path(__file__).resolve().parents[1] / "scripts/semgrep_benchmark.py"
    spec = importlib.util.spec_from_file_location("semgrep_benchmark", script)
    assert spec is not None and spec.loader is not None
    benchmark = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(benchmark)
    stages = benchmark.StageTimings()
    failure = PermissionError(errno.EACCES, "private source text", "private/path")

    def denied() -> None:
        raise failure

    wrapped = stages.wrap("root_remove_attempt", denied)
    for _ in range(70):
        with pytest.raises(PermissionError) as caught:
            wrapped()
        assert caught.value is failure

    async def unavailable() -> None:
        raise RuntimeError("private cleanup detail")

    with pytest.raises(RuntimeError):
        await stages.wrap("root_cleanup", unavailable)()
    assert stages.error_count == 71
    assert len(stages.errors) == 64
    assert stages.errors[0] == {
        "stage": "root_remove_attempt",
        "type": "PermissionError",
        "errno": errno.EACCES,
        "winerror": None,
    }
    assert "private" not in json.dumps(stages.errors)
    assert len(stages.values["root_remove_attempt"]) == 70
    assert len(stages.values["root_cleanup"]) == 1


def test_packaged_empty_manifest_uses_named_unqualified_workload() -> None:
    warning = q.qualification_warning(7, "a" * 64)
    assert warning is not None
    assert "eight_outstanding_three_profiles_16k_64k_v3" in warning
    assert "reference_p95_seconds=8.000" in warning
    assert "unqualified_fallback" in warning
    assert q.qualification_warning(8, "a" * 64) is None


def test_matching_reference_and_mismatched_or_invalid_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "qualification.json"
    monkeypatch.setattr(q, "_MANIFEST", path)
    monkeypatch.setattr(q, "platform_key", lambda: "windows_x64")
    row = {
        "platform": "windows_x64",
        "engine_version": ENGINE_VERSION,
        "engine_sha256": "a" * 64,
        "rules_sha256": hashlib.sha256(q._RULES.read_bytes()).hexdigest(),
        "workload": "eight_outstanding_three_profiles_16k_64k_v3",
        "qualified": True,
        "loaded_p95_seconds": 5,
        "hardware": {"fixture": "synthetic reference"},
    }
    path.write_text(json.dumps({"schema_version": 1, "measurements": [row]}))
    warning = q.qualification_warning(4, "a" * 64)
    assert warning is not None and "packaged_reference" in warning
    assert "reference_p95_seconds=5.000" in warning
    assert q.qualification_warning(6, "a" * 64) is None
    old = {**row, "workload": "eight_outstanding_three_profiles"}
    path.write_text(json.dumps({"schema_version": 1, "measurements": [old]}))
    assert "unqualified_fallback" in (q.qualification_warning(6, "a" * 64) or "")
    path.write_text(json.dumps({"schema_version": 1, "measurements": [row]}))
    assert "unqualified_fallback" in (q.qualification_warning(6, "b" * 64) or "")
    path.write_text('{"schema_version":999,"measurements":[]}')
    assert "unqualified_fallback" in (q.qualification_warning(6, "a" * 64) or "")
    path.write_text("invalid")
    assert "unqualified_fallback" in (q.qualification_warning(6, "a" * 64) or "")
    path.unlink()
    assert "unqualified_fallback" in (q.qualification_warning(6, "a" * 64) or "")
