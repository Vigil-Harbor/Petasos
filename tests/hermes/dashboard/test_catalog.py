"""Settings read and preview, with no web framework and no Hermes home."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from petasos.hermes.dashboard.catalog import preview_settings, read_settings

if TYPE_CHECKING:
    from petasos._types import Scanner

_SECRETS = {"session_secret": "unset", "hash_key": "unset"}


def test_read_lists_roles_levels_and_resolved_rows() -> None:
    """A fresh document resolves, and every leaf says where its value came from."""
    body = read_settings({}, secrets=_SECRETS)
    assert body["version"] == 1
    assert body["stored"]["role"] == "general"
    assert body["stored"]["level"] == "balanced"
    assert body["valid"] is True
    assert [role["name"] for role in body["roles"]] == [
        "general",
        "coding",
        "research",
        "support",
        "admin",
    ]
    assert body["roles"][1]["suggests"] == "balanced"
    assert [level["name"] for level in body["levels"]] == ["relaxed", "balanced", "strict"]
    paths = [row["path"] for row in body["settings"]]
    assert paths[0] == "fail_mode"
    fail_mode = body["settings"][0]
    assert fail_mode["section"] == ""
    assert fail_mode["origin"] == "level"
    assert fail_mode["type"] == "choice"
    assert "degraded" in fail_mode["choices"]
    assert fail_mode["help"]
    sections = [row["path"] for row in body["sections"]]
    assert sections[0] == "normalization"
    assert "session_secret" not in body["stored"]
    assert body["secrets"] == _SECRETS


def test_a_secret_in_the_stored_document_is_not_returned() -> None:
    """The four settings are returned. A secret key on the same mapping is not."""
    body = read_settings(
        {"session_secret": "should-not-appear", "hash_key": "also-hidden", "role": "research"},
        secrets={"session_secret": "set", "hash_key": "unset"},
    )
    assert body["stored"] == {
        "enabled": True,
        "role": "research",
        "level": "balanced",
        "overrides": {},
    }
    assert body["secrets"]["session_secret"] == "set"
    assert "should-not-appear" not in str(body["stored"])


def test_invalid_settings_name_the_path_and_leave_the_rows() -> None:
    """A bad role does not resolve, and the screen still has the schema."""
    body = read_settings({"role": "nope"}, secrets=_SECRETS)
    assert body["valid"] is False
    assert body["problems"][0]["path"] == "role"
    assert "nope" in body["problems"][0]["message"]
    assert body["settings"][0]["value"] is None
    assert body["sections"]


def test_preview_shows_what_a_role_would_change() -> None:
    """Choosing coding, without saving, moves the rules the role owns."""
    body = preview_settings({}, {"role": "coding"})
    assert body["valid"] is True
    changed = {row["path"]: row for row in body["changes"]}
    assert changed["rules.suppress"]["origin_after"] == "role"
    assert changed["tools.dangerous_posture"]["after"] == "approve"
    assert body["stored"]["role"] == "coding"
    assert body["stored"]["overrides"] == {}


def test_preview_of_an_invalid_value_writes_nothing_and_names_the_path() -> None:
    """An override the schema rejects is a problem list, not a change list."""
    body = preview_settings({}, {"overrides": {"fail_mode": "wide-open"}})
    assert body["valid"] is False
    assert body["changes"] == []
    assert body["problems"][0]["path"].startswith("overrides")
    assert body["problems"][0]["message"]


def test_read_serves_labels_for_every_name_a_person_reads() -> None:
    """Rows, sections, roles, levels and the four stored settings each carry a plain label."""
    body = read_settings({}, secrets=_SECRETS)
    assert body["labels"] == {
        "enabled": "Protection",
        "role": "Job",
        "level": "Strictness",
        "overrides": "Your changes",
    }
    assert [role["label"] for role in body["roles"]][:2] == ["General", "Coding"]
    assert body["levels"][0]["label"] == "Relaxed"
    assert all(section["label"] for section in body["sections"])
    rows = {row["path"]: row for row in body["settings"]}
    posture = rows["tools.dangerous_posture"]
    assert posture["label"] == "When a dangerous action is found"
    assert posture["choice_labels"]["approve"] == "Ask a person for approval"
    assert rows["tools.exempt"]["choice_labels"] is None


def test_locked_settings_are_read_from_hermes_managed_keys() -> None:
    """Pinned keys under Petasos's settings are served read-only: the four, and leaves."""
    unknown = read_settings({}, secrets=_SECRETS)
    assert unknown["locked"] == {"known": False, "stored": [], "settings": [], "plugin": False}
    managed = frozenset(
        {
            "plugins.enabled",
            "plugins.entries.petasos.settings.level",
            "plugins.entries.petasos.settings.overrides.tools.exempt",
            "model.default",
        }
    )
    body = read_settings({}, secrets=_SECRETS, managed=managed)
    assert body["locked"] == {
        "known": True,
        "stored": ["level"],
        "settings": ["tools.exempt"],
        "plugin": True,
    }


def test_a_value_you_set_says_what_resetting_it_would_leave() -> None:
    """Reset names its destination: the value and the layer it comes from."""
    body = read_settings(
        {"role": "coding", "overrides": {"tools": {"dangerous_posture": "block"}}},
        secrets=_SECRETS,
    )
    rows = {row["path"]: row for row in body["settings"]}
    assert rows["tools.dangerous_posture"]["reset_to"] == {"value": "approve", "origin": "role"}
    assert "reset_to" not in rows["tools.exempt"]


def _absent_prompt_guard() -> tuple[object, ...]:
    from petasos.scanners.registry import REGISTRY, BuildContext, ScannerSpec

    def absent(section: Any, context: BuildContext) -> Scanner:
        raise ImportError("No module named 'transformers'")

    spec = next(item for item in REGISTRY if item.id == "prompt_guard")
    return (
        ScannerSpec(
            id=spec.id,
            label=spec.label,
            extra=spec.extra,
            detects=spec.detects,
            section=spec.section,
            default_enabled=spec.default_enabled,
            build=absent,
            purpose=spec.purpose,
        ),
    )


def test_making_a_missing_check_required_says_what_happens_before_save() -> None:
    """The preview computes the consequence from the candidate's own fail mode."""
    from petasos.hermes.dashboard.catalog import preview_settings

    registry = _absent_prompt_guard()
    required = {"overrides": {"scanners": {"prompt_guard": {"enabled": "on"}}}}
    body = preview_settings({}, required, registry=registry)  # type: ignore[arg-type]
    found = body["consequences"]["scanners.prompt_guard.enabled"]
    assert found["holds"] is True
    assert "blocked" in found["sentence"]
    opened = {"overrides": {"fail_mode": "open", "scanners": {"prompt_guard": {"enabled": "on"}}}}
    body = preview_settings({}, opened, registry=registry)  # type: ignore[arg-type]
    found = body["consequences"]["scanners.prompt_guard.enabled"]
    assert found["holds"] is False
    assert "blocked" not in found["sentence"]
    assert preview_settings({}, {}, registry=registry)["consequences"] == {}  # type: ignore[arg-type]


def test_a_mapping_setting_names_the_two_halves_of_an_entry() -> None:
    """The rows editor takes its field names from the schema, not from the tab."""
    from petasos.hermes.dashboard.catalog import read_settings

    rows = {row["path"]: row for row in read_settings({}, secrets={})["settings"]}
    assert rows["tools.aliases"]["entry_labels"] == ["Other name", "Real tool"]
    assert rows["rules.severity_overrides"]["entry_labels"] == ["Rule id", "Severity"]
    assert rows["tools.enabled"]["entry_labels"] is None
