// ---------------------------------------------------------------------------
// Settings: every value, where it comes from, and a staged, previewed save.
// Rows, help sentences, bounds, choices and origins all come from the API.
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

function draftIsEmpty(draft) {
  return (
    draft.enabled === undefined &&
    draft.role === undefined &&
    draft.level === undefined &&
    !Object.keys(draft.overrides || {}).length
  );
}

function draftBody(draft) {
  var body = {};
  if (draft.enabled !== undefined) body.enabled = draft.enabled;
  if (draft.role !== undefined) body.role = draft.role;
  if (draft.level !== undefined) body.level = draft.level;
  if (Object.keys(draft.overrides || {}).length) body.overrides = draft.overrides;
  return body;
}

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

function boundsText(row) {
  var b = row.bounds || {};
  var parts = [];
  if (b.ge !== null && b.ge !== undefined) parts.push("at least " + b.ge);
  if (b.gt !== null && b.gt !== undefined) parts.push("more than " + b.gt);
  if (b.le !== null && b.le !== undefined) parts.push("at most " + b.le);
  if (b.lt !== null && b.lt !== undefined) parts.push("less than " + b.lt);
  return parts.join(", ");
}

function textFor(row, value) {
  if (value === null || value === undefined) return "";
  if (isList(row)) return (value || []).join("\n");
  if (isMapping(row)) return Object.keys(value || {}).length ? JSON.stringify(value, null, 2) : "";
  return String(value);
}

// Turn what a person typed into the value the API expects. A number that
// does not parse is sent as text, so the API explains what it needs.
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
  var id = "petasos-field-" + row.path.replace(/\./g, "-");
  var disabled = props.disabled;
  if (row.type === "bool") {
    return h(
      "label",
      { className: "petasos-check", htmlFor: id },
      h(C.Checkbox, {
        id: id,
        checked: props.value === true,
        disabled: disabled,
        onCheckedChange: function (checked) {
          props.onValue(checked === true);
        },
      }),
      h("span", null, props.value === true ? "On" : "Off")
    );
  }
  if (row.choices && row.choices.length) {
    return h(
      C.Select,
      {
        id: id,
        value: String(props.value),
        disabled: disabled,
        onValueChange: function (value) {
          props.onValue(value);
        },
      },
      row.choices.map(function (choice) {
        return h(C.SelectOption, { key: String(choice), value: String(choice) }, String(choice));
      })
    );
  }
  if (isList(row) || isMapping(row)) {
    return h("textarea", {
      id: id,
      className: "petasos-textarea petasos-mono-area",
      rows: Math.min(8, Math.max(2, String(props.text).split("\n").length + 1)),
      value: props.text,
      disabled: disabled,
      placeholder: isList(row) ? "One per line" : '{"name": "value"}',
      "aria-invalid": props.error ? "true" : undefined,
      "aria-describedby": props.error ? id + "-error" : undefined,
      onChange: function (e) {
        props.onText(e.target.value);
      },
    });
  }
  return h(C.Input, {
    id: id,
    value: props.text,
    disabled: disabled,
    inputMode: isNumber(row) ? "decimal" : undefined,
    "aria-invalid": props.error ? "true" : undefined,
    "aria-describedby": props.error ? id + "-error" : undefined,
    onChange: function (e) {
      props.onText(e.target.value);
    },
  });
}

