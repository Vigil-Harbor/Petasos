# PET-8 Spec — Profiles + Tool Call Guard (Premium)

**Ticket:** PET-8  
**Phase:** 5  
**Blocked by:** PET-7 (Frequency Tracking + Escalation Tiers) — merged  
**Blocks:** PET-10 (JWT License Validation + Premium Wiring)

---

## Goal

Deliver two premium modules — `ProfileResolver` and `ToolCallGuard` — that close the gap between detection ("what was found?") and response ("what should happen next?"). Profiles tune scanner behavior per use case; the guard enforces frequency-aware policy on tool execution before it happens.

---

## Scope

### Files to create

| File | Purpose |
|------|---------|
| `petasos/premium/profiles/__init__.py` | `ResolvedProfile`, `TierThresholds`, `ProfileResolver` class |
| `petasos/premium/profiles/general.json` | Built-in profile: balanced defaults |
| `petasos/premium/profiles/customer_service.json` | Built-in profile: PII-aggressive |
| `petasos/premium/profiles/code_generation.json` | Built-in profile: false-positive suppression |
| `petasos/premium/profiles/research.json` | Built-in profile: relaxed thresholds |
| `petasos/premium/profiles/admin.json` | Built-in profile: maximum sensitivity |
| `petasos/premium/guard.py` | `GuardResult`, `ToolCallGuard` class |
| `tests/test_profiles.py` | Unit tests for ProfileResolver |
| `tests/test_guard.py` | Unit tests for ToolCallGuard |

### Files to modify

| File | Change |
|------|--------|
| `petasos/pipeline.py` | Accept `profile` param in `__init__()` and `inspect()`, add `_premium_profile_hook()`, expose `config` property, add `is_premium_active()` public method |
| `petasos/scanners/minimal.py` | Add `with_suppress_rules()` factory method |
| `petasos/config.py` | Promote `_TIER3_FLOOR` to public `TIER3_FLOOR`, extract `_validate_tier_thresholds()` helper |
| `petasos/premium/escalation.py` | Import `TIER3_FLOOR` from `petasos.config` instead of defining own copy |
| `petasos/premium/__init__.py` | Re-export `ProfileResolver`, `ResolvedProfile`, `TierThresholds`, `ToolCallGuard`, `GuardResult` |
| `petasos/__init__.py` | Expose new premium symbols |
| `CLAUDE.md` | Update Target Layout to show `profiles/` as package directory |

### Files to leave alone

- `petasos/scanners/{llm_guard,llama_firewall,presidio}.py` — scanner internals unchanged (minimal.py is modified above)
- `petasos/premium/frequency.py` — consumed but not modified
- `petasos/normalize.py` — unchanged
- `petasos/_types.py` — no new types needed here (new types live in their own modules)

---

## Design

### D1: Profile system (`petasos/premium/profiles/__init__.py`)

#### ResolvedProfile dataclass

```python
@dataclass(frozen=True)
class ResolvedProfile:
    name: str
    suppress_rules: frozenset[str]
    severity_overrides: MappingProxyType[str, str]   # rule_id → severity value
    confidence_floor: float                          # findings below this confidence are dropped
    tier_thresholds: TierThresholds | None           # override tier1/2/3 values
    pii_entities_extra: tuple[str, ...]              # additional PII entities to detect
    tool_exempt_list: frozenset[str]                 # tools allowed even at tier2
    tool_alias_map: MappingProxyType[str, str]       # custom tool name aliases

    def to_dict(self) -> dict[str, Any]: ...
```

**Decision: `TierThresholds` is a simple frozen dataclass, not a dict.** Explicit fields (`tier1`, `tier2`, `tier3`) enforce the ascending invariant at construction time. Validation uses a shared helper (`_validate_tier_thresholds`) also called by `PetasosConfig.__post_init__` to avoid duplication.

```python
# In petasos/config.py — TIER3_FLOOR is canonical here (exported for escalation.py to import)
TIER3_FLOOR: float = 30.0

def _validate_tier_thresholds(tier1: float, tier2: float, tier3: float) -> None:
    if not all(math.isfinite(v) for v in (tier1, tier2, tier3)):
        raise ValueError(f"thresholds must be finite, got {tier1}, {tier2}, {tier3}")
    if not (tier1 < tier2 < tier3):
        raise ValueError(f"thresholds must be strictly ascending: {tier1} < {tier2} < {tier3}")
    if tier3 < TIER3_FLOOR:
        raise ValueError(f"tier3 must be >= {TIER3_FLOOR}, got {tier3}")
```

