"""PET-106 meta-test — every scanner-backend extra must have a paired CI lane.

A scanner extra declared in ``pyproject.toml`` ``[project.optional-dependencies]``
whose real-backend tests gate on the extra's presence (``@requires_presidio``,
``_skip_no_llm_guard``, …) will *silently self-skip* in the default ``ci.yml``
lane, which installs only ``[dev]``. A broken live-backend path then passes the
green gate indefinitely — the bug class behind PET-87 / PET-96 / PET-104. This
module mechanizes the invariant: for each scanner extra ``E`` there must exist a
``.github/workflows/extras-<E>.yml`` lane that installs ``E`` (as an extras
bracket) and runs ``pytest``.

The check is pure/IO-split so the invariant logic is provable on synthetic inputs
*and* runs against the real repo (the live witness). Retro-assertion (Done-when
#3): applied to the pre-PET-104 tree — which declared the ``llm-guard`` extra but
shipped no ``extras-llm-guard.yml`` lane — ``_check_lane_pairing`` would have
returned a violation naming ``llm-guard``; this is encoded executably as
``test_retro_pre_pet104_would_flag_llm_guard``.

The posture is fail-closed (spec Decision 2): any *new* optional-dependency key is
treated as a scanner extra (and so requires a lane) until it is paired with a lane
or added to ``_NON_SCANNER_EXTRAS``. Over-requiring a lane is the safe direction.
"""

from __future__ import annotations

import pathlib
import re
import sys
from typing import Any

import yaml

from tests.conftest import NONSKIPPING_LANES, NonSkippingLane

if sys.version_info >= (3, 11):  # noqa: UP036 - load-bearing: the local 3.10 dev box runs the else branch (spec Decision 6)
    import tomllib
else:  # local 3.10 dev interpreter only
    try:
        import tomli as tomllib
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised only on 3.10
        raise ModuleNotFoundError(
            "tomli is required to run tests/test_ci_extras_lanes.py on "
            'Python < 3.11; re-run `pip install -e ".[dev]"` to install the '
            "tomli backfill."
        ) from exc

# A parsed workflow mapping (or None for "file absent"). PyYAML maps the GitHub
# Actions ``on:`` trigger key to the Python bool ``True`` (YAML 1.1 truthy key),
# so top-level keys are mixed (``{"name", True, "jobs"}``); we read only ``jobs``
# and ``env``, never ``on``, so dict[Any, Any] is the honest annotation.
_Workflow = dict[Any, Any]

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_WORKFLOWS_DIR = _REPO_ROOT / ".github" / "workflows"
_PYPROJECT = _REPO_ROOT / "pyproject.toml"

# PET-106: non-scanner optional-dependency keys that legitimately have no
# extras-<extra>.yml lane. `all`/`dev` are meta/tooling aggregates; `console`
# is a frontend extra with no live-model path (brief § Out of scope).
# Deny-list, not allow-list: a NEW extra is assumed to be a scanner (and thus
# require a lane) until proven otherwise — fail-closed (spec Decision 2).
_NON_SCANNER_EXTRAS = frozenset({"all", "dev", "console"})


# --------------------------------------------------------------------------- #
# Canonical name mappings (pure)
# --------------------------------------------------------------------------- #


def _lane_filename(extra: str) -> str:
    """The workflow file paired with ``extra`` — keeps the hyphen."""
    return f"extras-{extra}.yml"


def _env_flag(extra: str) -> str:
    """The collection-guard arm for ``extra`` — upper-snake."""
    return "PETASOS_REQUIRE_" + extra.upper().replace("-", "_")


# --------------------------------------------------------------------------- #
# Pure checks
# --------------------------------------------------------------------------- #


def _run_steps(workflow: _Workflow | None) -> list[str]:
    """Flatten ``workflow["jobs"][*]["steps"][*]["run"]`` to the list of ``run``
    strings, tolerating missing/short keys (a malformed or absent lane yields
    ``[]`` — and therefore violations downstream — rather than a ``KeyError``)."""
    if not isinstance(workflow, dict):
        return []
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict):
        return []
    runs: list[str] = []
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        steps = job.get("steps")
        if not isinstance(steps, list):
            continue
        for step in steps:
            if isinstance(step, dict) and isinstance(step.get("run"), str):
                runs.append(step["run"])
    return runs