function FieldRow(props) {
  var row = props.row;
  var saved = props.saved;
  var staged = props.staged;
  var change = props.change;
  var id = "petasos-field-" + row.path.replace(/\./g, "-");
  var origin = staged ? "staged" : saved ? saved.origin : row.origin;
  var originText = staged ? "Changed here, not saved" : originLabel(origin, props.stored);
  var originTone = staged ? "warning" : origin === "override" ? "success" : origin === "default" ? "outline" : "secondary";
  var bounds = boundsText(row);
  return h(
    "div",
    {
      className: cn(
        "petasos-field",
        staged && "petasos-field-staged",
        props.error && "petasos-field-invalid",
        props.focused && "petasos-field-focused"
      ),
      id: "petasos-row-" + row.path,
    },
    h(
      "div",
      { className: "petasos-field-text" },
      h(C.Label, { className: "petasos-field-label", htmlFor: id }, fieldLabel(row.path)),
      h(Mono, { className: "petasos-path" }, row.path),
      h("p", { className: "petasos-field-help" }, row.help),
      h(
        "div",
        { className: "petasos-field-tags" },
        h(Pill, { tone: originTone, title: "Where this value comes from" }, originText),
        row.restart ? h(Pill, { tone: "outline", title: "A change takes effect after Hermes restarts" }, "Needs a restart") : null,
        row.audience === "expert" ? h(Pill, { tone: "outline" }, "Rarely needed") : null
      )
    ),
    h(
      "div",
      { className: "petasos-field-control" },
      h(FieldControl, {
        row: row,
        value: props.value,
        text: props.text,
        error: props.error,
        disabled: props.disabled,
        onValue: props.onValue,
        onText: props.onText,
      }),
      props.error
        ? h("p", { className: "petasos-field-error", id: id + "-error", role: "alert" }, props.error)
        : null,
      bounds ? h("p", { className: "petasos-help" }, "Allowed: " + bounds + ".") : null,
      change && staged
        ? h(
            "p",
            { className: "petasos-help" },
            "Was ",
            h("strong", null, showValue(change.before)),
            " (" + originLabel(change.origin_before, props.stored).toLowerCase() + ")."
          )
        : null,
      h(
        "div",
        { className: "petasos-field-actions" },
        staged
          ? h(LinkButton, { onClick: props.onUnstage }, "Undo this change")
          : null,
        !staged && saved && saved.origin === "override" && !props.disabled
          ? h(LinkButton, { onClick: props.onReset }, "Put back")
          : null
      )
    )
  );
}

function RuleHelper(props) {
  var rule = props.rule;
  var rows = props.rows;
  function value(path) {
    var found = rows.filter(function (row) {
      return row.path === path;
    })[0];
    return found ? found : { value: null, origin: "default" };
  }
  var suppress = value("rules.suppress");
  var severity = value("rules.severity_overrides");
  var quiet = (suppress.value || []).indexOf(rule) >= 0;
  var lowered = severity.value && severity.value[rule];
  var state = quiet
    ? "Quieted (" + originLabel(suppress.origin, props.stored).toLowerCase() + "). It does not block or count."
    : lowered
      ? "Its seriousness is set to " + lowered + " (" + originLabel(severity.origin, props.stored).toLowerCase() + ")."
      : "Active at its usual seriousness.";
  return h(
    Panel,
    {
      className: "petasos-rule-helper",
      title: "Settings for one rule",
      description: props.sentence || "The settings below decide what this rule does.",
      actions: h(LinkButton, { onClick: props.onClose }, "Close"),
    },
    h(KeyValues, {
      rows: [
        ["Rule", h(Mono, null, rule)],
        ["Now", state],
      ],
    }),
    h(
      "div",
      { className: "petasos-row-actions" },
      quiet
        ? null
        : h(Btn, { outlined: true, disabled: props.disabled, onClick: function () { props.onQuiet(rule); } }, "Quiet this rule"),
      h(
        Btn,
        { outlined: true, disabled: props.disabled, onClick: function () { props.onLower(rule); } },
        "Warn instead of block"
      ),
      h(
        Btn,
        {
          ghost: true,
          onClick: function () {
            go("tryit", { example: "hidden" });
          },
        },
        "Try it"
      )
    ),
    h(
      "p",
      { className: "petasos-help" },
      "Both stage a change below. Nothing is saved until you review it. Rules that check the " +
        "shape of the input cannot be quieted; the preview will say so."
    )
  );
}

