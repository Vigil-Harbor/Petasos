"""Structural rules for the package. Behaviour belongs in the other tests."""

from __future__ import annotations

import ast
import asyncio
import importlib
import importlib.util
import inspect
import pathlib
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

_REMOVED = (
    "petasos.config.legacy",
    "petasos.scanners.bootstrap",
    "petasos.session.profiles",
)
_CONFIG_TYPE = "petasos/config/sections/root.py"


def test_removed_config_modules_cannot_be_imported() -> None:
    """The flat config, the bridge, the profiles package, and the old builder are gone."""
    for name in _REMOVED:
        try:
            importlib.import_module(name)
        except ModuleNotFoundError:
            continue
        raise AssertionError(f"{name} still imports")


def test_one_config_type() -> None:
    """The only class named PetasosConfig is the tree."""
    found: list[str] = []
    for path in sorted(Path("petasos").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "PetasosConfig":
                found.append(path.as_posix())
    assert found == [_CONFIG_TYPE]


def _imported_modules(tree: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append((node.lineno, node.module))
    return found


def _named_for_hermes(module: str) -> bool:
    return "hermes" in module.lower()


def test_enforce_does_not_import_a_host() -> None:
    """Nothing under enforce imports a Hermes-named module."""
    offenders: list[str] = []
    root = Path("petasos/enforce")
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for line, module in _imported_modules(tree):
            if _named_for_hermes(module):
                offenders.append(f"{path}:{line} imports {module}")
    assert offenders == []


def test_lower_layers_do_not_import_enforce() -> None:
    """The session package, the pipeline, and the scanners sit below enforce."""
    offenders: list[str] = []
    roots = [
        Path("petasos/session"),
        Path("petasos/pipeline"),
        Path("petasos/scanners"),
    ]
    paths: list[Path] = []
    for root in roots:
        if root.is_file():
            paths.append(root)
        else:
            paths.extend(sorted(root.rglob("*.py")))
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for line, module in _imported_modules(tree):
            if module == "petasos.enforce" or module.startswith("petasos.enforce."):
                offenders.append(f"{path}:{line} imports {module}")
    assert offenders == []


_LEGACY_EVENT_STATE = frozenset(
    {
        "SPOOL_CAP_BYTES",
        "_ROT_SUFFIX",
        "_SPOOL_KEY",
        "_SPOOL_KEYS",
        "_SpoolResolver",
        "_OverrideSetter",
        "_override_setter",
        "_resolver",
    }
)
_MUTABLE_CALLS = frozenset(
    {
        "BoundedSemaphore",
        "Condition",
        "Event",
        "Lock",
        "RLock",
        "Semaphore",
        "defaultdict",
        "deque",
        "dict",
        "list",
        "local",
        "set",
    }
)


def _assigned(stmt: ast.stmt) -> list[tuple[str, ast.AST | None]]:
    if isinstance(stmt, ast.Assign):
        names = [target.id for target in stmt.targets if isinstance(target, ast.Name)]
        return [(name, stmt.value) for name in names]
    if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
        return [(stmt.target.id, stmt.value)]
    return []


_MUTATIONS = frozenset(
    {
        "add",
        "append",
        "clear",
        "discard",
        "extend",
        "insert",
        "pop",
        "popitem",
        "remove",
        "setdefault",
        "update",
    }
)


def _mutable(value: ast.AST | None) -> bool:
    if isinstance(value, (ast.List, ast.Dict, ast.Set)):
        return True
    if not isinstance(value, ast.Call):
        return False
    func = value.func
    if isinstance(func, ast.Name):
        return func.id in _MUTABLE_CALLS
    if isinstance(func, ast.Attribute):
        return func.attr in _MUTABLE_CALLS
    return False


def _written(tree: ast.AST, name: str) -> bool:
    """True when ``name`` is updated after it is created."""
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == name
            and node.attr in _MUTATIONS
        ):
            return True
        targets: tuple[ast.expr, ...] | list[ast.expr]
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = (node.target,)
        elif isinstance(node, ast.Delete):
            targets = tuple(node.targets)
        else:
            continue
        for target in targets:
            if (
                isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Name)
                and target.value.id == name
            ):
                return True
    return False


def test_enforce_has_no_module_state_beyond_the_legacy_spool() -> None:
    """Enforce state lives on the enforcer. The legacy spool writer is the exception."""
    offenders: list[str] = []
    root = Path("petasos/enforce")
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Global) and path.name != "events.py":
                offenders.append(f"{path}:{node.lineno} uses global")
        legacy = path.name == "events.py"
        for stmt in tree.body:
            for name, value in _assigned(stmt):
                if not _mutable(value) or not _written(tree, name):
                    continue
                if legacy and name in _LEGACY_EVENT_STATE:
                    continue
                offenders.append(f"{path}:{stmt.lineno} mutates module-level {name}")
    assert offenders == []


