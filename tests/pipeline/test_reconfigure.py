"""Pin live pipeline settings propagation without resetting accumulated session state.

See docs/architecture/rationale.md, "Test timing and backend qualification"."""

from __future__ import annotations

import logging

import pytest

from petasos.config.layers import resolve
from petasos.config.schema import from_mapping
from petasos.config.secrets import Secrets
from petasos.config.sections import PetasosConfig
from petasos.model import PipelineResult, ScanFinding, Severity
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


def test_reconfigure_frequency_takes_effect_same_instance() -> None:
    """Pin reconfigure frequency takes effect same instance."""
    pipe = _pipe(
        from_mapping(
            PetasosConfig,
            {
                "frequency": {
                    "half_life_seconds": 60.0,
                    "rolling_threshold": 10,
                },
            },
        )
    )
    assert pipe._frequency_tracker._half_life == 60.0
    assert pipe._frequency_tracker._rolling_threshold == 10

    pipe.reconfigure(
        from_mapping(
            PetasosConfig,
            {
                "frequency": {
                    "half_life_seconds": 5.0,
                    "rolling_threshold": 3,
                },
            },
        )
    )

    assert pipe._frequency_tracker._half_life == 5.0
    assert pipe._frequency_tracker._rolling_threshold == 3
    assert pipe.config.frequency.half_life_seconds == 5.0


def test_reconfigure_audit_verbosity_takes_effect() -> None:
    """Pin reconfigure audit verbosity takes effect."""
    pipe = _pipe(
        from_mapping(
            PetasosConfig,
            {
                "audit": {
                    "verbosity": "standard",
                },
            },
        )
    )
    result = PipelineResult(safe=True, findings=(), scanner_results=())

    ev1 = pipe._audit_emitter.emit(result, "s1", None)
    assert "findings" in ev1.payload

    pipe.reconfigure(
        from_mapping(
            PetasosConfig,
            {
                "audit": {
                    "verbosity": "minimal",
                },
            },
        )
    )

    ev2 = pipe._audit_emitter.emit(result, "s1", None)
    assert "findings" not in ev2.payload


def test_reconfigure_alert_threshold_takes_effect() -> None:
    """Pin reconfigure alert threshold takes effect."""
    pipe = _pipe(
        from_mapping(
            PetasosConfig,
            {
                "alerting": {
                    "pii_volume_threshold": 20,
                },
            },
        )
    )
    am = pipe._alert_manager
    result = PipelineResult(safe=True, findings=(_pii_finding(),), scanner_results=())

    alerts = am.evaluate(result, "s1", None)
    assert not any(a.rule_id == "pii_volume_spike" for a in alerts)

    pipe.reconfigure(
        from_mapping(
            PetasosConfig,
            {
                "alerting": {
                    "pii_volume_threshold": 1,
                },
            },
        )
    )

    alerts2 = am.evaluate(result, "s1", None)
    assert any(a.rule_id == "pii_volume_spike" for a in alerts2)


def test_reconfigure_alert_ring_buffer_capacity_rebuilds_keeping_newest() -> None:
    """Pin reconfigure alert ring buffer capacity rebuilds keeping newest."""
    pipe = _pipe(
        from_mapping(
            PetasosConfig,
            {
                "alerting": {
                    "ring_buffer_capacity": 10,
                },
            },
        )
    )
    am = pipe._alert_manager
    for i in range(10):
        am._pii_ring_buffer.append((float(i), i))

    pipe.reconfigure(
        from_mapping(
            PetasosConfig,
            {
                "alerting": {
                    "ring_buffer_capacity": 3,
                    "rapid_fire_count": 3,
                    "cross_session_burst_count": 3,
                },
            },
        )
    )

    assert am._pii_ring_buffer.maxlen == 3
    assert [count for _ts, count in am._pii_ring_buffer] == [7, 8, 9]


def test_reconfigure_decode_payloads_changes_minimal_scanner() -> None:
    """Pin reconfigure decode payloads changes minimal scanner."""
    scanner = MinimalScanner(
        max_payload_bytes=12_345,
        suppress_rules=frozenset({"petasos.syntactic.encoding.base64"}),
        decode_encoded_payloads=True,
    )
    pipe = _pipe(
        from_mapping(
            PetasosConfig,
            {
                "normalization": {
                    "decode_payloads": True,
                },
            },
        ),
        scanner=scanner,
    )
    assert pipe._minimal_scanner is scanner
    assert scanner._decode_encoded_payloads is True

    pipe.reconfigure(
        from_mapping(
            PetasosConfig,
            {
                "normalization": {
                    "decode_payloads": False,
                },
            },
        )
    )

    assert pipe._minimal_scanner is scanner
    assert scanner._decode_encoded_payloads is False
    assert scanner._max_payload_bytes == 12_345
    assert "petasos.syntactic.encoding.base64" in scanner._suppress_rules


def test_reconfigure_preserves_session_state() -> None:
    """Pin reconfigure preserves session state."""
    pipe = _pipe(
        from_mapping(
            PetasosConfig,
            {
                "frequency": {
                    "weights": {"r": 20.0},
                },
            },
        )
    )
    tracker = pipe._frequency_tracker
    r = tracker.update("sess", ["r"])
    assert r.current_score == 20.0
    assert r.tier == "tier1"
    assert tracker.size == 1

    pipe.reconfigure(
        from_mapping(
            PetasosConfig,
            {
                "frequency": {
                    "weights": {"r": 20.0},
                    "half_life_seconds": 5.0,
                },
            },
        )
    )

    assert tracker.size == 1
    state = tracker.get_state("sess")
    assert state is not None
    assert state.last_score == 20.0


