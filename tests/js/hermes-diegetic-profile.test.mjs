// Unit tests for PET-155 — diegetic profile binding: the Petasos console binds the
// Config Editor to Hermes's native sidebar profile switcher when embedded.
//
// Covers the JS surfaces added to petasos/console/static/petasos.js:
//   1. Pet.hostProfile — the capability layer. resolve() detects SDK vs query vs none
//      and canonicalizes profile/current to strings ("" = own/unknown); refreshCurrent()
//      reads the host /api/profiles/active; subscribe() observes selection changes (SDK
//      profileScope, or a foreign-safe history.pushState/replaceState patch + popstate);
//      attach()/detach() wire into the mount lifecycle; _rebind() re-binds on a flip.
//   2. Pet.renderDiegeticProfile (via renderHermesProfileSelector's opts.hostBinding) —
//      read-only render: bound name (escaped), binding tier, equipped-vs-management
//      banner (D5), no editable <select>.
//   3. renderConfig wiring — host pin reaches getConfig via Pet.state.selectedHermesProfile;
//      the generation guard drops out-of-order fetches; the diegetic 422 stays pinned.
//
// Like hermes-profile-selector.test.mjs this ships its own DOM shim, extended with
// innerHTML/insertBefore/firstChild/querySelectorAll plus a window with location/history/
// popstate, so the real petasos.js mount + renderConfig run under node:vm.
//
// Zero npm dependencies: Node's built-in test runner + assert + node:vm, evaluating the
// real shipped petasos.js. Run with:
//   node --test tests/js/hermes-diegetic-profile.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";
import assertLoose from "node:assert";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

// ── Interactive DOM shim (superset of hermes-profile-selector's) ────────────
function makeNode(nodeType) {
  return {
    nodeType, // 1 = element, 3 = text, 11 = fragment
    childNodes: [],
    style: {},
    dataset: {},
    attributes: {},
    handlers: {},
    className: "",
    title: "",
    value: undefined,
    parentNode: null,
    tabIndex: undefined,
    appendChild(child) {
      child.parentNode = this;
      this.childNodes.push(child);
      return child;
    },
    removeChild(child) {
      const i = this.childNodes.indexOf(child);
      if (i !== -1) this.childNodes.splice(i, 1);
      child.parentNode = null;
      return child;
    },
    insertBefore(node, ref) {
      node.parentNode = this;
      if (ref == null) { this.childNodes.push(node); return node; }
      const i = this.childNodes.indexOf(ref);
      if (i === -1) this.childNodes.push(node);
      else this.childNodes.splice(i, 0, node);
      return node;
    },
    remove() {
      if (this.parentNode) this.parentNode.removeChild(this);
    },
    setAttribute(k, v) {
      this.attributes[k] = String(v);
    },
    getAttribute(k) {
      return Object.prototype.hasOwnProperty.call(this.attributes, k) ? this.attributes[k] : null;
    },
    addEventListener(type, fn) {
      (this.handlers[type] = this.handlers[type] || []).push(fn);
    },
    querySelector(sel) {
      return matchAll(this, sel)[0] || null;
    },
    querySelectorAll(sel) {
      return matchAll(this, sel);
    },
    get firstChild() {
      return this.childNodes[0] || null;
    },
    get textContent() {
      if (this.nodeType === 3) return this.nodeValue;
      return this.childNodes.map((c) => c.textContent).join("");
    },
    set textContent(v) {
      const t = makeNode(3);
      t.nodeValue = String(v);
      t.parentNode = this;
      this.childNodes = [t];
    },
    set innerHTML(v) {
      // The console only ever assigns "" (a wipe). Treat any value as a clear.
      this.childNodes = [];
    },
    get innerHTML() {
      return "";
    },
  };
}

// Single-token selector matcher: ".class" | "tag" | "[data-x]" | "[data-x=\"v\"]".
// (Compound selectors like '.tab[data-key="x"]' are only used on keydown, untested.)
function nodeMatches(node, sel) {
  if (node.nodeType !== 1) return false;
  if (sel.startsWith(".")) {
    return (node.className || "").split(/\s+/).includes(sel.slice(1));
  }
  if (sel.startsWith("[")) {
    const m = /^\[([^=\]]+)(?:="([^"]*)")?\]$/.exec(sel);
    if (!m) return false;
    const attr = m[1];
    const key = attr.startsWith("data-") ? attr.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase()) : attr;
    const present = Object.prototype.hasOwnProperty.call(node.dataset, key) || Object.prototype.hasOwnProperty.call(node.attributes, attr);
    if (m[2] === undefined) return present;
    const val = node.dataset[key] != null ? node.dataset[key] : node.attributes[attr];
    return String(val) === m[2];
  }
  return node.tagName === sel.toUpperCase();
}
function matchAll(root, sel) {
  const out = [];
  const walk = (n) => {
    for (const c of n.childNodes) {
      if (c.nodeType === 1) {
        if (nodeMatches(c, sel)) out.push(c);
        walk(c);
      }
    }
  };
  walk(root);
  return out;
}

function makeDocument() {
  return {
    head: makeNode(1),
    createDocumentFragment() { return makeNode(11); },
    createElement(tag) {
      const el = makeNode(1);
      el.tagName = tag.toUpperCase();
      el.localName = tag;
      return el;
    },
    createElementNS(ns, tag) {
      const el = makeNode(1);
      el.tagName = tag.toUpperCase();
      el.localName = tag;
      el.namespaceURI = ns;
      return el;
    },
    createTextNode(t) {
      const node = makeNode(3);
      node.nodeValue = String(t);
      return node;
    },
  };
}

// Distinguishable original-history return values, so the patch's "return the captured
// result" contract (test #16) is assertable rather than undefined-vs-undefined.
const PUSH_RESULT = { tag: "push-result" };
const REPLACE_RESULT = { tag: "replace-result" };

