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
import { createDOM, loadConsole } from "./harness.mjs";

// ── Extended DOM shim (PET-103 D10) ────────────────────────────────────────
// Models the surface Pet.h touches that the richtext shim does not: `style`
// (required — Pet.h does `Object.assign(el.style, attrs.style)`, which throws on
// `undefined`), plus plain `className`/`title` slots. `textContent` keeps the
// aggregating GETTER (so `errEl.textContent === message` reads work) AND gains a
// throwing SETTER — so a regression to the old `errEl.textContent = ...` pattern
// fails loudly here instead of being a silent no-op. The shared factory defines
// both accessors in one descriptor so the setter does not drop the getter.
const { makeDocument } = createDOM({
  title: true,
  textContent: "strict",
});

const document = makeDocument();

// ── Load the real petasos.js under a sandbox ──────────────────────────────

const sandbox = { window: {}, document };
loadConsole(sandbox);
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

// Regression for PET-264: a refused Semgrep startup status renders as its own row.

const LIFECYCLE =
  "Semgrep was turned on, but this console has no lifecycle owner, so it was not started. " +
  "Shown from the startup build; a config change applies at the next restart.";
const UNSUPPORTED =
  "Semgrep was turned on, but this platform cannot run it, so it was not started. " +
  "Shown from the startup build; a config change applies at the next restart.";
const CONSTRUCTION =
  "Semgrep was turned on, but it failed to start and was not registered. " +
  "Shown from the startup build; a config change applies at the next restart.";
const GENERIC =
  "This scanner was requested and is not registered. " +
  "Shown from the startup build; a config change applies at the next restart.";

function allEls(node, pred, out) {
  if (!out) out = [];
  for (const child of node.childNodes || []) {
    if (child.nodeType === 1) {
      if (pred(child)) out.push(child);
      allEls(child, pred, out);
    }
  }
  return out;
}

function minimalRow() {
  return { name: "minimal", status: "healthy", last_ms: 3.5, last_error: null };
}

function semgrepStatus(outcome, reason, extra = {}) {
  return {
    scanner_id: "semgrep",
    display_name: "Semgrep",
    outcome,
    reason,
    ...extra,
  };
}

function refusedBuild(statuses) {
  return { available: true, statuses };
}

test("adopted refused Semgrep row shows the lifecycle explanation and token", () => {
  const kept = [{ name: "kept" }];
  Pet.state.scannerHealth = kept;
  const health = {
    scanners: [minimalRow()],
    scanner_build: refusedBuild([
      semgrepStatus("failed", "semgrep.host_lifecycle_unavailable"),
    ]),
  };
  Pet.adoptScannerBuild(health);
  assert.equal(Pet.state.scannerBuild, health.scanner_build);
  assert.equal(Pet.state.scannerHealth, kept);

  const tree = Pet.scannerHealthRows(health.scanners, Pet.state.scannerBuild);
  const text = tree.textContent;
  assert.ok(text.includes("Semgrep"));
  assert.ok(text.includes(LIFECYCLE));
  assert.ok(text.includes("semgrep.host_lifecycle_unavailable"));
  assert.ok(text.includes("3.5ms"));
  assert.ok(text.includes("\u2014"));

  const failed = allEls(tree, isPill).find((el) => el.textContent === "failed");
  assert.ok(failed, "failed pill not found");
  assert.match(failed.className, /\berr\b/);

  const blocks = allEls(tree, isErrorBlock);
  assert.deepEqual(
    blocks.map((el) => el.textContent),
    [LIFECYCLE, "semgrep.host_lifecycle_unavailable"],
  );
  assert.match(Pet.SCANNER_HEALTH_HELP, /<code>failed<\/code> or <code>missing<\/code>/);
  assert.ok(Pet.SCANNER_HEALTH_HELP.includes("startup-build outcome"));
  assert.ok(!Pet.SCANNER_HEALTH_HELP.includes("\u2014"));
});

