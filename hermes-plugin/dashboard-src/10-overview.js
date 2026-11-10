// ---------------------------------------------------------------------------
// Overview: is it working and what it covers, the two choices right beneath
// in the same panel, then what happened lately, the checks, and who can
// change the settings.
// ---------------------------------------------------------------------------

// A check's state is the API's ``operating`` value: whether it is checking
// the agent's actions now. The tone follows the code; the word is the API's.
var OPERATING_TONE = {
  running: "success",
  checked: "success",
  paused: "warning",
  failed: "destructive",
  stopped: "destructive",
  not_installed: "neutral",
  off: "neutral",
  skipped: "neutral",
};

function CheckState(props) {
  var operating = props.operating || {};
  var code = operating.code || "off";
  return h(Status, { tone: OPERATING_TONE[code] || "neutral", state: code }, operating.label || code);
}

function sentenceCase(text) {
  var value = String(text || "");
  return value ? value.charAt(0).toUpperCase() + value.slice(1) : "";
}

// "a, b and c"
function joinWords(words) {
  var list = words.filter(Boolean);
  if (list.length <= 1) return list.join("");
  return list.slice(0, -1).join(", ") + " and " + list[list.length - 1];
}

function heldChecks(status) {
  var coverage = status.coverage || { missing: [] };
  return (coverage.missing || []).filter(function (row) {
    return row.held;
  });
}

// The one verdict a person reads first. Protection is on or off; coverage
// says what is running and what is not, so "on" never reads as complete.
function verdictOf(status) {
  var switches = status.switches || {};
  var doctor = status.doctor || {};
  var checks = doctor.checks || [];
  var coverage = status.coverage || { running: [], missing: [], complete: false };
  if (switches.hermes && switches.hermes.on === false) {
    return {
      code: "off",
      tone: "destructive",
      word: "Not protected",
      title: "Hermes is not running Petasos",
      reason: switches.hermes.detail + " No action is being checked.",
      step: { label: "Open Plugins", href: "/plugins" },
    };
  }
  if (switches.hermes && switches.hermes.on === null) {
    return {
      code: "unknown",
      tone: "warning",
      word: "Unknown",
      title: "Petasos cannot tell whether Hermes is running it",
      reason: switches.hermes.detail,
    };
  }
  if (status.settings && status.settings.valid === false) {
    var error = status.settings.error || {};
    return {
      code: "invalid",
      tone: "destructive",
      word: "Not protected",
      title: "The saved settings have a mistake",
      reason: "Petasos cannot use settings it does not understand." + (error.message ? " " + error.message : ""),
      step: { label: "Fix it in Settings", view: "settings" },
    };
  }
  if (status.paused || (switches.petasos && switches.petasos.on === false)) {
    return {
      code: "paused",
      tone: "warning",
      word: "Paused",
      title: "Protection is paused",
      reason: "Actions run unchecked. Each one is recorded in Activity.",
    };
  }
  var failed = checks.filter(function (check) {
    return check.status === "fail";
  })[0];
  if (doctor.verdict === "not_protected" && failed) {
    return {
      code: "not_protected",
      tone: "destructive",
      word: "Not protected",
      title: failed.summary,
      reason: failed.meaning,
      stepText: failed.next_step,
    };
  }
  // A required check that cannot run: what that does to tool calls is the
  // API's sentence, computed from the settings that decide it.
  var held = heldChecks(status);
  if (held.length) {
    var first = held[0];
    var consequence = first.consequence || {};
    var check = checks.filter(function (item) {
      return item.id === "scanner_" + first.id;
    })[0];
    return {
      code: "held",
      tone: "destructive",
      word: "Check failed",
      title: consequence.title || (check && check.summary) || (first.name || first.label) + " cannot run",
      reason: (check && check.summary ? check.summary + " " : "") + (consequence.sentence || ""),
      held: first,
    };
  }
  var warned = checks.filter(function (check) {
    return check.status === "warn";
  })[0];
  var running = coverage.running.length;
  var title;
  if (coverage.complete) title = "Every check is running";
  else if (running <= 1) title = "Basic checks are running";
  else title = plural(running, "check is", "checks are") + " running";
  if (doctor.verdict === "protected_with_warnings" && warned) {
    return {
      code: "warn",
      tone: "warning",
      word: "On, with a problem",
      title: warned.summary,
      reason: warned.meaning,
      stepText: warned.next_step,
    };
  }
  return {
    code: "protected",
    tone: "success",
    word: "On",
    title: title,
    reason: "",
  };
}

