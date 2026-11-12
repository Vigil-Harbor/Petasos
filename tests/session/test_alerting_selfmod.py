"""Self-modification alerts retain their severity and bypass ordinary cooldowns."""

from __future__ import annotations

import pytest

from petasos.config.schema import from_mapping
from petasos.config.sections import PetasosConfig
from petasos.model import ScanFinding, Severity
from petasos.session.alerting import AlertManager


@pytest.mark.parametrize(
    ("rule", "severity"),
    [("petasos.selfmod.config_write", "critical"), ("petasos.selfmod.config_ref", "high")],
)
def test_selfmod_alerts_keep_severity_and_bypass_cooldown(rule: str, severity: str) -> None:
    delivered: list[object] = []
    config = from_mapping(PetasosConfig, {"alerting": {"enabled": False}})
    manager = AlertManager(config)
    manager.add_listener(delivered.append)
    finding = ScanFinding(rule, "selfmod", Severity.HIGH, 1.0, "protected config", "selfmod")
    first = manager.evaluate_selfmod(finding, "session")
    second = manager.evaluate_selfmod(finding, "session")
    assert first is not None and second is not None
    assert first.severity == second.severity == severity
    assert first.rule_id == second.rule_id == "selfmod_attempt"
    assert delivered == [first, second]
