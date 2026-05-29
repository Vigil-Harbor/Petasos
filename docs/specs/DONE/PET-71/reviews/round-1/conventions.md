# Conventions Review -- round 1

## Closure of round 0 findings
N/A -- round 1

## Findings

### F-1: Test command uses hardcoded Windows Python path
**Severity:** P4
Dominant convention across 15+ shipped specs uses `python -m pytest`, not `C:\python310\python.exe`.

### F-2: Brief Done-When "Profile parse/merge logs warning" not mapped in spec Done-When
**Severity:** P2
Brief criterion 3 not explicitly acknowledged as already covered by PET-59.
**Suggested fix:** Add Done-When note.

### F-3: Brief Done-When "Built-in profiles verified clean" not in spec Done-When
**Severity:** P3
Brief criterion 6 covered by PET-59 test but not in Done-When.

### F-4: D5 (single source of truth relocation) is a silent spec addition
**Severity:** P3
Brief predated PET-59; D5 relocates constant PET-59 placed. Rationale sound, should note provenance.

### F-5: Brief test #5 path corrected without acknowledgment
**Severity:** P4

### F-6: Brief test #3 deferral mapping scattered
**Severity:** P4

### F-7: Line references fragile but consistent with repo convention
**Severity:** P4

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 2 | P4: 4

STATUS: GREEN
