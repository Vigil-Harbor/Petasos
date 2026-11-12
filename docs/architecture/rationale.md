# Implementation rationale

Constraints that explain the current implementation.

## Agent directive boundaries

A directive requires an agent-address marker, a fetch/install/execute action,
and an external resource on the same physical line. README installation prose
does not by itself address an agent. Strong markers accept any external resource;
weak `Assistant:` and `Agent:` transcript tags require an archive or executable.
The resource vocabulary includes Windows scripts and droppers as well as Unix
executables and common archives. A document URL alone is insufficient for weak tags.

Physical lines split only at `\n`. `str.splitlines()` also splits at carriage
returns, vertical tabs, form feeds, record separators, NEL and Unicode line/paragraph
separators. Those characters survive normalization; treating them as boundaries
would let an attacker split the marker from its resource and evade the conjunction.
Offsets include the consumed newline. Canonical and separator views are searched;
composed leet views belong to the injection battery. Extra views omit positions.
The rule is unsuppressible, direction independent and HIGH, never CRITICAL.

## Syntactic anchor soundness

Each cheap anchor is a necessary condition and must remain a substring superset
of every pattern in its family. False anchor positives cost a pattern pass;
missing anchor alternatives silently remove detections. Injection alternatives
cover `inst`, `sys`, `disregard` and `now`, including template delimiters and the
bare `disregard your` branch. Agent-directive noun alternatives cover every marker;
word-bounded `AI` avoids matching `email` or `again` while accepting either determiner.
Command anchors use case-insensitive membership, but shell patterns remain case
sensitive. Per-view pruning keeps digit-dense and ordinary no-match scans within
the syntactic latency budget of less than 5 ms.

## Decoded finding budgets

Plain injection, role-switch and agent-directive checks precede decoded rescans.
The decoded path seeds its seen-rule set from plain findings and shares it across
candidates. Each rule contributes at most one finding per scan across both paths.
Repeated carriers must not multiply the 10-point injection weight into a session
termination from a single payload. Distinct rule ids can each contribute once.

A decoded injection sets the co-occurrence flag before duplicate suppression:
the attack is present even if its finding is already represented. Role-switch
and directive rescans have their own anchors; the injection anchor is not a
superset of their triggers. Injection and directive suppression is removed at
scanner construction, so rescans do not reapply suppressions.

Base64 span discovery also covers the hex alphabet at the same 16-character
floor. Each physical span consumes one attempt slot while both codecs are tried;
malformed floods therefore remain bounded. Decode-and-match validates short blobs
without emitting the LOW encoding flag. ROT13 has no structural signature, so it
uses one unconditional length-preserving view bounded by the decoded-byte cap.
The decode toggle preserves scanner identity and all unrelated tunables.

## Decoded coordinate spaces

Blob findings retain the original carrier span, so normalized decoded text can
be searched without projecting decoded offsets into the carrier. Canonical and
separator views are sufficient for named families. A blob with invisible characters
or homoglyphs must receive the same normalization as plain text.

ROT13 primary-view offsets index the normalized origin text one for one. Further
NFKC normalization would invalidate those offsets. Non-length-preserving separator
or composed extras omit position and matched text; blob extras still retain their
fixed carrier span. Role-switch triggers and capability grants must occur in the
same view. A suppressed capability match must not fall through to a LOW finding.

## Command detection boundaries

Command findings apply to outbound tool parameters: inbound installation prose
commonly contains `curl | sh`. Command rules are suppressible because code generation
legitimately emits commands; the code-generation role suppresses pipe-to-shell only.
All five rules are HIGH, never CRITICAL, and each emits once per scan. At weight
3.0 each, the family contributes at most 15 points rather than multiplying repeated
matches into a termination. Canonical and separator views unwind homoglyphs and
invisible characters; composed views remain specific to injection.

