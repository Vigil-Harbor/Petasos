"""PET-126: ConsoleHandlers.update_config routes through Pipeline.reconfigure.

The standalone (shared-pipeline) console path must use the same propagation
primitive as the gateway, not the bare ``self.pipeline._config = validated`` that
silently left subcomponents on the old config.
"""

from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from petasos.config import PetasosConfig  # noqa: E402
from petasos.console.server import ConsoleHandlers  # noqa: E402
from petasos.pipeline import Pipeline  # noqa: E402
from petasos.scanners.minimal import MinimalScanner  # noqa: E402


async def test_update_config_routes_through_reconfigure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Contain the persist write to a tmp config.yaml (no real Hermes home touched).
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    pipe = Pipeline(scanners=[MinimalScanner()], config=PetasosConfig(fail_mode="degraded"))
    handlers = ConsoleHandlers(pipe)

    seen: list[PetasosConfig] = []
    real_reconfigure = Pipeline.reconfigure

    def spy(self: Pipeline, new_config: PetasosConfig) -> None:
        seen.append(new_config)
        real_reconfigure(self, new_config)

    monkeypatch.setattr(Pipeline, "reconfigure", spy)

    result, errors = await handlers.update_config({"fail_mode": "closed"})

    assert errors is None
    assert result is not None
    assert len(seen) == 1  # routed through reconfigure, not a bare _config assignment
    assert seen[0].fail_mode == "closed"
    assert pipe.config.fail_mode == "closed"  # live config actually swapped


async def test_update_config_invalid_frequency_weights_returns_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # frequency_weights content passes from_dict but is validated inside
    # reconfigure (FrequencyTracker.apply_config); the route must surface a
    # structured field error, not let the ValueError become a 500.
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    pipe = Pipeline(scanners=[MinimalScanner()], config=PetasosConfig())
    handlers = ConsoleHandlers(pipe)
    before = pipe.config

    result, errors = await handlers.update_config({"frequency_weights": {"x": -1.0}})

    assert result is None
    assert errors is not None
    assert errors[0]["message"]  # non-empty error message
    assert pipe.config is before  # reconfigure aborted atomically; live config unchanged
