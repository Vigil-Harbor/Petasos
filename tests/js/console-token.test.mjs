// Unit tests for the PET-129 token-aware console client in
// petasos/console/static/petasos.js.
//
// PET-125 shipped a server-side, off-by-default PETASOS_CONSOLE_TOKEN Bearer gate on
// every standalone /api/* route. PET-129 teaches the browser client about that
// credential. This suite pins each of the three defects the ticket fixes, plus the
// round-1/round-2 edge cases the spec calls out:
//
//   1. No credential was ever attached -> the standalone _req / sse.connect now attach
//      `Authorization: Bearer <token>` when a token is stored, and ONLY on the
//      standalone path (the embedded Hermes SDK path is left untouched). (D1)
//   2. The equip banner misread a 401 as EQUIPPED -> Pet.bannerView keys on
//      authRequired FIRST, returning an explicit authenticate state, never EQUIPPED,
//      and Pet.auth.on401 sets authRequired. (D3)
//   3. The 10-second polls retried the 401 forever -> Pet.auth.on401 stops both polls
//      with no auto-reschedule; a verified re-auth resumes them. (D4)
//
// Zero npm dependencies: Node's built-in test runner + assert, a DOM shim (mirrors
// armed-sync.test.mjs / trap-burst.test.mjs), node:vm to evaluate the real shipped
// petasos.js, plus a mock fetch (records url + opts), recording sandbox timers (the
// trap-burst.test.mjs idiom), and AbortController/TextDecoder for the SSE path. Each
// test loads a FRESH Pet (the client carries global state: authRequired, token, poll
// timers), so they cannot cross-contaminate. Run with:
//   node --test tests/js/console-token.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

// ── DOM shim (mirrors trap-burst.test.mjs, + value/disabled/attrs for the panel) ──
function makeNode(nodeType) {
  return {
    nodeType,
    childNodes: [],
    style: {},
    className: "",
    title: "",
    value: "",
    disabled: false,
    attrs: {},
    appendChild(child) {
      this.childNodes.push(child);
      return child;
    },
    insertBefore(node, ref) {
      const i = ref ? this.childNodes.indexOf(ref) : -1;
      if (i < 0) this.childNodes.push(node);
      else this.childNodes.splice(i, 0, node);
      return node;
    },
    get firstChild() {
      return this.childNodes[0] || null;
    },
    addEventListener(_type, _fn) {},
    setAttribute(k, v) {
      this.attrs[k] = String(v);
    },
    removeAttribute(k) {
      delete this.attrs[k];
    },
    getAttribute(k) {
      return this.attrs[k];
    },
    querySelector() {
      return null;
    },
    querySelectorAll() {
      return [];
    },
    get textContent() {
      if (this.nodeType === 3) return this.nodeValue;
      return this.childNodes.map((c) => c.textContent).join("");
    },
    set textContent(v) {
      this.childNodes = [];
      const s = v == null ? "" : String(v);
      if (s !== "") {
        const n = makeNode(3);
        n.nodeValue = s;
        this.childNodes.push(n);
      }
    },
    set innerHTML(_v) {
      this.childNodes = [];
    },
  };
}

function makeDocument() {
  return {
    createDocumentFragment() {
      return makeNode(11);
    },
    createElement(tag) {
      const el = makeNode(1);
      el.tagName = tag.toUpperCase();
      el.localName = tag;
      return el;
    },
    createElementNS(_ns, tag) {
      return this.createElement(tag);
    },
    createTextNode(t) {
      const node = makeNode(3);
      node.nodeValue = String(t);
      return node;
    },
  };
}

// ── Sandbox helpers ──────────────────────────────────────────────────────────
const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(
  join(here, "..", "..", "petasos", "console", "static", "petasos.js"),
  "utf8"
);

// Load the real petasos.js into a fresh vm context. Every option is overridable so a
// test can inject its own fetch / timers / sessionStorage / window.
function loadPet(opts = {}) {
  const document = makeDocument();
  const sandbox = {
    window: opts.window || {},
    document,
    fetch: opts.fetch,
    setInterval: opts.setInterval || (() => 0),
    clearInterval: opts.clearInterval || (() => {}),
    setTimeout: opts.setTimeout || (() => 0),
    clearTimeout: opts.clearTimeout || (() => {}),
    AbortController:
      opts.AbortController ||
      class {
        constructor() {
          this.signal = {};
        }
        abort() {}
      },
    TextDecoder:
      opts.TextDecoder ||
      class {
        decode() {
          return "";
        }
      },
    console: { warn() {}, log() {}, error() {} },
  };
  // "sessionStorage" present as a key (even = undefined) means the test controls it;
  // otherwise hand the store a working in-memory sessionStorage.
  sandbox.sessionStorage = "sessionStorage" in opts ? opts.sessionStorage : makeSessionStorage();
  vm.runInNewContext(src, sandbox);
  return { Pet: sandbox.window.__PETASOS_CONSOLE__, sandbox, document };
}

