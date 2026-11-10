// ---------------------------------------------------------------------------
// Overview: is it working (and what is it covering), what happened lately,
// then the two choices: job and strictness.
// ---------------------------------------------------------------------------

var STATE_WORDS = {
  active: { tone: "success", word: "Running" },
  not_installed: { tone: "neutral", word: "Not installed" },
  off: { tone: "neutral", word: "Off" },
  unavailable: { tone: "destructive", word: "Not working" },
};

function stateWord(state) {
  return (STATE_WORDS[state] || { word: state }).word.toLowerCase();
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
      reason: switches.hermes.detail + " No tool call is being checked.",
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
  if (switches.petasos && switches.petasos.on === false) {
    return {
      code: "paused",
      tone: "warning",
      word: "Paused",
      title: "Protection is paused",
      reason: "Tool calls go through without being checked. Each one is still recorded in Activity.",
      step: { label: "Resume protection", resume: true },
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
  var warned = checks.filter(function (check) {
    return check.status === "warn";
  })[0];
  var missing = coverage.missing.length;
  var title;
  if (coverage.complete) title = "Every check is running";
  else if (coverage.running.length <= 1)
    title = "Only the basic checks are running. " + plural(missing, "optional check is", "optional checks are") + " not.";
  else title = plural(coverage.running.length, "check is", "checks are") + " running. " + plural(missing, "is", "are") + " not.";
  if (doctor.verdict === "protected_with_warnings" && warned) {
    return {
      code: "warn",
      tone: "warning",
      word: "On, with a problem",
      title: warned.summary,
      reason: warned.meaning,
      stepText: warned.next_step,
      coverageTitle: title,
    };
  }
  return {
    code: "protected",
    tone: "success",
    word: "Protection on",
    title: title,
    reason:
      "Petasos checks each tool call before it runs and each tool result before the agent reads it, " +
      "using the checks that are running.",
  };
}

function CoverageRows(props) {
  var coverage = props.status.coverage || { running: [], missing: [] };
  var catalog = props.catalog;
  var stored = (catalog && catalog.stored) || {};
  return h(KeyValues, {
    className: "petasos-coverage",
    rows: [
      [
        "Running",
        coverage.running.length
          ? coverage.running
              .map(function (row) {
                return row.label;
              })
              .join(", ")
          : "Nothing",
      ],
      [
        "Not running",
        coverage.missing.length
          ? h(
              "span",
              null,
              coverage.missing.map(function (row, i) {
                return h(
                  Fragment,
                  { key: row.id },
                  i ? ", " : "",
                  h("span", { className: row.recommended ? "petasos-strong" : null }, row.label),
                  " (" + stateWord(row.state) + (row.recommended ? ", recommended" : "") + ")"
                );
              }),
              " · ",
              h(LinkButton, { onClick: props.onShowChecks }, "What they add")
            )
          : "Nothing. Every check is running.",
      ],
      [
        "Setup",
        h(
          "span",
          null,
          "Job ",
          h("strong", null, roleLabel(catalog, stored.role || props.status.role)),
          " · Strictness ",
          h("strong", null, levelLabel(catalog, stored.level || props.status.level)),
          " · ",
          h(LinkButton, { onClick: props.onShowSetup }, "Change")
        ),
      ],
    ],
  });
}

function VerdictPanel(props) {
  var status = props.status;
  var verdict = verdictOf(status);
  var paused = verdict.code === "paused";
  var canPause = verdict.code === "protected" || verdict.code === "warn";
  var step = null;
  if (verdict.step && verdict.step.resume) {
    step = h(Btn, { onClick: props.onResume, disabled: props.locked }, verdict.step.label);
  } else if (verdict.step && verdict.step.href) {
    step = h("a", { className: "petasos-link", href: verdict.step.href }, verdict.step.label);
  } else if (verdict.step && verdict.step.view) {
    step = h(Btn, { onClick: function () { go(verdict.step.view); } }, verdict.step.label);
  }
  return h(
    "section",
    { className: "petasos-verdict", "aria-labelledby": "petasos-verdict-title" },
    h(
      "div",
      { className: "petasos-verdict-main" },
      h(
        "div",
        { className: "petasos-verdict-head" },
        h(Status, { tone: verdict.tone, large: true }, verdict.word),
        h("h2", { id: "petasos-verdict-title", className: "petasos-verdict-title" }, verdict.title)
      ),
      verdict.coverageTitle ? h("p", { className: "petasos-verdict-reason" }, verdict.coverageTitle) : null,
      verdict.reason ? h("p", { className: "petasos-verdict-reason" }, verdict.reason) : null,
      verdict.stepText ? h("p", { className: "petasos-verdict-reason" }, h("strong", null, "Next step: "), verdict.stepText) : null,
      step ? h("div", { className: "petasos-row-actions" }, step) : null,
      verdict.code === "off" || verdict.code === "invalid" ? null : h(CoverageRows, props)
    ),
    canPause || paused
      ? h(
          "div",
          { className: "petasos-verdict-side" },
          paused
            ? null
            : h(Btn, { outlined: true, onClick: props.onPause, disabled: props.locked }, "Pause protection"),
          h(
            "p",
            { className: "petasos-help" },
            paused
              ? "Paused in Petasos. Hermes still runs the plugin."
              : "Lets tool calls through unchecked until you resume, and records each one."
          )
        )
      : null
  );
}

function RecentPanel(props) {
  var summary = props.summary;
  var events = props.events || [];
  var counts = (summary && summary.by_outcome) || {};
  var tiles = [
    { key: "blocked", label: "Blocked", value: (counts.blocked || 0) + (counts.stopped || 0) },
    { key: "asked", label: "Asked a person", value: counts.asked || 0 },
    { key: "flagged", label: "Flagged to the agent", value: counts.flagged || 0 },
    { key: "allowed", label: "Let through while paused", value: counts.allowed || 0 },
  ];
  if (counts.not_stopped) {
    tiles.push({ key: "not_stopped", label: "Settings changes not stopped", value: counts.not_stopped, alarm: true });
  }
  var groups = groupEvents(events).slice(0, 4);
  return h(
    Panel,
    {
      title: "Last 24 hours",
      description: summary
        ? summary.total
          ? plural(summary.total, "event") + ". Tool calls that pass cleanly are not listed."
          : "Nothing to report. Tool calls that pass cleanly are not listed."
        : "Loading…",
      actions: h(LinkButton, { onClick: function () { go("activity"); } }, "Open Activity"),
    },
    h(
      "dl",
      { className: "petasos-stats" },
      tiles.map(function (tile) {
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
                "aria-label": tile.value + " " + tile.label + ": show them in Activity",
                onClick: function () {
                  go("activity", { range: "24h", outcome: tile.key });
                },
              },
              String(tile.value)
            )
          )
        );
      })
    ),
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
                h(Status, { tone: outcomeTone(outcome.code) }, outcome.label || "Recorded"),
                h(Icon, { name: "chevron", className: "petasos-chevron" })
              )
            );
          })
        )
      : null
  );
}