// What "on" covers, what runs and what does not, as compact rows. Checks are
// named by what they do, with the product after it.
function CoverageRows(props) {
  var status = props.status;
  var coverage = status.coverage || { running: [], missing: [] };
  var paused = props.paused;
  function named(row) {
    return row.name || row.label;
  }
  var running = coverage.running.map(named);
  var missing = coverage.missing
    .filter(function (row) {
      return !row.held;
    })
    .map(named);
  var rows = [];
  if (!paused && status.scope) rows.push(["Covers", status.scope]);
  if (paused) {
    rows.push([
      "Paused",
      h(
        "span",
        null,
        running.length ? joinWords(running) : "Every check",
        h("span", { className: "petasos-secondary" }, ". They resume when protection is turned back on.")
      ),
    ]);
  } else {
    rows.push(["Running", running.length ? joinWords(running) : "Nothing"]);
    rows.push([
      "Not running",
      missing.length
        ? h(
            "span",
            null,
            joinWords(missing),
            " · ",
            h(LinkButton, { onClick: props.onShowChecks }, "What these add")
          )
        : coverage.missing.length
          ? "Only the check above."
          : "Nothing. Every check is running.",
    ]);
  }
  return h(KeyValues, { className: "petasos-coverage", rows: rows });
}

// How to fix a required check that cannot run: where to run the command,
// the command to copy, or turn it off in Settings.
function HeldFix(props) {
  var row = props.row;
  var coverage = props.status.coverage || {};
  var name = row.name || row.label;
  return h(
    "div",
    { className: "petasos-fixbox" },
    row.command
      ? h(
          Fragment,
          null,
          h("p", null, h("strong", null, "To add it: "), coverage.add_where),
          h(Command, { value: row.command, label: "Copy the command that adds " + row.label })
        )
      : row.reason
        ? h("p", null, row.reason)
        : null,
    h(
      "p",
      null,
      row.command ? "Or " : "",
      h(
        LinkButton,
        {
          onClick: function () {
            go("settings", { path: "scanners." + row.id + ".enabled" });
          },
        },
        (row.command ? "turn it off in Settings" : "Turn " + name + " off in Settings")
      ),
      "."
    )
  );
}

// The status, built like every Hermes panel: its title with the state badge
// in the header, the action at the header's end, then compact rows: the
// state in one sentence, what "on" covers, what runs, and the two choices.
function VerdictPanel(props) {
  var status = props.status;
  var verdict = verdictOf(status);
  var paused = verdict.code === "paused";
  var canPause = verdict.code === "protected" || verdict.code === "warn" || verdict.code === "held";
  var action = null;
  if (paused) {
    action = h(Btn, { onClick: props.onResume, disabled: props.locked }, "Resume protection");
  } else if (canPause) {
    action = h(Btn, { outlined: true, onClick: props.onPause, disabled: props.locked }, "Pause protection");
  } else if (verdict.step && verdict.step.href) {
    action = h("a", { className: "petasos-link", href: verdict.step.href }, verdict.step.label);
  } else if (verdict.step && verdict.step.view) {
    action = h(Btn, { onClick: function () { go(verdict.step.view); } }, verdict.step.label);
  }
  var showCoverage = verdict.code !== "off" && verdict.code !== "invalid";
  return h(
    Panel,
    {
      className: cn("petasos-verdict", "petasos-verdict-" + verdict.code),
      title: "Protection",
      titleId: "petasos-verdict-label",
      badge: h(Status, { tone: verdict.tone, state: verdict.code }, verdict.word),
      actions: action,
    },
    h("p", { className: "petasos-verdict-title", id: "petasos-verdict-title" }, verdict.title),
    verdict.reason ? h("p", { className: "petasos-verdict-reason" }, verdict.reason) : null,
    verdict.stepText ? h("p", { className: "petasos-verdict-reason" }, h("strong", null, "Next step: "), verdict.stepText) : null,
    verdict.held ? h(HeldFix, { row: verdict.held, status: status }) : null,
    showCoverage ? h(CoverageRows, { status: status, paused: paused, onShowChecks: props.onShowChecks }) : null,
    props.children
  );
}

