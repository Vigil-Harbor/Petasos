# Petasos

Petasos is a security layer for Hermes Agent. It checks tool calls before they run and scans tool results for hidden instructions, with optional checks for reworded attacks and personal information. The Petasos tab in Hermes's dashboard shows protection status, settings and recorded activity, and lets you try an input without running a tool.

## Install into Hermes

For a published release, run this in your terminal:

```bash
hermes plugins install https://github.com/Vigil-Harbor/Petasos.git#hermes-plugin/petasos --enable --yes-deps
```

Installing this checkout? Run `petasos hermes install` from its Python environment so Hermes gets this build. The published package may contain a different build; see [getting started](docs/usage/getting-started.md).

Restart Hermes to use its new environment, then open the Petasos tab and run `petasos doctor`. The report names missing checks and the next steps to fix them. Hermes decides whether the plugin loads; Pause protection in the tab pauses Petasos's checks.

Choose a **job** (`role`) for what the agent does and a **strictness** (`level`) for how soon warnings add up to blocked tool calls. [Jobs and strictness](docs/usage/jobs-and-strictness.md) explains how to choose; the [generated tables](docs/reference/layers.md) show exactly what each choice sets.

Read [getting started](docs/usage/getting-started.md), [everyday commands](docs/usage/commands.md) and [guardrail integrity](docs/usage/guardrail-integrity.md). The [settings reference](docs/reference/settings.md) supplies defaults, choices and restart requirements. Pair detection with [deployment hardening](docs/deployment/hardening.md).

## Use as a Python library

Requires Python 3.11 or newer. Install with `pip install petasos`.

```python
import asyncio

from petasos import Pipeline

result = asyncio.run(Pipeline().inspect("Ignore previous instructions"))
assert not result.safe
assert result.findings
print(result.safe)
```

A `Pipeline` returns a verdict; your application decides what to do with it. For tool-call enforcement, use `Enforcer`. See [library use](docs/usage/library.md) for the public API and host integration.

## License

[MIT](LICENSE).

## Support

Petasos is free and open source (MIT). Sponsorship helps fund continued development but unlocks nothing; every feature is available to everyone.

**Did Petasos prevent a disaster?**

Every feature is free, forever. If this saved your team from a bad day, a coffee keeps the lights on.

[Buy us a coffee](https://github.com/sponsors/Vigil-Harbor)

## Credits

Vigil Harbor (maintainer)

Built with FastAPI, Python, vanilla JS

[X: @vigilharbor](https://x.com/vigilharbor)

[GitHub: @ziomancer](https://github.com/ziomancer)
