"""Dependency-free syntactic content scanning."""

from __future__ import annotations

from petasos.scanners.minimal.scanner import MinimalScanner
from petasos.scanners.minimal.taxonomy import RULE_TAXONOMY

__all__ = ["MinimalScanner", "RULE_TAXONOMY"]
