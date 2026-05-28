"""PROF-02 regression: retained dict ref must not mutate ResolvedProfile."""

from __future__ import annotations

from petasos.premium.profiles import _parse_profile


def test_severity_overrides_not_mutated_by_caller() -> None:
    data: dict = {
        "name": "test",
        "severity_overrides": {"SYN-001": "high"},
    }
    profile = _parse_profile(data)
    data["severity_overrides"]["SYN-001"] = "info"
    data["severity_overrides"]["SYN-002"] = "low"
    assert profile.severity_overrides["SYN-001"] == "high"
    assert "SYN-002" not in profile.severity_overrides


def test_tool_alias_map_not_mutated_by_caller() -> None:
    data: dict = {
        "name": "test",
        "tool_alias_map": {"read_file": "file_read"},
    }
    profile = _parse_profile(data)
    data["tool_alias_map"]["read_file"] = "evil_read"
    data["tool_alias_map"]["new_tool"] = "smuggled"
    assert profile.tool_alias_map["read_file"] == "file_read"
    assert "new_tool" not in profile.tool_alias_map


def test_empty_overrides_not_shared() -> None:
    data_a: dict = {"name": "a"}
    data_b: dict = {"name": "b"}
    prof_a = _parse_profile(data_a)
    prof_b = _parse_profile(data_b)
    assert prof_a.severity_overrides is not prof_b.severity_overrides
