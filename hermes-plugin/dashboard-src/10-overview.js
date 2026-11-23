
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

function CoverageRows(props) {
  var status = props.status;
  var coverage = status.coverage || { running: [], missing: [] };
  var paused = props.paused;
  function named(row) {
    return row.name || row.label;
  }
  var running = coverage.running.map(named);
  var missing = coverage.missing.filter(function (row) {
    return !row.held;
  });
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
  } else if (missing.length) {
    rows.push([
      "Not running",
      h(
        "span",
        null,
        plural(missing.length, "optional check") + " · ",
        h(LinkButton, { onClick: props.onShowChecks }, missing.length === 1 ? "What it adds" : "What these add")
      ),
    ]);
  }
  return h(KeyValues, { className: "petasos-coverage", rows: rows });
}

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

function VerdictPanel(props) {
  var status = props.status;
  var verdict = props.verdict;
  // While another write is in flight the control stays where it was, disabled.
  var code = verdict.was || verdict.code;
  var paused = code === "paused";
  var canPause = code === "protected" || code === "warn" || code === "held" || code === "saved";
  var action = null;
  if (verdict.code === "changing") {
    // The same control, still focusable, while its own write is unanswered.
    action = h(
      Btn,
      { id: "petasos-protection-action", outlined: verdict.word === "Pausing…", "aria-disabled": "true", className: "petasos-busy" },
      verdict.word
    );
  } else if (props.pending || verdict.code === "lastknown") {
    action = h(Btn, { id: "petasos-protection-action", onClick: props.onCheck, disabled: props.checking }, props.checking ? "Checking…" : "Check again");
  } else if (paused) {
    action = h(
      Btn,
      {
        id: "petasos-protection-action",
        onClick: props.saving ? undefined : props.onResume,
        disabled: props.locked,
        "aria-disabled": props.saving ? "true" : undefined,
        className: props.saving ? "petasos-busy" : undefined,
      },
      "Resume protection"
    );
  } else if (canPause) {
    action = h(
      Btn,
      {
        id: "petasos-protection-action",
        outlined: true,
        onClick: props.saving ? undefined : props.onPause,
        disabled: props.locked,
        "aria-disabled": props.saving ? "true" : undefined,
        className: props.saving ? "petasos-busy" : undefined,
      },
      "Pause protection"
    );
  } else if (verdict.step && verdict.step.href) {
    action = h("a", { className: "petasos-link", href: verdict.step.href }, verdict.step.label);
  } else if (verdict.step && verdict.step.view) {
    action = h(Btn, { onClick: function () { go(verdict.step.view); } }, verdict.step.label);
  }
  var showCoverage = ["off", "invalid"].indexOf(verdict.code) < 0 && props.detailsCurrent;
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
    props.finding && props.finding.count && props.detailsCurrent
      ? h(
          "div",
          { className: "petasos-alarm-row", role: "status" },
          h("p", null, props.finding.sentence),
          h(
            Btn,
            {
              outlined: true,
              onClick: function () {
                go("settings", { changed: "1" });
              },
            },
            props.finding.action
          )
        )
      : null,
    verdict.reason ? h("p", { className: "petasos-verdict-reason" }, verdict.reason) : null,
    verdict.stepText ? h("p", { className: "petasos-verdict-reason" }, h("strong", null, "Next step: "), verdict.stepText) : null,
    verdict.held ? h(HeldFix, { row: verdict.held, status: status }) : null,
    showCoverage ? h(CoverageRows, { status: status, paused: paused, onShowChecks: props.onShowChecks }) : null,
    props.waiting
      ? h("p", { className: "petasos-secondary", role: "status" }, "What is running is shown again once Petasos confirms the change.")
      : null,
    props.stale
      ? h(
          "div",
          { className: "petasos-alarm-row", role: "status" },
          h(
            "p",
            null,
            "The change was saved, but what is running could not be read afterwards" +
              (props.stale.readAt ? "; the last reading was at " + clockTime(props.stale.readAt) + ", before the change." : ".")
          ),
          h(Btn, { outlined: true, onClick: props.onCheck, disabled: props.checking }, props.checking ? "Checking…" : "Check again")
        )
      : null,
    props.children
  );
}

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
  var retryState = useState(0);
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
    [JSON.stringify(pending), retryState[0]]
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
      .onSave(Object.assign({}, pending, extra || {}), "Change the " + (pending.role ? "job" : "strictness"), previewed && previewed.applies)
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
    Panel,
    {
      className: "petasos-setup",
      id: "petasos-setup",
      title: "Setup",
      description: "Job and strictness set the defaults. A setting you change yourself in Settings takes precedence.",
      actions: h(LinkButton, { onClick: function () { go("settings"); } }, "All settings"),
    },
    roleLocked || levelLocked ? h("p", { className: "petasos-secondary" }, "Locked by your administrator.") : null,
    status.choices_note
      ? h("p", { className: "petasos-secondary", role: "status" }, status.choices_note)
      : null,
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
        locked: roleLocked || props.saving,
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
        locked: levelLocked || props.saving,
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
          currentRole: currentRole,
          currentLevel: currentLevel,
          busy: busyState[0],
          saving: props.saving,
          onRetry: function () {
            retryState[1](retryState[0] + 1);
          },
          onApply: function () {
            apply();
          },
          onCancel: function () {
            setPending(null);
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
    body = h(
      Notice,
      { tone: "destructive", title: "Petasos could not preview this", action: h(Btn, { onClick: props.onRetry }, "Try again") },
      previewed.failure.message
    );
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
      previewed.applies ? h("p", { className: "petasos-when" }, previewed.applies) : null,
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
          { className: "petasos-preview-text petasos-secondary" },
          h("strong", null, "This keeps " + levelLabel(catalog, pending.level || props.currentLevel) + " strictness. "),
          roleLabel(catalog, pending.role) +
            " is often used with " +
            levelLabel(catalog, suggestion) +
            ". " +
            (suggestedLevel && suggestedLevel.description ? suggestedLevel.description + " " : "") +
            "Choose it under Strictness first if you want it."
        )
      : null,
    h(
      "div",
      { className: "petasos-row-actions" },
      h(
        Btn,
        {
          onClick: props.onApply,
          disabled: props.busy || props.saving || !previewed || Boolean(previewed.failure) || !previewed.valid,
        },
        props.busy
          ? "Applying…"
          : "Apply " +
            roleLabel(catalog, pending.role || props.currentRole) +
            " with " +
            levelLabel(catalog, pending.level || props.currentLevel)
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

function RecentPanel(props) {
  var summary = props.summary;
  var events = props.events || [];
  var tiles = (summary && summary.figures) || [];
  var groups = groupEvents(events).slice(0, 4);
  var partial = summary && summary.complete === false;
  var description;
  if (!summary) description = props.failure ? "The activity record could not be read." : "Loading…";
  else if (summary.total) description = plural(summary.total, "event") + (partial ? " in the part of the record that was read" : "") + ". Clean actions are not listed.";
  else if (partial) description = "No events in the part of the record that was read. The rest was too large to read here.";
  else if (props.skipped) description = "No readable events.";
  else description = "Nothing to report. Clean actions are not listed.";
  if (props.skipped) {
    description += " " + plural(props.skipped, "line") + " of the record could not be read, so this may not be everything.";
  }
  if (summary && props.failure) description += " Could not refresh; these are from " + clockTime(props.readAt) + ".";
  return h(
    Panel,
    {
      title: "Last 24 hours",
      description: description,
      actions: h(LinkButton, { onClick: function () { go("activity"); } }, "Open Activity"),
      bare: !tiles.length && !groups.length,
    },
    tiles.length
      ? h(
          "ul",
          { className: "petasos-figures", "aria-label": "Events in the last 24 hours, by outcome" },
          tiles.map(function (tile) {
            var value = tile.count;
            return h(
              "li",
              { key: tile.code },
              h(
                "button",
                {
                  type: "button",
                  className: cn("petasos-figure", !value && "petasos-figure-zero"),
                  disabled: !value,
                  title: value ? "Show them in Activity" : undefined,
                  "aria-label": value + " " + tile.label + (value ? ": show them in Activity" : ""),
                  onClick: function () {
                    go("activity", {
                      range: "24h",
                      outcome: (tile.outcomes || [tile.code]).join(","),
                      word: tile.label,
                    });
                  },
                },
                h("span", { className: "petasos-figure-n" }, String(value)),
                h("span", { className: "petasos-figure-label" }, tile.label)
              )
            );
          })
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
                  event.headline || event.summary,
                  group.events.length > 1 ? h("span", { className: "petasos-repeat" }, " ×" + group.events.length) : null,
                  event.headline && event.explanation ? h("span", { className: "petasos-event-explain petasos-block" }, event.explanation) : null
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
        var fixable = info.command || ((info.recommended || info.held) && row.fix);
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
        ["Administrator", who.administrator || admin],
        ["Two switches", who.switches],
      ],
    })
  );
}

