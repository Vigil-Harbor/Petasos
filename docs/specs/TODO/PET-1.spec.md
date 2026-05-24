# PET-1 — Repo Bootstrap + Core Types + MinimalScanner + Normalization

> **Spec version:** v3 (revised round 2)
> **Brief:** `docs/briefs/PET-1-brief.md`
> **Plane:** PET-1 (`e693b18a`), project `5bff6316-84ea-4103-b9e2-4861ac9c226a`
> **Author:** Claude (spec-cycle)
> **Date:** 2026-05-24

---

## Goal

Stand up the Petasos greenfield repo with every core abstraction that downstream work items depend on: the `Scanner` protocol and type system, the 17-rule `MinimalScanner` ported from Drawbridge, the Unicode normalization layer, and the repo scaffolding (Hatch, ruff, mypy, pytest, CI). When this lands, three parallel scanner-wrapper squads (PET-3/4/5) can start immediately against the stable `Scanner` protocol.

---

## Scope

### Files to create

```
pyproject.toml                          # Hatch build, Python >=3.11, extras
ruff.toml                              # Lint + format config
.github/workflows/ci.yml               # Lint -> typecheck -> test matrix
petasos/__init__.py                    # Public API re-exports
petasos/_types.py                      # Scanner protocol, all result types
petasos/normalize.py                   # Unicode normalization layer
petasos/scanners/__init__.py           # Scanner subpackage
petasos/scanners/minimal.py            # MinimalScanner (17 rules)
petasos/py.typed                       # PEP 561 marker
tests/__init__.py                      # Test package
tests/conftest.py                      # Shared fixtures
tests/test_types.py                    # Protocol + dataclass tests
tests/test_normalize.py                # Normalization tests
tests/test_minimal_scanner.py          # MinimalScanner rule coverage
```

### Files to leave alone

- `petasos-spec.md`, `petasos-work-items.md`, `petasos-project-spec-DRAFT-PARKED.md` — project planning docs, not code
- `docs/` — spec/brief directory structure
- `CLAUDE.md` — already written
- `.gitignore` — already exists

### Out of scope

- ML scanner backends (PET-3/4/5)
- Pipeline orchestration (PET-6)
- Frequency tracking / escalation (PET-7)
- Profiles / tool call guard (PET-8)
- Audit / alerting (PET-9)
- JWT license validation (PET-10)
- Hermes integration testing (PET-11)
- PyPI publish (PET-12)
- Any network calls at runtime

---

## Decisions

### D1: Curated homoglyph table, not full ICU confusables

Port Drawbridge's 17-character homoglyph map (8 Cyrillic, 7 Greek, 1 Latin, 1 IPA). Full ICU confusables table is ~8K entries and adds import weight. The curated subset covers attack-relevant substitutions (Cyrillic а→a, Greek ο→o, etc.). Expand in patch releases if evasion reports demonstrate gaps.

### D2: `petasos.*` namespace for rule IDs

Rule IDs are `petasos.syntactic.<category>.<slug>` (e.g., `petasos.syntactic.injection.ignore-previous`). Not `drawbridge.*` — Petasos is uncoupled, own identity, own release cadence. Heritage acknowledged in code comments, not in runtime identifiers.

### D3: Frozen dataclasses for all result types

All result types (`ScanResult`, `ScanFinding`, `PipelineResult`, `NormalizedText`) use `@dataclass(frozen=True)`. Security library — mutation after construction is a bug vector. Matches Drawbridge's `Object.freeze` pattern. `ScanFinding` and `ScanResult` provide `to_dict()` / `from_dict()` helpers for JSON serialization. `PipelineResult` defers serialization helpers to PET-6 (when the full field set is defined). `NormalizedText` is an internal intermediate and does not need serialization.

### D4: `pytest-asyncio` for scanner testing

Scanner protocol is async (`async def scan(...)`). Testing without asyncio fixtures hides concurrency bugs. Use `pytest-asyncio` with `mode = "auto"` in `pyproject.toml`.

### D5: RTL override — detect and flag, don't strip

RTL control characters (U+202E, U+202D, U+2066–U+2069) are detected and reported as a `ScanFinding` but not removed from the text. Stripping RTL controls breaks legitimate bidirectional text. Detection-only preserves content fidelity while alerting to evasion attempts.

### D6: Homoglyph-substitution fires unconditionally (diverges from Drawbridge)