function makeSessionStorage() {
  const store = new Map();
  return {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => {
      store.set(k, String(v));
    },
    removeItem: (k) => {
      store.delete(k);
    },
  };
}

// Recording timers (trap-burst idiom): record scheduled callbacks, expose totals, and
// allow firing the still-active ones. clear* removes them from the active set, so a
// re-fire after clear is a no-op (the no-reschedule pin relies on this).
function makeTimers() {
  let nextId = 1;
  let totalIntervals = 0;
  let totalTimeouts = 0;
  const intervals = new Map();
  const timeouts = new Map();
  return {
    setInterval: (fn) => {
      const id = nextId++;
      intervals.set(id, fn);
      totalIntervals++;
      return id;
    },
    clearInterval: (id) => {
      intervals.delete(id);
    },
    setTimeout: (fn) => {
      const id = nextId++;
      timeouts.set(id, fn);
      totalTimeouts++;
      return id;
    },
    clearTimeout: (id) => {
      timeouts.delete(id);
    },
    fireIntervals() {
      for (const fn of [...intervals.values()]) fn();
    },
    fireTimeouts() {
      for (const fn of [...timeouts.values()]) fn();
    },
    get totalIntervals() {
      return totalIntervals;
    },
    get totalTimeouts() {
      return totalTimeouts;
    },
  };
}

// A FastAPI-shaped JSON response for the mock fetch (what _req's standalone branch
// consumes: r.ok / r.status / r.json()).
function jsonResp(status, body) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  };
}

// An SSE-shaped response: a body whose reader never resolves, so sse.connect's pump
// parks harmlessly after we have observed the request headers.
function sseResp() {
  return {
    ok: true,
    status: 200,
    body: { getReader: () => ({ read: () => new Promise(() => {}) }) },
  };
}

// Drain all pending microtasks (the _req fetch -> r.json() -> reader .then chain).
const flush = () => new Promise((r) => setImmediate(r));

// ── Tests ─────────────────────────────────────────────────────────────────────

// Seam-presence guard: a missing seam fails loudly here rather than letting a later
// test pass vacuously.
test("loader: petasos.js exports Pet.token, Pet.auth.on401, Pet.bannerView, Pet._poll", () => {
  const { Pet } = loadPet();
  assert.equal(typeof Pet, "object");
  assert.equal(typeof Pet.token, "object");
  for (const m of ["get", "set", "clear"]) {
    assert.equal(typeof Pet.token[m], "function", `Pet.token.${m} missing`);
  }
  assert.equal(typeof Pet.auth, "object");
  assert.equal(typeof Pet.auth.on401, "function");
  assert.equal(typeof Pet.bannerView, "function");
  assert.equal(typeof Pet._poll, "object");
  for (const m of ["startHealth", "startFallback", "state"]) {
    assert.equal(typeof Pet._poll[m], "function", `Pet._poll.${m} missing`);
  }
});

// The headline regression pin (D1, defect #1).
test("test_bearer_attached_on_standalone_path", async () => {
  const calls = [];
  const fetch = (url, opts) => {
    calls.push({ url, opts });
    return Promise.resolve(jsonResp(200, { scanners: [] }));
  };
  const { Pet } = loadPet({ fetch });
  Pet.token.set("s3cr3t");
  await Pet.api.getHealth();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "/api/health");
  // Verbatim "Bearer " + token, to match the server's case-sensitive scheme + verbatim
  // hmac.compare_digest comparison.
  assert.equal(calls[0].opts.headers.Authorization, "Bearer s3cr3t");
});

// The merge must not clobber a caller's headers literal (e.g. _post's Content-Type).
test("test_bearer_merge_preserves_caller_headers", async () => {
  const calls = [];
  const fetch = (url, opts) => {
    calls.push({ url, opts });
    return Promise.resolve(jsonResp(200, { armed: true }));
  };
  const { Pet } = loadPet({ fetch });
  Pet.token.set("tok");
  await Pet.api.setArmed(true); // _post: { "Content-Type": "application/json" }
  const h = calls[0].opts.headers;
  assert.equal(h["Content-Type"], "application/json");
  assert.equal(h.Authorization, "Bearer tok");
});