This helper and `TIER3_FLOOR` both live in `petasos/config.py`. The existing private `_TIER3_FLOOR` is promoted to a public `TIER3_FLOOR` export. `petasos/premium/escalation.py` imports `TIER3_FLOOR` from `petasos.config` (preserving the existing dependency direction: premium → config, never config → premium).

```python
@dataclass(frozen=True)
class TierThresholds:
    tier1: float
    tier2: float
    tier3: float

    def __post_init__(self) -> None:
        _validate_tier_thresholds(self.tier1, self.tier2, self.tier3)
```

#### ProfileResolver

```python
class ProfileResolver:
    def __init__(self) -> None:
        self._profiles: dict[str, ResolvedProfile] = {}
        self._load_builtins()

    def resolve(self, name_or_dict: str | dict[str, Any]) -> ResolvedProfile:
        ...

    def register(self, name: str, profile: ResolvedProfile) -> None:
        ...
```

**Loading.** The `profiles` package is both the Python module (containing `__init__.py`) and the container for JSON data files. JSON files are loaded via `importlib.resources.files("petasos.premium.profiles")` — since `profiles/` is a proper package (with `__init__.py`), this resolves to the package directory, and JSON files are discovered as siblings of `__init__.py`. Loaded once at construction, frozen into `ResolvedProfile` instances. No filesystem access after init.

**Validation errors during ProfileResolver construction are programming errors** (broken package), not runtime errors. They raise at import/construction time, before any `inspect()` call. This is consistent with dataclass `__post_init__` validation patterns and does not violate the "pipeline never throws" invariant (which applies to `inspect()` calls, not construction).

**register() is intended for application startup.** It should not be called concurrently with `resolve()`. For multi-threaded deployments, callers must synchronize access to `register()`. This is acceptable because asyncio (the primary use case) is single-threaded; multi-threaded callers configure profiles before starting the event loop.

**Resolution logic:**
1. If `name_or_dict` is a `str`: look up in `self._profiles`. `KeyError` on miss.
2. If `name_or_dict` is a `dict`: start from the `general` profile, merge dict values on top (key-by-key). Unspecified fields inherit from `general`. Return a new `ResolvedProfile` with `name="custom"`.

**Merge semantics:**
- `suppress_rules`: union of base + override
- `severity_overrides`: override wins per key
- `confidence_floor`: override replaces base
- `tier_thresholds`: override replaces base (all three must be provided together)
- `pii_entities_extra`: union
- `tool_exempt_list`: override replaces base
- `tool_alias_map`: override wins per key

**Unknown keys** in the override dict are silently ignored (forward-compatibility with future profile fields). **Type mismatches** (e.g., string where float expected) raise `ValueError` at merge time with the offending key name. **Partial `tier_thresholds`:** if present in the override dict, all three keys (`tier1`, `tier2`, `tier3`) are required; missing keys raise `ValueError("tier_thresholds requires all three keys: tier1, tier2, tier3")`.

#### 5 built-in profiles

| Profile | `suppress_rules` | `severity_overrides` | `confidence_floor` | `tier_thresholds` | `pii_entities_extra` | `tool_exempt_list` |
|---------|---|---|---|---|---|---|
| `general` | `{}` | `{}` | `0.0` | `None` (use config defaults) | `()` | `{}` |
| `customer_service` | `{}` | injection rules → HIGH (raise from MEDIUM) | `0.0` | `None` | `("PERSON", "EMAIL", "PHONE_NUMBER")` | `{}` |
| `code_generation` | encoding rules suppressed (`petasos.syntactic.encoding.*`) | `{}` | `0.6` (drop low-confidence matches on code-like content) | `None` | `()` | `{}` |
| `research` | encoding rules + `petasos.syntactic.injection.inst-delimiter` suppressed | `{}` | `0.7` | `{tier1: 25, tier2: 45, tier3: 70}` | `()` | `{}` |
| `admin` | `{}` | `{}` | `0.0` | `{tier1: 10, tier2: 20, tier3: 35}` | `("PERSON", "EMAIL", "PHONE_NUMBER", "CREDIT_CARD", "IBAN_CODE")` | `{}` |

