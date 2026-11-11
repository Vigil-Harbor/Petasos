"""Structural rules for the package. Behaviour belongs in the other tests."""

from __future__ import annotations

import ast
from pathlib import Path

# Still on the flat config or the profiles package. Each one is removed by a
# later package: the console, the scanner bootstrap, and the session re-export.
_ALLOWED = {
    Path("petasos/config/legacy.py"),
    Path("petasos/config/__init__.py"),
    Path("petasos/scanners/bootstrap.py"),
    Path("petasos/session/__init__.py"),
}


def _forbidden(module: str | None) -> bool:
    if module is None:
        return False
    if module == "petasos.config":
        return True
    return module == "petasos.session.profiles" or module.startswith("petasos.session.profiles.")


def _imports(tree: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "petasos.config" or _forbidden(alias.name):
                    found.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom) and _forbidden(node.module):
            found.append((node.lineno, node.module or ""))
    return found


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
    roots = [Path("petasos/session"), Path("petasos/pipeline.py"), Path("petasos/scanners")]
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


# The legacy spool writer still keeps process-global path and key state.
# New enforce modules, and any new name in events.py, may not.
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


# The guard's legacy path discovery still imports the resolver.
_HERMES_IMPORT_OK = {
    Path("petasos/session/guard.py"),
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


# plugin.py may mutate only the home-to-enforcer table. The lock beside it
# is the one lock that serialises that table.
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
    plugin_text = (root / "plugin.py").read_text(encoding="utf-8")
    assert "one entry per Hermes home" in plugin_text
    assert _ADAPTER_TABLE in plugin_text
    assert _ADAPTER_LOCK in plugin_text
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


def test_only_the_bridge_imports_the_flat_config_and_profiles() -> None:
    """Internals read the config tree. The bridge is the one temporary importer."""
    offenders: list[str] = []
    root = Path("petasos")
    for path in sorted(root.rglob("*.py")):
        if path in _ALLOWED:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for line, module in _imports(tree):
            offenders.append(f"{path}:{line} imports {module}")
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
