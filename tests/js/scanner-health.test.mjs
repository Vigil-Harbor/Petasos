// Unit tests for Pet.scannerHealthRows (petasos/console/static/petasos.js).
//
// Regression for PET-103:
//   1. A backend's `last_error` must render fully and selectably — wrapped
//      (`pre-wrap`), height-bounded with scroll — not clipped to a single-line
//      250px ellipsis reachable only via `title=`. The style contract is what
//      changed, so the primary assertions pin the style, not just text presence
//      (a text-presence-only check passes against the unfixed code).
//   2. The new `error` status (installed-but-load-crashed) must get an explicit
//      red pill, never the grey "unknown" `else`.
//   3. The Scanner Health help string (Pet.SCANNER_HEALTH_HELP) must define
//      `error` and the corrected `unavailable` wording.
//
// Zero npm dependencies: Node's built-in test runner + assert, an extended DOM
// shim, and node:vm to evaluate the real shipped petasos.js. Run with:
//   node --test tests/js/scanner-health.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

// ── Extended DOM shim (PET-103 D10) ────────────────────────────────────────
// Models the surface Pet.h touches that the richtext shim does not: `style`
// (required — Pet.h does `Object.assign(el.style, attrs.style)`, which throws on
// `undefined`), plus plain `className`/`title` slots. `textContent` keeps the
// aggregating GETTER (so `errEl.textContent === message` reads work) AND gains a
// throwing SETTER — so a regression to the old `errEl.textContent = ...` pattern
// fails loudly here instead of being a silent no-op. Both accessors are defined
// together (a `get`/`set` literal pair) so adding the setter does not drop the
// getter.
function makeNode(nodeType) {
  return {
    nodeType, // 1 = element, 3 = text, 11 = fragment
    childNodes: [],
    style: {},
    className: "",
    title: "",
    appendChild(child) {
      this.childNodes.push(child);
      return child;
    },
    get textContent() {
      if (this.nodeType === 3) return this.nodeValue;
      return this.childNodes.map((c) => c.textContent).join("");
    },
    set textContent(_v) {
      throw new Error(
        "PET-103 D10: textContent assignment is banned in this shim — pass the " +
          "message as a Pet.h text child, not `errEl.textContent = ...`."
      );
    },
  };
}

const document = {
  createDocumentFragment() {
    return makeNode(11);
  },
  createElement(tag) {
    const el = makeNode(1);
    el.tagName = tag.toUpperCase(); // mirrors real DOM (uppercase for HTML)
    el.localName = tag;
    return el;
  },
  createTextNode(t) {
    const node = makeNode(3);
    node.nodeValue = String(t);
    return node;
  },
};

// ── Load the real petasos.js under a sandbox ──────────────────────────────
const here = dirname(fileURLToPath(import.meta.url));
const petasosJsPath = join(here, "..", "..", "petasos", "console", "static", "petasos.js");
const src = readFileSync(petasosJsPath, "utf8");

const sandbox = { window: {}, document };
vm.runInNewContext(src, sandbox);
const Pet = sandbox.window.__PETASOS_CONSOLE__;

// ── Helpers ───────────────────────────────────────────────────────────────
// Depth-first search for the first element node matching `pred`.
function findEl(node, pred) {
  for (const child of node.childNodes || []) {
    if (child.nodeType === 1) {
      if (pred(child)) return child;
      const found = findEl(child, pred);
      if (found) return found;
    }
  }
  return null;
}

const isErrorBlock = (el) => el.style && el.style.whiteSpace === "pre-wrap";
// PET critique (P2): status chips moved off hardcoded inline colors onto the
// token-bound .pill variants (.pill ok | .pill warn | .pill err | bare .pill =
// neutral) so they follow the Hermes theme. Assert the variant class, not color.
const isPill = (el) => typeof el.className === "string" && /\bpill\b/.test(el.className);

