// PET-223: refused-approvals view, fetch cadence, and history arm.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createDOM, loadConsole } from "./harness.mjs";

const { makeDocument, makeNode } = createDOM({
  attributes: "raw",
  events: "record",
  selectors: "empty",
  localName: false,
  innerHTML: true,
  dataset: true,
  svg: "alias",
  textContent: "stored",
  tree: { remove: true, first: true, parents: true },
  // HTMLSelectElement: .value sticks only when a matching option already exists.
  // Otherwise the control displays the first option. This is what makes a
  // too-early assignment in paintRefusedQueue fail the repaint test.
  extendNode(node) {
    let selected;
    let plain;
    const options = () => (node.childNodes || []).filter((child) => child.tagName === "OPTION");
    const optionValue = (opt) => (opt.value == null ? "" : String(opt.value));
    Object.defineProperty(node, "value", {
      configurable: true,
      enumerable: true,
      get() {
        if (this.tagName !== "SELECT") return plain;
        const opts = options();
        if (selected != null && opts.some((opt) => optionValue(opt) === selected)) return selected;
        return opts.length ? optionValue(opts[0]) : "";
      },
      set(v) {
        if (this.tagName !== "SELECT") {
          plain = v;
          return;
        }
        const requested = v == null ? "" : String(v);
        selected = options().some((opt) => optionValue(opt) === requested) ? requested : null;
      },
    });
  },
});
const document = makeDocument();
const calls = [];
const sandbox = {
  window: {},
  document,
  console,
  setTimeout,
  clearTimeout,
  setInterval,
  clearInterval,
  AbortController,
  TextDecoder,
  fetch: (url, opts) => {
    calls.push({ url, opts });
    return Promise.resolve({
      ok: true,
      json: async () => ({ items: [] }),
    });
  },
};
loadConsole(sandbox);
const Pet = sandbox.window.__PETASOS_CONSOLE__;
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

function textOf(node) {
  if (!node) return "";
  if (node.nodeType === 3) return node.nodeValue || "";
  return (node.childNodes || []).map(textOf).join("");
}

test("refused queue carries credential handling notices", () => {
  const rows = Pet.refusedApprovalRows([
    item({ credential_redaction: "redacted" }),
    item({ item_id: "e-2", credential_redaction: "withheld" }),
    item({ item_id: "e-3", credential_redaction: "<script>unsafe</script>" }),
  ], null, false);
  assert.match(textOf(rows[0]), /masked locally; exposure unconfirmed/);
  assert.match(textOf(rows[1]), /redaction unavailable/);
  assert.ok(!textOf(rows[2]).includes("<script>"));
});

function item(extra) {
  return Object.assign({
    item_id: "e-1",
    choice: "deny",
    at: 1_700_000_000,
    origin: "petasos",
    tool: "terminal",
    pattern_key: "plugin_rule:petasos.x",
    petasos_rule: "petasos.x",
    command: "<terminal> (plugin approval rule)",
    description: 'command="rm -rf build"',
    provenance: "genuine",
    reviewed: false,
    coalesced: false,
  }, extra);
}