function makeWindow(opts) {
  opts = opts || {};
  const popHandlers = [];
  const loc = { search: opts.search || "", href: "http://host/", pathname: "/", hash: "" };
  const searchFromUrl = (url) => {
    if (typeof url !== "string") return loc.search;
    const qi = url.indexOf("?");
    if (qi === -1) return ""; // no query in the new URL -> search cleared
    let q = url.slice(qi);
    const hi = q.indexOf("#");
    if (hi !== -1) q = q.slice(0, hi);
    return q;
  };
  const history = {
    calls: { push: 0, replace: 0 },
    pushState(state, title, url) { this.calls.push++; if (url !== undefined) loc.search = searchFromUrl(url); return PUSH_RESULT; },
    replaceState(state, title, url) { this.calls.replace++; if (url !== undefined) loc.search = searchFromUrl(url); return REPLACE_RESULT; },
  };
  const console = { warn() {}, error() {}, log() {} };
  return {
    location: loc,
    history,
    console,
    __HERMES_PLUGIN_SDK__: opts.sdk,
    addEventListener(type, fn) { if (type === "popstate") popHandlers.push(fn); },
    removeEventListener(type, fn) {
      if (type !== "popstate") return;
      const i = popHandlers.indexOf(fn);
      if (i !== -1) popHandlers.splice(i, 1);
    },
    _firePopstate() { popHandlers.slice().forEach((h) => h()); },
    _popCount() { return popHandlers.length; },
  };
}

// ── Load a fresh petasos.js per test (state + history patch must not leak) ──
const here = dirname(fileURLToPath(import.meta.url));
const petasosJsPath = join(here, "..", "..", "petasos", "console", "static", "petasos.js");
const src = readFileSync(petasosJsPath, "utf8");

function load(opts) {
  opts = opts || {};
  const win = makeWindow(opts);
  const sandbox = {
    window: win,
    document: makeDocument(),
    console: win.console,
    setTimeout: () => 0,
    clearTimeout: () => {},
    setInterval: () => 0,
    clearInterval: () => {},
    fetch: () => Promise.resolve({ ok: true, status: 200, statusText: "OK", json: () => Promise.resolve({}) }),
  };
  vm.runInNewContext(src, sandbox);
  const Pet = win.__PETASOS_CONSOLE__;
  return { Pet, win };
}

// Recording SDK. Routes /api/profiles/active, /api/profiles, /api/.../config.
function makeSdk(cfg) {
  cfg = cfg || {};
  const calls = [];
  const sdk = {
    fetchJSON(url, o) {
      calls.push({ url: String(url), opts: o });
      if (/\/profiles\/active/.test(url)) {
        if (cfg.activeReject) return Promise.reject(new Error("404: not found"));
        if (cfg.activeMalformed) return Promise.resolve("not-an-object");
        return Promise.resolve(cfg.active || { active: "", current: "" });
      }
      if (/\/profiles(\?|$)/.test(url)) return Promise.resolve({ profiles: cfg.profiles || [] });
      if (/config/.test(url)) {
        if (cfg.configResolver) return cfg.configResolver(url);
        if (cfg.configMode === "422") return Promise.resolve({ _status: 422, detail: [{ field: "profile", message: "Profile 'ghost' not found" }] });
        return Promise.resolve(cfg.config || { error: "stub-early-return" });
      }
      return Promise.resolve({});
    },
    calls,
  };
  if (cfg.profileScope !== undefined) sdk.profileScope = cfg.profileScope;
  return sdk;
}

// A profileScope companion stub whose profile/currentProfile are mutable; _fire()
// drives the reactive subscriber the same way ProfileProvider would.
function makeScope(init) {
  init = init || {};
  return {
    profile: init.profile != null ? init.profile : "",
    currentProfile: init.currentProfile != null ? init.currentProfile : "",
    profiles: init.profiles || [],
    _cb: null,
    _unsubCalls: 0,
    subscribe(cb) {
      this._cb = cb;
      const self = this;
      if (init.subscribeReturnsUndefined) return undefined;
      return function () { self._unsubCalls += 1; };
    },
    _fire() { if (this._cb) this._cb(); },
  };
}

function host() { return makeNode(1); }

function payload(over) {
  over = over || {};
  return Object.assign(
    {
      is_active: true,
      hermes_profile: "alpha",
      config_tier: "profile",
      profile_home: "/root/profiles/alpha",
      config_warning: null,
      effective_config: { tier1_threshold: 15, tier2_threshold: 30, tier3_threshold: 50 },
      active_profile_overrides: null,
      hermes_profiles: [
        { name: "alpha", path: "/r/alpha", is_active: true, tier: "profile" },
        { name: "beta", path: "/r/beta", is_active: false, tier: "profile" },
      ],
    },
    over,
  );
}

const hasClass = (el, c) => el.nodeType === 1 && (el.className || "").split(/\s+/).includes(c);
function findByClass(root, cls) {
  for (const c of root.childNodes) {
    if (c.nodeType === 1) {
      if (hasClass(c, cls)) return c;
      const deep = findByClass(c, cls);
      if (deep) return deep;
    }
  }
  return null;
}
function findByTag(root, tag) {
  for (const c of root.childNodes) {
    if (c.nodeType === 1) {
      if (c.tagName === tag) return c;
      const deep = findByTag(c, tag);
      if (deep) return deep;
    }
  }
  return null;
}
const tick = () => new Promise((r) => r());
async function flush() { for (let i = 0; i < 6; i++) await tick(); }

// Stub the heavy mount internals so Pet.mount completes under the shim.
function stubMount(Pet) {
  Pet.renderDashboard = function () {};
  Pet.sse.connect = function () {};
  Pet.sse.disconnect = function () {};
}
function configCalls(sdk) {
  return sdk.calls.filter((c) => /config/.test(c.url));
}