**`tool_exempt_list` normalization:** Entries in profile JSON are normalized at load time (lower-cased) by `ProfileResolver`. This ensures the exempt check at guard step 4 (which compares against the fully-normalized tool name) matches correctly regardless of how entries are cased in JSON.

**`tool_alias_map` validation:** Values in `tool_alias_map` are validated at profile load time — empty-string values raise `ValueError("tool_alias_map values must be non-empty")`. This prevents aliases from silently mapping tools to empty names (which would trigger the postcondition block at step 1e with a misleading error).

**JSON loading:** Built-in profiles are loaded via `traversable.read_text(encoding="utf-8")` to ensure consistent behavior across editable installs and wheel installs on all platforms (avoids Windows default UTF-16 BOM encoding).

**Decision: profile names use underscores, not hyphens.** JSON filenames and profile lookup keys are `snake_case` (`customer_service`, `code_generation`). Consistent with Python identifiers and config field naming throughout the codebase. (Brief used hyphens; this is a deliberate adaptation to Python conventions.)

### D2: ToolCallGuard (`petasos/premium/guard.py`)

#### GuardResult dataclass

```python
@dataclass(frozen=True)
class GuardResult:
    allowed: bool
    reason: str
    findings: tuple[ScanFinding, ...]
    tier: str                   # "none", "tier1", "tier2", "tier3"
    param_scan_unsafe: bool     # True if parameter content scanning found HIGH/CRITICAL

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "findings": [f.to_dict() for f in self.findings],
            "tier": self.tier,
            "param_scan_unsafe": self.param_scan_unsafe,
        }
```

**Decision: `tier` is `str`, not `int`.** The brief specified `tier: int` but `evaluate_tier()` (PET-7) returns string values (`"none"`, `"tier1"`, `"tier2"`, `"tier3"`). Using `str` avoids lossy conversion and aligns with the established type throughout the premium layer.

#### ToolCallGuard class

```python
class ToolCallGuard:
    def __init__(
        self,
        pipeline: Pipeline,
        frequency_tracker: FrequencyTracker,
        config: PetasosConfig,
        profile: ResolvedProfile | None = None,
    ) -> None:
        ...

    async def evaluate(
        self,
        tool_name: str,
        tool_params: dict[str, Any],
        session_id: str,
    ) -> GuardResult:
        ...
```

**Decision: ToolCallGuard receives `config: PetasosConfig` directly in its constructor** (same pattern as `FrequencyTracker(config)`). It does not reach into `pipeline._config`. This preserves encapsulation and ensures mypy --strict compliance. The config is used for `evaluate_tier()` calls and for checking `tool_guard_enabled`.

#### Evaluation flow (inside `evaluate()`)

