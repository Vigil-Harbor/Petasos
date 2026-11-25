"""Pin authenticated session updates against spoofing and score inflation."""

from __future__ import annotations

import pytest

from petasos.config.secrets import Secrets
from petasos.config.sections import PetasosConfig
from petasos.session.frequency import FrequencyTracker, SessionToken

_SECRET = b"test-secret-key-32-bytes-long!!!"
_HOST = "host-a"


def _tracker() -> FrequencyTracker:
    return FrequencyTracker(PetasosConfig(), secrets=Secrets(session_secret=_SECRET))


def _mint(tracker: FrequencyTracker, session_id: str = "s1") -> SessionToken:
    return tracker.mint_token(session_id, _HOST)


def test_spoofed_session_id_rejected() -> None:
    """Pin spoofed session id rejected."""
    tracker = _tracker()
    forged = SessionToken(session_id="s1", host_id=_HOST, hmac_digest="bad-digest")
    with pytest.raises(ValueError, match="HMAC verification failed"):
        tracker.update(forged, ["petasos.syntactic.injection.ignore-previous"])


def test_inflated_score_blocked() -> None:
    """Pin inflated score blocked."""
    tracker = _tracker()
    victim_token = _mint(tracker, "victim")
    tracker.update(victim_token, [])

    attacker_forged = SessionToken(
        session_id="victim", host_id="attacker-host", hmac_digest="forged"
    )
    with pytest.raises(ValueError, match="HMAC verification failed"):
        tracker.update(attacker_forged, ["petasos.syntactic.injection.ignore-previous"] * 50)

    state = tracker.get_state(victim_token)
    assert state is not None
    assert state.last_score == 0.0


def test_reset_requires_valid_token() -> None:
    """Pin reset requires valid token."""
    tracker = _tracker()
    valid = _mint(tracker, "s1")
    tracker.update(valid, ["petasos.syntactic.injection.ignore-previous"])

    wrong_host = SessionToken(session_id="s1", host_id="evil-host", hmac_digest="wrong")
    with pytest.raises(ValueError, match="HMAC verification failed"):
        tracker.reset(wrong_host)

    state = tracker.get_state(valid)
    assert state is not None
    assert state.last_score > 0


def test_terminate_requires_valid_token() -> None:
    """Pin terminate requires valid token."""
    tracker = _tracker()
    valid = _mint(tracker, "s1")
    tracker.update(valid, [])

    spoofed = SessionToken(session_id="s1", host_id=_HOST, hmac_digest="spoofed")
    with pytest.raises(ValueError, match="HMAC verification failed"):
        tracker.terminate_session(spoofed)

    state = tracker.get_state(valid)
    assert state is not None
    assert not state.terminated


def test_eviction_flood_with_tokens() -> None:
    """Pin eviction flood with tokens."""
    tracker = _tracker()
    legit = _mint(tracker, "legit")
    tracker.update(legit, [])

    for i in range(100):
        forged = SessionToken(session_id=f"flood-{i}", host_id="attacker", hmac_digest="bad")
        with pytest.raises(ValueError, match="HMAC verification failed"):
            tracker.update(forged, [])

    state = tracker.get_state(legit)
    assert state is not None