_HERMES_IMPORT_OK = {
    Path("petasos/guard/guard.py"),
    Path("petasos/guard/selfmod.py"),
}


def _under_hermes_adapter(path: Path) -> bool:
    return path.parts[:2] == ("petasos", "hermes")


def test_only_the_adapter_imports_hermes() -> None:
    """Hermes is a name only the adapter and the guard fallback use."""
    offenders: list[str] = []
    root = Path("petasos")
    for path in sorted(root.rglob("*.py")):
        if _under_hermes_adapter(path) or path in _HERMES_IMPORT_OK:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for line, module in _imported_modules(tree):
            if "hermes" in module.lower():
                offenders.append(f"{path}:{line} imports {module}")
    assert offenders == []


# Only the home-to-enforcer table and its serializing lock are adapter shared state.
_ADAPTER_TABLE = "_registrations"
_ADAPTER_LOCK = "_registration_lock"


def _lock_names(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for stmt in tree.body if isinstance(tree, ast.Module) else []:
        for name, value in _assigned(stmt):
            if not isinstance(value, ast.Call):
                continue
            func = value.func
            attr = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if attr in {"Lock", "RLock"}:
                names.append(name)
    return names


def test_hermes_state_is_the_registered_enforcer() -> None:
    """The adapter's only module state is the enforcer table, one entry per home.

    ``home.py`` also assigns ``_SPOOL_PATH_OVERRIDE`` once. The adapter does
    not mutate it. It is not a collection.
    """
    offenders: list[str] = []
    root = Path("petasos/hermes")
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Global):
                continue
            offenders.append(f"{path}:{node.lineno} global {sorted(node.names)}")
        if path.name == "plugin.py":
            locks = _lock_names(tree)
            if locks != [_ADAPTER_LOCK]:
                offenders.append(f"{path} locks {locks}")
        for stmt in tree.body:
            for name, value in _assigned(stmt):
                if not _mutable(value) or not _written(tree, name):
                    continue
                if path.name == "plugin.py" and name == _ADAPTER_TABLE:
                    continue
                offenders.append(f"{path}:{stmt.lineno} mutates module-level {name}")
    assert offenders == []


_DASHBOARD = Path("petasos/hermes/dashboard")
_WEB_MODULES = frozenset({"fastapi", "starlette", "uvicorn"})


def _is_web(module: str) -> bool:
    root = module.split(".", 1)[0]
    return root in _WEB_MODULES


def test_dashboard_has_no_module_state() -> None:
    """The dashboard package computes a response and forgets it."""
    offenders: list[str] = []
    for path in sorted(_DASHBOARD.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Global):
                offenders.append(f"{path}:{node.lineno} global {sorted(node.names)}")
        for stmt in tree.body:
            for name, value in _assigned(stmt):
                if _mutable(value) and _written(tree, name):
                    offenders.append(f"{path}:{stmt.lineno} mutates module-level {name}")
    assert offenders == []