def test_reconfigure_session_secret_noop_with_warning(caplog: pytest.LogCaptureFixture) -> None:
    """Pin reconfigure session secret noop with warning."""
    secret = b"s" * 32
    pipe = Pipeline(
        scanners=[MinimalScanner()],
        config=PetasosConfig(),
        secrets=Secrets(session_secret=secret),
        host_id="h1",
    )
    tracker = pipe._frequency_tracker
    token = tracker.mint_token("sess", "h1")
    tracker.update(token, [])

    with caplog.at_level(logging.WARNING, logger="petasos.pipeline"):
        result = pipe.reconfigure(
            from_mapping(
                PetasosConfig,
                {
                    "frequency": {
                        "half_life_seconds": 7.0,
                    },
                },
            )
        )
    assert not [r for r in caplog.records if "session_secret" in r.getMessage()]
    assert tracker._session_secret == secret
    assert tracker.get_state(token) is not None
    assert "frequency.half_life_seconds" in result.applied


def test_reconfigure_tombstone_cap_shrink_trims_immediately() -> None:
    """Pin reconfigure tombstone cap shrink trims immediately."""
    pipe = _pipe(
        from_mapping(
            PetasosConfig,
            {
                "sessions": {
                    "max_tombstones": 100,
                },
            },
        )
    )
    tracker = pipe._frequency_tracker
    for i in range(5):
        tracker.terminate_session(f"s{i}")
    assert tracker.tombstone_count == 5

    pipe.reconfigure(
        from_mapping(
            PetasosConfig,
            {
                "sessions": {
                    "max_tombstones": 2,
                },
            },
        )
    )

    assert tracker.tombstone_count == 2


@pytest.mark.parametrize(
    "bad_weights",
    [
        {"a.*.b": 1.0},
        {"x": -1.0},
        {"y": float("inf")},
    ],
)
def test_reconfigure_atomic_on_invalid_weights(bad_weights: dict[str, float]) -> None:
    """Pin reconfigure atomic on invalid weights."""
    pipe = _pipe(
        from_mapping(
            PetasosConfig,
            {
                "frequency": {
                    "half_life_seconds": 60.0,
                },
                "audit": {
                    "verbosity": "standard",
                },
            },
        )
    )
    before = pipe.config

    with pytest.raises(ValueError):
        pipe.reconfigure(
            from_mapping(
                PetasosConfig,
                {
                    "frequency": {
                        "half_life_seconds": 5.0,
                        "weights": bad_weights,
                    },
                    "audit": {
                        "verbosity": "verbose",
                    },
                },
            )
        )

    assert pipe.config is before
    assert pipe._frequency_tracker._half_life == 60.0
    assert pipe.config.audit.verbosity == "standard"


def test_reconfigure_profile_switch_takes_effect() -> None:
    """Pin reconfigure profile switch takes effect."""
    pipe = _pipe(resolve({"role": "general"}).config)
    assert pipe.config.rules.suppress == ()

    result = pipe.reconfigure(resolve({"role": "research"}).config)

    assert "petasos.syntactic.encoding.invisible-chars" in pipe.config.rules.suppress
    assert "rules.suppress" in result.applied


def test_reconfigure_keeps_constructor_pinned_profile() -> None:
    """Pin reconfigure keeps constructor pinned profile."""
    pipe = Pipeline(
        scanners=[MinimalScanner()],
        config=resolve({"role": "general"}).config,
    )
    assert pipe.config.rules.confidence_floor == 0.0

    pipe.reconfigure(resolve({"role": "research"}).config)

    assert pipe.config.rules.confidence_floor == 0.7


def test_reconfigure_rejects_subfloor_or_unordered_tiers() -> None:
    """Pin reconfigure rejects subfloor or unordered tiers."""
    pipe = _pipe(PetasosConfig())
    before = pipe.config

    with pytest.raises(ValueError, match="escalation.tier3"):
        from_mapping(PetasosConfig, {"escalation": {"tier3": 10.0}})
    with pytest.raises(ValueError, match="escalation"):
        from_mapping(PetasosConfig, {"escalation": {"tier1": 40.0}})

    assert pipe.config is before


def test_shared_tracker_double_apply_is_idempotent_and_preserves_scores() -> None:
    """Pin shared tracker double apply is idempotent and preserves scores."""
    from petasos.guard.guard import ToolCallGuard
    from petasos.session.frequency import FrequencyTracker

    cfg = PetasosConfig()
    tracker = FrequencyTracker(cfg)
    pipeline = Pipeline(config=cfg, frequency_tracker=tracker)
    guard = ToolCallGuard(pipeline, tracker, cfg)

    tracker.update("s-keep", ["petasos.syntactic.injection.x"])
    before = tracker.get_state("s-keep")
    assert before is not None and before.last_score == 10.0

    new_cfg = from_mapping(
        PetasosConfig,
        {
            "frequency": {
                "half_life_seconds": 120.0,
            },
        },
    )
    pipeline.reconfigure(new_cfg)
    guard.apply_config(new_cfg)

    after = tracker.get_state("s-keep")
    assert after is not None and after.last_score == before.last_score
    assert tracker._half_life == 120.0
