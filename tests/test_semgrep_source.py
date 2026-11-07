"""Applicability and original-coordinate regressions, independent of the engine."""

import json
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


@pytest.mark.parametrize("layers", [1, 2])
async def test_preflight_decodes_json_candidates_without_maps(layers: int) -> None:
    from petasos.scanners._semgrep_source import preflight

    text = r'"\u0065\u0076\u0061\u006c\u0028payload)"'
    if layers == 2:
        text = json.dumps(text)
    assert await preflight(text)
    assert (await select_sources(text)).targets
