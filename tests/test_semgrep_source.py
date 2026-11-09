"""Applicability and original-coordinate regressions, independent of the engine."""

import json
import subprocess
import sys
from typing import Any

import pytest

from petasos.scanners._semgrep_engine import result_for
from petasos.scanners._semgrep_source import ProjectionError, select_sources
from tests._semgrep_helpers import require


@pytest.mark.parametrize("text", ["Hello (world); goodbye.", "ls -la; cd foo", "FOO=1 make"])
async def test_ordinary_prose_and_shell_are_not_asserted(text: str) -> None:
    selected = await select_sources(text)
    assert not any(t.asserted for t in selected.targets)
    assert result_for(selected).error is None


async def test_indented_method_maps_back_to_patch_characters() -> None:
    method = "    def handle(self, value):\n        return eval(value)\n"
    selected = await select_sources(method)
    (target,) = selected.targets
    assert target.region.text == "def handle(self, value):\n    return eval(value)\n"
    start = target.region.text.index("eval")
    assert target.region.interval(start, start + 11) == (
        method.index("eval"),
        method.index("eval") + 11,
    )
    assert not target.asserted


async def test_asserted_missing_body_follows_failure_policy() -> None:
    selected = await select_sources("def handler(value):\n")
    assert selected.targets[0].asserted
    assert result_for(selected).error == "semgrep.incomplete"


async def test_dense_search_fragments_never_assert_and_limit_is_nonerror() -> None:
    text = "src/code.py\n" + "".join(f"  {i * 3}: def handler{i}(value):\n" for i in range(1, 21))
    selected = await select_sources(text)
    assert len(selected.targets) == 16
    assert all(not t.asserted for t in selected.targets)
    result = result_for(selected)
    assert result.error is None
    assert require(result.coverage).status == "partial"
    assert "target_limit_tentative" in require(result.coverage).reasons


@pytest.mark.parametrize(
    "metadata",
    [
        {"truncated": True, "next_offset": 20},
        {"truncated": True, "truncated_by": "bytes", "hint": "Continue"},
        {"truncated": True, "total_count_is_lower_bound": True, "_hint": "More matches"},
    ],
)
async def test_paged_delivered_code_is_not_clamped(metadata: dict[str, Any]) -> None:
    text = json.dumps({"content": "10|eval(value)\n", **metadata})
    selected = await select_sources(text)
    assert len(selected.targets) == 1
    result = result_for(selected, completed={0})
    assert result.error is None
    assert "host_paged" in require(result.coverage).reasons


async def test_true_line_clamp_on_supported_code_is_incomplete() -> None:
    selected = await select_sources(
        json.dumps({"content": "eval(value)", "truncated_lines": True})
    )
    assert result_for(selected, completed={0}).error == "semgrep.incomplete"


async def test_json_escapes_and_numbered_lines_map_original_intervals() -> None:
    text = json.dumps({"content": '10|# 😀\n11|eval("é")\n'}, ensure_ascii=True)
    selected = await select_sources(text)
    region = selected.targets[0].region
    start = region.text.index("eval")
    a, b = region.interval(start, start + len('eval("é")'))
    assert text[a:b] == 'eval(\\"\\u00e9\\")'


async def test_segments_cannot_hide_nonnewline_gaps() -> None:
    with pytest.raises(ProjectionError, match="invalid_envelope"):
        await select_sources("eval(x) HIDDEN eval(y)", segments=((0, 7), (15, 22)))


async def test_separate_patch_fragments_keep_offsets() -> None:
    old = "    def f(self):\n        return eval(x)"
    new = "    def f(self):\n        return eval(y)"
    text = old + "\n" + new
    selected = await select_sources(text, segments=((0, len(old)), (len(old) + 1, len(text))))
    assert len(selected.targets) == 2
    region = selected.targets[1].region
    p = region.text.index("eval")
    assert region.interval(p, p + 7) == (text.index("eval(y)"), text.index("eval(y)") + 7)


