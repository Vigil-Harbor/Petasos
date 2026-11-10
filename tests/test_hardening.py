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
from petasos.config.layers import ROLES
from petasos.config.schema import from_mapping, to_mapping
from petasos.config.sections import PetasosConfig
from petasos.pipeline import Pipeline
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


class TestDefensiveCopies:
    def test_pipeline_config_is_copy(self) -> None:
        cfg = PetasosConfig()
        p = Pipeline(config=cfg)
        assert p.config == cfg
        with pytest.raises(AttributeError):
            p.config.fail_mode = "open"  # type: ignore[misc]

    def test_pipeline_result_findings_is_tuple(self) -> None:
        r = PipelineResult(safe=True, findings=())
        assert isinstance(r.findings, tuple)

    def test_pipeline_result_scanner_results_is_tuple(self) -> None:
        r = PipelineResult(safe=True, findings=(), scanner_results=())
        assert isinstance(r.scanner_results, tuple)

    def test_pipeline_result_errors_is_tuple(self) -> None:
        r = PipelineResult(safe=True, findings=(), errors=())
        assert isinstance(r.errors, tuple)

    def test_feature_status_is_mapping_proxy(self) -> None:
        p = Pipeline(
            config=from_mapping(
                PetasosConfig,
                {
                    "frequency": {
                        "enabled": True,
                    },
                },
            )
        )
        result_sync = p._build_feature_status()
        assert isinstance(result_sync, MappingProxyType)
        with pytest.raises(TypeError):
            result_sync["frequency"] = "hacked"  # type: ignore[index]


class TestImmutableExports:
    def test_rule_taxonomy_is_frozenset(self) -> None:
        assert isinstance(RULE_TAXONOMY, frozenset)

    def test_builtin_profiles_immutable(self) -> None:
        for role in ROLES.values():
            assert isinstance(role.document, MappingProxyType)

    def test_config_copy_preserves_frequency_weights(self) -> None:
        cfg = from_mapping(
            PetasosConfig,
            {
                "frequency": {
                    "weights": {"injection": 10.0},
                },
            },
        )
        copy = from_mapping(PetasosConfig, to_mapping(cfg))
        assert isinstance(cfg.frequency.weights, MappingProxyType)
        assert isinstance(copy.frequency.weights, MappingProxyType)
        assert copy.frequency.weights == cfg.frequency.weights
        assert copy.frequency.weights is not cfg.frequency.weights