def test_only_hermes_imports_the_dashboard() -> None:
    """Nothing outside the Hermes adapter imports the dashboard package."""
    offenders: list[str] = []
    root = Path("petasos")
    for path in sorted(root.rglob("*.py")):
        if path.parts[:3] == ("petasos", "hermes", "dashboard"):
            continue
        if path.parts[:2] == ("petasos", "hermes"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for line, module in _imported_modules(tree):
            dashboard = module == "petasos.hermes.dashboard"
            child = module.startswith("petasos.hermes.dashboard.")
            if dashboard or child:
                offenders.append(f"{path}:{line} imports {module}")
    assert offenders == []


def test_dashboard_responses_do_not_import_a_web_framework() -> None:
    """Response code does not import a web framework."""
    offenders: list[str] = []
    for path in sorted(_DASHBOARD.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if path.name == "router.py":
            for stmt in tree.body:
                if not isinstance(stmt, (ast.Import, ast.ImportFrom)):
                    continue
                if isinstance(stmt, ast.Import):
                    modules = [alias.name for alias in stmt.names]
                else:
                    modules = []
                if isinstance(stmt, ast.ImportFrom) and stmt.module:
                    modules.append(stmt.module)
                for module in modules:
                    if _is_web(module):
                        offenders.append(f"{path}:{stmt.lineno} imports {module} at module level")
            continue
        for line, module in _imported_modules(tree):
            if _is_web(module):
                offenders.append(f"{path}:{line} imports {module}")
    assert offenders == []


_LAYER = {
    "model": 0,
    "coverage": 0,
    "limits": 0,
    "normalize": 0,
    "profile_lint": 0,
    "config": 1,
    "scanners": 2,
    "session": 2,
    "pipeline": 3,
    "guard": 4,
    "enforce": 5,
    "hermes": 6,
    "cli": 7,
    "__main__": 7,
}
_GUARD_HOME_IMPORTS = {
    Path("petasos/guard/guard.py"),
    Path("petasos/guard/selfmod.py"),
}


def _absolute_imports(path: Path, tree: ast.AST) -> list[tuple[int, str]]:
    """Resolve import-from aliases as well as relative package imports."""
    found: list[tuple[int, str]] = []
    package = list(path.parent.parts)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - node.level + 1]
                module = (
                    ".".join([*base, *node.module.split(".")]) if node.module else ".".join(base)
                )
            else:
                module = node.module or ""
            found.append((node.lineno, module))
            found.extend((node.lineno, module + "." + alias.name) for alias in node.names)
    return found


def test_imports_follow_the_package_layers() -> None:
    """Every library import points to its own level or a lower one."""
    offenders: list[str] = []
    for path in sorted(Path("petasos").rglob("*.py")):
        if path == Path("petasos/__init__.py"):
            continue
        source = path.parts[1].removesuffix(".py")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for line, module in _absolute_imports(path, tree):
            parts = module.split(".")
            if len(parts) < 2 or parts[0] != "petasos":
                continue
            target = parts[1]
            if path in _GUARD_HOME_IMPORTS and module in {
                "petasos.hermes.home",
                "petasos.hermes.home.HermesConfigResolution",
                "petasos.hermes.home.hermes_root",
                "petasos.hermes.home.profile_directories",
                "petasos.hermes.home.resolve_hermes_config_path",
                "petasos.hermes.home.spool_path",
                "petasos.hermes.home.spool_rot_path",
            }:
                continue
            if target not in _LAYER or _LAYER[target] > _LAYER[source]:
                offenders.append(f"{path}:{line} imports {module}")
    assert offenders == []


def test_library_module_names_do_not_start_with_an_underscore() -> None:
    """Only Python's package and script entry modules use underscore names."""
    offenders = [
        str(path)
        for path in sorted(Path("petasos").rglob("*.py"))
        if path.stem.startswith("_") and path.name not in {"__init__.py", "__main__.py"}
    ]
    assert offenders == []


def test_packages_declare_their_public_names() -> None:
    """Each package declares its public surface explicitly."""
    for path in sorted(Path("petasos").rglob("__init__.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        names = {name for stmt in tree.body for name, _value in _assigned(stmt)}
        assert "__all__" in names, str(path)


def test_large_modules_state_why_they_stay_together() -> None:
    """A module over 800 lines states its cohesion constraint at the top."""
    for path in sorted(Path("petasos").rglob("*.py")):
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) > 800:
            assert lines[0].startswith("# ") and len(lines[0]) > 20, str(path)


def test_root_public_api_is_the_contract() -> None:
    """The root exports exactly the names in redesign section 9."""
    import petasos

    assert petasos.__all__ == [
        "Pipeline",
        "PipelineResult",
        "PetasosConfig",
        "Settings",
        "resolve",
        "ConfigError",
        "Secrets",
        "Scanner",
        "ScanResult",
        "ScanFinding",
        "Severity",
        "Direction",
        "Position",
        "MinimalScanner",
        "Enforcer",
        "Decision",
        "Allow",
        "Block",
        "Approve",
        "ToolCall",
        "__version__",
    ]
    assert all(hasattr(petasos, name) for name in petasos.__all__)


def test_removed_implementation_modules_cannot_be_imported() -> None:
    """Moved implementation modules leave no compatibility shims."""
    names = (
        "petasos._types",
        "petasos._coverage",
        "petasos._limits",
        "petasos.session._safe_json",
        "petasos.session.guard",
        "petasos.session.guardrail",
        "petasos.session.ingest",
        "petasos.scanners._semgrep_engine",
        "petasos.scanners._semgrep_process",
        "petasos.scanners._semgrep_runtime",
        "petasos.scanners._semgrep_source",
        "petasos.scanners._semgrep_roots",
        "petasos.scanners._semgrep_qualification",
    )
    for name in names:
        try:
            importlib.import_module(name)
        except ModuleNotFoundError:
            continue
        raise AssertionError(f"{name} still imports")


def test_the_suite_does_not_look_at_the_accounts_hermes_home() -> None:
    """Every test gets a throwaway home, so no test finds a real Hermes installation."""
    import os

    import pytest

    from petasos.hermes.home import hermes_root

    pwd = pytest.importorskip("pwd")

    account = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
    root = hermes_root().resolve()
    assert account != root and account not in root.parents


if TYPE_CHECKING:
    from collections.abc import Iterator

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_the_wheel_carries_the_tab_where_install_looks_for_it() -> None:
    """The build puts the tab's files at the path an installed copy reads them from."""
    import tomllib

    from petasos.hermes.dashboard import manifest

    document = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    carried = document["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    source = manifest.DASHBOARD_DIR.relative_to(_REPO_ROOT).as_posix()
    packaged = manifest._PACKAGED_TAB.relative_to(_REPO_ROOT).as_posix()
    assert carried[source] == packaged


_SCANNER_CLASSES = frozenset(
    {
        "MinimalScanner",
        "PresidioScanner",
        "PromptGuardScanner",
        "SemgrepScanner",
    }
)

_DISPATCH_FUNCS = frozenset({"getattr", "import_module"})

_MODULE_SCOPE = "<module>"

_SWEEP_ROOTS = ("petasos", "docs/deployment")

_DEFINITION_MODULES = frozenset(
    {
        "petasos/scanners/minimal/scanner.py",
        "petasos/scanners/presidio.py",
        "petasos/scanners/prompt_guard.py",
        "petasos/scanners/semgrep/adapter.py",
        "petasos/scanners/registry.py",
    }
)

_ALLOWLIST = frozenset(
    {
        ("petasos/pipeline/pipeline.py", "Pipeline.__init__"),
        ("petasos/pipeline/ingest.py", "scan_ingestion_result"),
    }
)

_BOOTSTRAPS: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Construction:
    """Provide Construction test data."""

    path: str
    function: str
    class_name: str
    lineno: int


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
            if isinstance(func, ast.Name) and func.id in _SCANNER_CLASSES:
                found.append(Construction(path, child_scope, func.id, child.lineno))
            elif isinstance(func, ast.Attribute) and func.attr in _SCANNER_CLASSES:
                found.append(Construction(path, child_scope, func.attr, child.lineno))
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
        elif isinstance(child, ast.Constant) and isinstance(child.value, str):
            cls = _dotted_class(child.value)
            if cls is not None:
                found.append(Construction(path, child_scope, cls, child.lineno))
    return sorted(set(found), key=lambda c: (c.lineno, c.class_name))


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
            ("petasos/pipeline/pipeline.py", "Pipeline.__init__"),
            ("petasos/pipeline/ingest.py", "scan_ingestion_result"),
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
    """Pin that __all__ references do not count as constructor calls."""
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
    found = _constructions_in(ast.parse(source), "petasos/pipeline/pipeline.py")
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
        "petasos/scanners/registry.py": "def build():\n    return MinimalScanner()\n",
        "petasos/scanners/factory.py": "def build():\n    return MinimalScanner()\n",
    }
    violations = check_no_unallowlisted_constructions(sources, _ALLOWLIST)
    assert [c.path for c in violations] == ["petasos/scanners/factory.py"]


if sys.version_info >= (3, 11):  # noqa: UP036 - load-bearing: the local 3.10 dev box runs the else branch
    import tomllib
else:
    try:
        import tomli as tomllib
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised only on 3.10
        raise ModuleNotFoundError(
            "tomli is required to run tests/test_async_marker_invariants.py on "
            'Python < 3.11; re-run `pip install -e ".[dev]"` to install the '
            "tomli backfill."
        ) from exc

_TESTS_DIR = _REPO_ROOT / "tests"

_PYPROJECT = _REPO_ROOT / "pyproject.toml"


async def test_anyio_runner_self_witness() -> None:
    """Pin automatic async-test execution without an explicit runner marker.

    See docs/architecture/rationale.md, "Async test and CI lane constraints"."""
    await asyncio.sleep(0)


def test_no_async_test_is_unrun(request: pytest.FixtureRequest) -> None:
    """Pin that every collected async test binds to the anyio runner.

    See docs/architecture/rationale.md, "Test runner fixture binding"."""
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
    """Pin no asyncio marker remains.

    See docs/architecture/rationale.md, "Async test and CI lane constraints"."""
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


_CONFIG_ROOT = Path("petasos/config")


def test_config_modules_import_nothing_above_the_config_layer() -> None:
    offenders: list[str] = []
    for path in sorted(_CONFIG_ROOT.rglob("*.py")):
        if path.name == "__init__.py" and path.parent == _CONFIG_ROOT:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            modules: list[str | None]
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module]
            else:
                continue
            for module in modules:
                if module is None or not module.startswith("petasos"):
                    continue
                if module == "petasos.model" or module.startswith("petasos.model."):
                    continue
                if module == "petasos.config" or module.startswith("petasos.config."):
                    continue
                offenders.append(f"{path}: {module}")

    assert offenders == []


class TestIsolation:
    def test_schema_imports_nothing_else_from_petasos(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = """
import importlib.util
import sys
from pathlib import Path
root = Path(sys.argv[1])
path = root / "petasos" / "config" / "schema.py"
before = {name for name in sys.modules if name == "petasos" or name.startswith("petasos.")}
spec = importlib.util.spec_from_file_location("_schema_isolation", path)
if spec is None or spec.loader is None:
    raise SystemExit("schema module could not be loaded")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
after = {name for name in sys.modules if name == "petasos" or name.startswith("petasos.")}
extra = sorted(after - before)
if extra:
    raise SystemExit("imported " + ", ".join(extra))
"""
        completed = subprocess.run(
            [sys.executable, "-c", script, str(root)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr or completed.stdout


_PLUGIN_ROOT = Path(__file__).resolve().parents[1]

_PLUGIN = _PLUGIN_ROOT / "hermes-plugin" / "petasos"


def test_plugin_directory_is_one_import() -> None:
    """The directory shim imports register and has no executable plumbing of its own."""
    tree = ast.parse((_PLUGIN / "__init__.py").read_text(encoding="utf-8"))
    statements = [
        node
        for node in tree.body
        if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))
    ]
    assert len(statements) == 2
    imported, exported = statements
    assert isinstance(imported, ast.ImportFrom)
    assert imported.module == "petasos.hermes.plugin"
    assert [(alias.name, alias.asname) for alias in imported.names] == [("register", None)]
    assert imported.level == 0
    assert isinstance(exported, ast.Assign)
    assert [target.id for target in exported.targets if isinstance(target, ast.Name)] == [
        "__all__"
    ]
    assert ast.literal_eval(exported.value) == ["register"]


_BUNDLE_ROOT = Path(__file__).resolve().parents[1]

_PLUGIN_DASHBOARD = _BUNDLE_ROOT / "hermes-plugin" / "petasos" / "dashboard"


def test_the_tab_uses_only_hermes_and_its_own_api() -> None:
    """No network asset, no second fetch path, no font or image of its own."""
    sources = _PLUGIN_DASHBOARD.parents[1] / "dashboard-src"
    script = "\n".join(path.read_text(encoding="utf-8") for path in sorted(sources.glob("*.js")))
    css = (sources / "style.css").read_text(encoding="utf-8")
    assert re.search(r"(?<![.\w])fetch\(", script) is None, "use SDK.fetchJSON"
    assert "__HERMES_SESSION_TOKEN__" not in script
    assert "import(" not in script
    assert "@import" not in css
    assert "url(" not in css
    assert "@font-face" not in css
    # Literal palette colours would bypass Hermes theme variables.
    assert re.search(r"#[0-9a-fA-F]{3,8}\b", css) is None
    assert 'var API = "/api/plugins/petasos";' in script


# The default lane checks admission phrases because the upstream scanner runs only in the sandbox.
_ADMISSION_TRIPS = (
    "ignore previous instructions",
    "ignore all previous instructions",
    "rm -rf",
    "| bash",
    "| sh",
    "~/.ssh",
    "system override",
    "developer mode",
)


def test_the_plugin_directory_holds_no_sample_attack() -> None:
    """Nothing Hermes scans before loading the plugin looks like an attack.

    This reads shipped files, because their text is what Hermes judges: an
    example attack in the tab would make Hermes refuse to install the plugin.
    """
    plugin = _PLUGIN_DASHBOARD.parent
    found: list[str] = []
    for path in sorted(plugin.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        found.extend(
            f"{path.relative_to(plugin)}: {trip}" for trip in _ADMISSION_TRIPS if trip in text
        )
    assert found == []


def test_the_installed_dashboard_folder_holds_only_what_hermes_loads() -> None:
    """The installer copies dashboard/ as it is: the manifest, the API shim, the joined script."""
    shipped = sorted(
        path.name
        for path in _PLUGIN_DASHBOARD.iterdir()
        if path.name != "__pycache__" and not path.name.startswith(".")
    )
    assert shipped == ["index.js", "manifest.json", "plugin_api.py"]