// ── 0. Loader guard ──────────────────────────────────────────────────────────
test("loader: petasos.js exports the PET-155 surfaces", () => {
  const { Pet } = load();
  assert.equal(typeof Pet.hostProfile, "object");
  assert.equal(typeof Pet.hostProfile.resolve, "function");
  assert.equal(typeof Pet.hostProfile.subscribe, "function");
  assert.equal(typeof Pet.hostProfile.attach, "function");
  assert.equal(typeof Pet.hostProfile.detach, "function");
  assert.equal(typeof Pet.renderDiegeticProfile, "function");
  assert.equal(typeof Pet.HOST_OWN_PROFILE_LABEL, "string");
});

// ── 1. Capability detection both ways ─────────────────────────────────────────
test("#1 capability detection: profileScope present -> sdk; absent -> query; no sdk -> none", () => {
  const sdkScope = makeSdk({ profileScope: makeScope({ profile: "research", currentProfile: "alpha" }) });
  const a = load({ sdk: sdkScope });
  assert.equal(a.Pet.hostProfile.resolve().source, "sdk");

  const sdkNoScope = makeSdk({}); // fetchJSON present, no profileScope
  const b = load({ sdk: sdkNoScope, search: "?profile=research" });
  assert.equal(b.Pet.hostProfile.resolve().source, "query");

  const c = load({}); // no SDK at all
  assert.equal(c.Pet.hostProfile.resolve().source, "none");
});

// ── 2. SDK re-bind re-fetches with the new ?profile=, no reload ───────────────
test("#2 SDK profileScope flip re-fetches /config with the new profile", () => {
  const scope = makeScope({ profile: "alpha", currentProfile: "alpha" });
  const sdk = makeSdk({ profileScope: scope });
  const { Pet, win } = load({ sdk });
  stubMount(Pet);
  Pet.mount(host());
  Pet.switchTab("cfg");
  assert.equal(Pet.state.selectedHermesProfile, "alpha");

  scope.profile = "research";
  scope.currentProfile = "alpha";
  scope._fire(); // host fires the reactive subscriber

  assert.equal(Pet.state.selectedHermesProfile, "research");
  const last = configCalls(sdk).pop();
  assert.ok(last && /config\?profile=research/.test(last.url), "config re-fetched with ?profile=research");
});

// ── 3. Fallback observes a replaceState flip (the headline footgun) ──────────
test("#3 fallback: replaceState flip re-binds (popstate-only would miss it)", () => {
  const sdk = makeSdk({});
  const { Pet, win } = load({ sdk, search: "" });
  stubMount(Pet);
  Pet.mount(host());
  Pet.switchTab("cfg");
  assert.equal(Pet.hostProfile.source, "query");

  // Sibling proof: a popstate-only listener (registered, but we drive replaceState)
  // never fires for a {replace:true} navigation.
  let popOnly = 0;
  win.addEventListener("popstate", () => { popOnly += 1; });

  win.history.replaceState({}, "", "?profile=research");

  assert.equal(Pet.state.selectedHermesProfile, "research");
  const last = configCalls(sdk).pop();
  assert.ok(last && /config\?profile=research/.test(last.url), "re-fetched /config?profile=research");
  assert.equal(popOnly, 0, "popstate-only listener would have missed the replaceState flip");
});

// ── 4. popstate still re-binds (back/forward) ────────────────────────────────
test("#4 fallback: a popstate with a changed ?profile= re-binds", () => {
  const sdk = makeSdk({});
  const { Pet, win } = load({ sdk, search: "?profile=alpha" });
  stubMount(Pet);
  Pet.mount(host());
  Pet.switchTab("cfg");
  assert.equal(Pet.state.selectedHermesProfile, "alpha");

  win.location.search = "?profile=beta"; // back/forward changed the URL
  win._firePopstate();

  assert.equal(Pet.state.selectedHermesProfile, "beta");
  assert.ok(/config\?profile=beta/.test(configCalls(sdk).pop().url));
});

// ── 5. Diegetic read-only render ─────────────────────────────────────────────
test("#5 diegetic render: no editable <select>, shows bound name + binding tier", () => {
  const { Pet } = load({ sdk: makeSdk({}) });
  const h = host();
  Pet.renderHermesProfileSelector(h, payload(), {
    hostBinding: { source: "query", profile: "research", current: "research", profiles: [] },
  });
  assert.equal(findByTag(h, "SELECT"), null, "no editable <select> in diegetic mode");
  const bound = findByClass(h, "pet-hermes-bound");
  assert.ok(bound, "bound-name read-out present");
  assert.equal(bound.textContent, "research");
  const binding = findByClass(h, "pet-hermes-binding");
  assert.ok(binding && binding.textContent.includes("tier"), "binding tier read-out present");
});

// ── 6. Equipped-vs-management banner (D5) ────────────────────────────────────
test("#6 banner: shown iff profile != '' && current != '' && profile != current", () => {
  const { Pet } = load({ sdk: makeSdk({}) });
  const mk = (profile, current) => {
    const h = host();
    Pet.renderHermesProfileSelector(h, payload({ is_active: false }), {
      hostBinding: { source: "sdk", profile, current, profiles: [] },
    });
    return h;
  };
  assert.ok(findByClass(mk("research", "alpha"), "pet-hermes-banner"), "differ -> banner");
  assert.equal(findByClass(mk("alpha", "alpha"), "pet-hermes-banner"), null, "equal -> no banner");
  assert.equal(findByClass(mk("research", ""), "pet-hermes-banner"), null, "current unknown -> suppressed");
});