// The first visit to a profile where nobody has chosen a job or a strictness.
// Progress is kept in this browser, per Hermes profile.
var startProfile = "";

function startKey() {
  return "petasos.start" + (startProfile ? ":" + startProfile : "");
}

function readStart() {
  try {
    return JSON.parse(window.localStorage.getItem(startKey()) || "{}") || {};
  } catch (_e) {
    return {};
  }
}

function writeStart(patch) {
  var next = Object.assign(readStart(), patch);
  try {
    window.localStorage.setItem(startKey(), JSON.stringify(next));
  } catch (_e) {
    // Without storage the steps simply show again on the next visit.
  }
  return next;
}

function startingNow(catalog) {
  var start = readStart();
  if (start.done) return false;
  if (start.begun) return true;
  var overrides = (catalog.stored && catalog.stored.overrides) || {};
  return Array.isArray(catalog.chosen) && !catalog.chosen.length && !Object.keys(overrides).length;
}

function StartStep(props) {
  return h(
    "li",
    { className: cn("petasos-step", props.done && "petasos-step-done") },
    h(
      "span",
      { className: "petasos-step-mark", "aria-hidden": true },
      props.done ? h(Icon, { name: "check", size: 14 }) : String(props.n)
    ),
    h(
      "div",
      { className: "petasos-step-text" },
      h("p", { className: "petasos-step-title" }, props.title, props.done ? h("span", { className: "sr-only" }, " (done)") : null),
      h("p", { className: "petasos-secondary" }, props.children)
    ),
    props.action ? h("div", { className: "petasos-step-action" }, props.action) : null
  );
}

