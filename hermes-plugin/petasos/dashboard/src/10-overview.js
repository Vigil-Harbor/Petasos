// ---------------------------------------------------------------------------
// Overview: am I protected, what kind of agent is this, how careful should
// Petasos be, what is doing the checking, and what happened lately.
// ---------------------------------------------------------------------------

// The one verdict a person reads first, from the status response. The order
// is the order of what would stop protection soonest.
function verdictOf(status) {
  var switches = status.switches || {};
  var doctor = status.doctor || {};
  var checks = doctor.checks || [];
  if (switches.hermes && switches.hermes.on === false) {
    return {
      code: "off",
      tone: "destructive",
      word: "Not protected",
      title: "Hermes is not running Petasos",
      reason:
        "Petasos is switched off in Hermes's plugin list, so no tool call is being checked.",
      detail: switches.hermes.detail,
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
      reason:
        "Petasos cannot use settings it does not understand. " +
        (error.message ? "The problem: " + error.message + "." : ""),
      step: { label: "Fix it in Settings", view: "settings" },
    };
  }
  if (switches.petasos && switches.petasos.on === false) {
    return {
      code: "paused",
      tone: "warning",
      word: "Paused",
      title: "Protection is paused",
      reason:
        "Tool calls are going through without being checked. Each one is still recorded, " +
        "so you can see what passed.",
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
  if (doctor.verdict === "protected_with_warnings" && warned) {
    return {
      code: "warn",
      tone: "warning",
      word: "Protected",
      title: "Protected, with one thing to look at",
      reason: warned.summary + (warned.meaning ? " " + warned.meaning : ""),
      stepText: warned.next_step,
    };
  }
  return {
    code: "protected",
    tone: "success",
    word: "Protected",
    title: "Petasos is checking this agent's tool calls",
    reason:
      "Every tool call and tool result is checked before it reaches the agent or leaves it.",
  };
}

function VerdictPanel(props) {
  var status = props.status;
  var verdict = verdictOf(status);
  var paused = status.switches && status.switches.petasos && status.switches.petasos.on === false;
  var canPause = verdict.code === "protected" || verdict.code === "warn";
  var step = null;
  if (verdict.step && verdict.step.resume) {
    step = h(Btn, { onClick: props.onResume, disabled: props.locked }, verdict.step.label);
  } else if (verdict.step && verdict.step.href) {
    step = h(
      "a",
      { className: "petasos-link", href: verdict.step.href },
      verdict.step.label + " →"
    );
  } else if (verdict.step && verdict.step.view) {
    step = h(Btn, { onClick: function () { go(verdict.step.view); } }, verdict.step.label);
  }
  return h(
    "section",
    {
      className: cn("petasos-verdict", "petasos-verdict-" + verdict.tone),
      "aria-labelledby": "petasos-verdict-title",
    },
    h(
      "div",
      { className: "petasos-verdict-main" },
      h(
        "div",
        { className: "petasos-verdict-word" },
        h(Pill, { tone: verdict.tone, className: "petasos-verdict-pill" }, verdict.word)
      ),
      h("h2", { id: "petasos-verdict-title", className: "petasos-verdict-title" }, verdict.title),
      verdict.reason ? h("p", { className: "petasos-verdict-reason" }, verdict.reason) : null,
      verdict.stepText
        ? h("p", { className: "petasos-verdict-step" }, h("span", null, "Next step: "), verdict.stepText)
        : null,
      step ? h("div", { className: "petasos-verdict-actions" }, step) : null,
      h(
        "p",
        { className: "petasos-verdict-meta" },
        "Job: ",
        h("strong", null, jobLabel(status.role)),
        " · Strictness: ",
        h("strong", null, levelLabel(status.level)),
        status.petasos_version ? " · Petasos " + status.petasos_version : null
      )
    ),
    canPause || paused
      ? h(
          "div",
          { className: "petasos-verdict-side" },
          paused
            ? null
            : h(
                Btn,
                { outlined: true, onClick: props.onPause, disabled: props.locked },
                "Pause protection"
              ),
          h(
            "p",
            { className: "petasos-help" },
            paused
              ? "Paused here, in Petasos. Hermes still loads the plugin, and every tool call " +
                  "that passes is recorded in Activity."
              : "Pausing lets tool calls through unchecked until you resume, and records each " +
                  "one. It is not Hermes's plugin switch: Petasos stays loaded."
          )
        )
      : null
  );
}

// One choice (job or strictness) as a list of plain options. Choosing one
// does not save: it opens a preview of what would change.
function ChoiceList(props) {
  return h(
    "fieldset",
    { className: "petasos-options", disabled: props.locked },
    h("legend", { className: "sr-only" }, props.legend),
    props.options.map(function (option) {
      var id = "petasos-" + props.name + "-" + option.name;
      var current = option.name === props.current;
      var chosen = option.name === props.chosen;
      return h(
        "label",
        {
          key: option.name,
          htmlFor: id,
          className: cn(
            "petasos-option",
            chosen && "petasos-option-chosen",
            current && "petasos-option-current"
          ),
        },
        h("input", {
          id: id,
          type: "radio",
          name: "petasos-" + props.name,
          value: option.name,
          checked: chosen,
          onChange: function () {
            props.onChoose(option.name);
          },
        }),
        h(
          "span",
          { className: "petasos-option-text" },
          h(
            "span",
            { className: "petasos-option-name" },
            option.label,
            current ? h(Pill, { tone: "outline", className: "petasos-option-tag" }, "Current") : null,
            option.tag ? h(Pill, { tone: "secondary", className: "petasos-option-tag" }, option.tag) : null
          ),
          h("span", { className: "petasos-option-plain" }, option.plain),
          option.meta ? h("span", { className: "petasos-option-meta" }, option.meta) : null
        )
      );
    })
  );
}

function ChoicesPanel(props) {
  var catalog = props.catalog;
  var status = props.status;
  var stored = catalog.stored || {};
  var currentRole = stored.role || status.role;
  var currentLevel = stored.level || status.level;
  var pendingState = useState(null); // {role} or {level} or {role, level}
  var pending = pendingState[0];
  var setPending = pendingState[1];
  var previewState = useState(null);
  var previewed = previewState[0];
  var setPreviewed = previewState[1];
  var busyState = useState(false);
  var busy = busyState[0];
  var setBusy = busyState[1];

  var chosenRole = pending && pending.role ? pending.role : currentRole;
  var chosenLevel = pending && pending.level ? pending.level : currentLevel;
  var roleInfo = (catalog.roles || []).filter(function (role) {
    return role.name === chosenRole;
  })[0];

  useEffect(
    function () {
      if (!pending) {
        setPreviewed(null);
        return;
      }
      var live = true;
      call("/settings/preview", { method: "POST", body: pending })
        .then(function (body) {
          if (live) setPreviewed(body);
        })
        .catch(function (failure) {
          if (live) setPreviewed({ failure: failure });
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
    setBusy(true);
    props
      .onSave(pending)
      .then(function () {
        setPending(null);
      })
      .finally(function () {
        setBusy(false);
      });
  }

  var roles = (catalog.roles || []).map(function (role) {
    var copy = JOB_COPY[role.name];
    return {
      name: role.name,
      label: jobLabel(role.name),
      plain: copy ? copy.plain : role.description,
    };
  });
  var levels = (catalog.levels || []).map(function (level) {
    var copy = LEVEL_COPY[level.name];
    return {
      name: level.name,
      label: levelLabel(level.name),
      plain: copy ? copy.plain : level.description,
      tag: roleInfo && roleInfo.suggests === level.name ? "Suggested for " + jobLabel(chosenRole) : null,
    };
  });

  return h(
    Fragment,
    null,
    h(
      "div",
      { className: "petasos-grid-2" },
      h(
        Panel,
        {
          title: "What does this agent do?",
          description:
            "Pick the closest job. It decides which checks matter for that kind of work.",
        },
        h(ChoiceList, {
          name: "job",
          legend: "Job",
          options: roles,
          current: currentRole,
          chosen: chosenRole,
          locked: props.locked,
          onChoose: function (name) {
            choose("role", name);
          },
        })
      ),
      h(
        "div",
        { className: "petasos-stack" },
        h(
          Panel,
          {
            title: "How strict should Petasos be?",
            description: "Stricter steps in sooner and blocks more. You can change it any time.",
          },
          h(ChoiceList, {
            name: "level",
            legend: "Strictness",
            options: levels,
            current: currentLevel,
            chosen: chosenLevel,
            locked: props.locked,
            onChoose: function (name) {
              choose("level", name);
            },
          })
        ),
        pending
          ? h(ChoicePreview, {
              pending: pending,
              previewed: previewed,
              rows: catalog.settings,
              stored: stored,
              roleInfo: roleInfo,
              currentLevel: currentLevel,
              busy: busy,
              onApply: apply,
              onCancel: function () {
                setPending(null);
              },
              onAlsoLevel: function (level) {
                choose("level", level);
              },
            })
          : props.aside || null
      )
    )
  );
}

function ChoicePreview(props) {
  var pending = props.pending;
  var previewed = props.previewed;
  var parts = [];
  if (pending.role) parts.push("the job to " + jobLabel(pending.role));
  if (pending.level) parts.push("strictness to " + levelLabel(pending.level));
  var heading = "Switching " + parts.join(" and ");
  var suggestion =
    pending.role &&
    props.roleInfo &&
    props.roleInfo.suggests !== (pending.level || props.currentLevel)
      ? props.roleInfo.suggests
      : null;
  var body;
  if (!previewed) {
    body = h("p", { className: "petasos-muted" }, "Working out what would change…");
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
    body = h(ChangeList, {
      rows: props.rows,
      changes: previewed.changes || [],
      stored: props.stored,
      after: previewed.stored,
      empty: "Nothing would change: your own settings already cover this.",
    });
  }
  var candidate = JSON.stringify(pending);
  return h(
    Panel,
    {
      className: "petasos-preview",
      title: "Preview",
      description: heading + ". Nothing is saved until you apply it.",
    },
    suggestion
      ? h(
          Notice,
          {
            tone: "info",
            action: h(
              Btn,
              { outlined: true, onClick: function () { props.onAlsoLevel(suggestion); } },
              "Also use " + levelLabel(suggestion)
            ),
          },
          jobLabel(pending.role) + " usually goes with " + levelLabel(suggestion) + " strictness."
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
          disabled: props.busy || !previewed || previewed.failure || !previewed.valid,
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

// What a change would do, setting by setting, in words first. A list shows
// what it adds and removes; anything else shows before and after.
function ChangeValues(props) {
  var before = props.before;
  var after = props.after;
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
        return h("li", { key: "+" + item, className: "petasos-diff-add" }, h("span", { "aria-hidden": true }, "+ "), h("span", { className: "sr-only" }, "adds "), String(item));
      }),
      removed.map(function (item) {
        return h("li", { key: "-" + item, className: "petasos-diff-remove" }, h("span", { "aria-hidden": true }, "− "), h("span", { className: "sr-only" }, "removes "), String(item));
      })
    );
  }
  return h(
    "div",
    { className: "petasos-change-values" },
    h("span", { className: "petasos-before" }, showValue(before)),
    h("span", { "aria-hidden": true, className: "petasos-arrow" }, "→"),
    h("span", { className: "petasos-after" }, showValue(after)),
    h("span", { className: "sr-only" }, " (was " + showValue(before) + ")")
  );
}

function ChangeList(props) {
  var changes = props.changes;
  var help = {};
  (props.rows || []).forEach(function (row) {
    help[row.path] = row.help;
  });
  if (!changes.length) {
    return h("p", { className: "petasos-muted" }, props.empty);
  }
  return h(
    "ul",
    { className: "petasos-changes", "aria-label": "What would change" },
    changes.map(function (change) {
      return h(
        "li",
        { key: change.path, className: "petasos-change" },
        h(
          "div",
          { className: "petasos-change-name" },
          h("span", null, help[change.path] || fieldLabel(change.path)),
          h(Mono, { className: "petasos-path" }, change.path)
        ),
        h(ChangeValues, { before: change.before, after: change.after }),
        h(
          "div",
          { className: "petasos-change-tags" },
          h(Pill, { tone: "outline" }, originLabel(change.origin_after, props.after || props.stored)),
          change.restart ? h(Pill, { tone: "warning" }, "Needs a restart") : null
        )
      );
    })
  );
}

var STATE_WORDS = {
  active: { tone: "success", word: "Working" },
  not_installed: { tone: "secondary", word: "Not installed" },
  off: { tone: "outline", word: "Off" },
  unavailable: { tone: "destructive", word: "Not working" },
};

function ScannersPanel(props) {
  var status = props.status;
  var checks = (status.doctor && status.doctor.checks) || [];
  var recommendations = status.recommendations || [];
  var openState = useState(null);
  var open = openState[0];
  var setOpen = openState[1];
  var optional = (status.scanners || []).filter(function (row) {
    return row.id !== "syntactic";
  });
  var noneOptional = optional.every(function (row) {
    return row.state !== "active";
  });
  return h(
    Panel,
    {
      title: "What is doing the checking",
      description:
        "The built-in checks always run. Optional scanners add a model or a code checker on top.",
    },
    noneOptional
      ? h(
          "p",
          { className: "petasos-help petasos-gap-below" },
          "No optional scanner is installed. The built-in checks catch the common attacks; " +
            "the recommended one below adds a model that catches reworded ones."
        )
      : null,
    h(
      "ul",
      { className: "petasos-scanners" },
      (status.scanners || []).map(function (row) {
        var id = row.id === "syntactic" ? "scanner_builtin" : "scanner_" + row.id;
        var check = checks.filter(function (item) {
          return item.id === id;
        })[0];
        var state = STATE_WORDS[row.state] || { tone: "secondary", word: row.state };
        var wanted = row.extra
          ? recommendations.filter(function (line) {
              return line.indexOf("petasos[" + row.extra + "]") >= 0;
            })[0]
          : null;
        var recommended = wanted && row.state !== "active";
        var expanded = open === row.id;
        return h(
          "li",
          { key: row.id, className: "petasos-scanner" },
          h(
            "div",
            { className: "petasos-scanner-head" },
            h("span", { className: "petasos-scanner-name" }, row.label),
            h(
              "span",
              { className: "petasos-scanner-tags" },
              recommended ? h(Pill, { tone: "warning" }, "Recommended") : null,
              h(Pill, { tone: state.tone }, state.word)
            )
          ),
          h(
            "p",
            { className: "petasos-scanner-text" },
            check ? check.summary : row.reason || "",
            check && check.meaning ? " " + check.meaning : ""
          ),
          recommended || row.state === "unavailable"
            ? h(
                Fragment,
                null,
                h(
                  LinkButton,
                  {
                    onClick: function () {
                      setOpen(expanded ? null : row.id);
                    },
                  },
                  expanded ? "Hide how to add it" : "How to add it"
                ),
                expanded
                  ? h(
                      "div",
                      { className: "petasos-fix" },
                      h("p", null, row.fix || wanted),
                      row.extra
                        ? h("p", null, "Package to add: ", h(Mono, null, "petasos[" + row.extra + "]"))
                        : null
                    )
                  : null
              )
            : null
        );
      })
    )
  );
}

function RecentPanel(props) {
  var summary = props.summary;
  var events = props.events || [];
  var counts = (summary && summary.by_outcome) || {};
  var tiles = [
    { key: "blocked", label: "Blocked", value: counts.blocked || 0 },
    { key: "asked", label: "Asked a person", value: (counts.asked || 0) },
    { key: "flagged", label: "Flagged to the agent", value: counts.flagged || 0 },
    { key: "allowed", label: "Let through while paused", value: counts.allowed || 0 },
  ];
  return h(
    Panel,
    {
      title: "Last 24 hours",
      description: summary
        ? summary.total
          ? plural(summary.total, "thing") + " Petasos stepped in on or recorded."
          : "Nothing to report. Clean tool calls are not listed."
        : "Loading…",
      actions: h(LinkButton, { onClick: function () { go("activity"); } }, "All activity →"),
    },
    h(
      "div",
      { className: "petasos-tiles" },
      tiles.map(function (tile) {
        return h(
          "button",
          {
            key: tile.key,
            type: "button",
            className: "petasos-tile",
            onClick: function () {
              go("activity", { range: "24h", outcome: tile.key });
            },
          },
          h("span", { className: "petasos-tile-value" }, String(tile.value)),
          h("span", { className: "petasos-tile-label" }, tile.label)
        );
      })
    ),
    events.length
      ? h(
          "ul",
          { className: "petasos-mini-list" },
          events.map(function (event) {
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
                h("span", { className: "petasos-mini-text" }, event.summary),
                h(Pill, { tone: outcomeTone(event.outcome && event.outcome.code) }, event.outcome && event.outcome.label)
              )
            );
          })
        )
      : null
  );
}

function GuardrailPanel(props) {
  var status = props.status;
  var doctor = status.doctor || {};
  var check = (doctor.checks || []).filter(function (item) {
    return item.id === "guardrail";
  })[0];
  return h(
    Panel,
    {
      title: "Who can change these settings",
      description: "An agent should not be able to switch off its own guardrails.",
    },
    h(KeyValues, {
      rows: [
        [
          "The agent",
          (check ? check.summary + " " : "") +
            "An attempt is recorded and makes the conversation riskier; enough of them and " +
            "its tool calls are blocked.",
        ],
        [
          "You",
          "Here, in Hermes Desktop's plugin settings, or with hermes petasos on the command line.",
        ],
        [
          "An administrator",
          props.locked
            ? "Has locked these settings. Changes are made in the managed Hermes configuration."
            : (check && check.meaning) || "Not reported yet.",
        ],
        [
          "Two switches",
          "Hermes's plugin switch (Plugins page) decides whether Petasos runs at all. " +
            "Pause, above, keeps it running and recording.",
        ],
      ],
    })
  );
}

function outcomeTone(code) {
  if (code === "blocked" || code === "stopped" || code === "declined") return "destructive";
  if (code === "asked" || code === "flagged" || code === "allowed" || code === "degraded") return "warning";
  if (code === "approved") return "success";
  return "secondary";
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
      call("/activity" + query({ limit: 3, since: since }))
        .then(function (body) {
          eventsState[1](body.events || []);
        })
        .catch(function () {});
    },
    30000,
    [props.refreshKey]
  );
  return h(
    "div",
    { className: "petasos-stack" },
    h(VerdictPanel, {
      status: status,
      locked: props.locked,
      onPause: props.onPause,
      onResume: props.onResume,
    }),
    catalog
      ? h(ChoicesPanel, {
          catalog: catalog,
          status: status,
          locked: props.locked,
          onSave: props.onSave,
          aside: h(RecentPanel, { summary: summaryState[0], events: eventsState[0] }),
        })
      : h(Panel, { title: "Job and strictness" }, h("p", { className: "petasos-muted" }, "Loading the choices…")),
    h(
      "div",
      { className: "petasos-grid-2" },
      h(ScannersPanel, { status: status }),
      h(GuardrailPanel, { status: status, locked: props.locked })
    )
  );
}