// Embedded Hermes path is untouched: no Petasos Authorization, and the standalone
// fetch is never reached (D1/D5).
test("test_no_bearer_on_embedded_sdk_path", async () => {
  const sdkCalls = [];
  const window = {
    __HERMES_PLUGIN_SDK__: {
      fetchJSON: (url, opts) => {
        sdkCalls.push({ url, opts });
        return Promise.resolve({ scanners: [] });
      },
    },
  };
  let fetchCalled = false;
  const fetch = () => {
    fetchCalled = true;
    return Promise.resolve(jsonResp(200, {}));
  };
  const { Pet } = loadPet({ window, fetch });
  Pet.token.set("s3cr3t");
  await Pet.api.getHealth();
  assert.equal(fetchCalled, false, "embedded path must not hit the standalone fetch");
  assert.equal(sdkCalls.length, 1);
  const opts = sdkCalls[0].opts;
  assert.ok(
    !opts || !opts.headers || !opts.headers.Authorization,
    "no Petasos Authorization injected on the embedded SDK path"
  );
});

// Standalone SSE connect attaches the bearer (D1).
test("test_sse_connect_sends_bearer_when_token_set", () => {
  const calls = [];
  const fetch = (url, opts) => {
    calls.push({ url, opts });
    return Promise.resolve(sseResp());
  };
  const { Pet } = loadPet({ fetch });
  Pet.token.set("s3cr3t");
  Pet.sse.connect();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "/api/events");
  assert.equal(calls[0].opts.headers.Accept, "text/event-stream");
  assert.equal(calls[0].opts.headers.Authorization, "Bearer s3cr3t");
});

// Embedded SSE keeps X-Hermes-Session-Token only, no Petasos Authorization (edge F-7);
// the two credentials never coexist.
test("test_no_bearer_on_sse_embedded_path", () => {
  const calls = [];
  const fetch = (url, opts) => {
    calls.push({ url, opts });
    return Promise.resolve(sseResp());
  };
  const window = {
    __HERMES_PLUGIN_SDK__: { fetchJSON: () => Promise.resolve({}) },
    __HERMES_SESSION_TOKEN__: "hsess",
  };
  const { Pet } = loadPet({ window, fetch });
  Pet.token.set("s3cr3t");
  Pet.sse.connect();
  assert.equal(calls.length, 1);
  const h = calls[0].opts.headers;
  assert.equal(h["X-Hermes-Session-Token"], "hsess");
  assert.ok(!h.Authorization, "no Petasos Authorization on the embedded SSE path");
});

// Defect #2: a 401 never renders EQUIPPED; on401 sets authRequired; the auth panel is
// honest.
test("test_401_does_not_render_equipped", () => {
  const { Pet } = loadPet();
  const v = Pet.bannerView({ authRequired: true, armed: true });
  assert.notEqual(v.label, "EQUIPPED", "a 401'd armed read must never read EQUIPPED");
  assert.equal(v.label, "AUTHENTICATE");
  assert.equal(v.on, false);

  assert.equal(Pet.state.authRequired, false);
  assert.equal(Pet.auth.on401({ _status: 401 }), true);
  assert.equal(Pet.state.authRequired, true);

  // The live authenticate panel shows AUTHENTICATE, never EQUIPPED.
  const panel = Pet.renderAuthPanel();
  assert.ok(/AUTHENTICATE/.test(panel.textContent), "auth panel shows AUTHENTICATE");
  assert.ok(!/EQUIPPED/.test(panel.textContent), "auth panel never shows EQUIPPED");
});

// on401 keys strictly on _status === 401, so it fires on BOTH envelope shapes and is
// inert on non-401 / no-status bodies (edges F-2 / F-4).
test("test_401_fires_on_both_envelope_shapes", () => {
  // JSON 401 body { detail, _status } (FastAPI HTTPException default detail).
  assert.equal(loadPet().Pet.auth.on401({ detail: "Unauthorized", _status: 401 }), true);
  // Parse-failure envelope { error, _status }.
  assert.equal(loadPet().Pet.auth.on401({ error: "401 Unauthorized", _status: 401 }), true);

  // Negatives, on a single fresh Pet: none flips authRequired.
  const { Pet } = loadPet();
  assert.equal(Pet.auth.on401({ detail: "Forbidden", _status: 403 }), false, "403 is not the auth state");
  assert.equal(Pet.auth.on401({ error: "boom" }), false, "no _status -> not a 401");
  assert.equal(Pet.auth.on401(null), false);
  assert.equal(Pet.auth.on401(undefined), false);
  assert.equal(Pet.state.authRequired, false, "non-401 inputs must not flip authRequired");
});

