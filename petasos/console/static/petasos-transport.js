/* Owns: token, auth, API, SSE, polling, and scope plumbing. Depends on: core state and primitives; Pet render callbacks. */
(function () {
  "use strict";
  var Pet = window.__PETASOS_CONSOLE__;
  var actual = Pet && Pet._moduleState ? Pet._moduleState.last : "missing";
  if (actual !== "core") throw new Error("petasos-transport expected module core, got " + actual);

  // ── PET-129: console token store + 401 auth chokepoint ──
  // PET-125 shipped an optional, off-by-default PETASOS_CONSOLE_TOKEN Bearer gate on
  // every standalone /api/* route (server.py:_require_console_token). This client
  // teaches the browser about that credential: it stores the operator-supplied token
  // here and attaches it on the standalone path only (D1). The embedded Hermes path
  // authenticates through its own X-Hermes-Session-Token mount and must never gain a
  // Petasos bearer (no double-credentialing).
  //
  // Persistence is sessionStorage (D2): survives a reload within the tab, dies when
  // the tab closes; a deliberate middle ground between in-memory (re-enter on every
  // reload) and localStorage (a long-lived bearer reachable by any script on the
  // origin indefinitely). The store NEVER throws to its callers: sessionStorage can be
  // absent (a headless node:vm load) or throw on setItem (private-browsing modes), so
  // every access is wrapped and falls back to an in-module in-memory value.
  var _UNSET = {};      // sentinel: no in-session set()/clear() has run yet
  var _tokenMem = _UNSET; // in-memory truth once set/clear runs; falls back to sessionStorage before that
  var _TOKEN_KEY = "petasos.console.token";
  Pet.token = {
    get: function () {
      // In-session truth wins: once set()/clear() has run, _tokenMem is authoritative
      // even if its sessionStorage write threw — so a failed write never lets get()
      // return a stale persisted token. Fall back to sessionStorage only before the
      // first set/clear (so an operator's token survives a reload within the tab).
      if (_tokenMem !== _UNSET) return _tokenMem;
      try {
        if (typeof sessionStorage !== "undefined" && sessionStorage) {
          var v = sessionStorage.getItem(_TOKEN_KEY);
          if (v != null) return v;
        }
      } catch (_) {}
      return null;
    },
    set: function (value) {
      var v = value == null ? "" : String(value);
      _tokenMem = v; // set the in-memory mirror FIRST so a throwing setItem still round-trips
      try {
        if (typeof sessionStorage !== "undefined" && sessionStorage) sessionStorage.setItem(_TOKEN_KEY, v);
      } catch (_) {}
      // D2 stale-submit guard: every credential change advances the auth generation
      // so reads issued under a superseded token (their on401 included) are dropped.
      Pet.auth._gen++;
    },
    clear: function () {
      _tokenMem = null;
      try {
        if (typeof sessionStorage !== "undefined" && sessionStorage) sessionStorage.removeItem(_TOKEN_KEY);
      } catch (_) {}
      Pet.auth._gen++;
    },
  };

  // Pet.auth.on401 is the one transport-agnostic 401 chokepoint (D3). It keys strictly
  // on `_status === 401` (NOT on `.error`): a FastAPI 401 JSON body is { detail,
  // _status: 401 } with no `.error` key, so the readers' `if (!d.error)` gate treats it
  // as an empty success and the stale optimistic state survives. on401 must therefore
  // be the FIRST statement of every /api reader's `.then`, strictly before any shape
  // check. Keyed on _status (not "is standalone"), it would also cover a future
  // embedded 401 without a rewrite (D-EMBEDDED-PARITY, forward-looking).
  Pet.auth = {
    _gen: 0, // D2 stale-submit generation counter; bumped on every token set/clear

    on401: function (d) {
      if (!(d && d._status === 401)) return false;
      Pet.auth._enterAuthRequired();
      return true;
    },

    // Idempotent transition into the authenticate state. Safe to run on every 401 and
    // shared with the manual "clear token" affordance (D2): stop both polls, drop the
    // SSE stream (resetting _usingFallback), clear the optimistic armed reassurance so
    // the banner cannot read EQUIPPED, un-stick the connectivity blip, and re-render.
    _enterAuthRequired: function () {
      Pet.state.authRequired = true;
      Pet._poll.stopHealth();
      Pet._poll.stopFallback();
      // PET-166 (D3): the scoped 30 s poll stops with the other transports; the gate
      // in _syncScopePoll reads authRequired, so this clears the singleton timer.
      if (typeof _syncScopePoll === "function") _syncScopePoll();
      if (Pet.sse) Pet.sse.disconnect(); // aborts SSE, resets _usingFallback, stops the fallback poll
      Pet._runtime.armedSeeded = false;   // force a re-seed from server truth after re-auth (edge F-3)
      Pet._runtime.historySeeded = false; // ditto for the scan-history buffer
      Pet._runtime.historyPaging = false; Pet._runtime.historyPagingGen++; // PET-152: drop any in-flight paging re-mint; its stale .then checks gen and bails
      Pet.state.armed = null; // unknown until a verified read; bannerView keys authRequired first regardless
      if (Pet.updateConnStatus) Pet.updateConnStatus(); // F-8: don't leave the blip stuck on POLLING
      if (Pet._runtime.container && Pet.renderDashboard) Pet.renderDashboard(Pet._runtime.container);
    },

    // D2: store the submitted token and run the D4 resume sequence. Called by the
    // authenticate panel's Unlock control; returns a promise of { ok, message? } so a
    // wrong/transient result can re-enable the control with a reason.
    submitToken: function (value) {
      Pet.token.set(value); // bumps _gen
      return Pet.auth._resume();
    },

    // D2: explicit "clear token" affordance. Runs the SAME idempotent teardown as
    // on401 (not a mere panel swap) so a manual clear cannot leave polls running or
    // flash a stale EQUIPPED banner (edge F-9).
    clearToken: function () {
      Pet.token.clear(); // bumps _gen
      Pet.auth._enterAuthRequired();
    },

    // D4 re-auth resume. Verification read mirrors the mount sequence (getArmed, then
    // getHealth). The captured generation (D2) gates reconciliation: a response from a
    // superseded token (including its 401) is dropped, so a wrong-then-correct
    // double-submit cannot let the wrong token's stale 401 tear down the correct
    // token's session (edge F-6). authRequired is cleared ONLY after the verification
    // read returns a non-401, well-shaped body (not optimistically on submit).
    // PET-192: both continuations also drop a superseded host scope (PET-166 D17).
    _resume: function () {
      var gen = Pet.auth._gen;
      var scopeGen = Pet._runtime.scopeGen; // PET-192 / D17: one send-time scope for the whole resume
      Pet._runtime.armedSeeded = false;   // re-derive from server truth, regardless of any stray frame (edge F-3)
      Pet._runtime.historySeeded = false;
      Pet._runtime.historyPaging = false; Pet._runtime.historyPagingGen++; // PET-152: supersede any in-flight paging re-mint across the re-auth resume
      return Pet.api.getArmed().then(function (d) {
        if (gen !== Pet.auth._gen || scopeGen !== Pet._runtime.scopeGen) return { ok: false, stale: true }; // superseded; drop (incl. a stale 401)
        if (d && d._status === 401) return { ok: false, message: "Authentication failed. Check the token and retry." };
        // round-2 edge F-3: a transient non-401 error (no boolean armed) keeps the
        // authenticate state and re-enables the control with a distinct message.
        if (!(d && typeof d.armed === "boolean")) return { ok: false, message: "Could not verify the token (transient error). Retry." };
        Pet.state.authRequired = false;
        Pet.state.armed = d.armed; // seed from the authenticated read, not the stale default
        Pet._runtime.armedSeeded = true;       // armed is verified; skip the dashboard's mount re-fetch
        return Pet.api.getHealth().then(function (h) {
          // A token set/clear or host scope change during the /health round-trip
          // supersedes this resume. Drop the whole stale
          // continuation — not just the health seed — so it cannot restart transports
          // or re-render the dashboard under a superseded generation (e.g. re-arming
          // polling/SSE that a concurrent clearToken just tore down).
          if (gen !== Pet.auth._gen || scopeGen !== Pet._runtime.scopeGen) return { ok: false, stale: true };
          if (h && !h.error && h._status !== 401) {
            Pet._runtime.healthLoaded = true;
            Pet.state.scannerHealth = h.scanners || [];
            Pet.state.pipelineHealth = h.pipeline || null;
            Pet.state.integrityHealth = h.integrity || null; // PET-157: mirror pipelineHealth
            Pet.adoptSelfmodTotal(Pet.state.pipelineHealth); // PET-165: re-sync the tile count
          }
          Pet._poll.startHealth();
          if (Pet.sse && Pet.sse.connect) Pet.sse.connect();
          if (Pet.updateConnStatus) Pet.updateConnStatus();
          if (Pet._runtime.container && Pet.renderDashboard) Pet.renderDashboard(Pet._runtime.container);
          return { ok: true };
        });
      });
    },
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
      // PET-129 D1: attach the optional console bearer on the standalone path only
      // (this branch is reached only when there is no embedded Hermes SDK above). Sent
      // verbatim as "Bearer " + token to match the server's case-sensitive scheme check
      // and its hmac.compare_digest verbatim comparison (server.py). Shallow-copy so a
      // caller's opts/headers literal (e.g. _post's { "Content-Type": ... }) is
      // preserved and never mutated; tolerate opts === undefined (_get passes none).
      // No token -> no Authorization key at all (byte-for-byte the token-off request).
      var _tok = Pet.token.get();
      if (_tok) {
        opts = Object.assign({}, opts);
        opts.headers = Object.assign({}, opts.headers, { Authorization: "Bearer " + _tok });
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
    // PET-166 (D10): the ONE derivation of the read scope the client sends. Empty
    // string means "omit the parameter entirely" — all of standalone (source "none"),
    // and an embedded host reporting no named profile, send nothing. The sole source
    // is Pet.state.selectedHermesProfile (two writers, host path + in-console picker);
    // reading hostProfile.profile directly would be a second derivation that diverges
    // under the picker.
    _scopeParam: function () {
      if (!Pet.hostProfile || Pet.hostProfile.source === "none") return "";
      var v = Pet.state.selectedHermesProfile;
      return String(v == null ? "" : v).trim();
    },
    getConfig: function (profile) { return this._get("/config" + (profile ? ("?profile=" + encodeURIComponent(profile)) : "")); },
    putConfig: function (patch) { return this._put("/config", patch); },
    // postScan is deliberately NOT scoped (D10): a playground scan is a write against
    // the equipped binding; the playground renders a note instead.
    postScan: function (text, dir, sid) { return this._post("/scan", { text: text, direction: dir, session_id: sid }); },
    getHealth: function () {
      var p = this._scopeParam();
      return this._get("/health" + (p ? "?profile=" + encodeURIComponent(p) : ""));
    },
    // PET-166 (D10): profile ALWAYS joins with "&" here — the path already carries
    // "?limit=", so a "?profile=" append would parse as part of the before value (or
    // limit) and silently fall back to the equipped scope on the primary surface.
    getScanHistory: function (limit, before) {
      var p = this._scopeParam();
      return this._get("/scan-history?limit=" + (limit || 100)
        + (before ? "&before=" + encodeURIComponent(before) : "")
        + (p ? "&profile=" + encodeURIComponent(p) : ""));
    },
    getProfiles: function () { return this._get("/profiles"); },
    getAbout: function () { return this._get("/about"); },
    getArmed: function () {
      var p = this._scopeParam();
      return this._get("/armed" + (p ? "?profile=" + encodeURIComponent(p) : ""));
    },
    // PET-166 (D6): the write's selector rides in the BODY (never the query — the
    // server 422s a query-borne one). opts.unscoped sends no selector: D16's
    // equipped-name-null and unknown-binding states arm the process binding directly.
    setArmed: function (a, opts) {
      opts = opts || {};
      var body = { armed: a };
      var p = opts.unscoped ? "" : this._scopeParam();
      if (p) body.profile = p;
      return this._post("/armed", body);
    },
  };

  // ── SSE client (fetch-based for auth header support) ──
  // PET-142: bounded-backoff reconnect. A transient stream fault (clean close,
  // mid-stream read error, network failure, or any non-auth HTTP status) no
  // longer latches polling for the whole session; it schedules a jittered,
  // capped reconnect (the existing 10s poll runs during the backoff window as
  // the safety net) and returns to push cadence on the reconnected stream's
  // first bytes. Only 401/403 and an exhausted attempt budget concede to polling
  // terminally — exactly where the pre-PET-142 single-strike client always
  // landed, so the worst case is strictly non-regressive. See spec PET-142.
  Pet.sse = {
    _reader: null,
    _abortCtrl: null,
    _usingFallback: false,        // D8: "polling is currently active" — true during transient backoff AND terminal concede
    _scopeLive: true,             // PET-166 D9: false while the open stream is the idle (non-equipped) one
    _scopeRefusal: null,          // PET-166 D9: "profile" | "capacity" | null — why a terminal refusal downgraded the chip
    _reconnectTimer: null,        // pending reconnect setTimeout handle, or null
    _reconnectAttempts: 0,        // consecutive failed attempts since the last durable stream
    _healthyTimer: null,          // pending durable-reset setTimeout handle (D11), or null
    _gen: 0,                      // connection generation (D12); bumped on disconnect + each _openStream
    _BACKOFF_BASE_MS: 1000,       // base delay
    _BACKOFF_MAX_MS: 30000,       // per-attempt delay cap
    _MAX_RECONNECTS: 6,           // attempt cap before conceding to polling
    _HEALTHY_RESET_MS: 60000,     // a reconnected stream must survive this long to refill the budget (D11)

    // Public entry: full reset, then a fresh stream. The reconnect timer calls
    // _openStream() directly (NOT this), so a reconnect does not re-enter the
    // counter-zeroing reset and break the attempt bound.
    connect: function () {
      this.disconnect();   // full reset: bump _gen, abort old stream, cancel both timers, zero counter, stop poll
      this._openStream();  // the fetch/pump body (no reset — safe on the reconnect path)
    },

    _openStream: function () {
      var self = this;
      var gen = (self._gen += 1);                    // D12: this connection's generation
      if (self._abortCtrl) self._abortCtrl.abort();  // defensive; inert on the reconnect path (disconnect nulled it)
      // PET-166 (D9): the reset point lives HERE, not in connect() — _scheduleReconnect
      // calls _openStream directly (bypassing connect), and with the reset in connect()
      // only, a reconnect landing on an equipped stream would leave the chip reading
      // SCOPED over a live stream forever (the read_scope frame that clears it is
      // emitted only on the non-equipped stream). Repainted before the fetch resolves.
      self._scopeLive = true;
      self._scopeRefusal = null;
      if (Pet.updateConnStatus) Pet.updateConnStatus();
      if (typeof _syncScopePoll === "function") _syncScopePoll();
      var url = Pet.api.baseUrl + "/events";
      var _sp = Pet.api._scopeParam();
      if (_sp) url += "?profile=" + encodeURIComponent(_sp);
      var headers = { "Accept": "text/event-stream" };
      // PET-129 D1/D5 (edge F-7): sse.connect is the single SSE client for both modes,
      // so exactly ONE credential is attached, keyed on the SAME embedded predicate as
      // _req (`sdk && sdk.fetchJSON`) — embedded -> Hermes session token only, standalone
      // -> Petasos bearer only. The two never coexist (double-credentialing D5 forbids),
      // and a partial SDK object lacking fetchJSON is treated as standalone by both paths.
      var _sdk = window.__HERMES_PLUGIN_SDK__;
      if (_sdk && _sdk.fetchJSON) {
        var _hs = window.__HERMES_SESSION_TOKEN__;
        if (_hs) headers["X-Hermes-Session-Token"] = _hs;
      } else {
        var _ctok = Pet.token.get();
        if (_ctok) headers["Authorization"] = "Bearer " + _ctok;
      }

      self._abortCtrl = new AbortController();
      fetch(url, {
        headers: headers,
        signal: self._abortCtrl.signal,
        credentials: "same-origin",
      })
        .then(function (resp) {
          if (gen !== self._gen) return;             // D12: superseded connection — drop silently
          // PET-129 D4: a 401 here is the auth-required terminal state, NOT transient
          // offline. Route it to the chokepoint (which stops the polls + disconnects,
          // cancelling PET-142's reconnect) instead of letting it fall to the .catch
          // reconnect, which would re-open and 401 forever. Genuine offline (a network
          // reject or a non-401 non-ok status) still throws below -> the .catch keeps
          // PET-142's bounded-backoff reconnect, so the live/polling indicator is intact.
          if (resp.status === 401) { Pet.auth.on401({ _status: 401 }); return; }
          // PET-166 (D9): a 422 (profile deleted between renders, D7) is TERMINAL —
          // no reconnect, no fallback — and must itself downgrade the chip, because
          // no stream opens so the read_scope frame that would clear _scopeLive
          // never arrives. Same for the idle-arm 503 below, which is discriminated
          // by its scope_refusal:"capacity" body marker; an UNMARKED 503 (the
          // equipped stream's subscriber-cap refusal) keeps the shipped
          // retry-then-fallback path.
          if (resp.status === 422) {
            self._scopeLive = false;
            self._scopeRefusal = "profile";
            if (Pet.updateConnStatus) Pet.updateConnStatus();
            if (typeof _syncScopePoll === "function") _syncScopePoll();
            return;
          }
          if (resp.status === 503) {
            resp.json().then(function (b) {
              if (gen !== self._gen) return;
              if (b && b.scope_refusal === "capacity") {
                self._scopeLive = false;
                self._scopeRefusal = "capacity";
                if (Pet.updateConnStatus) Pet.updateConnStatus();
                if (typeof _syncScopePoll === "function") _syncScopePoll();
                return;                        // terminal: an idle stream refused for capacity is not an outage
              }
              self._scheduleReconnect();       // unmarked 503: shipped retry-then-fallback
            }).catch(function () {
              if (gen === self._gen) self._scheduleReconnect();
            });
            return;
          }
          if (!resp.ok) throw new Error(resp.status);
          if (!resp.body) throw new Error("no response body");
          var reader = resp.body.getReader();
          var dec = new TextDecoder();
          self._reader = reader;
          var buf = "";
          function pump() {
            reader.read().then(function (r) {
              if (gen !== self._gen) return;         // D12: superseded — no resurrection, even on the done path
              if (r.done) {
                if (buf.trim()) {
                  var evType = null, evData = null;
                  buf.replace(/\r\n/g, "\n").split("\n").forEach(function (line) {
                    if (line.indexOf("event: ") === 0) evType = line.slice(7);
                    else if (line.indexOf("data: ") === 0) evData = line.slice(6);
                  });
                  if (evType && evData) self._dispatch(evType, evData);
                }
                self._scheduleReconnect();           // D9: clean close is retryable, not a terminal demotion
                return;
              }
              // D7: first bytes on this connection. Flip the UI back to LIVE now
              // (the operator's win) but only ARM a durability timer — the retry
              // budget refills on proven durability (D11), not on the first byte,
              // so a bytes-then-die flap stays bounded. Both branches are
              // idempotent on later chunks; on a clean first connect
              // (_reconnectAttempts===0, _usingFallback===false) the block is a no-op.
              if (self._usingFallback) {
                self._usingFallback = false;
                Pet._poll.stopFallback();
                if (Pet.updateConnStatus) Pet.updateConnStatus();   // POLLING → LIVE
              }
              if (self._reconnectAttempts > 0 && !self._healthyTimer) {
                self._healthyTimer = setTimeout(function () {
                  self._healthyTimer = null;
                  self._reconnectAttempts = 0;       // durable: earn a fresh retry budget
                }, self._HEALTHY_RESET_MS);
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
              if (gen !== self._gen) return;         // D12
              if (e.name !== "AbortError") self._scheduleReconnect();  // mid-stream read error is retryable
            });
          }
          pump();
        })
        .catch(function (e) {
          if (gen !== self._gen) return;             // D12
          if (e.name === "AbortError") return;       // deliberate teardown — never reconnect
          // D9: the terminal (non-retryable) set is {401, 403}. PET-129 now intercepts
          // a 401 upstream in the response handler (-> Pet.auth.on401, the authenticate
          // state) before it can throw here, so in practice this branch fires for 403;
          // the 401 arm is kept as belt-and-suspenders so any 401 that did reach here
          // still concedes rather than reconnect-storms. The `throw new Error(resp.status)`
          // makes e.message the status string.
          if (e.message === "401" || e.message === "403") {
            console.warn("Petasos SSE: auth rejected (" + e.message + "), using polling fallback");
            self._enableFallback();                  // terminal: a tab that will never re-authorize must not storm
          } else {
            self._scheduleReconnect();               // 5xx / 404 / 429 / network / "no response body" — all retryable
          }
        });
    },

    // PET-142: schedule one jittered reconnect, or concede to polling once the
    // attempt budget is spent. The single-flight guard (F-4) keeps disconnect()
    // able to cancel the one pending timer; the _healthyTimer clear (D11) makes a
    // not-yet-durable connection's death count toward the cap.
    _scheduleReconnect: function () {
      var self = this;
      if (self._reconnectTimer) return;              // F-4: exactly one reconnect pending at a time
      if (self._healthyTimer) {                      // D11/F-2: this connection died before proving durable
        clearTimeout(self._healthyTimer); self._healthyTimer = null;
      }
      if (self._reconnectAttempts >= self._MAX_RECONNECTS) {
        console.warn("Petasos SSE: reconnect attempts exhausted, using polling fallback");
        self._enableFallback();                      // terminal; no new timer scheduled → bounded
        return;
      }
      if (!self._usingFallback) {                    // D8: arm the safety net on the first fault
        self._usingFallback = true;
        Pet._poll.startFallback();                      // idempotent: guarded by _fallbackPollInterval (load-bearing)
        if (Pet.updateConnStatus) Pet.updateConnStatus();
      }
      var delay = self._backoffDelay(self._reconnectAttempts);
      self._reconnectAttempts += 1;
      self._reconnectTimer = setTimeout(function () {
        self._reconnectTimer = null;
        self._openStream();                          // _openStream bumps _gen; disconnect cleared this handle if torn down
      }, delay);
    },

    // PET-142: pure helper (testable seam, like Pet.mergeScanHistory / bypassTotal).
    // Equal jitter: returns a delay in [capped/2, capped) — half-open, so the floor
    // capped/2 is reachable (Math.random → 0) but the ceiling capped is not. Never
    // below capped/2 (no degenerate-zero retry), never the full cap (no herd).
    _backoffDelay: function (n) {
      var capped = Math.min(this._BACKOFF_BASE_MS * Math.pow(2, n), this._BACKOFF_MAX_MS);
      var half = capped / 2;
      return half + Math.random() * half;
    },

    _dispatch: function (evType, dataStr) {
      try { var d = JSON.parse(dataStr); } catch (_) { return; }
      if (evType === "scan_result") {
        // PET-99 D6: a malformed frame (JSON.parse("null"), a number, an array)
        // must never enter the render buffer — scanHistoryRows/renderDashboard
        // guard on read, but keeping the buffer object-only is the cheaper floor.
        if (d && typeof d === "object") {
          Pet.state.scanHistory.unshift(d);
          Pet.accrueBypass([d]); // PET-138: fold this frame's bypass count into state
          // PET-165: live-increment the self-tamper tile (the arm already guarantees d is
          // an object). The next /health adoption re-syncs against the server counter, so
          // a frame seen either side of the seed snapshot self-heals within one poll.
          if (d.event_type === "selfmod_attempt") Pet.state.selfmodTotal += 1;
          // PET-13: announce the newest verdict to AT; the wholesale re-render below
          // is not screen-reader-followable on its own.
          var _v = d.safe === false ? "blocked" : "allowed";
          var _nf = Array.isArray(d.findings) ? d.findings.length : 0;
          if (Pet.announce) Pet.announce("Scan " + _v + (_nf ? (", " + _nf + " finding" + (_nf === 1 ? "" : "s")) : ""));
        }
        // PET-148 (D-DRIFT): the @ring-cap marker pins this literal to the backend
        // _SCAN_HISTORY_RING_CAPACITY; the drift test greps the marker, never a bare 500
        // (which would also match the getScanHistory(500) seed page-size below).
        if (Pet.state.scanHistory.length > /* @ring-cap */ 500) Pet.state.scanHistory.length = 500;
        if (Pet.state.tab === "obs" && Pet._runtime.container) Pet.renderDashboard(Pet._runtime.container);
      } else if (evType === "audit") {
        Pet.state.auditLog.unshift(d);
        if (Pet.state.auditLog.length > 1000) Pet.state.auditLog.length = 1000;
      } else if (evType === "alert") {
        Pet.state.alerts.unshift(d);
        if (Pet.state.alerts.length > 200) Pet.state.alerts.length = 200;
      } else if (evType === "read_scope") {
        // PET-166 (D9/D19): the idle (non-equipped) stream's first frame. live:false
        // downgrades the chip to SCOPED and starts the D3 scoped poll; the frame
        // carries exactly the read_scope object, so it is adopted as-is.
        if (d && typeof d === "object") {
          Pet.state.readScope = d;
          if (d.live === false) {
            this._scopeLive = false;
            this._scopeRefusal = null;
            if (Pet.updateConnStatus) Pet.updateConnStatus();
            if (typeof _syncScopePoll === "function") _syncScopePoll();
          }
        }
      } else if (evType === "armed") {
        // PET-116: live cross-tab sync of the Equipped/Unequipped bit. _dispatch
        // cannot call paintBanner (a renderDashboard-local closure); it adopts the
        // authoritative pushed value into Pet.state.armed and re-renders, mirroring
        // the scan_result arm. renderDashboard rebuilds the banner from
        // Pet.state.armed and re-runs its per-entry seed guard.
        // PET-129 (edge F-3): a buffered armed frame racing the 401 teardown must not
        // mutate armed/Pet._runtime.armedSeeded while authentication is required (it would re-seed
        // a false EQUIPPED via a side channel). Bail first; resume re-derives from
        // server truth, and bannerView keys on authRequired regardless.
        if (Pet.state.authRequired) return;
        if (Pet._runtime.armedBusy) return;                 // don't clobber this tab's in-flight optimistic toggle
        if (d && typeof d.armed === "boolean") {
          Pet.state.armed = d.armed;            // adopt file-truth pushed by the originating tab
          Pet._runtime.armedSeeded = true;                  // an authoritative push counts as a seed (no redundant GET)
          if (Pet.state.tab === "obs" && Pet._runtime.container) Pet.renderDashboard(Pet._runtime.container);
        }
      }
    },

    _enableFallback: function () {
      if (this._usingFallback) return;
      this._usingFallback = true;
      Pet._poll.startFallback();
      if (Pet.updateConnStatus) Pet.updateConnStatus();  // PET-13: flip the header blip to POLLING
    },

    disconnect: function () {
      this._gen += 1;                                // D12: invalidate every in-flight continuation (incl. the done path)
      if (this._abortCtrl) { this._abortCtrl.abort(); this._abortCtrl = null; }
      this._reader = null;
      if (this._reconnectTimer) { clearTimeout(this._reconnectTimer); this._reconnectTimer = null; }
      if (this._healthyTimer) { clearTimeout(this._healthyTimer); this._healthyTimer = null; }
      this._reconnectAttempts = 0;
      this._usingFallback = false;
      Pet._poll.stopFallback();
    },
  };

  // ── Polling (health: always, scan/alert data: fallback when SSE unavailable) ──
  var _pollInterval = null;
  var _fallbackPollInterval = null;

  function startPolling() {
    if (_pollInterval) return;
    _pollInterval = setInterval(function () {
      var gen = Pet._runtime.scopeGen; // PET-166 D17: captured at send time
      Pet.api.getHealth().then(function (d) {
        if (Pet.auth.on401(d)) return; // PET-129 D3/D4/§1: first statement; a 401 stops the poll, never an empty-success no-op
        if (gen !== Pet._runtime.scopeGen) return; // PET-166: superseded scope
        if (Pet.isProfile422(d)) {
          // PET-166 D7: a 422 body carries no `error`; without this branch the shape
          // gate below would wipe the health/integrity panels every 10 s.
          var e0 = d.detail.filter(function (x) { return x && x.field === "profile"; })[0];
          Pet.state.scopeError = { surface: "health", message: (e0 && e0.message) || "profile not found" };
          if (Pet.state.tab === "obs" && Pet._runtime.container) Pet.renderDashboard(Pet._runtime.container);
          return;
        }
        if (!d.error) {
          Pet._runtime.healthLoaded = true;  // PET-127: a poll settle that beats a slow in-render fetch flips the gate, not the skeleton
          Pet._scope.adoptRead(d);    // PET-166 D19: health 200s are a readScope writer
          Pet.state.scannerHealth = d.scanners || [];
          Pet.state.pipelineHealth = d.pipeline || null;
          Pet.state.integrityHealth = d.integrity || null; // PET-157: mirror pipelineHealth (recurring poll)
          Pet.adoptSelfmodTotal(Pet.state.pipelineHealth); // PET-165: re-sync the tile count
          if (Pet.state.tab === "obs" && Pet._runtime.container) Pet.renderDashboard(Pet._runtime.container);
        }
      });
    }, 10000);
  }
  function stopPolling() {
    if (_pollInterval) { clearInterval(_pollInterval); _pollInterval = null; }
  }

  function startFallbackPolling() {
    if (_fallbackPollInterval) return;
    function send() {
      var gen = Pet._runtime.scopeGen; // PET-166 D17: captured at send time, per request
      return Pet.api.getScanHistory(100).then(function (d) {
        if (Pet.auth.on401(d)) return; // PET-129 D4: on401 nulls _fallbackPollInterval before the reschedule .then runs, so the re-arm below no-ops
        if (gen !== Pet._runtime.scopeGen) return; // PET-166 D17: superseded scope — drop
        if (Pet._scope.guardHistory(d)) return; // PET-166 D7: coherent 422 state
        if (!d.error && d.entries && Array.isArray(d.entries)) {
          Pet.state.scanHistory = d.entries;
          Pet.accrueBypass(d.entries); // PET-138: SSE-down path also feeds bypass state
          Pet._scope.adoptHistory(d);       // PET-166 D19: fallback assignments are writer sites too
          if (Pet.state.tab === "obs" && Pet._runtime.container) Pet.renderDashboard(Pet._runtime.container);
        }
      });
    }
    // Both arms re-arm: a rejected tick (render throw, network reject) must not end
    // the chain for the rest of the mount — the setInterval form it replaced survived
    // a failed tick, and the 401 stop already runs through the nulled-interval guard.
    function rearm() { if (_fallbackPollInterval) schedule(); }
    function schedule() {
      _fallbackPollInterval = setTimeout(function () {
        send().then(rearm, rearm);
      }, 10000);
    }
    send();
    schedule();
  }
  function stopFallbackPolling() {
    if (_fallbackPollInterval) { clearTimeout(_fallbackPollInterval); _fallbackPollInterval = null; }
  }

  // ── PET-166: read-scope plumbing (D3/D17/D19/D20) ──

  // Scope generation: bumped on every scope change (either axis); captured by every
  // scoped fetch at send time so a superseded resolve is dropped (Pet._runtime.configRenderGen pattern
  // extended to all five new surfaces).

  // D3: the 30 s scoped history poll. A SINGLETON with an idempotent start (the
  // startFallbackPolling / _scheduleReconnect guard pattern): a scope change re-uses
  // the running timer rather than starting a second — the poll is keyed on "a foreign
  // scope is on screen", not on which profile it is. Gate: !_scopeLive || foreign.
  // Keyed on the stream's own liveness as well as the scope so the SDK-fallback
  // equipped flip (which triggers no rebind and no reconnect) cannot strand a frozen
  // panel: the poll keeps running until a stream that is actually live replaces the
  // idle one. The hoisted server drain rides every one of these calls, keeping our
  // own fold and rotation alive while parked on a foreign profile.
  var _SCOPE_POLL_MS = 30000;
  function _syncScopePoll() {
    var want = !Pet.state.authRequired
      && Pet.hostProfile && Pet.hostProfile.source !== "none"
      && (!(Pet.sse && Pet.sse._scopeLive) || Pet.isForeignScope());
    if (!want) {
      if (Pet._runtime.scopePollTimer) { clearInterval(Pet._runtime.scopePollTimer); Pet._runtime.scopePollTimer = null; }
      return;
    }
    if (Pet._runtime.scopePollTimer) return; // singleton: one timer regardless of switch count
    Pet._runtime.scopePollTimer = setInterval(function () {
      var gen = Pet._runtime.scopeGen;
      Pet.api.getScanHistory(100).then(function (d) {
        if (Pet.auth.on401(d)) return;            // PET-129 §1: on401 first, always
        if (gen !== Pet._runtime.scopeGen) return;            // superseded scope: drop
        if (Pet._scope.guardHistory(d)) return;
        if (!d.error && d.entries && Array.isArray(d.entries)) {
          Pet.state.scanHistory = d.entries;
          Pet.accrueBypass(d.entries);
          Pet._scope.adoptHistory(d);
          if (Pet.state.tab === "obs" && Pet._runtime.container) Pet.renderDashboard(Pet._runtime.container);
        }
      });
    }, _SCOPE_POLL_MS);
  }

  // D19: adopt a scan-history 200's scope facts. Called from ALL FOUR scan-history
  // writer sites (mount seed, both fallback assignments, the 30 s scoped poll) —
  // never a subset. "Believes it scoped" is derived per call from the same
  // _scopeParam the request was built with (the request and this adoption run
  // within one scope generation; a moved generation was dropped above).
  Pet._scope.adoptHistory = function (d) {
    if (!d || typeof d !== "object") return;
    var sentScoped = Pet.api._scopeParam() !== "";
    var rs = d.read_scope;
    if (rs && typeof rs === "object") {
      Pet.state.readScope = rs;
      // Written on EVERY carrying 200, equipped included — a label that can only
      // hold a foreign value has no way back to equipped (D19).
      Pet.state.historyReadScope = rs;
      Pet.state.spoolTruncated = d.spool_truncated === true;
      if (rs.state !== "equipped" && typeof d.has_older === "boolean") {
        Pet.state.historyHasOlder = d.has_older; // non-equipped writer only (D12)
      }
      if (sentScoped) Pet.state.scopeNotice = rs.selected == null; // D20 (defensive arm)
    } else if (sentScoped) {
      // A 200 the client believes it scoped that carries no read_scope clears the
      // fields (stale backend / bundle skew) and raises the D20 notice.
      Pet.state.readScope = null;
      Pet.state.historyReadScope = null;
      Pet.state.spoolTruncated = false;
      Pet.state.historyHasOlder = false;
      Pet.state.scopeNotice = true;
    }
    Pet.state.scopeError = null; // a 200 on this surface clears the D7 error state
    _syncScopePoll();
  };

  // D19: the health/armed flavor of the adoption above (those payloads carry only
  // read_scope). Only 200s call this; a 422/409/503 leaves readScope untouched.
  Pet._scope.adoptRead = function (d) {
    if (!d || typeof d !== "object") return;
    var sentScoped = Pet.api._scopeParam() !== "";
    if (d.read_scope && typeof d.read_scope === "object") {
      Pet.state.readScope = d.read_scope;
      if (sentScoped) Pet.state.scopeNotice = d.read_scope.selected == null;
    } else if (sentScoped) {
      Pet.state.readScope = null;
      Pet.state.scopeNotice = true;
    }
    Pet.state.scopeError = null;
    _syncScopePoll();
  };

  // D7: shared 422 branch for the scoped readers. Sets the ONE coherent error state
  // (never four independent error boxes) and reports true so the caller returns
  // before its shape-guarded body can wipe healthy panels with a detail-only body.
  Pet._scope.guardHistory = function (d) {
    if (!Pet.isProfile422(d)) return false;
    var e0 = d.detail.filter(function (x) { return x && x.field === "profile"; })[0];
    Pet.state.scopeError = { surface: "scan-history", message: (e0 && e0.message) || "profile not found" };
    if (Pet.state.tab === "obs" && Pet._runtime.container) Pet.renderDashboard(Pet._runtime.container);
    return true;
  };

  // D17: invalidate every scoped surface on a host-profile change, on EITHER axis
  // (management selection or equipped flip). Pet.state.armed deliberately does NOT
  // reset (a null paints a false EQUIPPED); Pet.state.historyFilter deliberately
  // survives (a view preference, not profile data).
  Pet._scope.invalidate = function () {
    Pet._runtime.scopeGen++;
    Pet._runtime.historySeeded = false;
    Pet._runtime.armedSeeded = false;
    Pet._runtime.historyPaging = false;
    Pet._runtime.historyPagingGen++;         // drop an in-flight PET-152 two-fetch re-mint chain
    Pet._shell.clearArmedConfirm();         // a confirm window formed about the previous profile
    Pet.state.scanHistory = [];
    Pet.state.bypassBySession = {};
    Pet.state.historyStack = [];
    Pet.state.historyAtHead = true;
    Pet.state.readScope = null;           // null = the equipped form until the first 200 lands
    Pet.state.historyReadScope = null;
    Pet.state.historyHasOlder = false;
    Pet.state.spoolTruncated = false;
    Pet.state.scopeError = null;
    Pet.state.scopeNotice = false;
    if (!Pet.state.authRequired) {
      Pet.sse.connect();         // disconnect + reconnect with the new scope, exactly once
    }
    _syncScopePoll();
    if (Pet.state.tab === "obs" && Pet._runtime.container) Pet.renderDashboard(Pet._runtime.container);
  };

  // PET-129 D4: read-only testability seam over the module-private poll timers
  // (PET-103 D9 / scanner-health-help style: exposes state, adds no behavior).
  // startHealth/startFallback are thin wrappers so the headless node:vm harness can
  // start each poll directly (the health poll is otherwise reachable only through
  // Pet.mount, which the DOM shim cannot drive), making the poll-stop assertion
  // load-bearing rather than vacuously green. state() is the read-only probe.
  Pet._poll = {
    startHealth: function () { startPolling(); },
    startFallback: function () { startFallbackPolling(); },
    stopHealth: function () { stopPolling(); },
    stopFallback: function () { stopFallbackPolling(); },
    state: function () { return { health: !!_pollInterval, fallback: !!_fallbackPollInterval }; },
  };
  // Convenience alias for the read-only probe (some call sites reference Pet._pollState).
  Pet._pollState = Pet._poll.state;

  // PET-166: read-only testability seam over the IIFE-private armed latches (the
  // PET-129 D4 poll-timer seam pattern: exposes state, adds no behavior), plus the
  // scoped-poll probe so js/scope-poll-is-singleton can count timers.
  Pet._armedTestState = function () {
    return { busy: Pet._runtime.armedBusy, seeded: Pet._runtime.armedSeeded, confirmPending: Pet._runtime.armedConfirmPending };
  };
  Pet._scopePollState = function () { return { running: !!Pet._runtime.scopePollTimer }; };


  Pet._moduleState.last = "transport";
})();
