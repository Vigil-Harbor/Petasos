"""SYN-05 adversarial: JSON depth with brackets in string literals (PET-69)."""

from __future__ import annotations

from petasos.scanners.minimal import MinimalScanner


def test_json_depth_brackets_in_string() -> None:
    # Regression for PET-69: brackets in string literals must not inflate depth
    scanner = MinimalScanner()
    text = '{"data": "[[[[[[[[[["}'
    depth = scanner._check_json_depth(text)
    assert depth == 1
