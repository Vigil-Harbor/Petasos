"""PET-146: Config Editor Hermes-agent-profile selector — backend tests.

Covers the ``get_config``/``update_config`` payload extension and routing:
the binding identity + effective view (D1/D-EFFECTIVE), the equipped vs
non-equipped save split (D3/D4), the non-active dry-run validation gate
(D-NONACTIVE-VALIDATION), secret omission parity (edge round-2 F-1), normalized
is_active determination (edge F-3), and the embedded plugin bridge forwarding the
selector (edge F-1).

The handlers resolve the active Hermes binding from the environment at call time
(``resolve_hermes_config_path``), so each test redirects the platform-appropriate
root env var to a ``tmp_path`` sandbox with real ``profiles/<name>/config.yaml``
fixtures — the same shape the live resolver reads.
"""

from __future__ import annotations

import platform
from typing import TYPE_CHECKING, Any

import pytest
import yaml

pytest.importorskip("fastapi")

from petasos.config import PetasosConfig  # noqa: E402
from petasos.console.hermes import plugin_api  # noqa: E402
from petasos.console.server import ConsoleHandlers, ProfileNotFoundError  # noqa: E402
from petasos.pipeline import Pipeline  # noqa: E402
from petasos.scanners.minimal import MinimalScanner  # noqa: E402

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.anyio


