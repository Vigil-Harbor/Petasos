"""Turn the scanners section into live scanners and one status per backend.

Importing this module does not import an optional backend. Each backend is
imported inside its own builder, and only when that scanner is ``auto`` or
``on``. ``off`` is not constructed, probed, or imported.

``is_registered`` is the registration rule. ``active`` and ``unavailable`` are
in the composed list. ``not_installed`` and ``off`` are not. The state is the
whole answer: the reason never changes it. ``unavailable`` therefore always
has a scanner in the list, so every scan of that id returns an error and the
pipeline's fail mode applies. ``not_installed`` is only the quiet case:
``auto`` and the package is absent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from petasos._types import (
    AVAILABILITY_CAUSE_ABSENT,
    AVAILABILITY_CAUSE_LOAD_FAILED,
    ScanResult,
)
from petasos.scanners.minimal import MinimalScanner

if TYPE_CHECKING:
    from collections.abc import Callable

    from petasos._types import Direction, Scanner
    from petasos.config.sections import PetasosConfig

Capability = Literal["injection", "pii", "code"]
"""What an optional backend reports. The syntactic scanner is separate."""

ScannerState = Literal["active", "unavailable", "not_installed", "off"]
"""Whether a registry entry is in the composed list, and whether it can scan.

``active`` and ``unavailable`` are in the list. ``not_installed`` and ``off``
are not.
"""

Enabled = Literal["auto", "on", "off"]

_REGISTERED: frozenset[ScannerState] = frozenset(("active", "unavailable"))
_SEMGREP_REASONS = frozenset(
    {
        "semgrep.unsupported_platform",
        "semgrep.host_lifecycle_unavailable",
    }
)
_PII_ROLES = frozenset({"support", "admin"})
_SEMGREP_FIX: dict[str, str] = {
    "semgrep.host_lifecycle_unavailable": ("Pass a lifecycle owner when the scanners are built."),
    "semgrep.engine_unavailable": (
        "Set scanners.semgrep.engine_path to the pinned executable and "
        "scanners.semgrep.engine_sha256 to its digest."
    ),
    "semgrep.unsupported_platform": "Use Apple Silicon or 64-bit Windows.",
    "semgrep.construction_failed": ("Check the Semgrep settings and build the scanners again."),
    "semgrep.monitor_unavailable": "pip install petasos[semgrep]",
    "semgrep.lease_closed": "Open a new lifecycle owner. This one is already closed.",
}


def is_registered(state: ScannerState) -> bool:
    """True when a scanner in ``state`` is part of the composed list.

    ``active`` and ``unavailable`` are registered. ``not_installed`` and
    ``off`` are not. The reason is not consulted.
    """
    return state in _REGISTERED


@dataclass(frozen=True, slots=True)
class UnavailableScanner:
    """A scanner whose every scan returns ``reason`` and never raises.

    This stands in when a backend was requested and no working instance
    exists, so the pipeline's fail mode still applies. ``name`` is the
    registry id.
    """

    name: str
    reason: str

    async def scan(
        self,
        text: str,
        *,
        direction: Direction = "inbound",
        session_id: str | None = None,
    ) -> ScanResult:
        del text, direction, session_id
        return ScanResult(
            scanner_name=self.name,
            findings=(),
            duration_ms=0.0,
            error=self.reason,
        )


@dataclass(frozen=True, slots=True)
class BuildContext:
    """Values a builder needs that are not in the config tree.

    ``semgrep_lifecycle`` is the process-local owner of the Semgrep engine.
    ``semgrep_scheduling_key`` groups scans that share one engine lease.
    Without a lifecycle owner the Semgrep adapter is not constructed, and
    ``compose`` registers an ``UnavailableScanner`` in its place.
    """

    semgrep_lifecycle: object | None = None
    semgrep_scheduling_key: object | None = None


@dataclass(frozen=True, slots=True)
class ScannerSpec:
    """One optional backend ``compose`` knows how to build.

    ``id`` equals the scanner's ``name`` and the attribute under
    ``config.scanners``. ``build`` receives that section and the context.
    It runs only when the section's ``enabled`` value is ``auto`` or ``on``.
    ``purpose`` names the check by what it does, for a reader who does not
    know the product; ``label`` is the product's name.
    """

    id: str
    label: str
    extra: str | None
    detects: frozenset[Capability]
    section: str
    default_enabled: Enabled
    build: Callable[[Any, BuildContext], Scanner]
    purpose: str = ""


@dataclass(frozen=True, slots=True)
class ScannerStatus:
    """One registry entry after ``compose``.

    ``state`` decides registration: see ``is_registered``. ``reason`` is
    ``None`` only when ``state`` is ``active``. Otherwise it is text an
    operator can act on. ``extra`` is the pip extra that provides the
    backend, or ``None`` when none does. ``detects`` and ``label`` are copied
    from the spec so a later report can be printed from the status alone.
    ``missing`` is true when the backend reported itself absent: its package
    is not installed, or its model has not been downloaded. It tells a
    required scanner that is absent from one that is present and broken:
    both are ``unavailable``. ``purpose`` is copied from the spec.
    """

    id: str
    state: ScannerState
    reason: str | None
    extra: str | None
    detects: frozenset[Capability]
    label: str
    missing: bool = False
    purpose: str = ""


@dataclass(frozen=True, slots=True)
class Composition:
    """Scanners for a pipeline, and one status per registry entry.

    ``scanners`` starts with the syntactic scanner. A registry entry is in
    that tuple exactly when ``is_registered`` is true for its status.
    """

    scanners: tuple[Scanner, ...]
    statuses: tuple[ScannerStatus, ...]


def _missing_package(spec: ScannerSpec) -> str:
    if spec.extra is None:
        return f"{spec.label} is not installed."
    return f"{spec.label} is not installed. pip install petasos[{spec.extra}]"


def _import_reason(spec: ScannerSpec, exc: ImportError) -> str:
    curated = _missing_package(spec)
    detail = str(exc).strip()
    if not detail or detail in curated:
        return curated
    return f"{curated} ({detail})"


def _status(
    spec: ScannerSpec, state: ScannerState, reason: str | None, *, missing: bool = False
) -> ScannerStatus:
    if state == "active":
        reason = None
    elif not reason:
        reason = f"{spec.label} is {state}."
    return ScannerStatus(
        id=spec.id,
        state=state,
        reason=reason,
        extra=spec.extra,
        detects=spec.detects,
        label=spec.label,
        missing=missing,
        purpose=spec.purpose,
    )


def _read_probe(scanner: Scanner) -> tuple[bool, str | None, str | None]:
    probe = getattr(scanner, "availability", None)
    if not callable(probe):
        return True, None, None
    result = probe()
    if not isinstance(result, tuple) or len(result) == 0:
        return False, "availability probe returned an unexpected result", None
    reason = result[1] if len(result) > 1 and isinstance(result[1], str) else None
    cause_obj = result[2] if len(result) > 2 else None
    cause = (
        cause_obj
        if cause_obj in (AVAILABILITY_CAUSE_ABSENT, AVAILABILITY_CAUSE_LOAD_FAILED)
        else None
    )
    return bool(result[0]), reason, cause


def _after_build(
    spec: ScannerSpec,
    enabled: Enabled,
    instance: Scanner,
) -> tuple[ScannerStatus, Scanner | None]:
    # Probed after the instance exists so a probe that raises leaves the
    # instance registered. An ImportError from the probe is that case, not
    # "the package is absent": absence is a probe result of cause ``absent``,
    # or an ImportError from the builder.
    try:
        ok, reason, cause = _read_probe(instance)
    except Exception as exc:
        text = str(exc).strip() or f"{spec.label} availability probe failed."
        return _status(spec, "unavailable", text), instance
    if ok:
        return _status(spec, "active", None), instance
    if cause == AVAILABILITY_CAUSE_ABSENT:
        text = reason or _missing_package(spec)
        if enabled == "auto":
            return _status(spec, "not_installed", text, missing=True), None
        return (
            _status(spec, "unavailable", text, missing=True),
            UnavailableScanner(spec.id, text),
        )
    text = reason or f"{spec.label} is installed but cannot be used."
    return _status(spec, "unavailable", text), instance


def _compose_one(
    spec: ScannerSpec,
    config: PetasosConfig,
    context: BuildContext,
) -> tuple[ScannerStatus, Scanner | None]:
    section = getattr(config.scanners, spec.section)
    enabled = section.enabled
    if enabled == "off":
        return (
            _status(
                spec,
                "off",
                f"Turned off. Set scanners.{spec.id}.enabled to auto or on to run it.",
            ),
            None,
        )
    if enabled not in ("auto", "on"):
        reason = f"{spec.label} has enabled {enabled!r}. Use auto, on, or off."
        return _status(spec, "unavailable", reason), UnavailableScanner(spec.id, reason)
    try:
        instance = spec.build(section, context)
    except ImportError as exc:
        reason = _import_reason(spec, exc)
        if enabled == "auto":
            return _status(spec, "not_installed", reason, missing=True), None
        return (
            _status(spec, "unavailable", reason, missing=True),
            UnavailableScanner(spec.id, reason),
        )
    except Exception as exc:
        reason = str(exc).strip() or f"{spec.label} could not be built."
        return _status(spec, "unavailable", reason), UnavailableScanner(spec.id, reason)
    return _after_build(spec, enabled, instance)


def _build_prompt_guard(section: Any, context: BuildContext) -> Scanner:
    del context
    from petasos.scanners.prompt_guard import PromptGuardScanner

    return PromptGuardScanner(threshold=section.threshold)


def _build_presidio(section: Any, context: BuildContext) -> Scanner:
    del context
    from petasos.scanners.presidio import PresidioScanner

    # entities_extra is applied on each scan, so a role switch is live.
    # Baking it into the constructed scanner would freeze the role.
    entities = None if section.entities is None else list(section.entities)
    return PresidioScanner(
        entities=entities,
        language=section.language,
        score_threshold=section.score_threshold,
    )


def _build_semgrep(section: Any, context: BuildContext) -> Scanner:
    owner = context.semgrep_lifecycle
    if owner is None:
        raise ValueError("semgrep.host_lifecycle_unavailable")
    from petasos.scanners.semgrep import SemgrepLifecycleOwner, SemgrepScanner

    if not isinstance(owner, SemgrepLifecycleOwner):
        raise ValueError("semgrep.host_lifecycle_unavailable")
    try:
        return SemgrepScanner(
            owner=owner,
            engine_path=section.engine_path,
            engine_sha256=section.engine_sha256,
            request_timeout_seconds=section.request_timeout_seconds,
            max_source_bytes=section.max_source_bytes,
            semgrep_scheduling_key=context.semgrep_scheduling_key,
        )
    except Exception as exc:
        # These two texts are matched by name outside this package. Any other
        # construction failure collapses to one code.
        reason = str(exc)
        if reason not in _SEMGREP_REASONS:
            raise ValueError("semgrep.construction_failed") from exc
        raise


# Registration order after the syntactic scanner: Presidio, PromptGuard, Semgrep.
REGISTRY: tuple[ScannerSpec, ...] = (
    ScannerSpec(
        id="presidio",
        label="Presidio",
        extra="presidio",
        detects=frozenset({"pii"}),
        section="presidio",
        default_enabled="auto",
        build=_build_presidio,
        purpose="Personal details check",
    ),
    ScannerSpec(
        id="prompt_guard",
        label="PromptGuard",
        extra="prompt-guard",
        detects=frozenset({"injection"}),
        section="prompt_guard",
        default_enabled="auto",
        build=_build_prompt_guard,
        purpose="Reworded instructions check",
    ),
    ScannerSpec(
        id="semgrep",
        label="Semgrep",
        extra="semgrep",
        detects=frozenset({"code"}),
        section="semgrep",
        default_enabled="off",
        build=_build_semgrep,
        purpose="Risky code check",
    ),
)


def compose(
    config: PetasosConfig,
    context: BuildContext,
    *,
    registry: tuple[ScannerSpec, ...] = REGISTRY,
) -> Composition:
    """Build the syntactic scanner and each registry entry the config asks for.

    Never raises because an optional backend failed to import, construct, or
    answer its probe: that failure is a status. A failure to construct the
    syntactic scanner is not caught. ``registry`` defaults to ``REGISTRY``;
    tests pass a tuple of fake specs.
    """
    scanners: list[Scanner] = [
        MinimalScanner(decode_encoded_payloads=config.normalization.decode_payloads)
    ]
    statuses: list[ScannerStatus] = []
    for spec in registry:
        status, built = _compose_one(spec, config, context)
        if is_registered(status.state) is not (built is not None):
            raise RuntimeError(f"{spec.id} state {status.state} disagrees with registration")
        statuses.append(status)
        if built is not None:
            scanners.append(built)
    return Composition(scanners=tuple(scanners), statuses=tuple(statuses))


def _fix(status: ScannerStatus) -> str:
    known = _SEMGREP_FIX.get(status.reason or "")
    if known is not None:
        return known
    if status.extra is not None:
        return f"pip install petasos[{status.extra}]"
    return "Check this scanner's configuration and build the scanners again."


def _unavailable_line(status: ScannerStatus) -> str:
    reason = status.reason or "no reason was reported"
    fix = _fix(status)
    if fix in reason:
        return f"{status.label} is unavailable: {reason}"
    return f"{status.label} is unavailable: {reason}. {fix}"


def _capability_active(composition: Composition, capability: Capability) -> bool:
    return any(
        status.state == "active" and capability in status.detects
        for status in composition.statuses
    )


def fix_for(status: ScannerStatus) -> str | None:
    """What to do about a scanner that is not running, or None when it is active.

    ``off`` repeats the status reason, which already says how to turn it on.
    Anything else is the install or repair step.
    """
    if status.state == "active":
        return None
    if status.state == "off":
        return status.reason
    return _fix(status)


def recommendations(composition: Composition, role: str | None = None) -> tuple[str, ...]:
    """Plain-language actions for an operator, in a stable order.

    No active injection scanner suggests the prompt-guard extra. Role
    ``support`` or ``admin`` with no active personal-information scanner
    suggests the presidio extra. Each ``unavailable`` scanner adds its
    reason and the fix, in registry order, before those suggestions.
    """
    lines = [
        _unavailable_line(status)
        for status in composition.statuses
        if status.state == "unavailable"
    ]
    if not _capability_active(composition, "injection"):
        lines.append(
            "No injection scanner is active. "
            "Install the prompt-guard extra: pip install petasos[prompt-guard]."
        )
    if role in _PII_ROLES and not _capability_active(composition, "pii"):
        lines.append(
            f"Role {role} has no active personal-information scanner. "
            "Install the presidio extra: pip install petasos[presidio]."
        )
    return tuple(lines)


def spec_for(name: str) -> ScannerSpec | None:
    """The registry entry for a scanner id, label, or extra name.

    Matching ignores case and treats ``-`` and ``_`` as the same character.
    ``None`` when nothing matches, including a blank name.
    """
    token = _token(name)
    if token == "":
        return None
    for spec in REGISTRY:
        aliases = {_token(spec.id), _token(spec.label)}
        if spec.extra is not None:
            aliases.add(_token(spec.extra))
        if token in aliases:
            return spec
    return None


def _token(value: str) -> str:
    return value.strip().casefold().replace("-", "_")


__all__ = [
    "REGISTRY",
    "BuildContext",
    "Capability",
    "Composition",
    "Enabled",
    "ScannerSpec",
    "ScannerState",
    "ScannerStatus",
    "UnavailableScanner",
    "compose",
    "fix_for",
    "is_registered",
    "recommendations",
    "spec_for",
]
