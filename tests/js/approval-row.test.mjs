// Unit tests for approval-row rendering (petasos-observability.js), PET-222.
//
// An approval observation is an enforcement scan-row whose badge is the
// operator choice (or "pending"), never the green "safe" pill. The detail
// panel classifies the row and says no content scan ran.
//
// Zero npm deps: Node's built-in test runner + a DOM shim + node:vm over the
// real shipped script. Run with: node --test tests/js/approval-row.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";
import { createDOM, loadConsole } from "./harness.mjs";

const { makeDocument } = createDOM({
  title: true, dataset: true,
  attributes: "noop", events: "noop",
  textContent: "stored",
});

const document = makeDocument();
const sandbox = { window: {}, document };
loadConsole(sandbox);
const Pet = sandbox.window.__PETASOS_CONSOLE__;

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
const hasClass = (cls) => (el) => typeof el.className === "string" && el.className.split(/\s+/).includes(cls);
function text(tree) {
  return tree.textContent;
}

const RULE = "plugin_rule:destructive-recursive";

function approvalRow(overrides) {
  return {
    source: "enforcement",
    safe: true,
    finding_count: 0,
    event_type: "approval",
    phase: "response",
    choice: "deny",
    tool: "terminal",
    rule_id: RULE,
    surface: "cli",
    session_id: "sess-id",
    session_key: "sess-key",
    command: "<terminal> (plugin approval rule)",
    description: "run a command",
    decided_by: "operator",
    coalesced: false,
    tool_call_id: "tc-1",
    armed: true,
    duration_ms: 0,
    timestamp: 1700000000,
    scan_id: "e-ap1",
    ...overrides,
  };
}

function badgeOf(row) {
  const tree = Pet.scanHistoryRows([row]);
  const wanted = (typeof row.choice === "string" && row.choice !== "") ? row.choice : "pending";
  return findEl(tree, (el) => hasClass("pill")(el) && el.textContent === wanted);
}

test("deny response: badge is deny, not safe, and the row is a scan-row", () => {
  const row = approvalRow({ choice: "deny" });
  const tree = Pet.scanHistoryRows([row]);
  assert.equal(
    findEl(tree, (el) => hasClass("ok")(el) && el.textContent === "safe"),
    null,
    "approval row must not wear the green safe badge"
  );
  const badge = badgeOf(row);
  assert.ok(badge, "deny badge present");
  assert.equal(badge.textContent, "deny");
  assert.ok(hasClass("err")(badge), "deny uses the err class");
  assert.ok(findEl(tree, (el) => hasClass("scan-row")(el)), "enforcement scan-row");
  const panel = Pet.scanDetailPanel(row);
  const detail = text(panel);
  assert.ok(detail.includes("deny"), "detail contains the choice");
  assert.ok(detail.includes(RULE), "detail contains the rule");
  assert.ok(!detail.includes("Unknown row kind"), "detail classifies the row");
});

test("request with null choice shows pending", () => {
  const badge = badgeOf(approvalRow({ phase: "request", choice: null, scan_id: "e-ap2" }));
  assert.ok(badge, "pending badge present");
  assert.equal(badge.textContent, "pending");
  assert.ok(hasClass("warn")(badge), "pending uses the warn class");
});

test("response with empty choice shows pending", () => {
  const badge = badgeOf(approvalRow({ choice: "", scan_id: "e-ap3" }));
  assert.ok(badge, "pending badge present");
  assert.equal(badge.textContent, "pending");
  assert.ok(hasClass("warn")(badge));
});

test("detail provenance names the approval observation", () => {
  const detail = text(Pet.scanDetailPanel(approvalRow({ choice: "deny" })));
  assert.ok(detail.includes("n/a (Hermes approval observation, not a content scan)"));
});

test("timeout uses warn and once uses ok", () => {
  const timeout = badgeOf(approvalRow({ choice: "timeout", scan_id: "e-ap4" }));
  assert.equal(timeout.textContent, "timeout");
  assert.ok(hasClass("warn")(timeout), "timeout uses the warn class");
  const once = badgeOf(approvalRow({ choice: "once", scan_id: "e-ap5" }));
  assert.equal(once.textContent, "once");
  assert.ok(hasClass("ok")(once), "once uses the ok class");
});
