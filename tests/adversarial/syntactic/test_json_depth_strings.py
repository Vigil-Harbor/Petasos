"""Pin JSON depth counting that excludes brackets inside strings."""

from __future__ import annotations

from petasos.scanners.minimal import MinimalScanner


def test_json_depth_brackets_in_string() -> None:
    scanner = MinimalScanner()
    text = '{"data": "[[[[[[[[[["}'
    depth = scanner._check_json_depth(text)
    assert depth == 1
