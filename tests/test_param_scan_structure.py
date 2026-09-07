"""PET-190: structural pin on the single parameter-text derivation.

T-7. The behavioral tests in ``test_param_scan_parity.py`` prove the two paths agree today.
This file pins the *property* that keeps them agreeing: neither path may re-grow its own
serialization, its own cap, or its own direction literal. Written against what must be true,
not against the shape of the code that was deleted.

Pure ``ast`` plus stdlib: no ``petasos`` import, so it runs even when the library cannot be
imported at all.
"""

from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_GUARD_PATH = _ROOT / "petasos" / "session" / "guard.py"
_PLUGIN_PATH = _ROOT / "docs" / "deployment" / "reference_plugin" / "__init__.py"


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _find_function(tree: ast.Module, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} not found")


def _called_names(node: ast.AST) -> list[str]:
    """Every call target in `node`, as a dotted string (``json.dumps``, ``safe_json_dumps``)."""
    names: list[str] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Name):
            names.append(func.id)
        elif isinstance(func, ast.Attribute):
            parts = [func.attr]
            value = func.value
            while isinstance(value, ast.Attribute):
                parts.append(value.attr)
                value = value.value
            if isinstance(value, ast.Name):
                parts.append(value.id)
            names.append(".".join(reversed(parts)))
    return names


def _direction_keyword(node: ast.AST, callee_suffix: str) -> ast.expr:
    """The ``direction=`` value on the call whose target ends with `callee_suffix`."""
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if not isinstance(func, ast.Attribute) or func.attr != callee_suffix:
            continue
        for keyword in child.keywords:
            if keyword.arg == "direction":
                return keyword.value
    raise AssertionError(f"no direction= keyword on a .{callee_suffix}() call")


def test_fallback_uses_the_shared_helper_and_no_json_dumps() -> None:
    fallback = _find_function(_parse(_PLUGIN_PATH), "_fallback_pre_tool_call")
    calls = _called_names(fallback)

    assert calls.count("render_param_text") == 1
    assert "json.dumps" not in calls, "the fallback must not re-grow its own serialization"


def test_fallback_direction_is_the_shared_constant() -> None:
    fallback = _find_function(_parse(_PLUGIN_PATH), "_fallback_pre_tool_call")
    direction = _direction_keyword(fallback, "scan")

    assert isinstance(direction, ast.Name), "direction must be the constant, not a literal"
    assert direction.id == "PARAM_SCAN_DIRECTION"


def test_scan_params_uses_the_shared_helper_and_no_inline_serialization() -> None:
    scan_params = _find_function(_parse(_GUARD_PATH), "_scan_params")
    calls = _called_names(scan_params)

    assert calls.count("render_param_text") == 1
    assert "safe_json_dumps" not in calls, "serialization belongs to the helper alone"


def test_scan_params_direction_is_the_shared_constant() -> None:
    scan_params = _find_function(_parse(_GUARD_PATH), "_scan_params")
    direction = _direction_keyword(scan_params, "inspect")

    assert isinstance(direction, ast.Name), "direction must be the constant, not a literal"
    assert direction.id == "PARAM_SCAN_DIRECTION"


def test_scan_params_holds_no_cap_comparison() -> None:
    scan_params = _find_function(_parse(_GUARD_PATH), "_scan_params")

    for node in ast.walk(scan_params):
        if isinstance(node, ast.Compare):
            operands = [node.left, *node.comparators]
            names = {n.id for n in operands if isinstance(n, ast.Name)}
            assert "_MAX_PARAM_TEXT_LEN" not in names, "the cap belongs to the helper alone"


def test_the_cap_is_compared_in_exactly_one_place_and_it_is_the_helper() -> None:
    tree = _parse(_GUARD_PATH)
    helper = _find_function(tree, "render_param_text")
    helper_compares = {
        id(node)
        for node in ast.walk(helper)
        if isinstance(node, ast.Compare)
        and any(
            isinstance(n, ast.Name) and n.id == "_MAX_PARAM_TEXT_LEN"
            for n in [node.left, *node.comparators]
        )
    }
    module_compares = {
        id(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Compare)
        and any(
            isinstance(n, ast.Name) and n.id == "_MAX_PARAM_TEXT_LEN"
            for n in [node.left, *node.comparators]
        )
    }

    assert len(module_compares) == 1
    assert module_compares == helper_compares
