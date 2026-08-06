"""Shared config-to-scanner-list build (PET-174).

One translation from ``PetasosConfig`` to the scanner list every bootstrap hands
to ``Pipeline``. Two call sites use it today:

- ``petasos.console._standalone.build_dashboard_pipeline`` (the console pipeline), and
- the reference plugin's ``_deferred_init`` (the Hermes enforcement pipeline).

Before this module they were two hand-maintained loops, and the four
scanner-construction config fields (``presidio_entities``,
``presidio_entities_extra``, ``presidio_score_threshold``,
``decode_encoded_payloads``) reached only the first of them: the pipeline that
rendered the console honored them and the pipeline that blocked tool calls did
not. A third bootstrap that hand-copies the constructors would drift the same
way, so ``tests/test_scanner_bootstrap_structure.py`` pins the routing
structurally.

The helper returns data and never logs: the two callers differ in logger name,
message wording, level for the not-installed case, and identifier vocabulary, so
each formats its own lines from the returned ``ScannerBuildStatus`` records.

Base install: module-level imports are stdlib plus ``petasos.scanners.minimal``
(already imported unconditionally by ``petasos.pipeline``). Every optional
backend import is function-local, inside the per-backend ``try/except
ImportError``, so importing this module pulls in no ML dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from petasos.scanners.minimal import MinimalScanner

if TYPE_CHECKING:
    from collections.abc import Callable

    from petasos._types import Scanner
    from petasos.config import PetasosConfig

ScannerOutcome = Literal["verified", "degraded", "missing", "failed"]
"""How one optional backend fared during :func:`build_scanners`.

``verified`` - constructed and its availability probe said the backend is usable.
``degraded`` - constructed and registered, but the probe reported the backend
unusable (every scan will error).
``missing`` - the class could not be imported, or its constructor raised
``ImportError``; nothing was registered.
``failed`` - anything else went wrong. Ambiguous by construction: a constructor
raising a non-``ImportError`` registers nothing, while a throwing availability
probe leaves the instance registered. Read the returned scanner list, not this
value, to learn what is registered.
"""


@dataclass(frozen=True)
class ScannerBuildStatus:
    """One optional backend's build outcome, for the caller to render."""

    scanner_id: str
    """Snake id, equal to the backend's ``Scanner.name``
    (``llm_guard`` / ``llama_firewall`` / ``presidio``). Same vocabulary
    ``Pipeline.scanner_health()`` and the console Scanner Health panel key on."""

    display_name: str
    """Human-facing name (``LLM Guard`` / ``LlamaFirewall`` / ``Presidio``)."""

    outcome: ScannerOutcome
    reason: str | None = None
    """Populated for every non-``verified`` outcome: the probe reason for
    ``degraded``, ``str(exc)`` for ``missing`` and ``failed``."""


def _build_llm_guard(config: PetasosConfig) -> Scanner:
    from petasos.scanners import LlmGuardScanner

    return LlmGuardScanner()


def _build_llama_firewall(config: PetasosConfig) -> Scanner:
    from petasos.scanners import LlamaFirewallScanner

    return LlamaFirewallScanner()


def _build_presidio(config: PetasosConfig) -> Scanner:
    from petasos.scanners import PresidioScanner

    # PET-109: build Presidio from config (entities + score_threshold) instead of
    # the bare no-arg ctor. resolve_presidio_entities lives in presidio.py, whose
    # module imports are stdlib + petasos._types only - importing it does NOT
    # import the presidio backend, so the "importable without the extra"
    # invariant holds and the caller's try/except ImportError still catches a
    # genuinely-absent backend.
    from petasos.scanners.presidio import resolve_presidio_entities

    return PresidioScanner(
        entities=resolve_presidio_entities(
            config.presidio_entities, config.presidio_entities_extra
        ),
        score_threshold=config.presidio_score_threshold,
    )


