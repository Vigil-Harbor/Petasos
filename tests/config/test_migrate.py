"""Migration of a flat petasos section into settings."""

from petasos.config.layers import resolve
from petasos.config.migrate import migrate

_PINNED_BLOCK = {"tools": {"dangerous_posture": "block"}}


def test_a_default_section_keeps_the_old_general_block() -> None:
    """Pin a default section keeps the old general block."""
    result = migrate({})

    assert result.settings["enabled"] is True
    assert result.settings["role"] == "general"
    assert result.settings["level"] == "balanced"
    assert result.settings["overrides"] == _PINNED_BLOCK
    assert result.dropped == ()
    assert "does not start asking" in result.notes[0]
    assert "tools.dangerous_posture" in result.notes[0]
    resolved = resolve(result.settings)
    assert resolved.config.fail_mode == "degraded"
    assert resolved.config.tools.dangerous_posture == "block"


def test_profile_names_become_roles() -> None:
    """Pin profile names become roles."""
    assert migrate({"profile_name": "code_generation"}).settings["role"] == "coding"
    assert migrate({"profile_name": "customer_service"}).settings["role"] == "support"
    assert migrate({"profile_name": None}).settings["role"] == "general"


def test_exact_level_values_become_that_level() -> None:
    """Pin exact level values become that level."""
    relaxed = migrate(
        {
            "fail_mode": "degraded",
            "tier1_threshold": 25,
            "tier2_threshold": 45,
            "tier3_threshold": 65,
            "presidio_score_threshold": 0.5,
            "anonymize": False,
        }
    )
    strict = migrate(
        {
            "fail_mode": "closed",
            "tier1_threshold": 10,
            "tier2_threshold": 22,
            "tier3_threshold": 40,
            "presidio_score_threshold": 0.3,
            "anonymize": True,
        }
    )

    assert relaxed.settings["level"] == "relaxed"
    assert relaxed.settings["overrides"] == _PINNED_BLOCK
    assert strict.settings["level"] == "strict"
    assert strict.settings["overrides"] == _PINNED_BLOCK


def test_unmatched_level_fields_become_overrides_on_balanced() -> None:
    """Pin unmatched level fields become overrides on balanced."""
    result = migrate({"fail_mode": "open", "tier1_threshold": 12})

    assert result.settings["level"] == "balanced"
    assert result.settings["overrides"]["fail_mode"] == "open"
    assert result.settings["overrides"]["escalation"]["tier1"] == 12.0
    resolved = resolve(result.settings)
    assert resolved.config.fail_mode == "open"
    assert resolved.config.escalation.tier1 == 12.0
    assert resolved.config.escalation.tier2 == 30.0


def test_profile_entities_union_with_an_explicit_extra_list() -> None:
    """Pin profile entities union with an explicit extra list."""
    result = migrate({"profile_name": "customer_service", "presidio_entities_extra": ["url"]})

    extra = result.settings["overrides"]["scanners"]["presidio"]["entities_extra"]
    assert extra == ["URL", "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER"]
    assert resolve(result.settings).config.scanners.presidio.entities_extra == tuple(extra)


def test_profile_entities_need_no_override_when_the_flat_list_is_absent() -> None:
    """Pin profile entities need no override when the flat list is absent."""
    result = migrate({"profile_name": "admin"})

    assert result.settings["overrides"] == {}
    assert resolve(result.settings).config.scanners.presidio.entities_extra == (
        "PERSON",
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "CREDIT_CARD",
        "IBAN_CODE",
    )


def test_research_and_admin_tiers_are_noted_and_not_copied() -> None:
    """Pin research and admin tiers are noted and not copied."""
    research = migrate({"profile_name": "research"})
    admin = migrate({"profile_name": "admin"})

    assert research.settings["level"] == "balanced"
    assert research.settings["overrides"] == {}
    assert "25, 45, 70" in research.notes[0]
    assert "relaxed" in research.notes[0]
    assert admin.settings["level"] == "balanced"
    assert "10, 20, 35" in admin.notes[0]
    assert "strict" in admin.notes[0]
    assert resolve(research.settings).config.escalation.tier3 == 50.0


def test_scanner_switches_and_removed_backends() -> None:
    """Pin scanner switches and removed backends."""
    result = migrate(
        {
            "disabled_scanners": ["prompt_guard", "llm_guard", "llama_firewall", "nope"],
            "semgrep_enabled": True,
        }
    )

    overrides = result.settings["overrides"]["scanners"]
    assert overrides["prompt_guard"]["enabled"] == "off"
    assert overrides["semgrep"]["enabled"] == "on"
    assert "presidio" not in overrides
    assert any("llm_guard was removed" in note for note in result.notes)
    assert any("llama_firewall was removed" in note for note in result.notes)
    assert any("nope" in note for note in result.notes)
    assert resolve(result.settings).config.scanners.semgrep.enabled == "on"


