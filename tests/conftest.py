from __future__ import annotations

import importlib
import os
import pathlib
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest

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


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """PET-104 C — collection-time fail-loud guard for the extras-llm-guard lane.

    When ``PETASOS_REQUIRE_LLM_GUARD=1`` (set only in the extras-llm-guard job's
    ``env`` block), assert the real backend is importable via the same symbol
    ``LlmGuardScanner._do_load`` loads — ``llm_guard.input_scanners``, not a
    top-level ``find_spec`` — and that ``TestIntegrationWrappedStdio`` is
    collected unskipped. Otherwise fail collection loudly, naming the lane and
    the missing import. A no-op when the env var is unset, so the default
    ``ci.yml`` lane and local dev keep the existing ``@_skip_no_llm_guard``
    self-skip unchanged (spec D3).

    Controller-gated: under ``pytest-xdist`` only the controller (which lacks a
    ``workerinput`` attribute) runs this, so the message is emitted once and
    stays stable.
    """
    if os.environ.get("PETASOS_REQUIRE_LLM_GUARD") != "1":
        return
    if hasattr(config, "workerinput"):
        return

    lane = "extras-llm-guard"
    try:
        importlib.import_module("llm_guard.input_scanners")
    except ImportError as exc:
        raise pytest.UsageError(
            f"{lane} lane requires the real llm-guard extra, but importing "
            f"`llm_guard.input_scanners` (the symbol LlmGuardScanner._do_load "
            f'loads) failed: {exc}. Install with: pip install -e ".[llm-guard,dev]".'
        ) from exc

    target = "TestIntegrationWrappedStdio"
    in_class = [item for item in items if _item_class_name(item) == target]
    if not in_class:
        raise pytest.UsageError(
            f"{lane} lane: {target} (tests/test_llm_guard_wrapper.py) was not "
            f"collected. The non-weakref-able stdio path must run, not vanish."
        )
    would_skip = [
        item
        for item in in_class
        if any(mark.args and mark.args[0] for mark in item.iter_markers(name="skipif"))
    ]
    if would_skip:
        raise pytest.UsageError(
            f"{lane} lane: {target} is collected but {len(would_skip)} item(s) "
            f"would skip despite llm-guard being importable. The lane must "
            f"exercise the shield, not skip it."
        )