Overlap resolution prefers severity then confidence: destructive-recursive 0.95,
alias/decode/fetch 0.9, and pipe-to-shell 0.7. The pipe-to-shell confidence must meet
the highest built-in confidence floor. Alias, decode and fetch have disjoint leading
anchors. Word and trailing-pipe boundaries exclude table cells and regex alternations.
Quote-terminal shell words remain detectable because serialized tool parameters end
with quotes; quoted regex strings can therefore be false positives. Decode/fetch
allow closing parentheses so command substitutions remain detectable. Backslash
alias escapes defeat shell aliases and literal-string approvals, irrespective of
argument destructiveness; argument boundaries exclude LaTeX and Windows path prose.

Absolute and home-relative destructive targets are dangerous without attempting to
infer whether each absolute path is safe. Relative build paths and benign device
sinks remain outside the pattern. Truncation can remove a negative-lookahead pipe
and cause a false positive or remove an execution suffix and cause a miss; the
parameter truncation diagnostic exposes incomplete examination. Shell continuation
whitespace crosses newlines after a pipe. Strong-rule bodies stop at a newline to
bound table false positives, leaving multiline multistage pipelines outside detection.

## Injection pattern precision

Ignore-previous requires an adjective and allows a determiner stack so phrases
such as "ignore all of your previous instructions" do not fall between patterns.
Ignore-all requires all/any without the adjective slot. Disregard/forget form a
separate verb partition. Bare "ignore the instructions", bare "disregard the
instructions" and paraphrase nouns such as "guidance" remain outside these patterns
because they occur in benign technical prose.

New-instructions accepts "your new instructions are" and the colon form. "The new
instructions are in the README" is benign, so the determiner is not generalized.
System override requires the prompt context; bare "override the system" is ordinary
systems prose. System-prefix permits spaces/tabs before the colon, not leading
whitespace: `^\s*` with MULTILINE backtracks quadratically on newline floods
(measured at 19 seconds for 80 KB) and matches indented YAML keys. Indented SYSTEM,
lone-carriage-return lines, and other speaker tags are outside that rule.
Contractions and symmetric instruction/system delimiters are recognized explicitly.

## Invalid scan directions

Unrecognised directions skip the outbound command family. A debug diagnostic makes
that missing coverage visible without raising from a scanner boundary. Scanner
callers receive error-bearing results rather than argument-validation exceptions.

## Presidio entity vocabulary

Entity validation uses the curated severity vocabulary without importing Presidio,
so the base install has no optional dependency. Real but uncurated recognizers
are rejected rather than falling through to LOW severity. Per-call additions
are unioned with the scanner base without mutating it, preserving concurrent scans.

## Scanner availability failures

Build before probing so a failed probe retains the scanner instance for status and
cleanup. A probe ImportError is a probe failure; absence is an explicit absent
result or an ImportError from the builder. Per-call entity extras keep role changes live.

## JSON projection depth

A projection-depth limit stops retaining stack frames but still examines remaining
string tokens, including escaped identifiers. Malformed strings and quote alignment
must not hide later escaped code. The result records missing coverage rather than
certifying the remaining document as valid JSON.

## Alert scan counting

Rate-based alert rules count scans with findings or an unsafe result. Counting all
ingestion scans would keep a normal agent loop permanently over threshold. Empty
findings can mean clean content or detector failure, so only clean and safe scans
are skipped. The safe flag carries degraded/closed scanner failure; PipelineResult
errors are frozen before the alert hook and scanner errors live in ScanResult.error.

## Audit finding privacy

Finding rows are included when explicitly requested or at standard/verbose verbosity;
a minimal capture window can therefore still record findings. Raw content and
matched text are excluded. Direction is the resolved scan direction, uniform
across finding rows, rather than a claim of individual finding provenance.

## Quantized scan contributions

Uncapped command scoring permits at most five rules at weight 3.0: 15 points,
below session termination and equal to the default warning threshold. Capped
ingestion and parameter scans instead contribute exactly one configured step when
raw weight reaches it, or zero below it. A 3.0 command finding contributes zero
under the shipped 3.75 cap. This bounds both poisoning and benign reread trajectories.

A zero-contribution capped scan must not append a rolling-window entry: that
independent count-based promotion path could otherwise promote a session at score
zero. A cap of zero means no contribution of any kind; a tiny positive cap can
still count. Uncapped callers retain raw scoring and count findings scans.