function GetStarted(props) {
  var catalog = props.catalog;
  var stored = catalog.stored || {};
  var startState = useState(function () {
    return writeStart({ begun: true });
  });
  var start = startState[0];
  var pickedRole = (catalog.chosen || []).indexOf("role") >= 0;
  var pickedLevel = (catalog.chosen || []).indexOf("level") >= 0;
  var chosen = pickedRole || pickedLevel;
  var role = roleLabel(catalog, stored.role);
  var level = levelLabel(catalog, stored.level);
  var locked = props.locked || ((catalog.locked && catalog.locked.stored) || []).length > 0;
  var finished = chosen && Boolean(start.tried);
  function finish() {
    startState[1](writeStart({ done: true }));
  }
  function fold(hidden) {
    startState[1](writeStart({ hidden: hidden }));
  }
  if (start.done) return null;
  if (start.hidden) {
    return h(Panel, {
      className: "petasos-start",
      title: "Get started",
      description: (chosen ? 1 : 0) + (start.tried ? 1 : 0) + " of 2 steps done.",
      actions: h(Btn, { ghost: true, onClick: function () { fold(false); }, "aria-label": "Show the get started steps" }, "Show"),
      bare: true,
    });
  }
  return h(
    Panel,
    {
      className: "petasos-start",
      title: "Get started",
      description: "Two steps fit Petasos to this agent.",
      actions: finished
        ? h(Btn, { ghost: true, onClick: finish, "aria-label": "Finish and remove the get started steps" }, "Done")
        : h(Btn, { ghost: true, onClick: function () { fold(true); }, "aria-label": "Hide the get started steps" }, "Hide"),
    },
    h(
      "ol",
      { className: "petasos-steps-list" },
      h(
        StartStep,
        {
          n: 1,
          done: chosen,
          title: chosen ? "Setup chosen" : "Choose what this agent does",
          action: chosen
            ? null
            : h(
                Fragment,
                null,
                h(
                  Btn,
                  {
                    disabled: locked || props.saving,
                    onClick: function () {
                      props.onSave({ role: stored.role, level: stored.level }, "Keep " + role + " and " + level).catch(function () {});
                    },
                  },
                  String(props.savingWhat || "").indexOf("Keep ") === 0 ? "Saving…" : "Keep " + role + " and " + level
                ),
                h(Btn, { outlined: true, onClick: props.onChoose }, "Choose another")
              ),
        },
        chosen
          ? role +
              " job" +
              (pickedRole ? "" : " (the default; not chosen)") +
              ", " +
              level +
              " strictness" +
              (pickedLevel ? "" : " (the default; not chosen)") +
              ". Change them under Setup at any time."
          : "Nobody has chosen yet, so Petasos uses " + role + " with " + level + " strictness. Keep them, or pick the job that fits under Setup."
      ),
      h(
        StartStep,
        {
          n: 2,
          done: Boolean(start.tried),
          title: "Try an example",
          action: h(
            Btn,
            {
              outlined: true,
              onClick: function () {
                go("tryit");
              },
            },
            start.tried ? "Open Try it again" : "Open Try it"
          ),
        },
        "Try it runs a sample attack through the checks and shows what Petasos would do with it. Nothing is run or recorded. This step is done once a check has finished."
      )
    )
  );
}