function Settings(props) {
  var catalog = props.catalog;
  var params = props.route.params;
  var draftState = useState(function () {
    var seeded = { overrides: {} };
    if (params.stage) {
      try {
        var staged = JSON.parse(params.stage);
        seeded = Object.assign({ overrides: {} }, staged);
      } catch (_e) {
        seeded = { overrides: {} };
      }
    }
    return seeded;
  });
  var draft = draftState[0];
  var setDraft = draftState[1];
  var textsState = useState({});
  var texts = textsState[0];
  var setTexts = textsState[1];
  var localErrorsState = useState({});
  var previewState = useState(null);
  var preview = previewState[0];
  var savingState = useState(false);
  var saveErrorState = useState(null);
  var restartState = useState(null);
  var expertState = useState(false);
  var searchState = useState("");
  var sectionState = useState(params.rule ? "rules" : params.path ? topOf({ path: params.path }) : "basics");
  var section = sectionState[0];
  var resetState = useState(null);
  var reviewState = useState(false);
  var toast = SDK.hooks.useToast();

  var empty = draftIsEmpty(draft);
  var draftKey = JSON.stringify(draftBody(draft));

  useEffect(
    function () {
      if (empty) {
        previewState[1](null);
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

  // A link to one setting opens its section.
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
    [params.path, section]
  );

  if (!catalog) {
    return h(Panel, { title: "Settings" }, h("p", { className: "petasos-muted" }, "Loading settings…"));
  }

  var savedRows = catalog.settings || [];
  var rows = preview && preview.settings && preview.valid ? preview.settings : savedRows;
  var savedBy = {};
  savedRows.forEach(function (row) {
    savedBy[row.path] = row;
  });
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

  var locked = props.locked;
  var stored = catalog.stored || {};

  function stage(path, value) {
    var next = clone(draft);
    next.overrides = next.overrides || {};
    setIn(next.overrides, path, value);
    setDraft(next);
    saveErrorState[1](null);
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
      errors[row.path] = "This needs to be written as JSON, for example {\"name\": \"value\"}.";
    }
    localErrorsState[1](errors);
  }
  function discard() {
    setDraft({ overrides: {} });
    setTexts({});
    localErrorsState[1]({});
    saveErrorState[1](null);
    reviewState[1](false);
  }
  function save() {
    savingState[1](true);
    saveErrorState[1](null);
    call("/settings", { method: "PUT", body: draftBody(draft) })
      .then(function (body) {
        restartState[1](body.restart && body.restart.length ? body : null);
        toast.showToast(body.restart && body.restart.length ? "Saved. Restart needed." : "Saved", "success");
        setDraft({ overrides: {} });
        setTexts({});
        reviewState[1](false);
        props.onSaved(body);
      })
      .catch(function (failure) {
        if (failure.code === "managed") {
          props.onLocked(failure.message);
        }
        saveErrorState[1](failure);
      })
      .finally(function () {
        savingState[1](false);
      });
  }
  function reset(path) {
    call("/overrides/" + path, { method: "DELETE" })
      .then(function (body) {
        toast.showToast(body.cleared ? "Put back" : body.message, "success");
        if (body.restart && body.restart.length) restartState[1](body);
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
  var sectionsByPath = {};
  (catalog.sections || []).forEach(function (item) {
    sectionsByPath[item.path] = item;
  });
  var tops = [""];
  (catalog.sections || []).forEach(function (item) {
    if (item.path.indexOf(".") < 0 && tops.indexOf(item.path) < 0) tops.push(item.path);
  });
  function visible(row) {
    if (!expert && row.audience === "expert" && !hasIn(draft.overrides, row.path) && savedBy[row.path] && savedBy[row.path].origin !== "override") return false;
    if (!search) return true;
    return (row.path + " " + row.help + " " + fieldLabel(row.path)).toLowerCase().indexOf(search) >= 0;
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

  var navItems = [{ key: "basics", label: "Basics", count: 3 }].concat(
    tops.map(function (top) {
      return { key: top || "general", label: sectionLabel(top), count: counts[top] || 0, changed: changed[top] || 0, top: top };
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
    if (!last || last.section !== row.section) {
      groups.push({ section: row.section, rows: [row] });
    } else {
      last.rows.push(row);
    }
  });

  function renderRow(row) {
    var saved = savedBy[row.path];
    var staged = hasIn(draft.overrides, row.path);
    var text = row.path in texts ? texts[row.path] : textFor(row, row.value);
    return h(FieldRow, {
      key: row.path,
      row: row,
      saved: saved,
      staged: staged,
      change: changeBy[row.path],
      stored: staged ? (preview && preview.stored) || stored : stored,
      value: row.value,
      text: text,
      error: problems[row.path],
      focused: params.path === row.path || (params.rule && (row.path === "rules.suppress" || row.path === "rules.severity_overrides")),
      disabled: locked,
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

  var basics = h(
    Panel,
    {
      title: "Basics",
      description: "The three choices most people make. Everything else starts from these.",
    },
    h(
      "div",
      { className: "petasos-basics" },
      h(Choice, {
        id: "petasos-basic-enabled",
        label: "Protection",
        value: String(draft.enabled !== undefined ? draft.enabled : stored.enabled !== false),
        disabled: locked,
        options: [
          { value: "true", label: "On: check every tool call" },
          { value: "false", label: "Paused: let calls through and record them" },
        ],
        onChange: function (value) {
          stageTop("enabled", value === "true");
        },
      }),
      h(Choice, {
        id: "petasos-basic-role",
        label: "Job",
        value: draft.role || stored.role,
        disabled: locked,
        options: (catalog.roles || []).map(function (role) {
          return { value: role.name, label: jobLabel(role.name) };
        }),
        onChange: function (value) {
          stageTop("role", value);
        },
      }),
      h(Choice, {
        id: "petasos-basic-level",
        label: "Strictness",
        value: draft.level || stored.level,
        disabled: locked,
        options: (catalog.levels || []).map(function (level) {
          return { value: level.name, label: levelLabel(level.name) };
        }),
        onChange: function (value) {
          stageTop("level", value);
        },
      })
    ),
    h(KeyValues, {
      rows: [
        ["Your changes", plural(Object.keys(savedRows.filter(function (row) { return row.origin === "override"; })).length, "setting") + " differ from the job and strictness."],
        ["Session secret", catalog.secrets && catalog.secrets.session_secret === "set" ? "Set. Activity is signed." : "Not set. Activity is not signed."],
        ["Hash key", catalog.secrets && catalog.secrets.hash_key === "set" ? "Set." : "Not set."],
      ],
    }),
    h(
      "p",
      { className: "petasos-help" },
      "The session secret and hash key live in the profile's env file and are never shown here."
    ),
    savedRows.some(function (row) { return row.origin === "override"; })
      ? h(
          "div",
          { className: "petasos-row-actions" },
          h(
            Btn,
            { ghost: true, disabled: locked, onClick: function () { resetState[1]("*"); } },
            "Put back every setting I changed"
          )
        )
      : null
  );

  var changeCount = preview && preview.changes ? preview.changes.length : 0;
  var restartCount = preview && preview.changes ? preview.changes.filter(function (c) { return c.restart; }).length : 0;
  var invalid = preview && preview.valid === false;

  return h(
    "div",
    { className: "petasos-stack petasos-settings" },
    h(C.Toast, { toast: toast.toast }),
    locked
      ? h(
          Notice,
          { tone: "warning", title: "Locked by an administrator" },
          props.lockedMessage ||
            "These settings are fixed in the managed Hermes configuration. You can read them here; change them there."
        )
      : null,
    catalog.valid === false
      ? h(
          Notice,
          { tone: "destructive", title: "The saved settings have a mistake, so Petasos is not using them" },
          (catalog.problems || []).map(function (problem) {
            return h("p", { key: problem.path }, h(Mono, null, problem.path), " ", problem.message);
          })
        )
      : null,
    restartState[0]
      ? h(
          Notice,
          {
            tone: "info",
            title: "Saved. Some changes wait for a restart",
            action: h(Btn, { ghost: true, onClick: function () { restartState[1](null); } }, "Dismiss"),
          },
          "Hermes keeps the old value of these until it restarts: ",
          (restartState[0].restart || []).map(function (path, i) {
            return h(Fragment, { key: path }, i ? ", " : "", h(Mono, null, path));
          }),
          ". Use Restart Gateway in the sidebar when it suits you."
        )
      : null,
    saveError && !saveError.path && saveError.code !== "managed"
      ? h(Notice, { tone: "destructive", title: "Not saved" }, saveError.message)
      : null,
    params.rule
      ? h(RuleHelper, {
          rule: params.rule,
          rows: rows,
          stored: stored,
          sentence: params.sentence,
          disabled: locked,
          onQuiet: quietRule,
          onLower: lowerRule,
          onClose: function () {
            go("settings");
          },
        })
      : null,
    h(
      "div",
      { className: "petasos-settings-toolbar" },
      h(C.Input, {
        className: "petasos-search",
        placeholder: "Search settings…",
        "aria-label": "Search settings",
        value: searchState[0],
        onChange: function (e) {
          searchState[1](e.target.value);
        },
      }),
      h(
        "label",
        { className: "petasos-check", htmlFor: "petasos-expert" },
        h(C.Checkbox, {
          id: "petasos-expert",
          checked: expert,
          onCheckedChange: function (checked) {
            expertState[1](checked === true);
          },
        }),
        h("span", null, "Show rarely needed settings")
      )
    ),
    h(
      "div",
      { className: "petasos-settings-body" },
      h(
        "nav",
        { className: "petasos-sections", "aria-label": "Settings sections" },
        h("div", { className: "petasos-sections-title" }, "Sections"),
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
            item.changed ? h("span", { className: "petasos-section-changed", title: item.changed + " changed" }, "●", h("span", { className: "sr-only" }, item.changed + " changed")) : null,
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
                description: search ? plural(shown.length, "setting") + " match." : (sectionsByPath[activeTop] || {}).help || "Settings that apply everywhere.",
                actions: h(Pill, { tone: "outline" }, plural(shown.length, "field")),
              },
              groups.length
                ? groups.map(function (group) {
                    var sub = group.section !== activeTop && group.section;
                    return h(
                      "div",
                      { key: group.section || "root", className: "petasos-group" },
                      sub
                        ? h(
                            "div",
                            { className: "petasos-group-head" },
                            h("span", null, sectionLabel(group.section.split(".").slice(-1)[0])),
                            (sectionsByPath[group.section] || {}).help ? h("span", { className: "petasos-group-help" }, sectionsByPath[group.section].help) : null
                          )
                        : null,
                      group.rows.map(renderRow)
                    );
                  })
                : h(Empty, { title: "No settings here match" }, "Clear the search, or show rarely needed settings."),
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
    !empty
      ? h(
          "div",
          { className: cn("petasos-savebar", invalid && "petasos-savebar-invalid"), role: "region", "aria-label": "Staged changes" },
          h(
            "div",
            { className: "petasos-savebar-row" },
            h(
              "p",
              { className: "petasos-savebar-text" },
              invalid
                ? h(Fragment, null, h("strong", null, "Not valid yet. "), "Fix the marked setting before saving.")
                : preview
                  ? h(
                      Fragment,
                      null,
                      h("strong", null, plural(changeCount, "change") + " ready to save"),
                      restartCount ? " · " + restartCount + " " + (restartCount === 1 ? "needs" : "need") + " a restart" : ""
                    )
                  : "Checking…"
            ),
            h(
              "div",
              { className: "petasos-row-actions" },
              h(Btn, { ghost: true, onClick: discard }, "Discard"),
              h(
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
                  outlined: true,
                  disabled: invalid || !preview,
                  "aria-expanded": reviewState[0],
                  onClick: function () {
                    reviewState[1](!reviewState[0]);
                  },
                },
                reviewState[0] ? "Hide review" : "Review"
              ),
              h(Btn, { onClick: save, disabled: invalid || !preview || savingState[0] || locked }, savingState[0] ? "Saving…" : "Save")
            )
          ),
          reviewState[0] && preview && !invalid
            ? h(ChangeList, { rows: savedRows, changes: preview.changes || [], stored: stored, after: preview.stored, empty: "These edits leave every value as it was." })
            : null
        )
      : null,
    h(C.ConfirmDialog, {
      open: Boolean(resetState[0]),
      title: resetState[0] === "*" ? "Put back every change?" : "Put this setting back?",
      description:
        resetState[0] === "*"
          ? "Every setting you changed goes back to what the job and strictness say. This saves straight away."
          : "This setting goes back to what the job, the strictness or the default says. This saves straight away.",
      confirmLabel: "Put back",
      cancelLabel: "Keep it",
      onCancel: function () {
        resetState[1](null);
      },
      onConfirm: function () {
        if (resetState[0] === "*") {
          call("/overrides", { method: "DELETE" })
            .then(function (body) {
              toast.showToast("Put back", "success");
              props.onSaved(body.settings);
            })
            .catch(function (failure) {
              if (failure.code === "managed") props.onLocked(failure.message);
              saveErrorState[1](failure);
            })
            .finally(function () {
              resetState[1](null);
            });
        } else {
          reset(resetState[0]);
        }
      },
    })
  );
}