```
0. PREMIUM GATE:
   If not self._pipeline.is_premium_active("tool_guard"):
     Return GuardResult(allowed=True, reason="premium inactive",
                        findings=(), tier="none", param_scan_unsafe=False)
   This is a deliberate fail-open for unlicensed deployments.
   The entire escalation + guard system is a premium feature.

1. Normalize tool name:
   a. Case-fold (lower())
   b. Strip namespace prefixes: regex ^(?:mcp__[a-zA-Z0-9_]+__|hermes__)
      Only strips the first match (no recursive stripping).
   c. Map aliases: combined_map = DEFAULT_TOOL_ALIASES | profile.tool_alias_map
      (profile entries override defaults for same key). Single lookup in combined map.
   d. Strip whitespace
   e. POSTCONDITION: if normalized_name is empty after all transformations,
      Return GuardResult(allowed=False, reason="invalid tool name: empty after normalization",
                         findings=(), tier="none", param_scan_unsafe=False)

2. Derive current escalation tier:
   state = frequency_tracker.get_state(session_id)
   if state is None: tier = "none"
   elif state.terminated: tier = "tier3"
   else:
     # Use profile tier thresholds if available, otherwise config thresholds
     if self._profile and self._profile.tier_thresholds:
       t = self._profile.tier_thresholds
       if state.last_score >= t.tier3: tier = "tier3"
       elif state.last_score >= t.tier2: tier = "tier2"
       elif state.last_score >= t.tier1: tier = "tier1"
       else: tier = "none"
     else:
       tier = evaluate_tier(state.last_score, self._config)

3. Tier 3 → BLOCK (hardcoded, cannot be overridden)
   Return GuardResult(allowed=False, reason="session terminated (tier3)",
                      findings=(), tier="tier3", param_scan_unsafe=False)

4. Check tool against exempt list (profile.tool_exempt_list):
   If normalized_name in exempt list → allow without param scanning
   Return GuardResult(allowed=True, reason="tool exempt per profile",
                      findings=(), tier=tier, param_scan_unsafe=False)

5. Scan parameter content:
   a. Short-circuit: if tool_params is empty, skip scanning.
      Set param_scan_unsafe=False, findings=()
   b. Serialize: for each (key, value) in tool_params.items():
      - Skip entries where value is None
      - If value is str: use as-is
      - Otherwise: try json.dumps(value); on TypeError, fall back to str(value)
      Join non-None serialized values with "\n" → param_text
      (The TypeError fallback handles non-JSON-serializable values like bytes, datetime,
      or custom objects that may appear in Hermes hook payloads. str() produces a
      scannable representation without crashing the guard.)
   c. Short-circuit: if param_text is empty after join, skip scanning.
   d. Scan: result = await pipeline.inspect(param_text, direction="outbound",
                                            session_id=session_id)
   e. Interpret: if result.errors and not result.findings:
      # Pipeline failed internally, not a content detection
      param_scan_unsafe = False
      findings = ()
      Otherwise:
      param_scan_unsafe = not result.safe
      findings = result.findings

6. Tier 2 → BLOCK unless exempt (already checked in step 4)
   Return GuardResult(allowed=False,
                      reason="tier2: tool calls blocked",
                      findings=findings, tier="tier2",
                      param_scan_unsafe=param_scan_unsafe)

7. Tier 1 with unsafe params → WARN (allow=True but flag)
   Return GuardResult(allowed=True,
                      reason="tier1: allowed with warnings",
                      findings=findings, tier="tier1",
                      param_scan_unsafe=param_scan_unsafe)

8. Tier 1 clean OR no tier → ALLOW
   Return GuardResult(allowed=True, reason="allowed",
                      findings=findings, tier=tier,
                      param_scan_unsafe=param_scan_unsafe)
```

**Decision: ToolCallGuard is a standalone callable, not a pipeline stage.** Different inputs (tool name + params vs. text + direction), different lifecycle (pre-tool-call hook vs. content scanning). The guard *uses* the pipeline internally for parameter scanning but is not composed into the pipeline's stage sequence. This keeps Pipeline's single responsibility (content scanning) clean.

#### Tool name normalization details

**Default alias map** (built into ToolCallGuard, immutable):

```python
DEFAULT_TOOL_ALIASES: MappingProxyType[str, str] = MappingProxyType({
    "bash": "exec",
    "shell": "exec",
    "terminal": "exec",
    "file_read": "read",
    "read_file": "read",
    "file_write": "write",
    "write_file": "write",
    "web_fetch": "browser",
    "web_search": "browser",
    "http_request": "browser",
})
```

**Namespace stripping regex:** `^(?:mcp__[a-zA-Z0-9_]+__|hermes__)` — strips the matched prefix. Applied once (no recursive stripping). Examples:
- `mcp__plane__list_projects` → `list_projects`
- `hermes__terminal` → `terminal`
- `mcp__mcp__tool` → `mcp__tool` (first prefix stripped, no re-application)
- `read_file` → unchanged (no prefix match)
- `hermes__` → `` (empty — caught by postcondition in step 1e)

### D3: Pipeline integration

#### `Pipeline.__init__()` changes

```python
class Pipeline:
    def __init__(
        self,
        scanners: Sequence[Scanner] = (),
        *,
        config: PetasosConfig | None = None,
        profile: str | ResolvedProfile | None = None,  # NEW
    ) -> None:
        ...
        self._profile_resolver = ProfileResolver()
        self._default_profile: ResolvedProfile | None = self._resolve_profile(profile)
```

Resolution logic for `_resolve_profile()`:

```python
def _resolve_profile(self, profile: str | ResolvedProfile | None) -> ResolvedProfile | None:
    if isinstance(profile, ResolvedProfile):
        return profile
    if isinstance(profile, str):
        return self._profile_resolver.resolve(profile)  # KeyError on invalid name
    if self._config.profile_name:  # truthy check: None and "" both skip
        return self._profile_resolver.resolve(self._config.profile_name)
    return None
```

