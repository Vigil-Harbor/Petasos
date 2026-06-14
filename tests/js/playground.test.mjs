// Unit tests for the Scan Playground builders in petasos/console/static/petasos.js.
//
// Regression for PET-99:
//   D2  result region scrolls (overflowY:auto + minHeight:0) — never clip-to-hidden.
//   D3  error/detail text is fully legible: pre-wrap + overflow-wrap + bounded
//       scroll, and the full message is a real selectable text node.
//   D4  long matched_text is not lost — present in the DOM + on `title`.
//   D5  a failed scan restores the Scan button and shows a readable error on
//       BOTH the {error|detail} branch and a rejected promise — never stranded
//       on "Scanning...".
//   D6  a playground scan must not corrupt the Observability tab: the
//       render-consumed scan-history path (Pet.scanHistoryRows) and the
//       seed-merge path (Pet.mergeScanHistory) skip malformed entries instead
//       of throwing on the next render — the concrete cross-tab crash found in
//       spec review (an unguarded `.scan_id` deref) is pinned here.
//
// Zero npm dependencies: Node's built-in test runner + assert, an extended DOM
// shim (a superset of scanner-health.test.mjs's), and node:vm to evaluate the
// real shipped petasos.js. Run with:
//   node --test tests/js/playground.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

// ── Extended DOM shim (PET-99) ──────────────────────────────────────────────
// Superset of the scanner-health shim. Differences (see spec Test plan):
//   * textContent SETTER is real-DOM-faithful (clears childNodes, appends one
//     text node for a non-empty value) — NOT the scanner-health throwing setter,
//     because the playground legitimately assigns `scanBtn.textContent =
//     "Scanning..."`. The aggregating getter is kept so text appended via Pet.h
//     children reads back.
//   * innerHTML setter clears childNodes (the `resultArea.innerHTML = ""` clear
//     idiom — real-DOM semantics, so children don't accumulate across calls).
//   * no-op addEventListener / setAttribute (Pet.HelpTip / Pet.svg touch them).
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
    addEventListener(_type, _fn) {},
    setAttribute(_k, _v) {},
    get textContent() {
      if (this.nodeType === 3) return this.nodeValue;
      return this.childNodes.map((c) => c.textContent).join("");
    },
    set textContent(v) {
      // Real-DOM semantics: clear children; for a non-empty value, append one
      // text node. (Empty string clears to no children.)
      this.childNodes = [];
      const s = v == null ? "" : String(v);
      if (s !== "") {
        const n = makeNode(3);
        n.nodeValue = s;
        this.childNodes.push(n);
      }
    },
    set innerHTML(_v) {
      // Only `... = ""` is used in production; model the clear, ignore the value.
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
    el.tagName = tag.toUpperCase(); // mirrors real DOM (uppercase for HTML)
    el.localName = tag;
    return el;
  },
  createElementNS(_ns, tag) {
    return this.createElement(tag); // Pet.svg path
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

// ── Tests ───────────────────────────────────────────────────────────────

// Guards that the export ran and the extracted seam is present.
test("loader: petasos.js exports the playground builders + mergeScanHistory", () => {
  assert.equal(typeof Pet, "object");
  for (const fn of [
    "makeResultArea",
    "scanErrorBlock",
    "restoreScanButton",
    "renderScanResult",
    "runPlaygroundScan",
    "mergeScanHistory",
  ]) {
    assert.equal(typeof Pet[fn], "function", `Pet.${fn} missing`);
  }
});

// D2 — the result region scrolls within its flex bound; it does not clip.
test("test_result_area_scrolls_not_clips", () => {
  const ra = Pet.makeResultArea();
  assert.equal(ra.style.overflowY, "auto");
  assert.equal(ra.style.minHeight, "0");
  assert.equal(ra.style.flex, "1"); // the definite-height chain depends on this
});

// D3 — a multi-kilobyte, multi-line error is rendered in full as a real text
// node with the legibility style contract. The fixture is compared by variable
// (never a re-typed literal) to dodge CRLF/control-char round-trip false-fails.
test("test_long_error_fully_rendered", () => {
  const fixture =
    "SCAN FAILED\n\t" +
    "x".repeat(5000) +
    "\nNESTED\tTAB line\n" +
    "y".repeat(3000) +
    "\n— end —";
  const el = Pet.scanErrorBlock(fixture);
  assert.equal(el.textContent, fixture); // full, selectable, byte-for-byte
  assert.equal(el.style.whiteSpace, "pre-wrap");
  assert.equal(el.style.overflowWrap, "anywhere");
  assert.ok(el.style.maxHeight, "expected a bounded maxHeight");
  assert.equal(el.style.overflowY, "auto");
});

// D4 — a long matched_text survives into the DOM and onto `title`; it is never
// dropped. (CSS wrap is not measurable in the shim; the JS guard is presence.)
test("test_long_matched_text_not_lost", () => {
  const big = "M".repeat(4000) + "—" + "atched".repeat(50);
  const d = {
    result: {
      safe: false,
      findings: [
        {
          rule_id: "PROMPT_INJECTION",
          severity: "high",
          scanner_name: "minimal",
          message: "possible instruction override",
          matched_text: big,
        },
      ],
    },
  };
  const tree = Pet.renderScanResult(d, "x");
  assert.ok(tree.textContent.includes(big), "matched_text absent from rendered DOM");
  const matched = findEl(tree, (el) => el.className === "matched");
  assert.ok(matched, ".matched span not found");
  assert.equal(matched.title, big, ".matched title not set to full matched_text");
});

// D5 — both failure shapes restore the button and render a scanErrorBlock; the
// UI is never stranded on "Scanning...". Same nodes across both calls (the
// innerHTML="" clear means no special handling is needed).
test("test_failed_scan_restores_button", async () => {
  const scanBtn = document.createElement("button");
  const resultArea = document.createElement("div");

  // (a) rejected promise → the .catch arm
  await Pet.runPlaygroundScan({
    text: "hi",
    dir: "inbound",
    sid: null,
    scanBtn,
    resultArea,
    api: { postScan: () => Promise.reject(new Error("network down")) },
  });
  assert.equal(scanBtn.textContent, " Scan", "button not restored after rejection");
  let err = findEl(resultArea, isErrorBlock);
  assert.ok(err, "no scanErrorBlock rendered for rejection");
  assert.ok(err.textContent.includes("network down"), "rejection message not shown");

  // (b) resolved {error: ...} envelope → the .then {error|detail} branch
  await Pet.runPlaygroundScan({
    text: "hi",
    dir: "inbound",
    sid: null,
    scanBtn,
    resultArea,
    api: { postScan: () => Promise.resolve({ error: "boom from server" }) },
  });
  assert.equal(scanBtn.textContent, " Scan", "button not restored after error envelope");
  err = findEl(resultArea, isErrorBlock);
  assert.ok(err, "no scanErrorBlock rendered for error envelope");
  assert.ok(err.textContent.includes("boom from server"), "error envelope text not shown");
});

// D6 (render side) — the obs-render path a tab-switch triggers must not throw on
// a poisoned scan-history buffer. Pet.scanHistoryRows already guards non-objects;
// this pins that it stays guarded.
test("test_scan_then_switch_tab_no_throw", () => {
  const hist = [
    null,
    5,
    {},
    { safe: false, duration_ms: "x" }, // present-but-non-numeric latency
    {
      scan_id: "a",
      safe: true,
      finding_count: 2,
      duration_ms: 1.5,
      direction: "inbound",
      timestamp: 0,
    },
  ];
  assert.doesNotThrow(() => Pet.scanHistoryRows(hist));
});

// D6 (seed-merge side) — the real, non-tautological guard. The pre-fix inline
// loops dereferenced `.scan_id` on every buffer + fetched entry; a malformed
// entry threw on the next render. mergeScanHistory must skip non-objects on both
// sides AND preserve the prior dedup/append behavior exactly.
test("test_seed_merge_skips_malformed", () => {
  // Buffer already holds malformed entries (null, 5) + one real scan; the fetched
  // set repeats null/7, a bare {}, the already-seen "a", and a fresh "b".
  const buffer = [null, 5, { scan_id: "a" }];
  const result = Pet.mergeScanHistory(buffer, [
    null,
    7,
    {},
    { scan_id: "a" },
    { scan_id: "b" },
  ]);

  assert.equal(result, buffer, "should mutate + return the same buffer by reference");
  // null/5 stay physically in the buffer (skipped only during seen-building);
  // {} (scan_id undefined, unseen) and {scan_id:"b"} append; {scan_id:"a"} dedups.
  assert.equal(result.length, 5);
  const ids = result
    .filter((e) => e && typeof e === "object")
    .map((e) => e.scan_id);
  assert.deepEqual(ids, ["a", undefined, "b"]); // a (kept), {} survives, b appended
  assert.equal(ids.filter((x) => x === "a").length, 1, "scan_id 'a' not deduped");

  // Two scan_id-less objects: the first adds `undefined` to seen, deduping the
  // second — exactly one {} survives (pins the existing-buffer + fetched derefs).
  const r2 = Pet.mergeScanHistory([], [{}, {}]);
  assert.equal(r2.length, 1);
});

// Defensiveness (correctness/edge-cases F-10) — a malformed /scan body returns a
// readable scanErrorBlock instead of throwing into runPlaygroundScan's .catch.
test("test_render_scan_result_malformed", () => {
  for (const bad of [{}, { result: {} }]) {
    let node;
    assert.doesNotThrow(() => {
      node = Pet.renderScanResult(bad, "x");
    });
    assert.ok(isErrorBlock(node), "expected a scanErrorBlock for malformed shape");
    assert.ok(
      node.textContent.includes("Unexpected response shape"),
      "expected the shape-error message"
    );
  }
});