async def test_deep_noncode_json_does_not_report_engine_failure() -> None:
    selected = await select_sources("[" * 200 + '"hello"' + "]" * 200)
    result = result_for(selected)
    assert result.error is None
    assert require(result.coverage).status == "unsupported"
    assert "projection_depth_limit" in require(result.coverage).reasons


async def test_supported_fences_over_cap_report_incomplete() -> None:
    selected = await select_sources("```python\neval(value)\n```\n" * 17)
    assert len(selected.targets) == 16
    assert result_for(selected, completed=set(range(16))).error == "semgrep.incomplete"


async def test_clipped_tentative_rejection_is_partial_not_clear() -> None:
    selected = await select_sources("foo(" + "x" * 100, max_bytes=8)
    result = result_for(selected)
    assert result.error is None
    assert require(result.coverage).status == "partial"
    assert "source_limit_tentative" in require(result.coverage).reasons


async def test_json_code_before_depth_exhaustion_is_retained() -> None:
    text = '{"a":"import os\\nos.system(cmd)","b":' + "[" * 140 + "0" + "]" * 140 + "}"
    selected = await select_sources(text)
    assert len(selected.targets) == 1
    assert "os.system" in selected.targets[0].region.text
    assert selected.error == "semgrep.projection_limit_code"
    assert selected.tail is not None


async def test_code_in_json_keys_is_a_target() -> None:
    selected = await select_sources('{"os.system(cmd)": 1}')
    assert len(selected.targets) == 1
    assert selected.targets[0].region.text == "os.system(cmd)"


async def test_many_search_hits_report_the_unexamined_tail() -> None:
    selected = await select_sources(
        "app.py\n" + "".join(f"  {i * 3 + 1}: foo(value)\n" for i in range(40))
    )
    assert len(selected.targets) == 16
    assert selected.tail is not None
    assert selected.error is None
    assert "target_limit_tentative" in selected.reasons


async def test_malformed_deep_string_does_not_hide_later_escaped_code() -> None:
    text = "[" * 140 + r'"\x", "os.system\u0028cmd)"' + "]" * 140
    selected = await select_sources(text)
    assert selected.error == "semgrep.projection_limit_code"


async def test_truncated_envelope_with_escaped_code_is_recorded_as_unexamined() -> None:
    # The envelope never parses, and the raw pass cannot see a call whose
    # parenthesis is a JSON escape. Nothing is selected, so say so.
    selected = await select_sources(r'{"a": "os.system\u0028cmd)"')
    assert selected.targets == []
    assert selected.unsupported is True
    assert "malformed_envelope" in selected.reasons
    assert selected.error is None


async def test_truncated_envelope_with_plain_code_stays_raw() -> None:
    selected = await select_sources('{"a": "os.system(cmd)"')
    assert len(selected.targets) == 1
    assert "os.system(cmd)" in selected.targets[0].region.text
    assert selected.unsupported is False
    assert "malformed_envelope" not in selected.reasons


async def test_truncated_envelope_without_code_reads_no_targets() -> None:
    selected = await select_sources('{"a": "hello world"')
    assert selected.targets == []
    assert selected.unsupported is False
    assert selected.reasons == set()


@pytest.mark.parametrize("layers", [1, 2])
async def test_preflight_decodes_json_candidates_without_maps(layers: int) -> None:
    from petasos.scanners._semgrep_source import preflight

    text = r'"\u0065\u0076\u0061\u006c\u0028payload)"'
    if layers == 2:
        text = json.dumps(text)
    assert await preflight(text)
    assert (await select_sources(text)).targets


@pytest.mark.parametrize("kind", ["raw", "json", "tabs", "mixed", "unicode", "double"])
async def test_long_whitespace_across_chunk_boundaries_is_selected(kind: str) -> None:
    from petasos.scanners._semgrep_source import preflight

    call = "os.system" if kind == "tabs" else "eval"
    gap = "\t" * 400 if kind == "tabs" else " " * 400
    body = " " * 7899 + call + gap + "(payload)"
    text = body if kind == "raw" else json.dumps(body)
    expected = 1
    if kind == "mixed":
        text = json.dumps({"a": "foo(1)", "b": body})
        expected = 2
    if kind in ("unicode", "double"):
        text = '"' + "".join(f"\\u{ord(char):04x}" for char in body) + '"'
        if kind == "double":
            text = json.dumps(text)
    assert await preflight(text)
    selected = await select_sources(text)
    assert len(selected.targets) == expected
    assert any(call in target.region.text for target in selected.targets)


