# Conventions Review -- round 1

## Closure of round 0 findings
N/A -- round 1

## Findings

### F-1: Spec does not show updated step 6 code with text_after_mn (P2)
The homoglyph mapping and confusables_normalized flag must compare against text_after_mn (not text_after_nfkc). Code snippet missing. Fix: add step 6 code showing the updated variable names.

### F-2: Re-strip pass does not accumulate into invisible_chars_stripped (P3)
Cross-lens overlap with edge-cases F-3. Same issue.

### F-3: Test #2 self-contradictory with D1 (P3)
Cross-lens overlap with correctness F-2 / edge-cases F-4. Same issue.

### F-4: Homoglyph table uses literal chars while RTL_OVERRIDES gets chr() (P4)
PET-43 deferred section flagged chr() as preferred. Homoglyph table retains literals. Acceptable — visual audit of confusables requires seeing the glyph.

### F-5: Unit tests lack class grouping guidance (P4)
Existing tests use class TestXxx pattern. Spec lists tests by name without class assignment. Fix: add grouping note.

### F-6: guard.py cross-surface impact not documented (P4)
guard.py imports _HOMOGLYPH_TABLE. Expanding the table automatically expands tool name normalization. Fix: add note in scope section.

### F-7: Combining mark removal is unconditional — no config toggle rationale (P3)
Silent spec addition. Existing pipeline has individual toggles for each normalization step. The new Mn step has none. Fix: add explicit rationale as a decision.

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 3 | P4: 3

STATUS: GREEN