If a string name is invalid, `KeyError` propagates at construction time (programming error, same category as malformed JSON). Empty string `profile_name` is treated as "no profile" (same as `None`) — this is the defensive path since empty string is an unintentional config value, not a real profile lookup. No profile active means `_default_profile` is `None` — premium profile features are all no-ops.

#### `Pipeline.config` property (NEW)

```python
@property
def config(self) -> PetasosConfig:
    return self._config
```

Read-only access for ToolCallGuard and other external consumers. Returns the frozen config directly (no copy needed since PetasosConfig is a frozen dataclass).

#### `Pipeline.is_premium_active()` method (NEW)

```python
def is_premium_active(self, feature_name: str) -> bool:
    return self._check_premium(feature_name)
```

Public method exposing the premium gate check to external consumers (ToolCallGuard, future audit consumers). Delegates to the internal `_check_premium()` without exposing its implementation. This avoids private-method access from external classes while keeping `_check_premium` as the single internal implementation.

#### `Pipeline.inspect()` changes

```python
async def inspect(
    self,
    text: str,
    *,
    direction: Direction | None = None,
    session_id: str | None = None,
    profile: str | ResolvedProfile | dict[str, Any] | None = None,  # NEW
) -> PipelineResult:
```

When `profile` is provided, it overrides the pipeline's default profile for this call only. Dict values are resolved via `ProfileResolver.resolve(dict)`.

#### Modified `_inspect_inner()` flow

The profile hook inserts between Stage 1 (normalize) and Stage 2 (syntactic pre-filter). Profile-driven confidence floor filtering and severity overrides insert between Stage 5 (merge findings) and Stage 6 (frequency hook). The modified flow:

```
Stage 1:  Normalize text
Stage 1b: Profile hook → effective_scanner = _premium_profile_hook(active_profile)
Stage 2:  Syntactic pre-filter using effective_scanner (not self._minimal_scanner)
Stage 3:  Early exit check (closed mode)
Stage 4:  ML scanner fan-out
Stage 5:  Merge findings
Stage 5b: Confidence floor filtering (drop findings where finding.confidence < profile.confidence_floor;
          strict less-than, so floor=0.0 is a no-op). Only applies when is_premium_active("profiles")
          AND active_profile is not None. Otherwise no-op.
Stage 5c: Severity overrides (reconstruct findings with overridden severities). Same premium gate as 5b.
Stage 6:  Premium frequency hook (operates on filtered merged)
Stage 7:  Premium escalation hook
Stage 8:  _compute_safe (operates on filtered merged — respects profile adjustments)
Stage 9:  Anonymize
Stage 10: Build result
Stage 11: Audit hook
Stage 12: Alert hook
Stage 13: Return
```

**Key ordering invariant:** Stages 5b and 5c modify `merged` BEFORE `_compute_safe()` (Stage 8). This means the `safe` determination respects profile adjustments — a HIGH finding dropped by `confidence_floor` does not make `safe=False`.

#### `_premium_profile_hook()` — new hook

Runs at Stage 1b, between normalization and the syntactic pre-filter. Returns the scanner to use for Stage 2.

```python
async def _premium_profile_hook(
    self,
    profile: ResolvedProfile | None,
) -> MinimalScanner:
    if profile is None:
        return self._minimal_scanner
    if not self._check_premium("profiles"):
        return self._minimal_scanner
    if not profile.suppress_rules:
        return self._minimal_scanner
    return self._minimal_scanner.with_suppress_rules(profile.suppress_rules)
```

**Double gate:** The hook checks both `is_premium_active("profiles")` and whether the profile has any suppress_rules to apply. If neither is active, it returns the stored scanner (no copy). This matches the PET-7 pattern where hooks gate on `_check_premium(feature)` + a config toggle.

**Decision: copy-on-read, not mutation.** The pipeline's stored `MinimalScanner` and config are never mutated. Each `inspect()` call that has a profile override creates a local scanner copy with the profile's adjustments. Concurrent calls with different profiles cannot interfere.

**MinimalScanner.with_suppress_rules() factory method (NEW):**