async def test_escape_and_whitespace_carry_at_every_boundary_alignment() -> None:
    from petasos.scanners._semgrep_source import preflight

    for offset in range(8155, 8198):
        raw = " " * offset + "eval" + " " * 17000 + "(payload)"
        encoded = json.dumps(raw).replace(" ", r"\u0020")
        assert await preflight(raw)
        assert await preflight(encoded)
        assert await preflight(json.dumps(encoded))
    # A dotted identifier itself can exceed the carry buffer as well.
    assert await preflight("prefix." + "method" * 1600 + " " * 17000 + "(payload)")


async def test_leaf_overflow_recognizes_second_layer_code() -> None:
    text = json.dumps(["benign"] * 4096 + [r"eval\u0028payload)"])
    selected = await select_sources(text)
    assert selected.error == "semgrep.projection_limit_code"


@pytest.mark.parametrize("separator", ["\n", "/**/", "\f", "\u00a0", "\ufeff", "// note\n"])
async def test_sensitive_call_separators_survive_streaming(separator: str) -> None:
    from petasos.scanners._semgrep_source import preflight

    for offset in (0, 8188, 8190, 8192):
        body = " " * offset + "eval" + separator + "(payload)"
        for text in (body, json.dumps(body), json.dumps(json.dumps(body))):
            assert await preflight(text)
            assert (await select_sources(text)).targets
    body = "eval/*" + "x" * 20000 + "*/(payload)"
    assert await preflight(body)
    assert (await select_sources(body)).targets


@pytest.mark.parametrize(
    "body",
    [
        "See the docs at example.com\nThanks!",
        "Let me think...\nOK",
        "Pick a fruit, e.g.\u00a0apples",
        "I attached report.pdf\nand notes.",
        "We should eval\nthe options",
        "https://example.com",
        "a.b",
        "report.pdf\ufeff",
    ],
)
async def test_prose_separators_do_not_admit_engine_work(body: str) -> None:
    from petasos.scanners._semgrep_source import preflight

    for text in (body, json.dumps(body), json.dumps({"value": body})):
        assert not await preflight(text), text
        assert not (await select_sources(text)).targets, text


@pytest.mark.parametrize("space", ["\n", "\r\n", "\f", "\u00a0", "\ufeff"])
async def test_long_unicode_call_gaps_and_declaration_anchors(space: str) -> None:
    from petasos.scanners._semgrep_source import preflight

    body = "prefix." + "method" * 1600 + space * 17000 + "(payload)"
    assert await preflight(body)
    assert await preflight(json.dumps(body))
    assert await preflight("ordinary words\n" + space * 17000 + "\nimport os")


def test_whitespace_compaction_matches_reference_for_ascii_and_unicode() -> None:
    import random
    import re

    from petasos.scanners._semgrep_source import _compact_whitespace

    pattern = re.compile(r"[\s\ufeff]+")
    whitespace = "".join(chr(i) for i in range(0x110000) if chr(i).isspace()) + "\ufeff"
    rng = random.Random(25410)
    inputs = ["", "benign words " * 1000, "eval (payload)", "a\x00b c"]
    inputs.extend(f"a{char}b" for char in whitespace)
    inputs.extend(
        "".join(rng.choices("abc.() " + whitespace, k=rng.randrange(100))) for _ in range(4000)
    )
    for value in inputs:
        expected = pattern.sub(lambda match: "\n" if "\n" in match[0] else " ", value)
        assert _compact_whitespace(value) == expected, repr(value)


