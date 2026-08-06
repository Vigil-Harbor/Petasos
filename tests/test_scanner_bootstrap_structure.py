"""PET-174 structural pin — one scanner bootstrap, enforced.

The bug class this guards is "a new scanner-bootstrap site hand-copies the
scanner constructors and drifts": PET-98 and PET-109 both wired one of the two
bootstraps and not the other, and PET-174 is the third field-set to travel that
path. So the routing is pinned mechanically, not by review habit.

Modeled on ``tests/test_ci_extras_lanes.py`` and the posture wiki
``decisions/2026-06-17-pet-77-deploy-parity-guard.md`` endorses: count real AST
call nodes, never raw substrings; keep the checkers pure so they are provable on
synthetic sources, then run them against the real repo as a live witness.

Two invariants:

1. Both bootstraps call ``build_scanners`` and construct no scanner themselves.
2. No un-allowlisted site under ``petasos/`` or ``docs/deployment/`` constructs
   any of the four scanner classes, ``MinimalScanner`` included. ``scripts/`` and
   ``tests/`` are out of the sweep by design (replay harnesses and fixtures
   construct scanners freely; neither ships as a bootstrap).

Construction is detected in four node shapes, because the two bootstraps
constructed differently and the console's dispatch shape is the one a copy-paste
would carry forward. A residual fifth shape (a table-driven pair of bare
literals) is named in the spec's § Deferred; bare-name matching was rejected
because it false-positives on six legitimate in-tree label sites.
"""

from __future__ import annotations

import ast
import pathlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

_SCANNER_CLASSES = frozenset(
    {"MinimalScanner", "LlmGuardScanner", "LlamaFirewallScanner", "PresidioScanner"}
)

# Dispatch helpers whose *bare* class-name string argument is a construction in
# disguise (shape d).
_DISPATCH_FUNCS = frozenset({"getattr", "import_module"})

_MODULE_SCOPE = "<module>"

_SWEEP_ROOTS = ("petasos", "docs/deployment")

# The five modules that DEFINE the scanner classes (and the helper that owns the
# one legitimate construction of each). A file list, not a directory one, so a
# future petasos/scanners/factory.py is swept rather than born invisible.
# Repo-relative POSIX strings, per the Paths rule below.
_DEFINITION_MODULES = frozenset(
    {
        "petasos/scanners/minimal.py",
        "petasos/scanners/llm_guard.py",
        "petasos/scanners/llama_firewall.py",
        "petasos/scanners/presidio.py",
        "petasos/scanners/bootstrap.py",
    }
)

# (repo-relative POSIX path, qualified enclosing function) pairs that may construct
# a scanner. Each row carries its reason:
#   petasos/pipeline.py :: Pipeline.__init__          - the no-minimal-supplied
#       fallback; spec Decision 4 keeps it.
#   reference_plugin/__init__.py :: _get_fallback_scanner - the cold-window
#       fast-path fallback; spec Decision 7 keeps it bare.
#   reference_plugin/verify.py :: check_features / check_injection_scan - a
#       verification script, not a bootstrap.
# The function is QUALIFIED (ClassName.method): a bare "__init__" key would exempt
# every __init__ in pipeline.py, present and future. A module-scope construction
# is never allowlisted.
_ALLOWLIST = frozenset(
    {
        ("petasos/pipeline.py", "Pipeline.__init__"),
        ("docs/deployment/reference_plugin/__init__.py", "_get_fallback_scanner"),
        ("docs/deployment/reference_plugin/verify.py", "check_features"),
        ("docs/deployment/reference_plugin/verify.py", "check_injection_scan"),
    }
)

# (repo-relative POSIX path, bootstrap function) - invariant 1's targets.
_BOOTSTRAPS = (
    ("petasos/console/_standalone.py", "build_dashboard_pipeline"),
    ("docs/deployment/reference_plugin/__init__.py", "_deferred_init"),
)


@dataclass(frozen=True)
class Construction:
    path: str
    function: str
    class_name: str
    lineno: int


# --------------------------------------------------------------------------- #
# Pure checks
# --------------------------------------------------------------------------- #