function Overview(props) {
  var status = props.status;
  var catalog = props.catalog;
  var summaryState = useState(null);
  var eventsState = useState([]);
  var recentFailureState = useState(null);
  var skippedState = useState(0);
  var readAtState = useState(null);
  var beginRecent = useLatest();
  usePoll(
    function () {
      var since = Math.floor(Date.now() / 1000) - 86400;
      var latest = beginRecent();
      return Promise.all([call("/activity/summary" + query({ since: since })), call("/activity" + query({ limit: 20, since: since }))]).then(
        function (answers) {
          if (!latest()) return;
          summaryState[1](answers[0]);
          eventsState[1](answers[1].events || []);
          skippedState[1](answers[1].skipped_lines || 0);
          recentFailureState[1](null);
          readAtState[1](Date.now());
        },
        function (failure) {
          if (latest()) recentFailureState[1](failure);
        }
      );
    },
    30000,
    [props.refreshKey]
  );
  useEffect(
    function () {
      var panel = props.route && props.route.params && props.route.params.panel;
      if (panel !== "checks") return;
      var target = document.getElementById("petasos-checks");
      if (target) revealInView(target, "start");
    },
    [props.route && props.route.params && props.route.params.panel, Boolean(status)]
  );
  function reveal(id) {
    return function () {
      var target = document.getElementById(id);
      if (!target) return;
      revealInView(target, "start");
      var focusable = target.querySelector("[role=radio][tabindex='0']") || target.querySelector("button, a");
      if (focusable) focusable.focus({ preventScroll: true });
    };
  }
  var verdict = verdictOf(status);
  var usable = verdict.code !== "off" && verdict.code !== "invalid";
  startProfile = status.home || "";
  var starting = usable && catalog ? startingNow(catalog) : false;
  var setup = null;
  var staleCatalog =
    catalog && props.catalogFailure
      ? h(
          Notice,
          {
            tone: "warning",
            title: "The settings could not be re-read",
            action: h(Btn, { ghost: true, onClick: props.onRetryCatalog }, "Try again"),
          },
          "Setup and “Who can change these settings” show what was read at " +
            (props.catalogReadAt ? clockTime(props.catalogReadAt) : "an earlier time") +
            " and may have changed since."
        )
      : null;
  if (usable && catalog) {
    setup = h(SetupControls, { catalog: catalog, status: status, locked: props.locked, saving: props.saving, onSave: props.onSave });
  } else if (usable && props.catalogFailure) {
    setup = h(
      Panel,
      { title: "Setup", id: "petasos-setup" },
      h(
        Notice,
        {
          tone: "destructive",
          title: "The job and strictness could not be loaded",
          action: h(Btn, { onClick: props.onRetryCatalog }, "Try again"),
        },
        props.catalogFailure.message
      )
    );
  } else if (usable) {
    setup = h("p", { className: "petasos-secondary", role: "status" }, "Loading the choices…");
  }
  var recent = h(RecentPanel, {
    summary: summaryState[0],
    events: eventsState[0],
    failure: recentFailureState[0],
    skipped: skippedState[0],
    readAt: readAtState[0],
  });
  var verdictPanel = h(VerdictPanel, {
    status: status,
    catalog: catalog,
    locked: props.locked,
    saving: props.saving,
    pending: props.pending,
    stale: props.stale,
    verdict: props.verdict,
    detailsCurrent: props.detailsCurrent,
    waiting: props.waiting,
    checking: props.checking,
    onCheck: props.onCheck,
    onPause: props.onPause,
    onResume: props.onResume,
    onShowChecks: reveal("petasos-checks"),
    finding: summaryState[0] && summaryState[0].finding,
  });
  // While a change is unconfirmed, nothing that describes the current settings is shown as current.
  if (props.pending) {
    return h("div", { className: "petasos-stack" }, verdictPanel, recent);
  }
  return h(
    "div",
    { className: "petasos-stack" },
    verdictPanel,
    staleCatalog,
    starting
      ? h(GetStarted, {
          catalog: catalog,
          status: status,
          locked: props.locked,
          saving: props.saving,
          savingWhat: props.savingWhat,
          onSave: props.onSave,
          onChoose: reveal("petasos-setup"),
        })
      : null,
    setup,
    recent,
    h(
      "div",
      { className: "petasos-grid-2" },
      props.detailsCurrent ? h(ChecksPanel, { status: status }) : null,
      // Who may change settings is part of the status reading, so it follows the same rule.
      props.detailsCurrent ? h(WhoPanel, { status: status, catalog: catalog }) : null
    )
  );
}
