"""Secrets stay beside the config and never render a value."""

from petasos.config.secrets import Secrets


def test_repr_names_presence_and_hides_values() -> None:
    secret = b"session-secret-value"
    key = "hash-key-value"
    hidden = Secrets(session_secret=secret, hash_key=key)

    text = repr(hidden)

    assert text == "Secrets(session_secret=set, hash_key=set)"
    assert "session-secret-value" not in text
    assert "hash-key-value" not in text
    assert repr(Secrets()) == "Secrets(session_secret=unset, hash_key=unset)"


def test_secrets_have_no_mapping_export() -> None:
    assert not hasattr(Secrets, "to_mapping")
    assert "to_mapping" not in dir(Secrets(session_secret=b"x"))