Drawbridge gates the `homoglyph-substitution` rule on a conjunction: the rule only fires when `confusablesNormalized AND injectionMatchedOnNormalized` — i.e., homoglyphs co-occur with an injection pattern match. Petasos fires the rule whenever `confusables_normalized` is true, regardless of injection co-occurrence.

**Rationale:** Petasos is a detection library, not a gateway. False positives on benign Cyrillic/Greek text are acceptable at LOW severity because the downstream pipeline (PET-6) and profiles (PET-8) can suppress or filter by severity. Gating on injection co-occurrence creates a temporal coupling between the encoding and injection rule categories that complicates the scanner's internal logic and makes the rule's behavior harder to reason about in isolation. If false-positive volume is too high in practice, PET-8 profiles can suppress the rule or PET-6 can apply the conjunction at the pipeline level.

### D7: Suppression semantics

`suppress_rules` on `MinimalScanner.__init__()` controls which rules are skipped entirely — a suppressed rule does not run and produces no finding. Specifics:

1. **Suppression prevents execution**, not just output filtering. A suppressed rule's regex is never evaluated.
2. **Structural rules cannot be suppressed.** If a structural rule ID (`can_suppress=False`) appears in `suppress_rules`, it is silently ignored — no error, no finding about the invalid suppression. Structural rules are security-critical and their suppression is a design error, not a user preference.
3. **Suppression does not affect escalation logic.** The invisible-chars escalation checks whether any *non-suppressed* injection rule matched. If all injection rules are suppressed, invisible-chars cannot escalate.

---

## Design

### 1. Project scaffolding (`pyproject.toml`)

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "petasos"
version = "0.0.1"
requires-python = ">=3.11"
license = "MIT"
dependencies = []  # Zero required deps at base install

[project.optional-dependencies]
llm-guard = ["llm-guard>=0.3.16,<0.4"]
llamafirewall = ["llamafirewall"]
presidio = [
    "presidio-analyzer>=2.2,<3.0",
    "presidio-anonymizer>=2.2,<3.0",
]
all = ["petasos[llm-guard,llamafirewall,presidio]"]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-cov>=5.0",
    "mypy>=1.10",
    "ruff>=0.4",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"

[tool.mypy]
strict = true
python_version = "3.11"
```

### 2. Core types (`petasos/_types.py`)

All types in a single module. Downstream work items import from here.

```python
from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

Direction = Literal["inbound", "outbound"]

class Severity(enum.Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"

@dataclass(frozen=True)
class Position:
    start: int
    end: int

@dataclass(frozen=True)
class ScanFinding:
    rule_id: str
    finding_type: str  # e.g., "injection", "encoding", "structural", "pii"
    severity: Severity
    confidence: float  # 0.0–1.0
    message: str
    scanner_name: str
    position: Position | None = None
    matched_text: str | None = None

    def to_dict(self) -> dict[str, Any]: ...

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScanFinding: ...

@dataclass(frozen=True)
class ScanResult:
    scanner_name: str
    findings: tuple[ScanFinding, ...]  # tuple for immutability
    duration_ms: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]: ...

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScanResult: ...

@runtime_checkable
class Scanner(Protocol):
    @property
    def name(self) -> str: ...

    async def scan(
        self,
        text: str,
        *,
        direction: Direction = "inbound",
        session_id: str | None = None,
    ) -> ScanResult: ...

@dataclass(frozen=True)
class NormalizedText:
    original: str
    normalized: str
    transformations_applied: tuple[str, ...]
    invisible_chars_stripped: int = 0
    confusables_normalized: bool = False
    rtl_overrides_detected: bool = False
```

Key design choices:
- `ScanResult.findings` is `tuple`, not `list` — frozen dataclass with a mutable field is a false guarantee. Tuple enforces immutability all the way down.
- `Scanner` is `@runtime_checkable` so downstream code can do `isinstance(obj, Scanner)` for validation.
- `Position` is its own dataclass rather than a bare tuple — named fields prevent `start`/`end` transposition bugs.
- `PipelineResult` is **not defined here** — it belongs in PET-6 (pipeline orchestration) because its fields depend on premium features (escalation tier, session score, premium manifest) that don't exist yet. Defining it prematurely here would force a breaking change in PET-6. The brief's type table lists it as a PET-1 deliverable, but the correct scope is: define a placeholder in `_types.py` with only the fields knowable now (`safe`, `findings`, `sanitized_content`, `scanner_results`, `errors`) and document that PET-6 will extend it.

```python
@dataclass(frozen=True)
class PipelineResult:
    """Aggregate result from pipeline execution.

    PET-6 extends this with premium fields (escalation_tier, session_score,
    premium_features). The base definition here covers OSS-tier fields only.
    """
    safe: bool
    findings: tuple[ScanFinding, ...]
    sanitized_content: str | None = None
    scanner_results: tuple[ScanResult, ...] = ()
    errors: tuple[str, ...] = ()
