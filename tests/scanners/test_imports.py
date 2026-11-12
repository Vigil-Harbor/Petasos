"""Tests for petasos/scanners/__init__.py import guards and _is_missing_package helper."""

from __future__ import annotations

import importlib
import logging
import sys
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest

from petasos.scanners import _is_missing_package

if TYPE_CHECKING:
    import types


class TestIsMissingPackage:
    """Pin Is Missing Package."""

    def test_matches_expected_name(self) -> None:
        """Pin matches expected name."""
        exc = ImportError(name="presidio_analyzer")
        assert _is_missing_package(exc, {"presidio_analyzer"}) is True

    def test_rejects_unexpected_name(self) -> None:
        """Pin rejects unexpected name."""
        exc = ImportError(name="torch")
        assert _is_missing_package(exc, {"presidio_analyzer"}) is False

    def test_rejects_none_name(self) -> None:
        """Pin rejects none name."""
        exc = ImportError("broken")
        assert _is_missing_package(exc, {"presidio_analyzer"}) is False

    def test_rejects_submodule(self) -> None:
        """Pin rejects submodule."""
        exc = ImportError(name="presidio_analyzer.submodule")
        assert _is_missing_package(exc, {"presidio_analyzer"}) is False


@pytest.fixture()
def _reimport_scanners() -> Any:
    """Restore both module cache and parent binding after a clean reimport."""
    saved = dict(sys.modules)
    parent = sys.modules["petasos"]
    scanners = vars(parent)["scanners"]
    try:
        yield
    finally:
        sys.modules.clear()
        sys.modules.update(saved)
        # Restore parent bindings as well as sys.modules so dotted imports see the same package.
        vars(parent)["scanners"] = scanners


@pytest.mark.usefixtures("_reimport_scanners")
class TestImportGuardIntegration:
    """Pin Import Guard Integration."""

    @staticmethod
    def _reload_scanners() -> types.ModuleType:
        key = "petasos.scanners"
        sys.modules.pop(key, None)
        for k in list(sys.modules):
            if k.startswith("petasos.scanners.") and k != "petasos.scanners.minimal":
                sys.modules.pop(k, None)
        return importlib.import_module(key)

    def test_broken_extra_reraises(self) -> None:
        """Pin broken extra reraises."""
        original_import = __import__

        def selective_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if "prompt_guard" in name and "scanners" in name:
                raise ImportError(name="not_a_backend_dep")
            return original_import(name, *args, **kwargs)

        sys.modules.pop("petasos.scanners", None)
        sys.modules.pop("petasos.scanners.prompt_guard", None)
        with (
            patch("builtins.__import__", side_effect=selective_import),
            pytest.raises(
                ImportError,
            ) as exc_info,
        ):
            importlib.import_module("petasos.scanners")
        assert getattr(exc_info.value, "name", None) == "not_a_backend_dep"

    def test_bare_importerror_reraises(self) -> None:
        """Pin bare importerror reraises."""
        original_import = __import__

        def selective_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if "prompt_guard" in name and "scanners" in name:
                raise ImportError("broken dependency")
            return original_import(name, *args, **kwargs)

        sys.modules.pop("petasos.scanners", None)
        sys.modules.pop("petasos.scanners.prompt_guard", None)
        with (
            patch("builtins.__import__", side_effect=selective_import),
            pytest.raises(
                ImportError,
                match="broken dependency",
            ),
        ):
            importlib.import_module("petasos.scanners")

    def test_missing_extra_removes_from_all(self) -> None:
        """Pin missing extra removes from all."""
        original_import = __import__

        def selective_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if "prompt_guard" in name and "scanners" in name:
                raise ImportError(name="torch")
            return original_import(name, *args, **kwargs)

        sys.modules.pop("petasos.scanners", None)
        sys.modules.pop("petasos.scanners.prompt_guard", None)
        with patch("builtins.__import__", side_effect=selective_import):
            mod = importlib.import_module("petasos.scanners")
            assert "PromptGuardScanner" not in mod.__all__
            assert "MinimalScanner" in mod.__all__

    def test_missing_extra_logs_debug(self, caplog: pytest.LogCaptureFixture) -> None:
        """Pin missing extra logs debug."""
        original_import = __import__

        def selective_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if "prompt_guard" in name and "scanners" in name:
                raise ImportError(name="torch")
            return original_import(name, *args, **kwargs)

        sys.modules.pop("petasos.scanners", None)
        sys.modules.pop("petasos.scanners.prompt_guard", None)
        with (
            caplog.at_level(logging.DEBUG, logger="petasos.scanners"),
            patch("builtins.__import__", side_effect=selective_import),
        ):
            importlib.import_module("petasos.scanners")
        assert any("PromptGuardScanner not available" in r.message for r in caplog.records)

    def test_broken_presidio_reraises(self) -> None:
        """Pin broken presidio reraises."""
        original_import = __import__

        def selective_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if "presidio" in name and "scanners" in name:
                raise ImportError(name="not_a_backend_dep")
            return original_import(name, *args, **kwargs)

        sys.modules.pop("petasos.scanners", None)
        sys.modules.pop("petasos.scanners.presidio", None)
        with (
            patch("builtins.__import__", side_effect=selective_import),
            pytest.raises(ImportError) as exc_info,
        ):
            importlib.import_module("petasos.scanners")
        assert getattr(exc_info.value, "name", None) == "not_a_backend_dep"

    def test_missing_presidio_removes_both_from_all(self) -> None:
        """Pin missing presidio removes both from all."""
        original_import = __import__

        def selective_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if "presidio" in name and "scanners" in name:
                raise ImportError(name="presidio_analyzer")
            return original_import(name, *args, **kwargs)

        sys.modules.pop("petasos.scanners", None)
        sys.modules.pop("petasos.scanners.presidio", None)
        with patch("builtins.__import__", side_effect=selective_import):
            mod = importlib.import_module("petasos.scanners")
            assert "PresidioScanner" not in mod.__all__
            assert "anonymize" not in mod.__all__
            assert "MinimalScanner" in mod.__all__

    def test_minimal_always_present(self) -> None:
        """Pin minimal always present."""
        mod = self._reload_scanners()
        assert "MinimalScanner" in mod.__all__


def test_prompt_guard_scanner_is_exported_on_a_base_install() -> None:
    """Pin prompt guard scanner is exported on a base install."""
    import petasos.scanners as scanners_pkg

    # Parent bindings and sys.modules must identify the same restored package.
    assert scanners_pkg is sys.modules["petasos.scanners"]
    assert vars(scanners_pkg)["semgrep"] is sys.modules["petasos.scanners.semgrep"]
    assert "PromptGuardScanner" in scanners_pkg.__all__
    assert scanners_pkg.PromptGuardScanner().name == "prompt_guard"
