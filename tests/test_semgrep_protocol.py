"""Hostile protocol data and lexical-exclusion regressions."""

import json
from pathlib import Path
from typing import Any

import pytest

from petasos.scanners._semgrep_engine import ProtocolError, _local_functions, strict_output


@pytest.mark.parametrize(
    "payload",
    [
        b'{"version":"1.183.0","results":[],"results":[]}',
        b'{"version":"1.183.0","results":[],"value":NaN}',
        b'{"version":"different","results":[]}',
        b'x{"version":"1.183.0","results":[]}',
        b'{"version":"1.183.0","results":[]} trailing',
        b'{"version":"1.183.0","results":[],"nest":' + b"[" * 33 + b"0" + b"]" * 33 + b"}",
    ],
)
def test_malformed_engine_output_is_rejected(payload: bytes) -> None:
    with pytest.raises(ProtocolError):
        strict_output(payload)


def test_raw_core_progress_prefix_is_supported() -> None:
    assert (
        strict_output(b".\r\r\n" + json.dumps({"version": "1.183.0", "results": []}).encode())[
            "results"
        ]
        == []
    )


def test_explicit_local_function_binding_is_excluded() -> None:
    assert _local_functions("def eval(value):\n    return value\neval(data)\n") == {(3, 0)}


@pytest.mark.parametrize(
    "source",
    [
        "def eval(value):\n    return value\nfrom builtins import eval\neval(data)",
        "def eval(value):\n    return value\nimport builtins as eval\neval(data)",
        "def eval(value):\n    return value\neval = other\neval(data)",
        "@decorator\ndef eval(value):\n    return value\neval(data)",
        "def eval(value):\n    return value\n(lambda eval: eval(data))(other)",
        "def eval(value):\n    return value\nexec(rebind)\neval(data)",
        # Annotations run at definition time on Python 3.11-3.13.
        'def eval(value):\n    return value\ndef other(arg: globals().pop("eval")):\n'
        "    pass\neval(data)",
        "def eval(value):\n    return value\ndef other(*, arg: rebind()):\n    pass\neval(data)",
        "def eval(value):\n    return value\ndef other(*args: rebind()):\n    pass\neval(data)",
        "def eval(value):\n    return value\ndef other(**kw: rebind()):\n    pass\neval(data)",
        "def eval(value):\n    return value\ndef other(a, /, b: rebind()):\n    pass\neval(data)",
        "def eval(value):\n    return value\ndef other() -> rebind():\n    pass\neval(data)",
        "def eval(value) -> int:\n    return value\neval(data)",
    ],
)
def test_uncertain_binding_is_never_excluded(source: str) -> None:
    assert _local_functions(source) == set()


def _expected(tmp_path: Path, count: int = 1) -> tuple[list[str], dict[str, Any]]:
    from petasos.scanners._semgrep_engine import _path
    from petasos.scanners._semgrep_source import Region, Target

    paths = [str(tmp_path / f"candidate-{i}.source") for i in range(count)]
    targets = [Target(Region("eval(x)\n", 0, 8)) for _ in paths]
    return paths, {_path(p): (i, t) for i, (p, t) in enumerate(zip(paths, targets, strict=True))}


@pytest.mark.parametrize(
    "error",
    [
        {"type": "Timeout", "path": 0},
        {"error_type": ["OutOfMemory"], "location": {"path": 0}},
        {"type": "Fatal error"},
    ],
)
def test_engine_failures_never_leave_targets_complete(
    tmp_path: Path, error: dict[str, Any]
) -> None:
    from petasos.scanners._semgrep_engine import _findings

    error = json.loads(json.dumps(error))

    paths, expected = _expected(tmp_path, 2)
    for holder in (error, error.get("location", {})):
        if holder.get("path") == 0:
            holder["path"] = paths[0]
    data = {"paths": {"scanned": paths}, "errors": [error], "results": []}
    _found, parsed, failure = _findings(data, expected)
    assert failure == "semgrep.engine_error"
    assert 0 not in parsed
    if "path" not in error and "location" not in error:
        assert parsed == set()


@pytest.mark.parametrize(
    "mutation",
    [
        {"paths": []},
        {"errors": [None]},
        {"errors": [{"type": "Timeout", "location": []}]},
        {"results": [None]},
        {"results": [{"check_id": "petasos.semgrep.python.dynamic_code", "path": 0, "start": []}]},
    ],
)
def test_malformed_nested_structures_are_protocol_errors(
    tmp_path: Path, mutation: dict[str, Any]
) -> None:
    from petasos.scanners._semgrep_engine import _findings

    mutation = json.loads(json.dumps(mutation))

    paths, expected = _expected(tmp_path)
    data = {"paths": {"scanned": paths}, "errors": [], "results": [], **mutation}
    for row in data["results"]:
        if isinstance(row, dict) and row.get("path") == 0:
            row["path"] = paths[0]
            row["end"] = {"offset": 1}
    with pytest.raises(ProtocolError):
        _findings(data, expected)


async def test_protocol_error_keeps_findings_from_earlier_grammars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    from petasos.scanners import _semgrep_engine as engine
    from petasos.scanners._semgrep_process import ProcessResult
    from petasos.scanners._semgrep_source import select_sources

    selection = await select_sources("eval(payload)\n")
    assert len(selection.targets) == 1
    calls: list[list[str]] = []

    async def canned(argv: list[str], root: Path, *args: Any, **kwargs: Any) -> ProcessResult:
        calls.append(argv)
        path = str(root / "candidate-0.source")
        body: dict[str, Any]
        if len(calls) == 1:
            row = {
                "check_id": "petasos.semgrep.python.dynamic_code",
                "path": path,
                "start": {"offset": 0},
                "end": {"offset": 13},
            }
            body = {
                "version": engine.ENGINE_VERSION,
                "paths": {"scanned": [path]},
                "errors": [],
                "results": [row],
            }
        else:
            body = {
                "version": engine.ENGINE_VERSION,
                "paths": {"scanned": [path]},
                "errors": [],
                "results": [None],
            }
        return ProcessResult(0, json.dumps(body).encode(), None)

    monkeypatch.setattr(engine, "run_owned_process", canned)
    with ThreadPoolExecutor(max_workers=2) as executor:
        result = await engine.scan_selected(
            selection, "engine", tmp_path, time.monotonic() + 8, threading.Event(), executor
        )
    assert len(calls) == 2
    assert result.error == "semgrep.protocol_error"
    assert [f.rule_id for f in result.findings] == ["petasos.semgrep.python.dynamic_code"]


async def test_omitted_tail_without_targets_is_partial_coverage() -> None:
    from petasos.scanners._semgrep_engine import result_for
    from petasos.scanners._semgrep_source import select_sources

    selection = await select_sources(json.dumps(" " * 65536 + "eval(payload)"))
    assert not selection.targets
    coverage = result_for(selection).coverage
    assert coverage is not None
    assert coverage.status == "partial"
    assert "source_limit_tentative" in coverage.reasons