// One of the two choices, compact: the label, Hermes's segmented control,
// the selected option's one-line description, and every option's
// description one click away.
function ChoiceControl(props) {
  var id = "petasos-choose-" + props.name;
  var selected = props.options.filter(function (option) {
    return option.name === props.chosen;
  })[0];
  var saved = props.options.filter(function (option) {
    return option.name === props.current;
  })[0];
  return h(
    "div",
    { className: "petasos-choose", id: id + "-field" },
    h("p", { className: "petasos-label", id: id + "-label" }, props.label),
    h(Segmented, {
      id: id,
      labelledBy: id + "-label",
      describedBy: id + "-desc",
      value: props.chosen,
      disabled: props.locked,
      onChange: props.onChoose,
      options: props.options.map(function (option) {
        return { value: option.name, label: option.label };
      }),
    }),
    h(
      "p",
      { className: "petasos-choose-desc", id: id + "-desc" },
      selected ? selected.description : "",
      props.chosen !== props.current && saved
        ? h("span", { className: "petasos-secondary" }, " Saved: " + saved.label + ".")
        : null
    ),
    h(
      Disclosure,
      { label: props.allLabel, openLabel: "Hide " + props.allLabel.charAt(0).toLowerCase() + props.allLabel.slice(1) },
      h(
        "ul",
        { className: "petasos-optlist", "aria-label": props.label + ": what each option does" },
        props.options.map(function (option) {
          return h(
            "li",
            { key: option.name, className: cn("petasos-opt", option.name === props.chosen && "petasos-opt-on") },
            h("span", { className: "petasos-opt-name" }, option.label),
            h(
              "span",
              { className: "petasos-opt-desc" },
              option.description,
              option.name === props.current ? h("span", { className: "petasos-opt-note" }, " Saved.") : null,
              option.suggested ? h("span", { className: "petasos-opt-note" }, " Usual for " + option.suggested + ".") : null
            )
          );
        })
      )
    )
  );
}

function SetupControls(props) {
  var catalog = props.catalog;
  var status = props.status;
  var stored = catalog.stored || {};
  var currentRole = stored.role || status.role;
  var currentLevel = stored.level || status.level;
  var pendingState = useState(null);
  var pending = pendingState[0];
  var setPending = pendingState[1];
  var previewState = useState(null);
  var previewed = previewState[0];
  var busyState = useState(false);
  var locked = catalog.locked || {};
  var roleLocked = props.locked || (locked.stored || []).indexOf("role") >= 0;
  var levelLocked = props.locked || (locked.stored || []).indexOf("level") >= 0;

  var chosenRole = pending && pending.role ? pending.role : currentRole;
  var chosenLevel = pending && pending.level ? pending.level : currentLevel;
  var roleInfo = roleOf(catalog, chosenRole);

  useEffect(
    function () {
      if (!pending) {
        previewState[1](null);
        return;
      }
      var live = true;
      previewState[1](null);
      call("/settings/preview", { method: "POST", body: pending })
        .then(function (body) {
          if (live) previewState[1](body);
        })
        .catch(function (failure) {
          if (live) previewState[1]({ failure: failure });
        });
      return function () {
        live = false;
      };
    },
    [JSON.stringify(pending)]
  );

  function choose(kind, name) {
    var next = Object.assign({}, pending || {});
    var current = kind === "role" ? currentRole : currentLevel;
    if (name === current) delete next[kind];
    else next[kind] = name;
    setPending(Object.keys(next).length ? next : null);
  }

  function apply(extra) {
    busyState[1](true);
    props
      .onSave(Object.assign({}, pending, extra || {}))
      .then(function () {
        setPending(null);
      })
      .catch(function () {})
      .finally(function () {
        busyState[1](false);
      });
  }

  var roles = (catalog.roles || []).map(function (role) {
    return { name: role.name, label: role.label || role.name, description: role.description };
  });
  var levels = (catalog.levels || []).map(function (level) {
    return {
      name: level.name,
      label: level.label || level.name,
      description: level.description,
      suggested: roleInfo && roleInfo.suggests === level.name ? roleLabel(catalog, chosenRole) : null,
    };
  });
  var labels = catalog.labels || {};

  return h(
    "div",
    { className: "petasos-setup", id: "petasos-setup", role: "group", "aria-label": "Setup" },
    roleLocked || levelLocked ? h("p", { className: "petasos-secondary" }, "Locked by your administrator.") : null,
    h(
      "div",
      { className: "petasos-setup-grid" },
      h(ChoiceControl, {
        name: "job",
        label: labels.role || "Job",
        allLabel: "What each job does",
        options: roles,
        chosen: chosenRole,
        current: currentRole,
        locked: roleLocked,
        onChoose: function (name) {
          choose("role", name);
        },
      }),
      h(ChoiceControl, {
        name: "level",
        label: labels.level || "Strictness",
        allLabel: "What each strictness does",
        options: levels,
        chosen: chosenLevel,
        current: currentLevel,
        locked: levelLocked,
        onChoose: function (name) {
          choose("level", name);
        },
      })
    ),
    pending
      ? h(ChoicePreview, {
          catalog: catalog,
          pending: pending,
          previewed: previewed,
          stored: stored,
          roleInfo: roleInfo,
          currentLevel: currentLevel,
          busy: busyState[0],
          onApply: function () {
            apply();
          },
          onApplyWith: function (level) {
            apply({ level: level });
          },
          onCancel: function () {
            setPending(null);
          },
        })
      : null
  );
}

