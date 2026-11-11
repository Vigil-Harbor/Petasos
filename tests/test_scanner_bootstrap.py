"""PET-174 — behavior tests for the shared scanner bootstrap.

Every row runs on the ML-free ``ci.yml`` lane: the optional backends are patched
onto ``petasos.scanners`` with ``monkeypatch.setattr(..., raising=False)`` /
``monkeypatch.delattr(..., raising=False)``, so presence or absence of the extras
is irrelevant. The one deliberate exception is
``test_scanner_id_matches_scanner_name``, which must compare against the *real*
classes — comparing a fake's self-declared ``.name`` to the hardcoded
``scanner_id`` would only assert that the test author typed the same string
twice, and could not fail on the rename it exists to catch.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any, ClassVar, cast

import pytest

import petasos.scanners  # noqa: F401  (ensures sys.modules carries the package)
from petasos import PetasosConfig
from petasos._types import ScanResult
from petasos.pipeline import Pipeline
from petasos.scanners import MinimalScanner, ScannerBuildStatus, build_scanners
from petasos.scanners.presidio import DEFAULT_PRESIDIO_ENTITIES

if TYPE_CHECKING:
    import types

    from petasos._types import Direction


# ---------------------------------------------------------------------------
def _scanners_module() -> types.ModuleType:
    """The module object a ``from petasos.scanners import X`` actually resolves to.

    Both callers (and ``build_scanners`` itself) import function-locally, so
    patch the canonical cached module. Import-isolation fixtures must also
    restore the parent package binding to keep dotted targets consistent.
    """
    return sys.modules["petasos.scanners"]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("PETASOS_SESSION_SECRET", "PETASOS_HASH_KEY"):
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# Recording fakes — the FULL Scanner protocol, as _validate_scanner enforces it
# ---------------------------------------------------------------------------


class _BaseFakeScanner:
    """A fake with no ``availability`` attribute at all.

    ``scan`` carries the complete protocol signature (``petasos/_types.py``
    ``_validate_scanner``): a narrower ``async def scan(self, text)`` raises
    ``TypeError`` at ``Pipeline.__init__``, which both parity rows would hit.
    """

    scanner_name: ClassVar[str] = "fake"
    ctor_exc: ClassVar[BaseException | None] = None
    calls: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, **kwargs: Any) -> None:
        exc = type(self).ctor_exc
        if exc is not None:
            raise exc
        type(self).calls.append(dict(kwargs))

    @property
    def name(self) -> str:
        return type(self).scanner_name

    async def scan(
        self,
        text: str,
        *,
        direction: Direction = "inbound",
        session_id: str | None = None,
    ) -> ScanResult:
        return ScanResult(scanner_name=self.name, findings=())


class _ProbingFakeScanner(_BaseFakeScanner):
    """A fake that also implements ``availability()``."""

    probe: ClassVar[tuple[Any, ...]] = (True, None, None)
    probe_exc: ClassVar[BaseException | None] = None

    def availability(self) -> tuple[Any, ...]:
        exc = type(self).probe_exc
        if exc is not None:
            raise exc
        return type(self).probe


def _fake_class(
    *,
    scanner_name: str = "fake",
    probe: tuple[Any, ...] = (True, None, None),
    probe_exc: BaseException | None = None,
    ctor_exc: BaseException | None = None,
) -> type[_ProbingFakeScanner]:
    class _Fake(_ProbingFakeScanner):
        calls: ClassVar[list[dict[str, Any]]] = []

    _Fake.scanner_name = scanner_name
    _Fake.probe = probe
    _Fake.probe_exc = probe_exc
    _Fake.ctor_exc = ctor_exc
    return _Fake


def _no_probe_class(*, scanner_name: str = "fake") -> type[_BaseFakeScanner]:
    class _Fake(_BaseFakeScanner):
        calls: ClassVar[list[dict[str, Any]]] = []

    _Fake.scanner_name = scanner_name
    return _Fake


def _patch_presidio(
    monkeypatch: pytest.MonkeyPatch, cls: type[_BaseFakeScanner]
) -> type[_BaseFakeScanner]:
    monkeypatch.setattr(_scanners_module(), "PresidioScanner", cls, raising=False)
    return cls


def _status_by_id(statuses: list[ScannerBuildStatus], scanner_id: str) -> ScannerBuildStatus:
    matches = [s for s in statuses if s.scanner_id == scanner_id]
    assert len(matches) == 1, f"expected exactly one {scanner_id} status, got {statuses}"
    return matches[0]


# ---------------------------------------------------------------------------
# Constructor arguments (Done-when #2)
# ---------------------------------------------------------------------------


def test_minimal_gets_decode_flag() -> None:
    scanners, _ = build_scanners(PetasosConfig(decode_encoded_payloads=False))
    assert cast("MinimalScanner", scanners[0])._decode_encoded_payloads is False

    scanners, _ = build_scanners(PetasosConfig())
    assert cast("MinimalScanner", scanners[0])._decode_encoded_payloads is True


def test_presidio_gets_entities_and_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _patch_presidio(monkeypatch, _fake_class(scanner_name="presidio"))
    build_scanners(
        PetasosConfig(
            presidio_entities=("US_SSN",),
            presidio_entities_extra=("URL",),
            presidio_score_threshold=0.9,
        )
    )
    assert fake.calls == [{"entities": ["US_SSN", "URL"], "score_threshold": 0.9}]


def test_presidio_default_entities(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _patch_presidio(monkeypatch, _fake_class(scanner_name="presidio"))
    build_scanners(PetasosConfig(presidio_entities=None))
    assert fake.calls[0]["entities"] == list(DEFAULT_PRESIDIO_ENTITIES)


# ---------------------------------------------------------------------------
# Ordering + vocabulary contracts (D1)
# ---------------------------------------------------------------------------


def test_scanner_order_and_status_order(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_presidio(monkeypatch, _fake_class(scanner_name="presidio"))
    monkeypatch.setattr(
        _scanners_module(),
        "PromptGuardScanner",
        _fake_class(scanner_name="prompt_guard"),
        raising=False,
    )

    scanners, statuses = build_scanners(PetasosConfig())

    assert [s.name for s in scanners] == [
        "minimal",
        "presidio",
        "prompt_guard",
    ]
    assert [s.scanner_id for s in statuses] == [
        "presidio",
        "prompt_guard",
    ]
    # No status record for the MinimalScanner: neither caller logs one.
    assert not any(s.scanner_id == "minimal" for s in statuses)


def test_scanner_id_matches_scanner_name() -> None:
    """The hardcoded ``scanner_id`` must equal the backend's ``Scanner.name``.

    Deliberately unpatched: the fakes cannot pin this (they would only compare a
    string the test author typed twice). Per D0 the three real wrapper classes
    always import and their constructors only assign attributes, so they are
    constructible on the ML-free lane with no backend present.
    """
    from petasos.scanners import (
        PresidioScanner,
        PromptGuardScanner,
    )

    _, statuses = build_scanners(PetasosConfig())
    by_id = {s.scanner_id for s in statuses}
    assert by_id == {
        PresidioScanner().name,
        PromptGuardScanner().name,
    }


# ---------------------------------------------------------------------------
# Outcome classification (D1 steps 1-5)
# ---------------------------------------------------------------------------


def test_absent_class_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(_scanners_module(), "PresidioScanner", raising=False)
    scanners, statuses = build_scanners(PetasosConfig())
    status = _status_by_id(statuses, "presidio")
    assert status.outcome == "missing"
    assert status.reason
    assert not any(s.name == "presidio" for s in scanners)


def test_ctor_raising_importerror_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """A present class whose ctor raises ImportError also classifies ``missing``."""
    _patch_presidio(
        monkeypatch, _fake_class(scanner_name="presidio", ctor_exc=ImportError("no backend"))
    )
    scanners, statuses = build_scanners(PetasosConfig())
    status = _status_by_id(statuses, "presidio")
    assert status.outcome == "missing"
    assert status.reason == "no backend"
    assert not any(s.name == "presidio" for s in scanners)


def test_degraded_probe_status(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_presidio(
        monkeypatch, _fake_class(scanner_name="presidio", probe=(False, "no model", None))
    )
    scanners, statuses = build_scanners(PetasosConfig())
    status = _status_by_id(statuses, "presidio")
    assert status.outcome == "degraded"
    assert status.reason == "no model"
    # degraded ALWAYS means an instance is registered.
    assert any(s.name == "presidio" for s in scanners)


def test_probe_raise_keeps_scanner_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    """Append-before-probe: a throwing availability() does not unregister."""
    _patch_presidio(
        monkeypatch, _fake_class(scanner_name="presidio", probe_exc=RuntimeError("probe blew up"))
    )
    scanners, statuses = build_scanners(PetasosConfig())
    status = _status_by_id(statuses, "presidio")
    assert status.outcome == "failed"
    assert status.reason == "probe blew up"
    assert any(s.name == "presidio" for s in scanners)


def test_probe_raising_importerror_is_failed_not_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pins the two-`try` split and the "missing implies no instance" contract."""
    _patch_presidio(
        monkeypatch, _fake_class(scanner_name="presidio", probe_exc=ImportError("late import"))
    )
    scanners, statuses = build_scanners(PetasosConfig())
    status = _status_by_id(statuses, "presidio")
    assert status.outcome == "failed"
    assert any(s.name == "presidio" for s in scanners)


