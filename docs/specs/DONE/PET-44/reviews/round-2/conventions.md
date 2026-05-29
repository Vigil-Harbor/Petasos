# Conventions Review -- round 2

## Closure of round 1 findings

All 7 round 1 conventions findings closed.

| ID | Title | Status | Evidence |
|---|---|---|---|
| F-1 | Step 6 code missing | CLOSED | Spec lines 198-206 show step 6 with text_after_mn |
| F-2 | Counter not accumulated | CLOSED | stripped_count += restrip_count at line 104 |
| F-3 | Test #2 contradiction | CLOSED | Reframed as wiring test |
| F-4 | Literal vs chr() | CLOSED | Rationale at lines 196-197 |
| F-5 | Test class grouping | CLOSED | Grouping at line 236 |
| F-6 | guard.py note | CLOSED | Lines 27 and 207-208 |
| F-7 | Config toggle rationale | CLOSED | D5 at lines 69-73 |

## Findings

### F-1: D5 describes config toggles as "individual" — they are an all-or-nothing gate (P4)
Technically accurate at config-field level but could mislead. Minor wording issue.

### F-2: D5 is a category (c) spec addition — flagging for drift check (P3)
Correctly self-identified. Rationale is sound.

### F-3: D6 pipeline ordering is a category (c) spec addition (P3)
Correctly added with rationale. Flagging per protocol.

## Summary
P0: 0 | P1: 0 | P2: 0 | P3: 2 | P4: 1

STATUS: GREEN
