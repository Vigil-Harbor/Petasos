"""The temporary bridge: old configs and profiles become the config tree."""

from __future__ import annotations

import logging

import pytest

from petasos import PetasosConfig, ProfileResolver
from petasos.config.legacy import (
    PROFILE_WITH_TREE,
    bind,
    preserved_flat,
    require_hash_key,
)
from petasos.config.schema import to_mapping
from petasos.config.secrets import Secrets
from petasos.config.sections import PetasosConfig as TreeConfig

_PROFILES = ("general", "code_generation", "research", "customer_service", "admin")


def test_default_flat_config_matches_the_default_tree() -> None:
    bound = bind(None)

    assert bound.config == TreeConfig()
    assert bound.legacy == PetasosConfig()
    assert bound.profile is None
    assert bound.secrets == Secrets()


@pytest.mark.parametrize("name", _PROFILES)
def test_each_profile_copies_levers_and_not_tier_thresholds(name: str) -> None:
    profile = ProfileResolver().resolve(name)
    bound = bind(PetasosConfig(), name)

    assert bound.profile == profile
    assert set(bound.config.rules.suppress) == set(profile.suppress_rules)
    assert dict(bound.config.rules.severity_overrides) == dict(profile.severity_overrides)
    assert bound.config.rules.confidence_floor == profile.confidence_floor
    assert bound.config.rules.injection_floor_scope == profile.injection_floor_scope
    assert bound.config.tools.dangerous_posture == profile.dangerous_tool_posture
    assert set(bound.config.tools.exempt) == set(profile.tool_exempt_list)
    assert dict(bound.config.tools.aliases) == dict(profile.tool_alias_map)
    assert bound.config.escalation.tier1 == 15.0
    assert bound.config.escalation.tier2 == 30.0
    assert bound.config.escalation.tier3 == 50.0


def test_profile_forms_and_profile_name(caplog: pytest.LogCaptureFixture) -> None:
    resolved = ProfileResolver().resolve("research")
    by_name = bind(PetasosConfig(), "research")
    by_object = bind(PetasosConfig(), resolved)
    by_field = bind(PetasosConfig(profile_name="research"))
    custom = bind(
        PetasosConfig(),
        {
            "suppress_rules": ["petasos.syntactic.structural.excessive-depth"],
            "pii_entities_extra": ["NOT_A_TYPE", "URL"],
            "confidence_floor": 2.5,
            "tool_exempt_list": ["Read"],
            "tool_alias_map": {"Bash": "exec"},
        },
    )

    assert by_name.config == by_object.config == by_field.config
    assert custom.config.rules.suppress == ()
    assert custom.config.rules.confidence_floor == 1.0
    assert custom.config.scanners.presidio.entities_extra == ("URL",)
    assert custom.config.tools.exempt == ("read",)
    assert custom.config.tools.aliases["Bash"] == "exec"
    assert "excessive-depth" in caplog.text
    assert "NOT_A_TYPE" in caplog.text


def test_tree_plus_profile_is_rejected() -> None:
    with pytest.raises(ValueError, match=PROFILE_WITH_TREE):
        bind(TreeConfig(), "admin")


def test_secrets_are_extracted_and_never_rendered() -> None:
    secret = b"session-secret"
    bound = bind(PetasosConfig(session_secret=secret, hash_key="hash-secret"))
    rendered = repr(bound.secrets)
    mapped = str(to_mapping(bound.config))

    assert bound.secrets.session_secret == secret
    assert bound.secrets.hash_key == "hash-secret"
    assert "session-secret" not in rendered
    assert "hash-secret" not in rendered
    assert "session_secret" not in mapped
    assert "hash_key" not in mapped
    explicit = bind(PetasosConfig(hash_key="from-config"), secrets=Secrets(hash_key="explicit"))
    assert explicit.secrets.hash_key == "explicit"


def test_bad_weights_raise_the_tracker_error() -> None:
    with pytest.raises(ValueError, match="non-terminal"):
        bind(PetasosConfig(frequency_weights={"a.*.b": 1.0}))
    with pytest.raises(ValueError, match="non-negative"):
        bind(PetasosConfig(frequency_weights={"x": -1.0}))


def test_unknown_presidio_entities_do_not_reject_the_tree() -> None:
    bound = bind(PetasosConfig(presidio_entities=("NOT_A_TYPE", "EMAIL_ADDRESS")))

    assert bound.config.scanners.presidio.entities == ("EMAIL_ADDRESS",)
    assert bound.legacy is not None
    assert bound.legacy.presidio_entities == ("NOT_A_TYPE", "EMAIL_ADDRESS")


def test_hash_mode_needs_a_key_where_config_meets_secrets() -> None:
    tree = TreeConfig(anonymization={"enabled": True, "mode": "hash"})  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="hash_key is required"):
        require_hash_key(tree, Secrets())
    require_hash_key(tree, Secrets(hash_key="k"))


def test_preserved_flat_keeps_semgrep_and_the_live_secret() -> None:
    live = PetasosConfig(session_secret=b"live", semgrep_enabled=True, fail_mode="degraded")
    incoming = PetasosConfig(
        session_secret=b"next",
        semgrep_enabled=False,
        semgrep_request_timeout_seconds=2,
        fail_mode="open",
        disabled_scanners=("prompt_guard", "semgrep"),
    )

    kept = preserved_flat(live, incoming)

    assert kept.session_secret == b"live"
    assert kept.semgrep_enabled is True
    assert kept.semgrep_request_timeout_seconds == 8
    assert kept.fail_mode == "open"
    assert "prompt_guard" in kept.disabled_scanners
    assert "semgrep" not in kept.disabled_scanners


def test_logging_level_is_warning_for_the_strip(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="petasos.session.profiles"):
        bind(
            PetasosConfig(),
            {"suppress_rules": ["petasos.syntactic.structural.excessive-depth"]},
        )
    assert any("stripped" in record.getMessage() for record in caplog.records)
