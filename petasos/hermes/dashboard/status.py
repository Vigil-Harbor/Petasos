"""Whether protection is on, and what each scanner is doing.

The shape is a status line a later diagnostics report can add fields to.
Scanner construction is the registry's. This module does not start a download.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from petasos.config.layers import resolve
from petasos.config.schema import ConfigError
from petasos.hermes.dashboard.catalog import stored_document
from petasos.hermes.dashboard.errors import envelope
from petasos.scanners.registry import (
    REGISTRY,
    BuildContext,
    ScannerSpec,
    compose,
    fix_for,
    recommendations,
)

if TYPE_CHECKING:
    from petasos.hermes.dashboard.scope import HomeState

logger = logging.getLogger("petasos.hermes.dashboard")


def status(
    state: HomeState,
    *,
    registry: tuple[ScannerSpec, ...] | None = None,
    home_label: str = "",
) -> dict[str, Any]:
    """Protection, the two switches, and each scanner, for ``state``."""
    import petasos

    document = stored_document(state.stored)
    settings_error: dict[str, str] | None = None
    resolved = None
    if not state.readable:
        settings_error = {
            "path": "",
            "message": "The settings file could not be read.",
        }
    else:
        try:
            resolved = resolve(document)
        except ConfigError as exc:
            path, message = exc.errors[0]
            settings_error = {"path": path, "message": message}
    petasos_on = document["enabled"] is True
    if not state.readable:
        petasos_detail = "Petasos's own switch could not be read."
        petasos_flag: bool | None = None
    elif petasos_on:
        petasos_detail = "Petasos enforcement is on."
        petasos_flag = True
    else:
        petasos_detail = (
            "Petasos is paused. Tool calls are allowed through, and the pause is recorded."
        )
        petasos_flag = False
    armed = state.hermes_enabled is True and petasos_on and settings_error is None
    protection = "on" if armed else "off"
    scanners, advice = _scanners(
        None if resolved is None else resolved.config,
        registry if registry is not None else REGISTRY,
        None if resolved is None else document["role"],
    )
    return envelope(
        protection=protection,
        switches={
            "hermes": {"on": state.hermes_enabled, "detail": state.hermes_detail},
            "petasos": {"on": petasos_flag, "detail": petasos_detail},
        },
        settings={"valid": settings_error is None and state.readable, "error": settings_error},
        scanners=scanners,
        recommendations=list(advice),
        role=document["role"] if isinstance(document["role"], str) else None,
        level=document["level"] if isinstance(document["level"], str) else None,
        secrets=dict(state.secrets),
        home=home_label,
        petasos_version=petasos.__version__,
    )


def _scanners(
    config: Any,
    registry: tuple[ScannerSpec, ...],
    role: str | None,
) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    syntactic = {
        "id": "syntactic",
        "label": "Basic checks",
        "state": "active",
        "reason": None,
        "fix": None,
        "extra": None,
    }
    if config is None:
        return [syntactic], ()
    try:
        composition = compose(config, BuildContext(), registry=registry)
    except Exception:
        logger.exception("scanner composition failed")
        return (
            [
                syntactic,
                {
                    "id": "scanners",
                    "label": "Optional scanners",
                    "state": "unavailable",
                    "reason": "The scanners could not be checked.",
                    "fix": "Try again. If it keeps happening, the detail is in the log.",
                    "extra": None,
                },
            ],
            (),
        )
    rows = [syntactic]
    for item in composition.statuses:
        rows.append(
            {
                "id": item.id,
                "label": item.label,
                "state": item.state,
                "reason": item.reason,
                "fix": fix_for(item),
                "extra": item.extra,
            }
        )
    return rows, recommendations(composition, role)
