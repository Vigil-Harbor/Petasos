"""Translate Tool Search with Hermes's parser and fail closed without it."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from petasos.hermes.host import resolve_tool_call


@pytest.mark.parametrize(
    "result",
    [
        ("terminal", {"command": "echo ok"}, None),
        (None, {}, "unknown tool"),
        ("batch", {"calls": []}, None),
        ("terminal", [], None),
        ("", {}, None),
    ],
)
def test_resolution_or_the_original_wrapper(
    monkeypatch: pytest.MonkeyPatch, result: tuple[Any, Any, Any]
) -> None:
    args = {"name": "terminal", "arguments": {"command": "echo ok"}}
    seen = []

    def resolve(given: object) -> tuple[Any, Any, Any]:
        seen.append(given)
        return result

    monkeypatch.setattr(
        "petasos.hermes.host.load_module",
        lambda _name: SimpleNamespace(
            resolve_underlying_call=resolve, CONNECTOR_BATCH_SENTINEL="batch"
        ),
    )
    actual = resolve_tool_call("tool_call", args)
    assert seen == [args]
    assert actual == (
        (result[0], result[1])
        if result[0] == "terminal" and isinstance(result[1], dict)
        else ("tool_call", args)
    )


@pytest.mark.parametrize(
    "module",
    [
        None,
        SimpleNamespace(),
        SimpleNamespace(
            resolve_underlying_call=lambda _args: (_ for _ in ()).throw(RuntimeError("moved"))
        ),
    ],
)
def test_missing_or_broken_resolution_keeps_wrapper(
    monkeypatch: pytest.MonkeyPatch, module: object
) -> None:
    monkeypatch.setattr("petasos.hermes.host.load_module", lambda _name: module)
    args = {"name": "terminal", "arguments": {}}
    assert resolve_tool_call("tool_call", args) == ("tool_call", args)
    assert resolve_tool_call("terminal", args) == ("terminal", args)
