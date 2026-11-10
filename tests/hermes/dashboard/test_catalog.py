"""Settings read and preview, with no web framework and no Hermes home."""

from __future__ import annotations

from petasos.hermes.dashboard.catalog import preview_settings, read_settings

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