// One of the two choices: Hermes's segmented control under the label, the
// setting's key and its plain sentence, as Config draws a field.
function ChoiceHead(props) {
  var id = "petasos-choose-" + props.name;
  return h(
    "div",
    { className: "petasos-choose", id: id + "-field" },
    h("p", { className: "petasos-field-label", id: id + "-label" }, props.label),
    h("span", { className: "petasos-field-key" }, props.name === "job" ? "role" : "level"),
    h("p", { className: "petasos-field-help" }, props.help),
    h(Segmented, {
      id: id,
      labelledBy: id + "-label",
      value: props.chosen,
      disabled: props.locked,
      onChange: props.onChoose,
      options: props.options.map(function (option) {
        return { value: option.name, label: option.label };
      }),
    })
  );
}

// Every option's plain description, so none has to be chosen to be read.
function ChoiceOptions(props) {
  return h(
    "ul",
    { className: "petasos-optlist", "aria-label": props.label + ": what each option does" },
    props.options.map(function (option) {
      var chosen = option.name === props.chosen;
      var current = option.name === props.current;
      return h(
        "li",
        { key: option.name, className: cn("petasos-opt", chosen && "petasos-opt-on") },
        h("span", { className: "petasos-opt-name" }, option.label),
        h(
          "span",
          { className: "petasos-opt-desc" },
          option.description,
          current ? h("span", { className: "petasos-opt-note" }, " · saved") : null,
          option.suggested ? h("span", { className: "petasos-opt-note" }, " · suggested for " + option.suggested) : null
        )
      );
    })
  );
}