# (scanner_id, display_name, builder). Order is the registration order both
# pre-PET-174 loops produced, so `Pipeline`'s minimal-scanner detection and both
# callers' `scanners=%s` log lines are unchanged.
_BACKENDS: tuple[tuple[str, str, Callable[[PetasosConfig], Scanner]], ...] = (
    ("llm_guard", "LLM Guard", _build_llm_guard),
    ("llama_firewall", "LlamaFirewall", _build_llama_firewall),
    ("presidio", "Presidio", _build_presidio),
)


def build_scanners(
    config: PetasosConfig,
) -> tuple[list[Scanner], list[ScannerBuildStatus]]:
    """Build the scanner list a ``Pipeline`` bootstrap needs, plus per-backend status.

    Returns ``(scanners, statuses)``.

    ``scanners[0]`` is always the ``MinimalScanner``, carrying
    ``config.decode_encoded_payloads``; each optional backend that constructed
    successfully follows, in the fixed order LLM Guard, LlamaFirewall, Presidio.

    ``statuses`` carries one record per **optional backend only**, in that same
    fixed order. The ``MinimalScanner`` gets no record: neither in-tree caller
    logs anything for it, and emitting one would force both to filter it back out.

    Registration is three-way, and ``scanners`` is the authority. ``missing``
    means nothing was registered. ``degraded`` always means an instance **is**
    registered. ``failed`` is ambiguous: a constructor that raised registered
    nothing, while a throwing availability probe left the instance registered.
    Do not infer registration from ``failed``; read the returned list.

    Never raises for an optional-backend failure - every such failure is folded
    into a status record. A ``MinimalScanner`` construction failure is
    deliberately not caught: that is a base-install invariant breach and must
    surface.

    Holds no module-level mutable state, so a plugin's background init thread and
    a dashboard process can both call it without coordination.
    """
    scanners: list[Scanner] = [
        MinimalScanner(decode_encoded_payloads=config.decode_encoded_payloads)
    ]
    statuses: list[ScannerBuildStatus] = []

    for scanner_id, display_name, build in _BACKENDS:
        # Build stage. An ImportError here means the wrapper module (or the
        # backend a future wrapper imports at module level) did not import, so
        # nothing is registered -> `missing`.
        try:
            instance = build(config)
        except ImportError as exc:
            statuses.append(ScannerBuildStatus(scanner_id, display_name, "missing", str(exc)))
            continue
        except Exception as exc:
            statuses.append(ScannerBuildStatus(scanner_id, display_name, "failed", str(exc)))
            continue

        # Append BEFORE probing (both pre-PET-174 loops did): a scanner whose
        # availability() raises stays registered and is reported unavailable,
        # rather than vanishing from the pipeline.
        scanners.append(instance)

        # Probe stage, in its own try so an ImportError escaping a duck-typed
        # probe classifies as `failed`, not `missing`. Under one wide try, a
        # registered scanner that errors on every scan (and, under the default
        # fail_mode="degraded", blocks content) would be reported as "not
        # installed" at INFO - the one arrangement where the operator-visible
        # signal is the opposite of what is happening.
        try:
            probe = getattr(instance, "availability", None)
            if probe is None:
                statuses.append(ScannerBuildStatus(scanner_id, display_name, "verified"))
                continue
            # PET-103 D4: arity-tolerant extraction - availability() is duck-typed
            # here, so tolerate both the legacy 2-tuple and the widened 3-tuple
            # (ok, reason, cause).
            probe_result = probe()
            ok = bool(probe_result[0])
            reason = probe_result[1] if len(probe_result) > 1 else None
            if ok:
                statuses.append(ScannerBuildStatus(scanner_id, display_name, "verified"))
            else:
                statuses.append(ScannerBuildStatus(scanner_id, display_name, "degraded", reason))
        except Exception as exc:
            statuses.append(ScannerBuildStatus(scanner_id, display_name, "failed", str(exc)))

    return scanners, statuses