def _check_lane_pairing(extras: set[str], workflows: dict[str, _Workflow | None]) -> list[str]:
    """Return a human-readable violation per unpaired/under-specified lane.

    For each ``extra`` a violation is appended when (1) its lane file is absent
    (maps to ``None``), (2) no step installs the extra *as an extras bracket*, or
    (3) no step runs ``pytest``. Empty ⇒ paired. An empty ``extras`` set returns
    ``[]`` (vacuously paired); a scanner extra declared as an empty list still has
    a key and so still requires a lane (fail-closed, spec Decision 2).
    """
    violations: list[str] = []
    for extra in sorted(extras):
        lane = _lane_filename(extra)
        workflow = workflows.get(lane)
        if workflow is None:
            violations.append(
                f"scanner extra {extra!r} has no paired lane: expected "
                f".github/workflows/{lane} (fail-closed — add the lane or add the "
                f"extra to _NON_SCANNER_EXTRAS)."
            )
            continue
        runs = _run_steps(workflow)
        # Require the extra to appear as a complete comma-separated token inside a
        # `pip install` extras bracket, bounded by `[`/`,` on the left and `]`/`,`
        # on the right. A `\b` word boundary is NOT enough: `-`/`.` are non-word
        # chars, so `\bpresidio\b` would match `presidio` inside `.[presidio-helper]`
        # — a lane installing the wrong bracketed extra would pass (CodeRabbit, PR
        # #86). The negative look-around on `[\w.-]` (the PEP 503 extra-name charset)
        # rejects that while still accepting comma-joined extras (`.[presidio,dev]`,
        # `.[dev,presidio]`). An unrelated package whose name merely contains the
        # extra (`pip install some-presidio-helper`) has no `.[...]` bracket and is
        # rejected outright. `[^\n]*` stops at the newline so the install must keep
        # its extras bracket on one line.
        install_re = re.compile(
            r"pip install[^\n]*\.\[[^\]]*(?<![\w.\-])" + re.escape(extra) + r"(?![\w.\-])[^\]]*\]"
        )
        if not any(install_re.search(run) for run in runs):
            violations.append(
                f"{lane}: no step runs `pip install ...[{extra}...]` — the lane "
                f"must install the {extra!r} extra in a `.[...]` extras bracket "
                f"on the install line."
            )
        if not any("pytest" in run for run in runs):
            violations.append(
                f"{lane}: no step runs `pytest` — the lane must run the "
                f"real-backend tests, not just install the extra."
            )
    return violations


def _check_env_arm(lane_workflow: _Workflow | None, env_flag: str) -> list[str]:
    """Return a violation unless some job in ``lane_workflow`` sets ``env_flag`` to
    ``"1"`` at **job level**, compared as ``str(value).strip() == "1"`` (matching
    GitHub Actions' runtime stringification and the conftest guard's
    ``os.environ.get(env_flag) != "1"``), so an unquoted YAML int is accepted
    exactly as the runtime accepts it. Step- and workflow-level ``env`` are out of
    scope by design: the lanes arm at job level, and ``extras-llamafirewall.yml``
    carries an unrelated *step-level* ``env`` (HF tokens) this must not confuse for
    the arm."""
    if isinstance(lane_workflow, dict):
        jobs = lane_workflow.get("jobs")
        if isinstance(jobs, dict):
            for job in jobs.values():
                if not isinstance(job, dict):
                    continue
                env = job.get("env")
                if not isinstance(env, dict):
                    continue
                if env_flag in env and str(env[env_flag]).strip() == "1":
                    return []
    return [
        f'lane does not arm {env_flag}: set `{env_flag}: "1"` in the job\'s '
        f"`env:` block (job-level — not step- or workflow-level)."
    ]


