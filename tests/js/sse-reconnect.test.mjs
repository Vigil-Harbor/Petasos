// Unit tests for Pet.sse bounded-backoff reconnect (petasos/console/static/petasos.js).
//
// Regression for PET-142: the console SSE client was single-strike — the first
// stream fault latched 10s polling for the rest of the session, with no attempt
// to re-establish the stream until a full page reload. PET-142 inserts bounded
// exponential backoff with jitter *before* the concede-to-polling step: a
// retryable fault (clean close, mid-stream read error, network failure, or any
// non-auth HTTP status) schedules a jittered, capped reconnect; the operator
// returns to push cadence on the reconnected stream's first bytes; only 401/403
// and an exhausted attempt budget concede to polling terminally, exactly as the
// pre-PET-142 worst case. See docs/specs PET-142 (D1–D12, Done-when 1–8).
//
// Harness (the suite's load-bearing scaffolding). Because this suite drives
// connect() (not just _dispatch), each test builds a FRESH sandbox whose globals
// include what connect() touches that the existing shims omit: a stub `fetch`
// (URL-branching), controllable fake timers (addressable by kind, NOT fired
// blindly), Node's AbortController, TextDecoder/TextEncoder, a Math whose
// `random` is test-controlled, and a capturing console. Stubs return
// already-resolved promises and every drive step is `<fire>; await flush()`
// (drain the microtask queue) so no assertion observes a microtask-stale state.
//
// Zero npm dependencies: Node's built-in test runner + assert + vm. Run with:
//   node --test tests/js/sse-reconnect.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

const here = dirname(fileURLToPath(import.meta.url));
const petasosJsPath = join(here, "..", "..", "petasos", "console", "static", "petasos.js");
const SRC = readFileSync(petasosJsPath, "utf8");

const enc = new TextEncoder();
const POLL_MS = 10000; // startFallbackPolling delay (petasos.js:545) — fixed, not a Pet.sse constant

// ── Minimal DOM shim (same shape as armed-sync / scanner-health) ────────────
function makeNode(nodeType) {
  return {
    nodeType,
    childNodes: [],
    style: {},
    className: "",
    title: "",
    appendChild(c) {
      this.childNodes.push(c);
      return c;
    },
    setAttribute() {},
    querySelector() {
      return null;
    },
    get textContent() {
      if (this.nodeType === 3) return this.nodeValue;
      return this.childNodes.map((c) => c.textContent).join("");
    },
  };
}
function makeDocument() {
  return {
    currentScript: null, // _assetBase falls back to "/static/"
    createDocumentFragment() {
      return makeNode(11);
    },
    createElement(tag) {
      const el = makeNode(1);
      el.tagName = tag.toUpperCase();
      el.localName = tag;
      return el;
    },
    createTextNode(t) {
      const n = makeNode(3);
      n.nodeValue = String(t);
      return n;
    },
  };
}

// ── Promise/microtask helpers ───────────────────────────────────────────────
function makeDeferred() {
  let resolve, reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}
// One setImmediate (a macrotask) fires only after the entire microtask queue is
// drained, including microtasks queued by earlier microtasks — so a single flush
// settles a whole already-resolved promise cascade.
const flush = () => new Promise((r) => setImmediate(r));

// ── Controllable SSE stream (the reader behind a successful /events resp) ────
// read() pops queued results (bytes / clean-done / fail); once the queue is
// empty it returns a *parked* deferred the test can later resolve-done or fail —
// modelling a healthy-but-quiet stream sitting on an open read.
function makeStream() {
  const queued = [];
  let tail = null;
  const reader = {
    read() {
      if (queued.length) {
        const it = queued.shift();
        if (it && it.__fail) return Promise.reject(it.error);
        return Promise.resolve(it);
      }
      tail = makeDeferred();
      return tail.promise;
    },
  };
  return {
    reader,
    pushBytes(s) {
      queued.push({ done: false, value: enc.encode(s) });
      return this;
    },
    pushDone() {
      queued.push({ done: true });
      return this;
    },
    pushFail(e) {
      queued.push({ __fail: true, error: e || new TypeError("read error") });
      return this;
    },
    endClean() {
      if (tail) {
        const t = tail;
        tail = null;
        t.resolve({ done: true });
      }
    },
    failTail(e) {
      if (tail) {
        const t = tail;
        tail = null;
        t.reject(e || new TypeError("read error"));
      }
    },
  };
}