def test_disabled_wins_when_semgrep_is_also_enabled() -> None:
    """Pin disabled wins when semgrep is also enabled."""
    result = migrate({"disabled_scanners": ["semgrep"], "semgrep_enabled": True})

    assert result.settings["overrides"] == _PINNED_BLOCK
    assert resolve(result.settings).config.scanners.semgrep.enabled == "off"
    assert any("disabled wins" in note for note in result.notes)


def test_secrets_unknown_keys_and_inert_flags_are_not_copied() -> None:
    """Pin secrets unknown keys and inert flags are not copied."""
    secret = "hash-key-value"
    session = "session-secret-value"
    result = migrate(
        {
            "hash_key": secret,
            "session_secret": session,
            "host_id": "hermes-gavin-01",
            "detect_rtl_override": False,
            "fold_leet": False,
            "not_a_field": 1,
        }
    )
    rendered = repr(result)

    assert result.settings["overrides"] == _PINNED_BLOCK
    assert result.dropped == (
        "hash_key",
        "session_secret",
        "host_id",
        "detect_rtl_override",
        "fold_leet",
        "not_a_field",
    )
    assert secret not in rendered
    assert session not in rendered
    assert any("PETASOS_HASH_KEY" in note for note in result.notes)
    assert any("PETASOS_SESSION_SECRET" in note for note in result.notes)
    assert any("host_id" in note for note in result.notes)
    assert any("detect_rtl_override" in note for note in result.notes)
    assert any("fold_leet" in note for note in result.notes)
    assert any("not_a_field" in note for note in result.notes)


def test_integer_frequency_weights_become_floats() -> None:
    """Pin integer frequency weights become floats."""
    result = migrate({"frequency_weights": {"petasos.syntactic.command.*": 3}})

    weights = result.settings["overrides"]["frequency"]["weights"]
    assert weights == {"petasos.syntactic.command.*": 3.0}
    resolved = resolve(result.settings).config.frequency.weights
    assert resolved is not None
    assert resolved["petasos.syntactic.command.*"] == 3.0


def test_disabling_semgrep_matches_the_default() -> None:
    """Pin disabling semgrep matches the default."""
    result = migrate({"semgrep_enabled": False})

    assert result.settings["overrides"] == _PINNED_BLOCK
    assert any("does not start asking" in note for note in result.notes)
    assert resolve(result.settings).config.scanners.semgrep.enabled == "off"


def test_an_explicit_null_is_carried_into_overrides() -> None:
    """Pin an explicit null is carried into overrides."""
    result = migrate({"anonymize": None})

    assert result.settings["overrides"]["anonymization"]["enabled"] is None
    assert result.dropped == ()


def test_unknown_profile_is_dropped_and_names_the_roles() -> None:
    """Pin unknown profile is dropped and names the roles."""
    result = migrate({"profile_name": "night_watch"})

    assert result.settings["role"] == "general"
    assert result.settings["overrides"] == _PINNED_BLOCK
    assert "profile_name" in result.dropped
    assert "night_watch" in result.notes[0]
    assert "code_generation" in result.notes[0]
    assert any("does not start asking" in note for note in result.notes)


def test_an_old_general_profile_is_pinned_to_block_and_says_why() -> None:
    """Pin an old general profile is pinned to block and says why."""
    result = migrate({"profile_name": "general"})

    assert result.settings["role"] == "general"
    assert result.settings["overrides"] == _PINNED_BLOCK
    assert resolve(result.settings).config.tools.dangerous_posture == "block"
    assert "old profile blocked" in result.notes[0]
    assert "does not start asking" in result.notes[0]


def test_a_named_posture_is_kept() -> None:
    """Pin a named posture is kept."""
    blocked = migrate({"profile_name": "general", "dangerous_tool_posture": "block"})
    asked = migrate({"profile_name": "general", "dangerous_tool_posture": "approve"})
    coding = migrate({"profile_name": "code_generation", "dangerous_tool_posture": "block"})

    assert blocked.settings["overrides"] == _PINNED_BLOCK
    assert blocked.notes == ()
    assert asked.settings["overrides"] == {}
    assert asked.notes == ()
    assert resolve(asked.settings).config.tools.dangerous_posture == "approve"
    assert coding.settings["overrides"] == _PINNED_BLOCK
    assert coding.notes == ()
    assert resolve(coding.settings).config.tools.dangerous_posture == "block"
