
function topOf(row) {
  return row.path.indexOf(".") < 0 ? "" : row.path.split(".")[0];
}

function isList(row) {
  return String(row.type).indexOf("tuple") === 0;
}

function isMapping(row) {
  return String(row.type).indexOf("mapping") === 0;
}

function isNumber(row) {
  return row.type === "int" || row.type === "float";
}

function fieldId(path) {
  return "petasos-field-" + path.replace(/\./g, "-");
}

function boundsText(row) {
  var b = row.bounds || {};
  var low = b.ge !== null && b.ge !== undefined ? { n: b.ge, open: false } : b.gt !== null && b.gt !== undefined ? { n: b.gt, open: true } : null;
  var high = b.le !== null && b.le !== undefined ? { n: b.le, open: false } : b.lt !== null && b.lt !== undefined ? { n: b.lt, open: true } : null;
  if (low && high && !low.open && !high.open) return "between " + low.n + " and " + high.n;
  var parts = [];
  if (low) parts.push(low.open ? "more than " + low.n : low.n + " or higher");
  if (high) parts.push(high.open ? "less than " + high.n : high.n + " or lower");
  return parts.join(" and ");
}

function outOfBounds(row, number) {
  var b = row.bounds || {};
  if (b.ge !== null && b.ge !== undefined && number < b.ge) return true;
  if (b.gt !== null && b.gt !== undefined && number <= b.gt) return true;
  if (b.le !== null && b.le !== undefined && number > b.le) return true;
  if (b.lt !== null && b.lt !== undefined && number >= b.lt) return true;
  return false;
}

function fieldProblem(row, text, message) {
  if (isNumber(row) && text !== undefined) {
    var number = Number(String(text).trim());
    if (String(text).trim() === "" || !isFinite(number)) return "Enter a number.";
    if (outOfBounds(row, number)) return "Enter " + boundsText(row) + ".";
    if (row.type === "int" && Math.floor(number) !== number) return "Enter a whole number.";
  }
  var sentence = String(message || "");
  return sentence ? sentence.charAt(0).toUpperCase() + sentence.slice(1).replace(/\.?$/, ".") : "";
}

function textFor(row, value) {
  if (value === null || value === undefined) return "";
  if (isList(row)) return (value || []).join("\n");
  if (isMapping(row)) return "";
  return String(value);
}

function differs(row) {
  return JSON.stringify(row.value === undefined ? null : row.value) !== JSON.stringify(row.default === undefined ? null : row.default);
}

function stateWords(row, value) {
  if (row.type === "bool") return value === true ? "On" : "Off";
  if (row.choices && row.choices.length) return showValue(value, row);
  if (isList(row)) return value && value.length ? plural(value.length, "item") : "None";
  if (isMapping(row)) {
    if (value === null || value === undefined) return "Built in";
    var n = Object.keys(value).length;
    return n ? plural(n, "entry", "entries") : "None";
  }
  if (value === null || value === undefined || value === "") return "Not set";
  return String(value);
}

// Hermes Config has no mapping-entry editor; schema labels name both fields.
function MappingRows(props) {
  var row = props.row;
  var labels = row.entry_labels || ["Name", "Value"];
  var numeric = String(row.type).indexOf("float") >= 0;
  function fromValue(value) {
    var saved = props.savedValue || {};
    return Object.keys(value || {}).map(function (key) {
      return {
        key: key,
        value: value[key] === null || value[key] === undefined ? "" : String(value[key]),
        // Whether this row is an entry already saved, whatever is typed into other rows later.
        saved: Object.prototype.hasOwnProperty.call(saved, key),
      };
    });
  }
  var rowsState = useState(function () {
    return fromValue(props.value);
  });
  var entries = rowsState[0];
  var hasSaved = entries.some(function (entry) {
    return entry.saved;
  });
  var names = entries.map(function (entry) {
    return entry.key.trim();
  });
  var repeated = names.filter(function (name, index) {
    return name && names.indexOf(name) !== index;
  });
  function toValue(list) {
    var out = {};
    list.forEach(function (entry) {
      var key = entry.key.trim();
      if (!key) return;
      var text = entry.value.trim();
      var number = Number(text);
      out[key] = numeric && text !== "" && isFinite(number) ? number : text;
    });
    return out;
  }
  // Outside changes reset rows; local edits retain their editing state.
  var incoming = JSON.stringify(props.value || {});
  useEffect(
    function () {
      if (JSON.stringify(toValue(entries)) !== incoming) rowsState[1](fromValue(props.value));
    },
    [incoming]
  );
  // Once a save lands, the rows it stored are saved entries.
  var savedNow = JSON.stringify(Object.keys(props.savedValue || {}).sort());
  useEffect(
    function () {
      var saved = props.savedValue || {};
      rowsState[1](function (held) {
        return held.map(function (entry) {
          return Object.prototype.hasOwnProperty.call(saved, entry.key.trim()) && !entry.saved ? Object.assign({}, entry, { saved: true }) : entry;
        });
      });
    },
    [savedNow]
  );
  function update(list) {
    rowsState[1](list);
    var seen = {};
    var clash = list.some(function (entry) {
      var name = entry.key.trim();
      if (!name) return false;
      if (seen[name]) return true;
      seen[name] = true;
      return false;
    });
    // Two rows with one name would silently become one entry: nothing is staged until they differ.
    if (props.onProblem) props.onProblem(clash ? "Two entries have the same name. Give each its own name." : null);
    if (clash) return;
    var value = toValue(list);
    if (!Object.keys(value).length && row.nullable) props.onValue(null);
    else props.onValue(value);
  }
  var id = fieldId(row.path);
  return h(
    "div",
    { className: "petasos-maprows", role: "group", "aria-labelledby": id + "-label", "aria-describedby": props.describedBy },
    entries.length
      ? h(
          "div",
          { className: "petasos-maprow petasos-maprow-head", "aria-hidden": true },
          h("span", { className: "petasos-label" }, labels[0]),
          h("span", { className: "petasos-label" }, labels[1]),
          h("span", null)
        )
      : null,
    entries.map(function (entry, index) {
      return h(
        "div",
        { key: index, className: "petasos-maprow" },
        h(C.Input, {
          id: index === 0 ? id : undefined,
          value: entry.key,
          disabled: props.disabled || entry.saved,
          "aria-invalid": repeated.indexOf(entry.key.trim()) >= 0 ? "true" : undefined,
          "aria-label": labels[0] + " " + (index + 1),
          onChange: function (e) {
            var next = entries.slice();
            next[index] = { key: e.target.value, value: entry.value, saved: entry.saved };
            update(next);
          },
        }),
        h(C.Input, {
          value: entry.value,
          disabled: props.disabled,
          inputMode: numeric ? "decimal" : undefined,
          "aria-label": labels[1] + " " + (index + 1),
          onChange: function (e) {
            var next = entries.slice();
            next[index] = { key: entry.key, value: e.target.value, saved: entry.saved };
            update(next);
          },
        }),
        entry.saved
          ? h("span", { className: "petasos-tertiary" }, "Saved")
          : h(
          Btn,
          {
            ghost: true,
            disabled: props.disabled,
            "aria-label": "Remove " + (entry.key || labels[0].toLowerCase() + " " + (index + 1)),
            onClick: function () {
              update(entries.filter(function (_item, at) {
                return at !== index;
              }));
            },
          },
          "Remove"
        )
      );
    }),
    repeated.length
      ? h(
          "p",
          { className: "petasos-field-error", role: "alert" },
          "Two entries are named “" + repeated[0] + "”. Give each entry its own name; until then this change is not staged."
        )
      : null,
    hasSaved
      ? h(
          "p",
          { className: "petasos-secondary" },
          "A saved entry can be changed, but not removed or renamed by itself. Reset, below, removes every saved entry of this setting; add back the ones to keep."
        )
      : null,
    h(
      "div",
      null,
      h(
        Btn,
        {
          outlined: true,
          disabled: props.disabled,
          onClick: function () {
            rowsState[1](entries.concat([{ key: "", value: "", saved: false }]));
          },
        },
        "Add"
      )
    )
  );
}

