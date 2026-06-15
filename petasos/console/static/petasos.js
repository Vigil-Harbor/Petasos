/* petasos.js — Petasos Console frontend (vanilla JS, no build step)
   Exposes window.__PETASOS_CONSOLE__ namespace. */
(function () {
  "use strict";
  var Pet = {};

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

  var SEV = {
    critical: { cls: "sev-crit", col: "var(--crit)", short: "CRIT" },
    high: { cls: "sev-high", col: "var(--high)", short: "HIGH" },
    medium: { cls: "sev-med", col: "var(--med)", short: "MED" },
    low: { cls: "sev-low", col: "var(--low)", short: "LOW" },
    info: { cls: "sev-info", col: "var(--info)", short: "INFO" },
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

  Pet.SevBadge = function (sev) {
    var v = SEV[sev] || SEV.info;
    var badge = Pet.h("span", { className: "badge " + v.cls }, v.short);
    return badge;
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
    scanHistory: [],
    alerts: [],
    auditLog: [],
    scannerHealth: [],
    pipelineHealth: null,
    profiles: [],
    about: null,
    armed: true,  // PET-111: master Equipped/Unequipped bit; corrected by the mount fetch
    // PET-114: per-session collapse choices { sectionKey: bool }. Written SOLELY
    // by an onToggle (an explicit user collapse/expand) or the apply-error reveal,
    // never seeded on render — so an upgrade from a stale all-expanded payload
    // re-applies each section's real default_collapsed for untouched sections.
    sectionCollapsed: {},
  };

  // ── API client ──
  Pet.api = {
    baseUrl: "/api",
    _req: function (path, opts) {
      var url = this.baseUrl + path;
      var sdk = window.__HERMES_PLUGIN_SDK__;
      if (sdk && sdk.fetchJSON) {
        return sdk.fetchJSON(url, opts)
          .then(function (r) { return r; })
          .catch(function (e) {
            var msg = e.message || "";
            var match = msg.match(/^(\d+):\s*([\s\S]*)/);
            if (match) {
              var status = parseInt(match[1], 10);
              try { var body = JSON.parse(match[2]); body._status = status; return body; } catch (_) {}
              return { error: match[2], _status: status };
            }
            return { error: msg };
          });
      }
      return fetch(url, opts).then(function (r) {
        return r.json().then(function (data) {
          if (!r.ok) data._status = r.status;
          return data;
        }).catch(function () {
          return { error: r.status + " " + r.statusText, _status: r.status };
        });
      }).catch(function (e) {
        return { error: e.message };
      });
    },
    _get: function (path) { return this._req(path); },
    _post: function (path, body) {
      return this._req(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    },
    _put: function (path, body) {
      return this._req(path, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    },
    getConfig: function () { return this._get("/config"); },
    putConfig: function (patch) { return this._put("/config", patch); },
    postScan: function (text, dir, sid) { return this._post("/scan", { text: text, direction: dir, session_id: sid }); },
    getHealth: function () { return this._get("/health"); },
    getScanHistory: function (limit) { return this._get("/scan-history?limit=" + (limit || 100)); },
    getProfiles: function () { return this._get("/profiles"); },
    getAbout: function () { return this._get("/about"); },
    getArmed: function () { return this._get("/armed"); },
    setArmed: function (a) { return this._post("/armed", { armed: a }); },
  };

  // ── SSE client (fetch-based for auth header support) ──
  Pet.sse = {
    _reader: null,
    _abortCtrl: null,
    _usingFallback: false,

    connect: function () {
      var self = this;
      if (self._abortCtrl) self.disconnect();
      var url = Pet.api.baseUrl + "/events";
      var headers = { "Accept": "text/event-stream" };
      var token = window.__HERMES_SESSION_TOKEN__;
      if (token) headers["X-Hermes-Session-Token"] = token;

      self._abortCtrl = new AbortController();
      fetch(url, {
        headers: headers,
        signal: self._abortCtrl.signal,
        credentials: "same-origin",
      })
        .then(function (resp) {
          if (!resp.ok) throw new Error(resp.status);
          if (!resp.body) throw new Error("no response body");
          var reader = resp.body.getReader();
          var dec = new TextDecoder();
          self._reader = reader;
          var buf = "";
          function pump() {
            reader.read().then(function (r) {
              if (r.done) {
                if (buf.trim()) {
                  var evType = null, evData = null;
                  buf.replace(/\r\n/g, "\n").split("\n").forEach(function (line) {
                    if (line.indexOf("event: ") === 0) evType = line.slice(7);
                    else if (line.indexOf("data: ") === 0) evData = line.slice(6);
                  });
                  if (evType && evData) self._dispatch(evType, evData);
                }
                self._enableFallback();
                return;
              }
              buf += dec.decode(r.value, { stream: true }).replace(/\r\n/g, "\n");
              var frames = buf.split("\n\n");
              buf = frames.pop();
              frames.forEach(function (frame) {
                var evType = null, evData = null;
                frame.split("\n").forEach(function (line) {
                  if (line.indexOf("event: ") === 0) evType = line.slice(7);
                  else if (line.indexOf("data: ") === 0) evData = line.slice(6);
                });
                if (evType && evData) self._dispatch(evType, evData);
              });
              pump();
            }).catch(function (e) {
              if (e.name !== "AbortError") self._enableFallback();
            });
          }
          pump();
        })
        .catch(function (e) {
          if (e.name !== "AbortError") {
            console.warn("Petasos SSE: " + e.message + ", using polling fallback");
            self._enableFallback();
          }
        });
    },

    _dispatch: function (evType, dataStr) {
      try { var d = JSON.parse(dataStr); } catch (_) { return; }
      if (evType === "scan_result") {
        // PET-99 D6: a malformed frame (JSON.parse("null"), a number, an array)
        // must never enter the render buffer — scanHistoryRows/renderDashboard
        // guard on read, but keeping the buffer object-only is the cheaper floor.
        if (d && typeof d === "object") Pet.state.scanHistory.unshift(d);
        if (Pet.state.scanHistory.length > 500) Pet.state.scanHistory.length = 500;
        if (Pet.state.tab === "obs" && _container) Pet.renderDashboard(_container);
      } else if (evType === "audit") {
        Pet.state.auditLog.unshift(d);
        if (Pet.state.auditLog.length > 1000) Pet.state.auditLog.length = 1000;
      } else if (evType === "alert") {
        Pet.state.alerts.unshift(d);
        if (Pet.state.alerts.length > 200) Pet.state.alerts.length = 200;
      } else if (evType === "armed") {
        // PET-116: live cross-tab sync of the Equipped/Unequipped bit. _dispatch
        // cannot call paintBanner (a renderDashboard-local closure); it adopts the
        // authoritative pushed value into Pet.state.armed and re-renders, mirroring
        // the scan_result arm. renderDashboard rebuilds the banner from
        // Pet.state.armed and re-runs its per-entry seed guard.
        if (_armedBusy) return;                 // don't clobber this tab's in-flight optimistic toggle
        if (d && typeof d.armed === "boolean") {
          Pet.state.armed = d.armed;            // adopt file-truth pushed by the originating tab
          _armedSeeded = true;                  // an authoritative push counts as a seed (no redundant GET)
          if (Pet.state.tab === "obs" && _container) Pet.renderDashboard(_container);
        }
      }
    },

    _enableFallback: function () {
      if (this._usingFallback) return;
      this._usingFallback = true;
      startFallbackPolling();
    },

    disconnect: function () {
      if (this._abortCtrl) { this._abortCtrl.abort(); this._abortCtrl = null; }
      this._reader = null;
      this._usingFallback = false;
      stopFallbackPolling();
    },
  };

  // ── Polling (health: always, scan/alert data: fallback when SSE unavailable) ──
  var _pollInterval = null;
  var _fallbackPollInterval = null;

  function startPolling() {
    if (_pollInterval) return;
    _pollInterval = setInterval(function () {
      Pet.api.getHealth().then(function (d) {
        if (!d.error) {
          _healthLoaded = true;  // PET-127: a poll settle that beats a slow in-render fetch flips the gate, not the skeleton
          Pet.state.scannerHealth = d.scanners || [];
          Pet.state.pipelineHealth = d.pipeline || null;
          if (Pet.state.tab === "obs" && _container) Pet.renderDashboard(_container);
        }
      });
    }, 10000);
  }
  function stopPolling() {
    if (_pollInterval) { clearInterval(_pollInterval); _pollInterval = null; }
  }

  function startFallbackPolling() {
    if (_fallbackPollInterval) return;
    function schedule() {
      _fallbackPollInterval = setTimeout(function () {
        Pet.api.getScanHistory(100).then(function (d) {
          if (!d.error && d.entries && Array.isArray(d.entries)) {
            Pet.state.scanHistory = d.entries;
            if (Pet.state.tab === "obs" && _container) Pet.renderDashboard(_container);
          }
        }).then(function () {
          if (_fallbackPollInterval) schedule();
        });
      }, 10000);
    }
    Pet.api.getScanHistory(100).then(function (d) {
      if (!d.error && d.entries && Array.isArray(d.entries)) {
        Pet.state.scanHistory = d.entries;
        if (Pet.state.tab === "obs" && _container) Pet.renderDashboard(_container);
      }
    });
    schedule();
  }
  function stopFallbackPolling() {
    if (_fallbackPollInterval) { clearTimeout(_fallbackPollInterval); _fallbackPollInterval = null; }
  }

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
    var table = Pet.h("div", { style: { display: "flex", flexDirection: "column", gap: "4px" } });
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
      var nameEl = Pet.h("span", { className: "mono", style: { fontSize: "12px", color: "var(--tx)", minWidth: "120px", display: "inline-block" } }, s.name);
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

  // PET-102: history rows derived from the in-memory scan-history buffer.
  // Mirrors Pet.scannerHealthRows. Must NEVER throw — the SSE _dispatch calls
  // renderDashboard synchronously (petasos.js scan_result handler), so an
  // exception out of the row build would abort the live re-render. Every
  // caller-influenceable field is coerced/guarded. No innerHTML (PET-82): cells
  // are built with Pet.h + .textContent (title= for the truncated session id).
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
    var table = Pet.h("div", { style: { display: "flex", flexDirection: "column", gap: "4px" } });
    for (var i = 0; i < hist.length; i++) {
      var e = hist[i];
      if (!e || typeof e !== "object") continue; // never-throw: skip a malformed entry (e.g. JSON null from a bad SSE frame) rather than aborting the synchronous re-render
      var isBlocked = (e.safe === false); // strict ===false; truthy-but-not-false is not "blocked"
      var badge = Pet.h("span", { className: "pill " + (isBlocked ? "err" : "ok"), style: { minWidth: "62px", justifyContent: "center" } }, isBlocked ? "blocked" : "safe");

      var dirEl = Pet.h("span", { className: "mono", style: { fontSize: "11px", color: "var(--tx-faint)", minWidth: "64px", display: "inline-block" } });
      dirEl.textContent = (e.direction != null && e.direction !== "") ? String(e.direction) : "—";

      var findEl = Pet.h("span", { className: "mono", style: { fontSize: "11px", color: "var(--tx-faint)", minWidth: "78px", display: "inline-block" } });
      findEl.textContent = (Number(e.finding_count) || 0) + " findings";

      var latEl = Pet.h("span", { className: "mono", style: { fontSize: "11px", color: "var(--tx-faint)", minWidth: "56px", display: "inline-block" } });
      latEl.textContent = (Number(e.duration_ms) || 0).toFixed(1) + "ms"; // never e.duration_ms.toFixed — would throw on missing/non-numeric

      var sidStr = (e.session_id == null || e.session_id === "") ? "" : String(e.session_id);
      var sidEl = Pet.h("span", { className: "mono", title: sidStr, style: { fontSize: "11px", color: "var(--tx-faint)", maxWidth: "120px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", display: "inline-block" } });
      sidEl.textContent = sidStr ? (sidStr.length > 12 ? sidStr.slice(0, 12) + "…" : sidStr) : "—";

      var timeEl = Pet.h("span", { className: "mono", style: { fontSize: "11px", color: "var(--tx-faint)", marginLeft: "auto", display: "inline-block" } });
      timeEl.textContent = fmtTime(e.timestamp);

      var row = Pet.h("div", { style: { display: "flex", alignItems: "center", gap: "8px" } }, badge, dirEl, findEl, latEl, sidEl, timeEl);
      table.appendChild(row);
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

  Pet.renderDashboard = function (container) {
    container.innerHTML = "";
    var wrapper = Pet.h("div", { style: { display: "flex", flexDirection: "column", gap: "12px", height: "100%" } });

    // ── PET-111: Equipped/Unequipped master switch (first child of the tab) ──
    // paintBanner re-queries the LIVE banner node each call (never closes over a
    // captured node): renderDashboard rebuilds the banner on every SSE/poll frame,
    // and _container is null after unmount — so guard container-truthiness first.
    var paintBanner = function () {
      var b = _container && _container.querySelector(".equip-banner");
      if (!b) return;
      var on = Pet.state.armed !== false;
      var confirming = on && _armedConfirmPending;
      b.className = "equip-banner" + (on ? "" : " disarmed") + (confirming ? " confirming" : "");
      var lbl = b.querySelector(".equip-label");
      if (lbl) lbl.textContent = confirming ? "CONFIRM UNEQUIP?" : (on ? "EQUIPPED" : "UNEQUIPPED");
      var sub = b.querySelector(".equip-sub");
      if (sub) sub.textContent = confirming
        ? "Click again to disable all enforcement"
        : (on ? "Enforcement is ON" : "Enforcement is OFF for every session");
      var sw = b.querySelector(".switch");
      if (sw) {
        sw.className = "switch" + (on && !confirming ? " on" : "");
        sw.setAttribute("aria-checked", on ? "true" : "false");
        sw.setAttribute("aria-label", "Petasos enforcement: " + (on ? "equipped, click to unequip" : "unequipped, click to equip"));
      }
    };
    var doToggle = function () {
      if (_armedBusy) return;  // ignore rapid re-clicks while a write is in flight
      var on = Pet.state.armed !== false;
      // Disarming is the high-stakes direction: require a confirming 2nd click.
      // Arming protection back ON stays one click.
      if (on && !_armedConfirmPending) {
        _armedConfirmPending = true;
        paintBanner();
        _armedConfirmTimer = setTimeout(function () { clearArmedConfirm(); paintBanner(); }, 4000);
        return;
      }
      clearArmedConfirm();
      var next = !on;
      _armedBusy = true;
      Pet.state.armed = next; paintBanner();  // optimistic (live re-query, survives re-render)
      Pet.api.setArmed(next).then(function (d) {
        _armedBusy = false;
        _armedSeeded = true;  // a settled write IS a fresh seed -> no spurious follow-up GET
        var ok = d && !d.error && (!d._status || d._status < 400) && typeof d.armed === "boolean";
        Pet.state.armed = ok ? d.armed : !next;  // reconcile to authoritative value, else revert
        paintBanner();
      });
    };
    var armedOn = Pet.state.armed !== false;
    var confirming = armedOn && _armedConfirmPending;
    var armedSwitch = Pet.h("button", {
      className: "switch" + (armedOn && !confirming ? " on" : ""), type: "button", onClick: doToggle,
      role: "switch", ariaChecked: armedOn ? "true" : "false",
      ariaLabel: "Petasos enforcement: " + (armedOn ? "equipped, click to unequip" : "unequipped, click to equip")
    });
    armedSwitch.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); doToggle(); }
    });
    wrapper.appendChild(Pet.h("div", { className: "equip-banner" + (armedOn ? "" : " disarmed") + (confirming ? " confirming" : "") },
      Pet.h("img", { className: "equip-mark", src: Pet.asset("img/petasos-helmet.png"), alt: "" }),
      Pet.h("div", { className: "equip-text" },
        Pet.h("div", { className: "equip-label" }, confirming ? "CONFIRM UNEQUIP?" : (armedOn ? "EQUIPPED" : "UNEQUIPPED")),
        Pet.h("div", { className: "equip-sub" }, confirming ? "Click again to disable all enforcement" : (armedOn ? "Enforcement is ON" : "Enforcement is OFF for every session"))
      ),
      Pet.HelpTip("<b>Equipped</b>: master switch. <b>Unequipped</b> disables <b>all</b> Petasos enforcement (scan, guard, audit) for this and running sessions, applied by the next tool call. Backed by <code>petasos.enabled</code>."),
      armedSwitch
    ));

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

    var metricsRow = Pet.h("div", { style: { display: "flex", gap: "12px" } });
    // Lean metric cells (not four identical icon-panels): an eyebrow label over a
    // value. `blocked` carries severity weight when > 0 so the one security-load-
    // bearing number stands out instead of looking like `sessions`.
    var valueTile = function (label, value, alert) {
      return Pet.h("div", {
        style: {
          flex: "1", minWidth: "0", borderRadius: "var(--r-panel)", padding: "11px 14px",
          background: alert ? "var(--crit-soft)" : "var(--bg-panel)",
          border: "1px solid " + (alert ? "var(--crit)" : "var(--border)")
        }
      },
        Pet.h("div", { className: "eyebrow" }, label),
        Pet.h("div", { className: "num", style: { fontSize: "26px", marginTop: "4px", color: alert ? "var(--crit)" : "var(--tx-bright)" } }, String(value))
      );
    };
    metricsRow.appendChild(valueTile("scans", scans, false));
    metricsRow.appendChild(valueTile("blocked", blocked, blocked > 0));
    metricsRow.appendChild(valueTile("avg latency", avgLatency, false));
    metricsRow.appendChild(valueTile("sessions", sessions, false));
    wrapper.appendChild(metricsRow);

    // Scanner health
    var healthPanel = Pet.Panel({
      icon: "radar", title: "scanner health", place: "loaded backends", flush: true,
      help: Pet.HelpTip(Pet.SCANNER_HEALTH_HELP),
      // PET-127: keep this padding:12px div as the stable paint target in both
      // branches — the resolve/error arms find it via [style*='padding: 12px'].
      // Only <inner> changes: skeleton while !_healthLoaded, cached rows once a
      // /health response has settled (so steady-state SSE frames show no skeleton).
      // The role=status wrapper carries NO padding:12px, so the outer div stays the
      // unique [style*='padding: 12px'] match.
      content: Pet.h("div", { style: { padding: "12px" } },
        _healthLoaded
          ? Pet.scannerHealthRows(Pet.state.scannerHealth)
          : Pet.h("div", { role: "status", ariaBusy: true, ariaLabel: "Loading scanner status" },
              Pet.skelRows(3, { h: "16px" }))
      ),
    });
    wrapper.appendChild(healthPanel);

    // Scan history — rows derived from the same buffer (already most-recent-first).
    var historyPanel = Pet.Panel({
      icon: "list", title: "scan history", place: "recent evaluations", flush: true,
      help: Pet.HelpTip("<b>Scan History</b>: recent pipeline scans with severity, direction, and timing. Each row is one <code>Pipeline.evaluate()</code> call."),
      content: Pet.h("div", { style: { padding: "12px" } }, Pet.scanHistoryRows(hist)),
    });
    wrapper.appendChild(historyPanel);

    container.appendChild(wrapper);

    // PET-111: fetch the authoritative armed bit once per obs ENTRY (guarded by
    // _armedSeeded — reset in mount/unmount/switchTab→obs) — never on every
    // SSE/poll re-render. Skip while a write is in flight so it can't clobber an
    // optimistic value; paintBanner re-queries the live node.
    if (!_armedSeeded && !_armedBusy) {
      _armedSeeded = true;
      Pet.api.getArmed().then(function (d) {
        if (_armedBusy) return;
        if (d && !d.error && typeof d.armed === "boolean") {
          Pet.state.armed = d.armed;
          paintBanner();
        }
      });
    }

    // Fetch initial data and render scanner health
    Pet.api.getHealth().then(function (d) {
      _healthLoaded = true;  // PET-127: settled (either arm) -> stop painting the skeleton
      if (!d.error) {
        Pet.state.scannerHealth = d.scanners || [];
        Pet.state.pipelineHealth = d.pipeline || null;
        var rows = Pet.scannerHealthRows(Pet.state.scannerHealth);
        var contentEl = healthPanel.querySelector("[style*='padding: 12px']") || healthPanel.querySelector("div > div");
        if (contentEl) { contentEl.innerHTML = ""; contentEl.appendChild(rows); }
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
    if (!_historySeeded) {
      _historySeeded = true;
      Pet.api.getScanHistory(500).then(function (d) {
        // startFallbackPolling response-shape guard, NOT the bare !d.error check:
        // _req never rejects on HTTP error (it resolves an error envelope), and a
        // 200 {} body lacking .entries would make the merge throw on .scan_id.
        if (!d.error && d.entries && Array.isArray(d.entries)) {
          // PET-99 D6/D9: shape-guarded seed-merge (skips non-object entries on
          // both sides before reading .scan_id) — replaces the inline dedup loops.
          Pet.mergeScanHistory(Pet.state.scanHistory, d.entries);
          if (Pet.state.tab === "obs" && _container) Pet.renderDashboard(_container);
        }
      });
    }
  };

  // ── Playground result/error builders (PET-99 D9 testability seam) ──
  // Extracted from the former inline scan-button onClick closure so the console
  // JS harness (node:vm + DOM shim) can assert them as pure builder calls.

  // D2: the result region scrolls within its definite-height flex bound; it does
  // not clip-to-invisible. flex:1 + minHeight:0 + overflowY:auto.
  Pet.makeResultArea = function () {
    return Pet.h("div", { style: { flex: "1", minHeight: "0", overflowY: "auto" } });
  };

  // D3: one legibility contract for every failure shape. The message is a real,
  // selectable text node (present in textContent), not title-only; pre-wrap +
  // overflow-wrap keep it readable, a bounded maxHeight + scroll keep it reachable.
  Pet.scanErrorBlock = function (message) {
    return Pet.h("div", { style: {
      color: "var(--crit)", padding: "12px",
      whiteSpace: "pre-wrap", overflowWrap: "anywhere",
      maxHeight: "240px", overflowY: "auto",
    } }, String(message == null ? "" : message));
  };

  // D5: shared button-restore for both promise arms (success + failure).
  Pet.restoreScanButton = function (scanBtn) {
    scanBtn.textContent = "";
    scanBtn.appendChild(Pet.Icon("bolt"));
    scanBtn.appendChild(document.createTextNode(" Scan"));
  };

  // The success render (verdict + findings + normalization diff + anonymized
  // output + session overlay), lifted from the former onClick closure. Reads
  // d.result shape-defensively (D5) so a malformed body returns a readable error
  // block instead of throwing into runPlaygroundScan's .catch (which would
  // discard the whole result for a generic message). Side-effect-free.
  Pet.renderScanResult = function (d, rawText) {
    var r = d && d.result;
    if (!r || typeof r !== "object" || typeof r.safe !== "boolean" || !Array.isArray(r.findings)) {
      return Pet.scanErrorBlock("Unexpected response shape from /scan");
    }
    var findings = Array.isArray(r.findings) ? r.findings : [];
    var isSafe = (r.safe === true); // explicit, mirroring scanHistoryRows' ===false discipline

    var frag = document.createDocumentFragment();

    // Verdict
    var verdict = isSafe
      ? Pet.h("span", { className: "pill ok", style: { height: "18px", fontSize: "10px" } }, "safe")
      : Pet.h("span", { className: "pill err", style: { height: "18px", fontSize: "10px" } }, "blocked");

    var summary = Pet.h("div", { style: { display: "flex", alignItems: "center", gap: "10px", marginBottom: "12px" } },
      verdict,
      Pet.h("span", { style: { fontSize: "12px", color: "var(--tx-mut)" } }, findings.length + " findings")
    );
    frag.appendChild(summary);

    // Findings
    if (findings.length > 0) {
      var findingsPanel = Pet.Panel({
        icon: "radar", title: "findings", place: "detections by scanner",
        help: Pet.HelpTip("<b>Findings</b>: individual detections from each scanner. Severity ranges from <code>INFO</code> to <code>CRITICAL</code>. High+ on dangerous tools triggers a block."),
        content: Pet.h("div", { className: "vlist", style: { gap: "8px" } },
          findings.map(function (f) {
            var v = SEV[f.severity] || SEV.info;
            var finding = Pet.h("div", { className: "finding" });
            var rail = Pet.h("div", { className: "rail", style: { background: v.col } });
            var body = Pet.h("div", { className: "body" },
              Pet.h("div", { style: { display: "flex", gap: "8px", alignItems: "center" } },
                Pet.h("span", { className: "rid" }, f.rule_id),
                Pet.h("span", { className: "mono", style: { marginLeft: "auto", fontSize: "10px", color: "var(--tx-faint)" } }, f.scanner_name || "")
              ),
              Pet.h("div", { className: "msg" }, f.message || ""),
              // D4: full matched_text on title as a hover affordance; the CSS wrap
              // rules keep the visible badge text from clipping to invisibility.
              f.matched_text ? Pet.h("span", { className: "matched", title: f.matched_text }, f.matched_text) : null
            );
            finding.appendChild(rail);
            finding.appendChild(Pet.SevBadge(f.severity));
            finding.appendChild(body);
            return finding;
          })
        ),
      });
      frag.appendChild(findingsPanel);
    }

    // Normalized diff
    if (d.normalized_text && d.normalized_text !== rawText) {
      frag.appendChild(Pet.Panel({
        icon: "trending", title: "normalization", place: "before → after",
        content: Pet.h("div", { className: "mono", style: { fontSize: "11.5px", lineHeight: "1.7" } },
          Pet.h("div", { style: { color: "var(--tx-ghost)" } }, "raw: ", Pet.h("span", { style: { color: "var(--tx-mut)" } }, rawText)),
          Pet.h("div", { style: { color: "var(--tx-ghost)" } }, "norm: ", Pet.h("span", { style: { color: "var(--tx)" } }, d.normalized_text))
        ),
      }));
    }

    // Anonymized output
    if (r.sanitized_content) {
      frag.appendChild(Pet.Panel({
        icon: "shieldCheck", title: "anonymized output", place: "PII redacted",
        content: Pet.h("div", { className: "mono", style: { fontSize: "12px", color: "var(--tx-mut)", lineHeight: "1.7" } }, r.sanitized_content),
      }));
    }

    // Session overlay
    if (r.session_score != null || r.escalation_tier) {
      var stats = Pet.h("div", { style: { display: "flex", gap: "10px" } });
      if (r.session_score != null) {
        // Numeric coercion (mirrors scanHistoryRows' Number(...) discipline): a
        // present-but-non-numeric session_score degrades this one tile, never the
        // whole result and never the UI.
        var ss = Number(r.session_score);
        if (!Number.isNaN(ss)) { // present-but-non-numeric score → skip this tile
          stats.appendChild(Pet.h("div", { style: { flex: "1", background: "var(--bg-raised)", border: "1px solid var(--border)", borderRadius: "var(--r-card)", padding: "7px 11px" } },
            Pet.h("div", { className: "eyebrow" }, "session_score"),
            Pet.h("div", { className: "num", style: { fontSize: "18px", fontWeight: "700", color: "var(--amber-bright)" } }, ss.toFixed(3))
          ));
        }
      }
      if (r.escalation_tier) {
        stats.appendChild(Pet.h("div", { style: { flex: "1", background: "var(--bg-raised)", border: "1px solid var(--border)", borderRadius: "var(--r-card)", padding: "7px 11px" } },
          Pet.h("div", { className: "eyebrow" }, "escalation_tier"),
          Pet.h("div", { className: "num", style: { fontSize: "18px", fontWeight: "700", color: "var(--crit)" } }, r.escalation_tier)
        ));
      }
      frag.appendChild(Pet.Panel({ icon: "user", title: "session overlay", place: "frequency + escalation", help: Pet.HelpTip("<b>Session Overlay</b>: cumulative session risk score and escalation tier. Score rises with repeated violations; tier thresholds trigger progressively stricter enforcement."), content: stats }));
    }

    return frag;
  };

  // D5: the extracted submit handler. Restores the button on EVERY path and
  // routes both the {error|detail} response branch and the rejection branch
  // through scanErrorBlock — no path leaves the UI stranded on "Scanning...".
  // `api` is injected (defaults to Pet.api) so a test can pass a stub; the
  // returned promise lets the test await completion.
  Pet.runPlaygroundScan = function (opts) {
    var scanBtn = opts.scanBtn;
    var resultArea = opts.resultArea;
    scanBtn.textContent = "Scanning...";
    return (opts.api || Pet.api).postScan(opts.text, opts.dir, opts.sid)
      .then(function (d) {
        Pet.restoreScanButton(scanBtn);
        resultArea.innerHTML = "";
        if (d && (d.error || d.detail)) {
          var msg = d.error;
          if (msg == null) { try { msg = JSON.stringify(d.detail); } catch (_) { msg = String(d.detail); } }
          resultArea.appendChild(Pet.scanErrorBlock(msg));
          return;
        }
        resultArea.appendChild(Pet.renderScanResult(d, opts.text)); // shape-defensive
      })
      .catch(function (e) { // D5: any throw/rejection still restores + shows readable text
        Pet.restoreScanButton(scanBtn);
        resultArea.innerHTML = "";
        resultArea.appendChild(Pet.scanErrorBlock((e && e.message) || "Scan failed"));
      });
  };

  Pet.renderPlayground = function (container) {
    container.innerHTML = "";
    var wrapper = Pet.h("div", { style: { display: "flex", flexDirection: "column", gap: "12px", height: "100%" } });

    var textArea = Pet.h("textarea", {
      className: "input mono",
      style: { width: "100%", height: "80px", resize: "vertical", padding: "10px", fontSize: "13px", background: "var(--bg-input)", border: "1px solid var(--border)", borderRadius: "var(--r-card)", color: "var(--tx)" },
      placeholder: "Paste text to scan... Try: 'ignore previous instructions' or 'email: test@example.com card: 4111 1111 1111 1234'",
    });

    var resultArea = Pet.makeResultArea();

    var dirBtn = { dir: "inbound" };
    var dirToggle = Pet.h("div", { className: "seg", role: "radiogroup", ariaLabel: "Scan direction" });
    var inBtn = Pet.h("button", { className: "on", role: "radio", ariaChecked: "true", onClick: function () { dirBtn.dir = "inbound"; inBtn.className = "on"; outBtn.className = ""; inBtn.setAttribute("aria-checked", "true"); outBtn.setAttribute("aria-checked", "false"); } }, "inbound");
    var outBtn = Pet.h("button", { role: "radio", ariaChecked: "false", onClick: function () { dirBtn.dir = "outbound"; outBtn.className = "on"; inBtn.className = ""; outBtn.setAttribute("aria-checked", "true"); inBtn.setAttribute("aria-checked", "false"); } }, "outbound");
    dirToggle.appendChild(inBtn);
    dirToggle.appendChild(outBtn);

    var sessionInput = Pet.h("input", { className: "input mono", style: { width: "120px", height: "30px", fontSize: "12px" }, placeholder: "session_id" });
    sessionInput.maxLength = 128; // mirrors _MAX_SESSION_ID_LEN; server check is authoritative (PET-85)

    var scanBtn = Pet.h("button", { className: "btn btn-primary btn-sm", onClick: function () {
      var text = textArea.value;
      if (!text || !text.trim()) return;
      // PET-99 D5/D9: thin call into the extracted handler with the live
      // scanBtn/resultArea; all render + restore + error legibility lives there.
      Pet.runPlaygroundScan({
        text: text,
        dir: dirBtn.dir,
        sid: sessionInput.value || null,
        scanBtn: scanBtn,
        resultArea: resultArea,
      });
    } });
    scanBtn.appendChild(Pet.Icon("bolt"));
    scanBtn.appendChild(document.createTextNode(" Scan"));

    var controls = Pet.h("div", { style: { display: "flex", alignItems: "center", gap: "10px" } }, dirToggle, sessionInput, scanBtn);

    var inspectPanel = Pet.Panel({
      icon: "beaker", title: "inspect", place: "scan playground",
      help: Pet.HelpTip("<b>Scan Playground</b>: paste text and run it through the full pipeline. Choose <code>inbound</code> (user→agent) or <code>outbound</code> (agent→user) direction. Optionally bind to a session ID for frequency tracking."),
      content: Pet.h("div", { style: { display: "flex", flexDirection: "column", gap: "10px" } }, textArea, controls),
    });

    wrapper.appendChild(inspectPanel);
    wrapper.appendChild(resultArea);
    container.appendChild(wrapper);
  };

  // PET-114: pure builder — turns the flat field list + registry section metadata
  // into an ordered array of groups, each carrying a real boolean default_collapsed:
  //   [ { key, label, default_collapsed, fields: [field, …] }, … ]
  // Testable without the network (mirrors Pet.scannerHealthRows / mergeScanHistory).
  // Degrades gracefully (D6): a stale backend with no `sections` falls back to
  // field-appearance order, all expanded; a field whose section is absent from the
  // registry (forward-compat new field) lands in a trailing expanded group keyed by
  // its raw section — never silently dropped.
  Pet.groupConfigSections = function (fields, sections) {
    if (!Array.isArray(fields) || fields.length === 0) return [];

    // Group fields by section, preserving field order and first-appearance order.
    var bySection = {};
    var appearance = [];
    for (var i = 0; i < fields.length; i++) {
      var f = fields[i];
      if (!f || typeof f !== "object") continue;
      var key = (f.section == null) ? "unknown" : f.section;
      if (!Object.prototype.hasOwnProperty.call(bySection, key)) {
        bySection[key] = [];
        appearance.push(key);
      }
      bySection[key].push(f);
    }

    var groups = [];
    var used = {};
    if (Array.isArray(sections) && sections.length > 0) {
      // Registry path: emit one group per registry entry in `order` (sort on the
      // explicit value rather than trusting array order across the wire); skip
      // registry entries with zero matching fields.
      var ordered = sections.slice().sort(function (a, b) {
        return ((a && a.order) || 0) - ((b && b.order) || 0);
      });
      ordered.forEach(function (s) {
        if (!s || s.key == null) return;
        var gk = s.key;
        if (!Object.prototype.hasOwnProperty.call(bySection, gk)) return;
        groups.push({
          key: gk,
          label: (s.label != null) ? s.label : gk,
          // PET-123: carry the registry copy the last hop (builder -> render) so
          // the section body can show a plain-language intro. Never-undefined (D4).
          description: (s.description != null) ? s.description : "",
          default_collapsed: Boolean(s.default_collapsed),
          fields: bySection[gk],
        });
        used[gk] = true;
      });
    }
    // Trailing groups: any section not emitted above (unknown registry, or stale
    // backend with no/empty sections), in field first-appearance order, expanded.
    appearance.forEach(function (gk) {
      if (used[gk]) return;
      // PET-123: a stale backend / unknown section has no registry copy; "" is the
      // never-undefined sentinel the intro builder degrades on (D4).
      groups.push({ key: gk, label: gk, description: "", default_collapsed: false, fields: bySection[gk] });
    });
    return groups;
  };

  // PET-114 §3f: for each errored field, expand its owning section panel so the
  // inline error is visible, and persist the expansion as a user-visible choice.
  // Pure w.r.t. the DOM handles passed in; returns the set of section keys
  // revealed. A field with no panel / unknown section is a safe no-op.
  Pet.revealFieldSections = function (errorFields, fieldSection, panelsBySection) {
    var revealed = {};
    (errorFields || []).forEach(function (name) {
      var sec = fieldSection[name];
      var panel = sec && panelsBySection[sec];
      if (panel && typeof panel.petSetCollapsed === "function") {
        panel.petSetCollapsed(false);             // imperative expand (no onToggle)
        Pet.state.sectionCollapsed[sec] = false;  // next re-render keeps it open
        revealed[sec] = true;
      }
    });
    return revealed;
  };

  // Humanize a config key for display: "tier3_threshold" -> "Tier 3 Threshold".
  Pet.CONFIG_ACRONYMS = { pii: "PII", iban: "IBAN", ssn: "SSN", ttl: "TTL", id: "ID", ip: "IP", rtl: "RTL", nfkc: "NFKC", hmac: "HMAC", url: "URL", ml: "ML", jwt: "JWT", api: "API", json: "JSON", llm: "LLM" };
  Pet.humanizeKey = function (key) {
    if (typeof key !== "string" || !key) return "";
    var s = key.replace(/^petasos\./, "").replace(/[._]+/g, " ").replace(/([a-zA-Z])([0-9])/g, "$1 $2").trim();
    return s.split(/\s+/).filter(Boolean).map(function (w) {
      var lw = w.toLowerCase();
      return Pet.CONFIG_ACRONYMS[lw] || (w.charAt(0).toUpperCase() + w.slice(1));
    }).join(" ");
  };

  // PET-123: intro node for a section body, or null when there is no copy to show
  // (stale backend / unknown section). Never throws on a missing / blank /
  // non-string description — degrades to null (PET-99 / D4 never-throw posture).
  Pet.sectionIntro = function (description) {
    if (typeof description !== "string") return null;
    var text = description.trim();
    if (!text) return null;
    return Pet.h("div", {
      style: { fontSize: "11.5px", color: "var(--tx-faint)", margin: "2px 0 10px",
               lineHeight: "1.45" }
    }, text);
  };

  // ── PET-124: strength-preset "tuning dial" ──
  // Pure JS mirror of petasos.console._presets.resolve_active_preset. Projects
  // `configValues` to each preset's override keys and returns the matching
  // preset key, or null (the derived "Custom" state) when none match. Used for
  // live (pre-apply) flips while editing. Value-normalizing equality: booleans
  // and the fail_mode string compare strictly; numeric owned fields compare as
  // Number(a) === Number(b), so a JSON-sourced `30` and a literal `30.0` are
  // equal and a freshly-applied preset never spuriously reads as Custom.
  Pet.resolveActivePreset = function (configValues, presets) {
    if (!configValues || typeof configValues !== "object") return null;
    if (!Array.isArray(presets) || presets.length === 0) return null;
    var valEq = function (a, b) {
      if (typeof a === "boolean" || typeof b === "boolean") return a === b;
      if (typeof a === "number" || typeof b === "number") return Number(a) === Number(b);
      return a === b;
    };
    for (var i = 0; i < presets.length; i++) {
      var p = presets[i];
      if (!p || typeof p !== "object" || !p.overrides || typeof p.overrides !== "object") continue;
      var keys = Object.keys(p.overrides);
      if (keys.length === 0) continue;
      var match = true;
      for (var j = 0; j < keys.length; j++) {
        var k = keys[j];
        if (!Object.prototype.hasOwnProperty.call(configValues, k) || !valEq(configValues[k], p.overrides[k])) {
          match = false;
          break;
        }
      }
      if (match) return p.key != null ? p.key : null;
    }
    return null;
  };

  // Renders the segmented strength dial: one button per preset (in `order`) plus
  // a trailing non-selectable Custom segment, the active one highlighted from
  // `activeKey` (Custom when null/absent/unknown). Each metal carries a HelpTip
  // from its description. Clicking a metal calls onSelect(preset). Never throws
  // (PET-99) / no innerHTML (PET-82): degrades on every malformed shape — a stale
  // backend missing `presets` (renders nothing), an empty list (nothing), a
  // preset entry lacking `overrides` (skipped).
  Pet.renderStrengthDial = function (presets, activeKey, onSelect) {
    var wrap = Pet.h("div", { className: "pet-dial-wrap" });
    if (!Array.isArray(presets) || presets.length === 0) return wrap;
    var ordered = presets
      .filter(function (p) {
        return p && typeof p === "object" && p.overrides && typeof p.overrides === "object";
      })
      .sort(function (a, b) { return ((a && a.order) || 0) - ((b && b.order) || 0); });
    if (ordered.length === 0) return wrap;

    var row = Pet.h("div", { className: "pet-dial-row" });
    row.appendChild(Pet.h("span", { className: "pet-dial-title eyebrow" }, "Strength"));
    var seg = Pet.h("div", { className: "seg pet-dial" });

    var activeIsKnown = false;
    ordered.forEach(function (p) {
      var isOn = p.key === activeKey;
      if (isOn) activeIsKnown = true;
      var btn = Pet.h("button", {
        className: "pet-dial-seg" + (isOn ? " on" : ""),
        type: "button",
        dataset: { preset: String(p.key) },
        onClick: function () { if (typeof onSelect === "function") onSelect(p); },
      }, p.label != null ? p.label : String(p.key));
      if (p.description) {
        // The HelpTip lives inside the clickable segment; swallow its click so
        // reading the tooltip never bubbles to onSelect and applies the preset.
        var tip = Pet.HelpTip(p.description);
        tip.addEventListener("click", function (e) { if (e && e.stopPropagation) e.stopPropagation(); });
        btn.appendChild(tip);
      }
      seg.appendChild(btn);
    });

    // Derived Custom segment — presentational, not clickable. Highlighted when no
    // built-in level matches the live config.
    var custom = Pet.h("span", {
      className: "pet-dial-seg pet-dial-custom" + (activeIsKnown ? "" : " on"),
      dataset: { preset: "custom" },
      title: "Custom: the live config does not match any built-in level.",
    }, "Custom");
    seg.appendChild(custom);

    row.appendChild(seg);
    wrap.appendChild(row);

    // D6: presentational recommendation pairing Iron (strength) with the
    // code_generation profile (scenario, selected separately). Changes no default.
    wrap.appendChild(Pet.h("div", { className: "pet-dial-rec" },
      "Recommended for coding agents: ",
      Pet.h("b", {}, "Iron"),
      " strength with the ",
      Pet.h("b", {}, "code_generation"),
      " profile."
    ));
    return wrap;
  };

  // ── Profile-picker pure builders (PET-122) ──
  // Two single-purpose, never-throw builders in the Pet.groupConfigSections /
  // Pet.scannerHealthRows idiom (no DOM, no network). profileNames is the option
  // source (every valid name); profileDescriptions is the tip source (names that
  // carry a usable description). Both first-wins dedup so they agree on a
  // duplicate-name payload.

  // Map a profile name -> its trimmed description. Tolerant of a missing/partial/
  // failed /api/profiles payload. Never throws (PET-99 never-throw posture).
  // Profiles with a blank/missing/non-string description are intentionally absent
  // (caller falls back to neutral tip copy). First occurrence of a name wins, so a
  // duplicate-name payload agrees with profileNames. Values are never undefined/empty.
  Pet.profileDescriptions = function (profiles) {
    var out = {};
    if (!Array.isArray(profiles)) return out;
    for (var i = 0; i < profiles.length; i++) {
      var p = profiles[i];
      // Gate on p.name.trim() so a whitespace-only name (e.g. "   ") is rejected
      // rather than rendered as a blank button; the original p.name is kept as the
      // key/value so a padded-but-real name still matches the resolver exactly.
      if (p && typeof p.name === "string" && p.name.trim() &&
          !Object.prototype.hasOwnProperty.call(out, p.name) &&
          typeof p.description === "string" && p.description.trim()) {
        out[p.name] = p.description.trim();
      }
    }
    return out;
  };

  // Ordered list of valid profile names (ALL of them, regardless of description),
  // deduped first-wins, malformed entries skipped. Never throws. This is the option
  // source; profileDescriptions is the tip source.
  Pet.profileNames = function (profiles) {
    var out = [], seen = {};
    if (!Array.isArray(profiles)) return out;
    for (var i = 0; i < profiles.length; i++) {
      var p = profiles[i];
      // Whitespace-only names are rejected (see profileDescriptions); the original
      // name is the option value so it round-trips to the resolver unchanged.
      if (p && typeof p.name === "string" && p.name.trim() &&
          !Object.prototype.hasOwnProperty.call(seen, p.name)) {
        seen[p.name] = true;
        out.push(p.name);
      }
    }
    return out;
  };

  // ── Profile-picker render seam (PET-122, D1/D3) ──
  // Bespoke, fetch-sourced control for the nullable `profile_name` field. Render-
  // then-enrich: paints a minimal seg ("(none)" + current value) synchronously,
  // then swaps in the full option set + per-option HelpTips when profilesP resolves.
  // Never blocks the form on /api/profiles and never throws. Exposed on Pet (like
  // groupConfigSections / revealFieldSections) so the render-seam unit tests can
  // drive it; the returned node carries a `_petRebuild(names, descMap)` handle for
  // the dirty-selection and collision-guard tests.
  //
  // NONE_LABEL doubles as the structural unset button's label AND the reserved
  // literal guarded against name collision (D6): a payload/stored value equal to
  // "(none)" is treated as unset, never rendered as a second truthy-string button.
  var PROFILE_NONE_LABEL = "(none)";
  var PROFILE_FALLBACK_TIP = "Custom profile: no description provided.";   // D5, sole authored string
  Pet.buildProfileControl = function (f, val, profilesP) {
    var seg = Pet.h("div", { className: "seg", role: "radiogroup", ariaLabel: Pet.humanizeKey(f.name) });
    var btns = [];   // explicit node array; selection clearing avoids querySelectorAll (F-1)

    // Recompute selection from configDirty on EVERY call (F-4): dirty wins (may be
    // null); else the config value captured once in this function's `val` param
    // (F-3); null => unset. A click before getProfiles resolves wrote configDirty,
    // so the enrich rebuild re-reads it and keeps the highlight.
    function currentSelection() {
      return Object.prototype.hasOwnProperty.call(Pet.state.configDirty, "profile_name")
        ? Pet.state.configDirty.profile_name
        : (typeof val === "string" && val ? val : null);
    }
    // null OR the literal "(none)" both resolve to the structural unset button.
    function isNoneSel(sel) { return sel == null || sel === PROFILE_NONE_LABEL; }

    function highlight() {
      var sel = currentSelection();
      var noneOn = isNoneSel(sel);
      for (var i = 0; i < btns.length; i++) {
        var b = btns[i];
        var on = b._petNone ? noneOn : (!noneOn && b._petVal === sel);
        b.className = on ? "on" : "";
        b.setAttribute("aria-checked", on ? "true" : "false");
      }
    }

    function addButton(label, value, tipText) {
      var btn = Pet.h("button", {
        className: "", type: "button", role: "radio", ariaChecked: "false",
        onClick: function () { Pet.state.configDirty.profile_name = value; highlight(); },
      }, label);
      btn._petVal = value;          // null for the structural "(none)" button
      btn._petNone = (value == null);
      seg.appendChild(btn);
      btns.push(btn);
      if (tipText) seg.appendChild(Pet.HelpTip(tipText));   // sibling .help node, focus-revealable (D4)
    }

    // Clear via shim-observable node removal, never innerHTML="" (F-1): the test
    // shim has no innerHTML setter, so an innerHTML write would leave childNodes
    // intact and the enrich rebuild would stack on the stale minimal seg.
    function clearSeg() {
      while (seg.childNodes.length) seg.removeChild(seg.childNodes[seg.childNodes.length - 1]);
      btns = [];
    }

    function rebuild(names, descMap) {
      clearSeg();
      var list = Array.isArray(names) ? names : [];
      var map = (descMap && typeof descMap === "object") ? descMap : {};
      // A non-empty profile list means we have enriched data and attach a HelpTip
      // per name/union button. An empty list is the minimal/degrade seg (initial
      // paint, or getProfiles rejected/empty): "(none)" + current value, selectable,
      // NO tips, no console error (D3). tipFor() encodes that split.
      var enriched = list.length > 0;
      function tipFor(name) { return enriched ? (map[name] || PROFILE_FALLBACK_TIP) : null; }

      addButton(PROFILE_NONE_LABEL, null, null);   // structural unset, writes null, never a tip
      var sel = currentSelection();
      var present = {};
      for (var i = 0; i < list.length; i++) {
        var nm = list[i];
        if (nm === PROFILE_NONE_LABEL) continue;   // D6: never a second "(none)" button
        present[nm] = true;
        addButton(nm, nm, tipFor(nm));
      }
      // Union the current/dirty value if it is a real custom/unknown name not
      // already listed (and not the reserved "(none)" literal — F-2).
      if (typeof sel === "string" && sel && sel !== PROFILE_NONE_LABEL &&
          !Object.prototype.hasOwnProperty.call(present, sel)) {
        addButton(sel, sel, tipFor(sel));
      }
      highlight();
    }

    rebuild([], {});   // minimal initial seg: "(none)" + current value
    if (profilesP && typeof profilesP.then === "function") {
      profilesP.then(
        function (profiles) { rebuild(Pet.profileNames(profiles), Pet.profileDescriptions(profiles)); },
        function () { rebuild([], {}); }   // defensive: a non-normalized rejecting promise still degrades to the minimal seg
      );
    }
    seg._petRebuild = rebuild;   // test seam: drive the enrich rebuild synchronously
    return seg;
  };

  Pet.renderConfig = function (container) {
    container.innerHTML = "";
    var wrapper = Pet.h("div", { style: { display: "flex", flexDirection: "column", gap: "12px", height: "100%" } });

    var notice = Pet.h("div", { className: "notice", style: { flex: "0 0 auto" } },
      Pet.Icon("warn"),
      Pet.h("span", {}, Pet.h("b", {}, "Changes are saved to config.yaml."), " Active agent sessions use the previous config until restarted.")
    );
    wrapper.appendChild(notice);

    // PET-127: skeleton field-rows while /config resolves. role=status carries the
    // loading semantic for AT; the resolve arm (formArea.innerHTML = "") and error
    // arm both wipe this wrapper before appending real content, so no arm change.
    var formArea = Pet.h("div", { style: { flex: "1", overflowY: "auto" } },
      Pet.h("div", { role: "status", ariaBusy: true, ariaLabel: "Loading configuration", style: { padding: "20px" } },
        Pet.skelRows(5, { h: "20px" }))
    );
    wrapper.appendChild(formArea);
    container.appendChild(wrapper);

    // PET-122: kick off the profiles fetch concurrently with getConfig so it is
    // already in flight when the form paints. Normalize to a never-throwing promise
    // of a raw profile array: a rejected or malformed getProfiles resolves to [].
    // (_get/_req return a fetch-based promise that resolves to {error} on failure
    // rather than rejecting, so the onRejected arm is belt-and-suspenders.)
    var profilesP = Pet.api.getProfiles().then(
      function (resp) { return (resp && Array.isArray(resp.profiles)) ? resp.profiles : []; },
      function () { return []; }
    );

    Pet.api.getConfig().then(function (d) {
      if (d.error || !d.config || !d.fields) {
        formArea.innerHTML = "";
        formArea.appendChild(Pet.h("div", { style: { padding: "20px", color: "var(--err)", fontSize: "12px", fontFamily: "var(--font-mono)" } },
          d.error ? "Config unavailable: " + d.error : "Unexpected response from API"));
        return;
      }
      Pet.state.config = d.config;
      Pet.state.configFields = d.fields;
      Pet.state.configPresets = d.presets;
      Pet.state.configActivePreset = d.active_preset;
      formArea.innerHTML = "";

      // PET-124: strength dial at the top of the editor. The owned-field set is
      // derived from the presets payload so the live (pre-apply) recompute and the
      // apply wiring stay in lockstep with the backend registry. If `presets` is
      // absent (stale backend), OWNED is empty and the dial renders nothing.
      var OWNED = {};
      (Array.isArray(d.presets) ? d.presets : []).forEach(function (p) {
        if (p && p.overrides && typeof p.overrides === "object") {
          Object.keys(p.overrides).forEach(function (k) { OWNED[k] = true; });
        }
      });
      var dialHost = Pet.h("div", { className: "pet-dial-host" });
      formArea.appendChild(dialHost);
      var dialApplyInFlight = false;
      var currentConfigValues = function () {
        // Persisted config overlaid with in-memory edits, restricted to owned fields.
        var vals = {};
        Object.keys(OWNED).forEach(function (k) {
          if (d.config && Object.prototype.hasOwnProperty.call(d.config, k)) vals[k] = d.config[k];
        });
        Object.keys(Pet.state.configDirty).forEach(function (k) { vals[k] = Pet.state.configDirty[k]; });
        return vals;
      };
      var onSelectPreset = function (preset) {
        if (!preset || !preset.overrides || dialApplyInFlight) return;
        dialApplyInFlight = true;  // in-flight guard, mirrors the Apply button
        Pet.api.putConfig(preset.overrides).then(function (resp) {
          if (resp && resp._status && resp.detail) {
            var raw = Array.isArray(resp.detail) ? resp.detail : [resp.detail];
            var msg = raw.map(function (e) {
              if (!e || typeof e !== "object") return String(e);
              return (e.field || "?") + ": " + (e.message || e.msg || e.detail || String(e));
            }).join("; ");
            alert("Preset apply failed: " + msg);
            return;
          }
          if (resp && resp.error) { alert("Preset apply failed: " + resp.error); return; }
          // Re-render from persisted truth: the merge base is the server-side
          // config, so a preset apply intentionally discards unsaved non-owned
          // edits and resets the dirty map, consistent with the Apply path.
          Pet.state.config = resp.config || Pet.state.config;
          Pet.state.configDirty = {};
          Pet.renderConfig(container);
        }).then(function () { dialApplyInFlight = false; }, function () { dialApplyInFlight = false; });
      };
      var renderDial = function () {
        dialHost.innerHTML = "";
        var activeKey = Pet.resolveActivePreset(currentConfigValues(), d.presets);
        dialHost.appendChild(Pet.renderStrengthDial(d.presets, activeKey, onSelectPreset));
      };
      // Recompute the highlight only when an owned field changes; a non-owned edit
      // never flips the dial.
      var maybeUpdateDial = function (name) { if (OWNED[name]) renderDial(); };
      renderDial();

      var groups = Pet.groupConfigSections(d.fields, d.sections);
      // Declared up front (not inside the loop) so the empty path leaves them
      // safe-to-index {} objects for revealFieldSections (§3e).
      var fieldSection = {};
      var panelsBySection = {};
      // never-throw (PET-99): skip a malformed entry rather than throwing on
      // f.name before the empty-guard / recovery panel can render — mirrors the
      // guard groupConfigSections already applies to the same d.fields.
      d.fields.forEach(function (f) {
        if (!f || typeof f !== "object" || f.name == null) return;
        fieldSection[f.name] = f.section;
      });

      if (groups.length === 0) {
        // Expected-degraded, never-throw (PET-99): no fields, or a registry/field
        // mismatch. Render a neutral panel rather than a blank area.
        formArea.appendChild(Pet.Panel({
          icon: "sliders", title: "Configuration",
          content: Pet.h("div", { className: "mono", style: { fontSize: "12px", color: "var(--tx-faint)", padding: "8px" } }, "No configurable fields."),
        }));
      }

      groups.forEach(function (group) {
        var fields = group.fields;
        var fieldEls = fields.map(function (f) {
          var val = d.config[f.name];
          var control;
          if (f.name === "profile_name") {
            // PET-122: dedicated fetch-sourced control, placed first so no other
            // field matches it and the generic enum/text branches stay unreachable
            // for profile_name (D-OPT1).
            control = Pet.buildProfileControl(f, val, profilesP);
          } else if (f.type === "boolean") {
            var toggleFn = function () {
              val = !val;
              sw.className = "switch" + (val ? " on" : "");
              sw.setAttribute("aria-checked", val ? "true" : "false");
              Pet.state.configDirty[f.name] = val;
              maybeUpdateDial(f.name);
            };
            var sw = Pet.h("button", {
              className: "switch" + (val ? " on" : ""),
              type: "button",
              role: "switch", ariaChecked: val ? "true" : "false", ariaLabel: Pet.humanizeKey(f.name),
              onClick: toggleFn,
            });
            sw.addEventListener("keydown", function (e) {
              if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleFn(); }
            });
            control = sw;
          } else if (f.type === "enum" && f.constraints && f.constraints.values) {
            var seg = Pet.h("div", { className: "seg", role: "radiogroup", ariaLabel: Pet.humanizeKey(f.name) });
            f.constraints.values.forEach(function (opt) {
              var btn = Pet.h("button", {
                className: opt === val ? "on" : "", role: "radio", ariaChecked: opt === val ? "true" : "false",
                onClick: function () {
                  seg.querySelectorAll("button").forEach(function (b) { b.className = ""; b.setAttribute("aria-checked", "false"); });
                  btn.className = "on"; btn.setAttribute("aria-checked", "true");
                  Pet.state.configDirty[f.name] = opt;
                  maybeUpdateDial(f.name);
                }
              }, opt);
              seg.appendChild(btn);
            });
            control = seg;
          } else if (f.type === "number") {
            var inp = Pet.h("input", {
              className: "input mono", type: "number",
              style: { width: "110px", height: "32px" },
              value: val != null ? String(val) : "",
            });
            var c = f.constraints || {};
            if (c.min != null) inp.setAttribute("min", String(c.min));
            if (c.max != null) inp.setAttribute("max", String(c.max));
            var frac = (c.min != null && !Number.isInteger(c.min)) || (c.max != null && c.max <= 1);
            inp.setAttribute("step", frac ? "any" : "1");
            inp.addEventListener("change", function () { Pet.state.configDirty[f.name] = parseFloat(inp.value); maybeUpdateDial(f.name); });
            control = inp;
          } else if (f.redacted) {
            control = Pet.h("span", { className: "mono", style: { fontSize: "12px", color: "var(--tx-faint)" } }, val || "(not set)");
          } else {
            var inp2 = Pet.h("input", {
              className: "input mono", style: { width: "200px", height: "32px" },
              value: val != null ? String(val) : "",
            });
            inp2.addEventListener("change", function () { Pet.state.configDirty[f.name] = inp2.value; maybeUpdateDial(f.name); });
            control = inp2;
          }

          return Pet.h("div", { dataset: { field: f.name }, style: { display: "flex", alignItems: "flex-start", gap: "14px", padding: "12px 0", borderBottom: "1px solid var(--border-soft)" } },
            Pet.h("div", { style: { flex: "1" } },
              Pet.h("div", { style: { fontSize: "13px", fontWeight: "600", color: "var(--tx-bright)" } }, Pet.humanizeKey(f.name)),
              Pet.h("div", { style: { fontSize: "11.5px", color: "var(--tx)", marginTop: "3px" } }, f.help_plain || f.description),
              Pet.h("div", { className: "mono", style: { fontSize: "10px", color: "var(--tx-mut)", marginTop: "3px" } }, f.name)
            ),
            Pet.h("div", { className: "pet-ctrl-wrap", style: { flex: "0 0 auto", display: "flex", flexDirection: "column" } }, control)
          );
        });

        // Seed rule (§3b): read the user-choice map only if the key is present;
        // otherwise the registry/builder default. Never write the map here.
        var collapsed = Object.prototype.hasOwnProperty.call(Pet.state.sectionCollapsed, group.key)
          ? Pet.state.sectionCollapsed[group.key]   // user chose
          : group.default_collapsed;                 // registry/builder default
        // PET-123: prepend the plain-language intro (when present) above the field
        // rows. fieldEls is passed as a direct array child in both branches, so the
        // rows stay at today's DOM depth (Pet.h flattens an array child); the only
        // tree change is the single intro node when copy exists. intro === null is
        // byte-for-byte today's render (D4 / Design Change 3).
        var intro = Pet.sectionIntro(group.description);
        var body = intro
          ? Pet.h("div", {}, intro, fieldEls)
          : Pet.h("div", {}, fieldEls);
        var sectionPanel = Pet.Panel({
          icon: "sliders", title: group.label,
          collapsible: true, collapsed: collapsed,
          onToggle: function (c) { Pet.state.sectionCollapsed[group.key] = c; },
          content: body,
        });
        sectionPanel.dataset.section = group.key;
        panelsBySection[group.key] = sectionPanel;
        formArea.appendChild(sectionPanel);
      });

      // Save bar
      var saveBar = Pet.h("div", { style: { display: "flex", gap: "10px", justifyContent: "flex-end", padding: "10px 0" } },
        Pet.h("button", { className: "btn btn-ghost", onClick: function () {
          Pet.state.configDirty = {};
          Pet.renderConfig(container);
        } }, "Discard"),
        (function () {
          var applyBtn = Pet.h("button", { className: "btn btn-primary", onClick: function () {
            if (Object.keys(Pet.state.configDirty).length === 0) return;
            formArea.querySelectorAll(".pet-field-err").forEach(function (el) { el.remove(); });
            applyBtn.disabled = true;
            Pet.api.putConfig(Pet.state.configDirty).then(function (d) {
              if (d._status && d.detail) {
                var raw = Array.isArray(d.detail) ? d.detail : [d.detail];
                var details = raw.map(function (el) {
                  if (typeof el === "string") return { field: "?", message: el };
                  if (!el || typeof el !== "object") return { field: "?", message: String(el) };
                  return { field: el.field || el.name || el.path || "?", message: el.message || el.msg || el.detail || String(el) };
                });
                // §3f: expand any default-collapsed section that owns an errored
                // field BEFORE the .pet-field-err nodes are appended, so the
                // inline error lands in a visible (un-hidden) body. Synchronous
                // class removal in petSetCollapsed un-hides it this same tick.
                Pet.revealFieldSections(
                  details.map(function (e) { return e.field; }), fieldSection, panelsBySection
                );
                details.forEach(function (err) {
                  if (err.field === "?") return;
                  var fieldEl = null;
                  formArea.querySelectorAll("[data-field]").forEach(function (el) {
                    if (el.dataset.field === err.field) fieldEl = el;
                  });
                  if (fieldEl) {
                    var wrapper = fieldEl.querySelector(".pet-ctrl-wrap");
                    (wrapper || fieldEl).appendChild(Pet.h("div", {
                      className: "pet-field-err",
                      style: { color: "var(--err)", fontSize: "11px", marginTop: "4px" }
                    }, err.message));
                  }
                });
                if (!formArea.querySelector(".pet-field-err")) {
                  var msg = details.map(function (e) { return e.field + ": " + e.message; }).join("; ");
                  formArea.insertBefore(Pet.h("div", {
                    className: "pet-field-err",
                    style: { color: "var(--err)", fontSize: "12px", padding: "8px 12px", background: "var(--bg-raised)", borderRadius: "var(--r-card)", marginBottom: "8px" }
                  }, msg), formArea.firstChild);
                }
                return;
              }
              if (d.error) {
                formArea.insertBefore(Pet.h("div", {
                  className: "pet-field-err",
                  style: { color: "var(--err)", fontSize: "12px", padding: "8px 12px", background: "var(--bg-raised)", borderRadius: "var(--r-card)", marginBottom: "8px" }
                }, "Couldn't save: " + d.error + ". Your changes are kept; try Apply again."), formArea.firstChild);
                return;
              }
              Pet.state.config = d.config || Pet.state.config;
              Pet.state.configDirty = {};
              formArea.insertBefore(Pet.h("div", {
                className: "notice",
                style: { background: "var(--ok-soft)", borderColor: "rgba(63,185,80,.3)", color: "var(--ok)", marginBottom: "8px" }
              }, Pet.Icon("check"), Pet.h("span", {}, Pet.h("b", {}, "Configuration saved."), " Active sessions use the previous config until restarted.")), formArea.firstChild);
              setTimeout(function () { if (Pet.state.tab === "cfg") Pet.renderConfig(container); }, 1500);
            }).then(function () { applyBtn.disabled = false; }, function () { applyBtn.disabled = false; });
          } }, Pet.Icon("check"), " Apply");
          return applyBtn;
        })()
      );
      formArea.appendChild(saveBar);
    });
  };

  Pet.renderAbout = function (container) {
    container.innerHTML = "";
    var wrapper = Pet.h("div", { style: { display: "flex", flexDirection: "column", gap: "14px", maxWidth: "600px" } });

    // Header
    wrapper.appendChild(Pet.Panel({
      icon: "shieldCheck", title: "Petasos",
      content: Pet.h("div", {},
        Pet.h("div", { style: { fontSize: "14px", color: "var(--tx-bright)", fontWeight: "600" } }, "Petasos"),
        // PET-127: text-independent [data-pet-ver] anchor (retires the .mono + "v..."
        // text-coupled selector). Seeds a skeleton bar + aria-busy/aria-label; the
        // fill below repopulates it in place (so NO role=status here — see Decision 4).
        Pet.h("div", { className: "mono", dataset: { petVer: "1" }, ariaBusy: true, ariaLabel: "Loading version",
                       style: { fontSize: "11px", color: "var(--tx-faint)", marginTop: "4px" } },
          Pet.skel(48, 11)),
        Pet.h("span", { className: "pill ok", style: { marginTop: "8px", height: "18px", fontSize: "10px" } }, "MIT License")
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
        Pet.h("div", { style: { fontSize: "12.5px", color: "var(--tx-mut)", lineHeight: "1.6", maxWidth: "400px", margin: "0 auto 16px" } },
          "Every feature is free, forever. If this saved your team from a bad day, a coffee keeps the lights on."
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

  var _container = null;
  var _tabStrip = null;
  // PET-102: one-shot guard so the dashboard seeds the server's pre-existing
  // scan-history ring buffer exactly once per mount (not on every SSE re-render).
  // Reset in Pet.unmount AND at the top of Pet.mount (double-mount hardening).
  var _historySeeded = false;
  // PET-127: gate the scanner-health skeleton. renderDashboard re-runs on every
  // SSE/poll frame, so an unconditional skeleton would re-flash; this flips true
  // at every /health settle (in-render success+error arms AND the 10s poll), never
  // at paint time, and resets only in mount/unmount (not switchTab) so an
  // obs->other->obs round-trip reuses cached rows. NOT keyed off scannerHealth
  // (inits to [], truthy, and []-length collides with the genuine zero-backends
  // case where scannerHealthRows([]) is a false "unavailable" error).
  var _healthLoaded = false;
  // PET-111: _armedSeeded — fetch the Equipped/Unequipped bit once per obs ENTRY
  // (mount or switchTab→obs), never on every SSE/poll re-render. _armedBusy — a
  // POST /armed is in flight; suppress concurrent toggles and seed-overwrites.
  var _armedSeeded = false;
  var _armedBusy = false;
  var _armedConfirmPending = false;   // disarming requires a confirming 2nd click
  var _armedConfirmTimer = null;
  // The pending-disarm confirmation is per-view, ephemeral UI intent. Reset it on
  // every tab change, mount, and unmount so a half-finished two-step disarm cannot
  // carry across navigation or remount, and the 4s timer never fires post-teardown.
  function clearArmedConfirm() {
    _armedConfirmPending = false;
    if (_armedConfirmTimer) { clearTimeout(_armedConfirmTimer); _armedConfirmTimer = null; }
  }

  var TABS = [
    { key: "obs", icon: "activity", label: "Observability" },
    { key: "play", icon: "beaker", label: "Scan Playground" },
    { key: "cfg", icon: "sliders", label: "Config Editor" },
    { key: "about", icon: "shieldCheck", label: "About" },
  ];

  Pet.switchTab = function (name) {
    Pet.state.tab = name;
    clearArmedConfirm();  // a tab change abandons any half-finished two-step disarm
    if (_tabStrip) {
      _tabStrip.querySelectorAll(".tab").forEach(function (t) {
        var active = t.dataset.key === name;
        t.className = "tab" + (active ? " active" : "");
        t.setAttribute("aria-selected", active ? "true" : "false");
        t.tabIndex = active ? 0 : -1;
      });
    }
    if (!_container) return;
    _container.innerHTML = "";
    // PET-111: re-fetch the armed bit on each obs ENTRY (armed has no SSE
    // reconciliation, unlike scan history) — but not on every re-render.
    if (name === "obs") { _armedSeeded = false; Pet.renderDashboard(_container); }
    else if (name === "play") Pet.renderPlayground(_container);
    else if (name === "cfg") Pet.renderConfig(_container);
    else if (name === "about") Pet.renderAbout(_container);
  };

  Pet.mount = function (el) {
    el.innerHTML = "";
    _historySeeded = false;  // PET-102: re-seed on a re-mount that skipped unmount (plugin hot-reload)
    _healthLoaded = false;   // PET-127: re-show the scanner-health skeleton on (re-)mount
    _armedSeeded = false;    // PET-111: re-fetch the armed bit on (re-)mount
    clearArmedConfirm();     // drop any stale disarm-confirm + timer from a skipped unmount

    // Pane header
    var titleRow = Pet.h("div", { className: "pane-titlerow" },
      Pet.h("div", { className: "pane-mark" },
        Pet.h("img", { src: Pet.asset("img/petasos-helmet.png"), alt: "Petasos winged helmet" })
      ),
      Pet.h("div", {},
        Pet.h("div", { className: "pane-name" }, "Petasos"),
        Pet.h("div", { className: "pane-sub" }, "guardrail pipeline")
      )
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

    _container = Pet.h("div", { className: "content" });
    var paneBody = Pet.h("div", { className: "pane-body" }, _container);
    el.appendChild(paneBody);

    Pet.switchTab("obs");
    Pet.sse.connect();
    startPolling();
  };

  Pet.unmount = function () {
    Pet.sse.disconnect();
    stopPolling();
    _container = null;
    _tabStrip = null;
    _historySeeded = false;  // PET-102: next mount re-seeds the history buffer
    _healthLoaded = false;   // PET-127: next mount re-shows the scanner-health skeleton
    _armedSeeded = false;    // PET-111: next mount re-fetches the armed bit
    clearArmedConfirm();     // clear the pending-disarm confirm + its 4s timer on teardown
  };

  window.__PETASOS_CONSOLE__ = Pet;
})();
