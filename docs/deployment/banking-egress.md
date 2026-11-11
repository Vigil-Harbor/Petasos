# Sensitive-data egress

Petasos can stop detected personal information or remembered source text from leaving through configured tools. It cannot make a general promise that financial data stays on the machine.

## Choose the boundaries

Control where inference runs: Petasos does not intercept model requests. A remote model can receive data already in the conversation without an outbound tool call. Operating-system network controls must also cover shell commands and other routes outside the configured sink tools.

Configure `egress.sink_tools` with the actual tool names that send data out. Use full Hermes MCP wire names when applicable; Petasos's deterministic canonicalization is not Hermes's fuzzy tool resolution. Review `egress.taint_namespaces` for source tools whose returned text should be remembered and blocked on a later relay. The [settings reference](../reference/settings.md) describes the fields and their limits.

The taint fence matches normalized substrings, not general data flow. Paraphrases, summaries and re-encoding can evade it. Personal-information detection also does not recognize every balance, merchant or amount as sensitive. Use both as additional controls, alongside restricted destinations and appropriate inference placement.

## Operate the profile

Use Settings in the Petasos tab to configure lists. Check the intended home and scanners with `petasos doctor`. Review [guardrail integrity](../usage/guardrail-integrity.md) so the agent cannot simply weaken those settings through a recognized change. A machine-level pin affects all profiles using that managed directory.

Read [deployment hardening](hardening.md) before admitting unattended access. No live banking connector or model provider was exercised for this guide.
