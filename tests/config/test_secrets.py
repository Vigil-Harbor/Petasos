"""Secrets stay beside the config and never render a value."""

import pytest

from petasos.config.schema import from_mapping
from petasos.config.secrets import Secrets, require_hash_key
from petasos.config.sections import PetasosConfig
from petasos.pipeline import Pipeline

_HASH_KEY_MESSAGE = (
    "hash_key is required and must be non-empty when redaction_mode='hash' and anonymize=True"
)


def test_repr_names_presence_and_hides_values() -> None:
    """Pin repr names presence and hides values."""
    secret = b"session-secret-value"
    key = "hash-key-value"
    hidden = Secrets(session_secret=secret, hash_key=key)

    text = repr(hidden)

    assert text == "Secrets(session_secret=set, hash_key=set)"
    assert "session-secret-value" not in text
    assert "hash-key-value" not in text
    assert repr(Secrets()) == "Secrets(session_secret=unset, hash_key=unset)"


def test_secrets_have_no_mapping_export() -> None:
    """Pin secrets have no mapping export."""
    assert not hasattr(Secrets, "to_mapping")
    assert "to_mapping" not in dir(Secrets(session_secret=b"x"))


def test_hash_mode_without_a_key_is_rejected_where_config_meets_secrets() -> None:
    """Pin hash mode without a key is rejected where config meets secrets."""
    config = from_mapping(PetasosConfig, {"anonymization": {"enabled": True, "mode": "hash"}})

    with pytest.raises(ValueError, match=_HASH_KEY_MESSAGE):
        require_hash_key(config, Secrets())
    with pytest.raises(ValueError, match=_HASH_KEY_MESSAGE):
        require_hash_key(config, Secrets(hash_key=""))
    require_hash_key(config, Secrets(hash_key="k"))

    with pytest.raises(ValueError, match=_HASH_KEY_MESSAGE):
        Pipeline(config=config)
    pipeline = Pipeline(secrets=Secrets())
    with pytest.raises(ValueError, match=_HASH_KEY_MESSAGE):
        pipeline.reconfigure(config)
    assert pipeline.config.anonymization.mode != "hash"
