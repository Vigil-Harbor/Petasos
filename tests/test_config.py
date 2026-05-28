from __future__ import annotations

import dataclasses

import pytest

from petasos.config import PetasosConfig


class TestConfigDefaults:
    def test_default_construction(self) -> None:
        cfg = PetasosConfig()
        assert cfg.direction == "inbound"
        assert cfg.fail_mode == "degraded"
        assert cfg.anonymize is False
        assert cfg.pii_entities == ()
        assert cfg.redaction_mode == "redact"
        assert cfg.hash_key is None

    def test_premium_stubs_default_disabled(self) -> None:
        cfg = PetasosConfig()
        assert cfg.frequency_enabled is False
        assert cfg.escalation_enabled is False
        assert cfg.profile_name is None
        assert cfg.tool_guard_enabled is False
        assert cfg.audit_enabled is False
        assert cfg.alert_enabled is False

    def test_normalization_toggles_default_true(self) -> None:
        cfg = PetasosConfig()
        assert cfg.normalize_nfkc is True
        assert cfg.strip_zero_width is True
        assert cfg.map_homoglyphs is True
        assert cfg.detect_rtl_override is True


class TestConfigValidation:
    def test_rejects_invalid_direction(self) -> None:
        with pytest.raises(ValueError, match="direction"):
            PetasosConfig(direction="sideways")  # type: ignore[arg-type]

    def test_rejects_invalid_fail_mode(self) -> None:
        with pytest.raises(ValueError, match="fail_mode"):
            PetasosConfig(fail_mode="unknown")  # type: ignore[arg-type]

    def test_rejects_invalid_redaction_mode(self) -> None:
        with pytest.raises(ValueError, match="redaction_mode"):
            PetasosConfig(redaction_mode="scramble")  # type: ignore[arg-type]

    def test_requires_hash_key_for_hash_mode(self) -> None:
        with pytest.raises(ValueError, match="hash_key"):
            PetasosConfig(anonymize=True, redaction_mode="hash")

    def test_hash_mode_without_anonymize_ok(self) -> None:
        cfg = PetasosConfig(anonymize=False, redaction_mode="hash")
        assert cfg.redaction_mode == "hash"

    def test_rejects_empty_pii_entity(self) -> None:
        with pytest.raises(ValueError, match="pii_entities"):
            PetasosConfig(pii_entities=("PERSON", ""))


class TestConfigSerialization:
    def test_round_trip(self) -> None:
        cfg = PetasosConfig(
            direction="outbound",
            fail_mode="closed",
            anonymize=True,
            redaction_mode="replace",
            pii_entities=("PERSON", "EMAIL"),
        )
        d = cfg.to_dict()
        restored = PetasosConfig.from_dict(d)
        assert restored == cfg

    def test_to_dict_converts_tuples_to_lists(self) -> None:
        cfg = PetasosConfig(pii_entities=("PERSON",))
        d = cfg.to_dict()
        assert isinstance(d["pii_entities"], list)

    def test_from_dict_partial_fills_defaults(self) -> None:
        cfg = PetasosConfig.from_dict({"direction": "outbound"})
        assert cfg.direction == "outbound"
        assert cfg.fail_mode == "degraded"

    def test_from_dict_ignores_extra_keys(self) -> None:
        cfg = PetasosConfig.from_dict({"direction": "inbound", "unknown_field": 42})
        assert cfg.direction == "inbound"

    def test_empty_pii_entities_valid(self) -> None:
        cfg = PetasosConfig(pii_entities=())
        assert cfg.pii_entities == ()


class TestSessionSecret:
    def test_from_dict_session_secret_base64(self) -> None:
        import base64

        secret = b"my-secret"
        encoded = base64.b64encode(secret).decode()
        cfg = PetasosConfig.from_dict({"session_secret": encoded})
        assert cfg.session_secret == secret

    def test_to_dict_excludes_session_secret(self) -> None:
        cfg = PetasosConfig(session_secret=b"key")
        d = cfg.to_dict()
        assert "session_secret" not in d


class TestConfigFrozen:
    def test_frozen_prevents_mutation(self) -> None:
        cfg = PetasosConfig()
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.direction = "outbound"  # type: ignore[misc]
