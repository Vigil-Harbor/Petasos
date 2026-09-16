from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from petasos.session._safe_json import safe_json_dumps


class TestSafeJsonDumps:
    def test_normal_dict(self) -> None:
        d = {"key": "value", "nested": {"a": 1}}
        result = safe_json_dumps(d)
        parsed = json.loads(result)
        assert parsed == d

    def test_circular_dict(self) -> None:
        d: dict[str, object] = {}
        d["self"] = d
        result = safe_json_dumps(d)
        assert "[Circular]" in result
        assert isinstance(result, str)

    def test_circular_list(self) -> None:
        a: list[object] = []
        a.append(a)
        result = safe_json_dumps(a)
        assert "[Circular]" in result
        assert isinstance(result, str)

    def test_depth_limit(self) -> None:
        d: dict[str, object] = {"leaf": True}
        for _ in range(50):
            d = {"child": d}
        result = safe_json_dumps(d, max_depth=10)
        assert "[Depth limit]" in result

    def test_unserializable_type(self) -> None:
        # Regression for PET-197: placeholder only when __str__ raises.
        class RaisingStr:
            def __str__(self) -> str:
                raise RuntimeError("boom")

        result = safe_json_dumps({"obj": RaisingStr()})
        assert "[Unserializable: RaisingStr]" in result

    def test_bytes_contributes_text(self) -> None:
        # Regression for PET-197: bytes leaves contribute str() text, not a type placeholder.
        phrase = "ignore all previous instructions"
        payload = phrase.encode("ascii")
        top = safe_json_dumps(payload)
        nested = safe_json_dumps({"payload": payload})
        assert phrase in top
        assert phrase in nested
        assert "[Unserializable" not in top
        assert "[Unserializable" not in nested

    def test_path_contributes_text(self) -> None:
        # Regression for PET-197: Path leaves contribute str() text.
        path = Path("secret-dir") / "payload.txt"
        result = safe_json_dumps(path)
        assert "payload.txt" in result
        assert "[Unserializable" not in result

    def test_datetime_contributes_text(self) -> None:
        # Regression for PET-197: datetime leaves contribute str() text.
        result = safe_json_dumps(datetime(2026, 9, 15, 12, 0, 0))
        assert "2026" in result
        assert "15" in result
        assert "[Unserializable" not in result

    def test_huge_str_hits_max_size(self) -> None:
        # Regression for PET-197: a huge __str__ is still sliced by max_size.
        class HugeStr:
            def __str__(self) -> str:
                return "x" * 2_000_000

        result = safe_json_dumps(HugeStr(), max_size=1_000_000)
        assert result.endswith("...[truncated]")
        assert len(result) <= 1_000_000 + len("...[truncated]")

    def test_size_cap(self) -> None:
        big = {"data": "x" * 2_000_000}
        result = safe_json_dumps(big, max_size=1_000_000)
        assert result.endswith("...[truncated]")
        assert len(result) <= 1_000_000 + len("...[truncated]")

    def test_dag_shared_node_not_circular(self) -> None:
        shared: dict[str, int] = {"x": 1}
        d = {"a": shared, "b": shared}
        result = safe_json_dumps(d)
        assert "[Circular]" not in result
        parsed = json.loads(result)
        assert parsed["a"] == parsed["b"] == {"x": 1}

    def test_mixed_types(self) -> None:
        d = {
            "string": "hello",
            "int": 42,
            "float": 3.14,
            "bool": True,
            "none": None,
            "list": [1, "two", False],
            "nested": {"a": [1, 2]},
        }
        result = safe_json_dumps(d)
        parsed = json.loads(result)
        assert parsed == d

    def test_never_throws(self) -> None:
        class BadIter:
            def __iter__(self) -> BadIter:
                raise RuntimeError("boom")

        result = safe_json_dumps({"bad": BadIter()})
        assert isinstance(result, str)