// Unparsed numbers stay text so the API can return its validation reason.
function parseFor(row, text) {
  if (isList(row)) {
    return text
      .split("\n")
      .map(function (line) {
        return line.trim();
      })
      .filter(Boolean);
  }
  if (isMapping(row)) {
    if (!text.trim()) return row.nullable ? null : {};
    return JSON.parse(text);
  }
  if (isNumber(row)) {
    if (!text.trim() && row.nullable) return null;
    var number = Number(text);
    return text.trim() !== "" && isFinite(number) ? number : text;
  }
  if (!text && row.nullable) return null;
  return text;
}

function FieldControl(props) {
  var row = props.row;
  var id = fieldId(row.path);
  var described = [id + "-help", props.error ? id + "-error" : null].filter(Boolean).join(" ");
  if (row.type === "bool") {
    return h(Switch, {
      id: id,
      checked: props.value === true,
      disabled: props.disabled,
      labelledBy: id + "-label",
      describedBy: described,
      onChange: props.onValue,
    });
  }
  if (row.choices && row.choices.length) {
    return h(
      C.Select,
      {
        id: id,
        value: String(props.value),
        disabled: props.disabled,
        onValueChange: function (value) {
          props.onValue(value);
        },
      },
      row.choices.map(function (choice) {
        return h(C.SelectOption, { key: String(choice), value: String(choice) }, showValue(choice, row));
      })
    );
  }
  if (isMapping(row)) {
    return h(MappingRows, {
      row: row,
      value: props.value,
      savedValue: props.savedValue,
      disabled: props.disabled,
      describedBy: described,
      onValue: props.onValue,
      onProblem: props.onProblem,
    });
  }
  if (isList(row)) {
    return h("textarea", {
      id: id,
      className: "petasos-textarea petasos-mono-area",
      rows: Math.min(8, Math.max(2, String(props.text).split("\n").length + 1)),
      value: props.text,
      disabled: props.disabled,
      placeholder: "One per line",
      "aria-invalid": props.error ? "true" : undefined,
      "aria-describedby": described,
      onChange: function (e) {
        props.onText(e.target.value);
      },
    });
  }
  return h(C.Input, {
    id: id,
    value: props.text,
    disabled: props.disabled,
    inputMode: isNumber(row) ? "decimal" : undefined,
    "aria-invalid": props.error ? "true" : undefined,
    "aria-describedby": described,
    onChange: function (e) {
      props.onText(e.target.value);
    },
  });
}

function FieldRow(props) {
  var row = props.row;
  var saved = props.saved || row;
  var staged = props.staged;
  var change = props.change;
  var id = fieldId(row.path);
  var bounds = isNumber(row) ? boundsText(row) : "";
  var catalog = props.catalog;
  var stored = catalog.stored || {};
  var parts = [];
  var action = null;
  if (props.lockedHere) {
    parts.push(stateWords(row, props.value), "Locked by your administrator");
  } else if (staged) {
    parts.push(h("strong", { key: "s", className: "petasos-staged-word" }, "Changed, not saved"));
    if (change) parts.push("was " + stateWords(row, change.before));
    action = h(Btn, { ghost: true, compact: true, onClick: props.onUnstage }, "Undo");
  } else {
    parts.push(stateWords(row, props.value), originText(saved.origin, stored, catalog));
    var target = saved.origin === "override" ? saved.reset_to : null;
    if (target && !props.disabled) {
      action = h(
        Btn,
        { ghost: true, compact: true, onClick: props.onReset, "aria-label": "Reset " + rowLabel(row) + " to " + showValue(target.value, row) },
        sameValue(target.value, saved.value) ? "Use the inherited value" : "Reset to " + stateWords(row, target.value)
      );
    }
  }
  if (bounds && !props.error) parts.push("Allowed: " + bounds);
  if (row.restart) parts.push("After a Hermes restart");
  var line = [];
  parts.forEach(function (part, index) {
    if (index) line.push(h("span", { key: "d" + index, "aria-hidden": true, className: "petasos-dot" }, " · "));
    line.push(typeof part === "string" ? h("span", { key: "p" + index }, part) : part);
  });
  if (action) {
    line.push(h("span", { key: "da", "aria-hidden": true, className: "petasos-dot" }, " · "));
    line.push(h(Fragment, { key: "a" }, action));
  }
  return h(
    Field,
    {
      id: id,
      rowId: "petasos-row-" + row.path,
      label: rowLabel(row),
      path: row.path,
      help: row.help,
      inline: row.type === "bool",
      className: cn(staged && "petasos-field-staged", props.error && "petasos-field-invalid"),
      control: h(FieldControl, {
        row: row,
        savedValue: saved.origin === "override" ? saved.value : null,
        onProblem: props.onProblem,
        value: props.value,
        text: props.text,
        error: props.error,
        disabled: props.disabled,
        onValue: props.onValue,
        onText: props.onText,
      }),
    },
    props.error ? h("p", { className: "petasos-field-error", id: id + "-error", role: "alert" }, props.error) : null,
    props.consequence
      ? h(
          "p",
          { className: "petasos-consequence", role: "status" },
          h(
            "strong",
            null,
            (row.restart ? "Once in use: " : staged ? "On save: " : "") + props.consequence.title + ". "
          ),
          props.consequence.sentence
        )
      : null,
    h("p", { className: "petasos-provenance", id: id + "-state" }, line)
  );
}