```python
# Added to MinimalScanner class
def with_suppress_rules(self, additional: frozenset[str]) -> MinimalScanner:
    """Return a new MinimalScanner with additional rules suppressed."""
    return MinimalScanner(
        max_payload_bytes=self._max_payload_bytes,
        max_json_depth=self._max_json_depth,
        suppress_rules=self._suppress_rules | additional,
    )
```

This encapsulates the copy logic and avoids external access to MinimalScanner's private attributes. The profile hook becomes:

```python
return self._minimal_scanner.with_suppress_rules(profile.suppress_rules)
```

#### `_build_premium_features()` update

```python
"profiles": "unlocked" if active and self._default_profile is not None else "locked",
"tool_guard": "unlocked" if active and self._config.tool_guard_enabled else "locked",
```

Uses `self._default_profile is not None` (covers string-resolved, direct ResolvedProfile, and config.profile_name paths) rather than checking only `config.profile_name`.

---

## Decisions

### Profile package structure: `profiles/` is a package, not a sibling file

The profiles module lives at `petasos/premium/profiles/__init__.py` (a proper Python package). JSON data files live alongside `__init__.py` in the same package directory. This avoids the importlib.resources resolution conflict that would occur if both `profiles.py` (module) and `profiles/` (directory) existed at the same level. `importlib.resources.files("petasos.premium.profiles")` correctly resolves to the package directory containing both `__init__.py` and the JSON files.

### ToolCallGuard receives config directly

ToolCallGuard accepts `config: PetasosConfig` in its constructor (same pattern as `FrequencyTracker(config)`). It does not access `pipeline._config`. This preserves encapsulation and passes mypy --strict.

### Profile tier_thresholds bridge into ToolCallGuard

When a profile has non-None `tier_thresholds`, the guard uses those values for tier derivation (inline comparison) rather than calling `evaluate_tier(score, config)`. This ensures that profile-specific escalation sensitivity is respected in the guard's blocking decisions.

### Profile storage: bundled JSON in the package

Profiles are loaded from JSON files co-located with `__init__.py` in the `petasos/premium/profiles/` package. JSON profiles can be validated, serialized, and eventually edited by a frontend config UI without touching Python. The `ProfileResolver` loads and freezes them at construction time via `importlib.resources`.

### ToolCallGuard is standalone, not a pipeline stage

ToolCallGuard has different inputs (tool name, params) than content scanning (text, direction). The guard *uses* the pipeline internally (for parameter scanning) but isn't part of Pipeline's stage sequence. This matches the Drawbridge architecture and keeps Pipeline's single-responsibility (content scanning) clean.

### Copy-on-read for per-call profile override

When `Pipeline.inspect(profile="admin")` overrides the default profile, the override creates a local `MinimalScanner` copy with profile adjustments applied. The pipeline's stored scanner and config are never mutated. Frozen defaults + per-call copies = thread-safe without locks.

### Integration via hooks, not fork

ToolCallGuard layers on top of Hermes via `pre_tool_call` hooks. No fork of `tool_guardrails.py`, no coupling to Hermes internals. The hook shim is thin: deserialize hook payload → call `guard.evaluate()` → return decision. This keeps Petasos a pure library and defers integration specifics to PET-11.

### Tier 3 cannot be overridden

Hardcoded invariant carried from the spec. ToolCallGuard enforces this: Tier 3 blocks all tool calls regardless of profile, allowlist, or config. No profile can exempt a tool at Tier 3.

### ToolCallGuard fails open when premium inactive

Step 0 of the evaluation flow returns `allowed=True` when premium is not active. This is deliberate: the entire escalation + guard system is a premium feature. Without a license, no tool calls are blocked. This matches the PET-7 pattern where premium hooks are no-ops when inactive.

### Confidence floor positioning: post-merge, not pre-fan-out

The brief mentions profile adjustments applied "before scanner fan-out." For `suppress_rules`, this is literally true (Stage 1b, before syntactic pre-filter). For `confidence_floor` and `severity_overrides`, these operate on scanner output (findings) and therefore must run post-merge. Positioning them at Stage 5b/5c — after merge but before frequency hooks and `_compute_safe()` — ensures the `safe` determination respects profile-adjusted findings.

---

## Test plan

### `tests/test_profiles.py` (>=25 tests)

