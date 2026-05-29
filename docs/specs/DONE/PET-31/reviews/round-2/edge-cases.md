# Edge-Cases Review — Round 2

All R1 findings CLOSED. New findings:

### F-1 (P0): config.copy() strips session_secret — defense dead on arrival
Same as correctness F-1.

### F-2 (P1): test_pipeline_rejects_secret_without_host_id will pass incorrectly due to F-1
The check never fires because config.copy() already stripped the secret.

### F-3 (P2): Null bytes in session_id/host_id break null-byte separator unambiguity
mint_token() doesn't validate for embedded \x00.

### F-4 (P3): from_dict() raises binascii.Error on invalid base64, not ValueError
Should wrap in try/except for consistent error handling.

### F-5 (P2): copy() silently loses session_secret with no signal
No warning or docstring.

### F-6 (P2): No test covers from_dict base64 round-trip
Missing test for the new deserialization path.

### F-7 (P3): Guard test doesn't verify negative case (bare string rejected)
Happy path only.

STATUS: RED P0=1 P1=1 P2=3 P3=2 P4=0
