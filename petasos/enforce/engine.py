"""Build the pipeline an enforcer runs, and apply a later settings snapshot.

Scanner construction goes through the registry. A live change updates the
pipeline, the guard, lineage, and the egress sets. A restart-only change is
left as it is and reported. Secrets are not settings: a new secret is logged
and the one already in use stays.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from petasos.config.sections import PetasosConfig
from petasos.guard.guard import ToolCallGuard
from petasos.normalize import canonicalize_tool_name
from petasos.pipeline import Pipeline
from petasos.scanners.registry import REGISTRY, BuildContext, ScannerSpec, compose
from petasos.session.frequency import FrequencyTracker
from petasos.session.lineage import LineageRegistry
from petasos.session.taint import SessionTaintStore

if TYPE_CHECKING:
    import logging
    from collections.abc import Callable, Mapping, Sequence

    from petasos.config.schema import ReconfigureResult
    from petasos.config.secrets import Secrets
    from petasos.enforce.types import HostInfo
    from petasos.guard.guardrail import CheckFailures
    from petasos.model import Scanner

_SEMGREP_PREFIX = "scanners.semgrep."
_SECRET_UNSET = "PETASOS_SESSION_SECRET not set — HMAC session binding disabled"
_SECRET_BAD = "PETASOS_SESSION_SECRET is not valid base64 — HMAC session binding disabled"
_HASH_MISSING = (
    "PETASOS_HASH_KEY not set but redaction_mode=hash "
    "— PII anonymization will fail. Set PETASOS_HASH_KEY "
    "or change redaction_mode."
)
_SECRET_KEPT = (
    "reconfigure: session_secret change ignored (restart required); the live secret is preserved"
)
_SEMGREP_KEPT = "Semgrep settings change ignored: restart required"


def syntactic_scanner() -> Scanner:
    """The syntactic scanner, built by ``compose`` with no optional backends.

    The cold-start gate uses this until the pipeline exists. Construction stays
    inside the registry.
    """
    composed = compose(PetasosConfig(), BuildContext(), registry=())
    return composed.scanners[0]


def _names(values: Sequence[str]) -> frozenset[str]:
    return frozenset(canon for canon in (canonicalize_tool_name(item) for item in values) if canon)


@dataclass
class Engine:
    """The live pipeline and the state that sits beside it."""

    pipeline: Pipeline
    guard: ToolCallGuard
    tracker: FrequencyTracker
    lineage: LineageRegistry | None
    taint: SessionTaintStore
    egress: frozenset[str]
    namespaces: frozenset[str]
    config: PetasosConfig
    secrets: Secrets
    semgrep_warned: bool = False

    def fail_mode(self) -> str:
        """The live fail mode. An unexpected value is treated as degraded."""
        mode = self.config.fail_mode
        if mode in ("open", "degraded", "closed"):
            return mode
        return "degraded"


def _audit(logger: logging.Logger) -> Callable[..., None]:
    def handle(event: object) -> None:
        session_id = getattr(event, "session_id", "")
        sequence = getattr(event, "sequence_number", "")
        event_type = getattr(event, "event_type", "")
        logger.info(
            "PETASOS_AUDIT session=%s seq=%s type=%s",
            session_id,
            sequence,
            event_type,
        )
        payload = getattr(event, "payload", None)
        read = getattr(payload, "get", None)
        if not callable(read):
            return
        if not read("emit_findings"):
            return
        findings = read("findings", ())
        if not isinstance(findings, tuple | list):
            return
        for finding in findings:
            read_finding = getattr(finding, "get", None)
            if not callable(read_finding):
                continue
            logger.info(
                "PETASOS_AUDIT_FINDING session=%s seq=%s rule_id=%s "
                "severity=%s confidence=%s direction=%s",
                session_id,
                sequence,
                read_finding("rule_id"),
                read_finding("severity"),
                read_finding("confidence"),
                read_finding("direction"),
            )

    return handle


def _alert(logger: logging.Logger) -> Callable[..., None]:
    def handle(alert: object) -> None:
        logger.warning(
            "PETASOS_ALERT rule=%s tier=%s session=%s: %s",
            getattr(alert, "rule_id", ""),
            getattr(alert, "tier", "n/a"),
            getattr(alert, "session_id", ""),
            getattr(alert, "message", ""),
        )

    return handle


def _boot_warnings(config: PetasosConfig, secrets: Secrets, logger: logging.Logger) -> None:
    if secrets.session_secret is None:
        logger.warning(_SECRET_UNSET)
    if config.anonymization.mode == "hash" and not secrets.hash_key:
        logger.warning(_HASH_MISSING)


def build_engine(
    config: PetasosConfig,
    secrets: Secrets,
    *,
    host: HostInfo,
    scanners: Sequence[Scanner],
    registry: tuple[ScannerSpec, ...],
    logger: logging.Logger,
    secret_invalid: bool,
    origin: Mapping[str, str] | None = None,
    check_failures: CheckFailures | None = None,
) -> Engine:
    """Compose scanners and construct the pipeline, guard, and stores.

    ``secret_invalid`` selects the base64 warning. A missing secret uses the
    unset warning. Both are boot-only.
    """
    if secret_invalid:
        logger.warning(_SECRET_BAD)
    else:
        _boot_warnings(config, secrets, logger)
    composition = compose(config, BuildContext(), registry=registry)
    chosen: list[Scanner] = list(composition.scanners)
    present = {scanner.name for scanner in chosen}
    for extra in scanners:
        if extra.name in present:
            continue
        chosen.append(extra)
        present.add(extra.name)
    lineage: LineageRegistry | None
    if host.subagent_hooks:
        registry_live = LineageRegistry(config)
        lineage = registry_live
        tracker = FrequencyTracker(
            config,
            secrets=secrets,
            is_pinned=registry_live.is_pinned,
            on_terminate=registry_live.unregister,
        )
        logger.info("Petasos sub-agent lineage active")
    else:
        lineage = None
        tracker = FrequencyTracker(config, secrets=secrets)
        logger.info("Petasos sub-agent lineage inactive (sub-agent hooks unavailable)")
    pipeline = Pipeline(
        chosen,
        config=config,
        secrets=secrets,
        host_id=host.host_id,
        on_audit=_audit(logger),
        on_alert=_alert(logger),
        frequency_tracker=tracker,
    )
    guard = ToolCallGuard(
        pipeline,
        tracker,
        config,
        secrets=secrets,
        origin=origin,
        lineage=lineage,
        protected_paths=host.protected_paths,
        guardrail_surface=host.guardrail_surface,
        check_failures=check_failures,
    )
    egress = _names(config.egress.sink_tools)
    namespaces = _names(config.egress.taint_namespaces)
    if not egress:
        logger.warning(
            "egress_sink_tools is empty (or all names canonicalized away) — "
            "PII will not be blocked on any egress tool"
        )
    if config.egress.taint_namespaces and not namespaces:
        logger.warning(
            "source_taint_namespaces is set but all names canonicalized away — "
            "the source-taint egress fence will match no producing tool"
        )
    names = [scanner.name for scanner in chosen]
    unavailable = [status.id for status in composition.statuses if status.state == "unavailable"]
    logger.info(
        "Petasos initialized: scanners=%s, unavailable=%s, fail_mode=%s, host_id=%s",
        names,
        unavailable,
        config.fail_mode,
        host.host_id,
    )
    return Engine(
        pipeline=pipeline,
        guard=guard,
        tracker=tracker,
        lineage=lineage,
        taint=SessionTaintStore(config),
        egress=egress,
        namespaces=namespaces,
        config=pipeline.config,
        secrets=secrets,
    )


def apply_snapshot(
    engine: Engine,
    proposed: PetasosConfig,
    secrets: Secrets,
    logger: logging.Logger,
    *,
    origin: Mapping[str, str] | None = None,
) -> ReconfigureResult:
    """Apply one snapshot. Restart fields and secrets stay as they are.

    The pipeline's own reconfigure preserves restart fields. The guard then
    reads that preserved tree, not the proposed one.
    """
    result = engine.pipeline.reconfigure(proposed)
    semgrep = [path for path in result.restart_required if path.startswith(_SEMGREP_PREFIX)]
    others = [path for path in result.restart_required if not path.startswith(_SEMGREP_PREFIX)]
    if semgrep and not engine.semgrep_warned:
        engine.semgrep_warned = True
        logger.warning(_SEMGREP_KEPT)
    if secrets.session_secret != engine.secrets.session_secret:
        logger.warning(_SECRET_KEPT)
    if others:
        logger.warning("restart required: %s", ", ".join(others))
    live = engine.pipeline.config
    engine.guard.validate_config(live)
    engine.guard.apply_config(live, origin=origin)
    if engine.lineage is not None:
        engine.lineage.apply_config(live)
    engine.taint.apply_config(live)
    engine.egress = _names(live.egress.sink_tools)
    engine.namespaces = _names(live.egress.taint_namespaces)
    engine.config = live
    engine.guard.forget_protected_paths()
    return result


DEFAULT_REGISTRY = REGISTRY