// ── 7. Writes target the host profile via the body transport (D-WRITE) ───────
test("#7 write gate follows payload is_active; host pin rides buildSavePatch body", () => {
  const scope = makeScope({ profile: "research", currentProfile: "alpha" });
  const { Pet } = load({ sdk: makeSdk({ profileScope: scope }) });
  Pet.hostProfile.attach(); // pins Pet.state.selectedHermesProfile to the host profile
  assert.equal(Pet.state.selectedHermesProfile, "research");

  // Non-equipped (d.is_active === false) -> tag body profile = host.
  const nonEquipped = Pet.buildSavePatch({ fail_mode: "open" }, false, Pet.state.selectedHermesProfile);
  assert.equal(nonEquipped.profile, "research", "non-equipped save tags the host profile");

  // Equipped (is_active === true) -> omit profile (hot-apply). Sibling assertion.
  const equipped = Pet.buildSavePatch({ fail_mode: "open" }, true, Pet.state.selectedHermesProfile);
  assert.equal("profile" in equipped, false, "equipped save omits profile (write gate follows is_active)");
});

// ── 8. Unmount teardown restores history; no leaked listener ──────────────────
test("#8 fallback teardown: history restored, popstate listener removed", () => {
  const sdk = makeSdk({});
  const { Pet, win } = load({ sdk, search: "?profile=alpha" });
  const origPush = win.history.pushState;
  const origReplace = win.history.replaceState;
  stubMount(Pet);
  Pet.mount(host());
  assert.notEqual(win.history.replaceState, origReplace, "history patched while mounted");
  assert.equal(win._popCount(), 1, "one popstate listener installed");

  Pet.unmount();
  assert.equal(win.history.pushState, origPush, "pushState restored");
  assert.equal(win.history.replaceState, origReplace, "replaceState restored");
  assert.equal(win._popCount(), 0, "popstate listener removed");

  const before = win.history.calls.replace;
  win.history.replaceState({}, "", "?profile=ghost");
  assert.equal(win.history.calls.replace, before + 1, "original replaceState still works");
});

// ── 9. Untrusted-name escape (D7) ────────────────────────────────────────────
test("#9 untrusted name renders as a text node, no element injection", () => {
  const { Pet } = load({ sdk: makeSdk({}) });
  const evil = '<img src=x onerror=alert(1)>';
  const h = host();
  Pet.renderHermesProfileSelector(h, payload(), {
    hostBinding: { source: "query", profile: evil, current: evil, profiles: [] },
  });
  const bound = findByClass(h, "pet-hermes-bound");
  assert.ok(bound);
  assert.equal(findByTag(h, "IMG"), null, "no <img> element injected");
  assert.equal(bound.textContent, evil, "name preserved verbatim as escaped text");
  assert.ok(bound.childNodes.every((n) => n.nodeType === 3), "bound name is text node(s) only");
});

// ── 10. Standalone unchanged (regression) ────────────────────────────────────
test("#10 standalone (no sdk / source none): editable <select> renders as before", () => {
  const { Pet } = load({});
  Pet.state.configDirty = {};
  const h = host();
  // source "none" -> falls through to the editable PET-146 path.
  Pet.renderHermesProfileSelector(h, payload(), { selected: null, hostBinding: { source: "none", profile: "", current: "", profiles: [] }, onSwitch() {} });
  const select = findByTag(h, "SELECT");
  assert.ok(select, "editable <select> still renders");
  assert.equal(findByClass(h, "pet-hermes-bound"), null, "no diegetic read-out");
});

// ── 11. ""/own-profile normalization (embedded, empty ?profile=) ─────────────
test("#11 own-profile: embedded + empty ?profile= -> diegetic-on-own, no ?profile= read", async () => {
  const sdk = makeSdk({});
  const { Pet } = load({ sdk, search: "" });
  const desc = Pet.hostProfile.resolve();
  assert.equal(desc.source, "query", "embedded -> not standalone even on own profile");
  assert.equal(desc.profile, "", "own profile canonicalizes to ''");

  // Diegetic render on own: read-only placeholder, NOT the editable select.
  const h = host();
  Pet.renderHermesProfileSelector(h, payload(), { hostBinding: desc });
  assert.equal(findByTag(h, "SELECT"), null, "the two-dial bug must not survive on own profile");
  const bound = findByClass(h, "pet-hermes-bound");
  assert.equal(bound.textContent, Pet.HOST_OWN_PROFILE_LABEL, "own-profile placeholder shown");

  // Read targets own -> getConfig("") hits /api/config with no ?profile= query.
  await Pet.api.getConfig("");
  const ownReq = configCalls(sdk).pop();
  assert.ok(ownReq, "own-profile read issues a /config request");
  assert.equal(ownReq.url, "/api/config", "own-profile read hits /api/config (no query)");
  assert.ok(!/\?profile=/.test(ownReq.url), "own-profile read must not append ?profile=");
  // Banner absent (own == current both ""): assert no banner in the render.
  assert.equal(findByClass(h, "pet-hermes-banner"), null);
});

// ── 12. Off-cfg-tab re-bind is inert (state updates, no config fetch) ────────
test("#12 off-cfg flip: no config fetch, state updates, later cfg entry binds", () => {
  const sdk = makeSdk({});
  const { Pet, win } = load({ sdk, search: "" });
  stubMount(Pet);
  Pet.mount(host()); // starts on the obs tab
  assert.equal(Pet.state.tab, "obs");

  win.history.replaceState({}, "", "?profile=research");
  assert.equal(Pet.state.selectedHermesProfile, "research", "state updated even off-cfg");
  assert.equal(configCalls(sdk).length, 0, "no /config fetched while off the cfg tab");

  Pet.switchTab("cfg"); // later entry binds correctly
  const last = configCalls(sdk).pop();
  assert.ok(last && /config\?profile=research/.test(last.url), "cfg entry re-fetches the pinned profile");
});