// ── /events outcome constructors ────────────────────────────────────────────
const REJECT = (e) => ({ type: "reject", error: e || new TypeError("Failed to fetch") });
const HTTP = (status) => ({ type: "http", status });
const STREAM = (stream) => ({ type: "stream", stream });
const KEEPALIVE = ":keepalive\n\n"; // a chunk with no event:/data: — counts as bytes (liveness), dispatches nothing

// ── Fake-timer registry (addressable by kind, honors clearTimeout) ──────────
function makeTimers() {
  let nextId = 1;
  const handles = new Map();
  const seen = []; // every delay ever armed (F-2 collision guard)
  return {
    setTimeout(cb, delay) {
      const id = nextId++;
      handles.set(id, { id, cb, delay });
      seen.push(delay);
      return id;
    },
    clearTimeout(id) {
      handles.delete(id);
    },
    // startPolling (health) uses setInterval and only runs on mount — these tests
    // drive Pet.sse.connect() directly, so the interval path is dormant. Provide
    // harmless capture so a stray call never throws.
    setInterval(cb, delay) {
      const id = nextId++;
      handles.set(id, { id, cb, delay, interval: true });
      return id;
    },
    clearInterval(id) {
      handles.delete(id);
    },
    fireWhere(pred) {
      for (const h of [...handles.values()]) {
        if (pred(h)) {
          handles.delete(h.id);
          h.cb();
          return true;
        }
      }
      return false;
    },
    countDelay(d) {
      return [...handles.values()].filter((h) => h.delay === d).length;
    },
    seenDelays() {
      return seen.slice();
    },
    size() {
      return handles.size;
    },
  };
}

