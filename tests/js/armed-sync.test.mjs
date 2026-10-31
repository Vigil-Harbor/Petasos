// Unit tests for the `armed` arm of Pet.sse._dispatch (petasos/console/static/petasos.js).
//
// Regression for PET-116: live cross-tab sync of the Equipped/Unequipped bit.
// When one `obs` tab flips the master switch (POST /api/armed succeeds), the
// backend broadcasts an `armed` SSE frame; every other open tab's _dispatch
// adopts the authoritative pushed value into Pet.state.armed. This file pins:
//   1. State adoption — a valid boolean frame mutates Pet.state.armed.
//   2. Never-throw — a malformed frame (null / number / array / non-bool /
//      invalid JSON) is ignored, does not enter Pet.state.armed, and does not
//      throw (the cross-tab _dispatch runs renderDashboard synchronously, so a
//      throw would abort a live re-render in another tab — PET-99 posture).
//
// The re-render half is `_container`-guarded; `_container` is null in a headless
// load, so no real DOM is exercised here (the visual repaint and the in-flight
// `_armedBusy` guard stay in the spec's manual verification — `_armedBusy` is
// module-private and only set by a real in-flight doToggle).
//
// Zero npm dependencies: Node's built-in test runner + assert, a minimal DOM
// shim (same shape as scanner-health.test.mjs), and node:vm to evaluate the real
// shipped petasos.js. Run with:
//   node --test tests/js/armed-sync.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";
import { consoleSource, consoleSources, createDOM, loadConsole } from "./harness.mjs";

// ── Minimal DOM shim ────────────────────────────────────────────────────────
// The armed arm needs no real DOM (its re-render is _container-guarded and
// _container is null headlessly), but loading petasos.js under vm requires
// `document` to exist. Mirror the scanner-health shim shape.
const { makeDocument } = createDOM({
  title: true,
  textContent: "readonly",
});

const document = makeDocument();

// ── Load the real petasos.js under a sandbox ────────────────────────────────

const sandbox = { window: {}, document };
loadConsole(sandbox);
const Pet = sandbox.window.__PETASOS_CONSOLE__;

// ── Tests ───────────────────────────────────────────────────────────────────

// Guards that the export ran and the _dispatch seam is present.
test("loader: petasos.js exports Pet.sse._dispatch", () => {
  assert.equal(typeof Pet, "object");
  assert.equal(typeof Pet.sse, "object");
  assert.equal(typeof Pet.sse._dispatch, "function");
});

// Done-when 1 (state-adoption half): a valid boolean frame is adopted into
// Pet.state.armed, in both directions.
test("test_armed_adopts_valid_boolean", () => {
  Pet.state.armed = true;
  Pet.sse._dispatch("armed", JSON.stringify({ armed: false }));
  assert.equal(Pet.state.armed, false, "armed:false frame should set state to false");

  Pet.state.armed = false;
  Pet.sse._dispatch("armed", JSON.stringify({ armed: true }));
  assert.equal(Pet.state.armed, true, "armed:true frame should set state to true");
});

// ── PET-236: protection adoption, seeding, and the failed-response readers ──
// Each case gets a fresh realm. The SDK rejects as current Hermes does: ApiError
// with `status` and `body`, and a plain-sentence message.

function apiError(status, body, message = "Request failed") {
  return Object.assign(new Error(message), { status, body });
}

function freshConsole(sdk) {
  const box = {
    window: sdk ? { __HERMES_PLUGIN_SDK__: sdk } : {},
    document: makeDocument(),
    console, clearInterval, clearTimeout, setTimeout,
    setInterval: function (fn) { box.__tick = fn; return 1; },
    AbortController, TextDecoder,
    fetch: () => new Promise(() => {}),
  };
  const P = loadConsole(box);
  P.sse.connect = () => {}; // no transport under test
  return { P, tick: () => box.__tick() };
}

function embedded(reject) {
  const { P, tick } = freshConsole({
    fetchJSON: () => (reject ? Promise.reject(reject) : Promise.resolve({})),
  });
  P.hostProfile.source = "sdk";
  return { P, tick };
}

const flush = () => new Promise((r) => setImmediate(r));
const GOOD = { status: "hook_can_load", profile: "ops", next_steps: "", detail: "ok" };

test("adoption runs while a write is in flight, and the bit stays guarded", () => {
  const { P } = embedded();
  P.state.armed = false;
  const view = P._scope.armedReadView({
    response: { armed: true, protection: { status: "no_copy", profile: "ops", next_steps: "x" } },
    busy: true, scopeMoved: false, scopeParam: "ops",
  });
  assert.equal(P.state.protection.status, "no_copy");
  assert.equal(view.adoptArmed, false);
  assert.equal(view.adoptRead, false);
  assert.equal(view.protectionChanged, true);
  assert.equal(P._runtime.protectionSeeded, true);
});

