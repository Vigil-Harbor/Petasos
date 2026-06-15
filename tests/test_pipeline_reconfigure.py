"""PET-126: Pipeline.reconfigure hot-applies config to a live pipeline instance.

Each test pins a vector that silently failed before: a Config Editor save swapped
``pipeline._config`` but left subcomponents (FrequencyTracker scalars, AuditEmitter
/ AlertManager config refs, the MinimalScanner decode flag) on the boot-time
config. ``reconfigure`` propagates into all of them on the SAME instance without
resetting accumulated session state.
"""

from __future__ import annotations

import logging

import pytest

from petasos._types import PipelineResult, ScanFinding, Severity
from petasos.config import PetasosConfig
from petasos.pipeline import Pipeline
from petasos.scanners.minimal import MinimalScanner


def _pipe(config: PetasosConfig, *, scanner: MinimalScanner | None = None) -> Pipeline:
    return Pipeline(scanners=[scanner or MinimalScanner()], config=config)


def _pii_finding() -> ScanFinding:
    return ScanFinding(
        rule_id="petasos.presidio.person",
        finding_type="pii",
        severity=Severity.LOW,
        confidence=0.9,
        message="pii",
        scanner_name="minimal",
    )


# ── frequency / escalation scalars (pins frequency.py cached-scalar staleness) ──


def test_reconfigure_frequency_takes_effect_same_instance() -> None:
    # Regression for PET-126: FrequencyTracker cached frequency_half_life_seconds /
    # rolling_threshold as scalars at construction; a _config swap never updated them.
    pipe = _pipe(PetasosConfig(frequency_half_life_seconds=60.0, rolling_threshold=10))
    assert pipe._frequency_tracker._half_life == 60.0
    assert pipe._frequency_tracker._rolling_threshold == 10

    pipe.reconfigure(PetasosConfig(frequency_half_life_seconds=5.0, rolling_threshold=3))

    assert pipe._frequency_tracker._half_life == 5.0
    assert pipe._frequency_tracker._rolling_threshold == 3
    assert pipe.config.frequency_half_life_seconds == 5.0


def test_reconfigure_audit_verbosity_takes_effect() -> None:
    # Regression for PET-126: AuditEmitter read audit_verbosity off a STALE _config.
    pipe = _pipe(PetasosConfig(audit_verbosity="standard"))
    result = PipelineResult(safe=True, findings=(), scanner_results=())

    ev1 = pipe._audit_emitter.emit(result, "s1", None)
    assert "findings" in ev1.payload  # standard verbosity carries the findings list

    pipe.reconfigure(PetasosConfig(audit_verbosity="minimal"))

    ev2 = pipe._audit_emitter.emit(result, "s1", None)
    assert "findings" not in ev2.payload  # minimal verbosity drops it


def test_reconfigure_alert_threshold_takes_effect() -> None:
    # Regression for PET-126: AlertManager held a stale _config; alert_* thresholds
    # never changed live. A single PII finding crosses a lowered volume threshold.
    pipe = _pipe(PetasosConfig(alert_pii_volume_threshold=20))
    am = pipe._alert_manager
    result = PipelineResult(safe=True, findings=(_pii_finding(),), scanner_results=())

    alerts = am.evaluate(result, "s1", None)
    assert not any(a.rule_id == "pii_volume_spike" for a in alerts)

    pipe.reconfigure(PetasosConfig(alert_pii_volume_threshold=1))

    alerts2 = am.evaluate(result, "s1", None)
    assert any(a.rule_id == "pii_volume_spike" for a in alerts2)


def test_reconfigure_alert_ring_buffer_capacity_rebuilds_keeping_newest() -> None:
    # A capacity shrink rebuilds _pii_ring_buffer retaining the MOST-recent items
    # (ring-buffer recency), not the oldest.
    pipe = _pipe(PetasosConfig(alert_ring_buffer_capacity=10))
    am = pipe._alert_manager
    for i in range(10):
        am._pii_ring_buffer.append((float(i), i))

    pipe.reconfigure(
        PetasosConfig(
            alert_ring_buffer_capacity=3,
            alert_rapid_fire_count=3,
            alert_cross_session_burst_count=3,
        )
    )

    assert am._pii_ring_buffer.maxlen == 3
    assert [count for _ts, count in am._pii_ring_buffer] == [7, 8, 9]


def test_reconfigure_decode_payloads_changes_minimal_scanner() -> None:
    # Flipping decode_encoded_payloads reaches the live MinimalScanner; a
    # caller-supplied scanner keeps its other tunables AND its object identity.
    scanner = MinimalScanner(
        max_payload_bytes=12_345,
        suppress_rules=frozenset({"petasos.syntactic.encoding.base64"}),
        decode_encoded_payloads=True,
    )
    pipe = _pipe(PetasosConfig(decode_encoded_payloads=True), scanner=scanner)
    assert pipe._minimal_scanner is scanner
    assert scanner._decode_encoded_payloads is True

    pipe.reconfigure(PetasosConfig(decode_encoded_payloads=False))

    assert pipe._minimal_scanner is scanner  # identity preserved (not rebuilt)
    assert scanner._decode_encoded_payloads is False
    assert scanner._max_payload_bytes == 12_345  # other tunables untouched
    assert "petasos.syntactic.encoding.base64" in scanner._suppress_rules


