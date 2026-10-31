// PET-236: the pure banner decision and the caption under it. renderDashboard is never
// driven, per the harness rule in profile-scoped-reads.test.mjs. Keys are asserted one
// at a time: these objects come from a node:vm realm, so deepEqual would fail on them.
//
// Run with: node --test tests/js/protection-banner.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";
import { consoleSources, createDOM, loadConsole } from "./harness.mjs";

const { makeDocument } = createDOM({
  attributes: "raw", events: "noop", selectors: "empty", localName: false,
});
const sandbox = {
  window: {}, document: makeDocument(), console,
  setTimeout, clearTimeout, setInterval, clearInterval,
  AbortController, TextDecoder,
  fetch: () => new Promise(() => {}),
};
loadConsole(sandbox);
const Pet = sandbox.window.__PETASOS_CONSOLE__;

const p = (status, extra = {}) => ({ status, ...extra });
const view = (armed, protection, extra = {}) => Pet.bannerView({ armed, protection, ...extra });

test("a null protection keeps today's output on every existing key", () => {
  const on = view(true, null);
  assert.equal(on.label, "EQUIPPED");
  assert.equal(on.sub, "Enforcement is ON");
  assert.equal(on.cls, "equip-banner");
  assert.equal(on.on, true);
  assert.equal(on.confirming, false);
  assert.equal(on.authRequired, false);
  const off = view(false, null);
  assert.equal(off.label, "UNEQUIPPED");
  assert.equal(off.sub, "Enforcement is OFF for every session");
  assert.equal(off.cls, "equip-banner disarmed");
  assert.equal(off.on, false);
  const nul = view(null, null);
  assert.equal(nul.label, "UNEQUIPPED");
  assert.equal(nul.on, false);
});

test("each status row while armed", () => {
  for (const status of ["no_copy", "not_enabled"]) {
    const v = view(true, p(status));
    assert.equal(v.label, "NOT PROTECTED");
    assert.equal(v.sub, "No Petasos hook can load for this profile");
    assert.equal(v.on, true);
    assert.equal(v.protectedLook, false);
    assert.equal(v.ariaLabel, "Petasos enforcement: armed, but no hook can load, click to unequip");
    assert.match(v.cls, /disarmed/);
  }
  const shadowed = view(true, p("shadowed"));
  assert.equal(shadowed.label, "WRONG PLUGIN COPY");
  assert.equal(shadowed.sub, "Another folder claims the petasos name");
  assert.equal(shadowed.protectedLook, false);
  assert.equal(shadowed.on, true);
  const unknown = view(true, p("unknown"));
  assert.equal(unknown.label, "CANNOT VERIFY");
  assert.equal(unknown.sub, "Armed. Could not check whether a hook can load");
  assert.equal(unknown.cls, "equip-banner unknown");
  assert.equal(unknown.protectedLook, true);
  const fine = view(true, p("hook_can_load"));
  assert.equal(fine.label, "EQUIPPED");
  assert.equal(fine.sub, "Armed, and a hook can load");
  assert.equal(fine.protectedLook, true);
  assert.equal(fine.ariaLabel, "Petasos enforcement: equipped, click to unequip");
});

test("regression PET-236: never EQUIPPED for no_copy or shadowed", () => {
  for (const status of ["no_copy", "not_enabled", "shadowed"]) {
    assert.notEqual(view(true, p(status)).label, "EQUIPPED");
  }
});

test("confirming keeps its label, and the toggle still reads armed", () => {
  const v = view(true, p("no_copy"), { confirming: true });
  assert.equal(v.label, "CONFIRM UNEQUIP?");
  assert.equal(v.sub, "Click again to disable all enforcement");
  assert.equal(v.on, true);
  assert.equal(v.confirming, true);
});

test("disarmed reads UNEQUIPPED for every status apart from refused", () => {
  for (const status of ["no_copy", "not_enabled", "shadowed", "unknown", "hook_can_load"]) {
    const v = view(false, p(status));
    assert.equal(v.label, "UNEQUIPPED");
    assert.equal(v.on, false);
    assert.equal(v.ariaLabel, "Petasos enforcement: unequipped, click to equip");
  }
});

test("a refused field wins over the armed bit, in both directions", () => {
  for (const armed of [true, false, null]) {
    const v = view(armed, p("not_enabled", { refused: true }));
    assert.equal(v.label, "NOT PROTECTED");
    assert.equal(v.on, false);
    assert.equal(v.cls, "equip-banner unknown");
    assert.equal(v.ariaLabel, "Petasos enforcement: not available for this profile");
  }
});

test("authRequired wins first", () => {
  const v = view(true, p("hook_can_load"), { authRequired: true });
  assert.equal(v.label, "AUTHENTICATE");
  assert.equal(v.authRequired, true);
  assert.equal(v.on, false);
  assert.equal(typeof v.ariaLabel, "string");
});

test("protectionNotice: null when there is nothing to say", () => {
  assert.equal(Pet.protectionNotice(null, null), null);
  assert.equal(Pet.protectionNotice(p("hook_can_load"), null), null);
  assert.equal(Pet.protectionNotice(p("hook_can_load"), p("hook_can_load")), null);
});

test("protectionNotice: carries detail and next steps as text", () => {
  const text = Pet.protectionNotice(p("no_copy", { detail: "No copy.", next_steps: "Do this." }), null);
  assert.match(text, /No copy\./);
  assert.match(text, /Do this\./);
});

test("protectionNotice: names the selected profile", () => {
  const text = Pet.protectionNotice(
    p("hook_can_load"),
    p("no_copy", { profile: "beta", detail: "No copy.", next_steps: "" }),
  );
  assert.match(text, /Selected profile beta: No copy\./);
});

test("armScopeView: a refused field disables; the one-argument form is unchanged", () => {
  const refused = p("not_enabled", { refused: true });
  assert.equal(Pet.armScopeView(null, refused).disabled, true);
  assert.equal(Pet.armScopeView({ state: "equipped", selected: "a", equipped: "a" }, refused).disabled, true);
  assert.equal(Pet.armScopeView(null).disabled, false);
});

test("first paint and paintBanner use one view", () => {
  const dashboard = consoleSources.find((s) => s.filename === "petasos-dashboard.js").source;
  for (const inline of ['"CONFIRM UNEQUIP?"', '"EQUIPPED"', '"UNEQUIPPED"', '"Enforcement is ON"']) {
    assert.equal(dashboard.includes(inline), false, `inline banner string left behind: ${inline}`);
  }
  assert.equal(dashboard.match(/Pet\.bannerView\(\{\s*authRequired: Pet\.state\.authRequired/g).length, 2);
  // A boolean bit agrees; a null bit keeps its deliberate difference (first paint: !== false).
  for (const armed of [true, false]) {
    const first = view(armed !== false, null);
    const paint = view(armed, null);
    assert.equal(first.label, paint.label);
    assert.equal(first.on, paint.on);
  }
  assert.equal(view(null !== false, null).on, true);
  assert.equal(view(null, null).on, false);
});
