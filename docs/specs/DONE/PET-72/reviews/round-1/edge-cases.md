# PET-72 Edge-Cases Review -- Round 1

## Findings

### F-1: float('nan') confidence -- no test (P2)
NaN IS correctly rejected by `not (0.0 <= float('nan') <= 1.0)` but test plan has no NaN/inf test.

### F-2: validate_scanner rejects scanners using **kwargs (P1)
A scanner with `async def scan(self, text, **kwargs)` fails signature check because `direction`/`session_id` are not explicit params. **kwargs implicitly accepts all keywords.

### F-3: validate_scanner TypeError from Pipeline.__init__ vs "never throws" (P2)
Spec should note "never throws" applies to inspect(), not __init__().

### F-4: Position accepts float values for int fields (P2)
Python dataclasses don't enforce type annotations. `Position(start=0.5, end=5.5)` passes range validation but fails at string slicing.

### F-5: MappingProxyType shallow wrapping -- nested dicts still mutable (P3)
Current type is `MappingProxyType[str, str]` (string values), so not exploitable. Latent concern if type changes.

### F-6: validate_scanner propagates unexpected exceptions from property accessors (P2)
`hasattr(obj, "name")` propagates non-AttributeError exceptions.

### F-7: No positive test for validate_scanner (P2)
Test plan only has rejection cases. No test that MinimalScanner() passes validation.

### F-8: inspect.signature() could raise ValueError on exotic callables (P3)
C extensions or functools.partial could cause ValueError, not caught by validate_scanner.

### F-9: from_dict with string Position values (P3)
`Position(**{"start": "0", "end": "5"})` creates Position with strings. Comparison raises TypeError.

### F-10: TYPE_CHECKING unused import after block removal (P2)
Duplicate of correctness F-1.

## Summary
P0: 0 | P1: 1 | P2: 5 | P3: 3 | P4: 0

STATUS: RED P0=0 P1=1 P2=5 P3=3 P4=0
