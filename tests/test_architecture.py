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
    """Nothing under enforce imports the console or a Hermes-named module."""
    offenders: list[str] = []
    root = Path("petasos/enforce")
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for line, module in _imported_modules(tree):
            host = module == "petasos.console" or module.startswith("petasos.console.")
            if host or _named_for_hermes(module):
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


def test_only_the_bridge_imports_the_flat_config_and_profiles() -> None:
    """Internals read the config tree. The bridge is the one temporary importer."""
    offenders: list[str] = []
    root = Path("petasos")
    for path in sorted(root.rglob("*.py")):
        if "console" in path.parts or path in _ALLOWED:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for line, module in _imports(tree):
            offenders.append(f"{path}:{line} imports {module}")
    assert offenders == []