// The pending change, on its own inset surface: when it applies, the usual
// pairing stated as a trade with a button that names the combination, then
// Apply.
function ChoicePreview(props) {
  var catalog = props.catalog;
  var pending = props.pending;
  var previewed = props.previewed;
  var parts = [];
  if (pending.role) parts.push("job to " + roleLabel(catalog, pending.role));
  if (pending.level) parts.push("strictness to " + levelLabel(catalog, pending.level));
  var suggestion =
    pending.role && props.roleInfo && props.roleInfo.suggests !== (pending.level || props.currentLevel)
      ? props.roleInfo.suggests
      : null;
  var changes = previewed && previewed.changes ? previewed.changes : [];
  var body;
  if (!previewed) {
    body = h("p", { className: "petasos-secondary", role: "status" }, "Working out what would change…");
  } else if (previewed.failure) {
    body = h(Notice, { tone: "destructive", title: "Petasos could not preview this" }, previewed.failure.message);
  } else if (!previewed.valid) {
    body = h(
      Notice,
      { tone: "destructive", title: "This combination is not valid" },
      (previewed.problems || []).map(function (problem) {
        return h("p", { key: problem.path }, problem.message);
      })
    );
  } else {
    body = h(
      Fragment,
      null,
      h("p", { className: "petasos-when" }, whenItApplies(changes, catalog.settings)),
      h(
        Disclosure,
        { label: "Show the settings this changes (" + changes.length + ")", openLabel: "Hide the settings this changes" },
        h(ChangeList, {
          catalog: catalog,
          rows: catalog.settings,
          changes: changes,
          stored: props.stored,
          after: previewed.stored,
          empty: "No setting would change: your own settings already cover this.",
        })
      )
    );
  }
  var candidate = JSON.stringify(pending);
  var suggestedLevel = suggestion ? levelOf(catalog, suggestion) : null;
  return h(
    "section",
    { className: "petasos-preview", "aria-labelledby": "petasos-preview-title" },
    h("h3", { className: "petasos-preview-title", id: "petasos-preview-title" }, sentenceCase("Change the " + parts.join(" and ")) + "?"),
    body,
    suggestion
      ? h(
          "p",
          { className: "petasos-preview-text" },
          h("strong", null, levelLabel(catalog, suggestion) + " strictness: "),
          suggestedLevel && suggestedLevel.description ? suggestedLevel.description : ""
        )
      : null,
    h(
      "div",
      { className: "petasos-row-actions" },
      h(
        Btn,
        {
          onClick: props.onApply,
          disabled: props.busy || !previewed || Boolean(previewed.failure) || !previewed.valid,
        },
        props.busy ? "Applying…" : "Apply"
      ),
      suggestion
        ? h(
            Btn,
            {
              outlined: true,
              onClick: function () {
                props.onApplyWith(suggestion);
              },
              disabled: props.busy || !previewed || Boolean(previewed.failure) || !previewed.valid,
            },
            "Apply " + roleLabel(catalog, pending.role) + " with " + levelLabel(catalog, suggestion)
          )
        : null,
      h(
        Btn,
        {
          outlined: true,
          onClick: function () {
            go("tryit", { settings: candidate });
          },
        },
        "Try it first"
      ),
      h(Btn, { ghost: true, onClick: props.onCancel }, "Cancel")
    )
  );
}