test("a superseded read drops and adopts nothing", () => {
  const { P } = embedded();
  const view = P._scope.armedReadView({
    response: { armed: true, protection: GOOD }, busy: false, scopeMoved: true, scopeParam: "ops",
  });
  assert.equal(view.drop, true);
  assert.equal(P.state.protection, null);
});

test("every failed read after a hook_can_load scope reads CANNOT VERIFY, with no adoptRead", () => {
  const failures = [
    { error: "bad gateway", _status: 502 },
    { error: "timeout", _status: 504 },
    { detail: "boom", _status: 500 },
    { error: "network down" },
    { detail: "Not Found", _status: 404 },
    { detail: "Profile 'x' does not exist.", _status: 404 },
  ];
  for (const response of failures) {
    const { P } = embedded();
    P.state.protection = GOOD;
    const view = P._scope.armedReadView({ response, busy: false, scopeMoved: false, scopeParam: "ops" });
    assert.equal(P.state.protection.status, "unknown");
    assert.equal(P.state.protection.client, true);
    assert.equal(view.adoptRead, false);
    assert.equal(P.bannerView({ armed: true, protection: P.state.protection }).label, "CANNOT VERIFY");
  }
});

test("a failed read's detail is always a string, so Pet.h cannot throw", () => {
  for (const [response, want] of [
    [{ detail: [{ msg: "x" }], _status: 500 }, "HTTP 500"],
    [{}, "The request failed."],
    [null, "The request failed."],
  ]) {
    const { P } = embedded();
    P._scope.adoptProtection(response, "ops");
    assert.equal(P.state.protection.detail, want);
  }
});

test("401 and 422 are not adopted", () => {
  const { P } = embedded();
  P.state.protection = GOOD;
  P._scope.adoptProtection({ _status: 401, detail: "no" }, "ops");
  P._scope.adoptProtection({ _status: 422, detail: [{ field: "profile", message: "x" }] }, "ops");
  assert.equal(P.state.protection.status, "hook_can_load");
});

test("an SSE frame with no read still reports a read needed; a sent read does not", () => {
  const { P } = embedded();
  P.sse._dispatch("armed", JSON.stringify({ armed: true }));
  assert.equal(P._runtime.armedSeeded, true);
  assert.equal(P._scope.armedReadNeeded(), true);
  P._runtime.protectionSeeded = true; // the send site's latch, pending or failed
  assert.equal(P._scope.armedReadNeeded(), false);
  P._runtime.armedBusy = true;
  P._runtime.armedSeeded = false;
  assert.equal(P._scope.armedReadNeeded(), false);
});

test("change detection covers status, profile, next steps and selected_protection", () => {
  const { P } = embedded();
  const read = (body) => P._scope.adoptProtection({ armed: true, ...body }, "");
  assert.equal(read({ protection: { status: "no_copy", profile: "a", next_steps: "x" } }), true);
  assert.equal(read({ protection: { status: "no_copy", profile: "a", next_steps: "x" } }), false);
  assert.equal(read({ protection: { status: "no_copy", profile: "b", next_steps: "x" } }), true);
  assert.equal(read({ protection: { status: "no_copy", profile: "b", next_steps: "y" } }), true);
  assert.equal(read({
    protection: { status: "no_copy", profile: "b", next_steps: "y" },
    selected_protection: GOOD,
  }), true);
});

test("invalidate keeps the fields and clears the latch", () => {
  const { P } = embedded();
  P.state.protection = GOOD;
  P._runtime.protectionSeeded = true;
  P._scope.invalidate();
  assert.equal(P.state.protection.status, "hook_can_load");
  assert.equal(P._runtime.protectionSeeded, false);
});

test("regression PET-236: a refused read through ApiError never reads EQUIPPED", async () => {
  const { P } = embedded(apiError(404, '{"detail":"Plugin not found"}', "Plugin not found"));
  P.state.selectedHermesProfile = "ops";
  P.state.protection = GOOD;
  const d = await P.api.getArmed();
  assert.equal(d._status, 404);
  const view = P._scope.armedReadView({ response: d, busy: false, scopeMoved: false, scopeParam: "ops" });
  assert.equal(view.adoptRead, false);
  assert.equal(P.state.scopeNotice, false);
  assert.equal(P.state.protection.refused, true);
  assert.equal(P.state.protection.profile, "ops");
  assert.equal(P.state.selectedProtection, null);
  const banner = P.bannerView({ armed: true, protection: P.state.protection });
  assert.notEqual(banner.label, "EQUIPPED");
  assert.equal(banner.label, "NOT PROTECTED");
  assert.equal(P.armScopeView(null, P.state.protection).disabled, true);
});

test("the old message form still gives a status", async () => {
  const { P } = embedded(new Error('404: {"detail":"Plugin not found"}'));
  const d = await P.api.getArmed();
  assert.equal(d._status, 404);
  assert.equal(d.detail, "Plugin not found");
});