// ── Build a fresh, fully-driven console under vm ─────────────────────────────
function setup(opts = {}) {
  const timers = makeTimers();
  const warnings = [];
  const randomBox = { value: 0 }; // default 0 → deterministic backoff floor (capped/2), never collides with POLL/HEALTHY
  const ctl = {
    log: [],
    eventsCalls: 0,
    eventsHandler:
      opts.eventsHandler ||
      ((n) => {
        const arr = opts.events || [REJECT()];
        return arr[Math.min(n - 1, arr.length - 1)];
      }),
    scanHistory: opts.scanHistory || (() => ({ entries: [] })),
  };

  function fetchStub(url, _opts) {
    ctl.log.push(url);
    if (url.indexOf("/events") !== -1) {
      ctl.eventsCalls += 1;
      const outcome = ctl.eventsHandler(ctl.eventsCalls);
      if (outcome.type === "reject") return Promise.reject(outcome.error);
      if (outcome.type === "http") return Promise.resolve({ ok: false, status: outcome.status, body: null });
      if (outcome.type === "stream") {
        return Promise.resolve({ ok: true, status: 200, body: { getReader: () => outcome.stream.reader } });
      }
      throw new Error("bad /events outcome");
    }
    if (url.indexOf("/scan-history") !== -1) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(ctl.scanHistory()) });
    }
    if (url.indexOf("/health") !== -1) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ scanners: [], pipeline: null }) });
    }
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
  }

  const MathStub = Object.create(Math);
  MathStub.random = () => randomBox.value;

  const sandbox = {
    window: {},
    document: makeDocument(),
    fetch: fetchStub,
    setTimeout: timers.setTimeout,
    clearTimeout: timers.clearTimeout,
    setInterval: timers.setInterval,
    clearInterval: timers.clearInterval,
    AbortController,
    TextDecoder,
    TextEncoder,
    Math: MathStub,
    console: {
      warn: (...a) => warnings.push(a.join(" ")),
      error: () => {},
      log: () => {},
      info: () => {},
      debug: () => {},
    },
  };
  vm.runInNewContext(SRC, sandbox);
  const Pet = sandbox.window.__PETASOS_CONSOLE__;

  return {
    Pet,
    sse: Pet.sse,
    timers,
    ctl,
    warnings,
    randomBox,
    eventsCount: () => ctl.log.filter((u) => u.indexOf("/events") !== -1).length,
    // fire the single pending reconnect (backoff) timer: its delay is neither the
    // 10s poll nor the 60s durability timer. F-4 single-flight guarantees exactly
    // one such handle exists when a reconnect is pending.
    fireReconnect: () => timers.fireWhere((h) => h.delay !== POLL_MS && h.delay !== Pet.sse._HEALTHY_RESET_MS),
    fireHealthy: () => timers.fireWhere((h) => h.delay === Pet.sse._HEALTHY_RESET_MS),
    firePoll: () => timers.fireWhere((h) => h.delay === POLL_MS),
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// Test 1 — loader seams. Guards that the export ran and the new reconnect
// surface is present. (Note: errors on pre-change petasos.js because the seams
// don't exist; the clean red-fail tripwire is Test 2a, which references no new
// field.)
test("test_loader_exposes_reconnect_seams", () => {
  const { Pet, sse } = setup();
  assert.equal(typeof Pet, "object");
  assert.equal(typeof sse._scheduleReconnect, "function");
  assert.equal(typeof sse._openStream, "function");
  assert.equal(typeof sse._backoffDelay, "function");
  assert.equal(typeof sse._BACKOFF_BASE_MS, "number");
  assert.equal(typeof sse._BACKOFF_MAX_MS, "number");
  assert.equal(typeof sse._MAX_RECONNECTS, "number");
  assert.equal(typeof sse._HEALTHY_RESET_MS, "number");
});

// ─────────────────────────────────────────────────────────────────────────────
// Test 2a — fault then recover issues a SECOND /events fetch (Done-when 1).
// THE LOAD-BEARING REGRESSION TRIPWIRE: on today's single-strike code this count
// is exactly 1 (the first fault latches polling forever), so this assertion —
// which references NO new field — red-fails cleanly on the pre-change file.
test("test_fault_then_recover_issues_second_events_fetch", async () => {
  const recovered = makeStream().pushBytes(KEEPALIVE);
  const h = setup({ events: [REJECT(), STREAM(recovered)] });

  h.sse.connect();
  await flush(); // /events #1 rejects → reconnect scheduled
  h.fireReconnect();
  await flush(); // /events #2 resolves ok, reader yields a frame

  assert.ok(h.eventsCount() >= 2, `expected >= 2 /events fetches, got ${h.eventsCount()}`);
});

// Test 2b — the recovered stream is back on SSE (Done-when 1; secondary to 2a).
test("test_recovered_stream_is_back_on_sse", async () => {
  const recovered = makeStream().pushBytes(KEEPALIVE);
  const h = setup({ events: [REJECT(), STREAM(recovered)] });

  h.sse.connect();
  await flush();
  h.fireReconnect();
  await flush();

  assert.equal(h.sse._usingFallback, false, "first bytes of the reconnected stream flip back to LIVE");
});

// ─────────────────────────────────────────────────────────────────────────────
// Test 3 — budget refills ONLY after the durable window (Done-when 2; D11).
// First bytes flip to LIVE but do NOT zero the attempt counter; only the
// _HEALTHY_RESET_MS timer firing does. Then a second fault gets a full fresh
// _MAX_RECONNECTS budget — proving the refill is durability-gated, not first-byte.
test("test_budget_refills_only_after_durable_window", async () => {
  const healthy = makeStream().pushBytes(KEEPALIVE); // recovers, then parks on an open read
  const h = setup();
  h.ctl.eventsHandler = (n) => {
    if (n === 1) return REJECT(); // initial fault
    if (n === 2) return STREAM(healthy); // the durable reconnect
    return REJECT(); // n>=3: persistent, for the second storm
  };

  h.sse.connect();
  await flush(); // fault → reconnect scheduled, polling armed
  h.fireReconnect();
  await flush(); // first bytes: flip to LIVE, arm durability timer

  assert.equal(h.sse._usingFallback, false, "first bytes flip to LIVE");
  assert.ok(h.sse._reconnectAttempts > 0, "budget NOT yet refilled on first byte (durability pending)");
  assert.equal(h.timers.countDelay(h.sse._HEALTHY_RESET_MS), 1, "durability timer is armed");

  h.fireHealthy();
  await flush();
  assert.equal(h.sse._reconnectAttempts, 0, "durable stream refills the budget to 0");

  // Second fault: the parked healthy read fails; a full fresh storm must run.
  const before = h.eventsCount(); // initial + 1 reconnect = 2
  healthy.failTail();
  await flush(); // → reconnect scheduled (attempt 1 of a fresh budget)
  for (let i = 0; i < h.sse._MAX_RECONNECTS; i++) {
    h.fireReconnect();
    await flush();
  }
  assert.equal(
    h.eventsCount() - before,
    h.sse._MAX_RECONNECTS,
    "the refilled budget allows a full _MAX_RECONNECTS-attempt storm"
  );
  assert.equal(h.sse._reconnectTimer, null, "second storm concedes (no pending timer)");
  assert.equal(h.sse._usingFallback, true, "terminal polling after the second storm");
});

// ─────────────────────────────────────────────────────────────────────────────
// Test 4 — persistent failure is bounded, then concedes to polling (Done-when 3).
// Also pins F-3: at most one live /scan-history poll timer across the whole storm.
test("test_persistent_failure_bounded_then_polling", async () => {
  const h = setup({ events: [REJECT()] }); // always rejects
  h.randomBox.value = 0; // deterministic backoff {500,1000,2000,4000,8000,15000} — none == POLL/HEALTHY (F-2)

  h.sse.connect();
  await flush();
  assert.ok(h.timers.countDelay(POLL_MS) <= 1, "at most one poll timer (after first fault)");

  for (let i = 0; i < h.sse._MAX_RECONNECTS; i++) {
    h.fireReconnect();
    await flush();
    assert.ok(h.timers.countDelay(POLL_MS) <= 1, "F-3: never more than one live poll timer");
  }

  assert.equal(h.eventsCount(), h.sse._MAX_RECONNECTS + 1, "storm = initial + _MAX_RECONNECTS attempts");
  assert.equal(h.sse._reconnectTimer, null, "no pending reconnect after the cap");
  assert.equal(h.sse._usingFallback, true, "terminal: polling is the worst case (== today)");
  assert.equal(h.timers.countDelay(POLL_MS), 1, "exactly one live poll timer at terminal concede");
  assert.ok(h.warnings.length >= 1, "one console signal on terminal concede");

  // F-2: no armed backoff delay ever collided with the poll/durability delays.
  const backoffs = h.timers.seenDelays().filter((d) => d !== POLL_MS && d !== h.sse._HEALTHY_RESET_MS);
  for (const d of backoffs) {
    assert.notEqual(d, POLL_MS, "backoff delay must never equal the poll delay");
    assert.notEqual(d, h.sse._HEALTHY_RESET_MS, "backoff delay must never equal the durability delay");
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// Test 5 — 401/403 route straight to polling with zero reconnect attempts; a 5xx
// control case DOES reconnect (Done-when 4; pins D9 "only auth is terminal").
test("test_auth_401_routes_straight_to_polling", async () => {
  for (const status of [401, 403]) {
    const h = setup({ events: [HTTP(status)] });
    h.sse.connect();
    await flush();
    assert.equal(h.eventsCount(), 1, `${status}: exactly one /events fetch (zero reconnect attempts)`);
    assert.equal(h.sse._reconnectTimer, null, `${status}: no reconnect scheduled`);
    assert.equal(h.sse._reconnectAttempts, 0, `${status}: attempt budget untouched`);
    assert.equal(h.sse._usingFallback, true, `${status}: terminal polling`);
    assert.ok(h.warnings.some((w) => w.indexOf(String(status)) !== -1), `${status}: one auth console signal`);
  }

  // Control: a 500 is retryable, so it MUST schedule a reconnect.
  const h500 = setup({ events: [HTTP(500)] });
  h500.sse.connect();
  await flush();
  assert.notEqual(h500.sse._reconnectTimer, null, "500 is non-auth → reconnect scheduled");
  assert.ok(h500.sse._reconnectAttempts > 0, "500 consumes a reconnect attempt");
});

// ─────────────────────────────────────────────────────────────────────────────
// Test 6 — disconnect() cancels a pending reconnect and leaks no timer (Done-when 5).
test("test_disconnect_cancels_pending_reconnect", async () => {
  const h = setup({ events: [REJECT()] });
  h.sse.connect();
  await flush();
  assert.notEqual(h.sse._reconnectTimer, null, "precondition: a reconnect is pending");

  h.sse.disconnect();
  assert.equal(h.sse._reconnectTimer, null, "reconnect timer cancelled");
  assert.equal(h.sse._healthyTimer, null, "durability timer cancelled");
  assert.equal(h.sse._reconnectAttempts, 0, "attempt budget reset");
  assert.equal(h.sse._usingFallback, false, "polling stopped on teardown");

  const before = h.eventsCount();
  h.fireReconnect(); // nothing should be captured to fire
  await flush();
  assert.equal(h.eventsCount(), before, "no resurrection: firing yields no further /events fetch");
});

// Test 6b — a clean {done:true} that resolved before teardown must NOT resurrect
// the stream (Done-when 5; D12 generation token). The F-1 race: disconnect()
// interposes between read() and its already-queued {done:true} continuation.
test("test_clean_done_after_disconnect_does_not_resurrect", async () => {
  const s = makeStream(); // first read() parks on a deferred we control
  const h = setup({ events: [STREAM(s)] });

  h.sse.connect();
  await flush(); // pump reaches a *pending* read()

  s.endClean(); // queue the {done:true} continuation as a microtask
  h.sse.disconnect(); // bump _gen BEFORE the continuation runs
  await flush(); // continuation runs: gen !== _gen → no-op

  assert.equal(h.sse._reconnectTimer, null, "stale done scheduled no reconnect");
  assert.equal(h.eventsCount(), 1, "no further /events fetch (no resurrection)");
});

// ─────────────────────────────────────────────────────────────────────────────
// Test 7 — the blip shows POLLING specifically while a reconnect is PENDING, not
// a misleading LIVE while the stream is down (Done-when 6; F-9).
test("test_blip_polling_only_while_a_reconnect_is_pending", async () => {
  const h = setup({ events: [REJECT()] });
  h.sse.connect();
  await flush();
  assert.equal(h.sse._usingFallback, true, "polling active during backoff (blip would read POLLING)");
  assert.notEqual(h.sse._reconnectTimer, null, "a reconnect is genuinely pending (transient window, not terminal)");
});

// ─────────────────────────────────────────────────────────────────────────────
// Test 8 — backoff curve is bounded and jittered (Done-when 2; F-8).
// Pure helper — no timers/connect. Equal jitter: delay ∈ [capped/2, capped),
// half-open. random=0 hits the floor exactly; random≈1 approaches but never
// reaches the per-n ceiling (capped) — the two differ, so jitter is present.
test("test_backoff_curve_bounded_and_jittered", () => {
  const { sse, randomBox } = setup();
  const base = sse._BACKOFF_BASE_MS;
  const max = sse._BACKOFF_MAX_MS;

  for (let n = 0; n <= sse._MAX_RECONNECTS; n++) {
    const capped = Math.min(base * Math.pow(2, n), max);

    randomBox.value = 0;
    const floor = sse._backoffDelay(n);
    assert.equal(floor, capped / 2, `n=${n}: random=0 → exactly capped/2`);
    assert.ok(floor >= capped / 2, `n=${n}: never below capped/2`);

    // random→1 probes the formula's algebraic ceiling (not a runtime-reachable
    // value: Math.random is [0,1), so capped itself is unreachable).
    randomBox.value = 0.9999999;
    const ceil = sse._backoffDelay(n);
    assert.ok(ceil < capped, `n=${n}: strictly below the per-n ceiling (half-open)`);
    assert.ok(ceil < max, `n=${n}: under the global cap _BACKOFF_MAX_MS`);
    assert.ok(ceil > floor, `n=${n}: jitter present (ceiling probe != floor)`);
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// Test 9 — a clean stream end is RETRYABLE (brief D1). The first connect's reader
// returns {done:true} immediately (proxy lifetime-cap / graceful close), with NO
// intervening disconnect() — so it schedules a reconnect, not a terminal demotion.
test("test_clean_stream_end_is_retryable", async () => {
  const s = makeStream().pushDone();
  const h = setup({ events: [STREAM(s)] });

  h.sse.connect();
  await flush();

  assert.notEqual(h.sse._reconnectTimer, null, "clean close schedules a reconnect");
  assert.ok(h.sse._reconnectAttempts > 0, "clean close consumes a reconnect attempt (not terminal)");
});

// ─────────────────────────────────────────────────────────────────────────────
// Test 10 — a flapping bytes-then-die stream is BOUNDED (Done-when 2/3; D11/F-2).
// Each attempt yields one frame (flips LIVE, arms the durability timer) then dies
// before the durability timer fires. A naive first-byte reset would refill the
// budget every cycle and loop unbounded; the durability gate keeps it capped.
test("test_flapping_bytes_then_die_is_bounded", async () => {
  const h = setup();
  h.randomBox.value = 0;
  // Fresh "frame then immediate read-error" stream on every /events call.
  h.ctl.eventsHandler = () => STREAM(makeStream().pushBytes(KEEPALIVE).pushFail());

  h.sse.connect();
  await flush(); // #1: frame → (attempts 0, no flip) → die → reconnect scheduled
  for (let i = 0; i < h.sse._MAX_RECONNECTS; i++) {
    h.fireReconnect();
    await flush(); // each: frame → flip LIVE + arm healthy → die → clear healthy, attempts++
  }

  assert.equal(h.eventsCount(), h.sse._MAX_RECONNECTS + 1, "bytes-then-die flap bounded to initial + _MAX_RECONNECTS");
  assert.equal(h.sse._reconnectTimer, null, "flap concedes (no pending timer)");
  assert.equal(h.sse._usingFallback, true, "terminal polling after a bounded flap");
  assert.equal(h.timers.countDelay(h.sse._HEALTHY_RESET_MS), 0, "no durability timer survives (never refilled the budget)");
});

// ─────────────────────────────────────────────────────────────────────────────
// Test 11 — a reconnect's fallback-poll re-hydration does not double-count the
// PET-138 disarmed-bypass tally (brief D3). accrueBypass's `n > prev` max-gate
// absorbs re-observation of the same row (eviction-proof, no double count).
test("test_reconnect_does_not_double_count_bypass", async () => {
  const row = { event_type: "bypassed_disarmed", session_id: "sess-1", bypassed_count: 4 };
  // The fallback poll re-hydration returns the SAME row the tally already holds.
  const h = setup({ events: [REJECT()], scanHistory: () => ({ entries: [row] }) });

  h.Pet.accrueBypass([row]); // seed the tally to C = 4
  const C = h.Pet.bypassTotal();
  assert.equal(C, 4, "precondition: seeded bypass total is 4");

  h.sse.connect();
  await flush(); // fault → startFallbackPolling → getScanHistory re-hydrates the same row

  assert.equal(h.Pet.bypassTotal(), C, "re-hydration of the same row does not inflate the bypass total");
});
