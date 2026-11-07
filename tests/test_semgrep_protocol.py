"""Hostile protocol data and lexical-exclusion regressions."""

import json

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
    ],
)
def test_uncertain_binding_is_never_excluded(source: str) -> None:
    assert _local_functions(source) == set()
