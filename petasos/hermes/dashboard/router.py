"""HTTP routes Hermes mounts at ``/api/plugins/petasos/``.

The route functions catch every failure and return :func:`error_body`.
They hold no data of their own: each call reads the active home and calls
the plain functions in this package.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from petasos.hermes.dashboard.activity import (
    DEFAULT_LIMIT,
    ActivityQuery,
    read_event,
    read_page,
    summarize,
)
from petasos.hermes.dashboard.catalog import read_settings
from petasos.hermes.dashboard.changes import clear_overrides, preview, save_settings
from petasos.hermes.dashboard.errors import ApiError, envelope, error_body
from petasos.hermes.dashboard.examples import DEFAULT_EXAMPLE, examples
from petasos.hermes.dashboard.playground import try_input
from petasos.hermes.dashboard.scope import active_home, load_home, require_plugin_dir
from petasos.hermes.dashboard.status import status
from petasos.hermes.home import display_path
from petasos.hermes.host import managed_keys
from petasos.hermes.settings import write_settings

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

logger = logging.getLogger("petasos.hermes.dashboard")


def build_router() -> Any:
    """The router Hermes mounts. Importing this module does not import a web framework."""
    from fastapi import APIRouter
    from fastapi.responses import JSONResponse

    router = APIRouter()

    def _wrap(handler: Any) -> Any:
        async def wrapped(request: Any) -> Any:
            try:
                return JSONResponse(await handler(request))
            except ApiError as exc:
                return JSONResponse(error_body(exc), status_code=exc.status)
            except Exception:
                logger.exception("petasos dashboard request failed")
                failure = ApiError(
                    "internal",
                    "Petasos could not finish that request. The detail is in the log.",
                    status=500,
                )
                return JSONResponse(error_body(failure), status_code=500)

        return wrapped

    router.add_route("/status", _wrap(_status), methods=["GET"])
    router.add_route("/settings", _wrap(_read_settings), methods=["GET"])
    router.add_route("/settings/preview", _wrap(_preview), methods=["POST"])
    router.add_route("/settings", _wrap(_save), methods=["PUT"])
    router.add_route("/overrides", _wrap(_clear_all), methods=["DELETE"])
    router.add_route("/overrides/{path:path}", _wrap(_clear_one), methods=["DELETE"])
    router.add_route("/playground", _wrap(_playground), methods=["POST"])
    router.add_route("/playground/examples", _wrap(_examples), methods=["GET"])
    router.add_route("/activity", _wrap(_activity), methods=["GET"])
    router.add_route("/activity/summary", _wrap(_summary), methods=["GET"])
    router.add_route("/activity/{scan_id}", _wrap(_one_event), methods=["GET"])
    return router


def _writer(values: Mapping[str, object], plugin_dir: Path) -> None:
    write_settings(values, plugin_dir=plugin_dir)


def _redactor() -> Any:
    from petasos.hermes.host import load_redactor

    loaded = load_redactor()
    if not callable(loaded):
        return None
    return loaded


async def _status(_request: Any) -> dict[str, Any]:
    state = load_home(active_home())
    return status(state, home_label=display_path(state.home))


async def _read_settings(_request: Any) -> dict[str, Any]:
    state = load_home(active_home())
    if not state.readable:
        raise ApiError("unreadable", "The settings file could not be read.", status=500)
    return read_settings(state.stored, secrets=state.secrets, managed=managed_keys())


async def _preview(request: Any) -> dict[str, Any]:
    state = load_home(active_home())
    body = await _object(request)
    return preview(state.stored, body)


async def _save(request: Any) -> dict[str, Any]:
    state = load_home(active_home())
    if not state.readable:
        raise ApiError("unreadable", "The settings file could not be read, so nothing was saved.")
    plugin_dir = require_plugin_dir(state)
    body = await _object(request)
    return save_settings(
        state.stored,
        body,
        plugin_dir=plugin_dir,
        write=_writer,
        secrets=state.secrets,
        managed=managed_keys(),
    )


async def _clear_all(_request: Any) -> dict[str, Any]:
    return await _clear(None)


async def _clear_one(request: Any) -> dict[str, Any]:
    path = str(request.path_params.get("path", ""))
    return await _clear(path)


async def _clear(path: str | None) -> dict[str, Any]:
    state = load_home(active_home())
    if not state.readable:
        raise ApiError(
            "unreadable",
            "The settings file could not be read, so nothing was changed.",
        )
    plugin_dir = require_plugin_dir(state)
    return clear_overrides(
        state.stored,
        path,
        plugin_dir=plugin_dir,
        write=_writer,
        secrets=state.secrets,
        managed=managed_keys(),
    )


async def _playground(request: Any) -> dict[str, Any]:
    state = load_home(active_home())
    body = await _object(request)
    text = body.get("text")
    tool = body.get("tool")
    arguments = body.get("arguments")
    direction = body.get("direction")
    candidate = body.get("settings")
    if candidate is not None and not isinstance(candidate, dict):
        raise ApiError("invalid_input", "Settings must be an object.")
    known = {"text", "tool", "arguments", "direction", "settings"}
    extra = sorted(key for key in body if key not in known)
    if extra:
        raise ApiError("invalid_input", "The request has fields this preview does not use.")
    return await try_input(
        state.stored,
        text=text if isinstance(text, str) or text is None else text,
        direction=direction if isinstance(direction, str) or direction is None else None,
        tool=tool if isinstance(tool, str) or tool is None else None,
        arguments=arguments if isinstance(arguments, dict) or arguments is None else arguments,
        candidate=candidate,
        redactor=_redactor(),
        protected_paths=lambda: _protected(state.home),
    )


async def _examples(_request: Any) -> dict[str, Any]:
    return envelope(examples=examples(), default=DEFAULT_EXAMPLE)


async def _activity(request: Any) -> dict[str, Any]:
    state = load_home(active_home())
    query = _query(request)
    cursor = request.query_params.get("cursor") or None
    return read_page(
        state.spool,
        state.spool_rot,
        key=state.spool_key,
        verification=state.verification,
        query=query,
        cursor=cursor,
        redactor=_redactor(),
    )


async def _summary(request: Any) -> dict[str, Any]:
    state = load_home(active_home())
    return summarize(
        state.spool,
        state.spool_rot,
        key=state.spool_key,
        verification=state.verification,
        query=_query(request),
    )


async def _one_event(request: Any) -> dict[str, Any]:
    state = load_home(active_home())
    scan_id = str(request.path_params.get("scan_id", ""))
    return read_event(
        state.spool,
        state.spool_rot,
        scan_id,
        key=state.spool_key,
        verification=state.verification,
        redactor=_redactor(),
    )


def _query(request: Any) -> ActivityQuery:
    params = request.query_params
    limit = DEFAULT_LIMIT
    raw_limit = params.get("limit")
    if raw_limit not in (None, ""):
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError) as exc:
            raise ApiError("invalid_query", "Limit must be a whole number.") from exc
    return ActivityQuery(
        since=_when(params.get("since"), "since"),
        until=_when(params.get("until"), "until"),
        kind=_optional(params.get("kind")),
        tool=_optional(params.get("tool")),
        session=_optional(params.get("session")),
        severity=_optional(params.get("severity")),
        text=_optional(params.get("q")),
        limit=limit,
    )


def _when(value: object, name: str) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value))
    except (TypeError, ValueError) as exc:
        raise ApiError("invalid_query", f"{name} must be a time in seconds.") from exc


def _optional(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value


async def _object(request: Any) -> dict[str, Any]:
    try:
        data = await request.json()
    except Exception as exc:
        raise ApiError("invalid_json", "The request body must be a JSON object.") from exc
    if not isinstance(data, dict):
        raise ApiError("invalid_json", "The request body must be a JSON object.")
    return data


def _protected(home: Path) -> tuple[str, ...]:
    return (
        str(home / "config.yaml"),
        str(home / "plugins" / "petasos"),
        str(home / "active_profile"),
    )