def test_two_tuple_probe_tolerated(monkeypatch: pytest.MonkeyPatch) -> None:
    """PET-103 D4 arity tolerance: a legacy 2-tuple is not a `failed`."""
    _patch_presidio(monkeypatch, _fake_class(scanner_name="presidio", probe=(False, "legacy")))
    _, statuses = build_scanners(PetasosConfig())
    assert _status_by_id(statuses, "presidio").outcome == "degraded"
    assert _status_by_id(statuses, "presidio").reason == "legacy"

    _patch_presidio(monkeypatch, _fake_class(scanner_name="presidio", probe=(True, None)))
    _, statuses = build_scanners(PetasosConfig())
    assert _status_by_id(statuses, "presidio").outcome == "verified"


def test_no_probe_attribute_is_verified(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_presidio(monkeypatch, _no_probe_class(scanner_name="presidio"))
    scanners, statuses = build_scanners(PetasosConfig())
    status = _status_by_id(statuses, "presidio")
    assert status.outcome == "verified"
    assert status.reason is None
    assert any(s.name == "presidio" for s in scanners)


def test_ctor_failure_status(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_presidio(
        monkeypatch, _fake_class(scanner_name="presidio", ctor_exc=RuntimeError("bad ctor"))
    )
    scanners, statuses = build_scanners(PetasosConfig())
    status = _status_by_id(statuses, "presidio")
    assert status.outcome == "failed"
    assert status.reason == "bad ctor"
    assert not any(s.name == "presidio" for s in scanners)


def test_build_scanners_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every optional-backend failure arm returns normally."""
    monkeypatch.delattr(_scanners_module(), "PresidioScanner", raising=False)
    monkeypatch.setattr(
        _scanners_module(),
        "PromptGuardScanner",
        _fake_class(scanner_name="prompt_guard", ctor_exc=RuntimeError("boom")),
        raising=False,
    )
    scanners, statuses = build_scanners(PetasosConfig())
    assert [s.outcome for s in statuses] == ["missing", "failed"]
    assert scanners[0].name == "minimal"


class TestDisabledScanners:
    def test_disabled_backend_is_skipped_and_still_statused(self) -> None:
        config = PetasosConfig(disabled_scanners=("presidio",))
        scanners, statuses = build_scanners(config)
        by_id = {status.scanner_id: status for status in statuses}
        assert [status.scanner_id for status in statuses] == [
            "presidio",
            "prompt_guard",
        ]
        assert by_id["presidio"].outcome == "disabled"
        assert by_id["presidio"].reason == "disabled by config"
        assert [scanner.name for scanner in scanners if scanner.name == "presidio"] == []
        assert scanners[0].name == "minimal"


# ---------------------------------------------------------------------------
# PET-242 Decision 13: the fourth backend fails toward blocking, not softened
# ---------------------------------------------------------------------------


class TestPromptGuardUpgradeBehavior:
    _BENIGN = "please list the files in this folder"

    @pytest.fixture(autouse=True)
    def _no_prompt_guard(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import petasos.scanners.prompt_guard as pg

        pg._reset_for_tests()
        monkeypatch.setattr(
            pg, "_availability", lambda: (False, pg._INSTALL_HINT, "absent"), raising=True
        )

    async def _safe(self, config: PetasosConfig) -> bool:
        scanners, _statuses = build_scanners(config)
        return (await Pipeline(scanners=scanners, config=config).inspect(self._BENIGN)).safe

    async def test_presidio_disabled_blocks_until_prompt_guard_is_listed(self) -> None:
        assert (
            await self._safe(PetasosConfig(fail_mode="closed", disabled_scanners=("presidio",)))
            is False
        )
        assert (
            await self._safe(
                PetasosConfig(fail_mode="closed", disabled_scanners=("presidio", "prompt_guard"))
            )
            is True
        )

    async def test_healthy_presidio_blocks_until_prompt_guard_is_listed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_presidio(monkeypatch, _fake_class(scanner_name="presidio"))
        assert await self._safe(PetasosConfig(fail_mode="degraded")) is False
        assert (
            await self._safe(
                PetasosConfig(fail_mode="degraded", disabled_scanners=("prompt_guard",))
            )
            is True
        )


def test_semgrep_enabled_without_owner_never_constructs_or_probes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from petasos.scanners.semgrep import SemgrepScanner

    calls = []

    def forbidden(*args: Any, **kwargs: Any) -> None:
        calls.append(True)
        raise AssertionError("ownerless adapter construction")

    monkeypatch.setattr(SemgrepScanner, "__init__", forbidden)
    config = PetasosConfig(
        semgrep_enabled=True,
        disabled_scanners=("presidio", "prompt_guard"),
    )
    scanners, statuses = build_scanners(config)
    status = _status_by_id(statuses, "semgrep")
    assert status.outcome == "failed"
    assert status.reason == "semgrep.host_lifecycle_unavailable"
    assert [scanner.name for scanner in scanners] == ["minimal"]
    assert not calls