test("an ApiError body that is not an object counts as unparsed", async () => {
  for (const body of ["[1]", '"text"', "null", "not json"]) {
    const { P } = embedded(apiError(500, body, "Server error"));
    const d = await P.api.getArmed();
    assert.equal(d.error, "Server error");
    assert.equal(d._status, 500);
  }
});

test("an ApiError with status 0 stays {error}", async () => {
  const { P } = embedded(apiError(0, "", "offline"));
  const d = await P.api.getArmed();
  assert.equal(d.error, "offline");
  assert.equal(d._status, undefined);
});

test("Pet.responseOk gates on error and status", () => {
  const { P } = embedded();
  assert.equal(P.responseOk({ armed: true }), true);
  assert.equal(P.responseOk({ error: "x" }), false);
  assert.equal(P.responseOk({ _status: 500 }), false);
  assert.equal(P.responseOk(null), false);
});

test("regression PET-236: a failed health poll keeps the panels and the notice, in either order", async () => {
  for (const body of ['{"detail":"x"}', "{}"]) {
    for (const armedFirst of [true, false]) {
      const { P, tick } = embedded(apiError(500, body));
      P.hostProfile.source = "sdk";
      P.state.selectedHermesProfile = "ops";
      P.state.scannerHealth = ["kept"];
      P.state.scopeNotice = false;
      const armedRead = async () => {
        const d = await P.api.getArmed();
        const v = P._scope.armedReadView({ response: d, busy: false, scopeMoved: false, scopeParam: "ops" });
        assert.equal(v.adoptRead, false);
      };
      if (armedFirst) await armedRead();
      P._poll.startHealth();
      tick();
      await flush();
      if (!armedFirst) await armedRead();
      assert.equal(P.state.scannerHealth[0], "kept");
      assert.equal(P.state.scopeNotice, false);
      P._poll.stopHealth();
    }
  }
});

test("the health reader after a refused armed read adopts nothing", async () => {
  const { P, tick } = embedded(apiError(404, '{"detail":"Plugin not found"}'));
  P.state.selectedHermesProfile = "ops";
  P.state.scannerHealth = ["kept"];
  P._scope.adoptProtection(await P.api.getArmed(), "ops");
  P._poll.startHealth();
  tick();
  await flush();
  assert.equal(P.state.scannerHealth[0], "kept");
  assert.equal(P.state.scopeNotice, false);
  P._poll.stopHealth();
});

test("the other failed-response gates use Pet.responseOk at the source", () => {
  assert.doesNotMatch(consoleSource, /_historyResponseOk/);
  const dashboard = consoleSources.find((s) => s.filename === "petasos-dashboard.js").source;
  assert.match(dashboard, /if \(Pet\.responseOk\(d\)\) \{\s*Pet\._scope\.adoptRead\(d\); \/\/ PET-166 D19: health/);
  const config = consoleSources.find((s) => s.filename === "petasos-config.js").source;
  assert.match(config, /if \(!Pet\.responseOk\(d\)\) \{\s*formArea\.insertBefore/);
  assert.match(config, /else if \(resp && !Pet\.responseOk\(resp\)\)/);
  assert.match(config, /"Config unavailable: " \+ d\.detail/);
});

test("standalone: a failed first read stays null and is seeded; after a landed read it is unknown", () => {
  const { P } = freshConsole();
  assert.equal(P.hostProfile.source, "none");
  P._scope.adoptProtection({ error: "offline" }, "");
  assert.equal(P.state.protection, null);
  assert.equal(P._runtime.protectionSeeded, true);
  P._scope.adoptProtection({ armed: true, protection: GOOD }, "");
  P._scope.adoptProtection({ error: "offline" }, "");
  assert.equal(P.state.protection.status, "unknown");
});

test("standalone with no Hermes home: a body with no field keeps null", () => {
  const { P } = freshConsole();
  assert.equal(P._scope.adoptProtection({ armed: true }, ""), false);
  assert.equal(P.state.protection, null);
});

// Done-when 4: malformed frames never enter Pet.state.armed and never throw.
// Vectors: JSON null, a number, an array, an empty object (missing `armed`), a
// string-valued `armed`, a null-valued `armed` (the NaN-ish case — NaN cannot
// survive a JSON round-trip, it serializes to null), and a non-JSON string.
test("test_armed_ignores_malformed_frames_and_never_throws", () => {
  const badFrames = [
    "null",
    "5",
    "[]",
    "{}",
    JSON.stringify({ armed: "no" }),
    JSON.stringify({ armed: null }),
    "not json",
  ];
  for (const bad of badFrames) {
    Pet.state.armed = true;
    assert.doesNotThrow(
      () => Pet.sse._dispatch("armed", bad),
      `_dispatch threw on malformed frame: ${bad}`
    );
    assert.equal(
      Pet.state.armed,
      true,
      `malformed frame must not mutate Pet.state.armed: ${bad}`
    );
  }
});