var STAT_TILES = [
  { key: "blocked", label: "Blocked" },
  { key: "asked", label: "Asked a person" },
  { key: "flagged", label: "Flagged to the agent" },
  { key: "allowed", label: "Let through while paused" },
  { key: "not_stopped", label: "Setting changes not stopped", alarm: true },
];

// The figures, as Hermes's System page lays them out: a small label above,
// the value beneath at a size that reads as the value. Each figure is a
// grid cell whose value sits on the cell's last row, so values stay on one
// line when a label wraps.
function RecentPanel(props) {
  var summary = props.summary;
  var events = props.events || [];
  var counts = (summary && summary.by_outcome) || {};
  var values = {
    blocked: summary ? summary.blocked || 0 : 0,
    asked: (counts.asked || 0) + (counts.attempt_asked || 0),
    flagged: counts.flagged || 0,
    allowed: counts.allowed || 0,
    not_stopped: counts.not_stopped || 0,
  };
  var tiles = STAT_TILES.filter(function (tile) {
    return !tile.alarm || values[tile.key];
  });
  var groups = groupEvents(events).slice(0, 4);
  return h(
    Panel,
    {
      title: "Last 24 hours",
      description: summary
        ? summary.total
          ? plural(summary.total, "event") + ". Clean actions are not listed."
          : "Nothing to report. Clean actions are not listed."
        : "Loading…",
      actions: h(LinkButton, { onClick: function () { go("activity"); } }, "Open Activity"),
    },
    h(
      "dl",
      { className: "petasos-stats" },
      tiles.map(function (tile) {
        var value = values[tile.key];
        return h(
          "div",
          { key: tile.key, className: cn("petasos-stat", tile.alarm && "petasos-stat-alarm") },
          h("dt", null, tile.label),
          h(
            "dd",
            null,
            h(
              "button",
              {
                type: "button",
                className: "petasos-stat-value",
                title: "Show them in Activity",
                "aria-label": value + " " + tile.label + ": show them in Activity",
                onClick: function () {
                  go("activity", { range: "24h", outcome: tile.key });
                },
              },
              String(value)
            )
          )
        );
      })
    ),
    values.not_stopped
      ? h(
          "div",
          { className: "petasos-alarm-row", role: "status" },
          h(
            "p",
            null,
            h(
              "strong",
              null,
              values.not_stopped === 1
                ? "1 attempt to change settings was not stopped. "
                : values.not_stopped + " attempts to change settings were not stopped. "
            ),
            "The record cannot show whether a change took effect."
          ),
          h(
            Btn,
            {
              outlined: true,
              onClick: function () {
                go("settings", { changed: "1" });
              },
            },
            "Show changed settings"
          )
        )
      : null,
    groups.length
      ? h(
          "ul",
          { className: "petasos-mini-list", "aria-label": "Most recent events" },
          groups.map(function (group) {
            var event = group.events[0];
            var outcome = event.outcome || {};
            return h(
              "li",
              { key: event.scan_id },
              h(
                "button",
                {
                  type: "button",
                  className: "petasos-mini-row",
                  onClick: function () {
                    go("activity", { event: event.scan_id });
                  },
                },
                h("span", { className: "petasos-mini-when" }, whenText(event.timestamp)),
                h(
                  "span",
                  { className: "petasos-mini-text" },
                  event.summary,
                  group.events.length > 1 ? h("span", { className: "petasos-repeat" }, " ×" + group.events.length) : null
                ),
                h(Status, { tone: outcomeTone(outcome.code), state: outcome.code }, outcome.label || "Recorded"),
                h(Icon, { name: "chevron", className: "petasos-chevron" })
              )
            );
          })
        )
      : null
  );
}

