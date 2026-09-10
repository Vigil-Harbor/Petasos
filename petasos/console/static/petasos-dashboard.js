/* Owns: authentication and Observability rendering. Depends on: core, transport, observability, and Pet shell paging callbacks. */
(function () {
  "use strict";
  var Pet = window.__PETASOS_CONSOLE__;
  var actual = Pet && Pet._moduleState ? Pet._moduleState.last : "missing";
  if (actual !== "observability") throw new Error("petasos-dashboard expected module observability, got " + actual);

  // PET-129 D2: the authenticate panel rendered (instead of the dashboard tiles) while
  // Pet.state.authRequired is set. Shows the honest banner (bannerView authRequired ->
  // AUTHENTICATE, never EQUIPPED), a token field + Unlock submit, and an explicit
  // "clear token" affordance. Crucially it issues NO /api reads, so a token-gated
  // console renders a clear authenticate state rather than 401-looping broken tiles.
  // The submit runs the D4 resume sequence with the stale-submit generation guard; the
  // control is disabled while a resume is in flight and re-enabled with a reason on a
  // wrong/transient result. Clear runs the same idempotent teardown as on401 (F-9).
  Pet.renderAuthPanel = function () {
    var view = Pet.bannerView({ authRequired: true });
    var wrapper = Pet.h("div", { style: { display: "flex", flexDirection: "column", gap: "16px", height: "100%" } });

    wrapper.appendChild(Pet.h("div", { className: view.cls },
      Pet.h("img", { className: "equip-mark", src: Pet.asset("img/petasos-unequipped.png"), alt: "" }),
      Pet.h("div", { className: "equip-text" },
        Pet.h("div", { className: "equip-label" }, view.label),
        Pet.h("div", { className: "equip-sub" }, view.sub)
      )
    ));

    var msg = Pet.h("div", { className: "mono", style: { fontSize: "12px", color: "var(--tx-faint)", minHeight: "16px" } });
    var input = Pet.h("input", {
      type: "password", placeholder: "Console token", ariaLabel: "Console token",
      style: {
        flex: "1", minWidth: "0", padding: "10px 12px", borderRadius: "var(--r-panel)",
        background: "var(--bg-panel)", border: "1px solid var(--border)",
        color: "var(--tx)", fontFamily: "var(--font-mono)", fontSize: "13px"
      }
    });
    var submitBtn = Pet.h("button", {
      type: "button", className: "btn",
      style: { padding: "10px 16px", whiteSpace: "nowrap" }
    }, "Unlock");
    var clearBtn = Pet.h("button", {
      type: "button", className: "btn",
      style: { padding: "8px 12px", fontSize: "12px", alignSelf: "flex-start", color: "var(--tx-faint)" }
    }, "Clear token");

    var doSubmit = function () {
      var val = input.value;
      if (!val || submitBtn.disabled) return;
      submitBtn.disabled = true;                 // belt-and-suspenders against a double-submit (D2)
      msg.textContent = "Verifying...";
      Pet.auth.submitToken(val).then(function (res) {
        if (res && res.ok) return;               // resume cleared authRequired and re-rendered the dashboard
        if (res && res.stale) return;            // superseded by a later submit; that submit owns the outcome
        submitBtn.disabled = false;
        msg.textContent = (res && res.message) || "Authentication failed. Check the token and retry.";
      });
    };
    submitBtn.addEventListener("click", doSubmit);
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") { e.preventDefault(); doSubmit(); }
    });
    clearBtn.addEventListener("click", function () { Pet.auth.clearToken(); });

    var help = Pet.h("div", { className: "mono", style: { fontSize: "11px", color: "var(--tx-faint)", lineHeight: "1.5" } },
      "This console requires a token (PETASOS_CONSOLE_TOKEN). It is held for this browser tab only and is no stronger than your browser session.");

    var row = Pet.h("div", { style: { display: "flex", gap: "10px", alignItems: "center" } }, input, submitBtn);
    wrapper.appendChild(Pet.h("div", {
      style: {
        display: "flex", flexDirection: "column", gap: "10px",
        padding: "16px", borderRadius: "var(--r-panel)",
        background: "var(--bg-panel)", border: "1px solid var(--border)"
      }
    }, row, msg, help, clearBtn));

    return wrapper;
  };

  Pet.renderDashboard = function (container) {
    container.innerHTML = "";
    // PET-129 D2/D3: in the authenticate state, render the token-entry panel and issue
    // NO data reads (no getArmed/getHealth/getScanHistory), so a token-gated console
    // shows a clear authenticate state instead of 401-looping skeletons/broken tiles.
    if (Pet.state.authRequired) {
      container.appendChild(Pet.renderAuthPanel());
      return;
    }
    var wrapper = Pet.h("div", { style: { display: "flex", flexDirection: "column", gap: "16px", height: "100%" } });

    // ── PET-111: Equipped/Unequipped master switch (first child of the tab) ──
    // paintBanner re-queries the LIVE banner node each call (never closes over a
    // captured node): renderDashboard rebuilds the banner on every SSE/poll frame,
    // and Pet._runtime.container is null after unmount — so guard container-truthiness first.
    // PET-129 D3: paintBanner derives ALL of its live outputs (label, .equip-banner
    // class, .switch/aria-checked, helmet art) from the pure Pet.bannerView decision,
    // which keys on authRequired first. So a 401 (or an operator click while
    // unauthenticated) can never repaint EQUIPPED on the live node.
    var paintBanner = function () {
      var b = Pet._runtime.container && Pet._runtime.container.querySelector(".equip-banner");
      if (!b) return;
      var view = Pet.bannerView({
        authRequired: Pet.state.authRequired,
        armed: Pet.state.armed,
        confirming: Pet._runtime.armedConfirmPending,
      });
      b.className = view.cls;
      var lbl = b.querySelector(".equip-label");
      if (lbl) lbl.textContent = view.label;
      var sub = b.querySelector(".equip-sub");
      if (sub) sub.textContent = view.sub;
      var sw = b.querySelector(".switch");
      if (sw) {
        sw.className = "switch" + (view.on && !view.confirming ? " on" : "");
        sw.setAttribute("aria-checked", view.on ? "true" : "false");
        sw.setAttribute("aria-label", "Petasos enforcement: " + (view.on ? "equipped, click to unequip" : "unequipped, click to equip"));
      }
      // PET-13: two-state helmet art - worn (equipped) when armed, off (unequipped) when not.
      var mark = b.querySelector(".equip-mark");
      if (mark) mark.src = Pet.asset(view.on ? "img/petasos-equipped.png" : "img/petasos-unequipped.png");
    };
    // PET-166 (D16) via PET-185: the arm control is the ONE consumer that reads scope
    // state directly (it discriminates three states, not two). The derivation lives in
    // the pure Pet.armScopeView seam; both booleans are bit-identical to the old inline
    // form for every input, including the null-readScope standalone path.
    var _armView = Pet.armScopeView(Pet.state.readScope);
    var _armDisabled = _armView.disabled;
    var _armUnscoped = _armView.unscoped;
    var doToggle = function () {
      if (Pet.state.authRequired) return; // PET-129 D3: no toggling (or EQUIPPED repaint) while unauthenticated
      if (Pet._runtime.armedBusy) return;  // ignore rapid re-clicks while a write is in flight
      if (_armDisabled) return; // PET-166 D6/D16: arming a non-equipped profile is refused client-side too
      var on = Pet.state.armed !== false;
      // Disarming is the high-stakes direction: require a confirming 2nd click.
      // Arming protection back ON stays one click.
      if (on && !Pet._runtime.armedConfirmPending) {
        Pet._runtime.armedConfirmPending = true;
        paintBanner();
        Pet._runtime.armedConfirmTimer = setTimeout(function () { Pet._shell.clearArmedConfirm(); paintBanner(); }, 4000);
        return;
      }
      Pet._shell.clearArmedConfirm();
      var next = !on;
      Pet._runtime.armedBusy = true;
      var gen = Pet._runtime.scopeGen; // PET-166 D17: captured at send time, checked at resolve
      Pet.state.armed = next; paintBanner();  // optimistic (live re-query, survives re-render)
      Pet.api.setArmed(next, { unscoped: _armUnscoped }).then(function (d) {
        // PET-166 D17: the order below is the deliverable. (1) the latch clears
        // unconditionally — a return above this line strands the toggle dead for the
        // rest of the mount; (2) 401 enters the authenticate state even on a
        // superseded scope (PET-129 §1); (3) the scope-generation drop; (4) reconcile.
        Pet._runtime.armedBusy = false; // cleared on EVERY path (incl. the 401 route below) so re-auth can re-seed
        if (Pet.auth.on401(d)) return;
        var view = Pet.armedWriteView({ scopeMoved: gen !== Pet._runtime.scopeGen, response: d, next: next });
        Pet._runtime.armedSeeded = view.armedSeeded;
        if (view.action === "drop") {
          // leave the re-seed to the render path (:re-seed guard) so the new scope's
          // bit is re-read from the server rather than inherited or reconciled.
          if (Pet.state.tab === "obs" && Pet._runtime.container) Pet.renderDashboard(Pet._runtime.container);
          return;
        }
        if (view.armed !== undefined) Pet.state.armed = view.armed;
        if (view.banner) {
          // D16/D6: render the refusal in the banner sub line and announce for AT.
          var subEl = Pet._runtime.container && Pet._runtime.container.querySelector(".equip-banner .equip-sub");
          if (subEl) subEl.textContent = view.banner;
          if (Pet.announce) Pet.announce(view.banner);
        } else {
          paintBanner();
        }
        if (view.reread) {
          Pet.api.getArmed().then(function (rd) {
            if (Pet.auth.on401(rd)) return;
            if (gen !== Pet._runtime.scopeGen) return;
            if (Pet._runtime.armedBusy) return;
            Pet._scope.adoptRead(rd);
            if (rd && !rd.error && typeof rd.armed === "boolean") {
              Pet.state.armed = rd.armed;
              paintBanner();
            }
          });
        }
      });
    };
    var armedOn = Pet.state.armed !== false;
    var confirming = armedOn && Pet._runtime.armedConfirmPending;
    var armedSwitch = Pet.h("button", {
      className: "switch" + (armedOn && !confirming ? " on" : ""), type: "button", onClick: doToggle,
      role: "switch", ariaChecked: armedOn ? "true" : "false",
      ariaLabel: "Petasos enforcement: " + (armedOn ? "equipped, click to unequip" : "unequipped, click to equip")
    });
    if (_armDisabled) armedSwitch.disabled = true;
    armedSwitch.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); doToggle(); }
    });
    wrapper.appendChild(Pet.h("div", { className: "equip-banner" + (armedOn ? "" : " disarmed") + (confirming ? " confirming" : "") },
      Pet.h("img", { className: "equip-mark", src: Pet.asset(armedOn ? "img/petasos-equipped.png" : "img/petasos-unequipped.png"), alt: "" }),
      Pet.h("div", { className: "equip-text" },
        Pet.h("div", { className: "equip-label" }, confirming ? "CONFIRM UNEQUIP?" : (armedOn ? "EQUIPPED" : "UNEQUIPPED")),
        Pet.h("div", { className: "equip-sub" }, confirming ? "Click again to disable all enforcement" : (armedOn ? "Enforcement is ON" : "Enforcement is OFF for every session"))
      ),
      Pet.HelpTip("<b>Equipped</b>: master switch. <b>Unequipped</b> disables <b>all</b> Petasos enforcement (scan, guard, audit) for this and running sessions, applied by the next tool call. Backed by <code>petasos.enabled</code>."),
      armedSwitch
    ));
    // PET-166 (D16) via PET-185: label the arm control with the binding the banner
    // describes. The caption text is armScopeView's; a role="status" readout must
    // clear WCAG 1.4.3, hence --tx-mut rather than --tx-faint (petasos.css:179-183).
    if (_armView.notice) {
      wrapper.appendChild(Pet.h("div", { className: "mono", role: "status", style: { fontSize: "11px", color: "var(--tx-mut)" } },
        _armView.notice));
    }
    // PET-166 (D20): the client-side scope notice — a 200 the client believes it
    // scoped came back without a confirmed scope, so what is shown below is the
    // equipped binding's data, said out loud rather than misattributed.
    if (Pet.state.scopeNotice) {
      wrapper.appendChild(Pet.h("div", { role: "status", className: "notice" },
        Pet.Icon("warn"),
        Pet.h("span", {}, "showing: equipped binding. The backend did not confirm the selected profile scope; re-sync the console bundle if this persists.")));
    }
    // PET-166 (D7): the coherent scoped-422 state — ONE box, not four independent
    // error panels, and the stale panels below are not painted under it.
    if (Pet.state.scopeError) {
      wrapper.appendChild(Pet.h("div", { role: "alert", className: "notice" },
        Pet.Icon("warn"),
        Pet.h("span", {}, "this profile has no Petasos configuration yet (" + String(Pet.state.scopeError.message || "profile not resolved") + ")")));
      container.appendChild(wrapper);
      return;
    }

    // ── Metric tiles, computed from the in-memory scan-history buffer ──
    // (PET-102) The SSE scan_result handler maintains Pet.state.scanHistory and
    // re-renders this dashboard on every event, so deriving the tiles from that
    // array keeps tiles + history consistent on every recompute. Semantics are
    // buffer-scoped (Decision 6): each tile describes the current ≤500-entry
    // buffer, not lifetime totals.
    var hist = Pet.state.scanHistory || [];
    var scans = hist.length;
    var blocked = 0;
    var latencySum = 0;
    var sessionSet = new Set(); // ES6 runtime API, already relied on elsewhere (AbortController/TextDecoder)
    for (var i = 0; i < hist.length; i++) {
      var e = hist[i];
      if (!e || typeof e !== "object") continue; // never-throw: skip a malformed entry (e.g. JSON null from a bad SSE frame)
      if (e.safe === false) blocked++; // strict ===false (Decision 6)
      latencySum += (Number(e.duration_ms) || 0); // missing/non-numeric counts as 0; never throws
      var sid = e.session_id;
      if (sid !== null && sid !== undefined && sid !== "") sessionSet.add(sid); // distinct truthy session ids
    }
    // avg over an empty buffer is undefined → dash (honest, distinct from "..."
    // loading and from a true zero count); counts render literal 0 (Decision 4).
    var avgLatency = hist.length > 0 ? ((latencySum / hist.length).toFixed(1) + "ms") : "—";
    var sessions = sessionSet.size;
    // PET-138: "bypassed (disarmed)" total — sum of the dedicated per-session
    // accumulator (NOT recomputed from the buffer, so it survives row eviction).
    var bypassed = Pet.bypassTotal();
    // PET-165: "self-tamper" total — the server-authoritative lifetime count adopted from
    // /health and live-incremented over SSE, NOT recomputed from the buffer. A buffer-scoped
    // count would silently decay to 0 once 500 ordinary scans evicted the tamper rows, and
    // the highest-stakes signal is precisely the one that must not decay.
    var selfmodTotal = Number(Pet.state.selfmodTotal) || 0;

    // PET-165: wrap instead of crushing. Six tiles at flex:"1" squeezed the eyebrow
    // labels until "BYPASSED (DISARMED)" wrapped and its value dropped out of line with
    // its neighbours below ~1000px. A 170px basis is wide enough for the longest label
    // on one line, so the row reflows into two tidy rows rather than degrading in place.
    var metricsRow = Pet.h("div", { style: { display: "flex", gap: "10px", flexWrap: "wrap" } });
    // Lean metric cells (not four identical icon-panels): an eyebrow label over a
    // value. `blocked` carries severity weight when > 0 so the one security-load-
    // bearing number stands out instead of looking like `sessions`.
    // PET-165: `opts.tone` selects WHICH alert palette. `blocked` keeps crit red;
    // self-tamper takes amber, because PET-164 fixed amber as the self-tamper channel
    // colour precisely so red stays reserved for actual blocks. Two identically-red
    // tiles would read as the same severity when they are not: `blocked` is routine
    // enforcement over the buffered window, self-tamper is the guarded thing attacking
    // the guard. `opts.help` hangs a HelpTip off the label for tiles whose counting
    // scale is not obvious from the number alone.
    var valueTile = function (label, value, alert, opts) {
      opts = opts || {};
      var hue = opts.tone === "amber" ? "var(--amber)" : "var(--crit)";
      var soft = opts.tone === "amber" ? "var(--amber-soft)" : "var(--crit-soft)";
      var head = Pet.h("div", { style: { display: "flex", alignItems: "center", gap: "5px", minHeight: "15px" } },
        Pet.h("div", { className: "eyebrow" }, label)
      );
      if (opts.help) head.appendChild(opts.help);
      return Pet.h("div", {
        style: {
          flex: "1 1 170px", minWidth: "0", borderRadius: "var(--r-panel)", padding: "12px 14px",
          background: alert ? soft : "var(--bg-panel)",
          border: "1px solid " + (alert ? hue : "var(--border)")
        }
      },
        head,
        Pet.h("div", { className: "num", style: { fontSize: "26px", marginTop: "4px", color: alert ? hue : "var(--tx-bright)" } }, String(value))
      );
    };
    metricsRow.appendChild(valueTile("scans", scans, false));
    metricsRow.appendChild(valueTile("blocked", blocked, blocked > 0));
    metricsRow.appendChild(valueTile("avg latency", avgLatency, false));
    metricsRow.appendChild(valueTile("sessions", sessions, false));
    metricsRow.appendChild(valueTile("bypassed (disarmed)", bypassed, false));
    // PET-165: alert styling whenever nonzero, in amber (see valueTile). Sits last,
    // beside `bypassed (disarmed)`: those two are the only lifetime, eviction-proof
    // counters in the row, so the buffer-scoped four read as a block and the two
    // differently-scaled ones are neighbours rather than scattered among them. The
    // HelpTip carries the scale, since a bare number cannot say which window it counts.
    // PET-166 (D8): under a foreign scope the tile keeps its value and RELABELS to
    // name the binding it counts (a lifetime fact about the process actually
    // enforcing); the HelpTip is amended in the same seam because "the scan history
    // below" is another profile's file there.
    var selfmodView = Pet.selfmodTileLabel(Pet.isForeignScope());
    metricsRow.appendChild(valueTile(selfmodView.label, selfmodTotal, selfmodTotal > 0, {
      tone: "amber",
      help: Pet.HelpTip(selfmodView.help),
    }));
    wrapper.appendChild(metricsRow);

    // Scanner health
    var healthPanel = Pet.Panel({
      icon: "radar", title: "scanner health", place: "loaded backends", flush: true,
      help: Pet.HelpTip(Pet.SCANNER_HEALTH_HELP),
      // PET-127: keep this padding:12px div as the stable paint target in both
      // branches — the resolve/error arms find it via [style*='padding: 12px'].
      // Only <inner> changes: skeleton while !Pet._runtime.healthLoaded, cached rows once a
      // /health response has settled (so steady-state SSE frames show no skeleton).
      // The role=status wrapper carries NO padding:12px, so the outer div stays the
      // unique [style*='padding: 12px'] match.
      content: Pet.h("div", { style: { padding: "12px" } },
        Pet._runtime.healthLoaded
          ? Pet.scannerHealthRows(Pet.state.scannerHealth)
          : Pet.h("div", { role: "status", ariaBusy: true, ariaLabel: "Loading scanner status" },
              Pet.skelRows(3, { h: "16px" }))
      ),
    });
    wrapper.appendChild(healthPanel);

    // PET-157: integrity diagnostic panel, sibling to scanner health. Renders the additive
    // get_health `integrity` field so config skew (sig-missing/sig-mismatch) is distinguishable
    // from a genuine state and a key-off deployment, from the dashboard alone. A separate panel
    // (not patched in place by the cold-mount getHealth settle below); refreshes on the next
    // startPolling tick (<=10s) and on first paint — bounded, display-only staleness (D8 / F-1).
    var integrityPanel = Pet.Panel({
      icon: "shieldCheck", title: "integrity", place: "spool provenance", flush: true,
      content: Pet.h("div", { style: { padding: "12px" } },
        Pet.integrityRows(Pet.state.integrityHealth)
      ),
    });
    wrapper.appendChild(integrityPanel);

    // Scan history — PET-148 back-pages. The live head renders the SSE-maintained ≤500
    // buffer with the PET-144 "last N of M" subtitle; paged-back views render fetched older
    // pages with a positional (no-total) label and Older/Newer controls (D-RESTART/D-PAGING).
    var histAtHead = Pet.state.historyAtHead !== false;
    var histStack = Pet.state.historyStack || [];
    var histPaged = (!histAtHead && histStack.length) ? histStack[histStack.length - 1] : null;
    // PET-165: the row filter narrows the LIVE HEAD only. A paged-back view is a slice of
    // older history, so filtering it would present "the self-tamper events in this page" as
    // "the self-tamper events"; paged views therefore always render unfiltered and the
    // control reads its on-state from the effective filter below.
    var histFilter = (Pet.state.historyFilter === "selfmod") ? "selfmod" : "all";
    var histEffFilter = histPaged ? "all" : histFilter;
    var histRowsData = histPaged
      ? (Array.isArray(histPaged.entries) ? histPaged.entries : [])
      : Pet.filterHistoryRows(hist, histEffFilter);
    // PET-166 (D19): the WHOLE history panel reads one source — the scan-history
    // payload's own scope copy — never Pet.state.readScope, whose health-poll writer
    // can land first after a switch and would paint "no scans retained for beta"
    // over a buffer D17 just emptied.
    var histForeign = Pet.isForeignScope(Pet.state.historyReadScope);
    var histProfileName = histForeign && Pet.state.historyReadScope && Pet.state.historyReadScope.selected
      ? String(Pet.state.historyReadScope.selected) : "";
    // D12: the age label is computed over the UNFILTERED head buffer, never the
    // filtered rows (a fresh profile with no selfmod rows must not read stale), and
    // it is head-only (a back-page is older than the head by construction).
    var histAge = histPaged ? null : Pet.scanHistoryAge(hist);
    // PET-166 (D12): four-state subtitle selector. paged+equipped -> the positional
    // page label (unchanged); paged+foreign -> the scoped seam with the page label
    // as body (the view reaching furthest into another profile's data must say
    // whose it is); head+foreign -> the scoped seam with the count as body (no
    // "of N" — we have no lifetime count for a process we are not); head+equipped ->
    // the shipped seam, with the age clause appended at the render site so its
    // two-argument signature stays untouched.
    var histFilterOn = histEffFilter === "selfmod";
    var histSubtitle;
    if (histPaged) {
      histSubtitle = histForeign
        ? Pet.scopedHistorySubtitle(Pet.historyPageLabel(histPaged), histProfileName, null, false, histFilterOn)
        : Pet.historyPageLabel(histPaged);
    } else if (histForeign) {
      histSubtitle = Pet.scopedHistorySubtitle(
        "showing last " + hist.length, histProfileName,
        histAge && histAge.label, !!(histAge && histAge.stale), histFilterOn
      );
    } else {
      histSubtitle = Pet.scanHistorySubtitle(
        hist.length,
        Pet.state.pipelineHealth && Pet.state.pipelineHealth.scans_total
      );
      if (histAge) histSubtitle = histSubtitle + " · " + histAge.label + (histAge.stale ? " · stale" : "");
    }
    // PET-165: the filter APPENDS to the subtitle, never rewrites it. The counts stay the
    // unfiltered window's (so "showing last 500 of 1200" keeps meaning what PET-144 made
    // it mean), but a list showing 2 of 500 buffered rows under a bare "recent evaluations"
    // would misdescribe itself. One trailing clause fixes that without minting a second,
    // filter-scoped total the operator would have to reconcile against the tile.
    // PET-166 (D12): SKIPPED on the scopedHistorySubtitle arms — the seam emits the
    // clause itself from filterOn, so appending here would render it twice.
    if (histFilterOn && !histForeign) histSubtitle = histSubtitle + " · self-tamper only";
    // PET-152: "Older" is offered when an older cursor exists (the paged view's next_before) or,
    // off the live head, when scanHistoryHasOlder reports retained rows older than the live window
    // — gated on the SAME lifetime scans_total the subtitle reads on the equipped branch; a
    // non-equipped scope reads the server's has_older (PET-166 D12) — never a cached seed
    // cursor that goes stale after ring eviction. "Newer" only when paged back.
    var histCanOlder = histPaged
      ? (histPaged.nextBefore != null)                       // shipped paged arm, unchanged
      : Pet.isForeignScope(Pet.state.historyReadScope)       // D19: the panel's own scope copy
        ? Pet.scopedHistoryHasOlder(hist.length, Pet.state.historyHasOlder)
        : Pet.scanHistoryHasOlder(
            hist.length,
            Pet.state.pipelineHealth && Pet.state.pipelineHealth.scans_total
          );

    // PET-152: the "Older"/"Newer" handlers are now module-scoped (Pet.pageHistoryOlder /
    // Pet.pageHistoryNewer), defined once rather than rebuilt per render so they provably share
    // the one Pet._runtime.historyPaging in-flight binding and are unit-testable end-to-end.
    var histControls = Pet.h("div", { style: { display: "flex", gap: "8px", marginTop: "10px", alignItems: "center" } });
    if (histCanOlder) {
      histControls.appendChild(Pet.h("button", {
        className: "btn btn-ghost btn-sm", type: "button",
        ariaLabel: "Show older scan history", onClick: Pet.pageHistoryOlder,
      }, "Older"));
    }
    if (!histAtHead) {
      histControls.appendChild(Pet.h("button", {
        className: "btn btn-ghost btn-sm", type: "button",
        ariaLabel: "Show newer scan history", onClick: Pet.pageHistoryNewer,
      }, "Newer"));
    }
    // Body: rows for the active view, or the empty-state ladder (PET-166 D12 —
    // PET-165's arm order preserved exactly, scope-aware copy inside, one new arm
    // for the foreign nothing-retained state; the seam owns the copy so tests/js
    // can drive the full matrix without renderDashboard).
    var histBody;
    var histEmpty = Pet.historyEmptyState(hist, histRowsData, histPaged, histEffFilter, histForeign, histProfileName);
    if (histEmpty) {
      histBody = Pet.h("div", { className: "mono", style: { color: "var(--tx-faint)", fontSize: "12px" } }, histEmpty.text);
    } else {
      histBody = Pet.scanHistoryRows(histRowsData);
    }

    // PET-165: the one history filter dimension (no filter framework). Reuses the existing
    // .seg segmented primitive (PET-122/PET-124) so it inherits the shipped focus-visible and
    // on-state styling; seg-sm is the only new CSS, sizing it for the 38px panel head.
    var histFilterSeg = Pet.h("div", { className: "seg seg-sm", role: "radiogroup", ariaLabel: "Scan history filter" });
    histFilterSeg.appendChild(Pet.h("button", {
      className: histEffFilter === "all" ? "on" : "", type: "button", role: "radio",
      ariaChecked: histEffFilter === "all",
      onClick: function () { Pet.setHistoryFilter("all"); },
    }, "all"));
    // The active self-tamper segment takes the amber alert treatment (seg-alert), so the
    // one moment this control is loud is the one moment it is actually withholding rows.
    histFilterSeg.appendChild(Pet.h("button", {
      className: histEffFilter === "selfmod" ? "on seg-alert" : "", type: "button", role: "radio",
      ariaChecked: histEffFilter === "selfmod",
      onClick: function () { Pet.setHistoryFilter("selfmod"); },
    }, "self-tamper"));

    var historyPanel = Pet.Panel({
      icon: "list", title: "scan history", flush: true,
      // PET-144/PET-148: lifetime "last N of M" at the head; a positional label when paged.
      // PET-165: the subtitle reads the UNFILTERED buffered length, so filtering never
      // rewrites the eviction headline into a false "showing last 3 of N".
      place: histSubtitle,
      right: histFilterSeg,
      // PET-166 (D3): the spool retention notice rides the shipped HelpTip (the
      // established idiom for a scope/scale disclosure) rather than a new note element.
      help: Pet.HelpTip("<b>Scan History</b>: recent pipeline scans with severity, direction, and timing. Each row is one <code>Pipeline.evaluate()</code> call. <b>Older</b>/<b>Newer</b> page through retained history beyond the live window."
        + (histForeign && Pet.state.spoolTruncated
          ? " Older enforcement events for this profile were not read (spool exceeds the read cap)."
          : "")),
      content: Pet.h("div", { style: { padding: "12px" } }, histBody, histControls),
    });
    wrapper.appendChild(historyPanel);

    container.appendChild(wrapper);

    // PET-111: fetch the authoritative armed bit once per obs ENTRY (guarded by
    // Pet._runtime.armedSeeded — reset in mount/unmount/switchTab→obs) — never on every
    // SSE/poll re-render. Skip while a write is in flight so it can't clobber an
    // optimistic value; paintBanner re-queries the live node. The !scopeError arm:
    // a profile 422 resets the latch below (the bit was never read for that scope)
    // and paints scopeError BEFORE its re-render, so this gate is what keeps the
    // error re-render from re-fetching in a loop; the re-seed runs once a 200 on
    // any scoped surface clears the error.
    if (!Pet._runtime.armedSeeded && !Pet._runtime.armedBusy && !Pet.state.scopeError) {
      Pet._runtime.armedSeeded = true;
      var _armedGen = Pet._runtime.scopeGen; // PET-166 D17: captured at send time
      Pet.api.getArmed().then(function (d) {
        if (Pet.auth.on401(d)) return; // PET-129 D3/§1: first statement; a 401 here must not be read as armed
        if (_armedGen !== Pet._runtime.scopeGen) { Pet._runtime.armedSeeded = false; return; } // superseded scope: leave un-seeded for the new scope's render
        if (Pet.isProfile422(d)) {
          // PET-166 D7: the coherent error state; never leave the prior bit painted
          // as this profile's (the guard below would silently drop the 422). The
          // latch resets so the bit is re-read once the 422 clears — without this
          // the banner keeps the previous scope's enforcement state for the rest
          // of the scope (only mount/unmount/_invalidateScopeState reset it).
          Pet._runtime.armedSeeded = false;
          var _e0 = d.detail.filter(function (x) { return x && x.field === "profile"; })[0];
          Pet.state.scopeError = { surface: "armed", message: (_e0 && _e0.message) || "profile not found" };
          if (Pet.state.tab === "obs" && Pet._runtime.container) Pet.renderDashboard(Pet._runtime.container);
          return;
        }
        if (Pet._runtime.armedBusy) return;
        Pet._scope.adoptRead(d); // PET-166 D19: armed 200s are a readScope writer
        if (d && !d.error && typeof d.armed === "boolean") {
          Pet.state.armed = d.armed;
          paintBanner();
        }
      });
    }

    // Fetch initial data and render scanner health
    var _healthGen = Pet._runtime.scopeGen; // PET-166 D17: captured at send time
    Pet.api.getHealth().then(function (d) {
      if (Pet.auth.on401(d)) return; // PET-129 D3/§1: first statement, before the Pet._runtime.healthLoaded flip / shape gate
      if (_healthGen !== Pet._runtime.scopeGen) return; // PET-166: superseded scope
      if (Pet.isProfile422(d)) {
        // PET-166 D7: a 422 body carries no `error`, so without this the shape gate
        // below would wipe scannerHealth/pipelineHealth/integrityHealth every render.
        var _e0 = d.detail.filter(function (x) { return x && x.field === "profile"; })[0];
        Pet.state.scopeError = { surface: "health", message: (_e0 && _e0.message) || "profile not found" };
        if (Pet.state.tab === "obs" && Pet._runtime.container) Pet.renderDashboard(Pet._runtime.container);
        return;
      }
      Pet._runtime.healthLoaded = true;  // PET-127: settled (either arm) -> stop painting the skeleton
      if (!d.error) {
        Pet._scope.adoptRead(d); // PET-166 D19: health 200s are a readScope writer
        // PET-144: capture BEFORE the assignment whether this settle is the first to
        // populate pipelineHealth, so the cold-mount re-render below fires on the
        // null->set transition only.
        var hadHealth = Pet.state.pipelineHealth !== null;
        Pet.state.scannerHealth = d.scanners || [];
        Pet.state.pipelineHealth = d.pipeline || null;
        Pet.state.integrityHealth = d.integrity || null; // PET-157: mirror pipelineHealth (cold-mount settle)
        Pet.adoptSelfmodTotal(Pet.state.pipelineHealth); // PET-165: seed the tile count on cold mount
        var rows = Pet.scannerHealthRows(Pet.state.scannerHealth);
        var contentEl = healthPanel.querySelector("[style*='padding: 12px']") || healthPanel.querySelector("div > div");
        if (contentEl) { contentEl.innerHTML = ""; contentEl.appendChild(rows); }
        // PET-144 cold-mount: this in-render fetch only patches the scanner-health
        // panel above; the scan-history subtitle ("showing last N of M") is computed
        // from scans_total at render time. On a cold mount against an already-evicting
        // ring it would otherwise read "recent evaluations" until the first 10s poll.
        // Re-render once so the honest label appears on first paint. The transition
        // guard is load-bearing: this getHealth() fetch runs on EVERY renderDashboard
        // (unlike the timer-gated poll :533 / one-shot seed :1190), so an
        // unconditional re-render here would re-invoke the fetch without bound.
        if (!hadHealth && Pet.state.pipelineHealth && Pet.state.tab === "obs" && Pet._runtime.container) {
          Pet.renderDashboard(Pet._runtime.container);
        }
      } else {
        var contentEl = healthPanel.querySelector("[style*='padding: 12px']") || healthPanel.querySelector("div > div");
        if (contentEl) {
          contentEl.innerHTML = "";
          contentEl.appendChild(Pet.h("div", { className: "mono", style: { color: "var(--tx-faint)", fontSize: "12px" } }, "scanner status unavailable: health fetch failed"));
        }
      }
    });

    // ── One-shot seed of the server's pre-existing ring buffer (Decision 5) ──
    // On the SSE-healthy path Pet.state.scanHistory only fills from NEW events,
    // so a console opened against an already-populated buffer would look dead
    // until the next scan. Seed once per mount: fetch /scan-history, merge
    // dedup-by-scan_id (append unseen, no re-sort — keeps most-recent-first),
    // then re-render. The guard is set BEFORE the async call so concurrent
    // SSE-driven re-renders don't restart the fetch; it is reset only in
    // mount/unmount (never switchTab), so an obs→other→obs round-trip reuses
    // the SSE-maintained buffer rather than re-seeding.
    if (!Pet._runtime.historySeeded && !Pet.state.scopeError) { // !scopeError: same anti-loop arm as the armed seed above
      Pet._runtime.historySeeded = true;
      // PET-148: every (re-)seed starts at the live head — drop any paged-back state from a
      // prior mount/profile (a `before` cursor is only meaningful within its own profile).
      Pet.state.historyAtHead = true;
      Pet.state.historyStack = [];
      var _seedGen = Pet._runtime.scopeGen; // PET-166 D17: captured at send time
      Pet.api.getScanHistory(500).then(function (d) {
        if (Pet.auth.on401(d)) return; // PET-129 D3/§1: first statement, before the shape-guarded seed-merge
        if (_seedGen !== Pet._runtime.scopeGen) { Pet._runtime.historySeeded = false; return; } // PET-166: superseded scope
        if (Pet._scope.guardHistory(d)) { Pet._runtime.historySeeded = false; return; } // PET-166 D7; un-latch so the seed re-runs once the 422 clears
        // startFallbackPolling response-shape guard, NOT the bare !d.error check:
        // _req never rejects on HTTP error (it resolves an error envelope), and a
        // 200 {} body lacking .entries would make the merge throw on .scan_id.
        if (!d.error && d.entries && Array.isArray(d.entries)) {
          Pet._scope.adoptHistory(d); // PET-166 D19: the mount seed is a writer site
          // PET-148/PET-152: the seed merges the live-head window but no longer captures a head
          // cursor. PET-152 dropped that cached cursor: it went stale once the ring evicted past
          // the oldest seeded row, so the first "Older" click skipped the band between the current
          // oldest buffered row and the stale boundary. The head boundary is now re-minted per
          // head->older transition (Pet.pageHistoryOlder), never cached across evictions (edge F-4
          // still holds: that re-mint is a server round-trip, never a client-derived token).
          // PET-99 D6/D9: shape-guarded seed-merge (skips non-object entries on
          // both sides before reading .scan_id) — replaces the inline dedup loops.
          Pet.mergeScanHistory(Pet.state.scanHistory, d.entries);
          Pet.accrueBypass(d.entries); // PET-138: seed bypass counts from the pre-existing buffer
          if (Pet.state.tab === "obs" && Pet._runtime.container) Pet.renderDashboard(Pet._runtime.container);
        }
      });
    }
  };


  Pet._moduleState.last = "dashboard";
})();