// ── 13. /api/profiles/active failure resilience ──────────────────────────────
test("#13 active-profile fetch: reject / malformed / missing current -> current stays ''", async () => {
  const reject = load({ sdk: makeSdk({ activeReject: true }), search: "?profile=research" });
  reject.Pet.hostProfile.resolve();
  await reject.Pet.hostProfile.refreshCurrent();
  assert.equal(reject.Pet.hostProfile.current, "", "rejected fetch -> current unknown");

  const malformed = load({ sdk: makeSdk({ activeMalformed: true }), search: "?profile=research" });
  malformed.Pet.hostProfile.resolve();
  await malformed.Pet.hostProfile.refreshCurrent();
  assert.equal(malformed.Pet.hostProfile.current, "", "malformed body -> current unknown");

  const missing = load({ sdk: makeSdk({ active: { active: "x" } }), search: "?profile=research" });
  missing.Pet.hostProfile.resolve();
  await missing.Pet.hostProfile.refreshCurrent();
  assert.equal(missing.Pet.hostProfile.current, "", "missing 'current' field -> unknown");
});

// ── 14. Malformed profileScope falls back, not throws ────────────────────────
test("#14 malformed profileScope (no subscribe / profiles not array) -> fallback", () => {
  const a = load({ sdk: makeSdk({ profileScope: { profile: "x", currentProfile: "y" } }), search: "?profile=research" });
  assert.doesNotThrow(() => a.Pet.hostProfile.resolve());
  assert.equal(a.Pet.hostProfile.source, "query", "half-built companion (no subscribe) falls back");

  const b = load({ sdk: makeSdk({ profileScope: { subscribe: 7 } }), search: "?profile=research" });
  assert.equal(b.Pet.hostProfile.resolve().source, "query", "non-function subscribe falls back");
});

// ── 15. Foreign history patcher + skipped-unmount remount ────────────────────
test("#15 foreign patcher not clobbered; skipped-unmount remount fires one current cb", () => {
  const sdk = makeSdk({});
  const { Pet, win } = load({ sdk, search: "" });
  stubMount(Pet);

  // (a) Foreign wrapper installed ON TOP after our patch -> teardown must not clobber it.
  Pet.mount(host());
  const ourReplace = win.history.replaceState;
  let foreignCalls = 0;
  const foreign = function () { foreignCalls += 1; return ourReplace.apply(win.history, arguments); };
  win.history.replaceState = foreign;
  Pet.unmount();
  assert.equal(win.history.replaceState, foreign, "foreign wrapper on top is left intact");

  // (b) mount -> mount (skip unmount) -> exactly one *current* cb on a flip.
  const sdk2 = makeSdk({});
  const r = load({ sdk: sdk2, search: "" });
  stubMount(r.Pet);
  r.Pet.mount(host());
  r.Pet.mount(host()); // remount without unmount
  r.Pet.switchTab("cfg");
  r.win.history.replaceState({}, "", "?profile=research");
  assert.equal(r.Pet.state.selectedHermesProfile, "research");
  const cfgHits = configCalls(sdk2).filter((c) => /profile=research/.test(c.url));
  assert.ok(cfgHits.length >= 1, "the live cb fired");
});

// ── 16. Re-bind callback is exception-isolated ───────────────────────────────
test("#16 a throwing rebind cb does not break host pushState/replaceState", () => {
  const { Pet, win } = load({ sdk: makeSdk({}), search: "" });
  Pet.hostProfile.resolve(); // source query
  const teardown = Pet.hostProfile.subscribe(() => { throw new Error("boom"); });
  assert.doesNotThrow(() => {
    const r1 = win.history.replaceState({}, "", "?profile=z");
    assert.equal(r1, REPLACE_RESULT, "wrapper returns the original replaceState result");
    const r2 = win.history.pushState({}, "", "?profile=q");
    assert.equal(r2, PUSH_RESULT, "wrapper returns the original pushState result");
  });
  teardown();
});

// ── 17. Out-of-order in-flight fetches (generation guard) ────────────────────
// re-bind to Y then X; resolve X (current) then Y (superseded). The guard drops the
// stale Y .then before it does any work — observed via on401 (the first call past the
// guard): it fires once (X), not twice. The visible editor shows X, never Y.
test("#17 out-of-order config fetches: last bind wins (generation guard)", async () => {
  const pending = [];
  const sdk = makeSdk({
    configResolver: (url) => new Promise((resolve) => { pending.push({ url, resolve }); }),
  });
  const scope = makeScope({ profile: "alpha", currentProfile: "alpha" });
  sdk.profileScope = scope;
  const { Pet } = load({ sdk });
  stubMount(Pet);
  const el = host();
  Pet.mount(el);
  const containerEl = el.querySelector(".content");

  // Count getConfig .thens that pass the generation guard (on401 is the first call
  // after it). Only config payloads carry _cfg, so getProfiles arms don't inflate it.
  const origOn401 = Pet.auth.on401.bind(Pet.auth);
  let cfgThens = 0;
  Pet.auth.on401 = function (d) { if (d && d._cfg) cfgThens += 1; return origOn401(d); };

  Pet.switchTab("cfg");               // getConfig(alpha) #0 pending (never resolved)
  scope.profile = "Y"; scope._fire(); // renderConfig -> getConfig(Y) pending
  scope.profile = "X"; scope._fire(); // renderConfig -> getConfig(X) pending
  assert.equal(Pet.state.selectedHermesProfile, "X");

  const cfgPending = pending.filter((p) => /config/.test(p.url));
  const yReq = cfgPending.find((p) => /profile=Y/.test(p.url));
  const xReq = cfgPending.find((p) => /profile=X/.test(p.url));

  xReq.resolve({ error: "render-X", _cfg: true });  // current bind resolves first
  await flush();
  yReq.resolve({ error: "render-Y", _cfg: true });  // superseded bind resolves LAST
  await flush();

  assert.equal(cfgThens, 1, "the stale Y .then was dropped by the generation guard");
  const txt = containerEl.textContent;
  assert.ok(txt.includes("render-X"), "editor shows X");
  assert.ok(!txt.includes("render-Y"), "editor never shows the superseded Y");
});

