"""Pin alert settings reload without resetting counters or cooldowns.

See docs/architecture/rationale.md, "Alert and audit test constraints"."""

from __future__ import annotations

from petasos.config.schema import from_mapping
from petasos.config.sections import PetasosConfig
from petasos.session.alerting import AlertManager


def test_alert_add_listener_registers() -> None:
    mgr = AlertManager(PetasosConfig())
    mgr.add_listener(lambda a: None)
    assert len(mgr._listeners) == 1


def test_alert_apply_config_rebuilds_pii_ring_on_shrink() -> None:
    mgr = AlertManager(
        from_mapping(
            PetasosConfig,
            {
                "alerting": {
                    "ring_buffer_capacity": 10,
                    "rapid_fire_count": 3,
                    "cross_session_burst_count": 3,
                },
            },
        )
    )
    for i in range(10):
        mgr._pii_ring_buffer.append((float(i), 1))
    mgr.apply_config(
        from_mapping(
            PetasosConfig,
            {
                "alerting": {
                    "ring_buffer_capacity": 5,
                    "rapid_fire_count": 3,
                    "cross_session_burst_count": 3,
                },
            },
        )
    )
    assert mgr._pii_ring_buffer.maxlen == 5
    assert [ts for ts, _ in mgr._pii_ring_buffer] == [5.0, 6.0, 7.0, 8.0, 9.0]