// No-regression pin for the common token-off deployment: request shape is byte-for-byte
// today's (no Authorization key at all).
test("test_no_token_path_unchanged", async () => {
  const calls = [];
  const fetch = (url, opts) => {
    calls.push({ url, opts });
    return Promise.resolve(jsonResp(200, { scanners: [] }));
  };
  const { Pet } = loadPet({ fetch });
  // _get with no token: opts stays undefined exactly as today (no headers object added).
  await Pet.api.getHealth();
  assert.equal(calls[0].opts, undefined, "token-off _get sends no opts (no Authorization key)");
  // _post with no token: headers are exactly the caller's literal, no Authorization.
  await Pet.api.setArmed(true);
  const postHeaders = calls[1].opts.headers;
  assert.deepEqual(Object.keys(postHeaders), ["Content-Type"]);
  assert.equal(postHeaders.Authorization, undefined);
});

// The most security-relevant store must hold its never-throw invariant (edge F-5):
// sessionStorage absent, and sessionStorage.setItem throwing, both round-trip via the
// in-memory fallback without throwing to callers.
test("test_token_store_degrades_without_sessionStorage", () => {
  // (a) sessionStorage undefined (headless / blocked).
  const { Pet } = loadPet({ sessionStorage: undefined });
  assert.doesNotThrow(() => Pet.token.set("abc"));
  assert.equal(Pet.token.get(), "abc");
  assert.doesNotThrow(() => Pet.token.clear());
  assert.equal(Pet.token.get(), null);

  // (b) setItem throws (private-browsing quota).
  const throwing = {
    getItem: () => null,
    setItem: () => {
      throw new Error("denied");
    },
    removeItem: () => {},
  };
  const { Pet: Pet2 } = loadPet({ sessionStorage: throwing });
  assert.doesNotThrow(() => Pet2.token.set("xyz"));
  assert.equal(Pet2.token.get(), "xyz", "falls back to in-memory when setItem throws");
  assert.doesNotThrow(() => Pet2.token.clear());
  assert.equal(Pet2.token.get(), null);
});

// Defect #3 (edge F-1): a 401 stops BOTH polls; the fallback does not reschedule; and
// re-driving the now-cleared recorded timers issues no further /api fetch.
test("test_401_stops_health_and_fallback_polls", async () => {
  const timers = makeTimers();
  const fetchCalls = [];
  const fetch = (url) => {
    fetchCalls.push(url);
    return Promise.resolve(jsonResp(401, { detail: "Unauthorized" }));
  };
  const { Pet } = loadPet({
    fetch,
    setInterval: timers.setInterval,
    clearInterval: timers.clearInterval,
    setTimeout: timers.setTimeout,
    clearTimeout: timers.clearTimeout,
  });

  // Health poll: start it via the seam, drive its body once, assert it stops on 401.
  Pet._poll.startHealth();
  assert.equal(Pet._poll.state().health, true, "health poll active after startHealth");
  timers.fireIntervals(); // run the 10s health poll body -> getHealth (pending 401)
  await flush();
  await flush();
  assert.equal(Pet._poll.state().health, false, "health poll stopped on a 401");

  // Fallback poll: startFallback issues the initial read AND schedules the next tick.
  // Fire the scheduled tick so its reschedule .then is actually exercised, then 401.
  Pet._poll.startFallback();
  assert.equal(Pet._poll.state().fallback, true, "fallback poll active after startFallback");
  const timeoutsBeforeStop = timers.totalTimeouts;
  timers.fireTimeouts(); // run the scheduled fallback body -> getScanHistory + reschedule .then
  await flush();
  await flush();
  assert.equal(Pet._poll.state().fallback, false, "fallback poll stopped on a 401");
  assert.equal(
    timers.totalTimeouts,
    timeoutsBeforeStop,
    "fallback must NOT reschedule after a 401 (the re-arm guard no-ops on the nulled interval)"
  );

  // Re-driving the cleared timers issues no further /api fetch (no zombie polling).
  const fetchesAfterStop = fetchCalls.length;
  timers.fireIntervals();
  timers.fireTimeouts();
  await flush();
  await flush();
  assert.equal(fetchCalls.length, fetchesAfterStop, "no further /api fetch after the polls stop");
});