```

### 3. Normalization module (`petasos/normalize.py`)

Port of Drawbridge's `normalizeForDetection()` from `src/validation/normalize.ts`. Four transforms, executed in order:

**Step 1 — RTL override detection** (before stripping):
```python
RTL_OVERRIDES = frozenset([
    "\u202A",  # LRE
    "\u202B",  # RLE
    "\u202C",  # PDF
    "\u202D",  # LRO
    "\u202E",  # RLO
    "\u2066",  # LRI
    "\u2067",  # RLI
    "\u2068",  # FSI
    "\u2069",  # PDI
])
```
Scan for presence. Set flag. Do not remove.

**Step 2 — Invisible character stripping:**
```python
INVISIBLE_CHARS = frozenset([
    "\u0000",  # null
    "\u00AD",  # soft hyphen
    "\u200B",  # zero-width space
    "\u200C",  # ZWNJ
    "\u200D",  # ZWJ
    "\u200E",  # LRM
    "\u200F",  # RLM
    "\u202A",  # LRE
    "\u202B",  # RLE
    "\u202C",  # PDF
    "\u202D",  # LRO
    "\u202E",  # RLO
    "\u202F",  # narrow no-break space
    "\u2060",  # word joiner
    "\u2061",  # function application
    "\u2062",  # invisible times
    "\u2063",  # invisible separator
    "\u2064",  # invisible plus
    "\u2066",  # LRI
    "\u2067",  # RLI
    "\u2068",  # FSI
    "\u2069",  # PDI
    "\uFEFF",  # BOM / ZWNBSP
])
```
Strip all occurrences. Count stripped characters. Deliberately excludes U+2028/U+2029 (line/paragraph separators) to preserve `^SYSTEM:` multiline anchor detection.

**Step 3 — NFKC normalization:**
```python
unicodedata.normalize("NFKC", text)
```
Handles fullwidth Latin (Ａ→A), mathematical alphanumerics, compatibility characters.

**Step 4 — Homoglyph mapping:**

Character-by-character substitution using Drawbridge's curated 17-character table:

| Char | Codepoint | Maps to | Script |
|------|-----------|---------|--------|
| а | U+0430 | a | Cyrillic |
| е | U+0435 | e | Cyrillic |
| о | U+043E | o | Cyrillic |
| р | U+0440 | p | Cyrillic |
| с | U+0441 | c | Cyrillic |
| у | U+0443 | y | Cyrillic |
| і | U+0456 | i | Cyrillic |
| ѕ | U+0455 | s | Cyrillic |
| α | U+03B1 | a | Greek |
| ε | U+03B5 | e | Greek |
| ο | U+03BF | o | Greek |
| ρ | U+03C1 | p | Greek |
| κ | U+03BA | k | Greek |
| ι | U+03B9 | i | Greek |
| ν | U+03BD | v | Greek |
| ı | U+0131 | i | Latin (dotless i) |
| ɡ | U+0261 | g | IPA |

Implementation: build a `str.translate()` table via `str.maketrans()` for O(n) single-pass mapping.

**`confusables_normalized` flag:** Set `confusables_normalized = True` if the text after steps 3 and 4 differs from the text after step 2 (invisible-char stripping). This captures both NFKC normalization changes (e.g., fullwidth Latin) and homoglyph substitutions, matching Drawbridge's computation (`normalized !== stripped`). NFKC-only obfuscation (e.g., fullwidth `＜ignore previous instructions＞`) is a real evasion vector and must set the flag.

**Return type:** `NormalizedText` with all metadata fields populated.

**Public API:**
```python
def normalize(text: str) -> NormalizedText: ...
```

### 4. MinimalScanner (`petasos/scanners/minimal.py`)

Port of Drawbridge's syntactic pre-filter. Implements the `Scanner` protocol. The scanner applies all 17 rules against normalized input and returns a `ScanResult` with findings.

**Architecture:**

```python
@dataclass(frozen=True)
class SyntacticRule:
    rule_id: str
    category: str          # "injection", "encoding", "structural"
    severity: Severity
    can_suppress: bool     # False for structural rules
    description: str

