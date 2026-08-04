"""PET-169: the config-surface honesty audit, in executable form.

`_CLASSIFICATION` below is the **tracked authority** for the 2026-08-03 sweep of
every `PetasosConfig` field. The `docs/research/` audit doc is a dated snapshot
of the same sweep and is gitignored (spec Decision 8); when the two disagree,
this file wins.

Verdicts are read-site facts. Each maps onto one of PET-151's three dispositions:

    live-library   Reaches an outcome-affecting consumer on a base install.
                   No disposition owed; record the evidence.
    live-partial   Has a decision-point read, but on a pipeline registering only
                   MinimalScanner (the `pip install petasos` shape) flipping it
                   changes none of `safe`, `findings` (as {(rule_id, severity)}),
                   `sanitized_content`, `errors`, or `escalation_tier`, for all
                   inputs.  -> Caveat (D-C): name the true consumer in help_plain.
    live-shim      Read only by the deployment shim or the console bootstrap;
                   inert for a library embedder.  -> Caveat (D-C).
    not-a-control  A read exists but reaches no outcome-affecting consumer;
                   retained deliberately for parity.  -> Retire (D-A).
    dead           No read site anywhere; inert by accident, not by design.
                   The 2026-08-03 sweep found none.

The `live-partial` boundary applies only to keys whose claimed consumer is the
scan pipeline. A key with a decision-point or constructor read inside a
config-accepting session component a base-install embedder can drive directly
(ToolCallGuard, LineageRegistry, SessionTaintStore, AuditEmitter/AlertManager) is
`live-library` **through that component**, because its outcome is a GuardResult,
lineage/taint state, or an on_audit/on_alert emission rather than one of the five
compared PipelineResult fields. For a key whose only decision-point read is the
pipeline-side gate that invokes the component, the gate read is the anchor.

Evidence is a `path:line` anchor resolved at collection time, or the
`none:<declaration site>` sentinel, which is used iff the verdict is `dead`.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from petasos.config import _SECRET_FIELDS, PetasosConfig
from petasos.console._config_meta import _FIELD_META, generate_config_metadata

_REPO_ROOT = Path(__file__).resolve().parents[1]

_VERDICTS = frozenset({"live-library", "live-partial", "live-shim", "not-a-control", "dead"})
_CAVEAT_VERDICTS = frozenset({"live-partial", "live-shim"})

# Marker phrases test 4 requires in `help_plain`, one per caveat axis. Carried in
# the tuple rather than a second dict so a caveat key cannot silently drop out of
# the disclosure loop (spec Decision 1).
_M_NORM = "does not gate built-in findings"
_M_ANON = "needs the presidio extra and a registered PII-detecting scanner"
_M_MLSCAN = "has no effect until you add an ML scanner"
_M_CONSOLE = "applies only to the scanner the console builds at startup"
_M_PLUGIN = "enforced by the Hermes plugin, not by the Petasos library alone"
_M_INITWAIT = "no effect when Petasos is embedded directly as a library"

# (verdict, evidence, required_help_marker)
_CLASSIFICATION: dict[str, tuple[str, str, str | None]] = {
    # --- Normalization -----------------------------------------------------
    # PET-151, transcribed not re-derived (spec Decision 6). Pins already
    # shipped: tests/adversarial/normalization/test_unicode_bypass.py:323.
    "normalize_nfkc": ("live-partial", "petasos/pipeline.py:686", _M_NORM),
    "strip_zero_width": ("live-partial", "petasos/pipeline.py:687", _M_NORM),
    "map_homoglyphs": ("live-partial", "petasos/pipeline.py:688", _M_NORM),
    # PET-151 D-A, transcribed. Pin: test_unicode_bypass.py:347.
    "detect_rtl_override": ("not-a-control", "petasos/pipeline.py:689", None),
    # PET-143 D-A, transcribed. Pin: test_unicode_bypass.py:250.
    "fold_leet": ("not-a-control", "petasos/pipeline.py:690", None),
    # Threaded into MinimalScanner's constructor when Pipeline builds its own
    # instance. A caller-supplied MinimalScanner is adopted WITHOUT the flag
    # (pipeline.py:321-328); the value first reaches it at the next reconfigure
    # (pipeline.py:399). That is a deployment-axis defect, recorded in the audit
    # table and routed to a follow-up ticket; the library verdict is unaffected.
    "decode_encoded_payloads": ("live-library", "petasos/pipeline.py:332", None),
    # --- Scanning ----------------------------------------------------------
    "direction": ("live-library", "petasos/pipeline.py:637", None),
    # The base-install diff is _compute_safe's syntactic-error arm at :215, which
    # sits BEFORE the `if ml_total == 0` short-circuit at :218. pipeline.py:714 is
    # a supplementary read site only: early_exit needs a CRITICAL finding, which
    # already forces safe=False under every mode.
    "fail_mode": ("live-library", "petasos/pipeline.py:215", None),
    # Read only inside _scan_with_breaker, constructed only under
    # `elif self._ml_scanners:` (pipeline.py:722).
    "scanner_timeout_seconds": ("live-partial", "petasos/pipeline.py:952", _M_MLSCAN),
    "scanner_circuit_breaker_threshold": ("live-partial", "petasos/pipeline.py:925", _M_MLSCAN),
    "scanner_circuit_breaker_cooldown_seconds": (
        "live-partial",
        "petasos/pipeline.py:966",
        _M_MLSCAN,
    ),
    # PET-167, grandfathered: the shim is its only consumer.
    "init_wait_timeout_seconds": (
        "live-shim",
        "docs/deployment/reference_plugin/__init__.py:766",
        _M_INITWAIT,
    ),
    # --- Anonymization -----------------------------------------------------
    # Inert on a base install for a reason that is NOT the Presidio ImportError
    # arm: the import at pipeline.py:852 sits inside `if pii_findings:` (:850),
    # and pii_findings filters `merged` on finding_type == "pii", which only
    # PresidioScanner emits. MinimalScanner emits injection/command/encoding/
    # structural, so the whole block is unreachable and the handler never fires.
    "anonymize": ("live-partial", "petasos/pipeline.py:836", _M_ANON),
    "pii_entities": ("live-partial", "petasos/pipeline.py:843", _M_ANON),
    "redaction_mode": ("live-partial", "petasos/pipeline.py:857", _M_ANON),
    # Exempt from a test-8 load-bearing arm: hash_key is consumed only under
    # mode == "hash", an engine-path mode, and config.py:233 rejects
    # anonymize=True + redaction_mode="hash" + hash_key=None at construction, so
    # no extras-free configuration exists in which flipping it changes anything.
    # Its caveat rests on the redaction_mode arm plus this read trace.
    "hash_key": ("live-partial", "petasos/pipeline.py:858", _M_ANON),
    # Read ONLY by build_dashboard_pipeline, reachable only from
    # console/__main__.py and console/hermes/plugin_api.py. Pipeline never
    # constructs a PresidioScanner; it fans out over whatever the caller supplied
    # (pipeline.py:722-742). So `pip install petasos[presidio]` plus
    # Pipeline(scanners=[PresidioScanner()]) still gets nothing from these three:
    # the extra is installed and they are still inert. An "extras dependency"
    # caveat would be false prose shipped inside an honesty audit.
    "presidio_entities": ("live-shim", "petasos/console/_standalone.py:109", _M_CONSOLE),
    "presidio_entities_extra": ("live-shim", "petasos/console/_standalone.py:109", _M_CONSOLE),
    "presidio_score_threshold": ("live-shim", "petasos/console/_standalone.py:111", _M_CONSOLE),
    # --- Feature gates (via Pipeline._FEATURE_GATES, pipeline.py:568-574) ----
    "frequency_enabled": ("live-library", "petasos/pipeline.py:978", None),
    "escalation_enabled": ("live-library", "petasos/pipeline.py:998", None),
    "profile_name": ("live-library", "petasos/pipeline.py:587", None),
    # The ticket's original premise said this was dead config. Refuted
    # 2026-08-03: the enforcement site asks is_feature_enabled("tool_guard") by
    # FEATURE name, which _FEATURE_GATES maps to the attribute, and
    # _FEATURE_DISABLED is allowed=True, so turning it off allows every tool call
    # unscanned. tests/test_guard.py::TestFeatureGate already pins the difference.
    "tool_guard_enabled": ("live-library", "petasos/session/guard.py:440", None),
    "audit_enabled": ("live-library", "petasos/pipeline.py:1011", None),
    "alert_enabled": ("live-library", "petasos/pipeline.py:1023", None),
    # --- Alerting (all read inside AlertManager, a base-install consumer) ----
    "alert_cooldown_seconds": ("live-library", "petasos/session/alerting.py:149", None),
    "alert_per_minute_cap": ("live-library", "petasos/session/alerting.py:173", None),
    "alert_per_hour_cap": ("live-library", "petasos/session/alerting.py:179", None),
    "alert_critical_per_minute_cap": ("live-library", "petasos/session/alerting.py:141", None),
    "alert_high_severity_threshold": ("live-library", "petasos/session/alerting.py:312", None),
    "alert_rapid_fire_count": ("live-library", "petasos/session/alerting.py:356", None),
    "alert_rapid_fire_window_seconds": ("live-library", "petasos/session/alerting.py:353", None),
    "alert_cross_session_burst_count": ("live-library", "petasos/session/alerting.py:410", None),
    "alert_cross_session_burst_window_seconds": (
        "live-library",
        "petasos/session/alerting.py:394",
        None,
    ),
    "alert_pii_volume_threshold": ("live-library", "petasos/session/alerting.py:442", None),
    "alert_pii_volume_window_seconds": ("live-library", "petasos/session/alerting.py:439", None),
    "alert_ring_buffer_capacity": ("live-library", "petasos/session/alerting.py:349", None),
    "alert_per_session_contribution_cap": (
        "live-library",
        "petasos/session/alerting.py:167",
        None,
    ),
    "alert_max_session_contribution_entries": (
        "live-library",
        "petasos/session/alerting.py:158",
        None,
    ),
    # --- Audit (read inside AuditEmitter) -----------------------------------
    "audit_verbosity": ("live-library", "petasos/session/audit.py:110", None),
    "audit_emit_findings": ("live-library", "petasos/session/audit.py:111", None),
    # --- Frequency / escalation --------------------------------------------
    "frequency_half_life_seconds": ("live-library", "petasos/session/frequency.py:80", None),
    "frequency_weights": ("live-library", "petasos/session/frequency.py:104", None),
    "rolling_window_seconds": ("live-library", "petasos/session/frequency.py:81", None),
    "rolling_threshold": ("live-library", "petasos/session/frequency.py:82", None),
    "tier1_threshold": ("live-library", "petasos/session/escalation.py:80", None),
    "tier2_threshold": ("live-library", "petasos/session/escalation.py:80", None),
    "tier3_threshold": ("live-library", "petasos/session/escalation.py:73", None),
    # --- Session management -------------------------------------------------
    "max_sessions": ("live-library", "petasos/session/frequency.py:83", None),
    "session_ttl_seconds": ("live-library", "petasos/session/frequency.py:84", None),
    "max_new_sessions_per_minute": ("live-library", "petasos/session/frequency.py:85", None),
    "max_terminated_tombstones": ("live-library", "petasos/session/frequency.py:131", None),
    # Excluded from the console for SECRECY, which is an axis orthogonal to the
    # taxonomy (spec Decision 7): live-library AND excluded. Its consumers are the
    # guard's session binding and the console spool HMAC, neither of which is one
    # of the five compared PipelineResult fields, so the boundary-scope rule
    # applies and the component read is the anchor.
    "session_secret": ("live-library", "petasos/session/guard.py:669", None),
    # --- Tool guard / lineage / taint (read inside guard + registries) -------
    "subagent_lineage_enabled": ("live-library", "petasos/session/guard.py:698", None),
    "delegate_fanout_enabled": ("live-library", "petasos/session/guard.py:517", None),
    "lineage_max_depth": ("live-library", "petasos/session/lineage.py:37", None),
    "lineage_max_edges": ("live-library", "petasos/session/lineage.py:38", None),
    "lineage_edge_ttl_seconds": ("live-library", "petasos/session/lineage.py:39", None),
    "delegate_max_fanout_per_window": ("live-library", "petasos/session/guard.py:651", None),
    "delegate_fanout_window_seconds": ("live-library", "petasos/session/guard.py:234", None),
    "delegate_tool_names": ("live-library", "petasos/session/guard.py:218", None),
    # Only behavior reads are the shim's: the canonicalized sink set is built from
    # config at reference_plugin/__init__.py:685 and rebuilt on rebind at :1245.
    # Inside petasos/ the name appears only in config.py validation/coercion, its
    # _FIELD_META entry, a scope comment, and a taint.py docstring mention.
    "egress_sink_tools": (
        "live-shim",
        "docs/deployment/reference_plugin/__init__.py:685",
        _M_PLUGIN,
    ),
    "source_taint_namespaces": (
        "live-shim",
        "docs/deployment/reference_plugin/__init__.py:704",
        _M_PLUGIN,
    ),
    # The third knob of the same fence, and the named exemption: unlike its two
    # siblings it has a real library read, so under the boundary-scope rule it is
    # live-library through SessionTaintStore and test 2's marker-iff constraint
    # forbids pinning a caveat marker on it. Its help_plain is still extended to
    # name the plugin (a deliberately unpinned thirteenth prose edit), and the
    # audit table records that SessionTaintStore is today instantiated only by the
    # shim, so the key bites for a library embedder only if they drive the store.
    "taint_min_span_length": ("live-library", "petasos/session/taint.py:120", None),
}

_FIELD_NAMES = {f.name for f in dataclasses.fields(PetasosConfig)}


def _keys_with_verdict(verdict: str) -> frozenset[str]:
    return frozenset(k for k, (v, _, _) in _CLASSIFICATION.items() if v == verdict)


# ---------------------------------------------------------------------------
# 1. The tripwire against a future unclassified field.
# ---------------------------------------------------------------------------


def test_every_field_classified() -> None:
    """Every PetasosConfig field carries a verdict, including the three in
    _EXCLUDED_FIELDS.

    Ships because the 2026-08-03 sweep met the criterion pre-registered in spec
    Decision 1 and on the PET-169 Plane item before the sweep ran. BOTH clauses
    fired: clause 1 (five keys newly live-shim beyond the three disposed of by
    prior tickets) and clause 2 (twelve keys needing new help_plain caveat prose).

    generate_config_metadata() iterates dataclasses.fields(PetasosConfig) and
    emits a console entry for everything outside _EXCLUDED_FIELDS, so adding a
    field publishes an operator control automatically. Metadata coverage is
    already guarded; what nothing else requires is that a classified, described,
    well-sectioned field have a read site that affects an outcome.
    """
    assert set(_CLASSIFICATION) == _FIELD_NAMES


# ---------------------------------------------------------------------------
# 2. Verdicts and evidence are well formed, and every anchor resolves.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field_name", sorted(_CLASSIFICATION))
def test_verdicts_and_evidence_wellformed(field_name: str) -> None:
    verdict, evidence, marker = _CLASSIFICATION[field_name]
    assert verdict in _VERDICTS, f"{field_name}: unknown verdict {verdict!r}"

    # The `none:` sentinel is used iff the verdict is `dead`, so verdict and
    # evidence check each other. A dead key has no read site by definition; an
    # unconditional path:line requirement would force the auditor to fabricate
    # one, cite the declaration line (which spec Decision 4 disqualifies as a
    # read), or downgrade the verdict.
    is_sentinel = evidence.startswith("none:")
    assert is_sentinel == (verdict == "dead"), (
        f"{field_name}: the none: sentinel must be used iff verdict is 'dead' "
        f"(verdict={verdict!r}, evidence={evidence!r})"
    )

    # Resolve the anchor. Strip the sentinel prefix FIRST: "none:petasos/config.py:93"
    # splits to the path "none:petasos/config.py", which does not exist, so an
    # unstripped parser either reds spuriously or gets exempted from resolution
    # entirely, leaving the one anchor nobody checks on the verdict this ticket
    # exists to catch. A dead key's declaration site must still exist.
    raw = evidence[len("none:") :] if is_sentinel else evidence
    path_str, _, line_str = raw.rpartition(":")
    assert path_str and line_str.isdigit(), (
        f"{field_name}: evidence must be path:line, got {raw!r}"
    )
    target = _REPO_ROOT / path_str
    assert target.is_file(), f"{field_name}: evidence path does not exist: {path_str}"
    # encoding is explicit: the pinned local C:\python310 interpreter defaults to
    # cp1252 and petasos/normalize.py alone carries 89 non-ASCII characters, so an
    # unqualified read_text() raises UnicodeDecodeError locally while passing on CI.
    line_count = len(target.read_text(encoding="utf-8").splitlines())
    line_no = int(line_str)
    assert 1 <= line_no <= line_count, (
        f"{field_name}: evidence line {line_no} is outside {path_str} (1..{line_count})"
    )

    # A marker is required iff the verdict owes a caveat. An empty-string marker
    # would make `"" in help_plain` true for every entry, turning test 4 into an
    # assertion-shaped no-op; a None marker on a caveat key would raise TypeError
    # rather than fail readably.
    if verdict in _CAVEAT_VERDICTS:
        assert marker is not None and marker.strip(), (
            f"{field_name}: verdict {verdict!r} requires a non-empty help marker"
        )
    else:
        assert marker is None, (
            f"{field_name}: verdict {verdict!r} must not carry a help marker, got {marker!r}"
        )


# ---------------------------------------------------------------------------
# 3. Per-verdict membership is pinned.
# ---------------------------------------------------------------------------


def test_verdict_sets_pinned() -> None:
    """The `test_config_meta.py:48` idiom applied per verdict.

    Without this, emptying `live-partial` is a one-line edit no test can see,
    after which test 4 iterates zero keys and no caveat ships; and a future author
    can silence a red test 4, 5 or 8 by editing a verdict instead of the surface.
    """
    assert _keys_with_verdict("live-partial") == frozenset(
        {
            # PET-151, prose already shipped.
            "normalize_nfkc",
            "strip_zero_width",
            "map_homoglyphs",
            # The anonymization group.
            "anonymize",
            "pii_entities",
            "redaction_mode",
            "hash_key",
            # The scanner-timeout family: three keys, but only two carry the
            # `circuit_breaker` prefix, so seeding this group by glob silently
            # drops scanner_timeout_seconds.
            "scanner_timeout_seconds",
            "scanner_circuit_breaker_threshold",
            "scanner_circuit_breaker_cooldown_seconds",
        }
    )
    assert _keys_with_verdict("live-shim") == frozenset(
        {
            "init_wait_timeout_seconds",
            "presidio_entities",
            "presidio_entities_extra",
            "presidio_score_threshold",
            "egress_sink_tools",
            "source_taint_namespaces",
        }
    )
    assert _keys_with_verdict("not-a-control") == frozenset({"fold_leet", "detect_rtl_override"})
    # The 2026-08-03 sweep found no key with no read site anywhere. Recorded as a
    # pin rather than an omission: a future `dead` verdict is a finding, and it
    # has to red this line to get added.
    assert _keys_with_verdict("dead") == frozenset()


# ---------------------------------------------------------------------------
# 4-7. The surface must match the verdicts.
# ---------------------------------------------------------------------------


def test_caveat_keys_disclose_consumer() -> None:
    """Every live-partial and live-shim key names its true consumer at the point
    of display. Presence is asserted first so a de-surfaced caveat key reds
    instead of silently iterating zero times."""
    by_name = {e["name"]: e for e in generate_config_metadata()}
    for field_name in sorted(_keys_with_verdict("live-partial") | _keys_with_verdict("live-shim")):
        _, _, marker = _CLASSIFICATION[field_name]
        assert field_name in by_name, f"{field_name}: caveat key is not surfaced in the console"
        assert marker is not None  # guaranteed by test 2; narrows the type here
        help_plain = by_name[field_name]["help_plain"]
        assert marker in help_plain, (
            f"{field_name}: help_plain does not carry the required disclosure marker {marker!r}"
        )


def test_retired_keys_are_de_surfaced() -> None:
    """Every not-a-control and dead key is gone from BOTH the generated metadata
    and _FIELD_META. The second half closes the orphan-entry class and keeps the
    PET-128 doc-count guard honest."""
    surfaced = {e["name"] for e in generate_config_metadata()}
    for field_name in sorted(_keys_with_verdict("not-a-control") | _keys_with_verdict("dead")):
        assert field_name not in surfaced, f"{field_name}: retired key is still rendered"
        assert field_name not in _FIELD_META, f"{field_name}: retired key still has _FIELD_META"


def test_field_meta_has_no_orphans() -> None:
    """Catches a rename that leaves stale operator prose behind."""
    assert set(_FIELD_META) <= _FIELD_NAMES


def test_secret_defaults_never_published() -> None:
    """`entry["default"] = _serialize_default(...)` runs unconditionally at
    _config_meta.py:887 and `entry["redacted"] = True` is additive and scrubs
    nothing, so a future secret field with a non-None default would publish that
    default on every metadata fetch. hash_key's default is None today, so the hole
    is latent, which is precisely the state a tripwire exists to guard. Asserting
    excluded-or-redacted alone would be true by construction and unfalsifiable."""
    by_name = {e["name"]: e for e in generate_config_metadata()}
    for field_name in sorted(_SECRET_FIELDS):
        entry = by_name.get(field_name)
        if entry is None:
            continue  # excluded outright, e.g. session_secret
        assert entry["default"] is None, (
            f"{field_name}: a secret field must not publish a default value"
        )
        assert entry.get("redacted") is True, f"{field_name}: secret field is not marked redacted"
