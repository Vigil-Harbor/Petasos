from __future__ import annotations

from types import MappingProxyType

import pytest

from petasos._types import (
    Alert,
    AuditEvent,
    PipelineResult,
    ScanFinding,
    ScanResult,
    Severity,
)
from petasos.config import PetasosConfig
from petasos.pipeline import Pipeline
from petasos.premium.license import LicenseClaims, LicenseState
from petasos.premium.profiles import ProfileResolver
from petasos.scanners.minimal import RULE_TAXONOMY


class TestFrozenDataclasses:
    def test_scan_finding_frozen(self) -> None:
        f = ScanFinding(
            rule_id="test",
            finding_type="test",
            severity=Severity.LOW,
            confidence=0.5,
            message="test",
            scanner_name="test",
        )
        with pytest.raises(AttributeError):
            f.rule_id = "hacked"  # type: ignore[misc]

    def test_scan_result_frozen(self) -> None:
        r = ScanResult(scanner_name="test", findings=())
        with pytest.raises(AttributeError):
            r.scanner_name = "hacked"  # type: ignore[misc]

    def test_pipeline_result_frozen(self) -> None:
        r = PipelineResult(safe=True, findings=())
        with pytest.raises(AttributeError):
            r.safe = False  # type: ignore[misc]

    def test_audit_event_frozen(self) -> None:
        e = AuditEvent(
            event_id="e1",
            timestamp=0.0,
            session_id=None,
            event_type="test",
            payload=MappingProxyType({}),
            sequence_number=0,
        )
        with pytest.raises(AttributeError):
            e.event_type = "hacked"  # type: ignore[misc]

    def test_alert_frozen(self) -> None:
        a = Alert(
            alert_id="a1",
            timestamp=0.0,
            rule_id="r1",
            severity="high",
            session_id=None,
            message="test",
            context=MappingProxyType({}),
        )
        with pytest.raises(AttributeError):
            a.message = "hacked"  # type: ignore[misc]

    def test_license_claims_frozen(self) -> None:
        from datetime import datetime, timezone

        c = LicenseClaims(
            tier="pro",
            customer_id="c1",
            expiry=datetime.now(tz=timezone.utc),
            issued_at=datetime.now(tz=timezone.utc),
            features=frozenset(),
        )
        with pytest.raises(AttributeError):
            c.tier = "hacked"  # type: ignore[misc]


class TestDefensiveCopies:
    def test_pipeline_config_is_copy(self) -> None:
        cfg = PetasosConfig()
        p = Pipeline(config=cfg)
        assert p._config is not cfg

    def test_pipeline_result_findings_is_tuple(self) -> None:
        r = PipelineResult(safe=True, findings=())
        assert isinstance(r.findings, tuple)

    def test_pipeline_result_scanner_results_is_tuple(self) -> None:
        r = PipelineResult(safe=True, findings=(), scanner_results=())
        assert isinstance(r.scanner_results, tuple)

    def test_pipeline_result_errors_is_tuple(self) -> None:
        r = PipelineResult(safe=True, findings=(), errors=())
        assert isinstance(r.errors, tuple)

    def test_premium_features_is_mapping_proxy(self, valid_key: str) -> None:
        p = Pipeline(config=PetasosConfig(frequency_enabled=True))
        p.activate(valid_key)
        result_sync = p._build_premium_features()
        assert isinstance(result_sync, MappingProxyType)
        with pytest.raises(TypeError):
            result_sync["frequency"] = "hacked"  # type: ignore[index]


class TestImmutableExports:
    def test_rule_taxonomy_is_frozenset(self) -> None:
        assert isinstance(RULE_TAXONOMY, frozenset)

    def test_builtin_profiles_immutable(self) -> None:
        resolver = ProfileResolver()
        profile = resolver.resolve("general")
        assert isinstance(profile.suppress_rules, frozenset)
        assert isinstance(profile.severity_overrides, MappingProxyType)
        assert isinstance(profile.tool_exempt_list, frozenset)
        assert isinstance(profile.tool_alias_map, MappingProxyType)

    def test_config_copy_preserves_frequency_weights(self) -> None:
        cfg = PetasosConfig(frequency_weights=MappingProxyType({"injection": 10.0}))
        copy = cfg.copy()
        assert isinstance(copy.frequency_weights, MappingProxyType)
        assert copy.frequency_weights == cfg.frequency_weights
