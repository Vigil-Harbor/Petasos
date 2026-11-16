"""Pin JSON depth counting that excludes brackets inside strings."""

from __future__ import annotations

from petasos.scanners.minimal import MinimalScanner


def test_json_depth_brackets_in_string() -> None:
    scanner = MinimalScanner()
    text = '{"data": "[[[[[[[[[["}'
    depth = scanner._check_json_depth(text)
    assert depth == 1


def test_brackets_in_program_code_are_not_nesting() -> None:
    scanner = MinimalScanner()
    code = "rows = [f(x[i][j]) for i in range(n) if g(a[b[c[d[e[h[k[m[p[q[r]]]]]]]]]])]\n"
    assert scanner._check_json_depth(code * 3) <= 2


def test_brackets_in_a_shell_loop_are_not_nesting() -> None:
    scanner = MinimalScanner()
    shell = (
        'for d in a b; do [[ -n "$d" ]] && '
        "{ awk '/x[0-9]{2}[a-z]/{c[$1]++} END{print c[1]}' f; }; done"
    )
    assert scanner._check_json_depth(shell * 6) <= 2


def test_deep_json_after_other_text_is_still_counted() -> None:
    scanner = MinimalScanner()
    text = "the payload follows\n" + '{"a":' * 12 + "1" + "}" * 12
    assert scanner._check_json_depth(text) == 12


def test_unclosed_deep_json_is_still_counted() -> None:
    scanner = MinimalScanner()
    assert scanner._check_json_depth("note\n" + "[" * 11) == 11