function ruleState(rows, rule, props) {
  var byPath = rowsByPath(rows);
  var suppress = byPath["rules.suppress"] || { value: [], origin: "default" };
  var severity = byPath["rules.severity_overrides"] || { value: {}, origin: "default" };
  var quiet = (Array.isArray(suppress.value) ? suppress.value : []).indexOf(rule) >= 0;
  var lowered = severity.value && severity.value[rule];
  return {
    suppress: Array.isArray(suppress.value) ? suppress.value : [],
    severity: severity.value || {},
    quiet: quiet,
    words: quiet
      ? "Turned off (" + originText(suppress.origin, props.stored, props.catalog).toLowerCase() + "). It does not block, is not recorded, and adds no risk."
      : lowered
        ? "Counts as " + lowered + " (" + originText(severity.origin, props.stored, props.catalog).toLowerCase() + ")."
        : "On, at its usual severity.",
  };
}

function RuleHelper(props) {
  var rule = props.rule;
  var saved = ruleState(props.savedRows, rule, props);
  var staged = ruleState(props.rows, rule, props);
  var changed = props.dirty && staged.words !== saved.words;
  // Each action is "loading", "allowed", "refused" or "unknown" (the question could not be asked).
  var askedState = useState({ rule: rule, quiet: "loading", lower: "loading" });
  var asked = askedState[0].rule === rule ? askedState[0] : { quiet: "loading", lower: "loading" };
  var retryState = useState(0);
  var lowerValue = Object.assign({}, staged.severity);
  lowerValue[rule] = "low";
  useEffect(
    function () {
      var live = true;
      askedState[1]({ rule: rule, quiet: "loading", lower: "loading" });
      function accepted(overrides) {
        if (props.draftInvalid) return Promise.resolve("blocked");
        var body = draftBody(mergeDraft(props.draft, { overrides: overrides }, knownPaths(props.savedRows)));
        return call("/settings/preview", { method: "POST", body: body }).then(
          function (body) {
            if (body.valid !== false) return "allowed";
            var aboutRules = (body.problems || []).some(function (problem) {
              return /(^|\.)rules\.(suppress|severity_overrides)/.test(String(problem.path || ""));
            });
            // Another unsaved change is what Petasos objects to; that says nothing about this rule.
            return aboutRules ? "refused" : "blocked";
          },
          function () {
            return "unknown";
          }
        );
      }
      Promise.all([
        staged.quiet ? Promise.resolve("allowed") : accepted({ rules: { suppress: staged.suppress.concat([rule]) } }),
        accepted({ rules: { severity_overrides: lowerValue } }),
      ]).then(function (answers) {
        if (live) askedState[1]({ rule: rule, quiet: answers[0], lower: answers[1] });
      });
      return function () {
        live = false;
      };
    },
    [rule, Boolean(props.draftInvalid), JSON.stringify(draftBody(props.draft)), JSON.stringify(staged.suppress), JSON.stringify(staged.severity), retryState[0]]
  );
  var refused = [];
  if (!staged.quiet && asked.quiet === "refused") refused.push("turned off");
  if (asked.lower === "refused") refused.push("set to report without blocking");
  var unknown = asked.quiet === "unknown" || asked.lower === "unknown";
  var blocked = asked.quiet === "blocked" || asked.lower === "blocked";
  var loading = asked.quiet === "loading" || asked.lower === "loading";
  var offered = (!staged.quiet && asked.quiet === "allowed") || asked.lower === "allowed";
  return h(
    Panel,
    {
      className: "petasos-rule-helper",
      title: "Rule",
      description: props.sentence || "The settings below decide what this rule does.",
      actions: h(Btn, { ghost: true, onClick: props.onClose }, "Close"),
    },
    h(KeyValues, {
      rows: [
        ["Rule id", h("span", { className: "petasos-idrow" }, h(Ident, null, rule), h(CopyButton, { value: rule, label: "Copy rule id" }))],
        ["Saved", saved.words],
        changed ? ["With your unsaved changes", staged.words] : null,
      ],
    }),
    h(
      "div",
      { className: "petasos-row-actions" },
      staged.quiet || asked.quiet !== "allowed"
        ? null
        : h(Btn, { outlined: true, disabled: props.disabled, onClick: function () { props.onQuiet(rule); } }, "Turn this rule off"),
      asked.lower !== "allowed"
        ? null
        : h(Btn, { outlined: true, disabled: props.disabled, onClick: function () { props.onLower(rule); } }, "Report it without blocking"),
      h(
        LinkButton,
        {
          onClick: function () {
            var route = { rule: rule, sentence: props.sentence || "" };
            if (props.dirty && props.testable) route.settings = JSON.stringify(draftBody(props.draft));
            go("tryit", route);
          },
        },
        props.dirty && props.testable ? "Test your unsaved changes in Try it" : "Test it in Try it"
      )
    ),
    props.dirty && !props.testable
      ? h("p", { className: "petasos-secondary" }, "Try it would use the saved settings: your unsaved changes have not been checked yet, or need fixing.")
      : null,
    refused.length
      ? h("p", { className: "petasos-secondary", role: "status" }, "These settings do not let this rule be " + refused.join(" or ") + ".")
      : null,
    loading ? h("p", { className: "petasos-secondary", role: "status" }, "Checking what can be changed for this rule…") : null,
    blocked && !loading
      ? h(
          "p",
          { className: "petasos-secondary", role: "status" },
          "Another unsaved change needs fixing before Petasos can say what is allowed for this rule. Use “Go to it” in the bar above."
        )
      : null,
    unknown && !loading
      ? h(
          "p",
          { className: "petasos-secondary", role: "status" },
          "Petasos could not be asked what can be changed for this rule. ",
          h(Btn, { ghost: true, compact: true, onClick: function () { retryState[1](retryState[0] + 1); } }, "Try again")
        )
      : null,
    offered ? h("p", { className: "petasos-secondary" }, "Not saved until you press Save.") : null
  );
}

