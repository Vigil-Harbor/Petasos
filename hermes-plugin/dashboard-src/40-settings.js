// ---------------------------------------------------------------------------
// Settings: every value, laid out as Hermes's Config page lays out its own,
// with a review step before anything is saved. Rows, labels, help, bounds,
// choices and where each value comes from all come from the API.
// ---------------------------------------------------------------------------

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

// The allowed range, in words: "30 or higher", "between 1 and 8".
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

// What to say under a field the API refused. A number outside its range
// says the range; anything else is the API's own sentence.
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
  if (isMapping(row)) return Object.keys(value || {}).length ? JSON.stringify(value, null, 2) : "";
  return String(value);
}

// Turn what a person typed into the value the API expects. A number that
// does not parse is sent as text, so the API says what it needs.
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
  if (isList(row) || isMapping(row)) {
    return h("textarea", {
      id: id,
      className: "petasos-textarea petasos-mono-area",
      rows: Math.min(8, Math.max(2, String(props.text).split("\n").length + 1)),
      value: props.text,
      disabled: props.disabled,
      placeholder: isList(row) ? "One per line" : '{"name": "value"}',
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
  var provenance;
  if (props.lockedHere) {
    provenance = h("span", null, h("strong", null, "Locked by your administrator"), " · change it in Hermes's managed configuration");
  } else if (staged) {
    provenance = h(
      Fragment,
      null,
      h("strong", null, "Changed, not saved"),
      change ? " · was " + showValue(change.before, row) + " (" + originText(change.origin_before, stored, catalog).toLowerCase() + ")" : "",
      " · ",
      h(LinkButton, { onClick: props.onUnstage }, "Undo change")
    );
  } else if (saved.origin === "override") {
    var target = saved.reset_to;
    provenance = h(
      Fragment,
      null,
      "Your setting",
      target && !props.disabled
        ? h(
            Fragment,
            null,
            " · ",
            h(
              LinkButton,
              { onClick: props.onReset },
              "Reset to " + originText(target.origin, stored, catalog).toLowerCase() + ": " + showValue(target.value, row)
            )
          )
        : null
    );
  } else {
    provenance = originText(saved.origin, stored, catalog);
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
      className: cn(staged && "petasos-field-staged", props.error && "petasos-field-invalid", props.focused && "petasos-field-focused"),
      control: h(FieldControl, {
        row: row,
        value: props.value,
        text: props.text,
        error: props.error,
        disabled: props.disabled,
        onValue: props.onValue,
        onText: props.onText,
      }),
    },
    props.error ? h("p", { className: "petasos-field-error", id: id + "-error", role: "alert" }, props.error) : null,
    h(
      "p",
      { className: "petasos-provenance" },
      provenance,
      bounds ? " · allowed: " + bounds : "",
      row.restart ? " · applies after a Hermes restart" : ""
    )
  );
}

function RuleHelper(props) {
  var rule = props.rule;
  var byPath = rowsByPath(props.rows);
  var suppress = byPath["rules.suppress"] || { value: [], origin: "default" };
  var severity = byPath["rules.severity_overrides"] || { value: {}, origin: "default" };
  var quiet = (suppress.value || []).indexOf(rule) >= 0;
  var lowered = severity.value && severity.value[rule];
  var state = quiet
    ? "Turned off (" + originText(suppress.origin, props.stored, props.catalog).toLowerCase() + "). It does not block, is not recorded, and adds no risk."
    : lowered
      ? "Counts as " + lowered + " (" + originText(severity.origin, props.stored, props.catalog).toLowerCase() + ")."
      : "On, at its usual severity.";
  return h(
    Panel,
    {
      className: "petasos-rule-helper",
      title: "Rule",
      description: props.sentence || "The settings below decide what this rule does.",
      actions: h(LinkButton, { onClick: props.onClose }, "Close"),
    },
    h(KeyValues, {
      rows: [
        ["Rule id", h("span", { className: "petasos-idrow" }, h(Ident, null, rule), h(CopyButton, { value: rule, label: "Copy rule id" }))],
        ["Now", state],
      ],
    }),
    h(
      "div",
      { className: "petasos-row-actions" },
      quiet ? null : h(Btn, { outlined: true, disabled: props.disabled, onClick: function () { props.onQuiet(rule); } }, "Turn this rule off"),
      h(Btn, { outlined: true, disabled: props.disabled, onClick: function () { props.onLower(rule); } }, "Report it without blocking"),
      h(Btn, { ghost: true, onClick: function () { go("tryit", { example: "hidden" }); } }, "Try it")
    ),
    h(
      "p",
      { className: "petasos-help" },
      "Each stages a change below for you to review. Rules that check the shape of the input, or changes to Petasos itself, cannot be turned off; the review says so."
    )
  );
}

// The list of staged changes, before anything is saved.
function Review(props) {
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
    Panel,
    {
      className: "petasos-review",
      title: "Review changes",
      titleId: "petasos-review-title",
      description: "Nothing is saved until you press Save.",
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
              h("p", { className: "petasos-change-values" }, item[1], h("span", { className: "petasos-arrow", "aria-hidden": true }, " → "), h("span", { className: "sr-only" }, " becomes "), h("strong", null, item[2]))
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
      empty: top.length ? "No other setting changes." : "These edits leave every value as it was.",
    }),
    h("p", { className: "petasos-when" }, draft.enabled === false ? "Pausing applies from the agent's next tool call." : whenItApplies(changes, catalog.settings)),
    h(
      "div",
      { className: "petasos-row-actions" },
      h(Btn, { onClick: props.onSave, disabled: props.saving || props.locked }, props.saving ? "Saving…" : "Save " + plural(changes.length + top.length, "change")),
      h(Btn, { outlined: true, onClick: props.onTry }, "Try it first"),
      h(Btn, { ghost: true, onClick: props.onBack }, "Back to editing")
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
  var previewState = useState(null);
  var preview = previewState[0];
  var savingState = useState(false);
  var saveErrorState = useState(null);
  var savedState = useState(null);
  var expertState = useState(false);
  var searchState = useState("");
  var sectionState = useState(params.rule ? "rules" : params.path ? topOf({ path: params.path }) || "general" : "basics");
  var section = sectionState[0];
  var resetState = useState(null);
  var reviewState = useState(params.review === "1");
  var reviewing = reviewState[0];

  var empty = draftIsEmpty(draft);
  var draftKey = JSON.stringify(draftBody(draft));

  useEffect(
    function () {
      if (empty) {
        previewState[1](null);
        reviewState[1](false);
        return;
      }
      var live = true;
      var timer = window.setTimeout(function () {
        call("/settings/preview", { method: "POST", body: draftBody(draft) })
          .then(function (body) {
            if (live) previewState[1](body);
          })
          .catch(function (failure) {
            if (live) previewState[1]({ failure: failure, valid: false, problems: [], changes: [] });
          });
      }, 250);
      return function () {
        live = false;
        window.clearTimeout(timer);
      };
    },
    [draftKey]
  );

  // A link to one setting opens its section and brings it into view.
  useEffect(
    function () {
      if (params.path) sectionState[1](topOf({ path: params.path }) || "general");
    },
    [params.path]
  );
  useEffect(
    function () {
      if (!params.path) return;
      var target = document.getElementById("petasos-row-" + params.path);
      if (target) revealInView(target, "center");
    },
    [params.path, section, Boolean(catalog)]
  );
  useEffect(
    function () {
      if (!reviewing) return;
      var title = document.getElementById("petasos-review-title");
      if (title) {
        title.setAttribute("tabindex", "-1");
        title.focus({ preventScroll: true });
        revealInView(title, "start");
      }
    },
    [reviewing]
  );

  if (!catalog) {
    return h(Panel, { title: "Settings" }, h("p", { className: "petasos-help", role: "status" }, "Loading settings…"));
  }

  var savedRows = catalog.settings || [];
  var rows = preview && preview.settings && preview.valid ? preview.settings : savedRows;
  var savedBy = rowsByPath(savedRows);
  var changeBy = {};
  ((preview && preview.changes) || []).forEach(function (change) {
    changeBy[change.path] = change;
  });
  var problems = {};
  ((preview && preview.problems) || []).forEach(function (problem) {
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
    var next = clone(draft);
    if (value === stored[key]) delete next[key];
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
    setDraft(EMPTY_DRAFT);
    setTexts({});
    localErrorsState[1]({});
    saveErrorState[1](null);
    reviewState[1](false);
  }
  function afterWrite(body, message) {
    savedState[1]({ at: Date.now(), message: message, restart: (body && body.restart) || [] });
  }
  function save() {
    savingState[1](true);
    saveErrorState[1](null);
    call("/settings", { method: "PUT", body: draftBody(draft) })
      .then(function (body) {
        afterWrite(body, body.restart_message);
        setDraft(EMPTY_DRAFT);
        setTexts({});
        reviewState[1](false);
        props.onSaved(body);
      })
      .catch(function (failure) {
        if (failure.code === "managed") props.onLocked(failure.message);
        saveErrorState[1](failure);
        reviewState[1](false);
      })
      .finally(function () {
        savingState[1](false);
      });
  }
  function reset(path) {
    var url = path === "*" ? "/overrides" : "/overrides/" + path;
    call(url, { method: "DELETE" })
      .then(function (body) {
        afterWrite(body, (body.message || "") + " " + (body.restart_message || ""));
        props.onSaved(body.settings);
      })
      .catch(function (failure) {
        if (failure.code === "managed") props.onLocked(failure.message);
        saveErrorState[1](failure);
      })
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

  // Navigation: Basics first, then each top-level section in API order.
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

  var navItems = [{ key: "basics", label: "Basics", count: 3 }].concat(
    tops.map(function (top) {
      return { key: top || "general", label: sectionLabel(top), count: counts[top] || 0, changed: changed[top] || 0 };
    })
  );
  var activeTop = section === "basics" ? null : section === "general" ? "" : section;
  var shown = search
    ? rows.filter(visible)
    : activeTop === null
      ? []
      : rows.filter(function (row) {
          return topOf(row) === activeTop && visible(row);
        });

  // Group the shown rows by their parent section, in the order they come.
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
    return h(FieldRow, {
      key: row.path,
      catalog: catalog,
      row: row,
      saved: saved,
      staged: staged,
      change: changeBy[row.path],
      value: row.value,
      text: text,
      error: problem ? fieldProblem(row, row.path in texts ? texts[row.path] : undefined, problem) : null,
      focused: params.path === row.path || (params.rule && (row.path === "rules.suppress" || row.path === "rules.severity_overrides")),
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
      onReset: function () {
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
    }),
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
        ["Session secret", secrets.session_secret === "set" ? "Set. Activity records are signed." : "Not set. Activity records are not signed."],
        ["Hash key", secrets.hash_key === "set" ? "Set." : "Not set. Only needed to hide personal details as fingerprints."],
      ],
    }),
    h("p", { className: "petasos-help" }, "The session secret and hash key live in the profile's .env file and are never shown here."),
    overrideCount && !lockedAll
      ? h(
          "div",
          { className: "petasos-row-actions" },
          h(Btn, { outlined: true, onClick: function () { resetState[1]("*"); } }, "Reset all " + plural(overrideCount, "setting") + " you set")
        )
      : null
  );

  var changeCount = preview && preview.changes ? preview.changes.length : 0;
  var topChanges = ["enabled", "role", "level"].filter(function (key) {
    return draft[key] !== undefined && draft[key] !== stored[key];
  }).length;
  var invalid = Boolean(preview && preview.valid === false) || Object.keys(localErrorsState[0]).length > 0;
  var resetPath = resetState[0];
  var resetRow = resetPath && resetPath !== "*" ? savedBy[resetPath] : null;

  var toolbar = h(
    "div",
    { className: "petasos-settings-toolbar", role: "toolbar", "aria-label": "Settings" },
    h(
      "div",
      { className: "petasos-search" },
      h(Icon, { name: "search", className: "petasos-search-icon" }),
      h(C.Input, {
        type: "search",
        placeholder: "Search settings…",
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
      h(
        "span",
        { className: "petasos-help", role: "status" },
        empty
          ? "No unsaved changes"
          : invalid
            ? "Fix the marked setting to save"
            : preview
              ? plural(changeCount + topChanges, "unsaved change")
              : "Checking…"
      ),
      empty ? null : h(Btn, { ghost: true, onClick: discard }, "Discard"),
      empty
        ? null
        : h(
            Btn,
            {
              outlined: true,
              onClick: function () {
                go("tryit", { settings: JSON.stringify(draftBody(draft)) });
              },
            },
            "Try it first"
          ),
      h(
        Btn,
        {
          className: "uppercase",
          outlined: empty,
          disabled: empty || invalid || !preview || lockedAll,
          onClick: function () {
            reviewState[1](true);
          },
        },
        "Review and save"
      )
    )
  );

  var saved = savedState[0];

  return h(
    "div",
    { className: "petasos-stack petasos-settings" },
    toolbar,
    saved
      ? h(
          Notice,
          {
            tone: saved.restart.length ? "warning" : "success",
            title: "Saved at " + clockTime(saved.at),
            action: h(Btn, { ghost: true, onClick: function () { savedState[1](null); } }, "Dismiss"),
          },
          h("p", null, saved.message),
          saved.restart.length ? h("p", null, "Restart Gateway, in the sidebar, restarts Hermes when it suits you.") : null
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
    saveError && !saveError.path
      ? h(Notice, { tone: "destructive", title: "Not saved" }, saveError.message)
      : null,
    reviewing && preview && !invalid
      ? h(Review, {
          catalog: catalog,
          preview: preview,
          draft: draft,
          saving: savingState[0],
          locked: lockedAll,
          onSave: save,
          onTry: function () {
            go("tryit", { settings: JSON.stringify(draftBody(draft)) });
          },
          onBack: function () {
            reviewState[1](false);
          },
        })
      : null,
    params.rule
      ? h(RuleHelper, {
          catalog: catalog,
          rule: params.rule,
          rows: rows,
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
                searchState[1]("");
                sectionState[1](item.key);
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
                title: search ? "Matching settings" : sectionLabel(activeTop),
                description: search ? plural(shown.length, "setting") + " match." : (sections[activeTop] || {}).help || "Settings that apply everywhere.",
                actions: h(Tag, null, plural(shown.length, "field")),
              },
              groups.length
                ? groups.map(function (group) {
                    var sub = group.section !== activeTop && group.section;
                    var info = sub ? sections[group.section] || {} : null;
                    return h(
                      "div",
                      { key: group.section || "root", className: "petasos-group" },
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
                : h(Empty, { title: "No settings match", icon: "search" }, "Clear the search, or show rarely needed settings."),
              !search && hidden[activeTop]
                ? h(
                    "p",
                    { className: "petasos-help petasos-end" },
                    plural(hidden[activeTop], "rarely needed setting") + " hidden. ",
                    h(LinkButton, { onClick: function () { expertState[1](true); } }, "Show them")
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
              showValue(resetRow.value, resetRow) +
              " becomes " +
              showValue(resetRow.reset_to.value, resetRow) +
              " (" +
              originText(resetRow.reset_to.origin, stored, catalog).toLowerCase() +
              "). This saves now" +
              (resetRow.restart ? " and applies after a Hermes restart." : " and applies from the agent's next tool call.")
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