// ── 18. subscribe() returning no teardown is handled ─────────────────────────
test("#18 SDK subscribe returns undefined -> unmount does not throw, history untouched", () => {
  const scope = makeScope({ profile: "research", currentProfile: "alpha", subscribeReturnsUndefined: true });
  const sdk = makeSdk({ profileScope: scope });
  const { Pet, win } = load({ sdk });
  const origPush = win.history.pushState;
  stubMount(Pet);
  Pet.mount(host());
  assert.equal(win.history.pushState, origPush, "SDK path never patches history");
  assert.doesNotThrow(() => Pet.unmount());
});

// ── 19. Unmount before mount completes ───────────────────────────────────────
test("#19 unmount before mount: history untouched, no throw", () => {
  const { Pet, win } = load({ sdk: makeSdk({}), search: "?profile=alpha" });
  const origPush = win.history.pushState;
  const origReplace = win.history.replaceState;
  assert.doesNotThrow(() => Pet.unmount()); // bridge cancelled-before-mount path
  assert.equal(win.history.pushState, origPush);
  assert.equal(win.history.replaceState, origReplace);
});

// ── 20. Whitespace-only / over-long name ─────────────────────────────────────
test("#20 whitespace-only -> own placeholder; over-long -> length-capped", () => {
  const { Pet } = load({ sdk: makeSdk({}) });

  const hWs = host();
  Pet.renderHermesProfileSelector(hWs, payload(), { hostBinding: { source: "query", profile: "   ", current: "", profiles: [] } });
  assert.equal(findByClass(hWs, "pet-hermes-bound").textContent, Pet.HOST_OWN_PROFILE_LABEL, "whitespace -> placeholder, not blank");

  const big = "p".repeat(5000);
  const hBig = host();
  Pet.renderHermesProfileSelector(hBig, payload(), { hostBinding: { source: "query", profile: big, current: big, profiles: [] } });
  const txt = findByClass(hBig, "pet-hermes-bound").textContent;
  assert.ok(txt.length <= Pet.HOST_NAME_DISPLAY_CAP + 1, "over-long name capped");
});

// ── 21. Unrelated history mutation is a no-op ────────────────────────────────
test("#21 unrelated history mutation (?profile= unchanged) triggers no config fetch", () => {
  const sdk = makeSdk({});
  const { Pet, win } = load({ sdk, search: "?profile=research" });
  stubMount(Pet);
  Pet.mount(host());
  Pet.switchTab("cfg");
  const baseline = configCalls(sdk).length;

  win.history.replaceState({}, "", "?profile=research&tab=2"); // profile unchanged
  assert.equal(configCalls(sdk).length, baseline, "no extra /config fetch for an unrelated mutation");
});

// ── 22. Diegetic 422 stays pinned (no revert to own) ─────────────────────────
test("#22 diegetic 422: error surfaced, host pin kept, no re-fetch loop", async () => {
  const sdk = makeSdk({ configMode: "422" });
  const scope = makeScope({ profile: "ghost", currentProfile: "alpha" });
  sdk.profileScope = scope;
  const { Pet } = load({ sdk });
  stubMount(Pet);
  const el = host();
  Pet.mount(el);
  const containerEl = el.querySelector(".content");
  Pet.switchTab("cfg");
  await flush();

  assert.equal(Pet.state.selectedHermesProfile, "ghost", "host pin NOT reverted to own/null");
  // PET-155 D7/§C: the 422 must be surfaced (not silently swallowed) -> the readable
  // backend detail renders as a role=alert in the cfg container, keeping the host pin.
  const txt = containerEl.textContent;
  assert.ok(txt.includes("Host profile not resolved"), "diegetic 422 surfaces the readable error");
  assert.ok(txt.includes("Profile 'ghost' not found"), "the backend detail reaches the user");
  const before = configCalls(sdk).length;
  await flush();
  assert.equal(configCalls(sdk).length, before, "no re-fetch loop after the 422");
});

// ── 23. Subscription lifecycle: one teardown, invoked once, nulled ───────────
test("#23 lifecycle: unmount invokes the stored teardown once and nulls it", () => {
  const sdk = makeSdk({});
  const { Pet, win } = load({ sdk, search: "" });
  stubMount(Pet);
  Pet.mount(host());
  Pet.switchTab("cfg");
  Pet.switchTab("obs");
  Pet.switchTab("cfg"); // away-and-back must not double-subscribe

  assert.equal(typeof Pet.hostProfile._teardown, "function", "teardown stored after mount");
  const orig = Pet.hostProfile._teardown;
  let calls = 0;
  Pet.hostProfile._teardown = function () { calls += 1; return orig.apply(this, arguments); };
  const origReplace = win.history.replaceState;

  Pet.unmount();
  assert.equal(calls, 1, "teardown invoked exactly once");
  assert.equal(Pet.hostProfile._teardown, null, "teardown nulled");
  assert.notEqual(win.history.replaceState, undefined);
});

