/* Owns: severity, health, integrity, findings, details, history, reducers, and views. Depends on: core primitives/state; transport auth; Pet dashboard callbacks. */
(function () {
  "use strict";
  var Pet = window.__PETASOS_CONSOLE__;
  var actual = Pet && Pet._moduleState ? Pet._moduleState.last : "missing";
  if (actual !== "transport") throw new Error("petasos-observability expected module transport, got " + actual);

  var SEV = {
    critical: { cls: "sev-crit", col: "var(--crit)", short: "CRIT" },
    high: { cls: "sev-high", col: "var(--high)", short: "HIGH" },
    medium: { cls: "sev-med", col: "var(--med)", short: "MED" },
    low: { cls: "sev-low", col: "var(--low)", short: "LOW" },
    info: { cls: "sev-info", col: "var(--info)", short: "INFO" },
  };

  Pet.SevBadge = function (sev) {
    var v = SEV[sev] || SEV.info;
    var badge = Pet.h("span", { className: "badge " + v.cls }, v.short);
    return badge;
  };

  // ── Surface renderers ──

  // PET-103 D9: the Scanner Health help string lives in one named constant so
  // the JS test can assert its status definitions directly (without rendering
  // the whole dashboard) and so the label and help text cannot drift. Restricted
  // markup only (<b>/<code> + plain prose) — kept valid for Pet.richText and for
  // the richtext.test #19 tripwire (no `&`, no stray angle brackets).
  Pet.SCANNER_HEALTH_HELP =
    "<b>Scanner Health</b>: per-scanner backend status. " +
    "<code>healthy</code>: last scan succeeded. " +
    "<code>degraded</code>: last scan errored or timeout streak. " +
    "<code>circuit_open</code>: consecutive timeout breaker tripped. " +
    "<code>unavailable</code>: backend not installed or prerequisites missing. " +
    "<code>error</code>: backend installed but failed to load. See the error detail.";

  Pet.scannerHealthRows = function (scanners) {
    if (!scanners || !scanners.length) {
      return Pet.h("div", { className: "mono", style: { color: "var(--tx-faint)", fontSize: "12px" } }, "scanner status unavailable: health fetch failed");
    }
    var table = Pet.h("div", { style: { display: "flex", flexDirection: "column", gap: "6px" } });
    for (var i = 0; i < scanners.length; i++) {
      var s = scanners[i];
      // Token-bound .pill variants (no hardcoded greens/reds, so chips follow the
      // Hermes theme): healthy=ok, degraded=warn, unavailable/circuit_open/error=err,
      // unknown=neutral. `error` (installed-but-load-crashed) is a failure state, so
      // it shares the err pill, never falling through to neutral (PET-103 D7).
      var pillCls = "pill";
      if (s.status === "healthy") pillCls = "pill ok";
      else if (s.status === "degraded") pillCls = "pill warn";
      else if (s.status === "unavailable" || s.status === "circuit_open" || s.status === "error") pillCls = "pill err";
      var pill = Pet.h("span", { className: pillCls }, s.status || "unknown");
      var nameEl = Pet.h("span", { className: "mono", style: { fontSize: "12px", color: "var(--tx)", minWidth: "120px", display: "inline-block", overflowWrap: "anywhere" } }, s.name);
      var latency = Pet.h("span", { className: "mono", style: { fontSize: "11px", color: "var(--tx-faint)", minWidth: "60px", display: "inline-block" } }, s.last_ms != null ? (s.last_ms.toFixed(1) + "ms") : "—");
      var row = Pet.h("div", { style: { display: "flex", alignItems: "center", gap: "8px" } });
      row.appendChild(nameEl);
      row.appendChild(pill);
      row.appendChild(latency);
      // PET-103 D6: the per-scanner entry is a column so a multi-line error sits
      // on its own line beneath the name/pill/latency row without breaking their
      // alignment.
      var cell = Pet.h("div", { style: { display: "flex", flexDirection: "column", gap: "2px" } });
      cell.appendChild(row);
      if (s.last_error) {
        // PET-103 D6/D10: render the full message as a real `Pet.h` text-node
        // child (selectable, machine-readable, present in textContent) — wrapped
        // (`pre-wrap`) and height-bounded with scroll instead of clipped to a
        // single-line 250px ellipsis. `title=` is kept as a secondary hover only.
        var errEl = Pet.h("div", {
          className: "mono",
          title: s.last_error,
          style: {
            fontSize: "11px", color: "var(--tx-faint)",
            whiteSpace: "pre-wrap", wordBreak: "break-word",
            maxHeight: "120px", overflowY: "auto", marginTop: "2px",
            userSelect: "text", cursor: "text"
          }
        }, s.last_error);
        cell.appendChild(errEl);
      }
      table.appendChild(cell);
    }
    return table;
  };

  // PET-157: Observability integrity panel builder (mirrors Pet.scannerHealthRows). Reads the
  // additive get_health `integrity` field and renders the self-diagnosing state — ON/OFF, the
  // dominant verdict pill, the failure class, and the remediation line — so an operator can tell
  // config skew (sig-missing/sig-mismatch) from a genuine state from the dashboard alone. Never
  // throws: tolerant of a missing/partial `integrity` object (renders "integrity status
  // unavailable"), matching the scannerHealthRows([]) defensive idiom — the SSE _dispatch
  // re-render path calls this synchronously, so an exception here would abort the live re-render.
  // No alarm styling on the OFF / unattested paths (D2): bare `pill` is the neutral chip.
  Pet.integrityRows = function (integrity) {
    // Missing or partial payload (null/undefined/non-object, or no boolean `key_on`) renders the
    // unavailable fallback rather than guessing a state — mirrors scannerHealthRows([]).
    if (!integrity || typeof integrity !== "object" || typeof integrity.key_on !== "boolean") {
      return Pet.h("div", { className: "mono", style: { color: "var(--tx-faint)", fontSize: "12px" } }, "integrity status unavailable");
    }
    var wrap = Pet.h("div", { style: { display: "flex", flexDirection: "column", gap: "6px" } });
    var keyOn = integrity.key_on === true;
    var verdict = integrity.dominant_verdict;
    // Coerce a counts entry to a non-negative number; anything odd reads as 0 (never throws).
    function _n(x) { return (typeof x === "number" && isFinite(x) && x >= 0) ? x : 0; }
    var c = (integrity.counts && typeof integrity.counts === "object") ? integrity.counts : null;
    // Per-verdict counts over the recent window. Rendered whenever the backend supplied counts,
    // in BOTH modes, so the "single bad row among genuines" case the backend already exposes is
    // visible from the dashboard alone (PET-157 cry-wolf, brief other-implications bullet 1)
    // instead of being masked by the dominant verdict pill.
    function countsLine() {
      if (!c) return null;
      return Pet.h("div", { className: "mono", style: { fontSize: "11px", color: "var(--tx-faint)" } },
        "recent: " + _n(c.genuine) + " genuine / " + _n(c.unattested) + " unattested / " +
        _n(c.unverifiable) + " unverifiable (window " + _n(integrity.window_size) + ")");
    }

    var headRow = Pet.h("div", { style: { display: "flex", alignItems: "center", gap: "8px" } });
    headRow.appendChild(Pet.h("span", { className: "mono", style: { fontSize: "12px", color: "var(--tx)", minWidth: "120px", display: "inline-block" } }, "integrity"));
    // ON => ok pill; OFF => neutral (bare) pill, never an alarm (D2).
    headRow.appendChild(Pet.h("span", { className: keyOn ? "pill ok" : "pill" }, keyOn ? "ON" : "OFF"));
    wrap.appendChild(headRow);

    if (!keyOn) {
      // OFF: the mode-neutral invalid-base64 note (D9) when present, else a short default.
      var offNote = (typeof integrity.remediation === "string" && integrity.remediation)
        ? integrity.remediation
        : "integrity off (no session secret); rows are unattested";
      wrap.appendChild(Pet.h("div", { className: "mono", style: { fontSize: "11px", color: "var(--tx-faint)", whiteSpace: "pre-wrap", wordBreak: "break-word" } }, offNote));
      var offCounts = countsLine();
      if (offCounts) wrap.appendChild(offCounts);
      return wrap;
    }

    // ON: dominant verdict pill (genuine => ok, unattested => neutral, unverifiable => err).
    if (verdict) {
      var vPill = "pill";
      if (verdict === "genuine") vPill = "pill ok";
      else if (verdict === "unverifiable") vPill = "pill err";
      var vRow = Pet.h("div", { style: { display: "flex", alignItems: "center", gap: "8px" } });
      vRow.appendChild(Pet.h("span", { className: "mono", style: { fontSize: "11px", color: "var(--tx-faint)", minWidth: "120px", display: "inline-block" } }, "dominant verdict"));
      vRow.appendChild(Pet.h("span", { className: vPill }, verdict));
      if (typeof integrity.failure_class === "string" && integrity.failure_class) {
        vRow.appendChild(Pet.h("span", { className: "mono", style: { fontSize: "11px", color: "var(--tx-faint)" } }, integrity.failure_class));
      }
      wrap.appendChild(vRow);
    } else {
      // key on but the window is empty (no rows surfaced yet) — honest, not an error (D8).
      wrap.appendChild(Pet.h("div", { className: "mono", style: { fontSize: "11px", color: "var(--tx-faint)" } }, "no rows surfaced yet"));
    }

    var onCounts = countsLine();
    if (onCounts) wrap.appendChild(onCounts);

    // Cry-wolf guard: surface unverifiable rows even when they are NOT the dominant verdict (e.g.
    // one mismatched row among many genuines), so the dominant pill cannot lull the operator into
    // reading a tampered board as healthy. The dominant-unverifiable case already screams via the
    // err pill + remediation, so skip it there to avoid duplication. No per-row class here: the
    // backend reports failure_class only for the dominant-unverifiable case (D8), so this names
    // the count and points the operator at the rows rather than guessing the class.
    var nUnver = c ? _n(c.unverifiable) : 0;
    if (nUnver > 0 && verdict !== "unverifiable") {
      var warnRow = Pet.h("div", { style: { display: "flex", alignItems: "center", gap: "8px", marginTop: "2px" } });
      warnRow.appendChild(Pet.h("span", { className: "pill err" }, nUnver + " unverifiable"));
      warnRow.appendChild(Pet.h("span", { className: "mono", style: { fontSize: "11px", color: "var(--tx-faint)", whiteSpace: "pre-wrap", wordBreak: "break-word" } },
        (nUnver === 1 ? "1 row" : (nUnver + " rows")) + " in the recent window failed verification even though the dominant state is " + verdict + "; investigate before trusting this board."));
      wrap.appendChild(warnRow);
    }

    // Remediation line: present (from the backend) only when the dominant verdict is unverifiable.
    if (typeof integrity.remediation === "string" && integrity.remediation) {
      wrap.appendChild(Pet.h("div", { className: "mono", style: { fontSize: "11px", color: "var(--tx-faint)", whiteSpace: "pre-wrap", wordBreak: "break-word", marginTop: "2px" } }, integrity.remediation));
    }
    return wrap;
  };

  // PET-102: history rows derived from the in-memory scan-history buffer.
  // Mirrors Pet.scannerHealthRows. Must NEVER throw — the SSE _dispatch calls
  // renderDashboard synchronously (petasos.js scan_result handler), so an
  // exception out of the row build would abort the live re-render. Every
  // caller-influenceable field is coerced/guarded. No innerHTML (PET-82): cells
  // are built with Pet.h + .textContent (title= for the truncated session id).
  // PET-137: the per-finding renderer, extracted from Pet.renderScanResult so the
  // live playground result view AND the Observability detail panel share one builder.
  // matched_text-tolerant: shown on hover when present (live playground only); the
  // persisted detail blob strips it (D5), so it renders nothing in the detail panel.
  Pet.findingRows = function (findings) {
    var list = Array.isArray(findings) ? findings : [];
    return list.map(function (f) {
      f = f || {};
      var v = SEV[f.severity] || SEV.info;
      var finding = Pet.h("div", { className: "finding" });
      var rail = Pet.h("div", { className: "rail", style: { background: v.col } });
      var body = Pet.h("div", { className: "body" },
        Pet.h("div", { style: { display: "flex", gap: "8px", alignItems: "center", minWidth: "0" } },
          Pet.h("span", { className: "rid" }, f.rule_id),
          Pet.h("span", { className: "mono", style: { marginLeft: "auto", fontSize: "10px", color: "var(--tx-faint)" } }, f.scanner_name || "")
        ),
        Pet.h("div", { className: "msg" }, f.message || ""),
        f.matched_text ? Pet.h("span", { className: "matched", title: f.matched_text }, f.matched_text) : null
      );
      finding.appendChild(rail);
      finding.appendChild(Pet.SevBadge(f.severity));
      finding.appendChild(body);
      return finding;
    });
  };

  // PET-137: typed scan-detail panel, branched by row kind (D1). Read-only consumer of
  // the persisted summary (enforcement fields) or the bounded playground detail blob —
  // never surfaces matched_text (D5). The provenance line answers "is this legit?" (D3),
  // honest as far as the (unauthenticated, F7) spool allows — never overclaimed.
  Pet.scanDetailPanel = function (e) {
    var wrap = Pet.h("div", { className: "scan-detail" });
    if (!e || typeof e !== "object") {
      wrap.appendChild(Pet.h("div", { className: "sd-sub mono" }, "(detail unavailable)"));
      return wrap;
    }
    var ENF_KINDS = { block: 1, quarantine: 1, tier3: 1 };
    var isEnf = (e.source === "enforcement");
    var et = (e.event_type == null || e.event_type === "") ? "" : String(e.event_type);
    var isBypass = isEnf && et === "bypassed_disarmed";
    // PET-164: self-tamper classification rows (detection only, never a block).
    var isSelfmod = isEnf && et === "selfmod_attempt";
    // PET-167: cold-start markers are enforcement rows that are NOT enforcement decisions,
    // so without their own arm every branch below misses and the panel falls to the
    // terminal "Unknown row kind" else, where `reason` (the whole payload) is never
    // rendered at all.
    var isColdStart = isEnf && (et === "cold_start_degraded" || et === "init_failed");
    // PET-170: ingestion-result scan rows fall into the same trap the comment above
    // records. They need an arm here even though the badge chain already has one — the two
    // chains are independent, and `reason` is the operator's ONLY copy of the evidence
    // (the model-facing banner deliberately quotes none of the matched text), so a flagged
    // row landing in the terminal "Unknown row kind" else is a dead end.
    var isIngest = isEnf && (et === "ingest_flagged" || et === "ingest_unscanned");
    var isEnfDecision = isEnf && !!ENF_KINDS[et];
    var isPlayground = (e.source == null || e.source === "" || e.source === "playground");

    function fld(k, val) {
      return Pet.h("div", { className: "sd-field" },
        Pet.h("span", { className: "sd-k" }, k),
        Pet.h("span", { className: "sd-v mono" }, (val == null || val === "") ? "—" : String(val)));
    }

    // ── Provenance line: "is this legit?" (D3) ──
    var source = isEnf ? "enforcement" : (isPlayground ? "playground" : ("unknown (" + String(e.source) + ")"));
    var scanRan;
    if (isBypass) scanRan = "no (bypassed while Unequipped)";
    else if (isSelfmod) scanRan = "n/a (tool argument classification, not a content scan)";
    // PET-167: this chain is separate from the body branches below, so a body-only edit
    // would leave a row whose entire purpose is to state scan coverage reading "unknown".
    // PET-171: init_failed now runs the syntactic fallback, so "no (enforcement disabled)"
    // became false. Both arms state partial coverage; the difference is permanence.
    else if (isColdStart) scanRan = (et === "init_failed")
      ? "partial (syntactic scan only; ML scanners unavailable)"
      : "partial (syntactic scan only; ML scanners still starting)";
    // PET-170: same reason the chain above needed its own arm. A row whose whole purpose
    // is to state ingestion-scan coverage must never read "unknown" here.
    else if (isIngest) scanRan = (et === "ingest_unscanned")
      ? "no (scan unavailable; content passed through unverified)"
      : "yes (tool result content, scanned inbound)";
    else if (isEnfDecision || isPlayground) scanRan = "yes";
    else scanRan = "unknown";
    var armedStr;
    if (isPlayground) armedStr = "n/a (operator-initiated manual scan)";
    else if (e.armed === true) armedStr = "armed (Equipped)";
    else if (e.armed === false) armedStr = "disarmed (Unequipped)";
    else if (isEnfDecision) armedStr = "armed (Equipped)";  // D6 fallback: block-class only emits while armed
    else armedStr = "unknown";

    var prov = Pet.h("div", { className: "sd-provenance" },
      Pet.h("div", { className: "sd-prov-q" }, "is this legit?"),
      Pet.h("div", { className: "sd-prov-line mono" },
        "source: " + source + "  ·  scan ran: " + scanRan + "  ·  armed: " + armedStr)
    );
    if (isEnf) {
      // PET-139: attestation state from the spool-integrity HMAC verdict (D4), extending
      // PET-137's "is this legit?" line. Read summary.provenance; only the exact strings
      // "genuine" / "unverifiable" map through — an absent / non-string / unknown value
      // renders as "unattested" (not a crash, not a false "genuine"), gated the way the
      // PET-138 bypassed_count path guards its input. No-em-dash house style for the copy.
      // PET-166 (D15): `foreign` joins the map — rows read from a profile this
      // dashboard is not bound to, signed with a key we do not hold. Muted copy,
      // never tamper copy; an unknown value still collapses to unattested.
      var prv = e.provenance;
      var provState = (prv === "genuine" || prv === "unverifiable" || prv === "foreign") ? prv : "unattested";
      var attClass, attText;
      if (provState === "genuine") {
        attClass = "sd-prov-att sd-prov-genuine";
        attText = "Verified Petasos event: the signature checks out against the configured key.";
      } else if (provState === "unverifiable") {
        attClass = "sd-prov-att sd-prov-unverifiable";
        attText = "Unverified: signature missing or invalid; this row may not be a genuine Petasos decision.";
      } else if (provState === "foreign") {
        attClass = "sd-prov-att sd-prov-foreign";
        attText = "Signed by another profile's key; not verifiable from here.";
      } else {
        attClass = "sd-prov-att sd-prov-unattested";
        attText = "Integrity not configured: no signing key is set, so this row cannot be attested.";
      }
      prov.appendChild(Pet.h("div", { className: attClass }, attText));
    }
    wrap.appendChild(prov);

    // ── Kind-specific body ──
    if (isBypass) {
      wrap.appendChild(Pet.h("div", { className: "sd-heartbeat" },
        Pet.h("div", {}, "Enforcement bypassed (Unequipped). No scan was performed."),
        Pet.h("div", { className: "sd-sub" }, "A rate-limited heartbeat (about 1 per 30 s), not a per-call record; bypassed-call coverage is not counted here.")));
      wrap.appendChild(fld("tool", e.tool));
      wrap.appendChild(fld("session", e.session_id));
    } else if (isSelfmod) {
      // PET-164: self-tamper attempt drill-down. Detection only: the classification
      // never changed this call's allow/deny; repeated attempts escalate the session
      // tier and a dedicated alert fires in the gateway log.
      wrap.appendChild(Pet.h("div", { className: "sd-heartbeat" },
        Pet.h("div", {}, "Self-tamper attempt: this call referenced a Petasos-owned config surface."),
        Pet.h("div", { className: "sd-sub" }, "Detection only: the call itself was not blocked by this classification. Repeated attempts escalate the session tier; a dedicated alert fires in the gateway log.")));
      wrap.appendChild(fld("tool", e.tool));
      wrap.appendChild(fld("rule", e.rule_id));
      wrap.appendChild(fld("severity", e.severity));
      wrap.appendChild(fld("reason", e.reason));
      wrap.appendChild(fld("session", e.session_id));
    } else if (isColdStart) {
      // PET-167: cold-start marker drill-down. Non-blocking by design: the record says what
      // coverage this session actually got, it is not itself a decision.
      wrap.appendChild(Pet.h("div", { className: "sd-heartbeat" },
        Pet.h("div", {}, (et === "init_failed")
          ? "Scanner startup failed permanently: this session runs on the fast pattern scan only."
          : "Scanners were still starting: this session ran on the fast pattern scan only."),
        // PET-171: the sub-line is SHARED. "during the window" was false for init_failed,
        // whose blocks continue for the process lifetime with no window. And with no
        // task_id and no _agent the latch is a pair of process-wide booleans while every
        // call mints a fresh anon session, so "one per session" alone would tell an
        // operator that the neighbouring marker-less sessions ran fine.
        Pet.h("div", { className: "sd-sub" }, "At most one such record per session, and one per process when calls cannot be correlated. It marks coverage; blocks appear as their own rows.")));
      wrap.appendChild(fld("tool", e.tool));
      wrap.appendChild(fld("reason", e.reason));
      wrap.appendChild(fld("session", e.session_id));
    } else if (isIngest) {
      // PET-170: ingestion-result scan drill-down. Detection only, by design: the content
      // reached the model whole behind a banner. `reason` carries the raw finding message
      // (or the cause= / len= shape on the unscanned path) and is the operator's only copy
      // of the evidence, so it is rendered here.
      wrap.appendChild(Pet.h("div", { className: "sd-heartbeat" },
        Pet.h("div", {}, (et === "ingest_unscanned")
          ? "A tool result could not be scanned: the content was passed through to the model unverified."
          : "A tool result matched known prompt-injection patterns."),
        Pet.h("div", { className: "sd-sub" }, "Detection only: the content was passed through to the model, prefixed with a warning banner. Nothing was withheld and no tool call was blocked.")));
      wrap.appendChild(fld("tool", e.tool));
      wrap.appendChild(fld("rule", e.rule_id));
      wrap.appendChild(fld("severity", e.severity));
      wrap.appendChild(fld("reason", e.reason));
      wrap.appendChild(fld("session", e.session_id));
    } else if (isEnfDecision) {
      wrap.appendChild(fld("tool", e.tool));
      wrap.appendChild(fld("decision", et));
      wrap.appendChild(fld("tier", e.tier));
      wrap.appendChild(fld("rule", e.rule_id));
      wrap.appendChild(fld("severity", e.severity));
      wrap.appendChild(fld("reason", e.reason));
      wrap.appendChild(fld("session", e.session_id));
    } else if (isPlayground) {
      var det = e.detail;
      if (!det || typeof det !== "object") {
        wrap.appendChild(Pet.h("div", { className: "sd-sub" }, "(detail unavailable)"));
        wrap.appendChild(fld("findings", e.finding_count));
        wrap.appendChild(fld("direction", e.direction));
      } else {
        var fs = Array.isArray(det.findings) ? det.findings : [];
        if (fs.length) {
          wrap.appendChild(Pet.h("div", { className: "sd-section" }, "findings"));
          var vlist = Pet.h("div", { className: "vlist", style: { gap: "8px" } });
          var rows = Pet.findingRows(fs);
          for (var fi = 0; fi < rows.length; fi++) vlist.appendChild(rows[fi]);
          wrap.appendChild(vlist);
          if (Number(det.findings_omitted) > 0) {
            wrap.appendChild(Pet.h("div", { className: "sd-sub" }, "+" + det.findings_omitted + " more findings omitted (capped)"));
          }
        } else {
          wrap.appendChild(Pet.h("div", { className: "sd-sub" }, "no findings"));
        }
        var srs = Array.isArray(det.scanner_results) ? det.scanner_results : [];
        if (srs.length) {
          wrap.appendChild(Pet.h("div", { className: "sd-section" }, "scanners"));
          for (var si = 0; si < srs.length; si++) {
            var sr = srs[si] || {};
            var line = (sr.scanner_name || "?") + ": " + (Number(sr.duration_ms) || 0).toFixed(1) + "ms, "
              + (Number(sr.finding_count) || 0) + " findings" + (sr.error ? (" (error: " + String(sr.error) + ")") : "");
            wrap.appendChild(Pet.h("div", { className: "sd-scanner mono" }, line));
          }
        }
        if (det.normalized_text != null && det.normalized_text !== "") {
          wrap.appendChild(Pet.h("div", { className: "sd-section" }, "normalized text" + (det.normalized_text_truncated ? " (preview)" : "")));
          var pre = Pet.h("div", { className: "sd-normalized mono" });
          pre.textContent = String(det.normalized_text);
          wrap.appendChild(pre);
        }
      }
      wrap.appendChild(fld("session", e.session_id));
    } else {
      // Unknown row kind (D1 default). Do NOT claim playground/manual-scan provenance.
      wrap.appendChild(Pet.h("div", { className: "sd-sub" }, "Unknown row kind; cannot classify this entry."));
      wrap.appendChild(fld("source", e.source));
      wrap.appendChild(fld("event", et));
    }
    return wrap;
  };

  Pet.scanHistoryRows = function (hist) {
    if (!hist || !hist.length) {
      // Honest empty state — never the "..." loading ellipsis (Decision 4).
      return Pet.h("div", { className: "mono", style: { color: "var(--tx-faint)", fontSize: "12px" } }, "no scans yet");
    }
    function pad2(n) { return (n < 10 ? "0" : "") + n; }
    function fmtTime(ts) {
      var n = Number(ts);
      if (ts == null || isNaN(n)) return "—";
      var dt = new Date(n * 1000); // server timestamps are time.time() seconds
      if (isNaN(dt.getTime())) return "—"; // guard against Invalid Date
      return pad2(dt.getHours()) + ":" + pad2(dt.getMinutes()) + ":" + pad2(dt.getSeconds());
    }
    // PET-131: coerce any field to a printable cell — the no-data glyph "—" for
    // null/empty, never the string "undefined" (a bypassed_disarmed row carries no
    // tier/rule/severity). Mirrors the existing guarded cells; never throws.
    function pcell(v, w) {
      var el = Pet.h("span", { className: "mono", style: { fontSize: "11px", color: "var(--tx-faint)", minWidth: w, display: "inline-block" } });
      el.textContent = (v == null || v === "") ? "—" : String(v);
      return el;
    }
    // PET-137: a row click (or Enter/Space) toggles its detail panel. The open row's
    // scan_id lives in Pet.state.openDetailId (not local DOM), so it survives the
    // per-SSE-frame renderDashboard rebuild and re-opens by scan_id on the next render.
    function makeToggle(sid) {
      return function () {
        Pet.state.openDetailId = (Pet.state.openDetailId === sid) ? null : sid;
        if (Pet._runtime.container) Pet.renderDashboard(Pet._runtime.container);
      };
    }
    function makeKey(toggle) {
      return function (ev) {
        if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); toggle(); }
      };
    }
    var table = Pet.h("div", { style: { display: "flex", flexDirection: "column", gap: "6px" } });
    for (var i = 0; i < hist.length; i++) {
      var e = hist[i];
      if (!e || typeof e !== "object") continue; // never-throw: skip a malformed entry (e.g. JSON null from a bad SSE frame) rather than aborting the synchronous re-render

      // PET-131: enforcement rows (source==="enforcement") render distinguishably —
      // an "enf" source pill, a blocked/bypassed/safe badge, and tool + event/tier in
      // place of the playground direction/findings pair. Playground rows are
      // byte-identical to before (no source pill). No em/en dash or double-hyphen in
      // any label (house style); the only "—" is the no-data glyph.
      var isEnforcement = (e.source === "enforcement");
      var et = (e.event_type == null || e.event_type === "") ? "" : String(e.event_type);
      var isBypass = isEnforcement && et === "bypassed_disarmed";
      // PET-164: a self-tamper classification row is detection-only (safe=true on the
      // summary), but it must never wear the green "safe" badge; amber "self-tamper"
      // keeps red reserved for actual blocks.
      var isSelfmodRow = isEnforcement && et === "selfmod_attempt";
      // PET-167: cold-start markers. The summary carries safe=true (they block nothing and
      // stay out of _BLOCK_EVENT_TYPES, so they never inflate the blocked tile), but a row
      // meaning "we did not scan" must never wear the green safe pill. Amber for both:
      // never green ok, never red err.
      var isColdStart = isEnforcement && (et === "cold_start_degraded" || et === "init_failed");
      // PET-170: ingestion-result scan rows. The content was passed through to the model
      // whole, so these are not blocks and the summary carries safe=true (they stay out of
      // _BLOCK_EVENT_TYPES and never inflate the blocked tile). But a row meaning "this
      // content matched an injection pattern" must never wear the green safe pill either.
      // Amber, like cold-start and self-tamper, with the two classes labelled apart the way
      // isColdStart labels its pair: calling an unscanned result "flagged" would assert a
      // finding that by definition does not exist on that path.
      var isFlagged = isEnforcement && (et === "ingest_flagged" || et === "ingest_unscanned");
      var isBlocked = (e.safe === false); // strict ===false; truthy-but-not-false is not "blocked"

      // PET-165: severity-differentiated self-tamper badge. Severity rides the badge TEXT
      // as well as the class, so the critical/high distinction never depends on color
      // alone. Keys on the row's `severity` field (already in the spool summary), not on
      // rule_id, so a future selfmod rule renders correctly with no frontend change.
      // Anything other than the two known severities (missing, null, nonsense, a non-string)
      // falls back to the pre-PET-165 plain amber "self-tamper" — never throws, never
      // renders "undefined".
      var selfmodSev = "";
      if (isSelfmodRow && (e.severity === "critical" || e.severity === "high")) selfmodSev = e.severity;
      var badgeText = isBypass
        ? "bypassed (disarmed)"
        : (isSelfmodRow
            ? ("self-tamper" + (selfmodSev ? (" (" + selfmodSev + ")") : ""))
            : (isColdStart
                // PET-171: "unenforced" is now false. Not reused as "degraded" either:
                // that would erase the transient-versus-permanent distinction at a glance.
                ? (et === "init_failed" ? "syntactic only" : "degraded")
                : (isFlagged
                    ? (et === "ingest_unscanned" ? "unscanned" : "flagged")
                    : (isBlocked ? "blocked" : "safe"))));
      var badgeClass = isBypass
        ? "warn"
        : (isSelfmodRow
            ? (selfmodSev === "critical" ? "err" : "warn")
            : (isColdStart ? "warn" : (isFlagged ? "warn" : (isBlocked ? "err" : "ok"))));
      var badge = Pet.h("span", { className: "pill " + badgeClass, style: { justifyContent: "center" } }, badgeText);

      var rowEls = [];
      if (isEnforcement) {
        rowEls.push(Pet.h("span", { className: "pill blue", style: { minWidth: "40px", justifyContent: "center", fontSize: "10px" } }, "enf"));
      }
      rowEls.push(badge);

      if (isEnforcement) {
        var tierStr = (e.tier == null || e.tier === "") ? "" : String(e.tier);
        var etTier = et + (tierStr && tierStr !== et ? (" " + tierStr) : "");
        rowEls.push(pcell(e.tool, "120px"));
        rowEls.push(pcell(etTier, "120px"));
      } else {
        rowEls.push(pcell(e.direction, "64px"));
        var findEl = Pet.h("span", { className: "mono", style: { fontSize: "11px", color: "var(--tx-faint)", minWidth: "78px", display: "inline-block" } });
        findEl.textContent = (Number(e.finding_count) || 0) + " findings";
        rowEls.push(findEl);
      }

      var latEl = Pet.h("span", { className: "mono", style: { fontSize: "11px", color: "var(--tx-faint)", minWidth: "56px", display: "inline-block" } });
      latEl.textContent = (Number(e.duration_ms) || 0).toFixed(1) + "ms"; // never e.duration_ms.toFixed — would throw on missing/non-numeric
      rowEls.push(latEl);

      var sidStr = (e.session_id == null || e.session_id === "") ? "" : String(e.session_id);
      var sidEl = Pet.h("span", { className: "mono", title: sidStr, style: { fontSize: "11px", color: "var(--tx-faint)", maxWidth: "120px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", display: "inline-block" } });
      sidEl.textContent = sidStr ? (sidStr.length > 12 ? sidStr.slice(0, 12) + "…" : sidStr) : "—";
      rowEls.push(sidEl);

      var timeEl = Pet.h("span", { className: "mono", style: { fontSize: "11px", color: "var(--tx-faint)", marginLeft: "auto", display: "inline-block" } });
      timeEl.textContent = fmtTime(e.timestamp);
      rowEls.push(timeEl);

      var sid = e.scan_id;
      var clickable = (sid != null && sid !== "");
      var isOpen = clickable && Pet.state.openDetailId === sid;
      var rowAttrs = {
        className: "scan-row" + (clickable ? " clickable" : "") + (isOpen ? " open" : ""),
        style: { display: "flex", alignItems: "center", gap: "8px" }
      };
      if (clickable) {
        var toggle = makeToggle(sid);
        rowAttrs.role = "button";
        rowAttrs.tabIndex = 0;
        rowAttrs.ariaExpanded = isOpen;
        // PET-165: AT hears the severity too (spoken, not parenthesized), so the
        // critical/high split is not a purely visual distinction.
        rowAttrs.ariaLabel = (isSelfmodRow ? ("self-tamper detection" + (selfmodSev ? (", " + selfmodSev) : "")) : (isEnforcement ? "enforcement" : "playground")
          + " scan") + " row, " + (isOpen ? "expanded" : "collapsed") + ", activate to toggle detail";
        rowAttrs.onClick = toggle;
        rowAttrs.onKeydown = makeKey(toggle);
      }
      var row = Pet.h("div", rowAttrs);
      for (var ri = 0; ri < rowEls.length; ri++) row.appendChild(rowEls[ri]);
      table.appendChild(row);
      // PET-137: render the open detail panel directly below its row. Re-evaluated on
      // every rebuild and keyed on scan_id, so it survives an incoming SSE frame (D-FE)
      // and closes cleanly if the open row has evicted from the buffer.
      if (isOpen) table.appendChild(Pet.scanDetailPanel(e));
    }
    return table;
  };

  // PET-99 D6/D9: the scan-history seed-merge, extracted as a pure seam so a
  // malformed entry can never throw on render. Mirrors the existing
  // `if (!e || typeof e !== "object") continue` guards in renderDashboard
  // (js tile loop) and scanHistoryRows — closing the one buffer-consuming path
  // that lacked them (the old inline seed-merge dereferenced `.scan_id` on every
  // buffer entry AND every fetched entry with no shape guard). Skips non-object
  // entries on BOTH the existing buffer and the fetched entries before reading
  // `.scan_id`. Behavior-preserving vs the old inline loops: dedups by scan_id,
  // appends unseen (a bare {} with scan_id===undefined is an object, unseen on
  // first occurrence, so it survives — exactly the prior behavior). Mutates
  // `buffer` in place and returns it (the `return` is for test ergonomics).
  // Intentionally does NOT clamp to the SSE path's 500-entry cap — the request
  // limit bounds the fetched set and the next SSE frame re-clamps (out of scope).
  // PET-138: fold an array of scan-history rows into Pet.state.bypassBySession, the
  // dedicated eviction-proof per-session disarmed-bypass accumulator. Tiles
  // recompute from the ≤500 buffer each render, but a bypass count lives on a single
  // rate-limited heartbeat row that ages out — so the count is held here in state
  // (not recomputed from the buffer) and survives eviction once seen. Integer-gated:
  // a plain Number(x)||0 leaks a non-zero float (Number(3.7)||0 === 3.7), so only a
  // clean positive integer contributes (the server normalizes too, but this helper
  // is also called directly in tests with raw frames). Cumulative + Math.max, so a
  // re-surfaced/lower frame never lowers the count. Bounded drop-oldest (mirrors
  // server._MAX_TALLY_SESSIONS; the server tally is authoritative) so the frontend
  // is not the lone unbounded per-session map. Never throws on a malformed entry.
  var _MAX_BYPASS_SESSIONS = 10000; // mirrors server._MAX_TALLY_SESSIONS
  Pet.accrueBypass = function (entries) {
    if (!entries || typeof entries.length !== "number") return;
    var map = Pet.state.bypassBySession;
    for (var i = 0; i < entries.length; i++) {
      var e = entries[i];
      if (!e || typeof e !== "object" || e.event_type !== "bypassed_disarmed") continue;
      var sid = e.session_id;
      if (typeof sid !== "string" || sid === "") continue; // only string session ids (matches server isinstance(sid, str))
      var n = e.bypassed_count;
      // Gate on number-type FIRST (excludes bool/string/null/undefined — Number(true)
      // is 1, so a bare Number() would leak a bool), then positive-integer (excludes
      // float/0/negative/NaN). Mirrors the server's `type(cnt) is int and cnt > 0`.
      if (typeof n !== "number" || !Number.isInteger(n) || n <= 0) continue;
      // hasOwnProperty (not `in` / bare `map[sid]`) so a session id colliding with an
      // inherited Object member (e.g. "toString", "constructor") is read and stored as
      // an OWN property, never miscounted against a prototype member.
      var has = Object.prototype.hasOwnProperty.call(map, sid);
      var prev = has ? map[sid] : 0;
      if (n > prev) {
        map[sid] = n; // refresh in place (existing) or insert (new)
        if (!has) {
          var keys = Object.keys(map);
          if (keys.length > _MAX_BYPASS_SESSIONS) delete map[keys[0]]; // drop-oldest by insertion
        }
      }
    }
  };

  // PET-138: sum the per-session bypass accumulator for the tile. Pure seam (like
  // Pet.mergeScanHistory) so the console JS harness can assert the displayed total
  // without driving the full renderDashboard. Number()||0 is a belt over the
  // already-integer-gated stored values.
  Pet.bypassTotal = function () {
    var map = Pet.state.bypassBySession || {};
    var keys = Object.keys(map);
    var total = 0;
    for (var i = 0; i < keys.length; i++) total += (Number(map[keys[i]]) || 0);
    return total;
  };

  // PET-165: the single adoption seam for the server-authoritative self-tamper lifetime
  // count. Every site that assigns Pet.state.pipelineHealth calls this with the same
  // payload, so the three health-settle paths (auth resume, the 10s poll, the cold-mount
  // in-render fetch) cannot diverge. Strict number gate first (mirrors accrueBypass): a
  // missing/null/boolean/string/NaN/negative value LEAVES the current count rather than
  // writing NaN or a false zero into the tile. Adoption is a plain overwrite, never a
  // monotonic max: overwrite is what makes a console restart honestly reset the tile
  // (lifetime-since-start semantics). The cost is a <=10s downward flicker when a health
  // snapshot taken before an SSE-counted event lands after the client increment; it
  // self-heals on the next poll, and the tile is glanceability, not the audit record.
  Pet.adoptSelfmodTotal = function (pipeline) {
    if (!pipeline || typeof pipeline !== "object") return;
    var n = pipeline.selfmod_total;
    if (typeof n !== "number" || !Number.isFinite(n) || n < 0) return;
    Pet.state.selfmodTotal = n;
  };

  // PET-165: pure row-filter seam for the scan-history pane (testable like
  // Pet.mergeScanHistory / Pet.bypassTotal). Only the "selfmod" filter narrows; every
  // other value (including "all") returns the input UNCHANGED, so the default path is
  // byte-identical to pre-PET-165 rendering. Malformed entries are dropped by the
  // narrowing branch rather than thrown on (matches the scanHistoryRows shape guard).
  // Never mutates the buffer and never feeds a tile.
  Pet.filterHistoryRows = function (entries, filter) {
    if (filter !== "selfmod") return entries;
    var out = [];
    if (!entries || typeof entries.length !== "number") return out;
    for (var i = 0; i < entries.length; i++) {
      var e = entries[i];
      if (e && typeof e === "object" && e.event_type === "selfmod_attempt") out.push(e);
    }
    return out;
  };

  // PET-165: filter-toggle handler. The filter is a LIVE-HEAD view: selecting
  // "self-tamper" from a paged-back view snaps to the head first (via the existing
  // historyPagingView "head" transition), because a filtered slice of one older page
  // would read as "these are the self-tamper events" when it is only the events in that
  // page. Paged views therefore always render unfiltered. Announces for AT, then
  // re-renders through the normal renderDashboard path.
  Pet.setHistoryFilter = function (filter) {
    var next = (filter === "selfmod") ? "selfmod" : "all";
    var atHead = Pet.state.historyAtHead !== false;
    if (next === Pet.state.historyFilter && atHead) return; // nothing to change
    Pet.state.historyFilter = next;
    if (next === "selfmod" && !atHead) {
      var plan = Pet.historyPagingView(
        { atHead: Pet.state.historyAtHead, stack: Pet.state.historyStack }, "head"
      );
      Pet.state.historyAtHead = plan.atHead;
      Pet.state.historyStack = plan.stack;
    }
    if (Pet.announce) {
      Pet.announce(next === "selfmod"
        ? "Scan history filtered to self-tamper events"
        : "Scan history filter cleared, showing all rows");
    }
    if (Pet._runtime.container) Pet.renderDashboard(Pet._runtime.container);
  };

  // PET-144: honest scan-history subtitle. The ≤500 ring evicts silently; when the
  // authoritative lifetime count (scans_total from /health) exceeds the buffered
  // window, say so instead of implying the window is the whole record. Pure seam so
  // the console JS harness can assert the label without driving renderDashboard.
  Pet.scanHistorySubtitle = function (buffered, total) {
    var b = Number(buffered); if (!Number.isFinite(b) || b < 0) b = 0;
    var t = Number(total);
    // total absent / non-numeric (health not yet loaded) or not actually evicting:
    // fall back to the static subtitle, never a misleading "of NaN".
    if (!Number.isFinite(t) || t <= b) return "recent evaluations";
    return "showing last " + b + " of " + t;
  };

  // PET-152: the honest "are there retained rows older than the live window?" predicate that
  // gates the "Older" affordance off the live head. Reuses the SAME lifetime N already shown in
  // scanHistorySubtitle (/health.scans_total, D-RESTART) — no competing total is minted. The
  // b > 0 term (a deliberate divergence from scanHistorySubtitle, which is a pure label and
  // tolerates b === 0) refuses to offer "Older" off an EMPTY live buffer: an empty window has no
  // oldest edge to page past, and the one-shot seed (not "Older") is what populates the head.
  // Without it, scans_total > 0 over a transiently-empty pre-seed buffer would re-mint from the
  // Nth-newest row and CREATE a gap over rows 1..N (edges E-2/E-4). Pure (no DOM, no network).
  Pet.scanHistoryHasOlder = function (buffered, total) {
    var b = Number(buffered), t = Number(total);
    return Number.isFinite(b) && Number.isFinite(t) && b > 0 && t > b;
  };

  // ── PET-166: read-scope pure seams ──
  // Every one of these is pure over its arguments (no DOM, no network), matching the
  // discipline of every other history label in this file, and for the same stated
  // reason: no tests/js module drives renderDashboard, so a decision living inline
  // at the render site would be unassertable.

  // D19: THE one non-equipped predicate. Zero-arg form reads Pet.state.readScope; the
  // history panel passes Pet.state.historyReadScope explicitly (its facts arrive on a
  // different endpoint). null/undefined (all of standalone; the pre-first-200 window)
  // is the equipped form — never a bare .state dereference anywhere else.
  Pet.isForeignScope = function (scope) {
    if (arguments.length === 0) scope = Pet.state.readScope;
    return !!scope && scope.state !== "equipped";
  };

  // D7: the shared "is this a scoped-profile 422" test. Status-keyed (a 422 body
  // carries no `error`, so the readers' `!d.error` gates would treat it as an empty
  // success and wipe healthy panels). Checked AFTER Pet.auth.on401 in every reader.
  Pet.isProfile422 = function (d) {
    return !!(d && d._status === 422 && Array.isArray(d.detail)
      && d.detail.some(function (e) { return e && e.field === "profile"; }));
  };

  // D12: staleness derived client-side from the newest row of the UNFILTERED head
  // buffer. Returns null (age clause dropped) for no rows or a non-numeric
  // timestamp; a future timestamp clamps to "just now" rather than taking the fresh
  // branch off a bogus negative age. { label, stale } with stale at >= 1 h.
  Pet.scanHistoryAge = function (rows) {
    if (!rows || !rows.length) return null;
    var r = rows[0];
    var ts = (r && typeof r === "object") ? r.timestamp : null;
    if (typeof ts !== "number" || !isFinite(ts)) return null;
    var age = (Date.now() / 1000) - ts;
    if (age < 0) age = 0; // skewed profile clocks: clamp, never a negative "freshest" age
    var d = new Date(ts * 1000);
    var hh = ("0" + d.getHours()).slice(-2), mm = ("0" + d.getMinutes()).slice(-2);
    var ago;
    if (age < 60) ago = "just now";
    else if (age < 3600) ago = Math.floor(age / 60) + "m ago";
    else if (age < 86400) ago = Math.floor(age / 3600) + "h ago";
    else ago = Math.floor(age / 86400) + "d ago";
    return { label: "newest " + hh + ":" + mm + " (" + ago + ")", stale: age >= 3600 };
  };

  // D12: the scoped subtitle seam beside the shipped scanHistorySubtitle (whose
  // two-argument signature is deliberately NOT widened). `body` is a string, not a
  // count, so one seam mints both foreign forms: "showing last 12" at head and the
  // historyPageLabel when paged. It emits the trailing self-tamper clause ITSELF
  // from filterOn — the render site skips PET-165's append on the seam arms so the
  // clause can never render twice.
  Pet.scopedHistorySubtitle = function (body, profileName, ageLabel, stale, filterOn) {
    var s = String(body == null ? "" : body) + " for " + String(profileName == null ? "" : profileName);
    if (ageLabel) s += " · " + ageLabel;
    if (stale) s += " · stale";
    if (filterOn) s += " · self-tamper only";
    return s;
  };

  // D12: the foreign "Older" gate. Keeps scanHistoryHasOlder's b > 0 term (a
  // transiently-empty buffer is a per-switch event now, and paging off it re-mints
  // from the Nth-newest row and silently omits the head band — PET-152 E-2/E-4);
  // only the total moves to the server-emitted has_older boolean.
  Pet.scopedHistoryHasOlder = function (bufferLength, hasOlder) {
    var b = Number(bufferLength);
    return Number.isFinite(b) && b > 0 && hasOlder === true;
  };

  // D12: the empty-state ladder, PET-165's arm order preserved exactly with one new
  // arm appended and scope-aware copy inside. Returns { arm, text } when the render
  // site should print an empty-state body, and null when it should call
  // Pet.scanHistoryRows — null for arm 4 AND arm 3's equipped branch, which is what
  // keeps the "no scans yet" literal owned solely by scanHistoryRows. The !histPaged
  // guard on arm 3 is load-bearing: while paged, the live buffer emptying underneath
  // must not replace fetched rows with an empty-state sentence (PET-148).
  Pet.historyEmptyState = function (hist, histRowsData, histPaged, histEffFilter, isForeign, profileName) {
    hist = hist || [];
    histRowsData = histRowsData || [];
    if (histPaged && histRowsData.length === 0) {
      return { arm: 1, text: Pet.historyPageLabel(histPaged) }; // positional, never named (D12)
    }
    if (histEffFilter === "selfmod" && histRowsData.length === 0) {
      if (isForeign) {
        if (hist.length === 0) {
          // the filter is not why anything is missing; the copy is arm 3's
          return { arm: 3, text: "no scans retained for " + String(profileName || "") };
        }
        return { arm: 2, text: "no self-tamper events among the rows retained for " + String(profileName || "") };
      }
      return { arm: 2, text: "No self-tamper events in the buffered window." }; // PET-165 verbatim
    }
    if (!histPaged && hist.length === 0 && isForeign) {
      return { arm: 3, text: "no scans retained for " + String(profileName || "") };
    }
    return null;
  };

  // D8: the self-tamper tile keeps its value under a foreign scope and RELABELS to
  // name the binding it counts — it is a lifetime fact about the process that is
  // actually enforcing, and suppressing it would hide a live security signal to
  // avoid a labelling problem. The HelpTip is amended in the same seam because
  // "the scan history below" is another profile's file under a foreign scope.
  Pet.selfmodTileLabel = function (isForeign) {
    if (isForeign) {
      return {
        label: "self-tamper (this dashboard's binding)",
        help: "<b>Self-tamper</b>: tool calls that tried to write or read Petasos's own config, profile homes, or enforcement spool. Counted since this console started, for the profile this dashboard is bound to; the scan history below shows the selected profile instead. Detection only: these calls were not blocked.",
      };
    }
    return {
      label: "self-tamper",
      help: "<b>Self-tamper</b>: tool calls that tried to write or read Petasos's own config, profile homes, or enforcement spool. Counted since this console started, so it does not fall when older rows age out of the scan history below. Detection only: these calls were not blocked.",
    };
  };

  // D9: the connection chip's three-state decision, in a fixed order: POLLING
  // outranks SCOPED (a dead connection is the more urgent fact), else SCOPED, else
  // LIVE. The refusal titles never name the refused profile — the SCOPED tooltip
  // must not assert a scoped read of a name the server just declined to resolve.
  Pet.connChipView = function (usingFallback, scopeLive, refusal) {
    if (usingFallback) {
      return { className: "live polling", label: "POLLING", title: "Live stream unavailable; polling every 10s." };
    }
    if (!scopeLive) {
      var title;
      if (refusal === "profile") title = "live stream refused: profile not found";
      else if (refusal === "capacity") title = "live stream refused: event stream at capacity";
      else {
        var sel = Pet.state.selectedHermesProfile;
        title = "Viewing " + (sel ? String(sel) : "another profile") + "; live events stream only for the equipped profile. History refreshes every 30s.";
      }
      return { className: "live scoped", label: "SCOPED", title: title };
    }
    return { className: "live", label: "LIVE", title: "Live updates streaming." };
  };

  // D10: the playground note decision. A playground scan runs through the live
  // pipeline (a write against the equipped binding), so a foreign read scope gets a
  // one-line note instead of a result that never appears in the panel below.
  Pet.playgroundScopeNote = function (scope) {
    return Pet.isForeignScope(scope)
      ? "this scan ran against the equipped binding; it will not appear in the selected profile's history"
      : null;
  };

  // D17: the armed-write resolution decision (the PET-129 D3 bannerView extraction
  // pattern: the decision is a pure seam, paintBanner stays the render-local
  // painter). The caller clears Pet._runtime.armedBusy FIRST and routes 401 SECOND; this seam
  // then decides. On a moved scope generation it says drop-and-re-read: never
  // reconcile the stale optimistic bit, never banner the prior scope's message.
  Pet.armedWriteView = function (ctx) {
    ctx = ctx || {};
    var d = ctx.response || {};
    if (ctx.scopeMoved) {
      return { action: "drop", armedSeeded: false, banner: null, reread: true };
    }
    if (d._status === 409) {
      var e0 = Array.isArray(d.detail) ? d.detail[0] : null;
      return {
        action: "refused", armedSeeded: false, reread: true,
        banner: (e0 && e0.message) || "arming refused: not the equipped profile",
        armed: !ctx.next, // revert the optimistic bit; the re-read lands server truth
      };
    }
    if (Pet.isProfile422(d)) {
      var e1 = d.detail.filter(function (x) { return x && x.field === "profile"; })[0];
      return {
        action: "rejected", armedSeeded: false, reread: true,
        banner: (e1 && e1.message) || "profile rejected",
        armed: !ctx.next,
      };
    }
    var ok = d && !d.error && (!d._status || d._status < 400) && typeof d.armed === "boolean";
    return { action: "reconcile", armedSeeded: true, banner: null, reread: false, armed: ok ? d.armed : !ctx.next };
  };

  // PET-148: positional label for a paged-back history view (D-RESTART). NEVER a numeric
  // total — the only "of N" headline anywhere stays scanHistorySubtitle (scans_total from
  // /health). An empty page is retention-honest: "no older retained history" when the
  // cursor's segment aged out (older_truncated), never a flat "no older history" that would
  // read as a false absolute bottom (D-ROTATION / edge F-2). Pure (no DOM, no network).
  Pet.historyPageLabel = function (page) {
    page = page || {};
    var entries = Array.isArray(page.entries) ? page.entries : [];
    if (entries.length === 0) {
      return page.olderTruncated ? "no older retained history" : "no older history";
    }
    return "older history";
  };

  // PET-148/PET-152: pure paging-state transition for scan-history back-pages (testable in
  // node:vm, like scanHistorySubtitle / mergeScanHistory). The server cursor walks only OLDER
  // (D-PAGING); "newer" replays the client-buffered page stack back toward the live head.
  // Given the current paging state + a navigation action, returns the next-state descriptor
  // {atHead, stack, cursor, needsFetch, needsRemint, remintLimit?} — no DOM, no network. For
  // "older" OFF THE LIVE HEAD the reducer signals needsRemint (PET-152) instead of handing back a
  // cached head cursor that goes stale after ring eviction; the handler then re-mints the head
  // boundary via a fresh getScanHistory(remintLimit) round-trip and pages from that. For "older"
  // from a paged view the caller fetches with `cursor` (when needsFetch); for "newer"/"head" the
  // returned {atHead, stack} is applied directly (client-buffered, no fetch).
  Pet.historyPagingView = function (state, action) {
    state = state || {};
    var stack = Array.isArray(state.stack) ? state.stack.slice() : [];
    var top = stack.length ? stack[stack.length - 1] : null;
    if (action === "head") {
      return { atHead: true, stack: [], cursor: null, needsFetch: false };
    }
    if (action === "newer") {
      stack.pop(); // drop the current paged view
      if (stack.length === 0) return { atHead: true, stack: [], cursor: null, needsFetch: false };
      return { atHead: false, stack: stack, cursor: null, needsFetch: false };
    }
    if (action === "older") {
      if (top) {
        // Paged view (unchanged): advance past the current page via its server next_before.
        var cursor = (top.nextBefore != null) ? top.nextBefore : null;
        var needsFetch = cursor != null;
        return {
          atHead: needsFetch ? false : (state.atHead !== false),
          stack: stack, cursor: cursor, needsFetch: needsFetch, needsRemint: false,
        };
      }
      // Off the live head: re-mint required (PET-152); never reuse a cached cursor. The head
      // boundary is re-derived by the handler from a fetch sized to the runtime buffer length.
      var bufferLength = (typeof state.bufferLength === "number" && state.bufferLength > 0)
        ? state.bufferLength : 0;
      if (bufferLength === 0) {
        // Empty live buffer: no oldest edge to page past; the one-shot seed populates the head,
        // not "Older". Refuse to fetch so we never page from the Nth-newest row and create a gap
        // over rows 1..N (edges E-2/E-4).
        return {
          atHead: state.atHead !== false, stack: stack,
          cursor: null, needsFetch: false, needsRemint: false,
        };
      }
      return {
        atHead: false, stack: stack, cursor: null,
        needsFetch: false, needsRemint: true, remintLimit: bufferLength,
      };
    }
    // Unknown action: stay put.
    return { atHead: state.atHead !== false, stack: stack, cursor: null, needsFetch: false };
  };

  Pet.mergeScanHistory = function (buffer, entries) {
    var seen = new Set();
    for (var j = 0; j < buffer.length; j++) {
      var cur = buffer[j];
      if (cur && typeof cur === "object") seen.add(cur.scan_id);
    }
    for (var k = 0; k < entries.length; k++) {
      var en = entries[k];
      if (en && typeof en === "object" && !seen.has(en.scan_id)) {
        buffer.push(en); seen.add(en.scan_id);
      }
    }
    return buffer;
  };

  // PET-129 D3: pure banner label/sub/class decision, authRequired-FIRST. Extracted
  // from paintBanner so the headless node:vm harness (no querySelector) can assert the
  // decision directly. When authRequired is set, the banner renders an explicit
  // AUTHENTICATE state and NEVER EQUIPPED, regardless of the optimistic armed default
  // (closes defect #2). The non-auth branch is byte-for-byte today's paintBanner logic
  // for a boolean armed value (no-regression for the token-off path).
  Pet.bannerView = function (state) {
    state = state || {};
    if (state.authRequired) {
      return {
        label: "AUTHENTICATE",
        sub: "Enter the console token to view enforcement state",
        cls: "equip-banner unknown",
        on: false,
        confirming: false,
        authRequired: true,
      };
    }
    var on = state.armed !== false && state.armed != null;
    var confirming = on && !!state.confirming;
    return {
      label: confirming ? "CONFIRM UNEQUIP?" : (on ? "EQUIPPED" : "UNEQUIPPED"),
      sub: confirming
        ? "Click again to disable all enforcement"
        : (on ? "Enforcement is ON" : "Enforcement is OFF for every session"),
      cls: "equip-banner" + (on ? "" : " disarmed") + (confirming ? " confirming" : ""),
      on: on,
      confirming: confirming,
      authRequired: false,
    };
  };

  // PET-185: the ONE derivation of the arm control's scope state and the caption that
  // names which binding the banner above it describes. Pure (readScope in, plain object
  // out) so the node:vm harness can assert the labelling directly. PET-166 D16's three
  // states are preserved exactly; only the caption text gains the binding name.
  Pet.armScopeView = function (readScope) {
    var s = readScope || null;
    if (!s) return { disabled: false, unscoped: false, notice: null };
    var st = s.state;
    var selected = String(s.selected || "the selected profile");
    var disabled = st === "not_equipped" && s.equipped != null;
    var unscoped = st === "unknown" || s.equipped == null;
    // The binding's parenthetical is emitted ONLY for a tier that names something an
    // operator can act on. `equipped_tier` falls back to the raw resolution tier when no
    // member is active (server.py:613), so "profile" IS reachable here (an active_profile
    // pointing at a directory with no config.yaml: _paths.py:104 admits the dir, and
    // list_hermes_profiles skips it at _paths.py:184). "(this profile)" would name nothing
    // and read as a contradiction, so that tier and an absent tier get no parenthetical.
    var where = st === "unknown" ? ""
      : (s.equipped_tier === "hermes_home" ? " (HERMES_HOME)"
        : (s.equipped_tier === "root" ? " (the root Hermes home)" : ""));
    if (disabled) {
      return { disabled: true, unscoped: false,
        notice: "arming is disabled here: " + selected + " is not the equipped profile ("
          + String(s.equipped) + " is). The banner above shows " + String(s.equipped)
          + "'s state, not " + selected + "'s." };
    }
    if (unscoped) {
      // The two branches deliberately say DIFFERENT things. In the unknown row the
      // binding is unreachable, so read_armed returns its fail-secure True and a write
      // 503s (Decision 1): claiming the banner "describes" that binding would be the
      // same false confidence this ticket is removing.
      return { disabled: false, unscoped: true,
        notice: (st === "unknown"
          ? "could not verify this dashboard's binding. The banner shows the fail-secure state, and arming may not persist. It does not describe "
            + selected + "."
          : "the banner and the toggle both describe this dashboard's binding" + where
            + ", not " + selected + ". Arming here does not change " + selected + "'s enforcement.") };
    }
    return { disabled: false, unscoped: false, notice: null };
  };


  Pet._moduleState.last = "observability";
})();
