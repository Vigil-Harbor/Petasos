"""The stable Petasos library API."""

from __future__ import annotations

from petasos.config import ConfigError, PetasosConfig, Secrets, Settings, resolve
from petasos.enforce.decisions import Allow, Approve, Block, Decision
from petasos.enforce.enforcer import Enforcer
from petasos.enforce.types import ToolCall
from petasos.model import (
    Direction,
    PipelineResult,
    Position,
    ScanFinding,
    Scanner,
    ScanResult,
    Severity,
)
from petasos.pipeline import Pipeline
from petasos.scanners.minimal import MinimalScanner

__all__ = [
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

__version__ = "0.4.0"