test("refusedQueueView filters, bands, notes, and bad bodies", () => {
  const unverifiable = [];
  for (let i = 0; i < 999; i++) {
    unverifiable.push(item({
      item_id: `e-u${i}`,
      provenance: "unverifiable",
      at: 9_000_000_000 + i,
      origin: "hermes",
    }));
  }
  const body = {
    items: [item({ item_id: "e-real", at: 10 }), ...unverifiable],
    total: 1000,
    pending: 2,
    unknown: 3,
    approval_rows: 4,
    window_oldest: 1_700_000_000,
    truncated: true,
    unverifiable_count: 999,
    reviewed_integrity: "unverifiable",
    review_write: { available: false, reason: "no_console_token" },
  };
  const view = Pet.refusedQueueView(body, { choice: "all", origin: "all", includeReviewed: false });
  assert.equal(view.rows[0].item_id, "e-real");
  assert.equal(view.unverifiableRows.length, 999);
  assert.equal(view.unverifiableLabel, "failed verification (999)");
  assert.equal(view.unverifiableCollapsed, true);
  assert.equal(Pet.refusedQueueView(body, { showUnverifiable: true }).unverifiableCollapsed, false);
  assert.match(view.summary, /1000 refused/);
  assert.match(view.summary, /2 pending/);
  assert.match(view.summary, /3 unknown/);
  assert.match(view.summary, /since /);
  assert.match(view.note, /list may be incomplete/);
  assert.match(view.note, /reviewed marks failed verification/);
  assert.match(view.note, /Set PETASOS_CONSOLE_TOKEN/);
  assert.equal(view.canMark, false);

  const plugin = Pet.refusedQueueView({
    items: [item({ origin: "plugin", item_id: "e-p" }), item({ origin: "hermes", item_id: "e-h" })],
    total: 2, pending: 0, unknown: 0, approval_rows: 2, unverifiable_count: 0,
    review_write: { available: true, reason: null },
  }, { origin: "plugin" });
  assert.equal(plugin.rows.map((row) => row.item_id).join(","), "e-p");

  const reviewed = Pet.refusedQueueView({
    items: [item({ reviewed: true, item_id: "e-r" }), item({ item_id: "e-open" })],
    total: 2, pending: 0, unknown: 0, approval_rows: 2, unverifiable_count: 0,
    review_write: { available: true, reason: null },
  }, { includeReviewed: false });
  assert.equal(reviewed.rows.map((row) => row.item_id).join(","), "e-open");

  const none = Pet.refusedQueueView({
    items: [], total: 0, pending: 0, unknown: 0, approval_rows: 0, unverifiable_count: 0,
    review_write: { available: false, reason: "not_equipped" },
  }, {});
  assert.equal(none.summary, "no approval events recorded in this window");
  assert.match(none.note, /Select the equipped profile/);

  const io = Pet.refusedQueueView({
    items: [], approval_rows: 1, total: 0, pending: 0, unknown: 0, unverifiable_count: 0,
    reviewed_integrity: "io_error",
    review_write: { available: false, reason: "no_state_dir" },
  }, {});
  assert.match(io.note, /could not be read/);
  assert.match(io.note, /no state directory/);
  const foreign = Pet.refusedQueueView({
    items: [], approval_rows: 1, total: 0, pending: 0, unknown: 0, unverifiable_count: 0,
    reviewed_integrity: "foreign",
    review_write: { available: true, reason: null },
  }, {});
  assert.match(foreign.note, /another profile/);

  for (const bad of [null, { detail: [{ field: "profile", message: "no" }], _status: 422 }, { error: "nope" }]) {
    const failed = Pet.refusedQueueView(bad, {});
    assert.equal(typeof failed.note, "string");
    assert.ok(failed.note.length > 0);
    assert.equal(Object.keys(failed).sort().join(","), Object.keys(view).sort().join(","));
  }
});

test("refusedApprovalRows and approvalBadge", () => {
  const badge = Pet.approvalBadge("timeout");
  assert.equal(badge.text, "timeout");
  assert.equal(badge.cls, "warn");
  assert.equal(Pet.approvalBadge("deny").cls, "err");
  let marked = null;
  const rows = Pet.refusedApprovalRows(
    [item({}), item({ item_id: "e-done", reviewed: true })],
    (id) => { marked = id; },
    true,
  );
  assert.equal(rows.length, 2);
  assert.match(textOf(rows[0]), /command="rm -rf build"/);
  assert.match(textOf(rows[0]), /2023-11-14 22:13:20Z/);
  assert.match(textOf(rows[0]), /Mark reviewed/);
  assert.doesNotMatch(textOf(rows[1]), /Mark reviewed/);
  const button = rows[0].childNodes.find((node) => node.tagName === "BUTTON");
  button.handlers.click[0]();
  assert.equal(marked, "e-1");
  const hermes = Pet.refusedApprovalRows([
    item({
      origin: "hermes",
      command: "rm -rf /tmp/x",
      description: "pattern description",
      petasos_rule: null,
      pattern_key: "destructive",
    }),
  ], null, false);
  assert.match(textOf(hermes[0]), /rm -rf \/tmp\/x/);
  assert.match(textOf(hermes[0]), /pattern description/);
  assert.doesNotMatch(textOf(hermes[0]), /Mark reviewed/);
  const weird = Pet.refusedApprovalRows([
    { item_id: "e-w", choice: "deny", tool: { nope: true }, description: true, command: [{}], origin: "hermes" },
  ], () => {}, true);
  assert.equal(weird.length, 1);
  const history = Pet.scanHistoryRows([
    { source: "enforcement", event_type: "approval", choice: "timeout", scan_id: "e-t", safe: true },
    { source: "enforcement", event_type: "approval", choice: "deny", scan_id: "e-d", safe: true },
  ]);
  assert.match(textOf(history), /timeout/);
  assert.match(textOf(history), /deny/);
});