def _job_level_require_flags(workflow: _Workflow | None) -> set[str]:
    """Every ``PETASOS_REQUIRE_*`` key set in any job-level ``env`` block. Mirrors
    the scope ``_check_env_arm`` reads (job-level only), carrying the same
    tolerance contract as ``_run_steps``: a job whose ``env`` is absent or not a
    mapping is skipped rather than raising."""
    flags: set[str] = set()
    if not isinstance(workflow, dict):
        return flags
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict):
        return flags
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        env = job.get("env")
        if not isinstance(env, dict):
            continue
        for key in env:
            if isinstance(key, str) and key.startswith("PETASOS_REQUIRE_"):
                flags.add(key)
    return flags


# --------------------------------------------------------------------------- #
# Repo loaders (IO)
# --------------------------------------------------------------------------- #


def _optional_dependencies() -> dict[str, list[str]]:
    with _PYPROJECT.open("rb") as fh:
        data = tomllib.load(fh)
    opt = data["project"]["optional-dependencies"]
    assert isinstance(opt, dict)
    return {str(key): list(value) for key, value in opt.items()}


def _scanner_extras() -> set[str]:
    return set(_optional_dependencies()) - _NON_SCANNER_EXTRAS


def _load_workflow(name: str) -> _Workflow | None:
    path = _WORKFLOWS_DIR / name
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as fh:
        loaded = yaml.safe_load(fh)
    assert isinstance(loaded, dict), f"{name} did not parse to a mapping"
    return loaded


# --------------------------------------------------------------------------- #
# Tests — live witness
# --------------------------------------------------------------------------- #


def test_all_scanner_extras_have_paired_lanes() -> None:
    """Live witness: every real scanner extra in pyproject is paired with a lane
    that installs it and runs pytest. Fails pre-fix on presidio; passes once
    extras-presidio.yml lands (Done-when #1 witness, #2)."""
    extras = _scanner_extras()
    workflows: dict[str, _Workflow | None] = {
        _lane_filename(extra): _load_workflow(_lane_filename(extra)) for extra in extras
    }
    assert _check_lane_pairing(extras, workflows) == []


def test_every_nonskipping_lane_arms_its_env_flag() -> None:
    """Each NONSKIPPING_LANES row has a real lane that arms its env flag at job
    level (Done-when #4 wiring; live)."""
    for lane in NONSKIPPING_LANES:
        workflow = _load_workflow(_lane_filename(lane.extra))
        assert workflow is not None, f"{_lane_filename(lane.extra)} is missing"
        assert _check_env_arm(workflow, lane.env_flag) == []


def test_no_orphan_require_flags() -> None:
    """Symmetric drift guard: no lane arms a PETASOS_REQUIRE_* with no matching
    table row, and no table row lacks a lane that arms its flag."""
    by_env_flag: dict[str, NonSkippingLane] = {lane.env_flag: lane for lane in NONSKIPPING_LANES}
    # Direction 1 — every armed flag in a real extras-*.yml maps to a row.
    for path in sorted(_WORKFLOWS_DIR.glob("extras-*.yml")):
        workflow = _load_workflow(path.name)
        for flag in _job_level_require_flags(workflow):
            assert flag in by_env_flag, (
                f"{path.name} arms {flag} but no NONSKIPPING_LANES row has that "
                f"env_flag — add a row or stop arming the flag."
            )
            assert by_env_flag[flag].lane == path.stem, (
                f"{path.name} arms {flag}, but its NONSKIPPING_LANES row names "
                f"lane {by_env_flag[flag].lane!r}, not {path.stem!r}."
            )
    # Direction 2 — every row's lane exists and arms the row's flag.
    for lane in NONSKIPPING_LANES:
        workflow = _load_workflow(_lane_filename(lane.extra))
        assert workflow is not None, (
            f"NONSKIPPING_LANES row {lane.extra!r} has no {_lane_filename(lane.extra)} lane."
        )
        assert lane.env_flag in _job_level_require_flags(workflow), (
            f"{_lane_filename(lane.extra)} does not arm {lane.env_flag} at job level."
        )


def test_presidio_is_armed() -> None:
    """Explicit: the presidio rows arm both live-detection classes the lane runs
    unskipped — PET-106's real PII scan and PET-109's tightened-default regression
    (Done-when #4, presidio)."""
    rows = [lane for lane in NONSKIPPING_LANES if lane.extra == "presidio"]
    assert rows, "no presidio row in NONSKIPPING_LANES"
    assert all(row.import_target == "presidio_analyzer" for row in rows)
    armed = {row.target_class for row in rows}
    assert {"TestPresidioScannerIntegration", "TestPresidioTightenedDefault"} <= armed


