# Configuration

Petasos stores its Protection switch, job, strictness and overrides through Hermes's plugin-settings writer, under `plugins.entries.petasos.settings`. The library resolves the same settings document into one immutable `PetasosConfig` tree.

Start with [jobs and strictness](jobs-and-strictness.md). Use Settings in the Petasos tab for individual changes, or [everyday commands](commands.md) to change a simple value. Settings reports when the change applies. A running agent retains restart-bound values until it restarts.

The [generated settings reference](../reference/settings.md) lists every path, label, help sentence, type, choice, bound, default and restart requirement. [Generated layer tables](../reference/layers.md) show what the job and strictness contribute. Hand-written configuration does not bypass validation.

Secrets are supplied separately from settings; see [credentials](../deployment/credentials.md). Library callers can build a tree directly or resolve a settings document; see [library use](library.md).
