// Unit tests for the PET-13 overdrive "escalation trap" stress test in
// petasos/console/static/petasos.js (Pet.buildTrapViz / Pet.runTrapBurst).
//
// Headline regression: the scan response nests its fields under `.result`
// (mirrors Pet.renderScanResult's `var r = d && d.result`). An earlier build read
// session_score / escalation_tier / safe at the TOP level, so every shot came back
// score=0 / tier=none and the trap never sprang. The "reads .result" test below
// pins that: a `.result`-shaped stub MUST escalate and spring; a flat (top-level)
// stub MUST NOT, proving the code reads the nested shape.
//
// Zero npm dependencies: Node's built-in test runner + assert, a DOM shim
// (extends the playground shim with insertBefore/firstChild for the shot stream),
// node:vm to evaluate the real shipped petasos.js, and a sandbox setTimeout so the
// inter-shot delay resolves. Run with:
//   node --test tests/js/trap-burst.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

// ── DOM shim (extends playground.test.mjs's with insertBefore + firstChild) ──
function makeNode(nodeType) {
  return {
    nodeType,
    childNodes: [],
    style: {},
    className: "",
    title: "",
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
    setAttribute(_k, _v) {},
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

const document = {
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

// ── Load the real petasos.js under a sandbox ──────────────────────────────
const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(
  join(here, "..", "..", "petasos", "console", "static", "petasos.js"),
  "utf8"
);
// setTimeout: run the callback immediately so the inter-shot delay resolves
// without real wall-clock time (the burst still serializes via promise ticks).
const sandbox = { window: {}, document, setTimeout: (fn) => fn() };
vm.runInNewContext(src, sandbox);
const Pet = sandbox.window.__PETASOS_CONSOLE__;

// ── Helpers ───────────────────────────────────────────────────────────────
function findEl(node, pred) {
  for (const c of node.childNodes || []) {
    if (c.nodeType === 1) {
      if (pred(c)) return c;
      const f = findEl(c, pred);
      if (f) return f;
    }
  }
  return null;
}
function findAll(node, pred, acc = []) {
  for (const c of node.childNodes || []) {
    if (c.nodeType === 1) {
      if (pred(c)) acc.push(c);
      findAll(c, pred, acc);
    }
  }
  return acc;
}
const isErrorBlock = (el) => el.style && el.style.whiteSpace === "pre-wrap";
const vizRoot = (resultArea) => resultArea.childNodes[0];
const streamOf = (root) => findEl(root, (el) => el.className === "trap-stream");
const isSprung = (root) => /\bsprung\b/.test(root.className);
const hasLockdown = (root) => !!findEl(root, (el) => el.className === "trap-lockdown");
const rungs = (root) =>
  findAll(root, (el) => el.className && el.className.split(" ")[0] === "trap-rung");

// A /scan stub whose fields are correctly nested under `.result`.
function resultApi(seq) {
  let i = 0;
  return {
    postScan() {
      const s = seq[Math.min(i, seq.length - 1)];
      i++;
      return Promise.resolve({
        result: { safe: false, findings: [], session_score: s.score, escalation_tier: s.tier },
      });
    },
  };
}
// Same data but at the TOP level (no `.result`) — the pre-fix wrong shape.
function flatApi(seq) {
  let i = 0;
  return {
    postScan() {
      const s = seq[Math.min(i, seq.length - 1)];
      i++;
      return Promise.resolve({ safe: false, session_score: s.score, escalation_tier: s.tier });
    },
  };
}

const CLIMB = [
  { score: 10, tier: "none" },
  { score: 20, tier: "tier1" },
  { score: 40, tier: "tier2" },
  { score: 60, tier: "tier3" },
];

// ── Tests ───────────────────────────────────────────────────────────────

test("loader: exports the trap engine + data", () => {
  for (const fn of ["buildTrapViz", "runTrapBurst"]) {
    assert.equal(typeof Pet[fn], "function", `Pet.${fn} missing`);
  }
  assert.ok(Pet.TRAP_PAYLOADS.length > 0);
  // .join, not deepEqual: TRAP_TIERS is a vm-realm array and cross-realm
  // deepStrictEqual fails the Array-prototype check even with identical contents.
  assert.equal(Pet.TRAP_TIERS.map((t) => t.key).join(","), "tier3,tier2,tier1");
});

test("buildTrapViz: root element + setTier marks passed/active/idle rungs", () => {
  const viz = Pet.buildTrapViz();
  assert.equal(viz.root.nodeType, 1);
  for (const m of ["setScore", "setTier", "setPhase", "pushShot", "lockdown", "exhausted", "error"]) {
    assert.equal(typeof viz[m], "function", `viz.${m} missing`);
  }
  viz.setTier("tier2");
  const classes = rungs(viz.root).map((r) => r.className);
  assert.equal(classes.length, 3);
  assert.ok(classes.includes("trap-rung active"), "current tier (tier2) should be active");
  assert.ok(classes.includes("trap-rung passed"), "lower tier (tier1) should be passed");
  assert.ok(classes.includes("trap-rung"), "higher tier (tier3) should stay idle");
});

test("runTrapBurst: reads .result, climbs to tier3, springs the trap, stops early", async () => {
  const resultArea = document.createElement("div");
  const trapBtn = document.createElement("button");
  await Pet.runTrapBurst({ resultArea, trapBtn, api: resultApi(CLIMB), maxShots: 15 });

  const root = vizRoot(resultArea);
  assert.ok(isSprung(root), "viz should be in the sprung state");
  assert.ok(hasLockdown(root), "lockdown banner should be rendered");
  // tier3 is reached on shot 4 (CLIMB[3]); the burst must stop there, not run all 15.
  assert.equal(streamOf(root).childNodes.length, 4, "should stop at the tier3 shot");
  assert.equal(trapBtn.disabled, false, "button must be re-enabled when the burst settles");
});

test("runTrapBurst: a flat (top-level) response never escalates — pins the .result read", async () => {
  const resultArea = document.createElement("div");
  const trapBtn = document.createElement("button");
  // Same escalating data, but at the TOP level. If the code read top-level it would
  // spring; reading `.result` (correct) yields none/0 every shot -> exhausts.
  await Pet.runTrapBurst({ resultArea, trapBtn, api: flatApi(CLIMB), maxShots: 4 });

  const root = vizRoot(resultArea);
  assert.ok(!isSprung(root), "flat response must NOT spring the trap");
  assert.ok(!hasLockdown(root), "flat response must NOT render lockdown");
  assert.equal(streamOf(root).childNodes.length, 4, "should fire the full cap");
  assert.equal(trapBtn.disabled, false);
});

test("runTrapBurst: held below tier3 fires the cap, no throw, button restored", async () => {
  const resultArea = document.createElement("div");
  const trapBtn = document.createElement("button");
  await Pet.runTrapBurst({
    resultArea,
    trapBtn,
    api: resultApi([{ score: 12, tier: "tier1" }]), // stuck at tier1
    maxShots: 5,
  });
  const root = vizRoot(resultArea);
  assert.ok(!isSprung(root));
  assert.equal(streamOf(root).childNodes.length, 5, "fires the full cap when tier3 never hit");
  assert.ok(
    findEl(root, (el) => el.className && el.className.split(" ")[0] === "trap-note"),
    "exhausted note should render"
  );
  assert.equal(trapBtn.disabled, false);
});

test("runTrapBurst: a rejection and an {error} envelope both surface an error + restore", async () => {
  // (a) rejected promise
  let resultArea = document.createElement("div");
  let trapBtn = document.createElement("button");
  await assert.doesNotReject(
    Pet.runTrapBurst({
      resultArea,
      trapBtn,
      api: { postScan: () => Promise.reject(new Error("net down")) },
    })
  );
  assert.ok(findEl(vizRoot(resultArea), isErrorBlock), "rejection should render an error block");
  assert.equal(trapBtn.disabled, false, "button restored after rejection");

  // (b) resolved {error} envelope
  resultArea = document.createElement("div");
  trapBtn = document.createElement("button");
  await Pet.runTrapBurst({
    resultArea,
    trapBtn,
    api: { postScan: () => Promise.resolve({ error: "boom from server" }) },
  });
  assert.ok(findEl(vizRoot(resultArea), isErrorBlock), "error envelope should render an error block");
  assert.equal(trapBtn.disabled, false, "button restored after error envelope");
});
