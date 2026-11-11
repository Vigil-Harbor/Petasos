# Semgrep in a library application

Semgrep checks code without executing the submitted source. Hermes cannot run it because its adapter does not own the engine lifecycle. Do not create an unowned engine in a Hermes plugin to bypass that refusal.

## Own the engine

A library application installs the adapter extra named in the [scanner reference](../reference/scanners.md), separately provisions the engine, and supplies its absolute path and trusted digest. The adapter does not discover an engine through PATH or download it. Protect the engine and its configured digest from the agent.

Use `SemgrepLifecycleOwner` from `petasos.scanners.semgrep` as an asynchronous context manager. Pass the owner to `SemgrepScanner`, or to registry composition through `BuildContext(semgrep_lifecycle=owner)`. Keep it alive while scans use it and close it at application shutdown. Inspect cleanup failures instead of treating an expired deadline as proof that children stopped.

The [settings reference](../reference/settings.md) gives configuration bounds and restart requirements. The [engine pins](../../scripts/semgrep_engine_pins.json) record the validated engine identities. Findings and incomplete coverage remain subject to the pipeline's policy; a syntactic scan is not evidence of complete Semgrep coverage.

## Read the evidence

The [component evidence](../acceptance/semgrep/README.md) records bounded native runs and their limits. Those measurements do not qualify a different machine or establish a live Hermes integration. See [scanner setup](../usage/scanners.md) for the available Hermes checks and [library use](../usage/library.md) for the application boundary.
