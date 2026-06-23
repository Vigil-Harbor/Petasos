from __future__ import annotations

import importlib
import os
import pathlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import jwt as pyjwt
import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

_FIXTURES = pathlib.Path(__file__).parent / "fixtures"
_PRIVATE_KEY = (_FIXTURES / "test_private.pem").read_bytes()


def _make_token(
    *,
    tier: str = "pro",
    customer_id: str = "cust-test",
    features: list[str] | None = None,
    exp_delta: timedelta = timedelta(hours=1),
    iat_delta: timedelta = timedelta(seconds=0),
    extra_claims: dict[str, object] | None = None,
    algorithm: str = "EdDSA",
    key: bytes | None = None,
) -> str:
    now = datetime.now(tz=timezone.utc)
    payload: dict[str, object] = {
        "sub": "petasos-license",
        "exp": now + exp_delta,
        "iat": now + iat_delta,
        "tier": tier,
        "customer_id": customer_id,
        "features": features or [],
    }
    if extra_claims:
        payload.update(extra_claims)
    return pyjwt.encode(payload, key or _PRIVATE_KEY, algorithm=algorithm)


@pytest.fixture(autouse=True)
def _isolate_enforcement_spool(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """PET-131: redirect the cross-process enforcement spool to a throwaway temp path
    for every test.

    The dashboard now drains this spool on ``get_scan_history`` and the gateway
    ``_pre_tool_call`` block branches append to it, so without isolation a test could
    read the real machine spool (``%LOCALAPPDATA%/hermes/petasos-enforcement.jsonl``)
    or pollute it. Tests that inspect the spool read ``_events._spool_path()``, which
    returns this per-test path. A no-op if the console module is unimportable.
    """
    try:
        import petasos.console._events as _ev
    except Exception:
        yield
        return
    saved_override = _ev._SPOOL_PATH_OVERRIDE
    saved_cap = _ev.SPOOL_CAP_BYTES
    _ev._reset_events_state(str(tmp_path_factory.mktemp("enf_spool") / "enf.jsonl"))
    try:
        yield
    finally:
        _ev._SPOOL_PATH_OVERRIDE = saved_override
        _ev.SPOOL_CAP_BYTES = saved_cap


@pytest.fixture(autouse=True)
def _isolate_history_sink(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """PET-148: redirect the persistent scan-history sink to a throwaway temp path for
    every test (mirrors ``_isolate_enforcement_spool``).

    ``ConsoleHandlers._record_scan`` now appends every recorded scan to this on-disk sink,
    so without isolation a test would write to the real machine state dir
    (``%LOCALAPPDATA%/hermes/petasos-scan-history.jsonl``) or read it back. Tests that
    inspect the sink read ``_history._history_path()``, which returns this per-test path.
    A no-op if the console module is unimportable.
    """
    try:
        import petasos.console._history as _hist
    except Exception:
        yield
        return
    saved_override = _hist._HISTORY_PATH_OVERRIDE
    saved_cap = _hist._HISTORY_CAP_BYTES
    _hist._reset_history_state(str(tmp_path_factory.mktemp("hist_sink") / "hist.jsonl"))
    try:
        yield
    finally:
        _hist._HISTORY_PATH_OVERRIDE = saved_override
        _hist._HISTORY_CAP_BYTES = saved_cap


@pytest.fixture()
def valid_token() -> str:
    return _make_token()


@pytest.fixture()
def expired_token() -> str:
    return _make_token(exp_delta=timedelta(hours=-1), iat_delta=timedelta(hours=-2))


@pytest.fixture()
def valid_key() -> str:
    return _make_token()


def _item_class_name(item: pytest.Item) -> str | None:
    """Return the name of the test class owning ``item``, or None for module-level
    functions. ``cls`` is a ``pytest.Function`` attribute, absent on bare items."""
    cls = getattr(item, "cls", None)
    if cls is None:
        return None
    name: str = cls.__name__
    return name


def _would_skip(item: pytest.Item) -> bool:
    """True if ``item`` carries a decoration-time skip — either a plain
    ``@pytest.mark.skip`` (unconditional) or a truthy ``@pytest.mark.skipif``.

    A plain ``skip`` is not a ``skipif`` and would otherwise sail past the guard,
    skipping the target class despite the backend being importable — exactly what
    a non-skipping lane must catch. Module-level (PET-105 DD) so both lane guards
    share one definition and cannot drift. A *runtime* ``pytest.skip()`` in a test
    body is invisible here by design — the target classes must never call it.
    """
    if item.get_closest_marker("skip") is not None:
        return True
    return any(mark.args and bool(mark.args[0]) for mark in item.iter_markers(name="skipif"))


def _enforce_nonskipping_lane(
    items: list[pytest.Item],
    *,
    env_flag: str,
    import_target: str,
    target_class: str,
    lane: str,
) -> None:
    """Fail collection loudly if ``lane``'s real-backend class would skip.

    Armed only when ``env_flag`` is ``"1"`` (set in the lane job's ``env`` block);
    a no-op otherwise, so the default ``ci.yml`` lane and local dev keep their
    ``@skipif`` self-skip unchanged. When armed: import ``import_target`` (the same
    symbol the scanner's ``_do_load`` loads — not a top-level ``find_spec``) and
    assert ``target_class`` is collected unskipped. The three failure shapes
    (import-failed, target-not-collected, would-skip-despite-importable) mirror the
    PET-104 guard verbatim, parameterized per lane (PET-105 DD). Each lane is
    enforced independently — see DD for the both-armed composition.
    """
    if os.environ.get(env_flag) != "1":
        return

    try:
        importlib.import_module(import_target)
    except ImportError as exc:
        raise pytest.UsageError(
            f"{lane} lane requires the real backend extra, but importing "
            f"`{import_target}` (the symbol the scanner's _do_load loads) failed: "
            f"{exc}. Install the lane's extra (see .github/workflows/{lane}.yml)."
        ) from exc

    in_class = [item for item in items if _item_class_name(item) == target_class]
    if not in_class:
        raise pytest.UsageError(
            f"{lane} lane: {target_class} was not collected. "
            f"The non-weakref-able stdio path must run, not vanish."
        )

    would_skip = [item for item in in_class if _would_skip(item)]
    if would_skip:
        raise pytest.UsageError(
            f"{lane} lane: {target_class} is collected but {len(would_skip)} item(s) "
            f"would skip despite {import_target} being importable. "
            f"The lane must exercise the path, not skip it."
        )


@dataclass(frozen=True)
class NonSkippingLane:
    """One scanner backend whose CI lane must run a real-backend class without
    skipping. PET-106: single source of truth consumed by both the runtime guard
    below and tests/test_ci_extras_lanes.py. Add a backend = add a row here +
    add .github/workflows/extras-<extra>.yml (the meta-test enforces the pair).
    Frozen dataclass per CLAUDE.md § Key Design Invariants 'Frozen exports' and
    the petasos/_types.py idiom (round-1 conventions F-1)."""

    extra: str  # pyproject optional-dependency key, e.g. "presidio"
    env_flag: str  # CI lane env var, e.g. "PETASOS_REQUIRE_PRESIDIO"
    import_target: str  # symbol the scanner's _do_load imports
    target_class: str  # test class the lane must collect unskipped
    lane: str  # workflow basename, e.g. "extras-presidio"


NONSKIPPING_LANES: tuple[NonSkippingLane, ...] = (
    NonSkippingLane(
        "llm-guard",
        "PETASOS_REQUIRE_LLM_GUARD",
        "llm_guard.input_scanners",
        "TestIntegrationWrappedStdio",
        "extras-llm-guard",
    ),
    NonSkippingLane(
        "llamafirewall",
        "PETASOS_REQUIRE_LLAMAFIREWALL",
        "llamafirewall",
        "TestProbeWeakrefUnderSlotsStdio",
        "extras-llamafirewall",
    ),
    # presidio has two must-run live-detection classes in one lane: PET-106's real
    # PII scan and PET-109's tightened-default regression. Both need the extra +
    # spaCy model, so both are armed under the same PETASOS_REQUIRE_PRESIDIO flag.
    NonSkippingLane(
        "presidio",
        "PETASOS_REQUIRE_PRESIDIO",
        "presidio_analyzer",
        "TestPresidioScannerIntegration",
        "extras-presidio",
    ),
    NonSkippingLane(
        "presidio",
        "PETASOS_REQUIRE_PRESIDIO",
        "presidio_analyzer",
        "TestPresidioTightenedDefault",
        "extras-presidio",
    ),
    NonSkippingLane(
        "presidio",
        "PETASOS_REQUIRE_PRESIDIO",
        "presidio_analyzer",
        "TestProfilePresidioScoping",  # PET-119 profile→Presidio wiring contract
        "extras-presidio",
    ),
)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Collection-time fail-loud guards for the non-skipping extras lanes.

    PET-104 armed the ``extras-llm-guard`` lane; PET-105 added ``extras-llamafirewall``
    and extracted the shared enforcement body into ``_enforce_nonskipping_lane`` so the
    structurally-identical guards cannot drift (DD). PET-106 lifts the per-lane
    arguments into the module-level ``NONSKIPPING_LANES`` table — the single source of
    truth also consumed by ``tests/test_ci_extras_lanes.py`` — and arms presidio. Adding
    a backend is one table row plus one ``extras-<extra>.yml`` lane, no new control flow.
    Each lane is gated on its own ``PETASOS_REQUIRE_*`` env var, set only in that lane
    job's ``env`` block, so the default ``ci.yml`` lane and local dev keep the existing
    ``@skipif`` self-skip.

    Controller-gated as a SINGLE top-level check (DD): under ``pytest-xdist`` only the
    controller (which lacks a ``workerinput`` attribute) runs this, so each lane's
    message is emitted once and stays stable. Hoisting the gate above the env checks is
    behavior-equivalent for the single-env-var, controller-only, no-``-n`` invocation
    these lanes use (env-unset is a no-op either way).
    """
    if hasattr(config, "workerinput"):
        return
    for ln in NONSKIPPING_LANES:
        _enforce_nonskipping_lane(
            items,
            env_flag=ln.env_flag,
            import_target=ln.import_target,
            target_class=ln.target_class,
            lane=ln.lane,
        )
