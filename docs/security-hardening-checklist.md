# Security hardening checklist

Use this checklist before allowing unattended work. The [deployment guide](deployment/hardening.md) explains the controls and limits.

- [ ] Doctor reports the intended Hermes profile, plugin state and scanner health.
- [ ] Job, strictness and overrides match the work, and restart-bound changes have been applied to the intended processes.
- [ ] The operator understands the [open, blocked and pinned states](usage/guardrail-integrity.md), including machine-wide pin scope and bypass limits.
- [ ] Every profile's settings, secrets, plugin files, Python environment and evidence are protected from agent writes.
- [ ] Operating-system and network isolation restrict what the agent can access and where data can leave.
- [ ] Dashboard access and secret handling follow the host's controls; [report redaction](deployment/credentials.md) is not treated as a universal secrets scanner.
- [ ] Inference placement and [egress limits](deployment/banking-egress.md) suit the data.
- [ ] Recorded events have appropriate permissions and retention; signatures are not treated as encryption or proof of completeness.
- [ ] The intended host workflow has been checked separately from Try it and install diagnostics.
