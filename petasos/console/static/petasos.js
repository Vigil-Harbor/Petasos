/* petasos.js — Petasos Console frontend (vanilla JS, no build step)
   Exposes window.__PETASOS_CONSOLE__ namespace. */
(function () {
  "use strict";
  var Pet = {};

  // ── DOM helpers ──

  Pet.h = function (tag, attrs) {
    var el = document.createElement(tag);
    if (attrs) {
      if (attrs.className) el.className = attrs.className;
      if (attrs.style) Object.assign(el.style, attrs.style);
      if (attrs.title) el.title = attrs.title;
      if (attrs.tabIndex != null) el.tabIndex = attrs.tabIndex;
      if (attrs.type) el.type = attrs.type;
      if (attrs.value != null) el.value = attrs.value;
      if (attrs.placeholder) el.placeholder = attrs.placeholder;
      if (attrs.href) el.href = attrs.href;
      if (attrs.target) el.target = attrs.target;
      if (attrs.rel) el.rel = attrs.rel;
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

  Pet.HelpTip = function (html) {
    var btn = Pet.h("span", { className: "help", tabIndex: "0" });
    btn.appendChild(Pet.Icon("q"));
    var tip = Pet.h("span", { className: "tip" });
    tip.innerHTML = html;
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
  Pet.Panel = function (opts) {
    var head = Pet.h("div", { className: "panel-head" });
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
    var panel = Pet.h("div", { className: "panel" }, head, body);
    if (opts.style) Object.assign(panel.style, opts.style);
    return panel;
  };

  // ── State ──
  Pet.state = {
    tab: "obs",
    config: null,
    configFields: null,
    configDirty: {},
    scanHistory: [],
    alerts: [],
    auditLog: [],
    scannerHealth: [],
    pipelineHealth: null,
    lastScanResult: null,
    profiles: [],
    about: null,
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
              if (r.done) { self._enableFallback(); return; }
              buf += dec.decode(r.value, { stream: true });
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
        Pet.state.scanHistory.unshift(d);
        if (Pet.state.scanHistory.length > 500) Pet.state.scanHistory.length = 500;
        if (Pet.state.tab === "obs" && _container) Pet.renderDashboard(_container);
      } else if (evType === "audit") {
        Pet.state.auditLog.unshift(d);
        if (Pet.state.auditLog.length > 1000) Pet.state.auditLog.length = 1000;
      } else if (evType === "alert") {
        Pet.state.alerts.unshift(d);
        if (Pet.state.alerts.length > 200) Pet.state.alerts.length = 200;
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
    var fetchData = function () {
      Pet.api.getScanHistory(100).then(function (d) {
        if (!d.error && d.entries && Array.isArray(d.entries)) {
          Pet.state.scanHistory = d.entries;
          if (Pet.state.tab === "obs" && _container) Pet.renderDashboard(_container);
        }
      });
    };
    fetchData();
    _fallbackPollInterval = setInterval(fetchData, 10000);
  }
  function stopFallbackPolling() {
    if (_fallbackPollInterval) { clearInterval(_fallbackPollInterval); _fallbackPollInterval = null; }
  }

  // ── Surface renderers ──

  Pet.renderDashboard = function (container) {
    container.innerHTML = "";
    var wrapper = Pet.h("div", { style: { display: "flex", flexDirection: "column", gap: "12px", height: "100%" } });

    // Loading state or metrics
    var metricsRow = Pet.h("div", { style: { display: "flex", gap: "12px" } });
    var loadingTile = function (label) {
      return Pet.Panel({ icon: "activity", title: label, content: Pet.h("div", { className: "num", style: { fontSize: "24px", color: "var(--tx-bright)" } }, "...") });
    };
    metricsRow.appendChild(loadingTile("scans"));
    metricsRow.appendChild(loadingTile("blocked"));
    metricsRow.appendChild(loadingTile("avg latency"));
    metricsRow.appendChild(loadingTile("sessions"));
    wrapper.appendChild(metricsRow);

    // Scanner health
    var healthPanel = Pet.Panel({
      icon: "radar", title: "scanner health", place: "loaded backends", flush: true,
      help: Pet.HelpTip("<b>Scanner Health</b> — status of each loaded scanner backend (MinimalScanner, LLM Guard, Presidio, etc). <code>ready</code> means the scanner is initialized and processing."),
      content: Pet.h("div", { style: { padding: "12px" } },
        Pet.h("div", { className: "mono", style: { color: "var(--tx-faint)", fontSize: "12px" } }, "Loading scanner status...")
      ),
    });
    wrapper.appendChild(healthPanel);

    // Scan history
    var historyPanel = Pet.Panel({
      icon: "list", title: "scan history", place: "recent evaluations", flush: true,
      help: Pet.HelpTip("<b>Scan History</b> — recent pipeline scans with severity, direction, and timing. Each row is one <code>Pipeline.evaluate()</code> call."),
      content: Pet.h("div", { style: { padding: "12px" } },
        Pet.h("div", { className: "mono", style: { color: "var(--tx-faint)", fontSize: "12px" } }, "No scans recorded yet.")
      ),
    });
    wrapper.appendChild(historyPanel);

    container.appendChild(wrapper);

    // Fetch initial data
    Pet.api.getHealth().then(function (d) {
      if (!d.error) {
        Pet.state.scannerHealth = d.scanners || [];
        Pet.state.pipelineHealth = d.pipeline || null;
      }
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

    var resultArea = Pet.h("div", { style: { flex: "1", minHeight: "0" } });

    var dirBtn = { dir: "inbound" };
    var dirToggle = Pet.h("div", { className: "seg" });
    var inBtn = Pet.h("button", { className: "on", onClick: function () { dirBtn.dir = "inbound"; inBtn.className = "on"; outBtn.className = ""; } }, "inbound");
    var outBtn = Pet.h("button", { onClick: function () { dirBtn.dir = "outbound"; outBtn.className = "on"; inBtn.className = ""; } }, "outbound");
    dirToggle.appendChild(inBtn);
    dirToggle.appendChild(outBtn);

    var sessionInput = Pet.h("input", { className: "input mono", style: { width: "120px", height: "30px", fontSize: "12px" }, placeholder: "session_id" });

    var scanBtn = Pet.h("button", { className: "btn btn-primary btn-sm", onClick: function () {
      var text = textArea.value;
      if (!text || !text.trim()) return;
      scanBtn.textContent = "Scanning...";
      Pet.api.postScan(text, dirBtn.dir, sessionInput.value || null).then(function (d) {
        scanBtn.textContent = "";
        scanBtn.appendChild(Pet.Icon("bolt"));
        scanBtn.appendChild(document.createTextNode(" Scan"));
        resultArea.innerHTML = "";
        if (d.error || d.detail) {
          resultArea.appendChild(Pet.h("div", { style: { color: "var(--crit)", padding: "12px" } }, d.error || JSON.stringify(d.detail)));
          return;
        }
        Pet.state.lastScanResult = d;
        var r = d.result;

        // Verdict
        var verdict = r.safe
          ? Pet.h("span", { className: "pill ok", style: { height: "18px", fontSize: "10px" } }, "safe")
          : Pet.h("span", { className: "pill err", style: { height: "18px", fontSize: "10px" } }, "blocked");

        var summary = Pet.h("div", { style: { display: "flex", alignItems: "center", gap: "10px", marginBottom: "12px" } },
          verdict,
          Pet.h("span", { style: { fontSize: "12px", color: "var(--tx-mut)" } }, r.findings.length + " findings")
        );
        resultArea.appendChild(summary);

        // Findings
        if (r.findings.length > 0) {
          var findingsPanel = Pet.Panel({
            icon: "radar", title: "findings", place: "detections by scanner",
            help: Pet.HelpTip("<b>Findings</b> — individual detections from each scanner. Severity ranges from <code>INFO</code> to <code>CRITICAL</code>. High+ on dangerous tools triggers a block."),
            content: Pet.h("div", { className: "vlist", style: { gap: "8px" } },
              r.findings.map(function (f) {
                var v = SEV[f.severity] || SEV.info;
                var finding = Pet.h("div", { className: "finding" });
                var rail = Pet.h("div", { className: "rail", style: { background: v.col } });
                var body = Pet.h("div", { className: "body" },
                  Pet.h("div", { style: { display: "flex", gap: "8px", alignItems: "center" } },
                    Pet.h("span", { className: "rid" }, f.rule_id),
                    Pet.h("span", { className: "mono", style: { marginLeft: "auto", fontSize: "10px", color: "var(--tx-faint)" } }, f.scanner_name || "")
                  ),
                  Pet.h("div", { className: "msg" }, f.message || ""),
                  f.matched_text ? Pet.h("span", { className: "matched" }, f.matched_text) : null
                );
                finding.appendChild(rail);
                finding.appendChild(Pet.SevBadge(f.severity));
                finding.appendChild(body);
                return finding;
              })
            ),
          });
          resultArea.appendChild(findingsPanel);
        }

        // Normalized diff
        if (d.normalized_text && d.normalized_text !== text) {
          resultArea.appendChild(Pet.Panel({
            icon: "trending", title: "normalization", place: "before → after",
            content: Pet.h("div", { className: "mono", style: { fontSize: "11.5px", lineHeight: "1.7" } },
              Pet.h("div", { style: { color: "var(--tx-ghost)" } }, "raw: ", Pet.h("span", { style: { color: "var(--tx-mut)" } }, text)),
              Pet.h("div", { style: { color: "var(--tx-ghost)" } }, "norm: ", Pet.h("span", { style: { color: "var(--tx)" } }, d.normalized_text))
            ),
          }));
        }

        // Anonymized output
        if (r.sanitized_content) {
          resultArea.appendChild(Pet.Panel({
            icon: "shieldCheck", title: "anonymized output", place: "PII redacted",
            content: Pet.h("div", { className: "mono", style: { fontSize: "12px", color: "var(--tx-mut)", lineHeight: "1.7" } }, r.sanitized_content),
          }));
        }

        // Session overlay
        if (r.session_score != null || r.escalation_tier) {
          var stats = Pet.h("div", { style: { display: "flex", gap: "10px" } });
          if (r.session_score != null) {
            stats.appendChild(Pet.h("div", { style: { flex: "1", background: "var(--bg-raised)", border: "1px solid var(--border)", borderRadius: "var(--r-card)", padding: "7px 11px" } },
              Pet.h("div", { className: "eyebrow" }, "session_score"),
              Pet.h("div", { className: "num", style: { fontSize: "18px", fontWeight: "700", color: "var(--amber-bright)" } }, r.session_score.toFixed(3))
            ));
          }
          if (r.escalation_tier) {
            stats.appendChild(Pet.h("div", { style: { flex: "1", background: "var(--bg-raised)", border: "1px solid var(--border)", borderRadius: "var(--r-card)", padding: "7px 11px" } },
              Pet.h("div", { className: "eyebrow" }, "escalation_tier"),
              Pet.h("div", { className: "num", style: { fontSize: "18px", fontWeight: "700", color: "var(--crit)" } }, r.escalation_tier)
            ));
          }
          resultArea.appendChild(Pet.Panel({ icon: "user", title: "session overlay", place: "frequency + escalation", help: Pet.HelpTip("<b>Session Overlay</b> — cumulative session risk score and escalation tier. Score rises with repeated violations; tier thresholds trigger progressively stricter enforcement."), content: stats }));
        }
      });
    } });
    scanBtn.appendChild(Pet.Icon("bolt"));
    scanBtn.appendChild(document.createTextNode(" Scan"));

    var controls = Pet.h("div", { style: { display: "flex", alignItems: "center", gap: "10px" } }, dirToggle, sessionInput, scanBtn);

    var inspectPanel = Pet.Panel({
      icon: "beaker", title: "inspect", place: "scan playground",
      help: Pet.HelpTip("<b>Scan Playground</b> — paste text and run it through the full pipeline. Choose <code>inbound</code> (user→agent) or <code>outbound</code> (agent→user) direction. Optionally bind to a session ID for frequency tracking."),
      content: Pet.h("div", { style: { display: "flex", flexDirection: "column", gap: "10px" } }, textArea, controls),
    });

    wrapper.appendChild(inspectPanel);
    wrapper.appendChild(resultArea);
    container.appendChild(wrapper);
  };

  Pet.renderConfig = function (container) {
    container.innerHTML = "";
    var wrapper = Pet.h("div", { style: { display: "flex", flexDirection: "column", gap: "12px", height: "100%" } });

    var notice = Pet.h("div", { className: "notice", style: { flex: "0 0 auto" } },
      Pet.Icon("warn"),
      Pet.h("span", {}, Pet.h("b", {}, "Changes are saved to config.yaml."), " Active agent sessions use the previous config until restarted.")
    );
    wrapper.appendChild(notice);

    var formArea = Pet.h("div", { style: { flex: "1", overflowY: "auto" } },
      Pet.h("div", { className: "mono", style: { color: "var(--tx-faint)", padding: "20px" } }, "Loading configuration...")
    );
    wrapper.appendChild(formArea);
    container.appendChild(wrapper);

    Pet.api.getConfig().then(function (d) {
      if (d.error || !d.config || !d.fields) {
        formArea.innerHTML = "";
        formArea.appendChild(Pet.h("div", { style: { padding: "20px", color: "var(--err)", fontSize: "12px", fontFamily: "var(--font-mono)" } },
          d.error ? "Config unavailable: " + d.error : "Unexpected response from API"));
        return;
      }
      Pet.state.config = d.config;
      Pet.state.configFields = d.fields;
      formArea.innerHTML = "";

      var sections = {};
      d.fields.forEach(function (f) {
        if (!sections[f.section]) sections[f.section] = [];
        sections[f.section].push(f);
      });

      Object.keys(sections).forEach(function (section) {
        var fields = sections[section];
        var fieldEls = fields.map(function (f) {
          var val = d.config[f.name];
          var control;
          if (f.type === "boolean") {
            var toggleFn = function () {
              val = !val;
              sw.className = "switch" + (val ? " on" : "");
              Pet.state.configDirty[f.name] = val;
            };
            var sw = Pet.h("button", {
              className: "switch" + (val ? " on" : ""),
              type: "button",
              onClick: toggleFn,
            });
            sw.addEventListener("keydown", function (e) {
              if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleFn(); }
            });
            control = sw;
          } else if (f.type === "enum" && f.constraints && f.constraints.values) {
            var seg = Pet.h("div", { className: "seg" });
            f.constraints.values.forEach(function (opt) {
              var btn = Pet.h("button", { className: opt === val ? "on" : "", onClick: function () {
                seg.querySelectorAll("button").forEach(function (b) { b.className = ""; });
                btn.className = "on";
                Pet.state.configDirty[f.name] = opt;
              } }, opt);
              seg.appendChild(btn);
            });
            control = seg;
          } else if (f.type === "number") {
            var inp = Pet.h("input", {
              className: "input mono", type: "number",
              style: { width: "110px", height: "32px" },
              value: val != null ? String(val) : "",
            });
            inp.addEventListener("change", function () { Pet.state.configDirty[f.name] = parseFloat(inp.value); });
            control = inp;
          } else if (f.redacted) {
            control = Pet.h("span", { className: "mono", style: { fontSize: "12px", color: "var(--tx-faint)" } }, val || "(not set)");
          } else {
            var inp2 = Pet.h("input", {
              className: "input mono", style: { width: "200px", height: "32px" },
              value: val != null ? String(val) : "",
            });
            inp2.addEventListener("change", function () { Pet.state.configDirty[f.name] = inp2.value; });
            control = inp2;
          }

          return Pet.h("div", { dataset: { field: f.name }, style: { display: "flex", alignItems: "flex-start", gap: "14px", padding: "12px 0", borderBottom: "1px solid var(--border-soft)" } },
            Pet.h("div", { style: { flex: "1" } },
              Pet.h("div", { className: "mono", style: { fontSize: "12.5px", fontWeight: "600", color: "var(--tx-bright)" } }, f.name),
              Pet.h("div", { style: { fontSize: "11.5px", color: "var(--tx-faint)", marginTop: "3px" } }, f.description)
            ),
            Pet.h("div", { className: "pet-ctrl-wrap", style: { flex: "0 0 auto", display: "flex", flexDirection: "column" } }, control)
          );
        });

        var sectionPanel = Pet.Panel({
          icon: "sliders", title: section, content: Pet.h("div", {}, fieldEls),
        });
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
                alert("Save failed: " + d.error);
                return;
              }
              Pet.state.config = d.config || Pet.state.config;
              Pet.state.configDirty = {};
              Pet.renderConfig(container);
            }).then(function () { applyBtn.disabled = false; }, function () { applyBtn.disabled = false; });
          } }, Pet.Icon("check"), " Apply config");
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
        Pet.h("div", { className: "mono", style: { fontSize: "11px", color: "var(--tx-faint)", marginTop: "4px" } }, "v..."),
        Pet.h("span", { className: "pill ok", style: { marginTop: "8px", height: "18px", fontSize: "10px" } }, "MIT License")
      ),
    }));

    // Links
    wrapper.appendChild(Pet.Panel({
      icon: "flow", title: "Links",
      content: Pet.h("div", {},
        Pet.h("a", { href: "https://github.com/Vigil-Harbor/Petasos", target: "_blank", rel: "noopener", className: "link", style: { display: "block", padding: "6px 0" } }, "Repository"),
        Pet.h("a", { href: "https://github.com/Vigil-Harbor/Petasos/issues", target: "_blank", rel: "noopener", className: "link", style: { display: "block", padding: "6px 0" } }, "Issue Tracker")
      ),
    }));

    // Donation
    wrapper.appendChild(Pet.Panel({
      icon: "caduceus", title: "Support",
      help: Pet.HelpTip("<b>Support</b> — Petasos is free and open source (MIT). Sponsorship helps fund continued development but unlocks nothing — every feature is available to everyone."),
      style: { border: "1px solid rgba(232,144,28,.3)" },
      bodyStyle: { background: "rgba(232,144,28,.06)" },
      content: Pet.h("div", { style: { textAlign: "center", padding: "12px 0" } },
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
        Pet.h("div", {}, "Vigil Harbor — maintainer"),
        Pet.h("div", {}, "Built with FastAPI, Python, vanilla JS")
      ),
    }));

    container.appendChild(wrapper);

    // Fill version from API
    Pet.api.getAbout().then(function (d) {
      if (!d.error) {
        Pet.state.about = d;
        var ver = container.querySelector(".mono");
        if (ver && ver.textContent.indexOf("v...") >= 0) ver.textContent = "v" + d.version;
      }
    });
  };

  // ── Tab controller ──

  var _container = null;
  var _tabStrip = null;

  var TABS = [
    { key: "obs", icon: "activity", label: "Observability" },
    { key: "play", icon: "beaker", label: "Scan Playground" },
    { key: "cfg", icon: "sliders", label: "Config Editor" },
    { key: "about", icon: "shieldCheck", label: "About" },
  ];

  Pet.switchTab = function (name) {
    Pet.state.tab = name;
    if (_tabStrip) {
      _tabStrip.querySelectorAll(".tab").forEach(function (t) {
        t.className = "tab" + (t.dataset.key === name ? " active" : "");
      });
    }
    if (!_container) return;
    _container.innerHTML = "";
    if (name === "obs") Pet.renderDashboard(_container);
    else if (name === "play") Pet.renderPlayground(_container);
    else if (name === "cfg") Pet.renderConfig(_container);
    else if (name === "about") Pet.renderAbout(_container);
  };

  Pet.mount = function (el) {
    el.innerHTML = "";

    // Pane header
    var titleRow = Pet.h("div", { className: "pane-titlerow" },
      Pet.h("div", { className: "pane-mark" }, Pet.Icon("shieldCheck")),
      Pet.h("div", {},
        Pet.h("div", { className: "pane-name" }, "Petasos"),
        Pet.h("div", { className: "pane-sub" }, "guardrail pipeline")
      )
    );

    _tabStrip = Pet.h("div", { className: "tabs" });
    TABS.forEach(function (t) {
      var tab = Pet.h("div", { className: "tab" + (t.key === "obs" ? " active" : ""), dataset: { key: t.key }, onClick: function () { Pet.switchTab(t.key); } },
        Pet.Icon(t.icon), " " + t.label
      );
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
  };

  window.__PETASOS_CONSOLE__ = Pet;
})();