// ── 24. SDK host flip drops the prior profile's unsaved edits (F-4 isolation) ─
// The standalone selector clears configDirty before onSwitch (petasos.js:2612);
// the host-driven diegetic rebind is never mediated by that selector, so it must
// drop the stale dirty map itself or profile A's edits leak into the next Apply
// against profile B (via currentConfigValues/buildSavePatch).
test("#24 SDK host flip drops the prior profile's unsaved edits (no cross-profile leak)", () => {
  const scope = makeScope({ profile: "alpha", currentProfile: "alpha" });
  const sdk = makeSdk({ profileScope: scope });
  const { Pet } = load({ sdk });
  stubMount(Pet);
  Pet.mount(host());
  Pet.switchTab("cfg");
  assert.equal(Pet.state.selectedHermesProfile, "alpha");

  // Operator edits a field under alpha (the diegetic config form stays editable).
  Pet.state.configDirty = { tier1_threshold: 99 };

  // Hermes sidebar flips the bound management profile to beta.
  scope.profile = "beta";
  scope._fire();

  assert.equal(Pet.state.selectedHermesProfile, "beta", "rebind switched the management target");
  // configDirty is reassigned inside petasos.js's vm realm, so its prototype differs
  // from this file's Object.prototype — assert emptiness by key count, not deepEqual({}).
  assert.equal(Object.keys(Pet.state.configDirty).length, 0, "alpha's unsaved edits dropped on the host flip");
  // Impact: a save built now cannot persist alpha's stale field into beta.
  const patch = Pet.buildSavePatch(Pet.state.configDirty, false, Pet.state.selectedHermesProfile);
  assert.ok(!("tier1_threshold" in patch), "stale field cannot reach the new target");
  assert.equal(patch.profile, "beta", "save is tagged for the new target only");
});

// ── 25. SDK current-only update keeps the operator's in-progress edits ────────
// A currentProfile-only flip (equipped changed elsewhere) does NOT move the bound
// selection, so the operator's edits to the still-selected profile must survive.
test("#25 SDK current-only flip (selection unchanged) keeps the operator's edits", () => {
  const scope = makeScope({ profile: "alpha", currentProfile: "alpha" });
  const sdk = makeSdk({ profileScope: scope });
  const { Pet } = load({ sdk });
  stubMount(Pet);
  Pet.mount(host());
  Pet.switchTab("cfg");

  Pet.state.configDirty = { tier1_threshold: 42 };

  // Equipped profile changes elsewhere; the bound selection stays alpha.
  scope.currentProfile = "beta";
  scope._fire();

  assert.equal(Pet.state.selectedHermesProfile, "alpha", "selection unchanged on a current-only update");
  // Realm-agnostic (see #24): assert the edit survived by count + value, not deepEqual.
  assert.equal(Object.keys(Pet.state.configDirty).length, 1, "edits preserved when the target is unchanged");
  assert.equal(Pet.state.configDirty.tier1_threshold, 42, "the exact in-progress edit is intact");
});

// ── 26. Query host flip (replaceState) drops the prior profile's unsaved edits ─
test("#26 query host flip (replaceState) drops the prior profile's unsaved edits", () => {
  const sdk = makeSdk({});
  const { Pet, win } = load({ sdk, search: "?profile=alpha" });
  stubMount(Pet);
  Pet.mount(host());
  Pet.switchTab("cfg");
  assert.equal(Pet.state.selectedHermesProfile, "alpha");

  Pet.state.configDirty = { tier2_threshold: 7 };

  win.history.replaceState({}, "", "?profile=beta");

  assert.equal(Pet.state.selectedHermesProfile, "beta", "query rebind switched the target");
  // Realm-agnostic emptiness check (see #24).
  assert.equal(Object.keys(Pet.state.configDirty).length, 0, "alpha's unsaved edits dropped on the URL flip");
});

// ── 27. refreshCurrent generation survives detach/remount ────────────────────
// attach()/detach() bump _gen so a slow /api/profiles/active reply from a prior
// (torn-down) mount is dropped by refreshCurrent's generation guard rather than
// mutating `current` / re-rendering after the remount.
test("#27 a stale refreshCurrent resolving after detach/remount cannot mutate current", async () => {
  // A controllable /api/profiles/active: each call gets its own deferred resolver.
  const actives = [];
  const sdk = {
    calls: [],
    fetchJSON(url, o) {
      this.calls.push({ url: String(url), opts: o });
      if (/\/profiles\/active/.test(url)) {
        let resolve;
        const p = new Promise((r) => { resolve = r; });
        actives.push({ url: String(url), resolve });
        return p;
      }
      if (/\/profiles(\?|$)/.test(url)) return Promise.resolve({ profiles: [] });
      if (/config/.test(url)) return Promise.resolve({ error: "stub" });
      return Promise.resolve({});
    },
  };
  const { Pet } = load({ sdk, search: "?profile=alpha" });
  stubMount(Pet);

  Pet.mount(host());           // attach #1 -> refreshCurrent#1 captures gen A
  await flush();               // refreshCurrent defers its fetch to a microtask -> actives[0]
  assert.ok(actives.length >= 1, "first mount issued a /profiles/active");
  const beforeRemount = actives.length;
  Pet.unmount();               // detach bumps _gen -> refreshCurrent#1 is now stale
  Pet.mount(host());           // remount: attach #2 -> refreshCurrent#2 captures a newer gen
  await flush();               // -> a fresh /profiles/active for the new lifecycle
  // Prove the remount genuinely re-fetched (so the stale-drop below is a real
  // supersede, not a no-op): attach #2 must issue its own /profiles/active.
  assert.ok(actives.length > beforeRemount, "remount (attach #2) issued a fresh /profiles/active");

  // The STALE first refresh resolves last, naming a bogus equipped profile.
  actives[0].resolve({ current: "STALE-ghost" });
  await flush();

  assert.notEqual(Pet.hostProfile.current, "STALE-ghost", "stale refresh dropped by the generation guard");
});