def test_candidate_token_semantics_match_short_reference_inputs() -> None:
    import random
    import re

    from petasos.scanners._semgrep_source import _is_candidate

    reference = re.compile(
        r"\b[A-Za-z_$][\w.$]*\("
        r"|\b(?:eval|exec|Function|[A-Za-z_$][\w$]*\.[\w.$]+)"
        r"(?:[\s\ufeff]+\(|[\s\ufeff]*(?:/\*|//))"
        r"|(?m:^[ \t]*(?:from[ \t]+\S+[ \t]+import|import|class|def|async[ \t]+def"
        r"|function|const|let|var)\b)"
    )
    rng = random.Random(254)
    for _ in range(4000):
        token = "".join(rng.choices("ab09_.$é", k=rng.randrange(1, 32)))
        token += rng.choice(("", ".eval", "$eval", "exec", ".Function"))
        text = token + rng.choice(("(", " (", "\n(", "/**/(", "//", "\ufeff", "\nwords", ""))
        text += rng.choice(("", "\nimport os", " \u212a.abc//", " é\u0661 ", " eval\u00a0(x)"))
        assert _is_candidate(text) == bool(reference.search(text)), repr(text)


def test_header_and_fence_classification_matches_short_reference_inputs() -> None:
    import random
    import re

    from petasos.scanners._semgrep_source import (
        _FENCE,
        _is_candidate,
        _is_header,
        _is_search_header,
    )

    header = re.compile(
        r"(?:async +)?def +[A-Za-z_]\w*\s*\(.*\)\s*(?:->[^:]+)?\s*:"
        r"|class +[A-Za-z_]\w*(?:\([^\n]*\))?\s*:"
    )
    fence = re.compile(r"(?m)^ {0,3}(`{3,}|~{3,})([^\r\n]*)\r?$")
    rng = random.Random(25407)
    for _ in range(6000):
        atoms = ("x", "é", "->", ")", "(", ":", " ", "\t", "\n", "\r", ".", "/", "\\")
        body = "".join(rng.choices(atoms, k=rng.randrange(24)))
        value = rng.choice(("def f(", "async def f(", "class F", "class F(", ""))
        value += body + rng.choice(("", ":", "):", ")->x:", ")-> :"))
        assert _is_header(value) == bool(header.fullmatch(value)), repr(value)
        path_like = bool(re.fullmatch(r"\S[^\r\n]*[./\\][^\r\n]*", value))
        code_like = any(c in value for c in "()[]{};=\"'`") or _is_candidate(value)
        assert _is_search_header(value) == (path_like and not code_like), repr(value)
        value = " " * rng.randrange(6) + rng.choice(("`", "~")) * rng.randrange(12) + body
        assert [(m.span(), m.groups()) for m in _FENCE.finditer(value)] == [
            (m.span(), m.groups()) for m in fence.finditer(value)
        ], repr(value)