function SetupPanel(props) {
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

  function apply() {
    busyState[1](true);
    props
      .onSave(pending)
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
  var help = catalog.help || {};
  var labels = catalog.labels || {};

  return h(
    Panel,
    {
      id: "petasos-setup",
      title: "Setup",
      description: "Two choices decide how Petasos behaves. Nothing changes until you apply it.",
      actions: roleLocked || levelLocked ? h(Tag, { tone: "outline" }, "Locked by your administrator") : null,
    },
    // Both controls first, then both lists: in the narrow layout the two
    // choices stay together at the top of the panel.
    h(
      "div",
      { className: "petasos-grid-2 petasos-setup" },
      h(ChoiceHead, {
        name: "job",
        label: labels.role || "Job",
        help: help.role,
        options: roles,
        chosen: chosenRole,
        locked: roleLocked,
        onChoose: function (name) {
          choose("role", name);
        },
      }),
      h(ChoiceHead, {
        name: "level",
        label: labels.level || "Strictness",
        help: help.level,
        options: levels,
        chosen: chosenLevel,
        locked: levelLocked,
        onChoose: function (name) {
          choose("level", name);
        },
      }),
      h(ChoiceOptions, { label: labels.role || "Job", options: roles, current: currentRole, chosen: chosenRole }),
      h(ChoiceOptions, { label: labels.level || "Strictness", options: levels, current: currentLevel, chosen: chosenLevel })
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
          onApply: apply,
          onCancel: function () {
            setPending(null);
          },
          onAlsoLevel: function (level) {
            choose("level", level);
          },
        })
      : null
  );
}

