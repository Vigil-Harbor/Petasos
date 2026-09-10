/* Owns: About, paging, tabs, mount/unmount, connection painters, and final readiness. Depends on: core, transport, observability, dashboard, playground, and config. */
(function () {
  "use strict";
  var Pet = window.__PETASOS_CONSOLE__;
  var actual = Pet && Pet._moduleState ? Pet._moduleState.last : "missing";
  if (actual !== "config") throw new Error("petasos-shell expected module config, got " + actual);

  Pet.renderAbout = function (container) {
    container.innerHTML = "";
    var wrapper = Pet.h("div", { style: { display: "flex", flexDirection: "column", gap: "14px", maxWidth: "600px" } });

    // Header
    wrapper.appendChild(Pet.Panel({
      icon: "shieldCheck", title: "Petasos",
      content: Pet.h("div", {},
        Pet.h("div", { style: { fontSize: "15px", color: "var(--tx-bright)", fontWeight: "700" } }, "Petasos"),
        // PET-127: text-independent [data-pet-ver] anchor (retires the .mono + "v..."
        // text-coupled selector). Seeds a skeleton bar + aria-busy/aria-label; the
        // fill below repopulates it in place (so NO role=status here — see Decision 4).
        Pet.h("div", { className: "mono", dataset: { petVer: "1" }, ariaBusy: true, ariaLabel: "Loading version",
                       style: { fontSize: "11px", color: "var(--tx-faint)", marginTop: "4px" } },
          Pet.skel(48, 11)),
        Pet.h("span", { className: "pill ok", style: { marginTop: "8px", height: "18px", fontSize: "10px" } }, "MIT License"),
        Pet.h("p", { style: { fontSize: "13px", color: "var(--tx-mut)", lineHeight: "1.6", margin: "12px 0 0", maxWidth: "440px" } },
          "Thank you for checking out the plugin! It is my hope that it helps extend trust to your agents, and assists you in enforcing your guardrails.",
          Pet.h("br"),
          "May your Hermes Agent travel long and well."
        )
      ),
    }));

    // Links
    wrapper.appendChild(Pet.Panel({
      icon: "flow", title: "Links",
      content: Pet.h("div", {},
        Pet.h("a", { href: "https://github.com/Vigil-Harbor/Petasos", target: "_blank", rel: "noopener", className: "link", style: { display: "block", padding: "6px 0" } }, "Repository"),
        Pet.h("a", { href: "https://github.com/Vigil-Harbor/Petasos/issues", target: "_blank", rel: "noopener", className: "link", style: { display: "block", padding: "6px 0" } }, "Issue Tracker"),
        Pet.h("a", { href: "https://github.com/Vigil-Harbor/Petasos/blob/master/docs/usage/scanners.md", target: "_blank", rel: "noopener", className: "link", style: { display: "block", padding: "6px 0" } }, "Scanner Reference"),
        Pet.h("a", { href: "https://github.com/Vigil-Harbor/Petasos/blob/master/docs/usage/configuration.md", target: "_blank", rel: "noopener", className: "link", style: { display: "block", padding: "6px 0" } }, "Configuration Guide")
      ),
    }));

    // Donation
    wrapper.appendChild(Pet.Panel({
      icon: "caduceus", title: "Support",
      help: Pet.HelpTip("<b>Support</b>: Petasos is free and open source (MIT). Sponsorship helps fund continued development but unlocks nothing; every feature is available to everyone."),
      style: { border: "1px solid rgba(232,144,28,.3)" },
      bodyStyle: { background: "rgba(232,144,28,.06)" },
      content: Pet.h("div", { style: { textAlign: "center", padding: "12px 0" } },
        Pet.h("img", { className: "support-coffee", src: Pet.asset("img/coffee.webp"), alt: "A robot enjoying a hot cup of coffee" }),
        Pet.h("div", { style: { fontSize: "15px", fontWeight: "700", color: "var(--tx-bright)", marginBottom: "8px" } }, "Did Petasos prevent a disaster?"),
        Pet.h("div", { style: { fontSize: "13px", color: "var(--tx-mut)", lineHeight: "1.6", maxWidth: "400px", margin: "0 auto 16px" } },
          "Every feature is free, forever.",
          Pet.h("br"),
          "If this saved your team from a bad day, a coffee keeps the lights on."
        ),
        Pet.h("a", { href: "https://github.com/sponsors/Vigil-Harbor", target: "_blank", rel: "noopener", className: "btn btn-primary", style: { textDecoration: "none", display: "inline-flex" } },
          Pet.Icon("caduceus"), " Buy us a coffee"
        )
      ),
    }));

    // Credits
    wrapper.appendChild(Pet.Panel({
      icon: "user", title: "Credits",
      content: Pet.h("div", { className: "mono", style: { fontSize: "11px", color: "var(--tx-faint)", lineHeight: "1.8" } },
        Pet.h("div", {}, "Vigil Harbor (maintainer)"),
        Pet.h("div", {}, "Built with FastAPI, Python, vanilla JS"),
        Pet.h("a", { href: "https://x.com/vigilharbor", target: "_blank", rel: "noopener", className: "link", style: { display: "block", padding: "4px 0" } }, "X: @vigilharbor"),
        Pet.h("a", { href: "https://github.com/ziomancer", target: "_blank", rel: "noopener", className: "link", style: { display: "block", padding: "4px 0" } }, "GitHub: @ziomancer")
      ),
    }));

    container.appendChild(wrapper);

    // Fill version from API. PET-127: select the text-independent [data-pet-ver]
    // anchor, tear down the skeleton, and route success / {error} / malformed-200
    // (a 200 with no version) through the same innerHTML="" + remove(aria-busy) tail
    // so the skeleton can never spin forever (fixes the old "v..." stuck-on-failure
    // flash). Pet.state.about is set only when a real version is present (it is
    // currently write-only/unread, so narrowing the assignment is inert).
    Pet.api.getAbout().then(function (d) {
      var verEl = container.querySelector("[data-pet-ver]");
      if (!verEl) return;
      verEl.innerHTML = "";
      if (d && !d.error && d.version != null) {
        Pet.state.about = d;
        verEl.appendChild(document.createTextNode("v" + d.version));
      } else {
        verEl.appendChild(document.createTextNode("version unavailable"));
      }
      verEl.removeAttribute("aria-busy");
    });
  };

  // ── Tab controller ──

  var _tabStrip = null;
  var _connStatus = null;  // PET-13: LIVE/POLLING blip node in the pane header (persistent; not rebuilt per frame)
  var _liveRegion = null;  // PET-13: visually-hidden aria-live region; announces the newest scan verdict to AT
  // PET-102: one-shot guard so the dashboard seeds the server's pre-existing
  // scan-history ring buffer exactly once per mount (not on every SSE re-render).
  // Reset in Pet.unmount AND at the top of Pet.mount (double-mount hardening).
  // PET-148/PET-152: in-flight guard for scan-history paging. PET-152 extracted the
  // pageHistoryOlder/pageHistoryNewer handlers to module scope (Pet.pageHistoryOlder /
  // Pet.pageHistoryNewer), so they are now defined ONCE and provably share this one binding
  // rather than being rebuilt per renderDashboard. It ignores re-entrant clicks while a
  // getScanHistory fetch is pending — including across the PET-152 two-fetch re-mint chain —
  // so two quick clicks can't fetch the same cursor twice, and an in-flight "Older" re-mint
  // blocks a "Newer" click that would otherwise pop the cursor that pending .then is about to
  // push from (the :1667-style non-contiguous-page hazard).
  // PET-152: paging generation. Bumped at every paging-context teardown (_enterAuthRequired,
  // _resume, Pet.mount, Pet.unmount — beside each Pet._runtime.historySeeded = false) and captured by each
  // handler at entry; every fetch .then/.catch checks it before mutating, so a two-fetch re-mint
  // chain that outlives a re-seed / 401 / unmount / profile-switch cannot push a stale older page
  // onto a freshly-reset stack or flip historyAtHead. Mirrors the Pet.auth._gen stale-read guard.
  // PET-152: one-shot tripwire flag for the re-mint divergence (the gate offered "Older" because
  // scans_total > buffered, yet the head re-mint returned no cursor). Set once per console-JS load
  // and intentionally NOT reset at teardown — it is a structural-defect signal, not a per-session
  // one (matches the server one-shot WARNING _ring_overflow_warned at server.py:609).
  var _remintMissWarned = false;

  // PET-152: one-shot console.warn naming the re-mint divergence. The "Older" gate keyed on the
  // lifetime scans_total promised older rows exist, but the head re-mint came back with no cursor
  // (ring empty / error, or everything beyond the ring already rotated out). Surfacing it once
  // turns a would-be silent dead click into an operator-visible signal.
  function _warnRemintMiss() {
    if (_remintMissWarned) return;
    _remintMissWarned = true;
    if (typeof console !== "undefined" && console && console.warn) {
      console.warn(
        "[petasos] scan-history: re-mint returned no cursor while scans_total exceeded the " +
        "buffered window; landing on the retention-honest empty state. Rows older than the live " +
        "window are unreachable (aged out of retention, or the live ring is empty)."
      );
    }
  }

  // PET-152: a history fetch counts as a successful read only when it has no error AND no non-OK
  // HTTP status. _req (:530, :550) sets `_status` on a parsed non-OK body, which for a 403/500 like
  // `{}` carries NO `error` field — so a bare `!d.error` check would accept a failed read as an
  // empty older page (silent "no older history" on an auth/server failure). Gate paging on this
  // instead. `_status == null` covers OK bodies (status never stamped) and the test mocks.
  function _historyResponseOk(d) {
    return !!(d && !d.error && (d._status == null || d._status < 400));
  }

  // PET-152: the single shared push for an older page — both the re-mint path and the paged-view
  // path call it, so the shape guard and render trigger live in one place. Module-scoped (never a
  // render-local) because it needs Pet._runtime.container / Pet.renderDashboard. Keeps the Array.isArray shape
  // guard so a 200 {} / { entries: null } body lands on the honest empty state instead of throwing
  // on .scan_id (carried from the seed-merge hazard at :1778-1780).
  function _pushOlderPage(cursor, d) {
    Pet.state.historyAtHead = false;
    var st = Pet.state.historyStack || (Pet.state.historyStack = []);
    st.push({
      entries: (d && Array.isArray(d.entries)) ? d.entries : [],
      cursor: cursor,
      nextBefore: (d && d.next_before) || null,
      olderTruncated: !!(d && d.older_truncated),
    });
    if (Pet.state.tab === "obs" && Pet._runtime.container) Pet.renderDashboard(Pet._runtime.container);
  }

  // PET-152: "Older" handler. Reads Pet.state fresh at click time, captures the paging
  // generation, asks the reducer for a plan, and runs the two-fetch re-mint off the live head:
  // fetch-1 (limit = runtime buffer length, `before` absent) re-mints the head boundary off the
  // in-memory ring; fetch-2 (`before` = freshCursor) pages into the on-disk sink. The two fetches
  // read two different stores (server.py:1219-1235), so ring-then-sink is the only shape that can
  // mint a current head boundary AND then reach the sink. The Pet._runtime.historyPaging guard stays set
  // across BOTH fetches and is cleared on every terminal path; each .then/.catch first checks the
  // captured generation so a chain that outlives a re-seed / 401 / unmount drops without mutating.
  Pet.pageHistoryOlder = function () {
    if (Pet._runtime.historyPaging) return; // ignore re-entrant clicks while a fetch is in flight
    var gen = Pet._runtime.historyPagingGen; // F-2: capture; teardown bumps this
    var plan = Pet.historyPagingView(
      {
        atHead: Pet.state.historyAtHead !== false,
        stack: Pet.state.historyStack || [],
        bufferLength: (Pet.state.scanHistory || []).length,
      },
      "older"
    );
    if (plan.needsRemint) {
      Pet._runtime.historyPaging = true;
      Pet.api.getScanHistory(plan.remintLimit).then(function (rd) {
        if (gen !== Pet._runtime.historyPagingGen) return;          // superseded by re-seed/401/unmount
        if (Pet.auth.on401(rd)) { Pet._runtime.historyPaging = false; return; }
        if (!_historyResponseOk(rd)) { Pet._runtime.historyPaging = false; return; } // non-OK re-mint: not a miss, a failed read
        var freshCursor = rd.next_before || null;
        if (freshCursor == null) {                      // gate said older exist, ring points nowhere
          Pet._runtime.historyPaging = false;
          _pushOlderPage(null, { entries: [], older_truncated: true }); // honest empty (E-6)
          _warnRemintMiss();                            // one-shot tripwire (E-6)
          return;
        }
        return Pet.api.getScanHistory(100, freshCursor).then(function (d) {
          if (gen !== Pet._runtime.historyPagingGen) return;
          Pet._runtime.historyPaging = false;
          if (Pet.auth.on401(d)) return;
          if (_historyResponseOk(d)) { _pushOlderPage(freshCursor, d); }
        });
      }).catch(function () { if (gen === Pet._runtime.historyPagingGen) Pet._runtime.historyPaging = false; });
      return;
    }
    if (!plan.needsFetch) return; // paged view at the retained bottom (flag stays clear)
    Pet._runtime.historyPaging = true;
    Pet.api.getScanHistory(100, plan.cursor).then(function (d) {
      if (gen !== Pet._runtime.historyPagingGen) return;
      Pet._runtime.historyPaging = false; // clear before any early return so paging can resume
      if (Pet.auth.on401(d)) return; // a 401 stops paging, never a stale page
      if (_historyResponseOk(d)) { _pushOlderPage(plan.cursor, d); }
    }).catch(function () { if (gen === Pet._runtime.historyPagingGen) Pet._runtime.historyPaging = false; });
  };

  // PET-152: "Newer" handler — relocated to module scope, behavior byte-identical to the former
  // render-local closure (D-PAGING: client-buffered stack pop, no fetch), so it provably shares
  // the one Pet._runtime.historyPaging binding with pageHistoryOlder. Same in-flight guard: while an "Older"
  // fetch is pending, a synchronous stack pop here would invalidate the cursor that pending .then
  // is about to push from, appending a non-contiguous page and breaking Older/Newer adjacency.
  Pet.pageHistoryNewer = function () {
    if (Pet._runtime.historyPaging) return;
    var next = Pet.historyPagingView(
      { atHead: Pet.state.historyAtHead !== false, stack: Pet.state.historyStack || [] },
      "newer"
    );
    Pet.state.historyAtHead = next.atHead;
    Pet.state.historyStack = next.stack;
    if (Pet.state.tab === "obs" && Pet._runtime.container) Pet.renderDashboard(Pet._runtime.container);
  };
  // PET-127: gate the scanner-health skeleton. renderDashboard re-runs on every
  // SSE/poll frame, so an unconditional skeleton would re-flash; this flips true
  // at every /health settle (in-render success+error arms AND the 10s poll), never
  // at paint time, and resets only in mount/unmount (not switchTab) so an
  // obs->other->obs round-trip reuses cached rows. NOT keyed off scannerHealth
  // (inits to [], truthy, and []-length collides with the genuine zero-backends
  // case where scannerHealthRows([]) is a false "unavailable" error).
  // PET-111: Pet._runtime.armedSeeded — fetch the Equipped/Unequipped bit once per obs ENTRY
  // (mount or switchTab→obs), never on every SSE/poll re-render. Pet._runtime.armedBusy — a
  // POST /armed is in flight; suppress concurrent toggles and seed-overwrites.
  // The pending-disarm confirmation is per-view, ephemeral UI intent. Reset it on
  // every tab change, mount, and unmount so a half-finished two-step disarm cannot
  // carry across navigation or remount, and the 4s timer never fires post-teardown.
  Pet._shell.clearArmedConfirm = function () {
    Pet._runtime.armedConfirmPending = false;
    if (Pet._runtime.armedConfirmTimer) { clearTimeout(Pet._runtime.armedConfirmTimer); Pet._runtime.armedConfirmTimer = null; }
  };

  var TABS = [
    { key: "obs", icon: "activity", label: "Observability" },
    { key: "play", icon: "beaker", label: "Scan Playground" },
    { key: "cfg", icon: "sliders", label: "Config Editor" },
    { key: "about", icon: "shieldCheck", label: "About" },
  ];

  Pet.switchTab = function (name) {
    Pet.state.tab = name;
    Pet._shell.clearArmedConfirm();  // a tab change abandons any half-finished two-step disarm
    if (_tabStrip) {
      _tabStrip.querySelectorAll(".tab").forEach(function (t) {
        var active = t.dataset.key === name;
        t.className = "tab" + (active ? " active" : "");
        t.setAttribute("aria-selected", active ? "true" : "false");
        t.tabIndex = active ? 0 : -1;
      });
    }
    if (!Pet._runtime.container) return;
    Pet._runtime.container.innerHTML = "";
    // PET-111: re-fetch the armed bit on each obs ENTRY (armed has no SSE
    // reconciliation, unlike scan history) — but not on every re-render.
    if (name === "obs") { Pet._runtime.armedSeeded = false; Pet.renderDashboard(Pet._runtime.container); }
    else if (name === "play") Pet.renderPlayground(Pet._runtime.container);
    else if (name === "cfg") Pet.renderConfig(Pet._runtime.container);
    else if (name === "about") Pet.renderAbout(Pet._runtime.container);
  };

  Pet.mount = function (el) {
    el.innerHTML = "";
    Pet._runtime.historySeeded = false;  // PET-102: re-seed on a re-mount that skipped unmount (plugin hot-reload)
    Pet._runtime.historyPaging = false; Pet._runtime.historyPagingGen++;  // PET-152: cancel any in-flight paging from a skipped unmount
    Pet._runtime.healthLoaded = false;   // PET-127: re-show the scanner-health skeleton on (re-)mount
    Pet._runtime.armedSeeded = false;    // PET-111: re-fetch the armed bit on (re-)mount
    Pet._shell.clearArmedConfirm();     // drop any stale disarm-confirm + timer from a skipped unmount
    // PET-166 (D17/D19): a re-mount that skipped unmount must not inherit stale scope
    // facts (a foreign readScope from the prior mount would render another profile's
    // name before the first 200 lands).
    Pet._runtime.scopeGen++;
    if (Pet._runtime.scopePollTimer) { clearInterval(Pet._runtime.scopePollTimer); Pet._runtime.scopePollTimer = null; }
    Pet.sse._scopeLive = true;
    Pet.sse._scopeRefusal = null;
    Pet.state.readScope = null;
    Pet.state.historyReadScope = null;
    Pet.state.historyHasOlder = false;
    Pet.state.spoolTruncated = false;
    Pet.state.scopeError = null;
    Pet.state.scopeNotice = false;
    // PET-155: resolve the host profile + arm the switcher observer once per mount, so
    // a sidebar flip is observed even before the Config tab is first opened (§E).
    // attach() is idempotent — it tears down a stale patch left by a skipped unmount.
    Pet.hostProfile.attach();

    // Pane header
    // PET-13: connection-state indicator. The live feed can silently drop from SSE
    // to 10s polling (Pet.sse._enableFallback); this blip is the only signal the
    // operator gets that a quiet dashboard means "polling", not "all clear".
    _connStatus = Pet.h("div", { className: "live", role: "status", ariaLive: "polite", title: "Live updates streaming." },
      Pet.h("span", { className: "blip" }),
      Pet.h("span", { className: "live-label" }, "LIVE")
    );
    var titleRow = Pet.h("div", { className: "pane-titlerow" },
      Pet.h("div", { className: "pane-mark" },
        Pet.h("img", { src: Pet.asset("img/petasos-helmet.png"), alt: "Petasos winged helmet" })
      ),
      Pet.h("div", {},
        Pet.h("div", { className: "pane-name" }, "Petasos"),
        Pet.h("div", { className: "pane-sub" }, "guardrail pipeline")
      ),
      Pet.h("div", { className: "right" }, _connStatus)
    );

    _tabStrip = Pet.h("div", { className: "tabs", role: "tablist", ariaLabel: "Console sections" });
    TABS.forEach(function (t) {
      var isActive = t.key === "obs";
      var tab = Pet.h("div", {
        className: "tab" + (isActive ? " active" : ""), dataset: { key: t.key },
        role: "tab", tabIndex: isActive ? 0 : -1, ariaSelected: isActive ? "true" : "false",
        onClick: function () { Pet.switchTab(t.key); }
      }, Pet.Icon(t.icon), " " + t.label);
      tab.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); Pet.switchTab(t.key); return; }
        if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
          e.preventDefault();
          var keys = TABS.map(function (x) { return x.key; });
          var i = keys.indexOf(t.key);
          var nk = e.key === "ArrowRight" ? keys[(i + 1) % keys.length] : keys[(i - 1 + keys.length) % keys.length];
          Pet.switchTab(nk);
          var nt = _tabStrip && _tabStrip.querySelector('.tab[data-key="' + nk + '"]');
          if (nt) nt.focus();
        }
      });
      _tabStrip.appendChild(tab);
    });

    var paneHead = Pet.h("div", { className: "pane-head" }, titleRow, _tabStrip);
    el.appendChild(paneHead);

    Pet._runtime.container = Pet.h("div", { className: "content" });
    var paneBody = Pet.h("div", { className: "pane-body" }, Pet._runtime.container);
    el.appendChild(paneBody);

    // PET-13: off-screen live region. The dashboard re-renders wholesale on every
    // SSE frame, which AT cannot follow; announce only the newest verdict here.
    _liveRegion = Pet.h("div", { className: "sr-only" });
    _liveRegion.setAttribute("role", "status");
    _liveRegion.setAttribute("aria-live", "polite");
    _liveRegion.setAttribute("aria-atomic", "true");
    el.appendChild(_liveRegion);

    Pet.switchTab("obs");
    Pet.sse.connect();
    Pet._poll.startHealth();
    Pet.updateConnStatus();
  };

  // PET-13: paint the LIVE/POLLING blip from Pet.sse state. Re-queries via the
  // stored node (the pane header is built once per mount, not per SSE frame), so
  // it survives the dashboard's per-frame re-render of Pet._runtime.container.
  Pet.updateConnStatus = function () {
    if (!_connStatus) return;
    // PET-166 (D9): three states in a fixed order — POLLING outranks SCOPED (a dead
    // connection is the more urgent fact), else SCOPED (an idle non-equipped stream
    // or a terminal refusal), else LIVE. The decision is the pure Pet.connChipView
    // seam; this stays the painter.
    var v = Pet.connChipView(
      !!(Pet.sse && Pet.sse._usingFallback),
      !(Pet.sse && Pet.sse._scopeLive === false),
      Pet.sse ? Pet.sse._scopeRefusal : null
    );
    _connStatus.className = v.className;
    var lbl = _connStatus.querySelector(".live-label");
    if (lbl) lbl.textContent = v.label;
    _connStatus.setAttribute("title", v.title);
  };

  // PET-13: push a short message into the off-screen live region for AT.
  Pet.announce = function (msg) {
    if (_liveRegion) _liveRegion.textContent = msg;
  };

  Pet.unmount = function () {
    Pet._runtime.configRenderGen += 1;      // PET-155: supersede any in-flight renderConfig/save continuation so a late /config or PUT resolve can't mutate state after teardown
    Pet.sse.disconnect();
    Pet._poll.stopHealth();
    // PET-166 (D3/D17/D19): stop the scoped poll and reset the payload-derived scope
    // facts on teardown (the D19 reset set is the D17 list AND unmount).
    Pet._runtime.scopeGen++;
    if (Pet._runtime.scopePollTimer) { clearInterval(Pet._runtime.scopePollTimer); Pet._runtime.scopePollTimer = null; }
    Pet.sse._scopeLive = true;
    Pet.sse._scopeRefusal = null;
    Pet.state.readScope = null;
    Pet.state.historyReadScope = null;
    Pet.state.historyHasOlder = false;
    Pet.state.spoolTruncated = false;
    Pet.state.scopeError = null;
    Pet.state.scopeNotice = false;
    Pet.hostProfile.detach();   // PET-155: un-patch history / unsubscribe (§E); idempotent + foreign-safe
    Pet._runtime.container = null;
    _tabStrip = null;
    _connStatus = null;      // PET-13: drop the stale header-blip node
    _liveRegion = null;      // PET-13: drop the stale live-region node
    Pet._runtime.historySeeded = false;  // PET-102: next mount re-seeds the history buffer
    Pet._runtime.historyPaging = false; Pet._runtime.historyPagingGen++;  // PET-152: cancel any in-flight paging re-mint on teardown
    Pet._runtime.healthLoaded = false;   // PET-127: next mount re-shows the scanner-health skeleton
    Pet._runtime.armedSeeded = false;    // PET-111: next mount re-fetches the armed bit
    Pet._shell.clearArmedConfirm();     // clear the pending-disarm confirm + its 4s timer on teardown
  };


  Pet._moduleState.last = "shell";
  Pet._moduleState.ready = true;
})();
