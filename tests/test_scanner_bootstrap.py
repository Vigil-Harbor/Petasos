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

import importlib.util
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, cast

import pytest

import petasos.scanners  # noqa: F401  (ensures sys.modules carries the package)
from petasos import PetasosConfig
from petasos._types import ScanResult
from petasos.scanners import MinimalScanner, ScannerBuildStatus, build_scanners
from petasos.scanners.presidio import DEFAULT_PRESIDIO_ENTITIES

if TYPE_CHECKING:
    import types

    from petasos._types import Direction

# ---------------------------------------------------------------------------
# reference_plugin import via file path (same idiom as test_plugin_init_logging)
# ---------------------------------------------------------------------------

_REF_PLUGIN_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "deployment"
    / "reference_plugin"
    / "__init__.py"
)


def _import_reference_plugin() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        "petasos_reference_plugin", str(_REF_PLUGIN_PATH)
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _scanners_module() -> types.ModuleType:
    """The module object a ``from petasos.scanners import X`` actually resolves to.

    ``tests/test_scanner_init.py`` reimports ``petasos.scanners`` and then restores
    ``sys.modules`` from a snapshot, which can leave the ``scanners`` *attribute*
    on the ``petasos`` package pointing at a different module object than
    ``sys.modules`` does. Both callers (and ``build_scanners`` itself) import
    function-locally, and that path reads ``sys.modules`` — so patches must land
    there, not on ``petasos.scanners`` resolved through the package attribute.
    """
    return sys.modules["petasos.scanners"]


