"""Recording self-modification always alerts and obeys only the audit switch."""

from __future__ import annotations

import pytest

from petasos.config.schema import from_mapping
from petasos.config.sections import PetasosConfig
from petasos.model import ScanFinding, Severity
from petasos.pipeline import Pipeline


@pytest.mark.parametrize("audit_enabled", [True, False])
def test_selfmod_alerts_with_other_features_off_and_audit_follows_its_switch(
    audit_enabled: bool,
) -> None:
    config = from_mapping(
        PetasosConfig,
        {
            "audit": {"enabled": audit_enabled},
            "alerting": {"enabled": False},
            "frequency": {"enabled": False},
            "escalation": {"enabled": False},
        },
    )
    pipeline = Pipeline(config=config)
    alerts: list[object] = []
    audits: list[object] = []
    pipeline.add_alert_listener(alerts.append)
    pipeline.add_audit_listener(audits.append)
    finding = ScanFinding(
        "petasos.selfmod.config_write", "selfmod", Severity.CRITICAL, 1.0, "config", "selfmod"
    )
    pipeline.record_selfmod("session", finding)
    pipeline.record_selfmod("session", finding)
    assert len(alerts) == 2
    assert len(audits) == (2 if audit_enabled else 0)
