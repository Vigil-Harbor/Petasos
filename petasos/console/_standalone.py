"""Shared read-only dashboard ``Pipeline`` builder (PET-153).

Single source of truth for the read-only ``Pipeline`` the console backend
serves, used by both callers so they construct identical pipelines with no
drift:

- the embedded Hermes dashboard plugin (``plugin_api._self_init``), and
- the out-of-process standalone console entrypoint (``petasos.console.__main__``).

This module imports only petasos core + scanners (stdlib + ``petasos.*``); it
never imports fastapi/uvicorn, so it stays loadable on the fastapi-free lane and
the standalone ``__main__`` module top can import it without re-poisoning that
lane.

Logger pin (PET-87): every line is emitted through ``logging.getLogger(
"petasos.dashboard")`` with the verbatim message strings the log-honesty tests
assert on ("backend verified" / "backend missing — registered degraded" / the
self-initialized summary). Do not reword them without updating those tests.
"""

from __future__ import annotations

import base64
import importlib
import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

    from petasos import Pipeline

logger = logging.getLogger("petasos.dashboard")


def build_dashboard_pipeline(raw_config: dict[str, Any]) -> Pipeline:
    """Build the read-only dashboard ``Pipeline`` from a raw config dict.

    Owns everything ``_self_init`` historically did *between* the config read and
    ``init_handlers``: the ``host_id``/``enabled`` pops, the env-secret injection
    (``PETASOS_SESSION_SECRET`` base64-decoded into ``session_secret``,
    ``PETASOS_HASH_KEY`` into ``hash_key``), the ``PetasosConfig.from_dict``
    bad-config-falls-back-to-defaults guard, the scanner build with per-scanner
    probe logging, the ``Pipeline(host_id="dashboard")`` construction, the
    ``PETASOS_LICENSE_KEY`` activation, and the self-initialized summary log.

    The caller owns only the two ends: resolving ``raw_config`` (e.g.
    ``plugin_api._load_config()``) and wiring the result (e.g. ``init_handlers``).
    Pulling the env-secret injection in here is what makes attestation parity hold
    for the standalone ``__main__`` path: a builder that left those env reads in
    ``_self_init`` would hand the standalone console ``session_secret=None`` and
    silently unattested spool reads.
    """
    from petasos import PetasosConfig, Pipeline
    from petasos.scanners import MinimalScanner

    # Defensive copy: the builder mutates (pops + injects), so a caller's dict is
    # left untouched.
    raw_config = dict(raw_config)
    raw_config.pop("host_id", None)
    raw_config.pop("enabled", None)

    session_secret_b64 = os.environ.get("PETASOS_SESSION_SECRET")
    if session_secret_b64:
        try:
            raw_config["session_secret"] = base64.b64decode(session_secret_b64, validate=True)
        except Exception as exc:
            logger.warning(
                "PETASOS_SESSION_SECRET is not valid base64 — session binding disabled: %s",
                exc,
            )

    hash_key = os.environ.get("PETASOS_HASH_KEY")
    if hash_key:
        raw_config["hash_key"] = hash_key

    try:
        config = PetasosConfig.from_dict(raw_config)
    except (TypeError, ValueError) as exc:
        # PET-109: bind + log so a single bad field (e.g. presidio_score_threshold)
        # discarding ALL operator tuning to defaults is diagnosable, not silent.
        # A full per-field-tolerant load is out of scope (Deferred).
        logger.warning("config.yaml rejected (%s); falling back to defaults", exc)
        config = PetasosConfig()

    scanners = [MinimalScanner(decode_encoded_payloads=config.decode_encoded_payloads)]
    unavailable: list[str] = []
    for name, cls_path in [
        ("LLM Guard", "petasos.scanners.LlmGuardScanner"),
        ("LlamaFirewall", "petasos.scanners.LlamaFirewallScanner"),
        ("Presidio", "petasos.scanners.PresidioScanner"),
    ]:
        try:
            mod, cls = cls_path.rsplit(".", 1)

            m = importlib.import_module(mod)
            if name == "Presidio":
                # PET-109: build Presidio from config (entities + score_threshold)
                # instead of the bare no-arg ctor. resolve_presidio_entities lives in
                # presidio.py, whose module imports are stdlib + petasos._types only —
                # importing it does NOT import the presidio backend, so the
                # "importable without the extra" invariant holds and the surrounding
                # try/except ImportError still catches a genuinely-absent backend.
                from petasos.scanners.presidio import resolve_presidio_entities

                instance = getattr(m, cls)(
                    entities=resolve_presidio_entities(
                        config.presidio_entities, config.presidio_entities_extra
                    ),
                    score_threshold=config.presidio_score_threshold,
                )
            else:
                instance = getattr(m, cls)()
            scanners.append(instance)
            probe = getattr(instance, "availability", None)
            if probe is not None:
                # PET-103 D4: arity-tolerant extraction — availability() is
                # duck-typed here (getattr), so tolerate both the legacy 2-tuple
                # and the widened 3-tuple (ok, reason, cause).
                probe_result = probe()
                avail = bool(probe_result[0])
                reason = probe_result[1] if len(probe_result) > 1 else None
                if avail:
                    logger.info("Dashboard scanner %s: backend verified", name)
                else:
                    unavailable.append(name)
                    logger.warning(
                        "Dashboard scanner %s: backend missing — registered degraded: %s",
                        name,
                        reason,
                    )
            else:
                logger.info("Dashboard scanner %s: backend verified", name)
        except ImportError:
            unavailable.append(name)
            logger.warning("Dashboard scanner %s: import failed", name)
        except Exception as exc:
            unavailable.append(name)
            logger.warning("Dashboard scanner %s failed: %s", name, exc)

    pipeline = Pipeline(config=config, scanners=scanners, host_id="dashboard")

    license_key = os.environ.get("PETASOS_LICENSE_KEY")
    if license_key:
        pipeline.activate(license_key)

    logger.info(
        "Dashboard self-initialized pipeline: scanners=%s, unavailable=%s",
        [s.name for s in scanners],
        unavailable,
    )
    return pipeline