1. **Loading**: All 5 built-in profiles load without error
2. **Frozen**: Profiles are frozen dataclasses (attribute mutation raises)
3. **Resolve by name**: `resolver.resolve("admin")` returns the admin profile
4. **Resolve unknown**: `resolver.resolve("nonexistent")` raises `KeyError`
5. **Custom dict merge**: Dict merge inherits unspecified fields from `general`
6. **Suppress rules union**: Custom dict with `suppress_rules` unions with base
7. **Severity overrides**: Custom dict overrides replace base per key
8. **Confidence floor**: Non-zero floor drops low-confidence findings in pipeline
9. **Tier thresholds validation**: Invalid thresholds (non-ascending, tier3 < floor) raise `ValueError`
10. **PII entities extra**: Customer-service profile adds PERSON, EMAIL, PHONE_NUMBER
11. **Tool exempt list**: Profile exempt list passes through to ToolCallGuard
12. **Pipeline with profile string**: `Pipeline(profile="admin")` resolves correctly
13. **Pipeline with ResolvedProfile**: Direct profile object accepted
14. **Per-call override**: `inspect(profile="code_generation")` uses override, doesn't mutate pipeline
15. **Concurrent inspect calls**: Two concurrent `inspect()` with different profiles don't interfere
16. **Profile hook gated by premium**: Profile adjustments only apply when `_premium_active=True`
17. **Code-generation suppression**: Encoding rules suppressed, injection rules still fire
18. **Admin tier thresholds**: tier1=10, tier2=20, tier3=35 reflected in guard tier derivation
19. **Register custom profile**: `resolver.register("custom", profile)` makes it resolvable by name
20. **General profile is identity**: General profile produces no scanner adjustments
21. **Config.profile_name integration**: `PetasosConfig(profile_name="admin")` picked up by Pipeline
22. **Severity override produces new finding instance**: Original finding unchanged
23. **Profile JSON schema validation**: Malformed JSON raises at resolver init
24. **Empty suppress_rules roundtrip**: Empty frozenset serializes/deserializes cleanly
25. **importlib.resources loading**: Profiles load in installed-package context (not just dev)
26. **ResolvedProfile.to_dict()**: Round-trip serialization

### `tests/test_guard.py` (>=30 tests)

1. **Tier 3 blocks unconditionally**: Terminated session → allowed=False regardless of tool/params
2. **Tier 2 blocks non-exempt tools**: Non-exempt tool at tier2 → allowed=False
3. **Tier 2 allows exempt tools**: Exempt tool at tier2 → allowed=True
4. **Tier 1 allows with warning**: tier1 + unsafe params → allowed=True, param_scan_unsafe=True
5. **No tier allows clean**: No findings, no tier → allowed=True
6. **Tool name case folding**: "READ_FILE" normalized to "read_file"
7. **MCP namespace stripping**: "mcp__plane__list_projects" → "list_projects"
8. **Hermes namespace stripping**: "hermes__terminal" → "terminal"
9. **Alias mapping**: "bash" → "exec", "file_read" → "read"
10. **Profile alias map extends defaults**: Custom alias added via profile
11. **Whitespace stripped**: " read_file " → "read_file"
12. **Param scanning routes through pipeline**: Malicious param content detected
13. **Param scanning uses direction=outbound**: Confirmed via mock/spy
14. **GuardResult is frozen**: Attribute mutation raises
15. **Empty params short-circuit**: `tool_params={}` → no pipeline.inspect() call, param_scan_unsafe=False
16. **None-valued params skipped**: `{"key": None}` → None entries excluded from param_text
17. **Non-string params JSON-serialized**: Dict/list params use json.dumps for scanning
18. **Session not in tracker**: Unknown session_id → tier="none", allowed=True
19. **Multiple findings from param scan**: All findings propagated to GuardResult
20. **Exempt list check before param scanning**: Exempt tool skips scanning entirely
21. **Tier 3 check before param scanning**: Tier3 short-circuits without scanning
22. **Default alias map coverage**: All 10 default aliases resolve correctly
23. **Namespace prefix with numbers**: "mcp__server_2__tool" strips correctly
24. **No double-strip**: "mcp__mcp__tool" → "mcp__tool" (only first prefix stripped)
25. **Guard with no profile**: `ToolCallGuard(pipeline, tracker, config, profile=None)` works
26. **Guard with profile exempt list**: Profile exempts "read" → bash/file_read mapped and checked
27. **Pipeline error during param scan**: result.errors + no findings → param_scan_unsafe=False
28. **Concurrent guard evaluations**: Multiple async evaluate() calls don't interfere
29. **Guard premium gate**: Premium inactive → returns allowed=True (pass-through)
30. **GuardResult.to_dict()**: Serialization for hook response
31. **Empty tool name after normalization**: "hermes__" → blocked with "invalid tool name"
32. **Profile tier_thresholds in guard**: Admin profile (tier1=10) triggers tier1 at score=12
33. **Integration: full flow tier1→tier2→tier3**: Session escalation reflected in successive calls