class MinimalScanner:
    def __init__(
        self,
        *,
        max_payload_bytes: int = 524_288,    # 512 KB
        max_json_depth: int = 10,
        suppress_rules: frozenset[str] = frozenset(),
    ) -> None: ...

    @property
    def name(self) -> str:
        return "minimal"

    async def scan(
        self,
        text: str,
        *,
        direction: Direction = "inbound",
        session_id: str | None = None,
    ) -> ScanResult: ...
```

**Exception guard:** The `scan()` method wraps its entire body in `try: ... except Exception as exc:` and returns `ScanResult(scanner_name=self.name, findings=(), error=str(exc))` on any unexpected failure. Individual scanners must never propagate exceptions — the caller receives a `ScanResult` with the `error` field set instead. This is the scanner-level equivalent of the pipeline-level "never throws" invariant.

**Rule implementation by category:**

#### 4a. Injection patterns (8 rules)

Each is a compiled `re.Pattern` tested against normalized text. All severity `HIGH`, `can_suppress=True`.

| Rule ID | Pattern (Python re) |
|---------|---------------------|
| `petasos.syntactic.injection.ignore-previous` | `re.compile(r"ignore previous instructions", re.IGNORECASE)` |
| `petasos.syntactic.injection.ignore-all` | `re.compile(r"ignore all instructions", re.IGNORECASE)` |
| `petasos.syntactic.injection.disregard` | `re.compile(r"disregard your", re.IGNORECASE)` |
| `petasos.syntactic.injection.you-are-now` | `re.compile(r"you are now", re.IGNORECASE)` |
| `petasos.syntactic.injection.new-instructions` | `re.compile(r"new instructions\s*:", re.IGNORECASE)` |
| `petasos.syntactic.injection.system-override` | `re.compile(r"system override", re.IGNORECASE)` |
| `petasos.syntactic.injection.system-prefix` | `re.compile(r"^SYSTEM:", re.MULTILINE)` |
| `petasos.syntactic.injection.inst-delimiter` | `re.compile(r"\[INST\]|</INST>", re.IGNORECASE)` |

#### 4b. Role-switch detection (2 rules)

Compound detection — trigger patterns + grant patterns:

**Triggers:** `you are a`, `act as`, `pretend you are`, `roleplay as` (all `re.IGNORECASE`)

**Grants:** `no restrictions`, `no limits`, `without filters`, `DAN mode`, `developer mode` (all `re.IGNORECASE`)

| Rule ID | Logic | Severity | Can suppress |
|---------|-------|----------|-------------|
| `petasos.syntactic.injection.role-switch-capability` | Trigger AND grant both match | HIGH | Yes |
| `petasos.syntactic.injection.role-switch-only` | Trigger matches, no grant | LOW | Yes (but never structural fail even without suppression) |

#### 4c. Structural checks (3 rules)

Not regex — structural analysis of raw input. Severity `CRITICAL`, `can_suppress=False`.

| Rule ID | Check |
|---------|-------|
| `petasos.syntactic.structural.oversized-payload` | `len(text.encode("utf-8")) > max_payload_bytes` |
| `petasos.syntactic.structural.excessive-depth` | JSON parse with depth tracking > `max_json_depth` |
| `petasos.syntactic.structural.binary-content` | `re.search(r"[\x01-\x08\x0e-\x1f]", text)` (excludes \t \n \r) |

**JSON depth check implementation:** Use an iterative approach — scan for `[` and `{` characters with an explicit depth counter, incrementing on open and decrementing on close brackets/braces. Do not use `json.loads()` with recursive hooks, as a deeply nested malicious payload (1000+ levels) will trigger `RecursionError` — the very attack this rule defends against. On non-JSON content (no brackets/braces found), skip the check (not a finding). Catch both `json.JSONDecodeError` and `RecursionError` as fallback guards if `json.loads()` is used for any auxiliary validation.

#### 4d. Encoding detection (4 rules)

| Rule ID | Check | Severity | Can suppress |
|---------|-------|----------|-------------|
| `petasos.syntactic.encoding.invisible-chars` | `normalized.invisible_chars_stripped > 0` | MEDIUM | Yes |
| `petasos.syntactic.encoding.base64-in-text` | `re.search(r"[A-Za-z0-9+/]{40,}={0,2}", text)` | LOW | Yes |
| `petasos.syntactic.encoding.homoglyph-substitution` | `normalized.confusables_normalized` | LOW | Yes |
| `petasos.syntactic.encoding.rtl-override` | `normalized.rtl_overrides_detected` | MEDIUM | Yes |

**Escalation rule:** If `invisible-chars` fires AND any **non-suppressed** injection rule also fires on the same input, escalate `invisible-chars` severity from MEDIUM to HIGH. This matches Drawbridge's "obfuscation + injection = intentional attack" signal.

#### 4e. Processing order

1. Run structural checks on raw input (oversized-payload, binary-content, excessive-depth)
2. Normalize input via `normalize()`
3. Run injection patterns on normalized text
4. Run role-switch detection on normalized text
5. Run encoding detection: invisible-chars, homoglyph, RTL use normalization metadata; base64 uses raw input
6. Apply invisible-chars escalation if injection + invisible co-occur
7. Collect all findings, return `ScanResult`

Structural checks run first because an oversized or binary payload should fail fast before normalization (which is O(n) on input size).

#### 4f. Rule taxonomy

Export a `RULE_TAXONOMY: frozenset[str]` containing all 17 rule IDs. Used by downstream profile validation (PET-8) to ensure only valid rule IDs appear in suppression lists.

### 5. Public API (`petasos/__init__.py`)

```python
from petasos._types import (
    Direction,
    NormalizedText,
    PipelineResult,
    Position,
    ScanFinding,
    ScanResult,
    Scanner,
    Severity,
)
from petasos.normalize import normalize
from petasos.scanners.minimal import MinimalScanner, RULE_TAXONOMY

__all__ = [
    "Direction",
    "MinimalScanner",
    "NormalizedText",
    "PipelineResult",
    "Position",
    "RULE_TAXONOMY",
    "ScanFinding",
    "ScanResult",
    "Scanner",
    "Severity",
    "normalize",
]

__version__ = "0.0.1"
```

### 6. CI stub (`.github/workflows/ci.yml`)

Matrix: Python 3.11, 3.12, 3.13. Three jobs:
1. `ruff check . && ruff format --check .`
2. `mypy --strict .`
3. `pytest --cov`

All three run on `ubuntu-latest`. Uses `pip install -e ".[dev]"` for tooling.

---

## Test plan

### `tests/test_types.py` (~15 tests)

- `Scanner` protocol is `runtime_checkable` — `isinstance` works on a trivial stub
- A minimal stub implementing `name` + `scan()` satisfies `Scanner`
- `ScanFinding` is frozen — mutation raises `FrozenInstanceError`
- `ScanResult` is frozen — mutation raises `FrozenInstanceError`
- `PipelineResult` is frozen — mutation raises `FrozenInstanceError`
- `NormalizedText` is frozen — mutation raises `FrozenInstanceError`
- `Severity` enum values match expected strings
- `ScanFinding.to_dict()` round-trips through JSON correctly
- `ScanResult.to_dict()` round-trips through JSON correctly
- `Position` fields are named (`start`, `end`), not positional-only
- `ScanResult` with empty findings tuple is valid
- `ScanResult` with error string set is valid
- `Direction` literal type accepts "inbound" and "outbound"

### `tests/test_normalize.py` (~20 tests)

- NFKC: fullwidth `ａ` (Ａ) normalizes to `a`
- NFKC: mathematical bold `\U0001D400` normalizes correctly
- Zero-width space (U+200B) stripped, count = 1
- Multiple invisible chars stripped, count accurate
- Soft hyphen (U+00AD) stripped
- BOM (U+FEFF) stripped
- ZWNJ (U+200C) and ZWJ (U+200D) stripped
- U+2028/U+2029 (line/paragraph separators) NOT stripped
- RTL override (U+202E) detected, flag set
- LRO (U+202D) detected, flag set
- Bidi isolates (U+2066–U+2069) detected
- Homoglyph: Cyrillic а (U+0430) → Latin a
- Homoglyph: Greek ο (U+03BF) → Latin o
- Homoglyph: all 17 characters map correctly
- Homoglyph: `confusables_normalized` flag set when substitution occurs
- Homoglyph: flag NOT set when no confusables present
- Empty string normalizes to empty string
- ASCII-only string passes through with no transformations
- Combined: zero-width + homoglyph + NFKC all apply in sequence
- `NormalizedText.original` preserves the input verbatim

### `tests/test_minimal_scanner.py` (~28 tests)

- Each of 8 injection patterns detected (8 tests)
- Role-switch-capability: trigger + grant → finding
- Role-switch-only: trigger without grant → finding (LOW severity)
- Role-switch: grant without trigger → no finding
- Oversized payload → CRITICAL finding
- Excessive JSON depth → CRITICAL finding
- Binary content → CRITICAL finding
- Base64 block detected
- Invisible chars detected (from normalization metadata)
- Homoglyph substitution detected
- RTL override detected
- Invisible-chars escalation: invisible + injection → severity HIGH
- Suppressed rule: suppressed injection pattern → no finding
- Structural rules cannot be suppressed
- Clean input → empty findings, `ScanResult.error` is None
- Scanner `.name` returns `"minimal"`
- Scanner satisfies `Scanner` protocol (`isinstance` check)
- Configurable thresholds: custom `max_payload_bytes` honored
- Configurable thresholds: custom `max_json_depth` honored
- Exception guard: scanner returns `ScanResult(error=...)` on unexpected failure, never propagates
- Homoglyph substitution: fires at LOW severity (unconditional, per D6)
- JSON depth check: deeply nested payload (>100 levels) does not crash with RecursionError

### Test command

```bash
C:\Users\zioni\AppData\Local\Programs\Python\Python311\python.exe -m pytest tests/ -v --tb=short
```

Fallback (if Python 3.11 is on PATH as `python`):
```bash
python -m pytest tests/ -v --tb=short
```

Full gate (lint + typecheck + tests):
```bash
ruff check . && ruff format --check . && mypy --strict . && python -m pytest tests/ -v --tb=short --cov=petasos --cov-report=term-missing
```

---

## Done when

- [ ] `pip install -e .` succeeds in a clean Python 3.11 venv (base install, zero ML deps)
- [ ] `mypy --strict .` passes with zero errors
- [ ] `ruff check . && ruff format --check .` passes
- [ ] `MinimalScanner` detects all 17 rule categories against a fixed test corpus
- [ ] Normalization strips zero-width chars, maps confusable homoglyphs, flags RTL overrides
- [ ] >=50 tests passing (`pytest` green)
- [ ] `Scanner` protocol can be implemented by a trivial stub (verified in `test_types.py`)
- [ ] All result types are frozen (mutation raises `FrozenInstanceError`)
- [ ] GitHub Actions CI stub runs lint + typecheck + tests

---

## Out of scope

- ML scanner backends — PET-3/4/5 handle LLM Guard, LlamaFirewall, Presidio wrappers
- Pipeline orchestration — PET-6 (depends on this item but is separate)
- Frequency tracking / escalation — PET-7 (Premium tier)
- JWT license validation — PET-10
- PyPI publish — PET-12
- Hermes integration testing — PET-11
- Custom profiles / tool call guard — PET-8
- Any network calls at runtime — Petasos is offline-first by design

---

## Deferred (P2+)

- **Test command hardcodes Windows path** (conventions/R1/F-1): The primary test command uses the Windows-specific Python path. CI will use `python -m pytest` naturally. No spec change needed — convention is to pin the local dev interpreter.
- **Single source of version** (conventions/R1/F-2): `__version__` in `__init__.py` and `version` in `pyproject.toml` are manually synced. Consider `importlib.metadata` or `hatch-vcs` in a future pass.
- **`ruff.toml` contents unspecified** (conventions/R1/F-3): The scope lists `ruff.toml` as a file to create but the design section doesn't prescribe contents. Ruff defaults are reasonable; implementer picks line length and rule selection.
- **Constructor validation for thresholds** (edge-cases/R2/F-2): `max_payload_bytes` and `max_json_depth` accept zero/negative values without error. Implementer should raise `ValueError` on non-positive values.
- **JSON depth check bracket-in-string false positives** (edge-cases/R2/F-3): Iterative character scanning may count brackets inside JSON string values. Implementer should either use `json.loads()` + iterative depth walk (with `RecursionError` catch) or document the over-approximation.
- **Structural short-circuit behavior** (edge-cases/R2/F-4): The spec says structural checks "fail fast" but doesn't specify whether `oversized-payload` skips all subsequent checks. Implementer decides — Drawbridge short-circuits on oversized-payload only.
- **Severity enum serialization** (edge-cases/R2/F-6): `to_dict()` should serialize `Severity` as `.value` (lowercase string); `from_dict()` reconstructs via `Severity(data["severity"])`.
- **D6 and D7 are spec-level additions** (conventions/R2/F-1,F-2): Not in brief's D1-D5 — added by spec-cycle to address review findings. Flagged for human drift-check.
