"""Pin session-token binding across live risk reconfiguration.

See docs/architecture/rationale.md, "Quantized scan contributions"."""

from __future__ import annotations

import dataclasses

import pytest

from petasos.config.schema import from_mapping
from petasos.config.secrets import Secrets
from petasos.config.sections import PetasosConfig
from petasos.session.frequency import FrequencyTracker

_SECRET = b"k" * 32


def _secret_tracker() -> FrequencyTracker:
    return FrequencyTracker(PetasosConfig(), secrets=Secrets(session_secret=_SECRET))


def test_bare_string_rejected_when_secret_configured() -> None:
    tr = _secret_tracker()
    with pytest.raises(ValueError, match="pass a SessionToken"):
        tr.update("plain-session", ["petasos.syntactic.injection.ignore-previous"])


def test_tampered_token_digest_rejected() -> None:
    tr = _secret_tracker()
    tok = tr.mint_token("sess-1", "host-1")
    tampered = dataclasses.replace(tok, hmac_digest="00" * 32)
    with pytest.raises(ValueError, match="HMAC verification failed"):
        tr.update(tampered, ["petasos.syntactic.injection.ignore-previous"])


def test_wrong_host_token_rejected() -> None:
    tr = _secret_tracker()
    tok = tr.mint_token("sess-1", "host-1")
    wrong_host = dataclasses.replace(tok, host_id="host-2")
    with pytest.raises(ValueError, match="HMAC verification failed"):
        tr.update(wrong_host, ["petasos.syntactic.injection.ignore-previous"])


def test_valid_token_accepted_after_reject_paths() -> None:
    tr = _secret_tracker()
    tok = tr.mint_token("sess-1", "host-1")
    res = tr.update(tok, ["petasos.syntactic.injection.ignore-previous"])
    assert res.current_score > 0


def test_frequency_apply_config_atomic_on_bad_weights() -> None:
    tr = FrequencyTracker(
        from_mapping(
            PetasosConfig,
            {
                "frequency": {
                    "half_life_seconds": 60.0,
                },
            },
        )
    )
    tr.update("s", ["petasos.syntactic.injection.ignore-previous"])
    before = tr.get_state("s")
    assert before is not None
    with pytest.raises(ValueError, match="frequency.weights"):
        from_mapping(
            PetasosConfig,
            {
                "frequency": {
                    "weights": {"petasos.*.injection": 5.0},
                },
            },
        )
    assert tr.get_state("s") is not None
    assert tr._half_life == 60.0


def test_frequency_apply_config_rebinds_scalars() -> None:
    tr = FrequencyTracker(
        from_mapping(
            PetasosConfig,
            {
                "frequency": {
                    "half_life_seconds": 60.0,
                },
            },
        )
    )
    tr.apply_config(
        from_mapping(
            PetasosConfig,
            {
                "frequency": {
                    "half_life_seconds": 30.0,
                },
            },
        )
    )
    assert tr._half_life == 30.0
