
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
          change.applies && change.applies !== props.sharedApplies ? " · " + change.applies : "",
          " · ",
          h("span", { className: "petasos-key" }, change.path)
        )
      );
    })
  );
}

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

// Staged settings survive a reload, including Hermes's own reload after a sign-in.
// One draft per Hermes profile: a tab that moves between profiles must not carry edits across.
function draftKeyFor(home) {
  return "petasos.draft" + (home ? ":" + home : "");
}

function readDraft(home) {
  try {
    var parsed = JSON.parse(window.sessionStorage.getItem(draftKeyFor(home)) || "null");
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return EMPTY_DRAFT;
    var draft = { overrides: {} };
    if (typeof parsed.enabled === "boolean") draft.enabled = parsed.enabled;
    if (typeof parsed.role === "string") draft.role = parsed.role;
    if (typeof parsed.level === "string") draft.level = parsed.level;
    if (parsed.overrides && typeof parsed.overrides === "object" && !Array.isArray(parsed.overrides)) draft.overrides = parsed.overrides;
    return draftIsEmpty(draft) ? EMPTY_DRAFT : draft;
  } catch (_e) {
    return EMPTY_DRAFT;
  }
}

function writeDraft(draft, home) {
  try {
    if (draftIsEmpty(draft)) window.sessionStorage.removeItem(draftKeyFor(home));
    else window.sessionStorage.setItem(draftKeyFor(home), JSON.stringify(draftBody(draft)));
  } catch (_e) {
    // Storage may be refused; the draft still lives for this visit.
  }
}