def test_reconfigure_preserves_session_state() -> None:
    # Drive a session into tier1, then reconfigure; counters must survive (no reset).
    pipe = _pipe(PetasosConfig(frequency_weights={"r": 20.0}))
    tracker = pipe._frequency_tracker
    r = tracker.update("sess", ["r"])
    assert r.current_score == 20.0
    assert r.tier == "tier1"  # 20 >= tier1_threshold 15
    assert tracker.size == 1

    pipe.reconfigure(PetasosConfig(frequency_weights={"r": 20.0}, frequency_half_life_seconds=5.0))

    assert tracker.size == 1  # session not dropped
    state = tracker.get_state("sess")
    assert state is not None
    assert state.last_score == 20.0  # accumulated score preserved


def test_reconfigure_session_secret_noop_with_warning(caplog: pytest.LogCaptureFixture) -> None:
    secret = b"s" * 32
    pipe = Pipeline(
        scanners=[MinimalScanner()],
        config=PetasosConfig(session_secret=secret),
        host_id="h1",
    )
    tracker = pipe._frequency_tracker
    token = tracker.mint_token("sess", "h1")
    tracker.update(token, [])

    # A differing non-None secret is ignored (live preserved) and warns once.
    with caplog.at_level(logging.WARNING, logger="petasos.pipeline"):
        pipe.reconfigure(PetasosConfig(session_secret=b"d" * 32))
    warnings = [r for r in caplog.records if "session_secret" in r.getMessage()]
    assert len(warnings) == 1
    assert pipe.config.session_secret == secret
    assert tracker._session_secret == secret  # never rebound (Decision 2)
    assert tracker.get_state(token) is not None  # minted token still verifies

    # An absent/None secret preserves silently (no warning).
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="petasos.pipeline"):
        pipe.reconfigure(PetasosConfig(session_secret=None, frequency_half_life_seconds=7.0))
    assert not [r for r in caplog.records if "session_secret" in r.getMessage()]
    assert pipe.config.session_secret == secret
    assert tracker._session_secret == secret


def test_reconfigure_tombstone_cap_shrink_trims_immediately() -> None:
    pipe = _pipe(PetasosConfig(max_terminated_tombstones=100))
    tracker = pipe._frequency_tracker
    for i in range(5):
        tracker.terminate_session(f"s{i}")
    assert tracker.tombstone_count == 5

    pipe.reconfigure(PetasosConfig(max_terminated_tombstones=2))

    assert tracker.tombstone_count == 2  # trimmed on apply, not lazily


@pytest.mark.parametrize(
    "bad_weights",
    [
        {"a.*.b": 1.0},  # glob '*' in a non-terminal position
        {"x": -1.0},  # negative weight
        {"y": float("inf")},  # non-finite weight
    ],
)
def test_reconfigure_atomic_on_invalid_weights(bad_weights: dict[str, float]) -> None:
    pipe = _pipe(PetasosConfig(frequency_half_life_seconds=60.0, audit_verbosity="standard"))
    before = pipe.config

    with pytest.raises(ValueError):
        pipe.reconfigure(
            PetasosConfig(
                frequency_half_life_seconds=5.0,
                frequency_weights=bad_weights,
                audit_verbosity="verbose",
            )
        )

    # The fail-prone tracker step runs first, so nothing downstream was touched.
    assert pipe.config is before
    assert pipe._frequency_tracker._half_life == 60.0
    assert pipe._audit_emitter._config.audit_verbosity == "standard"


def test_reconfigure_profile_switch_takes_effect() -> None:
    # A config-driven profile follows profile_name on reconfigure (Decision 7).
    pipe = _pipe(PetasosConfig(profile_name="general"))
    assert pipe._default_profile is not None
    assert pipe._default_profile.name == "general"

    pipe.reconfigure(PetasosConfig(profile_name="research"))

    assert pipe._default_profile is not None
    assert pipe._default_profile.name == "research"


def test_reconfigure_keeps_constructor_pinned_profile() -> None:
    # A constructor-pinned profile is preserved across a profile_name change.
    pipe = Pipeline(scanners=[MinimalScanner()], config=PetasosConfig(), profile="general")
    assert pipe._default_profile is not None
    assert pipe._default_profile.name == "general"

    pipe.reconfigure(PetasosConfig(profile_name="research"))

    assert pipe._default_profile is not None
    assert pipe._default_profile.name == "general"  # pin wins over config


def test_reconfigure_rejects_subfloor_or_unordered_tiers() -> None:
    # The Tier-3 floor / ascending-order invariant runs in __post_init__, which
    # from_dict (console + reload build path) re-runs BEFORE reconfigure can swap.
    # An invalid tier config can therefore never be built to hand to reconfigure.
    pipe = _pipe(PetasosConfig())
    before = pipe.config
    base = before.to_dict()

    with pytest.raises(ValueError):
        PetasosConfig.from_dict({**base, "tier3_threshold": 10.0})  # below TIER3_FLOOR
    with pytest.raises(ValueError):
        PetasosConfig.from_dict({**base, "tier1_threshold": 40.0})  # tier1 > tier2

    assert pipe.config is before  # never reached reconfigure with an invalid config