function pillClass(status) {
  const tree = Pet.scannerHealthRows([{ name: "x", status, last_ms: null, last_error: null }]);
  const pill = findEl(tree, isPill);
  assert.ok(pill, `pill not found for status ${status}`);
  return pill.className;
}

// ── Tests ───────────────────────────────────────────────────────────────

// Guards that the export ran and the new surface is present.
test("loader: petasos.js exports scannerHealthRows + SCANNER_HEALTH_HELP", () => {
  assert.equal(typeof Pet, "object");
  assert.equal(typeof Pet.scannerHealthRows, "function");
  assert.equal(typeof Pet.SCANNER_HEALTH_HELP, "string");
});

// Guard-of-the-guard: the shim's throwing textContent setter is armed, so a
// revert to `errEl.textContent = ...` would fail loudly rather than silently.
test("shim: textContent setter throws (D10 tripwire is armed)", () => {
  const el = document.createElement("div");
  assert.throws(() => {
    el.textContent = "x";
  }, /PET-103 D10/);
});

// Primary fix: pins the style contract that changed (defect #1).
test("test_scanner_health_rows_render_full_error", () => {
  const msg =
    "weakref TypeError: cannot create weak reference to 'BoundMethodWeakref'\n" +
    "  File \"llm_guard/input_scanners/prompt_injection.py\", line 412, in _load\n" +
    "  File \"transformers/pipelines/__init__.py\", line 906, in pipeline\n" +
    "  ...a long multi-line backend error that previously clipped to ~250px...";
  const tree = Pet.scannerHealthRows([
    { name: "llm_guard", status: "error", last_ms: 12.3, last_error: msg },
  ]);
  const errEl = findEl(tree, isErrorBlock);
  assert.ok(errEl, "error element with whiteSpace:pre-wrap not found");

  // The style is what changed — text presence alone passes against the old code.
  assert.equal(errEl.style.whiteSpace, "pre-wrap");
  assert.notEqual(errEl.style.maxWidth, "250px");
  assert.ok(errEl.style.maxHeight, "expected a bounded maxHeight");
  assert.equal(errEl.style.overflowY, "auto");

  // Secondary: the full message is a real, selectable text node (not title-only).
  assert.equal(errEl.textContent, msg);
});

// Defect #2 (card): the new `error` status gets the red pill, not the grey else.
test("test_scanner_health_pill_color_for_error_status", () => {
  const cls = pillClass("error");
  // `error` shares the err (red) variant with unavailable/circuit_open, so this
  // witnesses "a failure pill, not the neutral else"; the status-value distinction
  // is caught Python-side.
  assert.match(cls, /\berr\b/);
  assert.doesNotMatch(cls, /\b(ok|warn)\b/);
});

// Defect #2 (card): help-text status definitions agree with the labels.
test("test_help_text_status_definitions_agree", () => {
  const help = Pet.SCANNER_HEALTH_HELP;
  assert.equal(typeof help, "string");
  // `error` is defined as installed-but-load-failed.
  assert.ok(help.includes("<code>error</code>"), "help omits an `error` definition");
  assert.ok(/installed but failed to load/.test(help), "`error` wording missing");
  // `unavailable` reads "not installed / prerequisites missing".
  assert.ok(help.includes("<code>unavailable</code>"), "help omits `unavailable`");
  assert.ok(
    /not installed/.test(help) && /prerequisites missing/.test(help),
    "`unavailable` wording missing"
  );
});

// Regression: the established statuses keep their pill colors.
test("existing statuses keep their established pill variants", () => {
  assert.match(pillClass("healthy"), /\bok\b/);
  assert.match(pillClass("degraded"), /\bwarn\b/);
  assert.match(pillClass("unavailable"), /\berr\b/);
  assert.match(pillClass("circuit_open"), /\berr\b/);
  // An unknown status falls through to the neutral pill (no ok/warn/err variant).
  const unknown = pillClass("totally_unknown");
  assert.match(unknown, /\bpill\b/);
  assert.doesNotMatch(unknown, /\b(ok|warn|err)\b/);
});