// ── 28. _sdk requires a CALLABLE fetchJSON (CodeRabbit) ──────────────────────
// A truthy-but-non-function fetchJSON is a half-built companion, not a usable SDK;
// it must fall through to standalone rather than route in and throw on first call.
test("#28 _sdk rejects a non-callable fetchJSON -> standalone (source none)", () => {
  const { Pet } = load({ sdk: { fetchJSON: {} }, search: "?profile=alpha" });
  assert.equal(Pet.hostProfile.resolve().source, "none", "non-function fetchJSON is not a usable embedded SDK");
});

// ── 29. Diegetic 422 surfaces the PROFILE detail, not detail[0] (CodeRabbit) ──
test("#29 diegetic 422 surfaces the profile detail even when it is not first", async () => {
  const sdk = makeSdk({
    configResolver: () => Promise.resolve({
      _status: 422,
      detail: [
        { field: "tier1_threshold", message: "must be an int" },   // non-profile error first
        { field: "profile", message: "Profile 'ghost' not found" },
      ],
    }),
  });
  sdk.profileScope = makeScope({ profile: "ghost", currentProfile: "alpha" });
  const { Pet } = load({ sdk });
  stubMount(Pet);
  const el = host();
  Pet.mount(el);
  const containerEl = el.querySelector(".content");
  Pet.switchTab("cfg");
  await flush();

  const txt = containerEl.textContent;
  assert.ok(txt.includes("Profile 'ghost' not found"), "the profile-field detail is shown");
  assert.ok(!txt.includes("must be an int"), "the non-profile detail is not used for the host-bound message");
});

// helper: find a <button> whose rendered text contains `label`
function findButtonByText(root, label) {
  let found = null;
  (function walk(n) {
    for (const c of n.childNodes) {
      if (c.nodeType !== 1 || found) continue;
      if (c.tagName === "BUTTON" && (c.textContent || "").includes(label)) { found = c; return; }
      walk(c);
    }
  })(root);
  return found;
}
const click = (btn) => { (btn.handlers.click || []).forEach((fn) => fn({ preventDefault() {}, stopPropagation() {} })); };

// ── 30. A save PUT resolving AFTER a host rebind cannot clobber the new profile ─
// The putConfig callback clears configDirty + writes config; without a generation
// guard a stale PUT from profile A (in flight when the host flips to B) would wipe
// B's fresh edits. The render-gen guard must drop it.
test("#30 stale save PUT after a host rebind is dropped (cannot wipe the new profile's edits)", async () => {
  let putResolve = null;
  const scope = makeScope({ profile: "alpha", currentProfile: "alpha" });
  const sdk = {
    calls: [],
    profileScope: scope,
    fetchJSON(url, o) {
      this.calls.push({ url: String(url), opts: o });
      if (/\/profiles\/active/.test(url)) return Promise.resolve({ active: "", current: "" });
      if (/\/profiles(\?|$)/.test(url)) return Promise.resolve({ profiles: [] });
      if (o && o.method === "PUT") return new Promise((r) => { putResolve = r; });
      if (/config/.test(url)) return Promise.resolve({ config: { tier1_threshold: 10 }, fields: [], presets: [] });
      return Promise.resolve({});
    },
  };
  const { Pet } = load({ sdk });
  stubMount(Pet);
  const el = host();
  Pet.mount(el);
  const containerEl = el.querySelector(".content");
  Pet.switchTab("cfg");
  await flush();                                   // form renders for alpha

  // Edit alpha (numeric -> no weaken-confirm gate) and click Apply -> PUT in flight.
  Pet.state.configDirty = { tier1_threshold: 99 };
  click(findButtonByText(containerEl, "Apply"));
  assert.ok(putResolve, "Apply issued a PUT (now in flight)");

  // Host sidebar flips to beta: rebind clears the (alpha) dirty map + re-renders.
  scope.profile = "beta";
  scope._fire();
  await flush();                                   // getConfig(beta) renders the new form
  assert.equal(Pet.state.selectedHermesProfile, "beta");

  // Operator starts editing beta.
  Pet.state.configDirty = { tier1_threshold: 55 };

  // The stale alpha PUT finally resolves — it must NOT clear beta's edits.
  putResolve({ config: { tier1_threshold: 10 }, applied: true });
  await flush();

  assert.equal(Object.keys(Pet.state.configDirty).length, 1, "beta's edits survived the stale PUT");
  assert.equal(Pet.state.configDirty.tier1_threshold, 55, "beta's exact edit is intact");
});

// ── 31. A /config resolving AFTER unmount cannot mutate state (CodeRabbit) ────
// Pet.unmount bumps _cfgRenderGen so an in-flight renderConfig continuation is
// superseded and cannot write Pet.state.config on a torn-down console.
test("#31 a /config resolving after unmount cannot clobber state", async () => {
  let cfgResolve = null;
  const sdk = {
    calls: [],
    fetchJSON(url, o) {
      this.calls.push({ url: String(url), opts: o });
      if (/\/profiles\/active/.test(url)) return Promise.resolve({ active: "", current: "" });
      if (/\/profiles(\?|$)/.test(url)) return Promise.resolve({ profiles: [] });
      if (/config/.test(url)) return new Promise((r) => { cfgResolve = r; });
      return Promise.resolve({});
    },
  };
  const { Pet } = load({ sdk, search: "?profile=alpha" });
  stubMount(Pet);
  Pet.mount(host());
  Pet.switchTab("cfg");                            // getConfig in flight (deferred)
  assert.ok(cfgResolve, "config fetch issued");

  Pet.state.config = { sentinel: true };
  Pet.unmount();                                   // bumps _cfgRenderGen -> supersede
  cfgResolve({ config: { sentinel: false, clobbered: true }, fields: [], presets: [] });
  await flush();

  assert.equal(Pet.state.config.sentinel, true, "state.config not overwritten after unmount");
  assert.ok(!Pet.state.config.clobbered, "the post-unmount resolve did not write");
});
