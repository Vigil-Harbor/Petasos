from __future__ import annotations

import json

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
        result = safe_json_dumps({"obj": object()})
        assert "[Unserializable" in result

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