# ── env-driven Hermes-root sandbox ──────────────────────────────────────────
def _point_root_at(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("HERMES_HOME", raising=False)
    if platform.system() == "Windows":
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    else:
        monkeypatch.setenv("HOME", str(tmp_path))
    from petasos.console._paths import hermes_root

    root = hermes_root()
    (root / "profiles").mkdir(parents=True, exist_ok=True)
    return root


def _write_profile(
    root: Path, name: str, section: dict[str, Any] | None = None, *, active: bool = False
) -> Path:
    pdir = root / "profiles" / name
    pdir.mkdir(parents=True, exist_ok=True)
    cfg_path = pdir / "config.yaml"
    cfg_path.write_text(yaml.safe_dump({"petasos": section or {}}), encoding="utf-8")
    if active:
        (root / "active_profile").write_text(name, encoding="utf-8")
    return cfg_path


def _handlers(config: PetasosConfig | None = None) -> ConsoleHandlers:
    return ConsoleHandlers(
        Pipeline(scanners=[MinimalScanner()], config=config or PetasosConfig(fail_mode="degraded"))
    )


def _section_of(cfg_path: Path) -> dict[str, Any]:
    return yaml.safe_load(cfg_path.read_text(encoding="utf-8"))["petasos"]


# ── D1: binding identity for each tier ──────────────────────────────────────
async def test_get_config_surfaces_binding_profile_tier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _point_root_at(tmp_path, monkeypatch)
    active = _write_profile(root, "gibson", {"fail_mode": "open"}, active=True)
    payload = await _handlers().get_config()

    assert payload["config_tier"] == "profile"
    assert payload["hermes_profile"] == "gibson"
    assert payload["profile_home"] == str(active.parent)
    assert payload["config_warning"] is None
    assert payload["is_active"] is True
    names = {p["name"] for p in payload["hermes_profiles"]}
    assert "gibson" in names


async def test_get_config_surfaces_binding_hermes_home_tier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _point_root_at(tmp_path, monkeypatch)
    hh = tmp_path / "hh"
    hh.mkdir()
    (hh / "config.yaml").write_text(yaml.safe_dump({"petasos": {}}), encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(hh))

    payload = await _handlers().get_config()
    assert payload["config_tier"] == "hermes_home"
    assert payload["hermes_profile"] == "HERMES_HOME"


async def test_get_config_surfaces_binding_root_tier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _point_root_at(tmp_path, monkeypatch)  # no active_profile pointer, no HERMES_HOME
    payload = await _handlers().get_config()
    assert payload["config_tier"] == "root"
    assert payload["hermes_profile"] == "root"


# ── D-EFFECTIVE: effective view reflects the internal profile overlay ────────
async def test_get_config_effective_settings_reflect_internal_profile_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _point_root_at(tmp_path, monkeypatch)
    # 'research' sets tier_thresholds {25,45,70} and confidence_floor 0.7.
    handlers = _handlers(PetasosConfig(fail_mode="degraded", profile_name="research"))
    payload = await handlers.get_config()

    eff = payload["effective_config"]
    # Positive: effective tier thresholds reflect the PROFILE, not the raw config.
    assert eff["tier1_threshold"] == 25
    assert eff["tier2_threshold"] == 45
    assert eff["tier3_threshold"] == 70

    ov = payload["active_profile_overrides"]
    assert ov is not None
    assert ov["name"] == "research"
    # Negative (corr F-1): confidence_floor is NOT a PetasosConfig field, so it is
    # ABSENT from effective_config but PRESENT in active_profile_overrides.
    assert "confidence_floor" not in eff
    assert ov["confidence_floor"] == 0.7


async def test_get_config_no_internal_profile_overrides_is_null(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _point_root_at(tmp_path, monkeypatch)
    payload = await _handlers(PetasosConfig(fail_mode="degraded")).get_config()
    assert payload["active_profile_overrides"] is None
    # No overlay -> effective tier thresholds equal the raw config defaults.
    assert payload["effective_config"]["tier1_threshold"] == payload["config"]["tier1_threshold"]


# ── D2: scope metadata is uniformly "profile" ───────────────────────────────
async def test_field_scope_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _point_root_at(tmp_path, monkeypatch)
    payload = await _handlers().get_config()
    fields = {f["name"]: f for f in payload["fields"]}
    assert fields  # non-empty
    assert all(f["scope"] == "profile" for f in fields.values())
    # The three reversed levers are explicitly per-profile, none "global".
    for lever in ("fail_mode", "egress_sink_tools", "source_taint_namespaces"):
        assert fields[lever]["scope"] == "profile"
    assert not any(f["scope"] == "global" for f in fields.values())


# ── D3: equipped edit hot-applies (PET-126 regression) ──────────────────────
async def test_edit_active_profile_hotapplies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _point_root_at(tmp_path, monkeypatch)
    active = _write_profile(root, "alpha", {"fail_mode": "degraded"}, active=True)
    handlers = _handlers(PetasosConfig(fail_mode="degraded"))

    calls = {"n": 0}
    orig = handlers.pipeline.reconfigure

    def _spy(cfg: PetasosConfig) -> None:
        calls["n"] += 1
        orig(cfg)

    monkeypatch.setattr(handlers.pipeline, "reconfigure", _spy)

    result, errors = await handlers.update_config({"fail_mode": "closed"})
    assert errors is None
    assert result is not None
    assert result["applied"] is True
    assert calls["n"] == 1  # reconfigure ran (hot-apply)
    assert handlers.pipeline.config.fail_mode == "closed"
    assert _section_of(active)["fail_mode"] == "closed"  # persisted to the active file


# ── D4: non-equipped edit persists without hot-apply ────────────────────────
async def test_edit_nonactive_profile_persists_without_hotapply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _point_root_at(tmp_path, monkeypatch)
    _write_profile(root, "alpha", {"fail_mode": "degraded"}, active=True)
    beta = _write_profile(root, "beta", {"fail_mode": "degraded"})
    handlers = _handlers(PetasosConfig(fail_mode="degraded"))

    before_cfg = handlers.pipeline.config
    calls = {"n": 0}
    monkeypatch.setattr(
        handlers.pipeline,
        "reconfigure",
        lambda cfg: calls.__setitem__("n", calls["n"] + 1),
    )

    result, errors = await handlers.update_config({"fail_mode": "open"}, profile="beta")
    assert errors is None
    assert result is not None
    assert result["applied"] is False
    assert calls["n"] == 0  # no reconfigure on the non-equipped path
    assert handlers.pipeline.config is before_cfg  # live config untouched
    assert _section_of(beta)["fail_mode"] == "open"  # target file written


async def test_safety_levers_persist_per_hermes_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _point_root_at(tmp_path, monkeypatch)
    _write_profile(root, "alpha", {"fail_mode": "degraded"}, active=True)
    # X carries an on-disk posture field NOT in the save body, to prove dirty-only
    # saves preserve (not reset) untouched posture (edge round-2 F-6).
    x = _write_profile(root, "x", {"fail_mode": "degraded", "tool_guard_enabled": False})
    y = _write_profile(root, "y", {"fail_mode": "closed"})
    y_before = y.read_bytes()
    handlers = _handlers(PetasosConfig(fail_mode="degraded"))

    body = {
        "fail_mode": "open",
        "source_taint_namespaces": ["vault"],
        "egress_sink_tools": ["mcp.send"],
    }
    result, errors = await handlers.update_config(body, profile="x")
    assert errors is None and result is not None

    sec = _section_of(x)
    assert sec["fail_mode"] == "open"
    assert sec["source_taint_namespaces"] == ["vault"]
    assert sec["egress_sink_tools"] == ["mcp.send"]
    # The on-disk lever not in the body survived (merge base = on-disk section).
    assert sec["tool_guard_enabled"] is False
    # A sibling profile is byte-for-byte untouched.
    assert y.read_bytes() == y_before


async def test_nonactive_save_omits_secrets_from_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _point_root_at(tmp_path, monkeypatch)
    _write_profile(root, "alpha", {"fail_mode": "degraded"}, active=True)
    beta = _write_profile(root, "beta", {"fail_mode": "degraded"})
    handlers = _handlers(PetasosConfig(fail_mode="degraded"))

    # A client payload carrying a redacted hash_key must not land on disk: the
    # secret is popped on every write (parity with the active path).
    result, errors = await handlers.update_config(
        {"fail_mode": "open", "hash_key": "[REDACTED]"}, profile="beta"
    )
    assert errors is None and result is not None and result["applied"] is False

    raw = beta.read_text(encoding="utf-8")
    assert "hash_key" not in raw
    assert "session_secret" not in raw
    assert "[REDACTED]" not in raw


# ── edge F-3: is_active is a normalized-path equality, not a leaf compare ────
async def test_is_active_path_normalization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _point_root_at(tmp_path, monkeypatch)
    alpha = _write_profile(root, "alpha", {"fail_mode": "degraded"})
    # Alias case (cross-platform): HERMES_HOME points AT profiles/alpha, so the
    # active binding file IS alpha's config.yaml. A save targeting "alpha" must be
    # recognized as the equipped path (reconfigure), never mis-routed to persist-only.
    monkeypatch.setenv("HERMES_HOME", str(alpha.parent))
    handlers = _handlers(PetasosConfig(fail_mode="degraded"))

    calls = {"n": 0}
    orig = handlers.pipeline.reconfigure
    monkeypatch.setattr(
        handlers.pipeline,
        "reconfigure",
        lambda cfg: (calls.__setitem__("n", calls["n"] + 1), orig(cfg))[1],
    )
    result, errors = await handlers.update_config({"fail_mode": "closed"}, profile="alpha")
    assert errors is None and result is not None
    assert result["applied"] is True  # equipped path
    assert calls["n"] == 1

    # And the read side agrees: get_config(profile="alpha") reports is_active True.
    payload = await handlers.get_config(profile="alpha")
    assert payload["is_active"] is True


@pytest.mark.skipif(platform.system() != "Windows", reason="case-fold is Windows-only")
async def test_is_active_path_normalization_casefold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _point_root_at(tmp_path, monkeypatch)
    alpha = _write_profile(root, "alpha", {"fail_mode": "degraded"})
    # HERMES_HOME with a case-variant of the same path: on Windows os.path.normcase
    # folds them equal, so the equipped edit is still recognized.
    monkeypatch.setenv("HERMES_HOME", str(alpha.parent).upper())
    handlers = _handlers(PetasosConfig(fail_mode="degraded"))
    payload = await handlers.get_config(profile="alpha")
    assert payload["is_active"] is True


# ── D-NONACTIVE-VALIDATION: dry-run gate rejects unappliable configs ─────────
async def test_nonactive_save_validation_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _point_root_at(tmp_path, monkeypatch)
    _write_profile(root, "alpha", {"fail_mode": "degraded"}, active=True)
    beta = _write_profile(root, "beta", {"fail_mode": "degraded"})
    handlers = _handlers(PetasosConfig(fail_mode="degraded"))

    # (a) malformed frequency_weights (negative weight) -> 422, byte-unchanged.
    before = beta.read_bytes()
    result, errors = await handlers.update_config(
        {"frequency_weights": {"some_tool": -1.0}}, profile="beta"
    )
    assert result is None and errors is not None
    assert errors[0]["field"] == "frequency_weights"
    assert beta.read_bytes() == before  # nothing pre-staged

    # (b) unresolvable profile_name -> 422 {field: profile_name}, byte-unchanged.
    result, errors = await handlers.update_config(
        {"profile_name": "no_such_profile_xyz"}, profile="beta"
    )
    assert result is None and errors is not None
    assert errors[0]["field"] == "profile_name"
    assert beta.read_bytes() == before


async def test_active_save_bad_profile_name_maps_to_422(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Active-path parity: an unknown profile_name surfaces as a structured 422, not
    # an unhandled 500 from reconfigure's ProfileResolver.resolve KeyError.
    root = _point_root_at(tmp_path, monkeypatch)
    _write_profile(root, "alpha", {"fail_mode": "degraded"}, active=True)
    handlers = _handlers(PetasosConfig(fail_mode="degraded"))

    result, errors = await handlers.update_config({"profile_name": "no_such_profile_xyz"})
    assert result is None and errors is not None
    assert errors[0]["field"] == "profile_name"


async def test_save_nonexistent_profile_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # edge F-6: a selector that no longer resolves (deleted between load and save)
    # is rejected explicitly, never silently routed to the active file.
    root = _point_root_at(tmp_path, monkeypatch)
    _write_profile(root, "alpha", {"fail_mode": "degraded"}, active=True)
    handlers = _handlers(PetasosConfig(fail_mode="degraded"))

    result, errors = await handlers.update_config({"fail_mode": "open"}, profile="ghost")
    assert result is None and errors is not None
    assert errors[0]["field"] == "profile"


# ── D4 load + edge F-5: non-active view carries the active binding's warning ─
async def test_get_config_nonactive_view_loads_target_and_carries_active_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _point_root_at(tmp_path, monkeypatch)
    # A DANGLING active_profile pointer -> tier root + warning on the active binding.
    (root / "active_profile").write_text("missing_profile", encoding="utf-8")
    _write_profile(root, "beta", {"fail_mode": "open"})
    handlers = _handlers(PetasosConfig(fail_mode="degraded"))

    payload = await handlers.get_config(profile="beta")
    assert payload["is_active"] is False
    assert payload["config"]["fail_mode"] == "open"  # loaded from beta's file
    # The dangling-pointer signal is the ACTIVE binding's, carried regardless of the
    # browsed profile (edge F-5).
    assert payload["config_warning"] is not None


async def test_get_config_malformed_profile_degrades_without_500(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A hand-edited / corrupt non-equipped config.yaml (valid YAML dict, but a value
    # PetasosConfig rejects) must never 500 the browse: get_config degrades to
    # defaults and surfaces a profile_warning (CodeRabbit PR #135).
    root = _point_root_at(tmp_path, monkeypatch)
    _write_profile(root, "alpha", {"fail_mode": "degraded"}, active=True)
    _write_profile(root, "beta", {"fail_mode": "bogus"})  # invalid enum -> from_dict raises
    handlers = _handlers(PetasosConfig(fail_mode="degraded"))

    payload = await handlers.get_config(profile="beta")
    assert payload["is_active"] is False
    assert payload["profile_warning"] is not None
    # Shown as defaults (a valid PetasosConfig), not the rejected value.
    assert payload["config"]["fail_mode"] == "degraded"
    # The valid-profile path leaves profile_warning None.
    ok = await handlers.get_config()
    assert ok["profile_warning"] is None


def _write_unreadable_profile(root: Path, name: str) -> Path:
    # A member profile (config.yaml exists) whose petasos: section is a non-dict —
    # read_petasos_section_checked() reports ok=False (a real read failure).
    pdir = root / "profiles" / name
    pdir.mkdir(parents=True, exist_ok=True)
    cfg = pdir / "config.yaml"
    cfg.write_text("petasos:\n  - not\n  - a dict\n", encoding="utf-8")
    return cfg


async def test_get_config_unreadable_profile_warns_not_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # CodeRabbit PR #135 (read-failure provenance): a malformed-YAML profile must
    # not silently present defaults — read_ok=False surfaces a profile_warning.
    root = _point_root_at(tmp_path, monkeypatch)
    _write_profile(root, "alpha", {"fail_mode": "degraded"}, active=True)
    _write_unreadable_profile(root, "beta")
    handlers = _handlers(PetasosConfig(fail_mode="degraded"))

    payload = await handlers.get_config(profile="beta")
    assert payload["is_active"] is False
    assert payload["profile_warning"] is not None  # not a silent default


async def test_nonactive_save_rejects_unreadable_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # CodeRabbit PR #135: a dirty save against an UNREADABLE profile is rejected, so
    # it cannot merge {} + body and silently persist all-defaults over the broken file.
    root = _point_root_at(tmp_path, monkeypatch)
    _write_profile(root, "alpha", {"fail_mode": "degraded"}, active=True)
    beta = _write_unreadable_profile(root, "beta")
    before = beta.read_bytes()
    handlers = _handlers(PetasosConfig(fail_mode="degraded"))

    result, errors = await handlers.update_config({"fail_mode": "open"}, profile="beta")
    assert result is None and errors is not None
    assert errors[0]["field"] == "profile"
    assert beta.read_bytes() == before  # the broken file is left untouched


async def test_get_config_unresolved_selector_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # CodeRabbit PR #135 (outside-diff): a named selector that does not resolve is
    # rejected (ProfileNotFoundError -> route 422), never a silent fallback to the
    # equipped view (which would risk editing the wrong profile).
    root = _point_root_at(tmp_path, monkeypatch)
    _write_profile(root, "alpha", {"fail_mode": "degraded"}, active=True)
    handlers = _handlers(PetasosConfig(fail_mode="degraded"))

    with pytest.raises(ProfileNotFoundError):
        await handlers.get_config(profile="ghost")
    # The bridge maps it to a 422 (not a 500 / silent active view).
    monkeypatch.setattr(plugin_api, "_handlers", handlers)
    resp = await plugin_api.get_config(profile="ghost")
    assert getattr(resp, "status_code", None) == 422


# ── edge F-1: the embedded plugin bridge forwards the selector ──────────────
async def test_bridge_forwards_profile_selector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _point_root_at(tmp_path, monkeypatch)
    _write_profile(root, "alpha", {"fail_mode": "degraded"}, active=True)
    beta = _write_profile(root, "beta", {"fail_mode": "degraded"})
    handlers = _handlers(PetasosConfig(fail_mode="degraded"))
    monkeypatch.setattr(plugin_api, "_handlers", handlers)

    # GET bridge forwards ?profile= -> the non-active view of beta.
    got = await plugin_api.get_config(profile="beta")
    assert got["is_active"] is False

    # PUT bridge forwards the body (selector rides as a top-level key) -> persists
    # to beta without hot-applying.
    class _Req:
        def __init__(self, data: dict[str, Any]) -> None:
            self._d = data

        async def json(self) -> dict[str, Any]:
            return self._d

    out = await plugin_api.update_config(_Req({"fail_mode": "open", "profile": "beta"}))
    assert isinstance(out, dict)
    assert out["applied"] is False
    assert _section_of(beta)["fail_mode"] == "open"