test("panel filters reveal reviewed rows and the failed-verification group", () => {
  const node = makeNode("div");
  Pet._runtime.refusedBody = node;
  Pet.state.refusedQueue = {
    body: {
      items: [
        item({ item_id: "e-open", description: "open-row" }),
        item({ item_id: "e-rev", reviewed: true, description: "reviewed-row" }),
        item({ item_id: "e-bad", provenance: "unverifiable", description: "forged-row" }),
      ],
      total: 3,
      pending: 0,
      unknown: 0,
      approval_rows: 3,
      unverifiable_count: 1,
      review_write: { available: true, reason: null },
    },
    note: null,
    filters: { choice: "all", origin: "all", includeReviewed: false },
    markError: null,
  };
  Pet.paintRefusedQueue();
  let text = textOf(node);
  assert.match(text, /open-row/);
  assert.doesNotMatch(text, /reviewed-row/);
  assert.doesNotMatch(text, /forged-row/);
  assert.match(text, /failed verification \(1\)/);
  const selects = node.childNodes[0].childNodes.filter((child) => child.tagName === "SELECT");
  assert.equal(selects.length, 2);
  selects[0].handlers.change[0]({ target: { value: "timeout" } });
  assert.equal(Pet.state.refusedQueue.filters.choice, "timeout");
  Pet.state.refusedQueue.filters.choice = "all";
  Pet.paintRefusedQueue();
  const box = node.childNodes[0].childNodes.find((child) => child.tagName === "INPUT");
  box.checked = true;
  box.handlers.change[0]({ target: box });
  text = textOf(node);
  assert.match(text, /reviewed-row/);
  const toggle = node.childNodes.find((child) => child.tagName === "BUTTON"
    && child.attrs && child.attrs["aria-label"] === "failed verification (1)");
  toggle.handlers.click[0]();
  text = textOf(node);
  assert.match(text, /forged-row/);
  assert.equal(Pet.state.refusedQueue.filters.showUnverifiable, true);
});

// The choice and origin selects display the active filter after every repaint.
test("paintRefusedQueue keeps the active choice and origin selected", () => {
  const node = makeNode("div");
  Pet._runtime.refusedBody = node;
  Pet.state.refusedQueue = {
    body: {
      items: [item({ item_id: "e-filtered", choice: "timeout", origin: "plugin" })],
      total: 1,
      pending: 0,
      unknown: 0,
      approval_rows: 1,
      unverifiable_count: 0,
      review_write: { available: true, reason: null },
    },
    note: null,
    filters: { choice: "timeout", origin: "plugin", includeReviewed: false },
    markError: null,
  };
  Pet.paintRefusedQueue();
  const selects = () => node.childNodes[0].childNodes.filter((child) => child.tagName === "SELECT");
  assert.equal(selects()[0].value, "timeout");
  assert.equal(selects()[1].value, "plugin");
  Pet.state.refusedQueue.filters = { choice: "all", origin: "all", includeReviewed: false };
  Pet.paintRefusedQueue();
  assert.equal(selects()[0].value, "all");
  assert.equal(selects()[1].value, "all");
});

test("approval_reviewed history arm is not safe or unknown", () => {
  const row = {
    source: "enforcement",
    event_type: "approval_reviewed",
    scan_id: "e-mark",
    item_id: "e-old",
    safe: true,
    finding_count: 0,
    armed: true,
    provenance: "genuine",
  };
  const list = Pet.scanHistoryRows([row]);
  const rendered = textOf(list);
  assert.match(rendered, /reviewed/);
  assert.doesNotMatch(rendered, /safe/);
  const detail = Pet.scanDetailPanel(row);
  const detailText = textOf(detail);
  assert.match(detailText, /n\/a \(operator review mark, not a content scan\)/);
  assert.match(detailText, /Operator marked a refused approval reviewed/);
  assert.match(detailText, /e-old/);
  assert.match(detailText, /scan ran: n\/a \(operator review mark, not a content scan\)/);
});

