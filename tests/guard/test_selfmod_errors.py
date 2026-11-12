"""Pin library health, reconfiguration and self-change error handling."""

from __future__ import annotations

from typing import Any, cast

from petasos.config.secrets import Secrets
from petasos.config.sections import PetasosConfig
from petasos.guard.guard import ToolCallGuard
from petasos.pipeline import Pipeline
from petasos.scanners.minimal import MinimalScanner


class _BoomParams:
    def values(self) -> Any:
        """Provide values for the test fixture."""
        raise RuntimeError("classifier broke")


def test_a_classifier_error_does_not_raise() -> None:
    """Pin a classifier error does not raise."""
    pipe = Pipeline(scanners=[MinimalScanner()], config=PetasosConfig())
    guard = ToolCallGuard(
        pipe,
        pipe._frequency_tracker,
        PetasosConfig(),
        secrets=Secrets(session_secret=b"a" * 32),
        protected_paths=lambda: ["/owned/config.yaml"],
    )
    match = guard._classify_selfmod("terminal", cast("dict[str, Any]", _BoomParams()))
    assert match is None
