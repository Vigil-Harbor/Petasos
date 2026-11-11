// ---------------------------------------------------------------------------
// Shared: staged changes, the list of what a change would do, and grouping
// of repeated events. Used by more than one view.
// ---------------------------------------------------------------------------

function clone(value) {
  return value === undefined ? undefined : JSON.parse(JSON.stringify(value));
}

function setIn(tree, path, value) {
  var parts = path.split(".");
  var node = tree;
  for (var i = 0; i < parts.length - 1; i += 1) {
    if (!node[parts[i]] || typeof node[parts[i]] !== "object" || Array.isArray(node[parts[i]])) {
      node[parts[i]] = {};
    }
    node = node[parts[i]];
  }
  node[parts[parts.length - 1]] = value;
}

function removeIn(tree, path) {
  var parts = path.split(".");
  var trail = [];
  var node = tree;
  for (var i = 0; i < parts.length - 1; i += 1) {
    if (!node || typeof node !== "object") return;
    trail.push([node, parts[i]]);
    node = node[parts[i]];
  }
  if (!node || typeof node !== "object") return;
  delete node[parts[parts.length - 1]];
  for (var j = trail.length - 1; j >= 0; j -= 1) {
    var parent = trail[j][0];
    var key = trail[j][1];
    if (parent[key] && typeof parent[key] === "object" && !Object.keys(parent[key]).length) {
      delete parent[key];
    }
  }
}

function hasIn(tree, path) {
  var node = tree;
  var parts = path.split(".");
  for (var i = 0; i < parts.length; i += 1) {
    if (!node || typeof node !== "object" || !(parts[i] in node)) return false;
    node = node[parts[i]];
  }
  return true;
}

function getIn(tree, path) {
  var node = tree;
  var parts = path.split(".");
  for (var i = 0; i < parts.length; i += 1) {
    if (!node || typeof node !== "object") return undefined;
    node = node[parts[i]];
  }
  return node;
}

var EMPTY_DRAFT = { overrides: {} };

function draftIsEmpty(draft) {
  return (
    !draft ||
    (draft.enabled === undefined &&
      draft.role === undefined &&
      draft.level === undefined &&
      !Object.keys(draft.overrides || {}).length)
  );
}

function draftBody(draft) {
  var body = {};
  if (!draft) return body;
  if (draft.enabled !== undefined) body.enabled = draft.enabled;
  if (draft.role !== undefined) body.role = draft.role;
  if (draft.level !== undefined) body.level = draft.level;
  if (Object.keys(draft.overrides || {}).length) body.overrides = draft.overrides;
  return body;
}

function leafCount(tree) {
  var count = 0;
  (function walk(node) {
    Object.keys(node || {}).forEach(function (key) {
      var value = node[key];
      if (value && typeof value === "object" && !Array.isArray(value)) walk(value);
      else count += 1;
    });
  })(tree);
  return count;
}

// What a change would do, setting by setting: the label and plain sentence
// above, the value below at full width, where it would come from beneath.
function ChangeValues(props) {
  var before = props.before;
  var after = props.after;
  var row = props.row;
  if (Array.isArray(before) && Array.isArray(after)) {
    var added = after.filter(function (item) {
      return before.indexOf(item) < 0;
    });
    var removed = before.filter(function (item) {
      return after.indexOf(item) < 0;
    });
    return h(
      "ul",
      { className: "petasos-diff" },
      added.map(function (item) {
        return h(
          "li",
          { key: "+" + item },
          h("span", { className: "petasos-diff-sign", "aria-hidden": true }, "+"),
          h("span", { className: "sr-only" }, "Adds "),
          h(Ident, null, String(item))
        );
      }),
      removed.map(function (item) {
        return h(
          "li",
          { key: "-" + item },
          h("span", { className: "petasos-diff-sign", "aria-hidden": true }, "−"),
          h("span", { className: "sr-only" }, "Removes "),
          h(Ident, null, String(item))
        );
      })
    );
  }
  return h(
    "p",
    { className: "petasos-change-values" },
    h("span", { className: "petasos-before" }, showValue(before, row)),
    h("span", { "aria-hidden": true, className: "petasos-arrow" }, " → "),
    h("span", { className: "sr-only" }, " becomes "),
    h("strong", { className: "petasos-after" }, showValue(after, row))
  );
}

function ChangeList(props) {
  var changes = props.changes || [];
  var byPath = rowsByPath(props.rows);
  if (!changes.length) {
    return h("p", { className: "petasos-help" }, props.empty);
  }
  return h(
    "ul",
    { className: "petasos-changes", "aria-label": props.label || "What would change" },
    changes.map(function (change) {
      var row = byPath[change.path] || { path: change.path };
      return h(
        "li",
        { key: change.path, className: "petasos-change" },
        h("p", { className: "petasos-change-name" }, rowLabel(row)),
        row.help ? h("p", { className: "petasos-help" }, row.help) : null,
        h(ChangeValues, { before: change.before, after: change.after, row: row }),
        h(
          "p",
          { className: "petasos-provenance" },
          originText(change.origin_after, props.after || props.stored, props.catalog),
          change.origin_before !== change.origin_after
            ? " · was " + originText(change.origin_before, props.stored, props.catalog).toLowerCase()
            : "",
          change.applies ? " · " + change.applies : "",
          " · ",
          h("span", { className: "petasos-key" }, change.path)
        )
      );
    })
  );
}

// Consecutive events that say the same thing about the same conversation
// are one row with a count. The group can be opened to show each event.
function groupEvents(events) {
  var groups = [];
  events.forEach(function (event) {
    var last = groups[groups.length - 1];
    var key = [
      event.summary,
      event.session_id || "",
      event.tool || "",
      (event.outcome && event.outcome.code) || "",
      String(event.severity || "").toLowerCase(),
    ].join("|");
    if (last && last.key === key) {
      last.events.push(event);
    } else {
      groups.push({ key: key, events: [event] });
    }
  });
  return groups;
}
