"""Parameters retain their text and obey the shared character ceiling."""

from __future__ import annotations

import pytest

from petasos.guard.params import render_param_text
from petasos.limits import MAX_PARAM_TEXT_LEN


def test_render_keeps_raw_strings_serializes_values_and_drops_none() -> None:
    rendered = render_param_text({"raw": "line one\nline two", "missing": None, "items": [1, 2]})
    assert rendered.text == "line one\nline two\n[1, 2]"
    assert rendered.original_len == len(rendered.text)
    assert not rendered.truncated
    assert render_param_text({"empty": None}).text == ""
    assert render_param_text({}).text == ""


@pytest.mark.parametrize("excess", [-1, 0, 1])
def test_render_caps_characters_at_the_shared_ceiling(excess: int) -> None:
    text = "é" * (MAX_PARAM_TEXT_LEN + excess)
    rendered = render_param_text({"value": text})
    assert rendered.text == text[:MAX_PARAM_TEXT_LEN]
    assert rendered.original_len == len(text)
    assert rendered.truncated is (excess > 0)
