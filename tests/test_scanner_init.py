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


# ---------------------------------------------------------------------------
# Unit tests for _is_missing_package()
# ---------------------------------------------------------------------------


class TestIsMissingPackage:
    def test_matches_expected_name(self) -> None:
        exc = ImportError(name="llm_guard")
        assert _is_missing_package(exc, {"llm_guard"}) is True

    def test_rejects_unexpected_name(self) -> None:
        exc = ImportError(name="torch")
        assert _is_missing_package(exc, {"llm_guard"}) is False

    def test_rejects_none_name(self) -> None:
        exc = ImportError("broken")
        assert _is_missing_package(exc, {"llm_guard"}) is False

    def test_rejects_submodule(self) -> None:
        exc = ImportError(name="llm_guard.submodule")
        assert _is_missing_package(exc, {"llm_guard"}) is False


# ---------------------------------------------------------------------------
# Integration tests for import-guard behavior
# ---------------------------------------------------------------------------


@pytest.fixture()
def _reimport_scanners() -> Any:
    """Snapshot sys.modules before test and restore after, allowing clean reimport."""
    saved = dict(sys.modules)
    yield
    sys.modules.clear()
    sys.modules.update(saved)


@pytest.mark.usefixtures("_reimport_scanners")
class TestImportGuardIntegration:
    @staticmethod
    def _reload_scanners() -> types.ModuleType:
        key = "petasos.scanners"
        sys.modules.pop(key, None)
        for k in list(sys.modules):
            if k.startswith("petasos.scanners.") and k != "petasos.scanners.minimal":
                sys.modules.pop(k, None)
        return importlib.import_module(key)

    def test_broken_extra_reraises(self) -> None:
        original_import = __import__

        def selective_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if "llm_guard" in name and "scanners" in name:
                raise ImportError(name="torch")
            return original_import(name, *args, **kwargs)

        sys.modules.pop("petasos.scanners", None)
        sys.modules.pop("petasos.scanners.llm_guard", None)
        with (
            patch("builtins.__import__", side_effect=selective_import),
            pytest.raises(
                ImportError,
            ) as exc_info,
        ):
            importlib.import_module("petasos.scanners")
        assert getattr(exc_info.value, "name", None) == "torch"

    def test_bare_importerror_reraises(self) -> None:
        original_import = __import__

        def selective_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if "llm_guard" in name and "scanners" in name:
                raise ImportError("broken dependency")
            return original_import(name, *args, **kwargs)

        sys.modules.pop("petasos.scanners", None)
        sys.modules.pop("petasos.scanners.llm_guard", None)
        with (
            patch("builtins.__import__", side_effect=selective_import),
            pytest.raises(
                ImportError,
                match="broken dependency",
            ),
        ):
            importlib.import_module("petasos.scanners")

    def test_missing_extra_removes_from_all(self) -> None:
        original_import = __import__

        def selective_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if "llm_guard" in name and "scanners" in name:
                raise ImportError(name="llm_guard")
            return original_import(name, *args, **kwargs)

        sys.modules.pop("petasos.scanners", None)
        sys.modules.pop("petasos.scanners.llm_guard", None)
        with patch("builtins.__import__", side_effect=selective_import):
            mod = importlib.import_module("petasos.scanners")
            assert "LlmGuardScanner" not in mod.__all__
            assert "MinimalScanner" in mod.__all__

    def test_missing_extra_logs_debug(self, caplog: pytest.LogCaptureFixture) -> None:
        original_import = __import__

        def selective_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if "llm_guard" in name and "scanners" in name:
                raise ImportError(name="llm_guard")
            return original_import(name, *args, **kwargs)

        sys.modules.pop("petasos.scanners", None)
        sys.modules.pop("petasos.scanners.llm_guard", None)
        with (
            caplog.at_level(logging.DEBUG, logger="petasos.scanners"),
            patch("builtins.__import__", side_effect=selective_import),
        ):
            importlib.import_module("petasos.scanners")
        assert any("LlmGuardScanner not available" in r.message for r in caplog.records)

    def test_missing_presidio_removes_both_from_all(self) -> None:
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

    def test_missing_llama_removes_from_all(self) -> None:
        original_import = __import__

        def selective_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if "llama_firewall" in name and "scanners" in name:
                raise ImportError(name="llamafirewall")
            return original_import(name, *args, **kwargs)

        sys.modules.pop("petasos.scanners", None)
        sys.modules.pop("petasos.scanners.llama_firewall", None)
        with patch("builtins.__import__", side_effect=selective_import):
            mod = importlib.import_module("petasos.scanners")
            assert "LlamaFirewallScanner" not in mod.__all__
            assert "MinimalScanner" in mod.__all__

    def test_minimal_always_present(self) -> None:
        mod = self._reload_scanners()
        assert "MinimalScanner" in mod.__all__