function ChangeSheet(props) {
  var catalog = props.catalog;
  var preview = props.preview;
  var draft = props.draft;
  var stored = catalog.stored || {};
  var labels = catalog.labels || {};
  var top = [];
  if (draft.enabled !== undefined && draft.enabled !== stored.enabled)
    top.push([labels.enabled || "Protection", stored.enabled === false ? "Paused" : "On", draft.enabled ? "On" : "Paused"]);
  if (draft.role !== undefined && draft.role !== stored.role)
    top.push([labels.role || "Job", roleLabel(catalog, stored.role), roleLabel(catalog, draft.role)]);
  if (draft.level !== undefined && draft.level !== stored.level)
    top.push([labels.level || "Strictness", levelLabel(catalog, stored.level), levelLabel(catalog, draft.level)]);
  var changes = (preview && preview.changes) || [];
  return h(
    "div",
    {
      id: "petasos-change-sheet",
      onKeyDown: function (event) {
        if (event.key === "Escape") props.onClose();
      },
    },
    h(
      Panel,
      {
        className: "petasos-sheet",
        title: "What will change",
        titleId: "petasos-sheet-title",
        description: draft.enabled === false ? "Pausing applies from the agent's next tool call." : (preview && preview.applies) || "",
        actions: h(Btn, { ghost: true, onClick: props.onClose, "aria-label": "Close the list of changes" }, "Close"),
      },
      top.length
        ? h(
            "ul",
            { className: "petasos-changes" },
            top.map(function (item) {
              return h(
                "li",
                { key: item[0], className: "petasos-change" },
                h("p", { className: "petasos-change-name" }, item[0]),
                h("p", { className: "petasos-change-values" }, h("span", { className: "petasos-before" }, item[1]), h("span", { className: "petasos-arrow", "aria-hidden": true }, " → "), h("span", { className: "sr-only" }, " becomes "), h("strong", null, item[2]))
              );
            })
          )
        : null,
      h(ChangeList, {
        catalog: catalog,
        rows: catalog.settings,
        changes: changes,
        stored: stored,
        after: preview && preview.stored,
        label: "Settings that would change",
        sharedApplies: draft.enabled === false ? "" : (preview && preview.applies) || "",
        empty: top.length ? "No other setting changes." : "These edits leave every value as it was.",
      })
    )
  );
}

