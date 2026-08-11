// PET-166: client-side read-scope behavior (petasos.js).
//
// Most cases drive a PURE SEAM, never renderDashboard: no tests/js module drives it
// (two stub it outright, the rest never reach it), which is exactly why D12 puts the
// empty-state ladder and the scoped subtitle behind Pet.historyEmptyState /
// Pet.scopedHistorySubtitle rather than inline at the render site.
//
// Mints its own node:vm realm and its own resetState(), following the shipped
// per-module pattern. Assert via Object.keys().length, never deepEqual on Pet.state
// objects (cross-realm prototypes).
//
// Zero npm deps: Node's built-in test runner + node:vm over the real shipped petasos.js.
// Run with: node --test tests/js/profile-scoped-reads.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

function makeNode(nodeType) {
  return {
    nodeType,
    childNodes: [],
    style: {},
    className: "",
    attrs: {},
    appendChild(child) { this.childNodes.push(child); return child; },
    setAttribute(k, v) { this.attrs[k] = v; },
    removeAttribute(k) { delete this.attrs[k]; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    addEventListener() {},
  };
}
const document = {
  createDocumentFragment() { return makeNode(11); },
  createElement(tag) { const el = makeNode(1); el.tagName = tag.toUpperCase(); return el; },
  createTextNode(t) { const n = makeNode(3); n.nodeValue = String(t); return n; },
};

const here = dirname(fileURLToPath(import.meta.url));
const petasosJsPath = join(here, "..", "..", "petasos", "console", "static", "petasos.js");
// AbortController / TextDecoder / fetch are runtime APIs petasos.js already relies
// on (the SSE pump); the shim provides them so _openStream can be driven headlessly.
const sandbox = {
  window: {}, document, console,
  setTimeout, clearTimeout, setInterval, clearInterval,
  AbortController, TextDecoder,
  fetch: function () { return new Promise(function () {}); },
};
vm.runInNewContext(readFileSync(petasosJsPath, "utf8"), sandbox);
const Pet = sandbox.window.__PETASOS_CONSOLE__;

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

function resetState() {
  Pet.state.readScope = null;
  Pet.state.historyReadScope = null;
  Pet.state.historyHasOlder = false;
  Pet.state.spoolTruncated = false;
  Pet.state.scopeError = null;
  Pet.state.scopeNotice = false;
  Pet.state.scanHistory = [];
  Pet.state.bypassBySession = {};
  Pet.state.historyStack = [];
  Pet.state.historyAtHead = true;
  Pet.state.historyFilter = "all";
  Pet.state.selectedHermesProfile = null;
  Pet.state.authRequired = false;
  Pet.hostProfile.source = "none";
  Pet.hostProfile.profile = "";
  Pet.hostProfile.current = "";
  Pet.sse._scopeLive = true;
  Pet.sse._scopeRefusal = null;
  Pet.sse._usingFallback = false;
}

function embedded(profile) {
  Pet.hostProfile.source = "sdk";
  Pet.hostProfile.profile = profile;
  Pet.state.selectedHermesProfile = profile;
}

function scope(state, selected, equipped, tier) {
  return {
    selected: selected === undefined ? "beta" : selected,
    equipped: equipped === undefined ? "alpha" : equipped,
    equipped_tier: tier || "profile",
    live: state === "equipped",
    state,
  };
}

// ── 1: scoped URLs asserted by PARSING, not substring ────────────────────────

test("js/scoped-urls: every read carries the profile, parsed not matched", async () => {
  resetState();
  embedded("beta");
  const seen = [];
  const origReq = Pet.api._req;
  Pet.api._req = function (path, opts) { seen.push({ path, opts }); return Promise.resolve({}); };
  try {
    await Pet.api.getScanHistory(100, "beta|1.0~s-a");
    await Pet.api.getHealth();
    await Pet.api.getArmed();
    await Pet.api.setArmed(false);
    await Pet.api.postScan("hi", "inbound", null);
  } finally {
    Pet.api._req = origReq;
  }
  const url = (i) => new URL("http://x" + seen[i].path);
  // getScanHistory already carries "?limit=", so the separator must be "&" — a naive
  // "?profile=" append parses as part of the `before` value with NO profile at all.
  assert.equal(url(0).searchParams.get("profile"), "beta");
  assert.equal(url(0).searchParams.get("before"), "beta|1.0~s-a");
  assert.equal(url(1).searchParams.get("profile"), "beta");
  assert.equal(url(2).searchParams.get("profile"), "beta");
  // The write carries the scope in the BODY (a query-borne selector is a 422).
  assert.equal(url(3).searchParams.get("profile"), null);
  assert.equal(JSON.parse(seen[3].opts.body).profile, "beta");
  // postScan carries it nowhere: a playground scan is a write against the equipped binding.
  assert.equal(url(4).searchParams.get("profile"), null);
  assert.equal(JSON.parse(seen[4].opts.body).profile, undefined);
});

test("js/standalone-renders-equipped-form: no scope emitted, every affordance equipped", async () => {
  resetState(); // source "none", readScope null
  const seen = [];
  const origReq = Pet.api._req;
  Pet.api._req = function (path) { seen.push(path); return Promise.resolve({}); };
  try {
    await Pet.api.getScanHistory(100);
    await Pet.api.getHealth();
    await Pet.api.getArmed();
    await Pet.api.setArmed(true);
  } finally {
    Pet.api._req = origReq;
  }
  for (const p of seen) assert.ok(p.indexOf("profile=") === -1, "no scope on " + p);
  // And every scoped affordance renders its equipped form off a null scope — a bare
  // readScope.state dereference would throw here instead.
  assert.equal(Pet.isForeignScope(), false);
  assert.equal(Pet.playgroundScopeNote(Pet.state.readScope), null);
  assert.equal(Pet.selfmodTileLabel(Pet.isForeignScope()).label, "self-tamper");
  assert.equal(Pet.scanHistorySubtitle(12, 4413), "showing last 12 of 4413"); // "of N" present
  assert.equal(Pet.historyEmptyState([], [], null, "all", false, ""), null); // equipped fall-through
  assert.equal(Pet._scopePollState().running, false);
});

// ── D19: the absent-scope predicate ──────────────────────────────────────────

test("js/is-foreign-scope: null is the equipped form, one implementation", () => {
  resetState();
  assert.equal(Pet.isForeignScope(null), false);
  assert.equal(Pet.isForeignScope(undefined), false);
  assert.equal(Pet.isForeignScope(scope("equipped", "alpha")), false);
  assert.equal(Pet.isForeignScope(scope("not_equipped")), true);
  assert.equal(Pet.isForeignScope(scope("unknown")), true);
  Pet.state.readScope = scope("not_equipped");
  assert.equal(Pet.isForeignScope(), true); // zero-arg reads Pet.state.readScope
});

// ── D12: subtitle composition ────────────────────────────────────────────────

test("js/scoped-subtitle-composition: four clauses, one appender, shipped seam untouched", () => {
  assert.equal(
    Pet.scopedHistorySubtitle("showing last 12", "beta", "newest 09:14 (6d ago)", true, true),
    "showing last 12 for beta · newest 09:14 (6d ago) · stale · self-tamper only"
  );
  // The paged-under-foreign form keeps the identity on the view that reaches furthest
  // into another profile's data; age and stale are head-only.
  assert.equal(
    Pet.scopedHistorySubtitle("showing older history", "beta", null, false, false),
    "showing older history for beta"
  );
  // The clause is emitted by the seam, so the render site must not append it again.
  const s = Pet.scopedHistorySubtitle("showing last 3", "beta", null, false, true);
  assert.equal(s.split("self-tamper only").length - 1, 1);
  // The shipped seam's two-argument signature is unchanged.
  assert.equal(Pet.scanHistorySubtitle.length, 2);
  assert.equal(Pet.scanHistorySubtitle(12, 4413), "showing last 12 of 4413");
});

test("js/equipped-paging-unchanged: scans_total still drives subtitle and gate", () => {
  // The fence that keeps D12's narrowing off the equipped path.
  assert.equal(Pet.scanHistorySubtitle(12, 4413), "showing last 12 of 4413");
  assert.equal(Pet.scanHistoryHasOlder(12, 4413), true);
  assert.equal(Pet.scanHistoryHasOlder(0, 4413), false);   // the b > 0 term survives
  assert.equal(Pet.scanHistoryHasOlder(12, 12), false);
  // PET-165's equipped filtered-empty copy renders verbatim.
  const arm = Pet.historyEmptyState([{}], [], null, "selfmod", false, "");
  assert.equal(arm.text, "No self-tamper events in the buffered window.");
});

test("js/scoped-history-has-older: server boolean, buffer term kept", () => {
  // Neither case below is reachable from scans_total alone, which is the point.
  assert.equal(Pet.scopedHistoryHasOlder(12, true), true);   // small scans_total, older exist
  assert.equal(Pet.scopedHistoryHasOlder(12, false), false); // large scans_total, none older
  // b > 0 survives: a click over a transiently-empty buffer would re-mint from the
  // Nth-newest row and silently omit the head band (PET-152 E-2/E-4).
  assert.equal(Pet.scopedHistoryHasOlder(0, true), false);
});

// ── D12: the empty-state ladder ──────────────────────────────────────────────

test("js/history-empty-state-ladder: arm order preserved, copy scope-aware", () => {
  const paged = { entries: [], olderTruncated: false };
  // Arm 1 (paged-empty) is positional and deliberately exempt from the naming rule.
  assert.equal(Pet.historyEmptyState([], [], paged, "all", true, "beta").arm, 1);
  assert.equal(Pet.historyEmptyState([], [], paged, "all", true, "beta").text, "no older history");

  // Arm 2, equipped: PET-165's copy verbatim (the reversal this ladder must not make).
  assert.equal(
    Pet.historyEmptyState([{}], [], null, "selfmod", false, "").text,
    "No self-tamper events in the buffered window."
  );
  // Arm 2, foreign: names both the filter and the profile.
  assert.equal(
    Pet.historyEmptyState([{}], [], null, "selfmod", true, "beta").text,
    "no self-tamper events among the rows retained for beta"
  );
  // Arm 2's empty-buffer exception returns arm 3, so token and copy never disagree.
  const exc = Pet.historyEmptyState([], [], null, "selfmod", true, "beta");
  assert.equal(exc.arm, 3);
  assert.equal(exc.text, "no scans retained for beta");

  // Arm 3, foreign only; the EQUIPPED branch falls through to scanHistoryRows (null),
  // which is what keeps the "no scans yet" literal owned by that seam.
  assert.equal(Pet.historyEmptyState([], [], null, "all", true, "beta").arm, 3);
  assert.equal(Pet.historyEmptyState([], [], null, "all", false, ""), null);

  // Arm 4: rows present -> null (render them).
  assert.equal(Pet.historyEmptyState([{}], [{}], null, "all", true, "beta"), null);

  // The !histPaged guard: while paged, an emptying live buffer must NOT replace the
  // fetched page with an empty-state sentence (PET-148's invariant).
  const withRows = { entries: [{}], olderTruncated: false };
  assert.equal(Pet.historyEmptyState([], [{}], withRows, "all", true, "beta"), null);
});

// ── D12: staleness ───────────────────────────────────────────────────────────

test("js/scan-history-age: fresh, stale, empty, degenerate, future", () => {
  const now = Date.now() / 1000;
  assert.equal(Pet.scanHistoryAge([]), null);
  assert.equal(Pet.scanHistoryAge(null), null);
  assert.equal(Pet.scanHistoryAge([{}]), null);                       // absent timestamp
  assert.equal(Pet.scanHistoryAge([{ timestamp: "nope" }]), null);    // non-numeric
  const fresh = Pet.scanHistoryAge([{ timestamp: now - 240 }]);
  assert.equal(fresh.stale, false);
  assert.ok(/^newest \d\d:\d\d \(4m ago\)$/.test(fresh.label));
  const stale = Pet.scanHistoryAge([{ timestamp: now - 7200 }]);
  assert.equal(stale.stale, true);
  assert.ok(stale.label.indexOf("2h ago") !== -1);
  // A future timestamp clamps rather than producing a negative age that would read
  // as the freshest row.
  const future = Pet.scanHistoryAge([{ timestamp: now + 600 }]);
  assert.equal(future.stale, false);
  assert.ok(future.label.indexOf("just now") !== -1);
});

// ── D8: the self-tamper tile relabel ─────────────────────────────────────────

test("js/selfmod-tile-scope-relabel: value kept, label and help scoped", () => {
  const equipped = Pet.selfmodTileLabel(false);
  const foreign = Pet.selfmodTileLabel(true);
  assert.equal(equipped.label, "self-tamper");
  assert.equal(foreign.label, "self-tamper (this dashboard's binding)");
  assert.ok(foreign.help.indexOf("bound to") !== -1);
  // The amended help no longer claims "the scan history below" counts the same thing.
  assert.ok(equipped.help.indexOf("age out of the scan history below") !== -1);
  assert.ok(foreign.help.indexOf("age out of the scan history below") === -1);
  // House style: no em dashes in either string.
  assert.ok(equipped.help.indexOf("\u2014") === -1);
  assert.ok(foreign.help.indexOf("\u2014") === -1);
  assert.ok(foreign.label.indexOf("\u2014") === -1);
});

// ── D9: the connection chip ──────────────────────────────────────────────────

test("js/conn-chip-scoped-class: className not just label, three distinct titles", () => {
  resetState();
  Pet.state.selectedHermesProfile = "beta";
  const live = Pet.connChipView(false, true, null);
  assert.equal(live.className, "live");
  assert.equal(live.label, "LIVE");

  const scoped = Pet.connChipView(false, false, null);
  assert.ok(scoped.className.indexOf("scoped") !== -1); // the CLASS, not merely the label
  assert.equal(scoped.label, "SCOPED");
  assert.ok(scoped.title.indexOf("beta") !== -1);       // names the selected profile

  // The two refusal titles are distinct and neither names the refused profile.
  const refused = Pet.connChipView(false, false, "profile");
  const atCap = Pet.connChipView(false, false, "capacity");
  assert.ok(refused.className.indexOf("scoped") !== -1);
  assert.ok(refused.title.indexOf("profile not found") !== -1);
  assert.ok(refused.title.indexOf("beta") === -1);
  assert.ok(atCap.title.indexOf("capacity") !== -1);
  assert.notEqual(refused.title, atCap.title);
  assert.notEqual(scoped.title, refused.title);

  // POLLING outranks SCOPED: a dead connection is the more urgent fact.
  const polling = Pet.connChipView(true, false, "capacity");
  assert.equal(polling.label, "POLLING");
  assert.ok(polling.className.indexOf("polling") !== -1);
});

// ── D10: the playground note ─────────────────────────────────────────────────

test("js/playground-scope-note: present when foreign, null when live or absent", () => {
  assert.equal(Pet.playgroundScopeNote(null), null);
  assert.equal(Pet.playgroundScopeNote(scope("equipped", "alpha")), null);
  const note = Pet.playgroundScopeNote(scope("not_equipped"));
  assert.ok(note.indexOf("equipped binding") !== -1);
  assert.ok(note.indexOf("\u2014") === -1); // house style
});

// ── D7: the shared 422 test ──────────────────────────────────────────────────

test("js/is-profile-422: status-keyed, not error-keyed", () => {
  // A 422 body carries no `error`, so the readers' `!d.error` gates would treat it
  // as an empty success and wipe healthy panels.
  assert.equal(Pet.isProfile422({ _status: 422, detail: [{ field: "profile", message: "x" }] }), true);
  assert.equal(Pet.isProfile422({ _status: 422, detail: [{ field: "before", message: "x" }] }), false);
  assert.equal(Pet.isProfile422({ detail: [{ field: "profile" }] }), false);
  assert.equal(Pet.isProfile422({ error: "boom" }), false);
  assert.equal(Pet.isProfile422(null), false);
});

// ── D17: the armed write under a scope change ────────────────────────────────

test("js/armed-write-scope-change: drop-and-re-read, never reconcile the stale bit", () => {
  // A switch landing mid-POST: the decision must be drop-and-re-read, must leave the
  // control re-armable (armedSeeded false), and must banner nothing about the prior scope.
  const moved = Pet.armedWriteView({ scopeMoved: true, response: { armed: true }, next: true });
  assert.equal(moved.action, "drop");
  assert.equal(moved.armedSeeded, false);
  assert.equal(moved.banner, null);
  assert.equal(moved.reread, true);
  assert.equal(moved.armed, undefined); // the stale optimistic bit is NOT reconciled

  // A 409 surfaces detail[0].message and leaves the switch in server-truth position
  // (it would otherwise snap back silently and read as a broken button).
  const refused = Pet.armedWriteView({
    scopeMoved: false, next: false,
    response: { _status: 409, detail: [{ field: "profile", message: "not the equipped profile" }] },
  });
  assert.equal(refused.action, "refused");
  assert.equal(refused.banner, "not the equipped profile");
  assert.equal(refused.armed, true); // reverted from the optimistic false
  assert.equal(refused.reread, true);

  // A 422 is handled distinctly from the 409 and from a success.
  const rejected = Pet.armedWriteView({
    scopeMoved: false, next: false,
    response: { _status: 422, detail: [{ field: "profile", message: "gone" }] },
  });
  assert.equal(rejected.action, "rejected");
  assert.equal(rejected.banner, "gone");

  // The ordinary path still reconciles to the authoritative value.
  const ok = Pet.armedWriteView({ scopeMoved: false, response: { armed: false }, next: false });
  assert.equal(ok.action, "reconcile");
  assert.equal(ok.armedSeeded, true);
  assert.equal(ok.armed, false);
});

test("js/armed-test-state: the read-only latch seam exists", () => {
  const st = Pet._armedTestState();
  assert.equal(Object.keys(st).length, 3);
  assert.equal(typeof st.busy, "boolean");
  assert.equal(typeof st.seeded, "boolean");
  assert.equal(typeof st.confirmPending, "boolean");
});

// ── D17/D19: invalidation and the payload-derived-state rule ─────────────────

test("js/read-scope-invalidation: a rebind clears every payload-derived fact", async () => {
  resetState();
  embedded("beta");
  Pet.state.readScope = scope("not_equipped");
  Pet.state.historyReadScope = scope("not_equipped");
  Pet.state.historyHasOlder = true;
  Pet.state.spoolTruncated = true;
  Pet.state.scanHistory = [{ scan_id: "s-beta" }];
  Pet.state.bypassBySession = { s1: 972 };
  Pet.state.historyFilter = "selfmod";

  // Drive the real rebind (SDK axis) with a fresh selection.
  const origConnect = Pet.sse.connect;
  Pet.sse.connect = function () {};
  sandbox.window.__HERMES_PLUGIN_SDK__ = {
    fetchJSON: function () { return Promise.resolve({}); },
    profileScope: { profile: "gamma", currentProfile: "alpha", profiles: [], subscribe: function () { return function () {}; } },
  };
  try {
    Pet.hostProfile._rebind();
  } finally {
    Pet.sse.connect = origConnect;
    delete sandbox.window.__HERMES_PLUGIN_SDK__;
  }

  // null is defined as the equipped form, so the transient window degrades toward
  // the safe direction rather than toward the previous profile's name.
  assert.equal(Pet.state.readScope, null);
  assert.equal(Pet.state.historyReadScope, null);
  assert.equal(Pet.state.historyHasOlder, false);
  assert.equal(Pet.state.spoolTruncated, false);
  assert.equal(Pet.state.scanHistory.length, 0);
  assert.equal(Object.keys(Pet.state.bypassBySession).length, 0); // D17: the headline number
  assert.equal(Pet.state.historyAtHead, true);
  assert.equal(Pet.state.historyStack.length, 0);
  // The arm control is NOT left disabled by the invalidation (a null scope is equipped).
  assert.equal(Pet.isForeignScope(), false);
});

test("js/fallback-poll-drops-superseded-scope: an in-flight resolve across a rebind never lands", async () => {
  // D17 uniformity: the fallback history poll captures _scopeGen at send time like
  // the other four scoped readers. Hold its request open across a real rebind, then
  // settle it with the PREVIOUS profile's rows — nothing may land.
  resetState();
  embedded("beta");
  let resolveHistory;
  const origGet = Pet.api.getScanHistory;
  Pet.api.getScanHistory = function () {
    return new Promise(function (res) { resolveHistory = res; });
  };
  const origConnect = Pet.sse.connect;
  Pet.sse.connect = function () {};
  sandbox.window.__HERMES_PLUGIN_SDK__ = {
    fetchJSON: function () { return Promise.resolve({}); },
    profileScope: { profile: "gamma", currentProfile: "alpha", profiles: [], subscribe: function () { return function () {}; } },
  };
  try {
    Pet._poll.startFallback();   // issues the initial read, held open above
    Pet.hostProfile._rebind();   // bumps the scope generation mid-flight
    resolveHistory({ entries: [{ scan_id: "s-beta-stale" }], read_scope: scope("not_equipped", "beta") });
    await flush();
    assert.equal(Pet.state.scanHistory.length, 0, "stale rows dropped");
    assert.equal(Pet.state.historyReadScope, null, "stale scope label dropped");
    assert.equal(Object.keys(Pet.state.bypassBySession).length, 0, "no bypass accrual off a dropped page");
  } finally {
    Pet.api.getScanHistory = origGet;
    Pet.sse.connect = origConnect;
    delete sandbox.window.__HERMES_PLUGIN_SDK__;
    Pet.unmount(); // clears the fallback timer so later tests see a quiet slate
  }
});

test("js/history-filter-survives-scope-change", async () => {
  resetState();
  embedded("beta");
  Pet.state.historyFilter = "selfmod";
  const origConnect = Pet.sse.connect;
  Pet.sse.connect = function () {};
  sandbox.window.__HERMES_PLUGIN_SDK__ = {
    fetchJSON: function () { return Promise.resolve({}); },
    profileScope: { profile: "gamma", currentProfile: "alpha", profiles: [], subscribe: function () { return function () {}; } },
  };
  try {
    Pet.hostProfile._rebind();
  } finally {
    Pet.sse.connect = origConnect;
    delete sandbox.window.__HERMES_PLUGIN_SDK__;
  }
  // A view preference, not profile data: clearing it would silently discard an
  // explicit operator selection.
  assert.equal(Pet.state.historyFilter, "selfmod");
  // And the resulting empty panel names both the filter and the profile.
  assert.equal(
    Pet.historyEmptyState([{}], [], null, "selfmod", true, "gamma").text,
    "no self-tamper events among the rows retained for gamma"
  );
});

test("js/bypass-cleared-on-scope-change: the tile reflects only the new profile", () => {
  resetState();
  Pet.accrueBypass([{ event_type: "bypassed_disarmed", session_id: "a1", bypassed_count: 972 }]);
  assert.equal(Pet.bypassTotal(), 972);
  // Object.keys().length, never deepEqual (cross-realm prototypes).
  assert.equal(Object.keys(Pet.state.bypassBySession).length, 1);
  Pet.state.bypassBySession = {};
  Pet.accrueBypass([{ event_type: "bypassed_disarmed", session_id: "b1", bypassed_count: 4 }]);
  assert.equal(Pet.bypassTotal(), 4);
  assert.equal(Object.keys(Pet.state.bypassBySession).length, 1);
});

// ── D9: SSE transitions ──────────────────────────────────────────────────────

test("js/read-scope-frame: live false downgrades to SCOPED, zero reconnects", () => {
  resetState();
  let reconnects = 0;
  const origSched = Pet.sse._scheduleReconnect;
  Pet.sse._scheduleReconnect = function () { reconnects += 1; };
  try {
    Pet.sse._dispatch("read_scope", JSON.stringify(scope("not_equipped")));
  } finally {
    Pet.sse._scheduleReconnect = origSched;
  }
  assert.equal(reconnects, 0);                 // an idle stream is not an outage
  assert.equal(Pet.sse._usingFallback, false); // and never concedes to polling
  assert.equal(Pet.sse._scopeLive, false);
  assert.equal(Pet.connChipView(false, Pet.sse._scopeLive, Pet.sse._scopeRefusal).label, "SCOPED");
  assert.equal(Pet.state.readScope.state, "not_equipped");
});

test("js/scope-live-resets-on-reconnect-not-only-connect", () => {
  // _scheduleReconnect calls _openStream DIRECTLY, so a connect()-only reset would
  // leave the chip reading SCOPED over a genuinely live stream.
  resetState();
  Pet.sse._scopeLive = false;
  Pet.sse._scopeRefusal = "capacity";
  Pet.sse._openStream(); // the sandbox fetch never settles, so only the reset runs
  assert.equal(Pet.sse._scopeLive, true);   // reset lives in _openStream
  assert.equal(Pet.sse._scopeRefusal, null);
  assert.equal(Pet.connChipView(false, Pet.sse._scopeLive, Pet.sse._scopeRefusal).label, "LIVE");
});

// ── D3: the scoped poll ──────────────────────────────────────────────────────

test("js/scope-poll-is-singleton: one timer across switches, cleared on teardown", () => {
  resetState();
  embedded("beta");
  const origConnect = Pet.sse.connect;
  Pet.sse.connect = function () {};
  sandbox.window.__HERMES_PLUGIN_SDK__ = {
    fetchJSON: function () { return Promise.resolve({}); },
    profileScope: { profile: "", currentProfile: "alpha", profiles: [], subscribe: function () { return function () {}; } },
  };
  try {
    // Three switches: A -> B -> C -> A, each through the real rebind path.
    for (const name of ["gamma", "delta", "beta"]) {
      sandbox.window.__HERMES_PLUGIN_SDK__.profileScope.profile = name;
      Pet.state.readScope = scope("not_equipped", name);
      Pet.sse._scopeLive = false;
      Pet.hostProfile._rebind();
    }
    assert.equal(Pet._scopePollState().running, true); // exactly one, not four
    // The gate goes false when a live equipped stream replaces the idle one.
    Pet.state.readScope = scope("equipped", "beta", "beta");
    Pet.sse._scopeLive = true;
    Pet.sse._dispatch("read_scope", JSON.stringify(scope("equipped", "beta", "beta")));
    Pet.hostProfile._rebind();
  } finally {
    Pet.sse.connect = origConnect;
    delete sandbox.window.__HERMES_PLUGIN_SDK__;
  }
  Pet.unmount();
  assert.equal(Pet._scopePollState().running, false); // cleared on teardown
});

test("js/scope-poll-survives-equipped-flip-until-a-live-stream-lands", () => {
  // Keyed on the stream's own liveness as well as the scope: on the SDK-fallback
  // equipped-flip path there is no rebind and no reconnect, so a scope-only gate
  // would freeze both the chip and the panel with no path back.
  resetState();
  embedded("beta");
  Pet.state.readScope = scope("not_equipped");
  Pet.sse._scopeLive = false;
  Pet.sse._dispatch("read_scope", JSON.stringify(scope("not_equipped")));
  assert.equal(Pet._scopePollState().running, true);

  // The selection becomes equipped while the stream is STILL the idle one.
  Pet.state.readScope = scope("equipped", "beta", "beta");
  Pet.sse._dispatch("read_scope", JSON.stringify(scope("equipped", "beta", "beta")));
  assert.equal(Pet._scopePollState().running, true); // still polling: the stream is idle

  Pet.unmount();
  assert.equal(Pet._scopePollState().running, false);
});

// ── D15: the foreign provenance branch ───────────────────────────────────────

test("js/foreign-provenance-row: not-verifiable copy, never tamper copy", () => {
  resetState();
  const panelFor = (prov) => collectText(Pet.scanDetailPanel({
    scan_id: "e-1", source: "enforcement", event_type: "block", provenance: prov,
    timestamp: 1, safe: false, tool: "web_request", session_id: "s1", armed: true,
  })).join(" ");

  const foreign = panelFor("foreign");
  assert.ok(foreign.indexOf("another profile's key") !== -1, foreign);
  assert.ok(foreign.indexOf("not verifiable from here") !== -1);
  // Never the tamper copy: a foreign row is not a forgery claim.
  assert.ok(foreign.indexOf("may not be a genuine") === -1);
  // House style, asserted on the added string itself (the panel carries shipped copy too).
  const added = "Signed by another profile's key; not verifiable from here.";
  assert.ok(foreign.indexOf(added) !== -1);
  assert.ok(added.indexOf("—") === -1);

  // The shipped verdicts are untouched, and an unknown value still collapses to
  // unattested rather than to the new branch.
  assert.ok(panelFor("unverifiable").indexOf("may not be a genuine") !== -1);
  assert.ok(panelFor("genuine").indexOf("signature checks out") !== -1);
  assert.ok(panelFor("weird-value").indexOf("Integrity not configured") !== -1);
});

function collectText(node, out) {
  out = out || [];
  if (!node) return out;
  if (node.nodeValue != null) out.push(node.nodeValue);
  const kids = node.childNodes || [];
  for (let i = 0; i < kids.length; i++) collectText(kids[i], out);
  return out;
}
