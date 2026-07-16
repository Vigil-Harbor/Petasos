"""Shape/static tests pinning the selfmod floor (PET-164 Decision 12)."""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "petasos"


def _parse_function(
    filepath: Path,
    func_name: str,
) -> ast.FunctionDef | ast.AsyncFunctionDef:
    """Parse a file and return the named function's AST node."""
    tree = ast.parse(filepath.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            return node
    raise ValueError(f"{func_name} not found in {filepath}")


def _find_method_in_class(
    filepath: Path,
    class_name: str,
    method_name: str,
) -> ast.FunctionDef | ast.AsyncFunctionDef:
    tree = ast.parse(filepath.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if (
                    isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and item.name == method_name
                ):
                    return item
    raise ValueError(f"{class_name}.{method_name} not found in {filepath}")


class TestRecordSelfmodShape:
    """Pin 1: record_selfmod has exactly one config gate: _is_enabled("audit")."""

    def test_single_is_enabled_gate(self) -> None:
        func = _find_method_in_class(
            _SRC / "pipeline.py",
            "Pipeline",
            "record_selfmod",
        )
        source = ast.dump(func)
        count = source.count("_is_enabled")
        assert count == 1, f"expected exactly 1 _is_enabled call, found {count}"

    def test_is_enabled_audit_only(self) -> None:
        func = _find_method_in_class(
            _SRC / "pipeline.py",
            "Pipeline",
            "record_selfmod",
        )
        calls = [
            node
            for node in ast.walk(func)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_is_enabled"
        ]
        assert len(calls) == 1
        arg = calls[0].args[0]
        assert isinstance(arg, ast.Constant) and arg.value == "audit"


class TestGuardSelfmodWeightShape:
    """Pin 2: _record_selfmod_weight uses requires_token, not session_secret config-if."""

    def test_uses_requires_token(self) -> None:
        func = _find_method_in_class(
            _SRC / "session" / "guard.py",
            "ToolCallGuard",
            "_record_selfmod_weight",
        )
        source = ast.dump(func)
        assert "requires_token" in source

    def test_no_session_secret_if(self) -> None:
        func = _find_method_in_class(
            _SRC / "session" / "guard.py",
            "ToolCallGuard",
            "_record_selfmod_weight",
        )
        source = ast.dump(func)
        assert "session_secret" not in source


class TestEvaluateSelfmodShape:
    """Pin 3: evaluate_selfmod contains 'critical' and no _rule_cooldowns access."""

    def test_contains_critical_literal(self) -> None:
        func = _find_method_in_class(
            _SRC / "session" / "alerting.py",
            "AlertManager",
            "evaluate_selfmod",
        )
        source = ast.dump(func)
        assert "'critical'" in source or '"critical"' in source or "critical" in source

    def test_no_rule_cooldowns_access(self) -> None:
        func = _find_method_in_class(
            _SRC / "session" / "alerting.py",
            "AlertManager",
            "evaluate_selfmod",
        )
        source = ast.dump(func)
        assert "_rule_cooldowns" not in source


class TestFrequencyFloorLiterals:
    """Pin 4: inline floor literals in _match_weight."""

    def test_config_write_floor(self) -> None:
        func = _find_method_in_class(
            _SRC / "session" / "frequency.py",
            "FrequencyTracker",
            "_match_weight",
        )
        source = ast.get_source_segment(
            (_SRC / "session" / "frequency.py").read_text(encoding="utf-8"), func
        )
        assert source is not None
        assert "10.0" in source
        assert "petasos.selfmod.config_write" in source

    def test_config_ref_floor(self) -> None:
        func = _find_method_in_class(
            _SRC / "session" / "frequency.py",
            "FrequencyTracker",
            "_match_weight",
        )
        source = ast.get_source_segment(
            (_SRC / "session" / "frequency.py").read_text(encoding="utf-8"), func
        )
        assert source is not None
        assert "3.0" in source
        assert "petasos.selfmod.config_ref" in source


class TestNoSelfmodConfigField:
    """Pin 5: no field containing 'selfmod' in PetasosConfig."""

    def test_no_selfmod_in_config(self) -> None:
        tree = ast.parse((_SRC / "config.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "PetasosConfig":
                for item in node.body:
                    if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                        assert "selfmod" not in item.target.id.lower(), (
                            f"PetasosConfig has a field containing 'selfmod': {item.target.id}"
                        )

    def test_no_selfmod_in_field_meta(self) -> None:
        source = (_SRC / "console" / "_config_meta.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and "selfmod" in node.value.lower()
            ):
                msg = f"_config_meta.py contains a selfmod-related string: {node.value!r}"
                raise AssertionError(msg)
