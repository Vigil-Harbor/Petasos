# Correctness Review — Round 1

All file:line anchors verified accurate. The spec's line references to `llama_firewall.py` L161–167 and `test_llama_firewall_scanner.py` L193–202 match the current code exactly. The proposed code blocks are consistent with each other and with the prose. The `ScanResult.error` field exists with correct type (`str | None`). The pipeline's `_compute_safe` logic handles `r.error is not None` as described. The `LlmGuardScanner` unconditionally registers `PromptInjection` as claimed. Every "Done when" criterion in the brief is mapped to a spec section. The three carried-forward decisions are reflected in D1–D3. No internal contradictions found. No stale anchors. No nonexistent references.

### F-1 (P4): Spec "Done when" checkboxes are pre-checked
All `[x]` items should be `[ ]` since this is a pre-implementation spec.

STATUS: GREEN
