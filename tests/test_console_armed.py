"""PET-111: petasos.console._armed read/write + cache, and the /armed routes.

Unit tests drive ``read_armed``/``write_armed`` against a tmp config via
``HERMES_HOME`` (tier-1 resolution; no real Hermes install touched). Route tests
exercise the bool-strict 422 and persist-failure 503 on both console surfaces.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")

import petasos.console._armed as armed_mod  # noqa: E402
from petasos.config import PetasosConfig  # noqa: E402
from petasos.console._armed import read_armed, write_armed  # noqa: E402
from petasos.pipeline import Pipeline  # noqa: E402
from petasos.scanners.minimal import MinimalScanner  # noqa: E402


def _write_config(
    path: Path,
    petasos_section: dict[str, Any] | None = None,
    extra_top: dict[str, Any] | None = None,
) -> None:
    import yaml

    data: dict[str, Any] = {"model": {"provider": "test"}}
    if extra_top:
        data.update(extra_top)
    if petasos_section is not None:
        data["petasos"] = petasos_section
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")


def _make_pipeline() -> Pipeline:
    return Pipeline(scanners=[MinimalScanner()], config=PetasosConfig(fail_mode="degraded"))


@pytest.fixture(autouse=True)
def _reset_cache() -> Iterator[None]:
    # The cache is keyed by (mtime_ns, size), not path — reset between tests so a
    # new tmp file can't be served a coincidentally-matching stale key (PET-111).
    armed_mod._reset_armed_cache()
    yield
    armed_mod._reset_armed_cache()


@pytest.fixture()
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    return tmp_path / "config.yaml"


# ── read_armed: defaults + fail-secure (Decision 5) ──────────────────────────


def test_default_armed_when_file_absent(cfg: Path) -> None:
    assert read_armed() is True  # no config.yaml -> armed


def test_default_armed_when_key_absent(cfg: Path) -> None:
    _write_config(cfg, petasos_section={"profile_name": "general"})
    assert read_armed() is True


def test_disarmed_only_on_literal_false(cfg: Path) -> None:
    _write_config(cfg, petasos_section={"enabled": False})
    assert read_armed() is False


@pytest.mark.parametrize("val", ["false", 0, None, "true", 1])
def test_non_bool_enabled_fails_secure_armed(cfg: Path, val: Any) -> None:
    # A non-bool enabled (incl. YAML null/`~`, or a torn write) must never
    # silently disarm a security control.
    _write_config(cfg, petasos_section={"enabled": val})
    assert read_armed() is True


# ── read_armed: TTL + cache (edge-cases R2/F-1) ──────────────────────────────


def test_cache_avoids_reparse_within_ttl(cfg: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_config(cfg, petasos_section={"enabled": True})
    calls = {"n": 0}
    real = armed_mod.read_petasos_section  # type: ignore[attr-defined]

    def counting(res: Any) -> Any:
        calls["n"] += 1
        return real(res)

    monkeypatch.setattr(armed_mod, "read_petasos_section", counting)
    monkeypatch.setattr(armed_mod.time, "monotonic", lambda: 100.0)  # type: ignore[attr-defined]
    assert read_armed() is True
    assert read_armed() is True
    assert calls["n"] == 1  # second call served from cache — no re-parse


def test_ttl_forces_reparse_on_unchanged_key(cfg: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Simulate a same-(mtime,size) out-of-band change: don't touch the file, just
    # change what the section parse returns. Within TTL the stale cache holds;
    # past TTL the value is re-read. Proves the TTL bounds the same-tick miss.
    _write_config(cfg, petasos_section={"enabled": True})
    clock = {"v": 100.0}
    monkeypatch.setattr(armed_mod.time, "monotonic", lambda: clock["v"])  # type: ignore[attr-defined]
    assert read_armed() is True  # parse #1 cached at t=100
    monkeypatch.setattr(armed_mod, "read_petasos_section", lambda res: {"enabled": False})
    clock["v"] = 100.5
    assert read_armed() is True  # within TTL -> stale cache
    clock["v"] = 101.5
    assert read_armed() is False  # past TTL -> re-parse observes the flip


# ── write_armed: preserve, create, fail-safe ─────────────────────────────────


def test_write_preserves_siblings_and_top_level(cfg: Path) -> None:
    _write_config(
        cfg,
        petasos_section={"profile_name": "general", "enabled": True},
        extra_top={"model": {"provider": "x"}},
    )
    assert write_armed(False) is True
    import yaml

    full = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert full["petasos"]["enabled"] is False
    assert full["petasos"]["profile_name"] == "general"  # sibling key preserved (BUG-A class)
    assert full["model"]["provider"] == "x"  # top-level key preserved
    assert read_armed() is False  # writer refreshed this process's cache


def test_write_creates_section_when_absent(cfg: Path) -> None:
    _write_config(cfg, petasos_section=None)
    assert write_armed(False) is True
    import yaml

    full = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert full["petasos"]["enabled"] is False


def test_write_fails_returns_false_on_missing_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # mkstemp into a non-existent parent dir raises -> caught -> False, no raise.
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "nope" / "deeper"))
    assert write_armed(False) is False


def test_write_fails_returns_false_on_oserror(cfg: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Simulate the Windows file-lock case (footgun #11): mkstemp/replace raises.
    _write_config(cfg, petasos_section={"enabled": True})
    import tempfile

    def boom(*a: Any, **k: Any) -> Any:
        raise OSError("locked")

    monkeypatch.setattr(tempfile, "mkstemp", boom)
    assert write_armed(False) is False  # never raises out


# ── /armed routes — bool-strict 422 + persist-failure 503, both surfaces ─────


@pytest.fixture(params=["standalone", "plugin"])
def client(request: pytest.FixtureRequest) -> Iterator[tuple[Any, str]]:
    from fastapi.testclient import TestClient

    import petasos.console.hermes.plugin_api as plugin_mod

    plugin_mod._handlers = None
    if request.param == "standalone":
        from petasos.console.server import build_app

        yield TestClient(build_app(_make_pipeline())), "/api/armed"
    else:
        from fastapi import FastAPI

        from petasos.console.hermes.plugin_api import init_handlers, router

        init_handlers(_make_pipeline())
        app = FastAPI()
        app.include_router(router)
        yield TestClient(app), "/armed"
    plugin_mod._handlers = None


def test_get_armed_reflects_read(client: tuple[Any, str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(armed_mod, "read_armed", lambda: False)
    tc, path = client
    r = tc.get(path)
    assert r.status_code == 200
    assert r.json() == {"armed": False}


@pytest.mark.parametrize(
    "bad", [{}, {"armed": None}, {"armed": 1}, {"armed": "true"}, {"armed": "false"}]
)
def test_post_armed_rejects_non_bool(
    client: tuple[Any, str], monkeypatch: pytest.MonkeyPatch, bad: dict[str, Any]
) -> None:
    # write_armed must never be reached for an invalid body.
    monkeypatch.setattr(armed_mod, "write_armed", lambda a: pytest.fail("write reached"))
    tc, path = client
    r = tc.post(path, json=bad)
    assert r.status_code == 422
    assert r.json()["detail"][0]["field"] == "armed"


def test_post_armed_accepts_bool(client: tuple[Any, str], monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[bool] = []

    def fake_write(armed: bool) -> bool:
        seen.append(armed)
        return True

    monkeypatch.setattr(armed_mod, "write_armed", fake_write)
    tc, path = client
    r = tc.post(path, json={"armed": False})
    assert r.status_code == 200
    assert r.json()["armed"] is False
    assert seen == [False]


def test_post_armed_persist_failure_is_503(
    client: tuple[Any, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # A failed disk write must surface as 503 so the frontend reverts (no fail-open).
    monkeypatch.setattr(armed_mod, "write_armed", lambda a: False)
    tc, path = client
    r = tc.post(path, json={"armed": True})
    assert r.status_code == 503
    assert r.json()["detail"][0]["field"] == "armed"