function ChoicePreview(props) {
  var catalog = props.catalog;
  var pending = props.pending;
  var previewed = props.previewed;
  var parts = [];
  if (pending.role) parts.push("the job to " + roleLabel(catalog, pending.role));
  if (pending.level) parts.push("strictness to " + levelLabel(catalog, pending.level));
  var consequences = [];
  if (pending.role) consequences.push((roleOf(catalog, pending.role) || {}).description);
  if (pending.level) consequences.push((levelOf(catalog, pending.level) || {}).description);
  var suggestion =
    pending.role && props.roleInfo && props.roleInfo.suggests !== (pending.level || props.currentLevel)
      ? props.roleInfo.suggests
      : null;
  var changes = previewed && previewed.changes ? previewed.changes : [];
  var detailsState = useState(false);
  var body;
  if (!previewed) {
    body = h("p", { className: "petasos-help", role: "status" }, "Working out what would change…");
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
        "div",
        { className: "petasos-disclosure" },
        h(
          LinkButton,
          {
            expanded: detailsState[0],
            onClick: function () {
              detailsState[1](!detailsState[0]);
            },
          },
          (detailsState[0] ? "Hide technical changes" : "Show technical changes") + " (" + changes.length + ")"
        ),
        detailsState[0]
          ? h(ChangeList, {
              catalog: catalog,
              rows: catalog.settings,
              changes: changes,
              stored: props.stored,
              after: previewed.stored,
              empty: "No setting would change: your own settings already cover this.",
            })
          : null
      )
    );
  }
  var candidate = JSON.stringify(pending);
  return h(
    "section",
    { className: "petasos-preview", "aria-labelledby": "petasos-preview-title" },
    h("h3", { className: "petasos-subhead", id: "petasos-preview-title" }, "Change " + parts.join(" and ")),
    consequences.map(function (sentence, i) {
      return sentence ? h("p", { key: i, className: "petasos-consequence" }, sentence) : null;
    }),
    suggestion
      ? h(
          "p",
          { className: "petasos-help" },
          roleLabel(catalog, pending.role) + " is usually paired with " + levelLabel(catalog, suggestion) + " strictness. ",
          h(LinkButton, { onClick: function () { props.onAlsoLevel(suggestion); } }, "Use " + levelLabel(catalog, suggestion) + " too")
        )
      : null,
    body,
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

function ChecksPanel(props) {
  var status = props.status;
  var checks = (status.doctor && status.doctor.checks) || [];
  var coverage = status.coverage || { missing: [] };
  var openState = useState(null);
  var recommended = {};
  coverage.missing.forEach(function (row) {
    recommended[row.id] = row.recommended;
  });
  return h(
    Panel,
    {
      id: "petasos-checks",
      title: "Checks",
      description: "The basic checks always run. Optional checks add a model or a code checker on top.",
    },
    h(
      "ul",
      { className: "petasos-scanners" },
      (status.scanners || []).map(function (row) {
        var id = row.id === "syntactic" ? "scanner_builtin" : "scanner_" + row.id;
        var check = checks.filter(function (item) {
          return item.id === id;
        })[0];
        var state = STATE_WORDS[row.state] || { tone: "neutral", word: row.state };
        var expanded = openState[0] === row.id;
        var fixable = (recommended[row.id] || row.state === "unavailable") && (row.fix || row.extra);
        return h(
          "li",
          { key: row.id, className: "petasos-scanner" },
          h(
            "div",
            { className: "petasos-scanner-head" },
            h("span", { className: "petasos-scanner-name" }, row.label),
            recommended[row.id] ? h(Tag, { tone: "outline" }, "Recommended") : null,
            h(Status, { tone: state.tone }, state.word)
          ),
          h("p", { className: "petasos-help" }, check ? check.summary : row.reason || "", check && check.meaning ? " " + check.meaning : ""),
          fixable
            ? h(
                Fragment,
                null,
                h(
                  LinkButton,
                  {
                    expanded: expanded,
                    onClick: function () {
                      openState[1](expanded ? null : row.id);
                    },
                  },
                  expanded ? "Hide how to add it" : "How to add it"
                ),
                expanded
                  ? h(
                      "div",
                      { className: "petasos-fix" },
                      row.fix ? h("p", null, row.fix) : null,
                      row.extra ? h("p", null, "Package: ", h(Mono, null, "petasos[" + row.extra + "]")) : null
                    )
                  : null
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
  if (!locked.known) admin = "This Hermes does not say which settings an administrator has locked.";
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
  return h(
    "div",
    { className: "petasos-stack" },
    h(VerdictPanel, {
      status: status,
      catalog: catalog,
      locked: props.locked,
      onPause: props.onPause,
      onResume: props.onResume,
      onShowChecks: reveal("petasos-checks"),
      onShowSetup: reveal("petasos-setup"),
    }),
    h(RecentPanel, { summary: summaryState[0], events: eventsState[0] }),
    catalog
      ? h(SetupPanel, { catalog: catalog, status: status, locked: props.locked, onSave: props.onSave })
      : h(Panel, { title: "Setup" }, h("p", { className: "petasos-help", role: "status" }, "Loading the choices…")),
    h(
      "div",
      { className: "petasos-grid-2" },
      h(ChecksPanel, { status: status }),
      h(WhoPanel, { status: status, catalog: catalog })
    )
  );
}