def test_million_character_header_fence_and_search_attacks_are_bounded() -> None:
    script = r"""
import asyncio, json, sys, time
sys.path[:] = json.loads(sys.argv[1])
from petasos.scanners._semgrep_source import (
    _FENCE, _is_header, _is_search_header, preflight, select_sources,
)

async def run():
    values = {
        "header": "def f(" + ")->x" * 249970,
        "header_colon": "def f(" + ")->x" * 249960 + ":!:",
        "search": "a" + "." * 999850 + "\rb\neval(x)",
        "fence": "`" * 999850 + "\rX\neval(x)",
    }
    measured = {}
    for name, body in values.items():
        for wrapped in (False, True):
            text = json.dumps(body) if wrapped else body
            started = time.perf_counter()
            assert not _is_header(body)
            assert not _is_search_header(body)
            assert not list(_FENCE.finditer(body))
            assert await preflight(text)
            selected = await select_sources(text)
            assert selected.examined == len(text)
            elapsed = time.perf_counter() - started
            measured[name + ("_json" if wrapped else "_raw")] = elapsed
            assert elapsed < 2.0, (name, wrapped, elapsed)
    print(json.dumps(measured))

asyncio.run(run())
"""
    result = subprocess.run(
        [str(vars(sys)["_base_executable"]), "-c", script, json.dumps(sys.path)],
        capture_output=True,
        text=True,
        timeout=20,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_million_character_dotted_input_has_bounded_candidate_cost() -> None:
    # A subprocess watchdog is necessary: asyncio timeouts cannot interrupt a
    # synchronous regex, and the old implementation could hang CI for hours.
    script = r"""
import asyncio, json, sys, time
sys.path[:] = json.loads(sys.argv[1])
from petasos.scanners._semgrep_source import _is_candidate, preflight, select_sources

async def run():
    dotted = "a." * 499950
    values = {
        "raw": dotted,
        "json": json.dumps(dotted),
        "after_fence": "```python\neval(x)\n```\n" + dotted,
        "json_after_call": json.dumps(["eval(x)", dotted]),
    }
    measured = {}
    for name, text in values.items():
        started = time.perf_counter()
        assert not _is_candidate(dotted)
        # A leading marker defeats the cheap absence check, exercising the
        # maximal-run matcher on the entire hostile identifier as well.
        assert not _is_candidate("(" + dotted)
        gate = await preflight(text)
        selection = await select_sources(text)
        expected = name in ("after_fence", "json_after_call")
        assert gate is expected, name
        assert len(selection.targets) == int(expected), name
        elapsed = time.perf_counter() - started
        measured[name] = elapsed
        assert elapsed < 1.0, (name, elapsed)
    print(json.dumps(measured))

asyncio.run(run())
"""
    result = subprocess.run(
        # Keep the parent's installed dependencies while bypassing the Windows
        # venv redirector, so timeout kills the actual regex worker process.
        [str(vars(sys)["_base_executable"]), "-c", script, json.dumps(sys.path)],
        capture_output=True,
        text=True,
        timeout=15,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0, result.stdout + result.stderr


async def test_code_shaped_search_headers_are_not_discarded() -> None:
    # A valid module whose first and last lines merely resemble path headers.
    text = 'os.system(cmd); """a.py\n  1: safe(1)\n""".strip()\n'
    selected = await select_sources(text)
    assert any("os.system(cmd)" in t.region.text for t in selected.targets)
    # Genuine search output still selects only the numbered rows.
    rows = await select_sources("src/app.py\n  10: run(x)\n  11: eval(y)\n")
    assert [t.region.text for t in rows.targets] == ["run(x)\neval(y)\n"]


@pytest.mark.parametrize(
    "call",
    [
        "(eval)(payload)",
        "x[0](payload)",
        "f()(payload)",
        "(eval)\n(payload)",
        "eval \\\n(payload)",
    ],
)
async def test_expression_callees_and_continuations_are_candidates(call: str) -> None:
    from petasos.scanners._semgrep_source import preflight

    for text in (call, json.dumps({"content": call})):
        assert await preflight(text), text
        selected = await select_sources(text)
        assert selected.targets, text
    # Chunk boundaries (8,192 characters) cannot split the call away.
    for shift in range(-12, 13):
        padded = " " * (8192 + shift - call.index("(", 1)) + call
        assert await preflight(padded), shift


@pytest.mark.parametrize(
    "suffix,error",
    [("eval(payload)", None), ("```python\neval(x)\n```\n", "semgrep.incomplete")],
)
async def test_clipped_json_leaf_records_the_omitted_suffix(
    suffix: str, error: str | None
) -> None:
    text = json.dumps(" " * 65536 + suffix)
    selected = await select_sources(text)
    assert selected.tail is not None
    assert 65536 < selected.tail < len(text)
    assert "source_limit_tentative" in selected.reasons
    assert selected.error == error


@pytest.mark.parametrize(
    "text",
    ["1" * 5000 + "|eval(payload)", "a.py\n  " + "1" * 5000 + ": eval(payload)"],
)
async def test_oversized_line_numbers_stay_raw(text: str) -> None:
    selected = await select_sources(text)
    assert selected.error is None
    assert any("eval(payload)" in t.region.text for t in selected.targets)
