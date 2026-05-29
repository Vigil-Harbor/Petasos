# Correctness Review — Round 3

## Closure table
All round 2 P1 CLOSED. All round 1+2 findings across all lenses CLOSED (16 total).

## Findings

### F-1 (P2): NaN behavior claim incorrect — `max(0.0, min(1.0, NaN))` returns 1.0 in CPython, not NaN
### F-2 (P2): llama_firewall.py in both "Files to change" and "Files to leave alone"
### F-3 (P2): No code block for llama_firewall.py NaN guard in D1
### F-4 (P3): Span-size tiebreaker silently dropped — consistent with alignment goal but undocumented

P0: 0 | P1: 0 | P2: 3 | P3: 1

STATUS: GREEN