function isPlain(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

// Equal values, whatever order a mapping's keys come in.
function sameValue(a, b) {
  if (a === undefined) a = null;
  if (b === undefined) b = null;
  if (isPlain(a) && isPlain(b)) {
    var keys = Object.keys(a);
    return (
      keys.length === Object.keys(b).length &&
      keys.every(function (key) {
        return Object.prototype.hasOwnProperty.call(b, key) && sameValue(a[key], b[key]);
      })
    );
  }
  if (Array.isArray(a) && Array.isArray(b)) {
    return (
      a.length === b.length &&
      a.every(function (item, index) {
        return sameValue(item, b[index]);
      })
    );
  }
  return a === b;
}

// Whether a stored value holds what was sent. Petasos merges a mapping into
// the entries already stored, so a stored mapping may hold more than the patch.
function holdsValue(stored, sent) {
  if (isPlain(sent) && isPlain(stored)) {
    return Object.keys(sent).every(function (key) {
      return Object.prototype.hasOwnProperty.call(stored, key) && holdsValue(stored[key], sent[key]);
    });
  }
  return sameValue(stored, sent);
}

// The schema's setting paths, as a lookup. `rows` is a settings body's `settings`.
function knownPaths(rows) {
  if (!rows) return null;
  var known = {};
  rows.forEach(function (row) {
    known[row.path] = true;
  });
  return known;
}

// The settings a tree of overrides names. A mapping-valued setting, such as
// rule ids to severities, is one setting whatever dots its keys hold, so the
// walk stops at a path the schema knows. Without the schema it stops at
// "section.setting", which compares anything deeper whole.
function leafPaths(tree, known) {
  var found = [];
  (function walk(node, parts) {
    Object.keys(node || {}).forEach(function (key) {
      var next = parts.concat([key]);
      var path = next.join(".");
      var value = node[key];
      var plain = value && typeof value === "object" && !Array.isArray(value) && Object.keys(value).length;
      if (!plain || (known ? known[path] : next.length >= 2)) found.push(path);
      else walk(value, next);
    });
  })(tree, []);
  return found;
}

// Whether the settings Petasos holds already contain everything in `body`.
function holdsChange(settings, body) {
  var stored = (settings && settings.stored) || {};
  var chosen = (settings && settings.chosen) || [];
  var keys = ["enabled", "role", "level"];
  for (var i = 0; i < keys.length; i += 1) {
    if (body[keys[i]] === undefined) continue;
    if (!sameValue(body[keys[i]], stored[keys[i]])) return false;
    // A job or strictness that only equals the default has not been written.
    if (keys[i] !== "enabled" && chosen.indexOf(keys[i]) < 0) return false;
  }
  var paths = leafPaths(body.overrides || {}, knownPaths(settings && settings.settings));
  for (var j = 0; j < paths.length; j += 1) {
    if (!holdsValue(getIn(stored.overrides || {}, paths[j]), getIn(body.overrides, paths[j]))) return false;
  }
  return true;
}

// A write whose answer is lost says nothing about whether it happened, so the
// settings are read back and the result is reported as what that reading shows.
function settleWrite(failure, held) {
  if (!unknownOutcome(failure)) {
    failure.outcome = "refused";
    throw failure;
  }
  return call("/settings", { timeout: 10000 }).then(
    function (settings) {
      if (held(settings)) return { settings: settings, readBack: true };
      var missing = new ApiFailure(
        failure.status,
        failure.code,
        "Petasos did not confirm the change, and it was not there when this page read the settings back at " +
          clockTime(Date.now()) +
          ". A request that got no answer can still finish later; Refresh shows what is saved now.",
        failure.path
      );
      missing.outcome = "not_saved";
      missing.settings = settings;
      throw missing;
    },
    function () {
      var unknown = new ApiFailure(
        failure.status,
        failure.code,
        "Petasos did not answer, so this page cannot tell whether the change was saved. Check again before you retry.",
        failure.path
      );
      unknown.outcome = "unknown";
      throw unknown;
    }
  );
}

var READ_BACK_NOTE = "Petasos's answer was lost, so this page read the settings back: the change is saved.";

// `applies` is the sentence a preview gave for when this change takes effect.
function writeSettings(body, applies) {
  return call("/settings", { method: "PUT", body: body }).then(
    function (saved) {
      return { settings: saved, readBack: false, message: saved.restart_message || "Saved" };
    },
    function (failure) {
      return settleWrite(failure, function (settings) {
        return holdsChange(settings, body);
      }).then(function (result) {
        result.message = READ_BACK_NOTE + (applies ? " " + applies : "");
        return result;
      });
    }
  );
}

// What is left of `draft` once `sent` has been saved: anything edited since stays.
function draftAfterSave(draft, sent, known) {
  var left = { overrides: clone((draft && draft.overrides) || {}) };
  ["enabled", "role", "level"].forEach(function (key) {
    if (draft && draft[key] !== undefined && !sameValue(draft[key], sent[key])) left[key] = draft[key];
  });
  leafPaths(sent.overrides || {}, known).forEach(function (path) {
    if (hasIn(left.overrides, path) && sameValue(getIn(left.overrides, path), getIn(sent.overrides, path))) {
      removeIn(left.overrides, path);
    }
  });
  return draftIsEmpty(left) ? EMPTY_DRAFT : left;
}

// The staged values a trial would overwrite with something different.
function draftConflicts(draft, candidate, known) {
  var found = [];
  if (!draft || !candidate) return found;
  ["enabled", "role", "level"].forEach(function (key) {
    if (draft[key] !== undefined && candidate[key] !== undefined && !sameValue(draft[key], candidate[key])) found.push(key);
  });
  leafPaths(candidate.overrides || {}, known).forEach(function (path) {
    if (hasIn(draft.overrides || {}, path) && !sameValue(getIn(draft.overrides, path), getIn(candidate.overrides, path))) {
      found.push(path);
    }
  });
  return found;
}

function mergeDraft(draft, candidate, known) {
  var next = { overrides: clone((draft && draft.overrides) || {}) };
  ["enabled", "role", "level"].forEach(function (key) {
    if (draft && draft[key] !== undefined) next[key] = draft[key];
    if (candidate[key] !== undefined && candidate[key] !== "") next[key] = candidate[key];
  });
  leafPaths(candidate.overrides || {}, known).forEach(function (path) {
    setIn(next.overrides, path, clone(getIn(candidate.overrides, path)));
  });
  return next;
}

// Only the newest request of a kind may publish its answer.
function useLatest() {
  var count = useRef(0);
  return function begin() {
    count.current += 1;
    var mine = count.current;
    return function isLatest() {
      return mine === count.current;
    };
  };
}

function resetSettings(path) {
  var url = path === "*" ? "/overrides" : "/overrides/" + path;
  return call(url, { method: "DELETE" }).then(
    function (body) {
      var effect = String(body.restart_message || "").replace(/^Reset\.\s*/, "");
      return { settings: body.settings, readBack: false, message: [body.message, effect].filter(Boolean).join(" ") };
    },
    function (failure) {
      return settleWrite(failure, function (settings) {
        var overrides = (settings.stored && settings.stored.overrides) || {};
        return path === "*" ? !Object.keys(overrides).length : !hasIn(overrides, path);
      }).then(function (result) {
        result.message = READ_BACK_NOTE;
        return result;
      });
    }
  );
}