function Settings(props) {
  var catalog = props.catalog;
  var params = props.route.params;
  var draft = props.draft || EMPTY_DRAFT;
  var setDraft = props.setDraft;
  var textsState = useState({});
  var texts = textsState[0];
  var setTexts = textsState[1];
  var localErrorsState = useState({});
  // A preview is kept with the draft it describes; only a matching one may be reviewed or saved.
  var previewState = useState(null);
  var preview = previewState[0] ? previewState[0].body : null;
  var previewRetryState = useState(0);
  var saveErrorState = useState(null);
  var focusPathState = useState(null);
  var discardedState = useState(null);
  var savedState = useState(null);
  var expertState = useState(false);
  var searchState = useState("");
  var sectionState = useState(
    params.changed ? "changed" : params.section ? params.section : params.rule ? "rules" : params.path ? topOf({ path: params.path }) || "general" : "basics"
  );
  var section = sectionState[0];
  var resetState = useState(null);
  var reviewState = useState(params.review === "1");
  var reviewing = reviewState[0];
  var toolbarRef = useRef(null);
  var lastReset = useRef(null);
  // After a reset the Reset control is gone, so focus goes to the setting it belonged to.
  var rememberResetOpener = useReturnFocus(Boolean(resetState[0]), function () {
    var path = lastReset.current;
    return path && path !== "*" && document.getElementById(fieldId(path)) ? fieldId(path) : "petasos-settings-search";
  });

  var empty = draftIsEmpty(draft);
  // The draft and the saved settings it would change: a preview describes exactly this pair.
  var draftKey = JSON.stringify([draftBody(draft), catalog && catalog.stored]);

  useEffect(
    function () {
      if (empty) {
        previewState[1](null);
        reviewState[1](false);
        return;
      }
      var live = true;
      var key = draftKey;
      var timer = window.setTimeout(function () {
        call("/settings/preview", { method: "POST", body: draftBody(draft) })
          .then(function (body) {
            if (live) previewState[1]({ key: key, body: body });
          })
          .catch(function (failure) {
            if (live) previewState[1]({ key: key, failed: failure, body: preview });
          });
      }, 250);
      return function () {
        live = false;
        window.clearTimeout(timer);
      };
    },
    [draftKey, previewRetryState[0]]
  );
  var previewCurrent = Boolean(previewState[0] && previewState[0].key === draftKey && !previewState[0].failed && previewState[0].body);
  var previewFailed = previewState[0] && previewState[0].key === draftKey ? previewState[0].failed : null;

  useEffect(
    function () {
      if (params.path) sectionState[1](topOf({ path: params.path }) || "general");
    },
    [params.path]
  );
  // Typed text is kept only for settings that are still staged or still wrong.
  useEffect(
    function () {
      setTexts(function (held) {
        var kept = {};
        Object.keys(held).forEach(function (path) {
          if (hasIn(draft.overrides, path) || localErrorsState[0][path]) kept[path] = held[path];
        });
        return Object.keys(kept).length === Object.keys(held).length ? held : kept;
      });
    },
    [draftKey]
  );
  // "Fix the marked setting": open its section, then put focus on it.
  useEffect(
    function () {
      var path = focusPathState[0];
      if (!path) return;
      var field = document.getElementById(fieldId(path));
      if (!field) return;
      focusPathState[1](null);
      revealInView(field, "center");
      field.focus({ preventScroll: true });
    },
    [focusPathState[0], section]
  );
  useEffect(
    function () {
      if (!params.path) return;
      var target = document.getElementById("petasos-row-" + params.path);
      if (target) revealInView(target, "center");
    },
    [params.path, section, Boolean(catalog)]
  );

  if (props.pending) {
    // The notice above this view explains the unconfirmed change and offers Check again.
    return h(
      Panel,
      { title: "Settings" },
      h(
        "p",
        { role: "status" },
        "Settings are not shown while a change is unconfirmed: what this page last read may no longer be what is saved. Use Check again, above."
      ),
      empty ? null : h("p", { className: "petasos-secondary" }, "Your unsaved changes are kept.")
    );
  }
  if (!catalog && props.catalogFailure) {
    return h(
      Panel,
      { title: "Settings" },
      h(
        Notice,
        {
          tone: "destructive",
          title: "The settings could not be loaded",
          action: h(Btn, { onClick: props.onRetryCatalog }, "Try again"),
        },
        h("p", null, props.catalogFailure.message),
        empty ? null : h("p", null, "Your unsaved changes are kept.")
      )
    );
  }
  if (!catalog) {
    return h(Panel, { title: "Settings" }, h("p", { className: "petasos-help", role: "status" }, "Loading settings…"));
  }

  var savedRows = catalog.settings || [];
  // Until a preview of this exact draft arrives, a staged value is shown as typed and nothing derived from it is.
  var rows =
    previewCurrent && preview.settings && preview.valid
      ? preview.settings
      : savedRows.map(function (row) {
          if (!hasIn(draft.overrides, row.path)) return row;
          return Object.assign({}, row, { value: getIn(draft.overrides, row.path), origin: "override" });
        });
  var savedBy = rowsByPath(savedRows);
  var changeBy = {};
  ((previewCurrent && preview.changes) || []).forEach(function (change) {
    changeBy[change.path] = change;
  });
  var problems = {};
  ((previewCurrent && preview.problems) || []).forEach(function (problem) {
    problems[String(problem.path).replace(/^overrides\./, "")] = problem.message;
  });
  var saveError = saveErrorState[0];
  if (saveError && saveError.path) {
    problems[String(saveError.path).replace(/^overrides\./, "")] = saveError.message;
  }
  Object.keys(localErrorsState[0]).forEach(function (path) {
    problems[path] = localErrorsState[0][path];
  });

  var lockedInfo = catalog.locked || { stored: [], settings: [] };
  var lockedAll = props.locked || (lockedInfo.stored || []).indexOf("overrides") >= 0;
  var stored = catalog.stored || {};
  var labels = catalog.labels || {};
  var help = catalog.help || {};
  var sections = sectionsByPath(catalog);

  function stage(path, value) {
    discardedState[1](null);
    var next = clone(draft);
    next.overrides = next.overrides || {};
    setIn(next.overrides, path, value);
    setDraft(next);
    saveErrorState[1](null);
    savedState[1](null);
  }
  function unstage(path) {
    var next = clone(draft);
    removeIn(next.overrides || {}, path);
    setDraft(next);
    var t = Object.assign({}, texts);
    delete t[path];
    setTexts(t);
    var errors = Object.assign({}, localErrorsState[0]);
    delete errors[path];
    localErrorsState[1](errors);
  }
  function stageTop(key, value) {
    discardedState[1](null);
    var next = clone(draft);
    if (value === stored[key] && !props.saving) delete next[key];
    else next[key] = value;
    setDraft(next);
    savedState[1](null);
  }
  function onText(row, text) {
    var t = Object.assign({}, texts);
    t[row.path] = text;
    setTexts(t);
    var errors = Object.assign({}, localErrorsState[0]);
    try {
      stage(row.path, parseFor(row, text));
      delete errors[row.path];
    } catch (_e) {
      errors[row.path] = 'This needs to be JSON, for example {"name": "value"}.';
    }
    localErrorsState[1](errors);
  }
  function discard() {
    discardedState[1]({ draft: draft, count: staged });
    setDraft(EMPTY_DRAFT);
    setTexts({});
    localErrorsState[1]({});
    saveErrorState[1](null);
    reviewState[1](false);
  }
  function afterWrite(body, message) {
    savedState[1]({ at: Date.now(), message: message, restart: (body && body.restart) || [] });
    reviewState[1](false);
  }
  var DRAFT_NOTES = {
    unknown: "Your draft is still here. Refresh to check what is saved before you save again.",
    other: "Your changes are still here, not saved.",
  };
  // Only what was sent is cleared: an edit made while the save was in flight stays staged.
  function save() {
    if (props.saving || !previewCurrent) return;
    var sent = clone(draftBody(draft));
    saveErrorState[1](null);
    props
      .onWrite(
        function () {
          return writeSettings(sent, preview && preview.applies);
        },
        "Save settings",
        DRAFT_NOTES,
        sent
      )
      .then(function (result) {
        afterWrite(result.settings, result.message);
      })
      .catch(function (failure) {
        if (failure.path) saveErrorState[1](failure);
        reviewState[1](false);
        if (toolbarRef.current) revealInView(toolbarRef.current, "start");
      });
  }
  function reset(path) {
    if (props.saving) return;
    var row = path === "*" ? null : savedBy[path];
    props
      .onWrite(
        function () {
          return resetSettings(path);
        },
        path === "*" ? "Reset every setting you set" : "Reset " + rowLabel(row || { path: path })
      )
      .then(function (result) {
        afterWrite(result.settings, result.message);
      })
      .catch(function () {})
      .finally(function () {
        resetState[1](null);
      });
  }
  function quietRule(rule) {
    var current = hasIn(draft.overrides, "rules.suppress")
      ? draft.overrides.rules.suppress
      : (savedBy["rules.suppress"] && savedBy["rules.suppress"].value) || [];
    if (current.indexOf(rule) >= 0) return;
    stage("rules.suppress", current.concat([rule]));
    var t = Object.assign({}, texts);
    t["rules.suppress"] = current.concat([rule]).join("\n");
    setTexts(t);
  }
  function lowerRule(rule) {
    var current = hasIn(draft.overrides, "rules.severity_overrides")
      ? draft.overrides.rules.severity_overrides
      : (savedBy["rules.severity_overrides"] && savedBy["rules.severity_overrides"].value) || {};
    var next = Object.assign({}, current);
    next[rule] = "low";
    stage("rules.severity_overrides", next);
    var t = Object.assign({}, texts);
    t["rules.severity_overrides"] = JSON.stringify(next, null, 2);
    setTexts(t);
  }

  function pickSection(key) {
    searchState[1]("");
    sectionState[1](key);
    if (key === "changed") go("settings", { changed: "1" });
    else if (params.changed) go("settings", { section: key });
  }
  var expert = expertState[0];
  var search = searchState[0].trim().toLowerCase();
  var tops = [""];
  (catalog.sections || []).forEach(function (item) {
    if (item.path.indexOf(".") < 0 && tops.indexOf(item.path) < 0) tops.push(item.path);
  });
  function visible(row) {
    if (!expert && row.audience === "expert" && !hasIn(draft.overrides, row.path) && savedBy[row.path] && savedBy[row.path].origin !== "override") return false;
    if (!search) return true;
    return (row.path + " " + row.help + " " + rowLabel(row)).toLowerCase().indexOf(search) >= 0;
  }
  var counts = {};
  var changed = {};
  var hidden = {};
  rows.forEach(function (row) {
    var top = topOf(row);
    if (visible(row)) counts[top] = (counts[top] || 0) + 1;
    else if (!search) hidden[top] = (hidden[top] || 0) + 1;
    var s = savedBy[row.path];
    if ((s && s.origin === "override") || hasIn(draft.overrides, row.path)) changed[top] = (changed[top] || 0) + 1;
  });

  function sectionLabel(top) {
    if (!top) return "General";
    return (sections[top] && sections[top].label) || top;
  }

  var changedRows = rows.filter(function (row) {
    return differs(row) || hasIn(draft.overrides, row.path);
  });
  var navItems = [
    { key: "basics", label: "Basics", count: 3 },
    { key: "changed", label: "Changed from default", count: changedRows.length },
  ].concat(
    tops.map(function (top) {
      return { key: top || "general", label: sectionLabel(top), count: counts[top] || 0, changed: changed[top] || 0 };
    })
  );
  var changedView = !search && section === "changed";
  var activeTop = section === "basics" || section === "changed" ? null : section === "general" ? "" : section;
  var shown = search
    ? rows.filter(visible)
    : changedView
      ? changedRows
      : activeTop === null
        ? []
        : rows.filter(function (row) {
            return topOf(row) === activeTop && visible(row);
          });

  var groups = [];
  shown.forEach(function (row) {
    var last = groups[groups.length - 1];
    if (!last || last.section !== row.section) groups.push({ section: row.section, rows: [row] });
    else last.rows.push(row);
  });

  function renderRow(row) {
    var saved = savedBy[row.path];
    var staged = hasIn(draft.overrides, row.path);
    var text = row.path in texts ? texts[row.path] : textFor(row, row.value);
    var lockedHere = (lockedInfo.settings || []).indexOf(row.path) >= 0;
    var problem = problems[row.path];
    var consequences = (previewCurrent && preview.valid && preview.consequences) || (empty ? catalog.consequences : null) || {};
    return h(FieldRow, {
      consequence: row.value === "on" ? consequences[row.path] : null,
      key: row.path,
      catalog: catalog,
      row: row,
      saved: saved,
      staged: staged,
      change: changeBy[row.path],
      value: row.value,
      text: text,
      error: problem ? fieldProblem(row, row.path in texts ? texts[row.path] : undefined, problem) : null,
      disabled: lockedAll || lockedHere,
      lockedHere: lockedHere,
      onValue: function (value) {
        stage(row.path, value);
      },
      onText: function (value) {
        onText(row, value);
      },
      onUnstage: function () {
        unstage(row.path);
      },
      onProblem: function (message) {
        localErrorsState[1](function (held) {
          if ((held[row.path] || null) === message) return held;
          var next = Object.assign({}, held);
          if (message) next[row.path] = message;
          else delete next[row.path];
          return next;
        });
      },
      onReset: function () {
        rememberResetOpener();
        lastReset.current = row.path;
        resetState[1](row.path);
      },
    });
  }

  var lockedStored = lockedInfo.stored || [];
  var enabledNow = draft.enabled !== undefined ? draft.enabled : stored.enabled !== false;
  var roleNow = draft.role || stored.role;
  var levelNow = draft.level || stored.level;
  var overrideCount = savedRows.filter(function (row) {
    return row.origin === "override";
  }).length;
  var secrets = catalog.secrets || {};
  var sessionCheck = props.detailsCurrent && ((props.status.doctor && props.status.doctor.checks) || []).filter(function (check) {
    return check.id === "session_secret";
  })[0];
  var basics = h(
    Panel,
    {
      title: "Basics",
      description: "The choices most people make. Everything else starts from these.",
    },
    h(Field, {
      id: "petasos-basic-enabled",
      label: labels.enabled || "Protection",
      path: "enabled",
      help: help.enabled,
      inline: true,
      control: h(Switch, {
        id: "petasos-basic-enabled",
        checked: enabledNow,
        disabled: props.locked || lockedStored.indexOf("enabled") >= 0,
        labelledBy: "petasos-basic-enabled-label",
        describedBy: "petasos-basic-enabled-help",
        onChange: function (value) {
          stageTop("enabled", value);
        },
      }),
    }, h(
      "p",
      { className: "petasos-provenance" },
      enabledNow ? "On" : "Paused",
      draft.enabled !== undefined && draft.enabled !== (stored.enabled !== false) ? h(Fragment, null, h("span", { className: "petasos-dot", "aria-hidden": true }, " · "), h("strong", { className: "petasos-staged-word" }, "Changed, not saved")) : null
    )),
    h(Field, {
      id: "petasos-basic-role",
      label: labels.role || "Job",
      path: "role",
      help: help.role,
      control: h(
        Fragment,
        null,
        h(
          C.Select,
          {
            id: "petasos-basic-role",
            value: roleNow,
            disabled: props.locked || lockedStored.indexOf("role") >= 0,
            onValueChange: function (value) {
              stageTop("role", value);
            },
          },
          (catalog.roles || []).map(function (role) {
            return h(C.SelectOption, { key: role.name, value: role.name }, role.label || role.name);
          })
        ),
        h("p", { className: "petasos-help petasos-gap-above" }, (roleOf(catalog, roleNow) || {}).description)
      ),
    }),
    h(Field, {
      id: "petasos-basic-level",
      label: labels.level || "Strictness",
      path: "level",
      help: help.level,
      control: h(
        Fragment,
        null,
        h(
          C.Select,
          {
            id: "petasos-basic-level",
            value: levelNow,
            disabled: props.locked || lockedStored.indexOf("level") >= 0,
            onValueChange: function (value) {
              stageTop("level", value);
            },
          },
          (catalog.levels || []).map(function (level) {
            return h(C.SelectOption, { key: level.name, value: level.name }, level.label || level.name);
          })
        ),
        h("p", { className: "petasos-help petasos-gap-above" }, (levelOf(catalog, levelNow) || {}).description)
      ),
    }),
    h(KeyValues, {
      rows: [
        [labels.overrides || "Your changes", overrideCount ? plural(overrideCount, "setting") + " set by you, on top of the job and strictness." : "None. The job and strictness decide every setting."],
        [
          "Session secret",
          !props.detailsCurrent
            ? "The current signing state could not be confirmed. Check the protection state again."
            : secrets.session_secret !== "set"
              ? "Not set. Activity records are not signed."
              : props.status.record_signing && props.status.record_signing.signed
                ? "Set and usable. New activity records are signed; Activity shows whether each one still matches."
                : sessionCheck && (sessionCheck.status === "warn" || sessionCheck.status === "fail")
                  ? "Set, but Petasos cannot make a signing key from it, so records are not signed. Running hermes petasos doctor says what is wrong with it."
                  : "Set. Petasos has not confirmed whether it can sign new activity records.",
        ],
        ["Hash key", secrets.hash_key === "set" ? "Set." : "Not set. Only needed to hide personal details as fingerprints."],
      ],
    }),
    h("p", { className: "petasos-help" }, "The session secret and hash key live in the profile's .env file and are never shown here."),
    overrideCount && !lockedAll
      ? h(
          "div",
          { className: "petasos-row-actions" },
          h(Btn, { outlined: true, onClick: function () { rememberResetOpener(); lastReset.current = "*"; resetState[1]("*"); } }, "Reset all " + plural(overrideCount, "setting") + " you set")
        )
      : null
  );

  var changeCount = previewCurrent && preview.changes ? preview.changes.length : 0;
  var topChanges = ["enabled", "role", "level"].filter(function (key) {
    return draft[key] !== undefined && draft[key] !== stored[key];
  }).length;
  var invalid = (previewCurrent && preview.valid === false) || Object.keys(localErrorsState[0]).length > 0;
  var resetPath = resetState[0];
  var resetRow = resetPath && resetPath !== "*" ? savedBy[resetPath] : null;

  var staged = changeCount + topChanges;
  var toolbar = h(
    "div",
    { className: "petasos-settings-toolbar", role: "toolbar", "aria-label": "Settings", ref: toolbarRef },
    h(
      "div",
      { className: "petasos-search" },
      h(Icon, { name: "search", className: "petasos-search-icon" }),
      h(C.Input, {
        type: "search",
        id: "petasos-settings-search",
        placeholder: "Search settings",
        "aria-label": "Search settings",
        value: searchState[0],
        onChange: function (e) {
          searchState[1](e.target.value);
        },
      })
    ),
    h(
      "div",
      { className: "petasos-inline-switch" },
      h(Switch, { id: "petasos-expert", checked: expert, labelledBy: "petasos-expert-label", onChange: expertState[1] }),
      h("span", { id: "petasos-expert-label" }, "Show rarely needed settings")
    ),
    h(
      "div",
      { className: "petasos-savebox" },
      empty
        ? h("span", { className: "petasos-secondary", role: "status" }, "No unsaved changes")
        : previewFailed
          ? h(
              "span",
              { className: "petasos-secondary petasos-strong", role: "status" },
              "These changes could not be checked. ",
              h(Btn, { ghost: true, compact: true, onClick: function () { previewRetryState[1](previewRetryState[0] + 1); } }, "Try again")
            )
          : invalid
          ? h(
              "span",
              { className: "petasos-secondary petasos-strong", role: "status" },
              "A setting needs fixing before you can save. ",
              h(
                Btn,
                {
                  ghost: true,
                  compact: true,
                  onClick: function () {
                    var path = Object.keys(problems)[0];
                    if (!path) return;
                    searchState[1]("");
                    sectionState[1](topOf({ path: path }) || "general");
                    focusPathState[1](path);
                  },
                },
                "Go to it"
              )
            )
          : previewCurrent
            ? h(
                "button",
                {
                  type: "button",
                  className: "petasos-changecount",
                  "aria-expanded": reviewing,
                  "aria-controls": "petasos-change-sheet",
                  onClick: function () {
                    reviewState[1](!reviewing);
                  },
                },
                plural(staged, "unsaved change"),
                h(Icon, { name: "chevron", size: 14, className: "petasos-changecount-chevron" })
              )
            : h("span", { className: "petasos-secondary", role: "status" }, "Checking changes…"),
      empty
        ? null
        : h(
            Btn,
            {
              outlined: true,
              onClick: discard,
              disabled: props.saving,
              title: props.saving ? "Wait for the save in progress to finish" : undefined,
              "aria-label": "Discard all " + plural(staged, "unsaved change"),
            },
            "Discard all"
          ),
      empty
        ? null
        : h(
            Btn,
            {
              outlined: true,
              disabled: invalid || !previewCurrent,
              title: invalid ? "Fix the marked setting first" : undefined,
              onClick: function () {
                go("tryit", { settings: JSON.stringify(draftBody(draft)) });
              },
            },
            "Try it first"
          ),
      h(
        Btn,
        {
          disabled: empty || invalid || !previewCurrent || lockedAll || props.saving,
          onClick: save,
        },
        props.saving ? "Saving…" : "Save"
      )
    )
  );
  var sheet =
    reviewing && previewCurrent && !invalid && !empty
      ? h(ChangeSheet, {
          catalog: catalog,
          preview: preview,
          draft: draft,
          onClose: function () {
            reviewState[1](false);
          },
        })
      : null;

  var saved = savedState[0];

  return h(
    "div",
    { className: "petasos-stack petasos-settings" },
    toolbar,
    sheet,
    saved
      ? h(
          "div",
          { className: "petasos-saved" },
          h(
            Notice,
            {
              tone: "success",
              title: "Saved at " + clockTime(saved.at),
              action: h(Btn, { ghost: true, onClick: function () { savedState[1](null); } }, "Dismiss"),
            },
            h("p", null, saved.message)
          )
        )
      : null,
    discardedState[0] && empty
      ? h(
          Notice,
          {
            tone: "info",
            title: "Discarded " + plural(discardedState[0].count, "unsaved change"),
            action: h(
              Btn,
              {
                outlined: true,
                onClick: function () {
                  setDraft(discardedState[0].draft);
                  discardedState[1](null);
                },
              },
              "Undo"
            ),
          },
          "Nothing was saved. Undo puts the changes back as they were."
        )
      : null,
    props.catalogFailure
      ? h(
          Notice,
          {
            tone: "warning",
            title: "The settings could not be re-read",
            action: h(Btn, { ghost: true, onClick: props.onRetryCatalog }, "Try again"),
          },
          "The saved values shown here were read at " + (props.catalogReadAt ? clockTime(props.catalogReadAt) : "an earlier time") + " and may have changed since. " + props.catalogFailure.message
        )
      : null,
    lockedAll
      ? h(
          Notice,
          { tone: "warning", title: "Locked by your administrator" },
          props.lockedMessage || "These settings are fixed in Hermes's managed configuration. You can read them here and change them there."
        )
      : (lockedInfo.settings || []).length || lockedStored.length
        ? h(Notice, { tone: "info", title: "Some settings are locked by your administrator" }, "They are marked below and cannot be changed here.")
        : null,
    catalog.valid === false
      ? h(
          Notice,
          { tone: "destructive", strong: true, title: "The saved settings have a mistake, so Petasos is not using them" },
          (catalog.problems || []).map(function (problem) {
            return h("p", { key: problem.path }, h(Mono, null, problem.path), " ", problem.message);
          })
        )
      : null,
    params.rule
      ? h(RuleHelper, {
          catalog: catalog,
          rule: params.rule,
          rows: rows,
          savedRows: savedRows,
          dirty: !empty,
          draft: draft,
          draftInvalid: invalid,
          testable: previewCurrent && !invalid,
          stored: stored,
          sentence: params.sentence,
          disabled: lockedAll,
          onQuiet: quietRule,
          onLower: lowerRule,
          onClose: function () {
            go("settings");
          },
        })
      : null,
    h(
      "div",
      { className: "petasos-settings-body" },
      h(Choice, {
        id: "petasos-section-pick",
        className: "petasos-section-pick",
        label: "Section",
        value: search ? "" : section,
        placeholder: "Search results",
        options: navItems.map(function (item) {
          return { value: item.key, label: item.label + " (" + item.count + ")" + (item.changed ? " · changed" : "") };
        }),
        onChange: pickSection,
      }),
      h(
        "nav",
        { className: "petasos-sections", "aria-label": "Settings sections" },
        h("p", { className: "petasos-sections-title" }, "Sections"),
        navItems.map(function (item) {
          var active = !search && section === item.key;
          return h(
            "button",
            {
              key: item.key,
              type: "button",
              className: cn("petasos-section", active && "petasos-section-on"),
              "aria-current": active ? "page" : undefined,
              onClick: function () {
                pickSection(item.key);
              },
            },
            h("span", { className: "petasos-section-name" }, item.label),
            item.changed ? h("span", { className: "petasos-section-changed", title: item.changed + " set by you or changed" }, "●", h("span", { className: "sr-only" }, item.changed + " changed")) : null,
            h("span", { className: "petasos-section-count" }, String(item.count))
          );
        })
      ),
      h(
        "div",
        { className: "petasos-settings-main" },
        !search && section === "basics"
          ? basics
          : h(
              Panel,
              {
                title: search ? "Matching settings" : changedView ? "Changed from default" : sectionLabel(activeTop),
                description: search
                  ? plural(shown.length, "setting") + " match."
                  : changedView
                    ? "Every setting whose value is not its default, whoever changed it."
                    : (sections[activeTop] || {}).help || "Settings that apply everywhere.",
                actions: h(Tag, null, plural(shown.length, "field")),
              },
              groups.length
                ? groups.map(function (group, index) {
                    var sub = group.section !== activeTop && group.section;
                    var info = sub ? sections[group.section] || {} : null;
                    // A section's rows can resume after a nested group, so its name alone is not a unique key.
                    return h(
                      "div",
                      { key: (group.section || "root") + ":" + index, className: "petasos-group" },
                      sub
                        ? h(
                            "div",
                            { className: "petasos-group-head" },
                            h("span", { className: "petasos-group-name" }, info.label || group.section),
                            h("span", { className: "petasos-group-rule", "aria-hidden": true })
                          )
                        : null,
                      sub && info.help ? h("p", { className: "petasos-help" }, info.help) : null,
                      group.rows.map(renderRow)
                    );
                  })
                : changedView
                  ? h(Empty, { title: "Every setting is at its default", icon: "check" })
                  : h(Empty, { title: "No settings match", icon: "search" }, "Clear the search, or show rarely needed settings."),
              !search && hidden[activeTop]
                ? h(
                    "p",
                    { className: "petasos-help petasos-end" },
                    plural(hidden[activeTop], "rarely needed setting") + " hidden. ",
                    h(Btn, { ghost: true, compact: true, onClick: function () { expertState[1](true); } }, "Show them")
                  )
                : null
            )
      )
    ),
    h(C.ConfirmDialog, {
      open: Boolean(resetPath),
      title: resetPath === "*" ? "Reset every setting you set?" : "Reset this setting?",
      description:
        resetPath === "*"
          ? "All " + plural(overrideCount, "setting") + " you set go back to what the job, the strictness or the default gives. This saves now."
          : resetRow && resetRow.reset_to
            ? rowLabel(resetRow) +
              ": " +
              (sameValue(resetRow.value, resetRow.reset_to.value)
                ? "stays " +
                  showValue(resetRow.value, resetRow) +
                  " for now, and from then on follows " +
                  originText(resetRow.reset_to.origin, stored, catalog).toLowerCase() +
                  " instead of your setting"
                : showValue(resetRow.value, resetRow) +
                  " becomes " +
                  showValue(resetRow.reset_to.value, resetRow) +
                  " (" +
                  originText(resetRow.reset_to.origin, stored, catalog).toLowerCase() +
                  ")") +
              ". This saves now. " +
              (resetRow.restart
                ? "An agent started from now on uses this. An agent already running keeps the previous value until it restarts."
                : "It applies from the agent's next tool call.")
            : "This setting goes back to what the job, the strictness or the default gives. This saves now.",
      confirmLabel: "Reset",
      cancelLabel: "Keep it",
      onCancel: function () {
        resetState[1](null);
      },
      onConfirm: function () {
        reset(resetPath);
      },
    })
  );
}