def _scoped_nodes(node: ast.AST, scope: str, class_prefix: str) -> Iterator[tuple[ast.AST, str]]:
    """Yield ``(node, qualified enclosing function)`` for every descendant.

    ``ClassName.method`` for a method (dotted ClassDef ancestry), the bare name
    for a module-level function, ``"<module>"`` at module scope.
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef):
            yield child, scope
            nested = f"{class_prefix}.{child.name}" if class_prefix else child.name
            yield from _scoped_nodes(child, scope, nested)
        elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            qualified = f"{class_prefix}.{child.name}" if class_prefix else child.name
            inner = qualified if scope == _MODULE_SCOPE else f"{scope}.{child.name}"
            yield child, scope
            yield from _scoped_nodes(child, inner, "")
        else:
            yield child, scope
            yield from _scoped_nodes(child, scope, class_prefix)


def _dotted_class(value: str) -> str | None:
    """Shape (c): a dotted constant naming a scanner class.

    Dotted-only is load-bearing. A bare-name match false-positives on six
    legitimate in-tree sites that name a class without constructing anything
    (``__all__`` bookkeeping in petasos/scanners/__init__.py, PASS/WARN report
    labels in verify.py), which would force a permanently non-empty allowlist.
    """
    if "." not in value:
        return None
    for cls in _SCANNER_CLASSES:
        if value.endswith(f".{cls}"):
            return cls
    return None


def _constructions_in(node: ast.AST, path: str, scope: str = _MODULE_SCOPE) -> list[Construction]:
    """Every scanner construction under ``node``, in all four detected shapes."""
    found: list[Construction] = []
    for child, child_scope in _scoped_nodes(node, scope, ""):
        if isinstance(child, ast.Call):
            func = child.func
            # (a) direct name call - LlmGuardScanner()
            if isinstance(func, ast.Name) and func.id in _SCANNER_CLASSES:
                found.append(Construction(path, child_scope, func.id, child.lineno))
            # (b) attribute call - petasos.scanners.PresidioScanner()
            elif isinstance(func, ast.Attribute) and func.attr in _SCANNER_CLASSES:
                found.append(Construction(path, child_scope, func.attr, child.lineno))
            # (d) split-literal dispatch - getattr(m, "PresidioScanner")()
            dispatch = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr
                if isinstance(func, ast.Attribute)
                else None
            )
            if dispatch in _DISPATCH_FUNCS:
                for arg in child.args:
                    if (
                        isinstance(arg, ast.Constant)
                        and isinstance(arg.value, str)
                        and arg.value in _SCANNER_CLASSES
                    ):
                        found.append(Construction(path, child_scope, arg.value, arg.lineno))
        # (c) dotted dispatch constant - "petasos.scanners.PresidioScanner"
        elif isinstance(child, ast.Constant) and isinstance(child.value, str):
            cls = _dotted_class(child.value)
            if cls is not None:
                found.append(Construction(path, child_scope, cls, child.lineno))
    # Shapes can overlap (a dotted constant handed to import_module); report once.
    return sorted(set(found), key=lambda c: (c.lineno, c.class_name))


def _find_function(tree: ast.Module, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
            return node
    return None


def _calls_build_scanners(func: ast.AST) -> bool:
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        called = node.func
        if isinstance(called, ast.Name) and called.id == "build_scanners":
            return True
        if isinstance(called, ast.Attribute) and called.attr == "build_scanners":
            return True
    return False


def check_bootstrap_routes(source: str | None, path: str, func_name: str) -> list[str]:
    """Invariant 1 for one bootstrap. ``None`` source means the file is absent.

    Liveness: an absent file or a missing function is a violation, not a silent
    pass — otherwise a rename would quietly retire the check.
    """
    if source is None:
        return [f"{path}: file is missing — the bootstrap pin cannot run."]
    tree = ast.parse(source)
    func = _find_function(tree, func_name)
    if func is None:
        return [f"{path}: function {func_name!r} not found — the bootstrap pin cannot run."]
    violations = []
    if not _calls_build_scanners(func):
        violations.append(
            f"{path}::{func_name} does not call build_scanners — every scanner "
            f"bootstrap must route through petasos.scanners.build_scanners."
        )
    for c in _constructions_in(func, path, func_name):
        violations.append(
            f"{path}::{c.function}:{c.lineno} constructs {c.class_name} directly — "
            f"call build_scanners(config) instead."
        )
    return violations


def check_no_unallowlisted_constructions(
    sources: dict[str, str], allowlist: frozenset[tuple[str, str]]
) -> list[Construction]:
    """Invariant 2 over ``{repo-relative POSIX path: source}``."""
    violations: list[Construction] = []
    for path in sorted(sources):
        if path in _DEFINITION_MODULES:
            continue
        for c in _constructions_in(ast.parse(sources[path]), path):
            if (c.path, c.function) in allowlist:
                continue
            violations.append(c)
    return violations


# --------------------------------------------------------------------------- #
# Repo loaders (IO)
# --------------------------------------------------------------------------- #


def _read(path: str) -> str | None:
    """Read a repo-relative file as UTF-8.

    The explicit encoding is load-bearing on this ticket's declared local gate:
    the 3.10 dev interpreter's default locale encoding is cp1252, which cannot
    decode petasos/normalize.py or petasos/session/license.py (both carry UTF-8
    zero-width characters).
    """
    p = _REPO_ROOT / path
    if not p.is_file():
        return None
    return p.read_text(encoding="utf-8")


def _sweep_sources() -> dict[str, str]:
    """Every ``*.py`` under the swept roots, keyed by repo-relative POSIX path.

    POSIX-normalized keys are load-bearing, not cosmetic: on Windows the default
    ``str(p.relative_to(root))`` yields ``petasos\\pipeline.py``, which matches
    neither the definition-module exclusion list nor the allowlist.
    """
    sources: dict[str, str] = {}
    for root in _SWEEP_ROOTS:
        for p in sorted((_REPO_ROOT / root).rglob("*.py")):
            sources[p.relative_to(_REPO_ROOT).as_posix()] = p.read_text(encoding="utf-8")
    return sources


# --------------------------------------------------------------------------- #
# Tests — live witness
# --------------------------------------------------------------------------- #


def test_both_bootstraps_route_through_helper() -> None:
    """Invariant 1, live (Done-when #3)."""
    for path, func_name in _BOOTSTRAPS:
        assert (_REPO_ROOT / path).is_file(), f"{path} is missing"
        assert check_bootstrap_routes(_read(path), path, func_name) == []


def test_no_unallowlisted_scanner_construction() -> None:
    """Invariant 2, live (Done-when #3)."""
    sources = _sweep_sources()
    assert sources, "the sweep visited no files — the checker would pass vacuously"
    for path, _ in _BOOTSTRAPS:
        assert path in sources, f"{path} was not visited by the sweep"
    assert check_no_unallowlisted_constructions(sources, _ALLOWLIST) == []


def test_allowlist_is_exactly_the_documented_rows() -> None:
    """An implementer who silences a violation by adding a row has to change this
    assertion too, so the spec table and the code cannot drift."""
    documented = frozenset(
        {
            ("petasos/pipeline.py", "Pipeline.__init__"),
            ("docs/deployment/reference_plugin/__init__.py", "_get_fallback_scanner"),
            ("docs/deployment/reference_plugin/verify.py", "check_features"),
            ("docs/deployment/reference_plugin/verify.py", "check_injection_scan"),
        }
    )
    assert documented == _ALLOWLIST


def test_allowlisted_sites_still_exist() -> None:
    """Liveness for the allowlist itself: every row names a real construction, so
    a stale exemption cannot silently widen the checker."""
    sources = _sweep_sources()
    live = {
        (c.path, c.function)
        for path in sources
        for c in _constructions_in(ast.parse(sources[path]), path)
    }
    assert live >= _ALLOWLIST


# --------------------------------------------------------------------------- #
# Tests — synthetic (the checkers have teeth without touching the repo)
# --------------------------------------------------------------------------- #

_PRE_FIX_PLUGIN = """
def _deferred_init():
    scanners = [MinimalScanner()]
    try:
        from petasos.scanners import PresidioScanner

        instance = PresidioScanner()
        scanners.append(instance)
    except ImportError:
        pass
"""

_PRE_FIX_CONSOLE = """
def build_dashboard_pipeline(raw_config):
    for name, cls_path in [
        ("LLM Guard", "petasos.scanners.LlmGuardScanner"),
        ("LlamaFirewall", "petasos.scanners.LlamaFirewallScanner"),
        ("Presidio", "petasos.scanners.PresidioScanner"),
    ]:
        mod, cls = cls_path.rsplit(".", 1)
        m = importlib.import_module(mod)
        instance = getattr(m, cls)()
"""


def test_retro_pre_fix_plugin_would_be_flagged() -> None:
    """Retro (shape a): the pre-PET-174 plugin body constructs MinimalScanner and
    PresidioScanner by hand and calls no helper."""
    violations = check_bootstrap_routes(
        _PRE_FIX_PLUGIN, "docs/deployment/reference_plugin/__init__.py", "_deferred_init"
    )
    assert any("build_scanners" in v for v in violations)
    assert any("PresidioScanner" in v for v in violations)
    assert any("MinimalScanner" in v for v in violations)


def test_retro_pre_fix_console_would_be_flagged() -> None:
    """Retro (shape c): the dotted dispatch table the ticket deletes. This is what
    proves the widened checker reaches the console's idiom, not just the plugin's."""
    violations = check_bootstrap_routes(
        _PRE_FIX_CONSOLE, "petasos/console/_standalone.py", "build_dashboard_pipeline"
    )
    assert any("LlmGuardScanner" in v for v in violations)
    assert any("LlamaFirewallScanner" in v for v in violations)
    assert any("PresidioScanner" in v for v in violations)


def test_attribute_call_is_flagged() -> None:
    """Shape (b)."""
    source = "def boot():\n    return petasos.scanners.PresidioScanner()\n"
    found = _constructions_in(ast.parse(source), "x.py")
    assert [c.class_name for c in found] == ["PresidioScanner"]
    assert found[0].function == "boot"


def test_split_literal_getattr_is_flagged() -> None:
    """Shape (d): the split-literal variant of the console's dispatch idiom, one
    token away from the code this ticket deletes."""
    source = (
        "def boot():\n"
        '    m = importlib.import_module("petasos.scanners")\n'
        '    return getattr(m, "PresidioScanner")()\n'
    )
    found = _constructions_in(ast.parse(source), "x.py")
    assert [c.class_name for c in found] == ["PresidioScanner"]


def test_all_bookkeeping_is_not_flagged() -> None:
    """Negative row: naming a class in ``__all__`` constructs nothing. Pins the
    dotted-only narrowing of shape (c)."""
    source = '__all__ += ["PresidioScanner"]\n'
    assert _constructions_in(ast.parse(source), "x.py") == []


def test_report_label_is_not_flagged() -> None:
    """Negative row: a PASS/WARN report label constructs nothing."""
    source = 'def check():\n    available.append("PresidioScanner")\n'
    assert _constructions_in(ast.parse(source), "x.py") == []


def test_method_scope_is_qualified() -> None:
    """A method-scoped construction reports ``ClassName.method``, so a bare
    ``__init__`` allowlist key cannot exempt every ``__init__`` in a module."""
    source = "class Pipeline:\n    def __init__(self):\n        self.s = MinimalScanner()\n"
    found = _constructions_in(ast.parse(source), "petasos/pipeline.py")
    assert [c.function for c in found] == ["Pipeline.__init__"]


def test_module_scope_construction_is_reported() -> None:
    """A module-scope construction is never allowlisted, so it must be reported
    under the ``<module>`` scope rather than silently attributed to a function."""
    sources = {"x.py": "_scanner = MinimalScanner()\n"}
    violations = check_no_unallowlisted_constructions(sources, _ALLOWLIST)
    assert [(c.function, c.class_name) for c in violations] == [("<module>", "MinimalScanner")]


def test_definition_modules_are_excluded() -> None:
    """The five defining modules may construct freely; everything else may not."""
    sources = {
        "petasos/scanners/bootstrap.py": "def build():\n    return MinimalScanner()\n",
        "petasos/scanners/factory.py": "def build():\n    return MinimalScanner()\n",
    }
    violations = check_no_unallowlisted_constructions(sources, _ALLOWLIST)
    assert [c.path for c in violations] == ["petasos/scanners/factory.py"]


def test_missing_bootstrap_file_is_a_violation() -> None:
    """Liveness: an absent file is not a clean file."""
    violations = check_bootstrap_routes(None, "petasos/console/_standalone.py", "build")
    assert any("missing" in v for v in violations)


def test_renamed_bootstrap_function_is_a_violation() -> None:
    """Liveness: a renamed target does not silently pass."""
    violations = check_bootstrap_routes(
        "def other():\n    pass\n", "petasos/console/_standalone.py", "build_dashboard_pipeline"
    )
    assert any("not found" in v for v in violations)
