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
