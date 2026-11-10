"""compose() turns scanner settings into a list and one status per backend."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import replace
from typing import Any

import pytest

from petasos._types import Direction, ScanResult
from petasos.config.floors import PROMPT_GUARD_THRESHOLD
from petasos.config.sections import PetasosConfig, PresidioConfig
from petasos.config.sections.scanners import PromptGuardConfig
from petasos.scanners.minimal import MinimalScanner
from petasos.scanners.presidio import DEFAULT_PRESIDIO_ENTITIES, PresidioScanner
from petasos.scanners.prompt_guard import _BLOCK_THRESHOLD, _INSTALL_HINT, PromptGuardScanner
from petasos.scanners.registry import (
    REGISTRY,
    BuildContext,
    Capability,
    Composition,
    Enabled,
    ScannerSpec,
    ScannerState,
    ScannerStatus,
    UnavailableScanner,
    compose,
    is_registered,
    recommendations,
)
from petasos.scanners.registry import (
    _build_presidio as build_presidio,
)
from petasos.scanners.registry import (
    _build_prompt_guard as build_prompt_guard,
)


def _config(
    *,
    prompt_guard: Enabled = "auto",
    presidio: Enabled = "auto",
    semgrep: Enabled = "off",
) -> PetasosConfig:
    base = PetasosConfig()
    return replace(
        base,
        scanners=replace(
            base.scanners,
            prompt_guard=replace(base.scanners.prompt_guard, enabled=prompt_guard),
            presidio=replace(base.scanners.presidio, enabled=presidio),
            semgrep=replace(base.scanners.semgrep, enabled=semgrep),
        ),
    )


class _Stub:
    def __init__(self, name: str, probe: tuple[object, ...]) -> None:
        self._name = name
        self._probe = probe

    @property
    def name(self) -> str:
        return self._name

    def availability(self) -> tuple[object, ...]:
        return self._probe

    async def scan(
        self,
        text: str,
        *,
        direction: Direction = "inbound",
        session_id: str | None = None,
    ) -> ScanResult:
        del text, direction, session_id
        return ScanResult(scanner_name=self._name, findings=(), error="stub")


class _Silent:
    """A scanner with no availability probe."""

    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def scan(
        self,
        text: str,
        *,
        direction: Direction = "inbound",
        session_id: str | None = None,
    ) -> ScanResult:
        del text, direction, session_id
        return ScanResult(scanner_name=self._name, findings=())


def _spec(
    scanner_id: str,
    build: Any,
    *,
    detects: frozenset[Capability] = frozenset({"injection"}),
    extra: str | None = "prompt-guard",
    label: str | None = None,
) -> ScannerSpec:
    return ScannerSpec(
        id=scanner_id,
        label=label or scanner_id,
        extra=extra,
        detects=detects,
        section=scanner_id,
        default_enabled="auto",
        build=build,
    )


def _names(composition: Composition) -> list[str]:
    return [scanner.name for scanner in composition.scanners]


def _by_id(composition: Composition) -> dict[str, ScannerStatus]:
    return {status.id: status for status in composition.statuses}


def test_registry_declares_the_three_backends() -> None:
    assert [spec.id for spec in REGISTRY] == ["presidio", "prompt_guard", "semgrep"]
    assert [spec.section for spec in REGISTRY] == ["presidio", "prompt_guard", "semgrep"]
    assert [spec.default_enabled for spec in REGISTRY] == ["auto", "auto", "off"]
    assert [spec.extra for spec in REGISTRY] == ["presidio", "prompt-guard", "semgrep"]
    assert [spec.label for spec in REGISTRY] == ["Presidio", "PromptGuard", "Semgrep"]
    assert REGISTRY[0].detects == frozenset({"pii"})
    assert REGISTRY[1].detects == frozenset({"injection"})
    assert REGISTRY[2].detects == frozenset({"code"})
    base = PetasosConfig()
    for spec in REGISTRY:
        assert getattr(base.scanners, spec.section).enabled == spec.default_enabled


def test_is_registered_is_only_the_state() -> None:
    assert is_registered("active") is True
    assert is_registered("unavailable") is True
    assert is_registered("not_installed") is False
    assert is_registered("off") is False


def test_base_install_leaves_auto_scanners_out() -> None:
    composition = compose(PetasosConfig(), BuildContext())
    assert _names(composition) == ["minimal"]
    statuses = _by_id(composition)
    assert statuses["presidio"].state == "not_installed"
    assert statuses["prompt_guard"].state == "not_installed"
    assert statuses["semgrep"].state == "off"
    assert statuses["presidio"].extra == "presidio"
    assert "pip install petasos[presidio]" in (statuses["presidio"].reason or "")
    assert "pip install petasos[prompt-guard]" in (statuses["prompt_guard"].reason or "")
    assert statuses["semgrep"].reason is not None
    for status in composition.statuses:
        assert (status.id in _names(composition)) is is_registered(status.state)


def test_decode_payloads_reaches_the_syntactic_scanner() -> None:
    base = PetasosConfig()
    config = replace(base, normalization=replace(base.normalization, decode_payloads=False))
    composition = compose(config, BuildContext())
    scanner = composition.scanners[0]
    assert isinstance(scanner, MinimalScanner)
    assert scanner._decode_encoded_payloads is False


def test_syntactic_constructor_failure_is_not_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    class Boom:
        def __init__(self, **kwargs: object) -> None:
            del kwargs
            raise RuntimeError("syntactic failed")

    monkeypatch.setattr("petasos.scanners.registry.MinimalScanner", Boom)
    with pytest.raises(RuntimeError, match="syntactic failed"):
        compose(PetasosConfig(), BuildContext())


def test_empty_registry_is_only_the_syntactic_scanner() -> None:
    composition = compose(PetasosConfig(), BuildContext(), registry=())
    assert _names(composition) == ["minimal"]
    assert composition.statuses == ()


@pytest.mark.parametrize(
    ("enabled", "probe", "state", "registered", "stand_in"),
    [
        ("auto", (True, None, None), "active", True, False),
        ("auto", (False, "weights missing", "load_failed"), "unavailable", True, False),
        ("auto", (False, "package missing", "absent"), "not_installed", False, False),
        ("on", (True, None, None), "active", True, False),
        ("on", (False, "weights missing", "load_failed"), "unavailable", True, False),
        ("on", (False, "package missing", "absent"), "unavailable", True, True),
        ("off", (True, None, None), "off", False, False),
        ("off", (False, "weights missing", "load_failed"), "off", False, False),
        ("off", (False, "package missing", "absent"), "off", False, False),
    ],
)
async def test_enablement_table(
    enabled: Enabled,
    probe: tuple[object, ...],
    state: ScannerState,
    registered: bool,
    stand_in: bool,
) -> None:
    built: list[_Stub] = []
    calls: list[str] = []

    def build(section: Any, context: BuildContext) -> _Stub:
        del context
        calls.append(section.enabled)
        stub = _Stub("prompt_guard", probe)
        built.append(stub)
        return stub

    composition = compose(
        _config(prompt_guard=enabled),
        BuildContext(),
        registry=(_spec("prompt_guard", build),),
    )
    status = composition.statuses[0]
    assert status.state == state
    assert status.extra == "prompt-guard"
    assert (status.id in _names(composition)) is registered
    assert (status.id in _names(composition)) is is_registered(status.state)
    if enabled == "off":
        assert calls == []
        assert status.reason is not None
        return
    assert calls == [enabled]
    if not registered:
        assert built[0] not in composition.scanners
        assert status.reason == "package missing"
        return
    scanner = composition.scanners[-1]
    if stand_in:
        assert isinstance(scanner, UnavailableScanner)
        assert scanner.reason == "package missing"
        assert (await scanner.scan("text")).error == "package missing"
        assert (await scanner.scan("")).error == "package missing"
        return
    assert scanner is built[0]
    if state == "active":
        assert status.reason is None
    else:
        assert status.reason == "weights missing"


@pytest.mark.parametrize("enabled", ["auto", "on"])
async def test_probe_that_raises_stays_registered(enabled: Enabled) -> None:
    built: list[_Stub] = []

    class _Raising(_Stub):
        def availability(self) -> tuple[object, ...]:
            raise ImportError("probe blew up")

    def build(section: Any, context: BuildContext) -> _Raising:
        del section, context
        stub = _Raising("prompt_guard", (True, None, None))
        built.append(stub)
        return stub

    composition = compose(
        _config(prompt_guard=enabled),
        BuildContext(),
        registry=(_spec("prompt_guard", build),),
    )
    status = composition.statuses[0]
    assert status.state == "unavailable"
    assert status.reason == "probe blew up"
    assert composition.scanners[-1] is built[0]
    assert is_registered(status.state) is True


@pytest.mark.parametrize("enabled", ["auto", "on"])
def test_probe_runtime_error_stays_registered(enabled: Enabled) -> None:
    class _Raising(_Stub):
        def availability(self) -> tuple[object, ...]:
            raise RuntimeError("probe crashed")

    def build(section: Any, context: BuildContext) -> _Raising:
        del section, context
        return _Raising("prompt_guard", (True, None))

    composition = compose(
        _config(prompt_guard=enabled),
        BuildContext(),
        registry=(_spec("prompt_guard", build),),
    )
    status = composition.statuses[0]
    assert status.state == "unavailable"
    assert status.reason == "probe crashed"
    assert _names(composition) == ["minimal", "prompt_guard"]


@pytest.mark.parametrize(
    ("probe", "state", "reason"),
    [
        ((False, "engine down"), "unavailable", "engine down"),
        ((True, None), "active", None),
        (
            (False, None, "load_failed"),
            "unavailable",
            "PromptGuard is installed but cannot be used.",
        ),
        (
            (False, None, "absent"),
            "not_installed",
            "PromptGuard is not installed. pip install petasos[prompt-guard]",
        ),
        ((False, "weights", "load_failed"), "unavailable", "weights"),
        ((False, "gone", "absent"), "not_installed", "gone"),
    ],
)
def test_probe_causes(
    probe: tuple[object, ...],
    state: ScannerState,
    reason: str | None,
) -> None:
    def build(section: Any, context: BuildContext) -> _Stub:
        del section, context
        return _Stub("prompt_guard", probe)

    composition = compose(
        _config(prompt_guard="auto"),
        BuildContext(),
        registry=(_spec("prompt_guard", build, label="PromptGuard"),),
    )
    status = composition.statuses[0]
    assert status.state == state
    assert status.reason == reason
    assert (status.id in _names(composition)) is is_registered(state)


def test_probe_without_availability_is_active() -> None:
    def build(section: Any, context: BuildContext) -> _Silent:
        del section, context
        return _Silent("prompt_guard")

    composition = compose(
        _config(prompt_guard="auto"),
        BuildContext(),
        registry=(_spec("prompt_guard", build),),
    )
    assert composition.statuses[0].state == "active"
    assert isinstance(composition.scanners[-1], _Silent)


def test_unexpected_probe_result_is_unavailable() -> None:
    class _Odd(_Silent):
        def availability(self) -> str:
            return "nope"

    def build(section: Any, context: BuildContext) -> _Odd:
        del section, context
        return _Odd("prompt_guard")

    composition = compose(
        _config(prompt_guard="on"),
        BuildContext(),
        registry=(_spec("prompt_guard", build),),
    )
    status = composition.statuses[0]
    assert status.state == "unavailable"
    assert status.reason == "availability probe returned an unexpected result"
    assert isinstance(composition.scanners[-1], _Odd)


@pytest.mark.parametrize(
    ("enabled", "state", "registered"),
    [("auto", "not_installed", False), ("on", "unavailable", True)],
)
async def test_builder_import_error(
    enabled: Enabled,
    state: ScannerState,
    registered: bool,
) -> None:
    def build(section: Any, context: BuildContext) -> _Stub:
        del section, context
        raise ImportError("No module named 'torch'")

    composition = compose(
        _config(prompt_guard=enabled),
        BuildContext(),
        registry=(_spec("prompt_guard", build, label="PromptGuard"),),
    )
    status = composition.statuses[0]
    assert status.state == state
    assert status.reason is not None
    assert "pip install petasos[prompt-guard]" in status.reason
    assert "No module named 'torch'" in status.reason
    assert (status.id in _names(composition)) is registered
    if registered:
        scanner = composition.scanners[-1]
        assert isinstance(scanner, UnavailableScanner)
        assert (await scanner.scan("x")).error == status.reason


@pytest.mark.parametrize("enabled", ["auto", "on"])
async def test_builder_that_raises_registers_a_stand_in(enabled: Enabled) -> None:
    def build(section: Any, context: BuildContext) -> _Stub:
        del section, context
        raise RuntimeError("disk full")

    composition = compose(
        _config(prompt_guard=enabled),
        BuildContext(),
        registry=(_spec("prompt_guard", build),),
    )
    status = composition.statuses[0]
    assert status.state == "unavailable"
    assert status.reason == "disk full"
    scanner = composition.scanners[-1]
    assert isinstance(scanner, UnavailableScanner)
    assert (await scanner.scan("x")).error == "disk full"


def test_off_does_not_call_a_builder_that_would_raise() -> None:
    def build(section: Any, context: BuildContext) -> _Stub:
        del section, context
        raise AssertionError("builder was called")

    composition = compose(
        _config(prompt_guard="off"),
        BuildContext(),
        registry=(_spec("prompt_guard", build),),
    )
    assert composition.statuses[0].state == "off"
    assert _names(composition) == ["minimal"]


def test_order_follows_the_registry_after_the_syntactic_scanner() -> None:
    def ready(scanner_id: str) -> ScannerSpec:
        def build(section: Any, context: BuildContext) -> _Stub:
            del section, context
            return _Stub(scanner_id, (True, None, None))

        detects: frozenset[Capability] = frozenset({"code"})
        return _spec(scanner_id, build, detects=detects, extra=None)

    composition = compose(
        _config(prompt_guard="on", presidio="on", semgrep="on"),
        BuildContext(),
        registry=(ready("semgrep"), ready("presidio"), ready("prompt_guard")),
    )
    assert _names(composition) == ["minimal", "semgrep", "presidio", "prompt_guard"]
    assert [status.id for status in composition.statuses] == [
        "semgrep",
        "presidio",
        "prompt_guard",
    ]
    assert {status.state for status in composition.statuses} == {"active"}


def test_one_composition_covers_registered_and_quiet_states() -> None:
    def probe_of(scanner_id: str, probe: tuple[object, ...]) -> ScannerSpec:
        def build(section: Any, context: BuildContext) -> _Stub:
            del section, context
            return _Stub(scanner_id, probe)

        return _spec(scanner_id, build, extra="presidio" if scanner_id == "presidio" else "x")

    composition = compose(
        _config(presidio="on", prompt_guard="auto", semgrep="off"),
        BuildContext(),
        registry=(
            probe_of("presidio", (False, "model missing", "load_failed")),
            probe_of("prompt_guard", (False, "missing", "absent")),
            probe_of("semgrep", (True, None, None)),
        ),
    )
    states = {status.id: status.state for status in composition.statuses}
    assert states == {
        "presidio": "unavailable",
        "prompt_guard": "not_installed",
        "semgrep": "off",
    }
    assert _names(composition) == ["minimal", "presidio"]
    for status in composition.statuses:
        assert (status.id in _names(composition)) is is_registered(status.state)
    assert {status.state for status in composition.statuses} >= {
        "unavailable",
        "not_installed",
        "off",
    }


def test_presidio_section_reaches_the_scanner_except_entities_extra() -> None:
    section = replace(
        PresidioConfig(),
        entities=("EMAIL_ADDRESS",),
        entities_extra=("URL",),
        score_threshold=0.42,
        language="de",
    )
    scanner = build_presidio(section, BuildContext())
    assert isinstance(scanner, PresidioScanner)
    assert scanner._entities == ["EMAIL_ADDRESS"]
    assert "URL" not in scanner._entities
    assert scanner._score_threshold == 0.42
    assert scanner._language == "de"
    untouched = build_presidio(PresidioConfig(), BuildContext())
    assert isinstance(untouched, PresidioScanner)
    assert untouched._entities == list(DEFAULT_PRESIDIO_ENTITIES)


def test_prompt_guard_threshold_reaches_the_scanner() -> None:
    scanner = build_prompt_guard(replace(PromptGuardConfig(), threshold=0.42), BuildContext())
    assert isinstance(scanner, PromptGuardScanner)
    assert scanner._threshold == 0.42
    default = PromptGuardScanner()
    assert default._threshold == _BLOCK_THRESHOLD == PROMPT_GUARD_THRESHOLD


async def test_prompt_guard_threshold_changes_which_scores_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "petasos.scanners.prompt_guard._scan_sync",
        lambda text, cancelled: 0.5,
    )
    low = PromptGuardScanner(threshold=0.4)
    high = PromptGuardScanner(threshold=0.9)
    assert (await low.scan("hello")).findings
    assert (await high.scan("hello")).findings == ()
    assert (await PromptGuardScanner().scan("hello")).findings == ()


async def test_turned_on_but_missing_registers_the_stand_in() -> None:
    composition = compose(
        _config(prompt_guard="on", presidio="on", semgrep="off"),
        BuildContext(),
    )
    assert _names(composition) == ["minimal", "presidio", "prompt_guard"]
    for scanner in composition.scanners[1:]:
        assert isinstance(scanner, UnavailableScanner)
        assert "pip install" in scanner.reason
        assert (await scanner.scan("hello")).error == scanner.reason
        assert (await scanner.scan("")).error == scanner.reason
    assert _by_id(composition)["prompt_guard"].reason == _INSTALL_HINT
    assert not any(isinstance(scanner, PresidioScanner) for scanner in composition.scanners)
    assert not any(isinstance(scanner, PromptGuardScanner) for scanner in composition.scanners)


def test_semgrep_off_does_not_construct(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("SemgrepScanner was constructed")

    monkeypatch.setattr("petasos.scanners.semgrep.SemgrepScanner.__init__", forbidden)
    composition = compose(PetasosConfig(), BuildContext())
    assert _by_id(composition)["semgrep"].state == "off"
    assert "semgrep" not in _names(composition)


async def test_semgrep_without_owner_is_unavailable_and_not_constructed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("SemgrepScanner was constructed")

    monkeypatch.setattr("petasos.scanners.semgrep.SemgrepScanner.__init__", forbidden)
    composition = compose(_config(semgrep="on"), BuildContext())
    status = _by_id(composition)["semgrep"]
    assert status.state == "unavailable"
    assert status.reason == "semgrep.host_lifecycle_unavailable"
    scanner = next(item for item in composition.scanners if item.name == "semgrep")
    assert isinstance(scanner, UnavailableScanner)
    assert (await scanner.scan("code")).error == "semgrep.host_lifecycle_unavailable"
    assert is_registered(status.state) is True


async def test_semgrep_rejects_a_lifecycle_that_is_the_wrong_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("SemgrepScanner was constructed")

    monkeypatch.setattr("petasos.scanners.semgrep.SemgrepScanner.__init__", forbidden)
    composition = compose(
        _config(semgrep="auto"),
        BuildContext(semgrep_lifecycle=object()),
    )
    status = _by_id(composition)["semgrep"]
    assert status.state == "unavailable"
    assert status.reason == "semgrep.host_lifecycle_unavailable"
    assert isinstance(
        next(item for item in composition.scanners if item.name == "semgrep"),
        UnavailableScanner,
    )


async def test_semgrep_with_owner_and_no_engine_stays_the_real_scanner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from petasos.scanners.semgrep import SemgrepLifecycleOwner, SemgrepScanner

    key = object()
    seen: dict[str, object] = {}
    real_init = SemgrepScanner.__init__

    def spy(self: SemgrepScanner, **kwargs: object) -> None:
        seen.update(kwargs)
        real_init(self, **kwargs)  # type: ignore[arg-type]

    async with SemgrepLifecycleOwner() as owner:
        monkeypatch.setattr(SemgrepScanner, "__init__", spy)
        composition = compose(
            _config(semgrep="on", prompt_guard="off", presidio="off"),
            BuildContext(semgrep_lifecycle=owner, semgrep_scheduling_key=key),
        )
    status = _by_id(composition)["semgrep"]
    assert status.state == "unavailable"
    assert seen["semgrep_scheduling_key"] is key
    assert seen["owner"] is owner
    scanner = composition.scanners[-1]
    if status.reason == "semgrep.unsupported_platform":
        assert isinstance(scanner, UnavailableScanner)
        return
    assert status.reason == "semgrep.engine_unavailable"
    assert isinstance(scanner, SemgrepScanner)
    assert seen["engine_path"] is None


@pytest.mark.parametrize(
    ("message", "reason"),
    [
        ("disk full", "semgrep.construction_failed"),
        ("semgrep.unsupported_platform", "semgrep.unsupported_platform"),
        ("semgrep.host_lifecycle_unavailable", "semgrep.host_lifecycle_unavailable"),
    ],
)
async def test_semgrep_constructor_errors_keep_today_reason_strings(
    monkeypatch: pytest.MonkeyPatch,
    message: str,
    reason: str,
) -> None:
    from petasos.scanners.semgrep import SemgrepLifecycleOwner, SemgrepScanner

    def boom(self: SemgrepScanner, **kwargs: object) -> None:
        del self, kwargs
        raise RuntimeError(message) if message == "disk full" else ValueError(message)

    monkeypatch.setattr(SemgrepScanner, "__init__", boom)
    async with SemgrepLifecycleOwner() as owner:
        composition = compose(
            _config(semgrep="on"),
            BuildContext(semgrep_lifecycle=owner),
        )
    status = _by_id(composition)["semgrep"]
    assert status.state == "unavailable"
    assert status.reason == reason
    scanner = next(item for item in composition.scanners if item.name == "semgrep")
    assert isinstance(scanner, UnavailableScanner)
    assert (await scanner.scan("code")).error == reason


def test_recommendations_name_the_missing_capability_and_the_broken_scanner() -> None:
    composition = Composition(
        scanners=(MinimalScanner(),),
        statuses=(
            ScannerStatus(
                id="prompt_guard",
                state="unavailable",
                reason="weights missing",
                extra="prompt-guard",
                detects=frozenset({"injection"}),
                label="PromptGuard",
            ),
            ScannerStatus(
                id="presidio",
                state="not_installed",
                reason="Presidio is not installed. pip install petasos[presidio]",
                extra="presidio",
                detects=frozenset({"pii"}),
                label="Presidio",
            ),
            ScannerStatus(
                id="semgrep",
                state="unavailable",
                reason="semgrep.host_lifecycle_unavailable",
                extra="semgrep",
                detects=frozenset({"code"}),
                label="Semgrep",
            ),
        ),
    )
    lines = recommendations(composition, role="admin")
    assert lines == (
        "PromptGuard is unavailable: weights missing. pip install petasos[prompt-guard]",
        "Semgrep is unavailable: semgrep.host_lifecycle_unavailable. "
        "Pass a lifecycle owner when the scanners are built.",
        "No injection scanner is active. "
        "Install the prompt-guard extra: pip install petasos[prompt-guard].",
        "Role admin has no active personal-information scanner. "
        "Install the presidio extra: pip install petasos[presidio].",
    )
    assert recommendations(composition, role="support")[-1].startswith("Role support")
    assert recommendations(composition, role="research") == lines[:3]
    assert recommendations(composition) == lines[:3]


def test_recommendations_stay_quiet_when_the_capability_is_active() -> None:
    composition = Composition(
        scanners=(),
        statuses=(
            ScannerStatus(
                id="prompt_guard",
                state="active",
                reason=None,
                extra="prompt-guard",
                detects=frozenset({"injection"}),
                label="PromptGuard",
            ),
            ScannerStatus(
                id="presidio",
                state="active",
                reason=None,
                extra="presidio",
                detects=frozenset({"pii"}),
                label="Presidio",
            ),
        ),
    )
    assert recommendations(composition, role="admin") == ()


def test_base_install_recommendations_suggest_prompt_guard() -> None:
    composition = compose(PetasosConfig(), BuildContext())
    assert recommendations(composition) == (
        "No injection scanner is active. "
        "Install the prompt-guard extra: pip install petasos[prompt-guard].",
    )
    admin = recommendations(composition, role="admin")
    assert admin[0] == recommendations(composition)[0]
    assert "presidio" in admin[1]
    assert recommendations(composition, role="coding") == recommendations(composition)


def test_importing_the_registry_and_composing_loads_no_ml_package() -> None:
    script = (
        "import petasos.scanners.registry as registry\n"
        "from petasos.config.sections import PetasosConfig\n"
        "registry.compose(PetasosConfig(), registry.BuildContext())\n"
        "banned = ('torch', 'transformers', 'tokenizers', 'presidio_analyzer',"
        " 'presidio_anonymizer', 'spacy')\n"
        "loaded = [name for name in banned if name in __import__('sys').modules]\n"
        "raise SystemExit(0 if not loaded else ','.join(loaded))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == ""
