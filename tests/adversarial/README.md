# Adversarial test corpus (PET-14 Bucket B)

Regression tests produced by the cross-model red-team pass. Each file maps to attack categories in `docs/security/red-team-runbook.md`.

| Directory | Category |
|-----------|----------|
| `normalization/` | Unicode / normalization bypass |
| `syntactic/` | Injection evasion, ReDoS validation |
| `pipeline/` | Degraded fail-mode, merge, config surface |
| `config/` | Config poisoning |
| `guard/` | Tool-name / alias smuggling |
| `license/` | JWT hard constraints |

Run: `pytest tests/adversarial`

Findings: `docs/security/red-team-findings.md`