def _reset_plugin(ref: types.ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """The plugin-reset idiom from tests/test_profile_rebind.py."""
    monkeypatch.setattr(ref, "_config", {})
    monkeypatch.setattr(ref, "_initialized", False)
    monkeypatch.setattr(ref, "_init_error", None)
    monkeypatch.setattr(ref, "_pipeline", None)
    monkeypatch.setattr(ref, "_guard", None)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("PETASOS_LICENSE_KEY", "PETASOS_SESSION_SECRET", "PETASOS_HASH_KEY"):
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
    monkeypatch.setattr(
        _scanners_module(), "LlmGuardScanner", _fake_class(scanner_name="llm_guard"), raising=False
    )
    monkeypatch.setattr(
        _scanners_module(),
        "LlamaFirewallScanner",
        _fake_class(scanner_name="llama_firewall"),
        raising=False,
    )
    _patch_presidio(monkeypatch, _fake_class(scanner_name="presidio"))

    scanners, statuses = build_scanners(PetasosConfig())

    assert [s.name for s in scanners] == ["minimal", "llm_guard", "llama_firewall", "presidio"]
    assert [s.scanner_id for s in statuses] == ["llm_guard", "llama_firewall", "presidio"]
    # No status record for the MinimalScanner: neither caller logs one.
    assert not any(s.scanner_id == "minimal" for s in statuses)


def test_scanner_id_matches_scanner_name() -> None:
    """The hardcoded ``scanner_id`` must equal the backend's ``Scanner.name``.

    Deliberately unpatched: the fakes cannot pin this (they would only compare a
    string the test author typed twice). Per D0 the three real wrapper classes
    always import and their constructors only assign attributes, so they are
    constructible on the ML-free lane with no backend present.
    """
    from petasos.scanners import LlamaFirewallScanner, LlmGuardScanner, PresidioScanner

    _, statuses = build_scanners(PetasosConfig())
    by_id = {s.scanner_id for s in statuses}
    assert by_id == {LlmGuardScanner().name, LlamaFirewallScanner().name, PresidioScanner().name}


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
    monkeypatch.delattr(_scanners_module(), "LlmGuardScanner", raising=False)
    monkeypatch.setattr(
        _scanners_module(),
        "LlamaFirewallScanner",
        _fake_class(scanner_name="llama_firewall", ctor_exc=RuntimeError("boom")),
        raising=False,
    )
    _patch_presidio(
        monkeypatch, _fake_class(scanner_name="presidio", probe_exc=RuntimeError("probe boom"))
    )
    scanners, statuses = build_scanners(PetasosConfig())
    assert [s.outcome for s in statuses] == ["missing", "failed", "failed"]
    assert scanners[0].name == "minimal"


# ---------------------------------------------------------------------------
# Caller formatting (Done-when #4)
# ---------------------------------------------------------------------------

_FOUR_OUTCOMES: list[ScannerBuildStatus] = [
    ScannerBuildStatus("llm_guard", "LLM Guard", "verified"),
    ScannerBuildStatus("llama_firewall", "LlamaFirewall", "degraded", "no model"),
    ScannerBuildStatus("presidio", "Presidio", "missing", "import blew up"),
    ScannerBuildStatus("extra_backend", "Extra Backend", "failed", "kaboom"),
]


def _patch_build_scanners(
    monkeypatch: pytest.MonkeyPatch, statuses: list[ScannerBuildStatus]
) -> None:
    """Patch on ``petasos.scanners``, NOT on the caller module.

    Both callers import ``build_scanners`` function-locally, and a function-local
    ``from X import Y`` reads the attribute off ``X`` at call time and binds a
    local — patching the caller module has no effect (and would raise
    ``AttributeError``, since the name never lands there).
    """

    def _fake_build(config: Any) -> tuple[list[Any], list[ScannerBuildStatus]]:
        return [MinimalScanner()], list(statuses)

    monkeypatch.setattr(_scanners_module(), "build_scanners", _fake_build)


class TestCallerFormatting:
    def test_console_renders_all_four_outcomes(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from petasos.console._standalone import build_dashboard_pipeline

        _patch_build_scanners(monkeypatch, _FOUR_OUTCOMES)
        with caplog.at_level(logging.DEBUG):
            build_dashboard_pipeline({})

        rendered = {r.getMessage(): r.levelno for r in caplog.records}
        assert rendered["Dashboard scanner LLM Guard: backend verified"] == logging.INFO
        assert (
            rendered[
                "Dashboard scanner LlamaFirewall: backend missing — registered degraded: no model"
            ]
            == logging.WARNING
        )
        assert rendered["Dashboard scanner Presidio: import failed"] == logging.WARNING
        assert rendered["Dashboard scanner Extra Backend failed: kaboom"] == logging.WARNING
        # The unavailable list keeps display-name vocabulary.
        assert any(
            "unavailable=['LlamaFirewall', 'Presidio', 'Extra Backend']" in m for m in rendered
        )

    def test_plugin_renders_all_four_outcomes(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ref = _import_reference_plugin()
        _reset_plugin(ref, monkeypatch)
        _patch_build_scanners(monkeypatch, _FOUR_OUTCOMES)

        with caplog.at_level(logging.DEBUG):
            ref._deferred_init()

        rendered = {r.getMessage(): r.levelno for r in caplog.records}
        assert rendered["LLM Guard backend verified — scanner active"] == logging.INFO
        assert (
            rendered[
                "LlamaFirewall backend missing — scanner registered degraded "
                "(every scan will error): no model"
            ]
            == logging.WARNING
        )
        assert rendered["Presidio not installed — PII detection unavailable"] == logging.INFO
        assert rendered["Extra Backend failed to load: kaboom"] == logging.WARNING
        # The startup summary keeps snake ids.
        assert any(
            "unavailable=['llama_firewall', 'presidio', 'extra_backend']" in m for m in rendered
        )


class TestPluginNotInstalledTable:
    def test_unknown_scanner_id_uses_fallback_message(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A backend absent from ``_NOT_INSTALLED_MSG`` renders the generic line
        and must not KeyError inside ``_deferred_init``'s outer try (which would
        latch ``_init_error`` and boot the plugin unenforcing)."""
        ref = _import_reference_plugin()
        _reset_plugin(ref, monkeypatch)
        _patch_build_scanners(
            monkeypatch, [ScannerBuildStatus("brand_new", "Brand New", "missing", "nope")]
        )

        with caplog.at_level(logging.DEBUG):
            ref._deferred_init()

        assert any(r.getMessage() == "Brand New not installed, skipped" for r in caplog.records)
        assert ref._init_error is None
        assert ref._initialized is True


# ---------------------------------------------------------------------------
# Enforcement parity (Done-when #1)
# ---------------------------------------------------------------------------


class TestEnforcementParity:
    def test_both_bootstraps_construct_identically(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Regression for PET-174: one non-default config, two bootstraps, one
        set of Presidio constructor arguments."""
        from petasos.console._standalone import build_dashboard_pipeline

        fake = _patch_presidio(monkeypatch, _fake_class(scanner_name="presidio"))
        raw: dict[str, Any] = {
            "host_id": "test-host",
            "enabled": True,
            "presidio_entities": ["US_SSN"],
            "presidio_entities_extra": ["URL"],
            "presidio_score_threshold": 0.9,
            "decode_encoded_payloads": False,
        }

        # Each path gets its OWN copy: the console copies defensively, but
        # _deferred_init pops host_id/enabled off _config in place.
        console_pipeline = build_dashboard_pipeline(dict(raw))

        ref = _import_reference_plugin()
        _reset_plugin(ref, monkeypatch)
        monkeypatch.setattr(ref, "_config", dict(raw))
        ref._deferred_init()
        assert ref._init_error is None
        plugin_pipeline = ref._pipeline

        assert len(fake.calls) == 2
        assert fake.calls[0] == fake.calls[1]
        assert fake.calls[0] == {"entities": ["US_SSN", "URL"], "score_threshold": 0.9}

        for pipeline in (console_pipeline, plugin_pipeline):
            minimal = pipeline._minimal_scanner
            assert minimal is not None
            assert minimal._decode_encoded_payloads is False

    def test_plugin_honors_decode_flag_at_startup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The regression that would have caught PET-174: the plugin-path minimal
        scanner reflects ``decode_encoded_payloads: false`` BEFORE any reconfigure."""
        ref = _import_reference_plugin()
        _reset_plugin(ref, monkeypatch)
        monkeypatch.setattr(ref, "_config", {"decode_encoded_payloads": False})
        ref._deferred_init()

        assert ref._init_error is None
        minimal = ref._pipeline._minimal_scanner
        assert minimal is not None
        assert minimal._decode_encoded_payloads is False
