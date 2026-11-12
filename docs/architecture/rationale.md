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