Reconfiguration parses weights before changing any live state, then commits scalar
bounds, weights and tombstone trimming under the tracker lock. Session secrets
remain immutable so tokens minted before reconfiguration remain valid.

## Lineage lock order

The host supplies child-to-parent edges; child tool content cannot choose a parent.
Tracker callbacks run inside the tracker lock, touch only registry state, are O(1)
and nonblocking, and never call the tracker. The only nested lock order is tracker
then registry. Both stores use the monotonic clock for expiry. Registry reconfiguration
preserves edges and updates cached bounds under the same lock as readers.

Pinned sessions retain tiers needed by live children. TTL passes inspect a snapshot
of the expiry deque so requeued pinned entries are not revisited in the same call.
Every removed session drops its outgoing edge, even without a tombstone. When all
candidates are pinned, the hard twice-max-sessions ceiling bounds memory by sacrificing
the least-recently-updated session; descendants then use their own tier. Terminated
ancestor tombstones survive, preserving tier-three inheritance. Existing tombstones
keep their FIFO position during eviction rather than being refreshed as new entries.

## Source taint bounds

Source-taint matching blocks relay of source-namespace content even when it is not
personal information, such as balances, amounts and merchants. A session-keyed
store prevents cross-session matching. Per-session oldest-span eviction and global
least-recently-active-session eviction bound retained content by sessions times spans
per session times maximum span length, without relying on a session-end hook.

Capture and argument checks use JSON-wire scalar forms, not Python repr, and bound
text, leaves and recursion depth. Content beyond those bounds is unexamined.
Malformed, truncated or too-deep JSON becomes one capped leaf rather than raising.
Oversized leaves are dropped. The minimum normalized span length is read and
updated under one lock; reconfiguration affects future captures only, preserving
stored spans and never retroactively admitting rejected spans.

## Finding suppression floors

Structural findings always retain their floor, independently of scan direction or
injection scope. Prefix recognition supplements the structural-rule vocabulary.
Injection findings retain their floor inbound; only the exact pair of inbound-only
scope and outbound direction permits relaxation. Unvalidated values therefore
fail safe. A profile cannot turn off inbound injection detection.

## Scanner health provenance

Scanner health distinguishes load errors, runtime degradation and absent prerequisites.
Availability probes are duck typed: two-element results omit cause; malformed or
throwing probes leave the initial healthy state intact. The value stays Any so
arity checks remain live rather than becoming statically impossible tuple accesses.
A load_failed cause uses the probe reason, even if empty, rather than a stale scan error.

Timeouts have a separate error prefix because only consecutive timeouts open the
breaker. Other outcomes reset the streak. asyncio.TimeoutError also supports hosts
where it differs from the builtin; cancellation is a BaseException and propagates.
The default timeout bounds callers that omit an explicit scan timeout.

## Shared tracker token binding

An injected tracker and its pipeline must share the session secret. Otherwise the
pipeline chooses bare ids or tokens under one binding while the tracker enforces
another, causing every update to fail and potentially leaving a safe-looking result.

## Spawn budget atomicity

Prune, count, compare and append occur under one lock so two concurrent children
cannot both consume the last available slot. Expired session deques are removed
by an amortized global sweep at most once per window, including sessions never
consumed again; memory follows active windows rather than all historical ids.
Changing the window retains timestamps and the sweep clock; a shorter window
expires retained events on the next consume under the same reader lock.

## Parameter scan degradation

Parameter scan degradation means an unsafe result co-occurs with a scanner error.
The host can therefore block degraded detection even when findings are personal
information rather than injection. Fail-open scanner errors that leave safe true
do not set this flag. Guard-internal scan and hook failures explicitly set it
regardless of scanner fail mode. Tool parameters are outbound agent content, so
the command family applies to both normal and fallback parameter scans.

## Scan contribution calibration

The contribution divisor is four. A divisor of three blocks dispatch after six
consecutive flagged ingestion reads, below the intended eight-read floor. A divisor
of five makes the shipped step 3.0, losing sub-step immunity for a single command
finding. The step is the config tier-one threshold divided by four; role thresholds
are not consulted. The measured upper raw-weight band for a maximally poisoned
8,000-character ingestion window is 80. A step above that band makes every such
scan quantize to zero and disables the session backstop, so it has a diagnostic.

