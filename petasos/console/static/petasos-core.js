/* Owns: namespace, assets, DOM/UI primitives, state, internal containers. Depends on: browser window and document. */
(function () {
  "use strict";
  var Pet = {};
  Pet._runtime = {
    container: null,
    scopeGen: 0,
    scopePollTimer: null,
    configRenderGen: 0,
    historySeeded: false,
    historyPaging: false,
    historyPagingGen: 0,
    healthLoaded: false,
    armedSeeded: false,
    armedBusy: false,
    armedConfirmPending: false,
    armedConfirmTimer: null,
  };
  Pet._scope = {};
  Pet._shell = {};

  // Static assets live next to this script (/static/ standalone,
  // /dashboard-plugins/petasos/dist/ inside Hermes) — resolve from the
  // script URL, captured now because currentScript is null in callbacks.
  var _scriptSrc = document.currentScript && document.currentScript.src;
  var _assetBase = _scriptSrc ? _scriptSrc.slice(0, _scriptSrc.lastIndexOf("/") + 1) : "/static/";
  Pet.asset = function (path) { return _assetBase + path; };

  // ── DOM helpers ──

  Pet.h = function (tag, attrs) {
    var el = document.createElement(tag);
    if (attrs) {
      if (attrs.className) el.className = attrs.className;
      if (attrs.style) Object.assign(el.style, attrs.style);
      if (attrs.title) el.title = attrs.title;
      if (attrs.tabIndex != null) el.tabIndex = attrs.tabIndex;
      // PET-114: role / aria-expanded are not plain DOM properties — route them
      // through setAttribute so the collapsible Panel head exposes them. Additive;
      // no existing caller sets them.
      if (attrs.role) el.setAttribute("role", attrs.role);
      if (attrs.ariaExpanded != null) el.setAttribute("aria-expanded", String(attrs.ariaExpanded));
      if (attrs.ariaLabel != null) el.setAttribute("aria-label", String(attrs.ariaLabel));
      if (attrs.ariaSelected != null) el.setAttribute("aria-selected", String(attrs.ariaSelected));
      if (attrs.ariaChecked != null) el.setAttribute("aria-checked", String(attrs.ariaChecked));
      // PET-127: aria-busy (loading-region in flight) + aria-hidden (decorative
      // skeleton bars). Additive; no existing caller sets them.
      if (attrs.ariaBusy != null) el.setAttribute("aria-busy", String(attrs.ariaBusy));
      if (attrs.ariaHidden != null) el.setAttribute("aria-hidden", String(attrs.ariaHidden));
      if (attrs.type) el.type = attrs.type;
      if (attrs.value != null) el.value = attrs.value;
      if (attrs.placeholder) el.placeholder = attrs.placeholder;
      if (attrs.href) el.href = attrs.href;
      if (attrs.target) el.target = attrs.target;
      if (attrs.rel) el.rel = attrs.rel;
      if (attrs.src) el.src = attrs.src;
      if (attrs.alt != null) el.alt = attrs.alt;
      if (attrs.dataset) Object.assign(el.dataset, attrs.dataset);
      Object.keys(attrs).forEach(function (k) {
        if (k.indexOf("on") === 0 && typeof attrs[k] === "function") {
          el.addEventListener(k.slice(2).toLowerCase(), attrs[k]);
        }
      });
    }
    for (var i = 2; i < arguments.length; i++) {
      var child = arguments[i];
      if (child == null || child === false) continue;
      if (Array.isArray(child)) {
        child.forEach(function (c) {
          if (c != null && c !== false) el.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
        });
      } else if (typeof child === "string" || typeof child === "number") {
        el.appendChild(document.createTextNode(String(child)));
      } else {
        el.appendChild(child);
      }
    }
    return el;
  };

  Pet.svg = function (tag, attrs) {
    var el = document.createElementNS("http://www.w3.org/2000/svg", tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        el.setAttribute(k, attrs[k]);
      });
    }
    for (var i = 2; i < arguments.length; i++) {
      var child = arguments[i];
      if (child != null) el.appendChild(child);
    }
    return el;
  };

  // PET-127: skeleton bar. width default "100%", height default "12px" (one text
  // line). Numbers -> px; non-finite / blank -> default. Decorative: aria-hidden
  // so AT skips it (the loading semantic is carried by the role=status wrapper).
  // Pure builder in the Pet.scannerHealthRows / Pet.sectionIntro idiom; never throws.
  Pet.skel = function (w, h) {
    var dim = function (v, dflt) {
      if (typeof v === "number" && isFinite(v)) return v + "px";
      if (typeof v === "string" && v.trim()) return v.trim();
      return dflt;
    };
    return Pet.h("div", {
      className: "skel",
      ariaHidden: true,
      style: { width: dim(w, "100%"), height: dim(h, "12px") },
    });
  };

  // PET-127: n skeleton bars in a column, with a gap. opts.h sets bar height;
  // opts.w the width; opts.gap the spacing. Non-finite / n<1 -> 1 bar; a positive
  // fraction (0<n<1) also clamps to 1 (Math.floor would otherwise drop it to 0,
  // yielding an empty placeholder) — the builder never renders zero bars.
  Pet.skelRows = function (n, opts) {
    opts = opts || {};
    var count = (typeof n === "number" && isFinite(n) && n > 0) ? Math.max(1, Math.floor(n)) : 1;
    var rows = [];
    for (var i = 0; i < count; i++) rows.push(Pet.skel(opts.w, opts.h));
    return Pet.h("div", { style: { display: "flex", flexDirection: "column", gap: (opts.gap || "8px") } }, rows);
  };

  // ── Icons (ported from pcommon.jsx) ──
  var ICONS = {
    activity: "M3 12h4l3 8 4-16 3 8h4",
    shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3z",
    shieldCheck: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3z M9 12l2 2 4-4",
    bolt: "M13 3L4 14h6l-1 7 9-11h-6z",
    user: "M12 13a4 4 0 100-8 4 4 0 000 8z M5 21a7 7 0 0114 0",
    radar: "M12 12l5-3 M12 21a9 9 0 109-9 M12 12a4.5 4.5 0 104.5 4.5",
    list: "M8 6h12 M8 12h12 M8 18h12 M4 6h0 M4 12h0 M4 18h0",
    beaker: "M9 3h6 M10 3v6l-5 9a2 2 0 002 3h10a2 2 0 002-3l-5-9V3 M7 14h10",
    sliders: "M4 7h10 M18 7h2 M4 12h4 M12 12h8 M4 17h12 M18 17h2 M14 5v4 M8 10v4 M16 15v4",
    trending: "M3 17l6-6 4 4 8-8 M21 7v5h-5",
    grid: "M4 4h7v7H4z M13 4h7v7h-7z M4 13h7v7H4z M13 13h7v7h-7z",
    bell: "M18 9a6 6 0 10-12 0c0 7-3 8-3 8h18s-3-1-3-8 M10.5 20a2 2 0 003 0",
    check: "M5 12l5 5 9-11",
    refresh: "M21 12a9 9 0 11-3-6.7L21 8 M21 4v4h-4",
    warn: "M12 3l9 16H3z M12 10v4 M12 17h0",
    arrowIn: "M12 5v10 M8 11l4 4 4-4 M5 20h14",
    arrowOut: "M12 19V9 M8 13l4-4 4 4 M5 4h14",
    lock: "M7 11V8a5 5 0 0110 0v3 M5 11h14v9H5z M12 15v2",
    q: "M12 3a9 9 0 100 18 9 9 0 000-18z M9.6 9.4a2.4 2.4 0 114 1.9c-.8.5-1.6 1-1.6 2 M12 16.6h0",
    flow: "M6 4h0 M6 20h0 M18 12h0 M6 6v12 M6 12h9 M14 9l4 3-4 3",
    caduceus: "M12 3v18 M9 5a3 3 0 006 0 M8 9h8 M9 9c-2 2-2 5 3 6 5-1 5-4 3-6 M7 21h10",
    x: "M6 6l12 12 M18 6L6 18",
    // PET-114: collapse affordance. Points right (collapsed); CSS rotates it
    // 90° to point down when the section is expanded.
    chevron: "M9 6l6 6-6 6",
  };

  Pet.Icon = function (name) {
    var d = ICONS[name];
    if (!d) return document.createTextNode("");
    var svg = Pet.svg("svg", {
      class: "i", viewBox: "0 0 24 24", fill: "none",
      stroke: "currentColor", "stroke-width": "1.7",
      "stroke-linecap": "round", "stroke-linejoin": "round",
    });
    d.split(" M").forEach(function (seg, i) {
      svg.appendChild(Pet.svg("path", { d: (i ? "M" : "") + seg }));
    });
    return svg;
  };


  // Parses a restricted markup subset into a DocumentFragment of real DOM nodes.
  // Recognized (opening + closing, any case): <b> <code> <em>.
  // Every other "<" is treated as a literal character and escaped to a text node.
  // A closing tag that does not match the current open element is treated as
  // literal text — mismatched/unbalanced structure is never silently suppressed.
  // No HTML string is ever constructed; no innerHTML/DOMParser is ever used.
  // NOTE: ALLOWED must never gain a "g" flag — RegExp.exec with /g is stateful
  // (lastIndex persists across calls) and would make richText non-deterministic.
  Pet.richText = function (markup) {
    var frag = document.createDocumentFragment();
    if (markup == null) return frag;
    markup = String(markup);
    var ALLOWED = /^<(\/?)(b|code|em)>$/i;
    var stack = [frag];
    var buf = "";
    var i = 0;
    var flush = function () {
      if (buf) {
        stack[stack.length - 1].appendChild(document.createTextNode(buf));
        buf = "";
      }
    };
    while (i < markup.length) {
      if (markup[i] === "<") {
        var close = markup.indexOf(">", i);
        if (close !== -1) {
          var m = ALLOWED.exec(markup.substring(i, close + 1));
          if (m) {
            if (m[1] === "/") {
              // Closing tag: only pop when it matches the current open element.
              var closing = m[2].toLowerCase();
              var top = stack[stack.length - 1];
              if (stack.length > 1 && top.tagName && top.tagName.toLowerCase() === closing) {
                flush();
                stack.pop();
                i = close + 1;
                continue;
              }
              // Mismatched/unbalanced closer — fall through to literal text.
            } else {
              flush();
              var el = document.createElement(m[2].toLowerCase());
              stack[stack.length - 1].appendChild(el);
              stack.push(el);
              i = close + 1;
              continue;
            }
          }
        }
      }
      buf += markup[i];
      i++;
    }
    flush();
    return frag;
  };

  Pet.HelpTip = function (html) {
    var btn = Pet.h("span", { className: "help", tabIndex: "0" });
    btn.appendChild(Pet.Icon("q"));
    var tip = Pet.h("span", { className: "tip" });
    tip.appendChild(Pet.richText(html));
    btn.appendChild(tip);
    var position = function () {
      var r = btn.getBoundingClientRect();
      tip.style.position = "fixed";
      tip.style.left = r.left + "px";
      tip.style.top = (r.bottom + 6) + "px";
      var tRect = tip.getBoundingClientRect();
      if (tRect.bottom > window.innerHeight - 8) {
        tip.style.top = (r.top - tRect.height - 6) + "px";
      }
      if (tRect.right > window.innerWidth - 8) {
        tip.style.left = (window.innerWidth - tRect.width - 8) + "px";
      }
    };
    btn.addEventListener("mouseenter", position);
    btn.addEventListener("focus", position);
    return btn;
  };


  // ── Panel primitive ──
  // PET-114 D5: collapsible support is additive and default-off. When
  // `opts.collapsible` is falsy the builder is behaviorally unchanged, so the
  // Observability / Playground / About callers are unaffected. Body visibility
  // is driven solely by the `collapsed` class on the panel (CSS rule) — there is
  // no imperative body.style.display write, so there is exactly one hide mechanism.
  Pet.Panel = function (opts) {
    var collapsible = !!opts.collapsible;
    var collapsed = collapsible && !!opts.collapsed;

    var headAttrs = { className: "panel-head" + (collapsible ? " collapsible" : "") };
    if (collapsible) {
      headAttrs.role = "button";
      headAttrs.tabIndex = 0;
      headAttrs.ariaExpanded = !collapsed;
    }
    var head = Pet.h("div", headAttrs);
    if (collapsible) {
      // Leading chevron in an `.ic` flex slot so it inherits the head's vertical
      // centering; the `chevron` class is the CSS rotation hook.
      head.appendChild(Pet.h("span", { className: "ic chevron" }, Pet.Icon("chevron")));
    }
    if (opts.icon) {
      var ic = Pet.h("span", { className: "ic" }, Pet.Icon(opts.icon));
      head.appendChild(ic);
    }
    head.appendChild(Pet.h("span", { className: "pt" }, opts.title || ""));
    if (opts.help) head.appendChild(opts.help);
    if (opts.place) head.appendChild(Pet.h("span", { className: "place" }, opts.place));
    if (opts.right) {
      var r = Pet.h("span", { className: "right" });
      if (typeof opts.right === "string") r.textContent = opts.right;
      else if (Array.isArray(opts.right)) opts.right.forEach(function (c) { r.appendChild(c); });
      else r.appendChild(opts.right);
      head.appendChild(r);
    }
    var body = Pet.h("div", { className: "panel-body" + (opts.flush ? " flush" : "") });
    if (opts.bodyStyle) Object.assign(body.style, opts.bodyStyle);
    if (opts.content) {
      if (Array.isArray(opts.content)) opts.content.forEach(function (c) { if (c) body.appendChild(c); });
      else body.appendChild(opts.content);
    }
    var panel = Pet.h("div", { className: "panel" + (collapsed ? " collapsed" : "") }, head, body);
    if (opts.style) Object.assign(panel.style, opts.style);

    if (collapsible) {
      // Imperative live-DOM mutation, not a re-render: flip the flag, drive the
      // `collapsed` class on the panel, rewrite aria-expanded on the live head.
      var applyState = function () {
        panel.className = "panel" + (collapsed ? " collapsed" : "");
        head.setAttribute("aria-expanded", String(!collapsed));
      };
      var toggle = function () {
        collapsed = !collapsed;
        applyState();
        if (typeof opts.onToggle === "function") opts.onToggle(collapsed);
      };
      head.addEventListener("click", toggle);
      head.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); }
      });
      // Programmatic handle for the apply-error reveal (§3f): expand/collapse
      // WITHOUT firing onToggle (a programmatic expansion is not a user choice).
      panel.petSetCollapsed = function (c) {
        collapsed = !!c;
        applyState();
      };
    }
    return panel;
  };

  // ── State ──
  Pet.state = {
    tab: "obs",
    config: null,
    configFields: null,
    configDirty: {},
    // PET-124: strength-preset registry + derived active level from the last
    // /config fetch (alongside config / configFields). active level is recomputed
    // authoritatively on every fetch and update response.
    configPresets: null,
    configActivePreset: null,
    // PET-146: the non-equipped Hermes profile currently being viewed/edited in the
    // Config Editor, or null for the equipped binding (the default, byte-identical
    // to the pre-PET-146 active-only view). Persists across renderConfig re-renders
    // so a profile switch reloads the same profile after save/discard.
    selectedHermesProfile: null,
    scanHistory: [],
    // PET-148/PET-152: scan-history back-page paging state. historyAtHead=true shows the live
    // SSE-maintained scanHistory buffer (the most-recent window); when paged back, historyStack
    // holds the fetched older pages (top = current view). PET-152 dropped the cached
    // historyHeadCursor field: it was captured once at seed and went stale once the ring evicted
    // past the oldest seeded row, so the first "Older" click skipped the band between the current
    // oldest buffered row and the stale boundary. The head boundary is now re-minted via a fresh
    // server round-trip on every head->older transition, and the "Older" affordance off the head
    // gates on scanHistoryHasOlder(buffered, scans_total) on the equipped branch; a
    // non-equipped scope reads the server's has_older (PET-166 D12). The single "of N"
    // total stays /health.scans_total (D-RESTART); paged views never compute a competing total.
    historyAtHead: true,
    historyStack: [],
    // PET-166 (D19): payload-derived read-scope facts. readScope is the cross-surface
    // scope object (null = the equipped form; all of standalone stays null);
    // historyReadScope is the history panel's OWN copy, written only by scan-history
    // 200s, because its two facts arrive on different endpoints. historyHasOlder is
    // the server-emitted "Older" gate for the non-equipped branch; spoolTruncated is
    // the D3 retention fact; scopeError is the D7 coherent 422 state; scopeNotice is
    // the D20 "showing: equipped binding" client notice. All reset on scope change
    // and unmount (D17).
    readScope: null,
    historyReadScope: null,
    historyHasOlder: false,
    spoolTruncated: false,
    scopeError: null,
    scopeNotice: false,
    // PET-138: session_id -> cumulative count of tool calls bypassed while disarmed.
    // Dedicated, eviction-proof state (the count rides a single rate-limited
    // heartbeat row that ages out of scanHistory); fed by Pet.accrueBypass.
    bypassBySession: {},
    // PET-165: server-authoritative lifetime count of surfaced self-tamper attempts,
    // feeding the "self-tamper" metric tile. Seeded from /health (pipeline.selfmod_total)
    // and incremented per SSE selfmod frame, so the tile never decays when the 500-entry
    // ring evicts the underlying rows. Lifetime-since-console-start, not persisted.
    selfmodTotal: 0,
    // PET-165: scan-history row filter, "all" or "selfmod". Filters RENDERED rows only,
    // never the buffer and never a tile value. Live-head only (paged views render
    // unfiltered); per-page-load, not persisted.
    historyFilter: "all",
    // PET-137: scan_id of the scan-history row whose detail panel is open (or null).
    // Persisted in state (not local DOM) so the panel survives renderDashboard's
    // per-SSE-frame rebuild; re-opened by scan_id, so an evicted row closes cleanly.
    openDetailId: null,
    alerts: [],
    auditLog: [],
    scannerHealth: [],
    pipelineHealth: null,
    integrityHealth: null, // PET-157: additive get_health `integrity` payload for the obs panel
    profiles: [],
    about: null,
    armed: true,  // PET-111: master Equipped/Unequipped bit; corrected by the mount fetch
    // PET-129: first-class terminal "authenticate" state. Set true by Pet.auth.on401
    // when a standalone /api call returns 401 (PETASOS_CONSOLE_TOKEN gate, PET-125);
    // distinct from "offline". While true the dashboard renders the authenticate
    // panel, both polls are stopped, and the banner reads AUTHENTICATE (never a false
    // EQUIPPED). Cleared only by a verified re-auth (Pet.auth resume).
    authRequired: false,
    // PET-114: per-session collapse choices { sectionKey: bool }. Written SOLELY
    // by an onToggle (an explicit user collapse/expand) or the apply-error reveal,
    // never seeded on render — so an upgrade from a stale all-expanded payload
    // re-applies each section's real default_collapsed for untouched sections.
    sectionCollapsed: {},
  };


  Pet._moduleState = { last: "core", ready: false };
  window.__PETASOS_CONSOLE__ = Pet;
})();