// Re-auth resume (edges F-3 / F-6, happy path): a valid token leaves the authenticate
// state, restarts polling, and re-seeds armed from the authenticated read.
test("test_reauth_resumes_polling_and_reseeds", async () => {
  const timers = makeTimers();
  const fetch = (url, opts) => {
    const auth = opts && opts.headers && opts.headers.Authorization;
    if (auth === "Bearer good") {
      if (url.indexOf("/armed") >= 0) return Promise.resolve(jsonResp(200, { armed: false }));
      if (url.indexOf("/health") >= 0) return Promise.resolve(jsonResp(200, { scanners: [], pipeline: null }));
      if (url.indexOf("/scan-history") >= 0) return Promise.resolve(jsonResp(200, { entries: [] }));
      if (url.indexOf("/events") >= 0) return Promise.resolve(sseResp());
      return Promise.resolve(jsonResp(200, {}));
    }
    return Promise.resolve(jsonResp(401, { detail: "Unauthorized" }));
  };
  const { Pet } = loadPet({
    fetch,
    setInterval: timers.setInterval,
    clearInterval: timers.clearInterval,
    setTimeout: timers.setTimeout,
    clearTimeout: timers.clearTimeout,
  });

  // Enter the authenticate state via a 401, then submit a valid token.
  Pet.auth.on401({ _status: 401 });
  assert.equal(Pet.state.authRequired, true);
  assert.equal(Pet.state.armed, null, "armed cleared to unknown on a 401");

  const res = await Pet.auth.submitToken("good");
  await flush();
  await flush();
  assert.equal(res.ok, true, "a valid token resumes");
  assert.equal(Pet.state.authRequired, false, "authenticate state cleared after a verified re-auth");
  // The default is true and on401 set it null; armed === false proves it came from the
  // authenticated read, not the stale optimistic default.
  assert.equal(Pet.state.armed, false, "armed re-seeded from the authenticated read");
  assert.equal(Pet._poll.state().health, true, "health polling restarted after re-auth");
});

// Stale-submit generation guard (edge F-6): a wrong token then a correct token. The
// wrong token's stale 401 must NOT tear down the correct token's established session.
test("test_stale_submit_generation_guard", async () => {
  const timers = makeTimers();
  const fetch = (url, opts) => {
    const auth = opts && opts.headers && opts.headers.Authorization;
    if (url.indexOf("/armed") >= 0) {
      return auth === "Bearer correct"
        ? Promise.resolve(jsonResp(200, { armed: true }))
        : Promise.resolve(jsonResp(401, { detail: "Unauthorized" }));
    }
    if (auth === "Bearer correct") {
      if (url.indexOf("/health") >= 0) return Promise.resolve(jsonResp(200, { scanners: [] }));
      if (url.indexOf("/events") >= 0) return Promise.resolve(sseResp());
      return Promise.resolve(jsonResp(200, {}));
    }
    return Promise.resolve(jsonResp(401, { detail: "Unauthorized" }));
  };
  const { Pet } = loadPet({
    fetch,
    setInterval: timers.setInterval,
    clearInterval: timers.clearInterval,
    setTimeout: timers.setTimeout,
    clearTimeout: timers.clearTimeout,
  });
  Pet.auth.on401({ _status: 401 });

  // Wrong then correct, near-simultaneously (a double-submit). The wrong submit's read
  // is issued under a now-superseded generation, so its 401 is dropped.
  const pWrong = Pet.auth.submitToken("wrong");
  const pCorrect = Pet.auth.submitToken("correct");
  const [rWrong, rCorrect] = await Promise.all([pWrong, pCorrect]);
  await flush();
  await flush();

  assert.equal(rWrong.ok, false, "the superseded (wrong) submit does not resume");
  assert.ok(rWrong.stale || rWrong.message, "the wrong submit is dropped/reported, not a teardown");
  assert.equal(rCorrect.ok, true, "the correct token resumes");
  assert.equal(Pet.state.authRequired, false, "the correct token's session survives the stale 401");
  assert.equal(Pet.state.armed, true, "armed seeded from the correct token's read");
});

// The "clear token" affordance runs the same idempotent teardown as on401 (edge F-9):
// it clears the stored token and re-enters the authenticate state.
test("test_clear_token_re_enters_authenticate_state", () => {
  const { Pet } = loadPet();
  Pet.token.set("tok");
  Pet.state.authRequired = false;
  Pet.auth.clearToken();
  assert.equal(Pet.token.get(), null, "clear drops the stored token");
  assert.equal(Pet.state.authRequired, true, "clear re-enters the authenticate state");
});