test("startup rows follow the record rules and skip bad entries", () => {
  const scanners = [minimalRow()];

  Pet.adoptScannerBuild({
    scanners,
    scanner_build: { available: false, statuses: null },
  });
  assert.equal(Pet.state.scannerBuild, null);
  let tree = Pet.scannerHealthRows(scanners, Pet.state.scannerBuild);
  assert.ok(!tree.textContent.includes(LIFECYCLE));
  assert.ok(!tree.textContent.includes(GENERIC));

  Pet.adoptScannerBuild({ scanners });
  assert.equal(Pet.state.scannerBuild, null);
  tree = Pet.scannerHealthRows(scanners, Pet.state.scannerBuild);
  assert.ok(!tree.textContent.includes(LIFECYCLE));

  assert.doesNotThrow(() => Pet.adoptScannerBuild(null));
  assert.equal(Pet.state.scannerBuild, null);
  assert.doesNotThrow(() => Pet.adoptScannerBuild(undefined));
  Pet.adoptScannerBuild({ scanner_build: { available: true, statuses: "nope" } });
  assert.equal(Pet.state.scannerBuild, null);

  tree = Pet.scannerHealthRows(
    scanners,
    refusedBuild([semgrepStatus("disabled", "disabled by config")]),
  );
  assert.ok(!tree.textContent.includes(LIFECYCLE));
  assert.ok(!tree.textContent.includes("disabled by config"));
  assert.ok(!tree.textContent.includes(GENERIC));

  const registered = [
    minimalRow(),
    { name: "semgrep", status: "error", last_ms: null, last_error: "probe blew up" },
  ];
  tree = Pet.scannerHealthRows(
    registered,
    refusedBuild([semgrepStatus("failed", "semgrep.host_lifecycle_unavailable")]),
  );
  assert.ok(!tree.textContent.includes(LIFECYCLE));
  assert.ok(!tree.textContent.includes("semgrep.host_lifecycle_unavailable"));
  assert.ok(tree.textContent.includes("probe blew up"));

  tree = Pet.scannerHealthRows(
    scanners,
    refusedBuild([semgrepStatus("failed", "semgrep.unsupported_platform")]),
  );
  assert.ok(tree.textContent.includes(UNSUPPORTED));
  assert.ok(tree.textContent.includes("semgrep.unsupported_platform"));

  tree = Pet.scannerHealthRows(
    scanners,
    refusedBuild([semgrepStatus("failed", "semgrep.construction_failed")]),
  );
  assert.ok(tree.textContent.includes(CONSTRUCTION));
  assert.ok(tree.textContent.includes("semgrep.construction_failed"));

  tree = Pet.scannerHealthRows(
    scanners,
    refusedBuild([
      {
        scanner_id: "presidio",
        display_name: "Presidio",
        outcome: "missing",
        reason: "No module named presidio",
      },
    ]),
  );
  assert.ok(tree.textContent.includes("Presidio"));
  assert.ok(tree.textContent.includes(GENERIC));
  assert.ok(tree.textContent.includes("No module named presidio"));
  const missing = allEls(tree, isPill).find((el) => el.textContent === "missing");
  assert.ok(missing, "missing pill not found");
  assert.match(missing.className, /\berr\b/);

  tree = Pet.scannerHealthRows(
    scanners,
    refusedBuild([
      semgrepStatus("verified", null),
      semgrepStatus("degraded", "no model"),
    ]),
  );
  assert.ok(!tree.textContent.includes(GENERIC));
  assert.ok(!tree.textContent.includes("no model"));

  tree = Pet.scannerHealthRows(
    scanners,
    refusedBuild([
      { scanner_id: "extra", display_name: "", outcome: "failed", reason: "" },
    ]),
  );
  assert.ok(tree.textContent.includes("extra"));
  assert.deepEqual(
    allEls(tree, isErrorBlock).map((el) => el.textContent),
    [GENERIC],
  );

  const empty = Pet.scannerHealthRows(
    [],
    refusedBuild([semgrepStatus("failed", "semgrep.host_lifecycle_unavailable")]),
  );
  assert.equal(empty.textContent, "scanner status unavailable: health fetch failed");
  assert.ok(!empty.textContent.includes(LIFECYCLE));

  assert.doesNotThrow(() => {
    Pet.scannerHealthRows(scanners, refusedBuild([
      null,
      "bad",
      1,
      { outcome: "failed" },
      { outcome: "failed", scanner_id: 3 },
      semgrepStatus("failed", "semgrep.host_lifecycle_unavailable"),
    ]));
  });
  tree = Pet.scannerHealthRows(scanners, refusedBuild([
    null,
    semgrepStatus("failed", "semgrep.host_lifecycle_unavailable"),
  ]));
  assert.ok(tree.textContent.includes(LIFECYCLE));
});