test("fetch cadence, scope, and transport", async () => {
  sandbox.setInterval = () => 0;
  sandbox.clearInterval = () => {};
  Pet.sse.connect = () => {};
  Pet.sse.disconnect = () => {};
  const container = makeNode(1);
  Pet._runtime.container = container;
  Pet.state.tab = "obs";
  Pet.state.authRequired = false;
  Pet.state.scopeError = null;
  Pet._runtime.refusedSeeded = false;
  Pet._runtime.refusedFetchSeq = 0;
  Pet._runtime.armedSeeded = true;
  Pet._runtime.protectionSeeded = true;
  Pet._runtime.historySeeded = true;
  Pet.state.refusedQueue.body = null;
  Pet.state.refusedQueue.markError = "old";
  let pending = [];
  let callsN = 0;
  const realRender = Pet.renderDashboard;
  let renders = 0;
  Pet.renderDashboard = function (node) {
    renders += 1;
    return realRender.call(Pet, node);
  };
  Pet.api.getRefusedApprovals = () => {
    callsN += 1;
    return new Promise((resolve) => pending.push(resolve));
  };
  Pet.api.getHealth = () => new Promise(() => {});
  Pet.api.getArmed = () => new Promise(() => {});
  Pet.api.getScanHistory = () => new Promise(() => {});
  Pet.renderDashboard(container);
  Pet.renderDashboard(container);
  Pet.renderDashboard(container);
  assert.equal(callsN, 1);
  const during = renders;
  Pet.renderDashboard(container);
  assert.equal(callsN, 1);
  assert.ok(renders > during);

  const first = pending[0];
  Pet._runtime.scopeGen += 1;
  first({ items: [{ item_id: "stale" }], approval_rows: 1, total: 1, pending: 0, unknown: 0 });
  await flush();
  assert.equal(Pet.state.refusedQueue.body, null);
  assert.equal(Pet._runtime.refusedSeeded, false);

  Pet.auth.on401 = () => true;
  Pet._runtime.refusedSeeded = false;
  Pet.renderDashboard(container);
  pending.at(-1)({ _status: 401 });
  await flush();
  assert.equal(Pet.state.refusedQueue.body, null);
  Pet.auth.on401 = () => false;

  Pet._runtime.refusedSeeded = false;
  Pet.state.scopeError = null;
  Pet.renderDashboard(container);
  pending.at(-1)({ _status: 422, detail: [{ field: "profile", message: "missing" }] });
  await flush();
  assert.equal(Pet.state.scopeError.surface, "approvals");
  assert.equal(Pet.state.refusedQueue.body, null);
  const after422 = callsN;
  Pet.renderDashboard(container);
  assert.equal(callsN, after422);

  Pet.state.scopeError = null;
  Pet._runtime.refusedSeeded = false;
  Pet.renderDashboard(container);
  pending.at(-1)({ error: "down" });
  await flush();
  assert.equal(Pet.state.refusedQueue.note, "refused approvals could not be loaded");
  const afterFail = callsN;
  Pet.renderDashboard(container);
  Pet.renderDashboard(container);
  assert.equal(callsN, afterFail);

  Pet.state.refusedQueue.markError = "kept";
  Pet._scope.invalidate();
  assert.equal(Pet.state.refusedQueue.body, null);
  assert.equal(Pet.state.refusedQueue.markError, null);
  await flush();
  const afterInvalidate = callsN;
  assert.equal(afterInvalidate, afterFail + 1);

  const beforeResume = callsN;
  Pet.api.getArmed = async () => ({ armed: true });
  Pet.api.getHealth = async () => ({ scanners: [], pipeline: { scans_total: 0 } });
  Pet._runtime.refusedSeeded = true;
  await Pet.auth._resume();
  await flush();
  assert.equal(callsN, beforeResume + 1);

  const seqBefore = Pet._runtime.refusedFetchSeq;
  Pet._runtime.refusedSeeded = false;
  Pet.state.scopeError = null;
  const older = [];
  Pet.api.getRefusedApprovals = () => new Promise((resolve) => older.push(resolve));
  Pet._fetchRefusedApprovals();
  const firstFetch = older[0];
  Pet._runtime.refusedSeeded = false;
  Pet._fetchRefusedApprovals();
  const secondFetch = older[1];
  secondFetch({ items: [{ item_id: "new" }], total: 1, pending: 0, unknown: 0, approval_rows: 1 });
  await flush();
  firstFetch({ items: [{ item_id: "old" }], total: 1, pending: 0, unknown: 0, approval_rows: 1 });
  await flush();
  assert.equal(Pet.state.refusedQueue.body.items[0].item_id, "new");
  assert.ok(Pet._runtime.refusedFetchSeq > seqBefore);

  const rendersBefore = renders;
  Pet._runtime.refusedSeeded = false;
  Pet._fetchRefusedApprovals();
  older.at(-1)({ items: [], total: 0, pending: 0, unknown: 0, approval_rows: 0 });
  await flush();
  assert.equal(renders, rendersBefore);

  const seen = [];
  const original = sandbox.fetch;
  sandbox.fetch = (url, opts) => {
    seen.push({ url: String(url), body: opts && opts.body });
    return original(url, opts);
  };
  Pet.api.getRefusedApprovals = function () {
    const p = this._scopeParam();
    return this._get("/approvals/refused" + (p ? "?profile=" + encodeURIComponent(p) : ""));
  };
  Pet.api.markApprovalReviewed = function (itemId) {
    const body = { item_id: itemId };
    const p = this._scopeParam();
    if (p) body.profile = p;
    return this._post("/approvals/reviewed", body);
  };
  Pet.hostProfile.source = "none";
  await Pet.api.getRefusedApprovals();
  assert.equal(seen.at(-1).url.endsWith("/approvals/refused"), true);
  Pet.hostProfile.source = "sdk";
  Pet.hostProfile.profile = "beta";
  Pet.state.selectedHermesProfile = "beta";
  await Pet.api.getRefusedApprovals();
  assert.match(seen.at(-1).url, /profile=beta/);
  await Pet.api.markApprovalReviewed("e-9");
  assert.match(seen.at(-1).body, /"item_id":"e-9"/);
  assert.match(seen.at(-1).body, /"profile":"beta"/);
});