### Test interactions with existing tests

- `tests/test_premium_integration.py` — extend with profile + guard integration scenarios
- `tests/test_pipeline.py` — add tests for `profile` param in `inspect()` and `__init__()`
- Existing frequency/escalation tests remain untouched (PET-8 consumes, doesn't modify)

## Test command

```
python -m pytest tests/test_profiles.py tests/test_guard.py tests/test_pipeline.py tests/test_premium_integration.py -v
```

---

## Done when

- [ ] `ProfileResolver` loads all 5 built-in profiles from bundled JSON and freezes them
- [ ] Each profile demonstrably adjusts scanner thresholds (tested with MinimalScanner)
- [ ] Custom profile via dict overrides built-in values; unspecified fields inherit from `general`
- [ ] `ToolCallGuard.evaluate()` blocks at Tier 2 (unless allowlisted) and Tier 3 (unconditional)
- [ ] `ToolCallGuard.evaluate()` warns at Tier 1 (allowed=True, findings populated)
- [ ] Parameter content scanning routes through `Pipeline.inspect(direction="outbound")` and produces findings
- [ ] Tool name normalization handles: case folding, namespace stripping (`mcp__`, `hermes__`), alias mapping, whitespace
- [ ] `Pipeline.inspect()` accepts optional `profile` override without mutating stored config
- [ ] `Pipeline.__init__()` resolves string profile names via `ProfileResolver`
- [ ] `GuardResult` is a frozen dataclass with `allowed`, `reason`, `findings`, `tier`, `param_scan_unsafe`
- [ ] >=50 tests across profiles + guard modules
- [ ] All premium code gated behind `self._premium_active` (PET-7 scaffold)

---

## Out of scope

- **JWT license validation** — PET-10. PET-8 uses the `_premium_active` boolean flag from PET-7; real JWT validation comes later.
- **Audit trail emission from ToolCallGuard** — PET-9. Guard results are returned to the caller; audit logging of guard decisions is wired in PET-9.
- **Hermes integration testing** — PET-11. PET-8 delivers the API; PET-11 tests it end-to-end in the Hermes hook pipeline.
- **Profile editing UI** — future. JSON format is chosen to enable this, but no frontend work is in scope.
- **MCP tool result scanning** — post-tool-call analysis is a separate concern from pre-call guarding.
- **Network-based policy sync** — Petasos is offline-first. Profiles are bundled, not fetched.
- **Microsoft AGT integration** — complementary tool, no runtime dependency.

---

## Deferred (P2+)

- `SessionState` type not explicitly re-exported from `premium/__init__.py` — guard imports it directly from `petasos.premium.frequency`. Acceptable since `SessionState` is an internal type used only for the `get_state()` return value; external callers interact with `GuardResult`, not `SessionState`.
- `DEFAULT_TOOL_ALIASES` uses `MappingProxyType` for frozen-export compliance (addressed in design).
- `TierThresholds` validation shares logic with `PetasosConfig.__post_init__` via `_validate_tier_thresholds()` helper (addressed in design).
- Empty `session_id` string is treated as "no session" (tier=none, no frequency tracking). This is acceptable — Hermes always provides a valid session ID; empty string is a caller bug that fails open rather than crashing.
- `DEFAULT_FREQUENCY_WEIGHTS` in `frequency.py` is a plain dict (existing tech debt predating PET-8). PET-8's new `DEFAULT_TOOL_ALIASES` correctly uses `MappingProxyType`; migrating `DEFAULT_FREQUENCY_WEIGHTS` is a future hardening task.
- CLAUDE.md Target Layout update included in Files to modify table.