// Each check by what it does, its product beneath, and its state now: the
// API's operating value, the same one every view draws.
function ChecksPanel(props) {
  var status = props.status;
  var checks = (status.doctor && status.doctor.checks) || [];
  var coverage = status.coverage || { running: [], missing: [] };
  var byId = {};
  coverage.running.concat(coverage.missing).forEach(function (row) {
    byId[row.id] = row;
  });
  return h(
    Panel,
    {
      id: "petasos-checks",
      title: "Checks",
      description: status.checks_note,
    },
    h(
      "ul",
      { className: "petasos-scanners" },
      (status.scanners || []).map(function (row) {
        var id = row.id === "syntactic" ? "scanner_builtin" : "scanner_" + row.id;
        var check = checks.filter(function (item) {
          return item.id === id;
        })[0];
        var info = byId[row.id] || {};
        var basic = row.id === "syntactic";
        var name = basic ? row.label : row.purpose || sentenceCase(info.covers || row.label);
        var product = basic ? info.covers : row.label;
        var fixable = (info.recommended || info.held) && (info.command || row.fix);
        return h(
          "li",
          { key: row.id, className: "petasos-scanner" },
          h(
            "div",
            { className: "petasos-scanner-head" },
            h(
              "span",
              { className: "petasos-scanner-name" },
              name,
              product ? h("span", { className: "petasos-scanner-product" }, product) : null
            ),
            info.recommended ? h(Tag, { tone: "outline" }, "recommended") : null,
            h(CheckState, { operating: row.operating })
          ),
          !basic && check ? h("p", { className: "petasos-secondary" }, check.summary) : null,
          fixable
            ? h(
                Disclosure,
                { label: "How to add it", openLabel: "Hide how to add it" },
                info.command
                  ? h(
                      Fragment,
                      null,
                      h("p", null, coverage.add_where),
                      h(Command, { value: info.command, label: "Copy the command that adds " + row.label })
                    )
                  : h("p", null, row.fix)
              )
            : null
        );
      })
    )
  );
}

function WhoPanel(props) {
  var who = props.status.who_can_change || {};
  var locked = (props.catalog && props.catalog.locked) || { known: false };
  var labels = (props.catalog && props.catalog.labels) || {};
  var byPath = rowsByPath(props.catalog && props.catalog.settings);
  var pinned = (locked.stored || [])
    .map(function (key) {
      return labels[key] || key;
    })
    .concat(
      (locked.settings || []).map(function (path) {
        return rowLabel(byPath[path] || { path: path });
      })
    );
  var admin;
  if (!locked.known) admin = "This Hermes does not say which settings are locked.";
  else if (pinned.length) admin = "Has locked: " + pinned.join(", ") + ". Change them in Hermes's managed configuration.";
  else admin = "Nothing is locked.";
  if (locked.plugin) admin += " Hermes's plugin list is locked too.";
  return h(
    Panel,
    { title: "Who can change these settings", description: "An agent should not be able to switch off its own guardrails." },
    h(KeyValues, {
      rows: [
        ["The agent", who.agent],
        ["You", who.you],
        ["Administrator", admin],
        ["Two switches", who.switches],
      ],
    })
  );
}

function Overview(props) {
  var status = props.status;
  var catalog = props.catalog;
  var summaryState = useState(null);
  var eventsState = useState([]);
  usePoll(
    function () {
      var since = Math.floor(Date.now() / 1000) - 86400;
      call("/activity/summary" + query({ since: since }))
        .then(summaryState[1])
        .catch(function () {});
      call("/activity" + query({ limit: 20, since: since }))
        .then(function (body) {
          eventsState[1](body.events || []);
        })
        .catch(function () {});
    },
    30000,
    [props.refreshKey]
  );
  function reveal(id) {
    return function () {
      var target = document.getElementById(id);
      if (!target) return;
      revealInView(target, "start");
      var focusable = target.querySelector("[role=radio][tabindex='0'], button, a");
      if (focusable) focusable.focus({ preventScroll: true });
    };
  }
  var verdict = verdictOf(status);
  var setup = verdict.code === "off" || verdict.code === "invalid"
    ? null
    : catalog
      ? h(SetupControls, { catalog: catalog, status: status, locked: props.locked, onSave: props.onSave })
      : h("p", { className: "petasos-secondary petasos-setup", role: "status" }, "Loading the choices…");
  return h(
    "div",
    { className: "petasos-stack" },
    h(
      VerdictPanel,
      {
        status: status,
        catalog: catalog,
        locked: props.locked,
        onPause: props.onPause,
        onResume: props.onResume,
        onShowChecks: reveal("petasos-checks"),
      },
      setup
    ),
    h(RecentPanel, { summary: summaryState[0], events: eventsState[0] }),
    h(
      "div",
      { className: "petasos-grid-2" },
      h(ChecksPanel, { status: status }),
      h(WhoPanel, { status: status, catalog: catalog })
    )
  );
}
