"""Migration of a flat petasos section into settings."""

from petasos.config.layers import resolve
from petasos.config.migrate import migrate


def test_a_default_section_has_empty_overrides() -> None:
    result = migrate({})

    assert result.settings["enabled"] is True
    assert result.settings["role"] == "general"
    assert result.settings["level"] == "balanced"
    assert result.settings["overrides"] == {}
    assert result.dropped == ()
    assert result.notes == ()
    assert resolve(result.settings).config.fail_mode == "degraded"


def test_profile_names_become_roles() -> None:
    assert migrate({"profile_name": "code_generation"}).settings["role"] == "coding"
    assert migrate({"profile_name": "customer_service"}).settings["role"] == "support"
    assert migrate({"profile_name": None}).settings["role"] == "general"


def test_exact_level_values_become_that_level() -> None:
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
    assert relaxed.settings["overrides"] == {}
    assert strict.settings["level"] == "strict"
    assert strict.settings["overrides"] == {}


def test_unmatched_level_fields_become_overrides_on_balanced() -> None:
    result = migrate({"fail_mode": "open", "tier1_threshold": 12})

    assert result.settings["level"] == "balanced"
    assert result.settings["overrides"]["fail_mode"] == "open"
    assert result.settings["overrides"]["escalation"]["tier1"] == 12.0
    resolved = resolve(result.settings)
    assert resolved.config.fail_mode == "open"
    assert resolved.config.escalation.tier1 == 12.0
    assert resolved.config.escalation.tier2 == 30.0


def test_profile_entities_union_with_an_explicit_extra_list() -> None:
    result = migrate({"profile_name": "customer_service", "presidio_entities_extra": ["url"]})

    extra = result.settings["overrides"]["scanners"]["presidio"]["entities_extra"]
    assert extra == ["URL", "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER"]
    assert resolve(result.settings).config.scanners.presidio.entities_extra == tuple(extra)


def test_profile_entities_need_no_override_when_the_flat_list_is_absent() -> None:
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
    result = migrate({"disabled_scanners": ["semgrep"], "semgrep_enabled": True})

    assert result.settings["overrides"] == {}
    assert resolve(result.settings).config.scanners.semgrep.enabled == "off"
    assert any("disabled wins" in note for note in result.notes)


def test_secrets_unknown_keys_and_inert_flags_are_not_copied() -> None:
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

    assert result.settings["overrides"] == {}
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
    result = migrate({"frequency_weights": {"petasos.syntactic.command.*": 3}})

    weights = result.settings["overrides"]["frequency"]["weights"]
    assert weights == {"petasos.syntactic.command.*": 3.0}
    resolved = resolve(result.settings).config.frequency.weights
    assert resolved is not None
    assert resolved["petasos.syntactic.command.*"] == 3.0


def test_disabling_semgrep_matches_the_default() -> None:
    result = migrate({"semgrep_enabled": False})

    assert result.settings["overrides"] == {}
    assert result.notes == ()
    assert resolve(result.settings).config.scanners.semgrep.enabled == "off"


def test_an_explicit_null_is_carried_into_overrides() -> None:
    result = migrate({"anonymize": None})

    assert result.settings["overrides"]["anonymization"]["enabled"] is None
    assert result.dropped == ()


def test_unknown_profile_is_dropped_and_names_the_roles() -> None:
    result = migrate({"profile_name": "night_watch"})

    assert result.settings["role"] == "general"
    assert "profile_name" in result.dropped
    assert "night_watch" in result.notes[0]
    assert "code_generation" in result.notes[0]
