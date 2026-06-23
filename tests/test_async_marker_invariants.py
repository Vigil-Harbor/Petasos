"""PET-149 recurrence guards: async tests run under anyio; no asyncio drift.

The bug class these lock out: under anyio's default ``strict`` mode an
``async def test_*`` that is not bound to the anyio runner is *called*, returns a
coroutine that is never awaited, and passes trivially. A naive marker swap would
silently stop running every currently-unmarked async test while the suite still
reports green. The structural fix is anyio's native ``anyio_mode = "auto"``
(``pyproject.toml`` ``[tool.pytest.ini_options]``), the replacement for the removed
``asyncio_mode = "auto"``: it binds every coroutine test to the anyio runner via
anyio's early ``usefixtures("anyio_backend")`` collection path. These guards prove
that mode stays enabled, that no async test slips through unbound, and that the
asyncio marker / config never creep back.

Mirrors the pure/IO-split, ``tomllib``/``tomli``-guarded static-scan style of
``tests/test_ci_extras_lanes.py``.
"""

from __future__ import annotations

import asyncio
import inspect
import pathlib
import re
import sys
from typing import Any

import pytest

if sys.version_info >= (3, 11):  # noqa: UP036 - load-bearing: the local 3.10 dev box runs the else branch
    import tomllib
else:  # local 3.10 dev interpreter only
    try:
        import tomli as tomllib
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised only on 3.10
        raise ModuleNotFoundError(
            "tomli is required to run tests/test_async_marker_invariants.py on "
            'Python < 3.11; re-run `pip install -e ".[dev]"` to install the '
            "tomli backfill."
        ) from exc

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_TESTS_DIR = _REPO_ROOT / "tests"
_PYPROJECT = _REPO_ROOT / "pyproject.toml"


async def test_anyio_runner_self_witness() -> None:
    """PET-149 canary - intentionally carries NO inline marker. It runs only if
    ``anyio_mode = "auto"`` bound it to the anyio runner; the ``await`` below
    executes only under a real event loop. Two jobs: (1) guarantee this module
    always collects >=1 async item, so ``test_no_async_test_is_unrun`` is never a
    vacuous pass even run in isolation; (2) prove auto-mode actually fired (if it
    did not, this coroutine is never awaited and surfaces as an offender below).
    This is the single sanctioned exception to the implicit "async tests rely on
    anyio auto-mode" rule - do NOT add ``@pytest.mark.anyio`` (that binds the test
    regardless and defeats job (2)) and do NOT replicate the no-marker pattern in
    behavioral tests.
    """
    await asyncio.sleep(0)


def test_no_async_test_is_unrun(request: pytest.FixtureRequest) -> None:
    """Load-bearing guard: every collected ``async def test_*`` must be bound to
    the anyio runner. Membership is keyed on ``anyio_backend in fixturenames`` -
    anyio's auto-mode injects that fixture into every coroutine test's closure, and
    ``anyio_backend in fixturenames`` *is* anyio's own execution key
    (``pytest_pyfunc_call`` drives the coroutine only when ``anyio_backend`` is a
    funcarg). Asserts only ``not unrun`` (no positive-count floor), so ``-k`` /
    ``--deselect`` / ``--last-failed`` selections that drop the self-witness do not
    false-red; the unmarked self-witness above supplies the positive "auto-mode
    fired" proof on any whole-file or whole-suite run.
    """
    unrun = sorted(
        item.nodeid
        for item in request.session.items
        if isinstance(item, pytest.Function)
        and inspect.iscoroutinefunction(item.obj)
        and "anyio_backend" not in item.fixturenames
    )
    assert not unrun, (
        "async test(s) not bound to the anyio runner - under anyio strict mode "
        "(no auto-mode) these never await, a green suite that exercises nothing. "
        f"anyio_mode=auto must bind them: {unrun}"
    )


def test_no_asyncio_marker_remains() -> None:
    """Static scan: no file under ``tests/`` carries a ``pytest.mark.asyncio``
    marker (anyio is the sole async convention, PET-149). Excludes this module,
    which names the forbidden marker in its own regex; the human-readable failure
    message builds the literal from concatenated parts so the scanner stays
    self-safe.
    """
    pattern = re.compile(r"pytest\.mark\.asyncio")
    this_file = pathlib.Path(__file__).resolve()
    offenders: list[str] = []
    for path in sorted(_TESTS_DIR.rglob("*.py")):
        if path.resolve() == this_file:
            continue
        if pattern.search(path.read_text(encoding="utf-8")):
            offenders.append(path.relative_to(_REPO_ROOT).as_posix())
    forbidden = "pytest.mark." + "asyncio"
    assert not offenders, (
        f"the {forbidden} marker must not appear under tests/ - anyio is the sole "
        f"async convention (PET-149); offending files: {offenders}"
    )


def test_pyproject_async_config_consistent() -> None:
    """``pyproject.toml`` must agree with the migration: ``anyio_mode = "auto"`` is
    enabled (the runner that binds every async test), ``asyncio_mode`` is absent,
    and ``pytest-asyncio`` is gone from the ``[dev]`` extra (D-DEPS).
    """
    with _PYPROJECT.open("rb") as fh:
        data: dict[str, Any] = tomllib.load(fh)

    tool = data.get("tool", {})
    assert isinstance(tool, dict)
    pytest_cfg = tool.get("pytest", {})
    assert isinstance(pytest_cfg, dict)
    ini_options = pytest_cfg.get("ini_options", {})
    assert isinstance(ini_options, dict)
    assert ini_options.get("anyio_mode") == "auto", (
        'anyio_mode must be "auto" in [tool.pytest.ini_options] - the anyio-native '
        "replacement for asyncio_mode=auto that binds every async test to the anyio "
        "runner (PET-149); without it, unmarked async tests are silently un-run."
    )
    assert "asyncio_mode" not in ini_options, (
        "asyncio_mode must be absent from [tool.pytest.ini_options] - anyio auto-mode "
        "is the runner and pytest-asyncio is dropped (PET-149 D-DEPS)."
    )

    project = data.get("project", {})
    assert isinstance(project, dict)
    optional = project.get("optional-dependencies", {})
    assert isinstance(optional, dict)
    dev = optional.get("dev", [])
    assert isinstance(dev, list)
    offenders = [
        str(dep)
        for dep in dev
        if str(dep).replace("_", "-").casefold().startswith("pytest-asyncio")
    ]
    assert not offenders, (
        "pytest-asyncio must be absent from [project.optional-dependencies].dev "
        f"(dropped per PET-149 D-DEPS); found: {offenders}"
    )