def test_nonskipping_table_matches_derivation() -> None:
    """The table's env_flag / lane fields equal the canonical derivations, so the
    stored strings cannot drift from the convention."""
    for lane in NONSKIPPING_LANES:
        assert lane.env_flag == _env_flag(lane.extra)
        assert lane.lane == _lane_filename(lane.extra).removesuffix(".yml")


# --------------------------------------------------------------------------- #
# Tests — synthetic (the check has teeth without touching the repo)
# --------------------------------------------------------------------------- #


def test_pairing_check_flags_missing_lane() -> None:
    """A declared scanner extra with an absent lane is a violation (Done-when #1,
    synthetic — the same shape as pre-fix presidio)."""
    workflows: dict[str, _Workflow | None] = {"extras-presidio.yml": None}
    violations = _check_lane_pairing({"presidio"}, workflows)
    assert violations
    assert any("presidio" in violation for violation in violations)


def test_retro_pre_pet104_would_flag_llm_guard() -> None:
    """Retro regression (Done-when #3): the pre-PET-104 tree declared the
    llm-guard extra with no extras-llm-guard.yml lane; the check would have
    flagged it."""
    workflows: dict[str, _Workflow | None] = {"extras-llm-guard.yml": None}
    violations = _check_lane_pairing({"llm-guard"}, workflows)
    assert any("llm-guard" in violation for violation in violations)


def test_pairing_check_flags_lane_without_pytest() -> None:
    """A lane that installs the extra but never runs pytest is a violation."""
    lane: _Workflow = {
        "jobs": {
            "scanner-tests": {
                "steps": [{"run": 'pip install -e ".[presidio,dev]"'}],
            }
        }
    }
    workflows: dict[str, _Workflow | None] = {"extras-presidio.yml": lane}
    violations = _check_lane_pairing({"presidio"}, workflows)
    assert any("pytest" in violation for violation in violations)


def test_pairing_check_flags_lane_without_install() -> None:
    """A lane that runs pytest but only installs an unrelated package whose name
    merely contains the extra is a violation — locks the tightened bracket regex
    (rule 2) against substring false-positives."""
    lane: _Workflow = {
        "jobs": {
            "scanner-tests": {
                "steps": [
                    {"run": "pip install some-presidio-helper"},
                    {"run": "pytest tests/test_presidio_scanner.py"},
                ],
            }
        }
    }
    workflows: dict[str, _Workflow | None] = {"extras-presidio.yml": lane}
    violations = _check_lane_pairing({"presidio"}, workflows)
    assert any("install" in violation.lower() for violation in violations)
    # pytest IS present, so the install violation is the only one.
    assert not any("`pytest`" in violation for violation in violations)


def test_pairing_check_rejects_hyphenated_superstring_in_bracket() -> None:
    """Regression for PR #86 (CodeRabbit): a lane whose extras bracket installs a
    *different* extra that merely contains the required name as a hyphen-bounded
    substring (``.[presidio-helper]`` for ``presidio``) must still be flagged. A
    word-boundary regex would wrongly accept it (``-`` is a non-word char); the
    delimiter-bounded look-around rejects it."""
    lane: _Workflow = {
        "jobs": {
            "scanner-tests": {
                "steps": [
                    {"run": 'pip install -e ".[presidio-helper,dev]"'},
                    {"run": "pytest tests/test_presidio_scanner.py"},
                ],
            }
        }
    }
    workflows: dict[str, _Workflow | None] = {"extras-presidio.yml": lane}
    violations = _check_lane_pairing({"presidio"}, workflows)
    assert any("install" in violation.lower() for violation in violations)


def test_pairing_check_empty_extras_returns_no_violations() -> None:
    """Degenerate input pins the vacuous pass so a future refactor can't add an
    ``assert extras`` precondition that regresses it (spec Done-when teeth)."""
    assert _check_lane_pairing(set(), {}) == []