Nonpositive tier one returns zero before any ratio division. Otherwise a zero
division could escape into parameter scanning and mark every call unsafe. The
tier-two/tier-one ratio is checked before step bands because dispatch blocking is
the urgent threshold. Reconfiguration rearms the once-only diagnostics. Self-change
weights remain unclamped: a single config-write attempt is bounded at 10 points
and intentionally contributes a full risk step immediately.

## Tool alias canonicalization

The alias-free canonicalizer is shared by host classification and guard evaluation.
Alias keys are canonicalized into the same namespace as incoming names, including
CamelCase and tool suffixes; otherwise those aliases never match. Canonically
colliding configured keys use last-writer-wins. Configured aliases must not point
to exempt tools; built-in aliases may point to operator-exempted targets. Delegate
names are canonicalized too and cannot be exempt, because exemption skips the
tier ladder and would defeat fan-out enforcement.

## Inherited guard tiers

Child tiers combine their own tier with live ancestor tiers. Optional tier-one/two
inheritance can be disabled, but ancestor termination tombstones always force
tier three, including after state eviction. An absent registry uses own-tier only.
Any failure during token minting, state lookup or tier combination returns tier
three so it cannot reach a host adapter failure path that would allow the call.

## Guard overflow attribution

Depth overflow means argument traversal is incomplete, not that a specific owned
path matched. The sentinel target identifies that condition without misattributing
a path in triage. The guard and adapter share the public constant.

## Hermes tool classification

Unknown tools default to acting and ingesting, failing toward enforcement and
scrutiny. Argument blocking, result scanning and source-taint egress answer separate
questions. Result scanning excludes known non-ingesting tools; the named ingesting
subset contains only table rows that reach the hook. Non-string results remain
outside that result-text seam: native vision returns multimodal dictionaries.

Single-underscore `mcp_*` table entries do not match Hermes's double-underscore
server/tool registration after canonicalization. They retain published read-only
membership but cannot enter the hook-reaching ingestion subset. Evidence rows can
remain even when all their axes equal defaults. Upstream source citations in the
table and docs/architecture/hermes-host-facts.md record the host constraints.

## Enforcement spool integrity

Writers append events without fsync or full-file rewrites: telemetry failure must
not delay or break tool enforcement. Readers drain forward from a byte offset,
independent of producer restarts. A trailing partial line waits for completion;
malformed complete lines advance the offset. Read errors keep the last good cursor.
Only the dashboard rotates; an existing rotated sibling must never be overwritten.

Event identity uses a full UUID with an e- prefix, distinct from playground ids.
High-volume blocked sessions generate thousands of events, so short prefixes risk
collisions in dashboard deduplication. The cap exceeds the observed burst of about
40 blocks in 2 hours 18 minutes at about 300 bytes per row and a peak tail interval.

Signing uses an HMAC-SHA256 domain-separated session-secret subkey with the
petasos/enforcement-spool/v1 label, preventing cross-use with session tokens.
Path-keyed keys take precedence over the fallback key. Resetting path/cap state
does not reset signing. No key writes unsigned records; verification returns false
for absent keys or invalid records, while callers distinguish unattested deployments
from verification failure. A string signature, including empty string, is a mismatch
after failed verification; non-string or missing signatures are missing.
Instance spools retain their own path, key and cap independently of module writers.

## Model-facing result notices

Content blocks can occur after the guard allows or outside a GuardResult, so their
message formatter accepts the decision path directly and supplies a valid fallback
reason for unknown paths. Source/sink provenance belongs only in operator records.

Ingestion notices annotate content returned whole and must not claim a tool was
blocked. Their banner has no trailing newline. Finding details use rule id and
severity only: scanner messages can contain attacker-controlled decoded content,
and embedding those messages in a trusted banner would reinject the payload.
The operator receives the raw finding message through its event record. A top-finding
line appears only with a finding and never for the examination ceiling; the additional
count excludes the top finding. Coverage appears only when supplied. Scanned/total
counts appear only for findings and ceiling paths with omitted input, never when
scanning was unavailable.
