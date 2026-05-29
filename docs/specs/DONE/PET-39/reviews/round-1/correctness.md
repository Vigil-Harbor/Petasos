# Correctness Review -- round 1

## Findings

### F-1: Hardcoded fingerprint is platform-dependent due to line endings
**Severity:** P0
**Where:** spec.md:42 (Decision 1), spec.md:98 (`_EXPECTED_KEY_FINGERPRINT` constant)
The repository has `core.autocrlf = true` and no `.gitattributes` file. On Windows, `public.pem` is checked out with `\r\n` line endings (116 bytes, hash `5736739a...`). On Linux/macOS, the same file is checked out with `\n` (114 bytes, different hash). `importlib.resources.files(...).joinpath("public.pem").read_bytes()` reads on-disk bytes, so the fingerprint check fails cross-platform.
**Suggested fix:** Normalize line endings before hashing: `hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest()` and pin the LF-based hash, or add `.gitattributes` entry for PEM files.

### F-2: Brief's `exp=1e999` criterion is not directly tested
**Severity:** P2
**Where:** spec.md:167-168 (Test plan)
`1e999` evaluates to `float('inf')` in Python. PyJWT already handles infinity in `jwt.decode`. The spec correctly uses `10**18` for the real vulnerability but doesn't test the brief's explicit `1e999` criterion.
**Suggested fix:** Add `test_exp_infinity_returns_invalid` with `exp=float("inf")`.

### F-3: No test for truly missing tier claim (key absent from JWT)
**Severity:** P3
**Where:** spec.md:51, spec.md:172
Decision 3 states missing tier defaults to "standard" → passes. But no test verifies a JWT with the `tier` key entirely absent. `_make_token` always sets `tier`.
**Suggested fix:** Add `test_missing_tier_defaults_to_standard` using direct `jwt.encode`.

### F-4: Spec does not specify `__init__.py` for `tests/adversarial/license/`
**Severity:** P3
**Where:** spec.md:27
The existing `test_jwt_attacks.py` works without `__init__.py` via pytest rootdir discovery. New tests importing `_make_token` from `tests.conftest` should note the import path.

### F-5: Spec line reference "L66-74" is slightly off
**Severity:** P4
**Where:** spec.md:119
L66 is a blank line. The claims block starts at L67.

## Summary
P0: 1 | P1: 0 | P2: 1 | P3: 2 | P4: 1

STATUS: RED P0=1 P1=0 P2=1 P3=2 P4=1
