// ---------------------------------------------------------------------------
// Try it: paste text or describe a tool call, and see what Petasos would do.
// Nothing here is saved or recorded. Trial settings are not saved.
// ---------------------------------------------------------------------------

// The sample inputs come from the API (GET /playground/examples). They are
// not kept in this script: Hermes scans a plugin's files for dangerous
// strings before it loads the plugin, and a sample attack written here reads
// to that scan as an attack.
function exampleIn(list, id) {
  return (list || []).filter(function (item) {
    return item.id === id;
  })[0];
}

function inputOf(example) {
  if (!example) return null;
  if (example.kind === "tool") {
    return { mode: "tool", tool: example.tool, args: JSON.stringify(example.arguments || {}, null, 2) };
  }
  return { mode: "text", text: example.text, direction: example.direction || "inbound" };
}

// The checked text with each finding marked, numbered to match the list.
function Marked(props) {
  var text = props.text || "";
  var spans = (props.findings || [])
    .map(function (finding, index) {
      return finding.span ? { start: finding.span.start, end: finding.span.end, n: index + 1 } : null;
    })
    .filter(function (span) {
      return span && span.end > span.start && span.start < text.length;
    })
    .sort(function (a, b) {
      return a.start - b.start;
    });
  var parts = [];
  var cursor = 0;
  spans.forEach(function (span) {
    if (span.start < cursor) return; // overlapping: the first one wins
    if (span.start > cursor) parts.push(text.slice(cursor, span.start));
    parts.push(
      h(
        "mark",
        { key: "m" + span.n + "-" + span.start, className: "petasos-mark", title: "Finding " + span.n },
        h("sup", { className: "petasos-mark-n", "aria-label": "finding " + span.n }, String(span.n)),
        text.slice(span.start, Math.min(span.end, text.length))
      )
    );
    cursor = Math.min(span.end, text.length);
  });
  if (cursor < text.length) parts.push(text.slice(cursor));
  return h("pre", { className: "petasos-marked", "aria-label": props.label }, parts);
}

function FindingList(props) {
  var findings = props.findings || [];
  if (!findings.length) {
    return h("p", { className: "petasos-help" }, "Nothing matched a rule.");
  }
  return h(
    Fragment,
    null,
    h(
      "ol",
      { className: "petasos-findings" },
      findings.map(function (finding, index) {
        var syntactic = String(finding.rule).indexOf("petasos.syntactic.") === 0;
        return h(
          "li",
          { key: finding.rule + "-" + index, className: "petasos-finding" },
          h("span", { className: "petasos-finding-n", "aria-hidden": true }, String(index + 1)),
          h(
            "div",
            { className: "petasos-finding-body" },
            h(
              "div",
              { className: "petasos-finding-head" },
              h("span", { className: "petasos-finding-sentence" }, finding.sentence),
              h(Severity, { value: finding.severity })
            ),
            h(
              "p",
              { className: "petasos-finding-meta" },
              h(Ident, null, finding.rule),
              h("span", { title: props.confidenceHelp }, " · Match strength " + Math.round((finding.confidence || 0) * 100) + "%"),
              finding.span ? null : h("span", null, " · Not tied to one place in the text")
            ),
            syntactic
              ? h(
                  "div",
                  { className: "petasos-row-actions" },
                  h(LinkButton, { onClick: function () { props.onQuiet(finding.rule); } }, "Try without this rule"),
                  h(LinkButton, { onClick: function () { go("settings", { rule: finding.rule }); } }, "Rule settings")
                )
              : null
          )
        );
      })
    ),
    props.confidenceHelp ? h("p", { className: "petasos-help" }, props.confidenceHelp) : null
  );
}

function ScannerTakePart(props) {
  return h(
    "ul",
    { className: "petasos-took-part" },
    (props.scanners || []).map(function (row) {
      return h(
        "li",
        { key: row.id },
        h(Status, { tone: row.participated ? "success" : "neutral" }, row.participated ? "Checked" : "Skipped"),
        h("span", { className: "petasos-took-name" }, row.label),
        h("span", { className: "petasos-help" }, !row.participated && row.reason ? row.reason : "")
      );
    })
  );
}

function argumentText(args) {
  // The API marks findings against the string arguments joined by line breaks.
  return Object.keys(args || {})
    .map(function (key) {
      return typeof args[key] === "string" ? args[key] : null;
    })
    .filter(function (value) {
      return value !== null;
    })
    .join("\n");
}

function trialSummary(candidate, catalog) {
  if (!candidate) return "";
  var parts = [];
  if (candidate.role) parts.push("job " + roleLabel(catalog, candidate.role));
  if (candidate.level) parts.push("strictness " + levelLabel(catalog, candidate.level));
  var count = leafCount(candidate.overrides || {});
  if (count) parts.push(plural(count, "other setting"));
  return parts.join(", ");
}

function OutcomeHead(props) {
  var outcome = props.outcome || {};
  return h(
    "div",
    { className: "petasos-decision" },
    h(Status, { tone: outcomeTone(outcome.code), large: true }, (props.prefix || "") + (outcome.label || "")),
    h("p", { className: "petasos-decision-text" }, outcome.sentence)
  );
}

function TryIt(props) {
  var catalog = props.catalog;
  var params = props.route.params;
  var initialCandidate = useMemo(function () {
    if (!params.settings) return null;
    try {
      return JSON.parse(params.settings);
    } catch (_e) {
      return null;
    }
  }, []);

  var examplesState = useState(null);
  var examples = examplesState[0];
  var modeState = useState("tool");
  var mode = modeState[0];
  var textState = useState("");
  var directionState = useState("inbound");
  var toolState = useState("");
  var argsState = useState("{}");
  var exampleState = useState("");
  var candidateState = useState(initialCandidate);
  var candidate = candidateState[0];
  var setCandidate = candidateState[1];
  var trialOpenState = useState(Boolean(initialCandidate));
  var advancedState = useState(
    initialCandidate && initialCandidate.overrides ? JSON.stringify(initialCandidate.overrides, null, 2) : ""
  );
  var advancedErrorState = useState("");
  var resultState = useState(null);
  var baselineState = useState(null);
  var runningState = useState(false);
  var failureState = useState(null);
  var inputErrorState = useState("");
  var ranState = useState(null); // what was checked, for marking and staleness

  function current() {
    return { mode: mode, text: textState[0], direction: directionState[0], tool: toolState[0], args: argsState[0] };
  }

  function load(example) {
    var input = inputOf(example);
    if (!input) return;
    exampleState[1](example.id);
    modeState[1](input.mode);
    if (input.mode === "text") {
      textState[1](input.text);
      directionState[1](input.direction);
    } else {
      toolState[1](input.tool);
      argsState[1](input.args);
    }
  }

  // Load the examples, fill the input with the one the link named (or the
  // default), and check it, so the first look is a real answer.
  useEffect(function () {
    call("/playground/examples")
      .then(function (body) {
        var list = body.examples || [];
        examplesState[1](list);
        var first = exampleIn(list, params.example) || exampleIn(list, body.default) || list[0];
        if (!first) return;
        load(first);
        run(initialCandidate, Object.assign({ text: "", direction: "inbound", tool: "", args: "{}" }, inputOf(first)));
      })
      .catch(function (failure) {
        examplesState[1]([]);
        failureState[1](failure);
      });
  }, []);

  function body(input) {
    if (input.mode === "text") {
      return { text: input.text, direction: input.direction };
    }
    var parsed;
    try {
      parsed = JSON.parse(input.args || "{}");
    } catch (_e) {
      throw new Error('The arguments need to be JSON, for example {"command": "ls"}.');
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error("The arguments need to be a JSON object, in curly braces.");
    }
    return { tool: String(input.tool || "").trim(), arguments: parsed };
  }

  function signature(input, using) {
    return JSON.stringify([input.mode, input.text, input.direction, input.tool, input.args, using || null]);
  }

  function run(nextCandidate, given) {
    var using = nextCandidate === undefined ? candidate : nextCandidate;
    var input = given || current();
    var request;
    try {
      request = body(input);
    } catch (err) {
      inputErrorState[1](err.message);
      return;
    }
    inputErrorState[1]("");
    failureState[1](null);
    runningState[1](true);
    var checked = input.mode === "text" ? request.text : argumentText(request.arguments);
    var withSettings = using ? Object.assign({}, request, { settings: using }) : request;
    var jobs = [call("/playground", { method: "POST", body: withSettings })];
    if (using) jobs.push(call("/playground", { method: "POST", body: request }));
    var stamp = signature(input, using);
    Promise.all(jobs)
      .then(function (answers) {
        resultState[1](answers[0]);
        baselineState[1](answers[1] || null);
        ranState[1]({ text: checked, mode: input.mode, signature: stamp });
      })
      .catch(function (failure) {
        failureState[1](failure);
        resultState[1](null);
      })
      .finally(function () {
        runningState[1](false);
      });
  }

  function suppressed() {
    var overrides = (candidate && candidate.overrides) || {};
    return (overrides.rules && overrides.rules.suppress) || null;
  }

  function quiet(rule) {
    var next = Object.assign({}, candidate || {});
    var overrides = clone(next.overrides || {});
    overrides.rules = overrides.rules || {};
    var saved = rowsByPath(catalog && catalog.settings)["rules.suppress"];
    var list = (overrides.rules.suppress || (saved && saved.value) || []).slice();
    if (list.indexOf(rule) < 0) list.push(rule);
    overrides.rules.suppress = list;
    next.overrides = overrides;
    setCandidate(next);
    trialOpenState[1](true);
    advancedState[1](JSON.stringify(overrides, null, 2));
    run(next);
  }

  function unquiet(rule) {
    var next = clone(candidate || {});
    var list = ((next.overrides && next.overrides.rules && next.overrides.rules.suppress) || []).filter(function (item) {
      return item !== rule;
    });
    var saved = rowsByPath(catalog && catalog.settings)["rules.suppress"];
    var savedList = (saved && saved.value) || [];
    if (JSON.stringify(list) === JSON.stringify(savedList)) removeIn(next.overrides, "rules.suppress");
    else setIn(next.overrides, "rules.suppress", list);
    updateCandidate({ overrides: Object.keys(next.overrides || {}).length ? next.overrides : "" });
    advancedState[1](next.overrides && Object.keys(next.overrides).length ? JSON.stringify(next.overrides, null, 2) : "");
  }

  function updateCandidate(patch) {
    var next = Object.assign({}, candidate || {}, patch);
    Object.keys(next).forEach(function (key) {
      if (next[key] === "" || next[key] === undefined) delete next[key];
    });
    setCandidate(Object.keys(next).length ? next : null);
  }

  var stored = (catalog && catalog.stored) || {};
  var result = resultState[0];
  var baseline = baselineState[0];
  var ran = ranState[0];
  var stale = Boolean(result && ran && ran.signature !== signature(current(), candidate));

  var input = h(
    Panel,
    {
      title: "Input",
      description: "Text the agent might read or send, or a tool call it might make.",
    },
    h(Choice, {
      id: "petasos-try-example",
      label: "Example",
      value: exampleState[0] || "",
      placeholder: examples ? "Load an example…" : "Loading examples…",
      options: (examples || []).map(function (example) {
        return { value: example.id, label: example.label };
      }),
      onChange: function (value) {
        var example = exampleIn(examples, value);
        if (example) load(example);
      },
    }),
    h(
      "p",
      { className: "petasos-help" },
      (exampleIn(examples, exampleState[0]) || {}).description
        ? exampleIn(examples, exampleState[0]).description + " "
        : "",
      "Choosing an example fills the input below. Nothing runs until you press Check."
    ),
    h(
      "div",
      { className: "petasos-filter-group" },
      h("span", { className: "petasos-filter-label", id: "petasos-try-mode-label" }, "Kind"),
      h(Segmented, {
        id: "petasos-try-mode",
        labelledBy: "petasos-try-mode-label",
        value: mode,
        options: [
          { value: "text", label: "Text" },
          { value: "tool", label: "Tool call" },
        ],
        onChange: function (value) {
          modeState[1](value);
          exampleState[1]("");
        },
      })
    ),
    mode === "text"
      ? h(
          Fragment,
          null,
          h(C.Label, { className: "petasos-label", htmlFor: "petasos-try-text" }, "Text"),
          h("textarea", {
            id: "petasos-try-text",
            className: "petasos-textarea",
            rows: 5,
            value: textState[0],
            onChange: function (e) {
              textState[1](e.target.value);
              exampleState[1]("");
            },
          }),
          h(Choice, {
            id: "petasos-try-direction",
            label: "Direction",
            value: directionState[0],
            options: [
              { value: "inbound", label: "Coming in: a tool result, page or file the agent reads" },
              { value: "outbound", label: "Going out: text the agent writes into a tool call" },
            ],
            onChange: directionState[1],
          })
        )
      : h(
          Fragment,
          null,
          h(C.Label, { className: "petasos-label", htmlFor: "petasos-try-tool" }, "Tool"),
          h(C.Input, {
            id: "petasos-try-tool",
            value: toolState[0],
            "aria-describedby": "petasos-try-tool-help",
            onChange: function (e) {
              toolState[1](e.target.value);
              exampleState[1]("");
            },
          }),
          h("p", { className: "petasos-help", id: "petasos-try-tool-help" }, "The tool's name as Hermes knows it, such as terminal or write_file."),
          h(C.Label, { className: "petasos-label", htmlFor: "petasos-try-args" }, "Arguments"),
          h("textarea", {
            id: "petasos-try-args",
            className: "petasos-textarea petasos-mono-area",
            rows: 5,
            value: argsState[0],
            "aria-describedby": "petasos-try-args-help",
            onChange: function (e) {
              argsState[1](e.target.value);
              exampleState[1]("");
            },
          }),
          h("p", { className: "petasos-help", id: "petasos-try-args-help" }, 'A JSON object, for example {"command": "ls"}.')
        ),
    inputErrorState[0] ? h("p", { className: "petasos-field-error", role: "alert" }, inputErrorState[0]) : null,
    h(
      "div",
      { className: "petasos-row-actions" },
      h(Btn, { onClick: function () { run(); }, disabled: runningState[0] }, runningState[0] ? "Checking…" : "Check"),
      h(
        Btn,
        {
          outlined: true,
          "aria-expanded": trialOpenState[0],
          "aria-controls": "petasos-trial",
          onClick: function () {
            trialOpenState[1](!trialOpenState[0]);
          },
        },
        candidate ? "Trial settings: " + trialSummary(candidate, catalog) : "Trial settings"
      ),
      h("span", { className: "petasos-help" }, "Nothing is saved or recorded.")
    )
  );

  var output;
  if (failureState[0]) {
    var failure = failureState[0];
    var byPath = rowsByPath(catalog && catalog.settings);
    var failedPath = failure.path ? String(failure.path).replace(/^overrides\./, "") : "";
    output = h(
      Panel,
      { title: "Result" },
      h(
        Notice,
        {
          tone: failure.code === "invalid_settings" ? "warning" : "destructive",
          title: failure.code === "invalid_settings" ? "Petasos does not allow that trial setting" : "Petasos could not check this",
        },
        h("p", null, failure.message),
        failedPath ? h("p", null, "Setting: ", rowLabel(byPath[failedPath] || { path: failedPath }), " ", h(Mono, { className: "petasos-faint" }, failedPath)) : null
      )
    );
  } else if (!result) {
    output = h(Panel, { title: "Result" }, h("p", { className: "petasos-help", role: "status" }, runningState[0] ? "Checking…" : "Press Check to see what Petasos would do."));
  } else {
    output = h(
      Panel,
      { title: baseline ? "Trial result" : "Result", className: "petasos-result" },
      stale
        ? h(
            Notice,
            { tone: "info", title: "Out of date", action: h(Btn, { outlined: true, onClick: function () { run(); } }, "Check again") },
            "The input or the trial settings changed since this check."
          )
        : null,
      baseline
        ? h(
            "div",
            { className: "petasos-compare", role: "group", "aria-label": "Trial and live results" },
            h(
              "div",
              { className: "petasos-compare-cell" },
              h("p", { className: "petasos-label" }, "With trial settings (not saved)"),
              h(OutcomeHead, { outcome: result.outcome, prefix: "Trial: " })
            ),
            h(
              "div",
              { className: "petasos-compare-cell" },
              h("p", { className: "petasos-label" }, "With your live settings"),
              h(OutcomeHead, { outcome: baseline.outcome, prefix: "Live: " })
            )
          )
        : h(OutcomeHead, { outcome: result.outcome }),
      result.message
        ? h(
            Fragment,
            null,
            h("h4", { className: "petasos-subhead" }, "What the agent would see"),
            h("pre", { className: "petasos-message" }, result.message)
          )
        : null,
      h("h4", { className: "petasos-subhead" }, "What matched"),
      ran && ran.text
        ? h(Marked, { text: ran.text, findings: result.findings, label: "The checked input with matches marked" })
        : null,
      h(FindingList, { findings: result.findings, onQuiet: quiet, confidenceHelp: result.confidence_help }),
      result.findings_omitted ? h("p", { className: "petasos-help" }, plural(result.findings_omitted, "more finding") + " not shown.") : null,
      result.normalized_changed && result.normalized
        ? h(
            Fragment,
            null,
            h("h4", { className: "petasos-subhead" }, "How Petasos read it"),
            h("p", { className: "petasos-help" }, "Disguised characters were turned into plain ones before checking:"),
            h("pre", { className: "petasos-message" }, result.normalized)
          )
        : null,
      h("h4", { className: "petasos-subhead" }, "Checks"),
      h(ScannerTakePart, { scanners: result.scanners })
    );
  }

  var quieted = suppressed() || [];
  var savedSuppress = (rowsByPath(catalog && catalog.settings)["rules.suppress"] || {}).value || [];
  var trial = trialOpenState[0]
    ? h(
        Panel,
        {
          id: "petasos-trial",
          title: "Trial settings",
          description: "These apply to Try it only. The result is shown beside what your live settings do. Nothing is saved.",
          actions: candidate ? h(Btn, { ghost: true, onClick: function () { setCandidate(null); advancedState[1](""); baselineState[1](null); } }, "Use live settings") : null,
        },
        catalog
          ? h(
              "div",
              { className: "petasos-grid-3" },
              h(Choice, {
                id: "petasos-try-job",
                label: (catalog.labels && catalog.labels.role) || "Job",
                value: (candidate && candidate.role) || "saved",
                options: [{ value: "saved", label: "As saved: " + roleLabel(catalog, stored.role) }].concat(
                  (catalog.roles || []).map(function (role) {
                    return { value: role.name, label: role.label || role.name };
                  })
                ),
                onChange: function (value) {
                  updateCandidate({ role: value === "saved" ? "" : value });
                },
              }),
              h(Choice, {
                id: "petasos-try-level",
                label: (catalog.labels && catalog.labels.level) || "Strictness",
                value: (candidate && candidate.level) || "saved",
                options: [{ value: "saved", label: "As saved: " + levelLabel(catalog, stored.level) }].concat(
                  (catalog.levels || []).map(function (level) {
                    return { value: level.name, label: level.label || level.name };
                  })
                ),
                onChange: function (value) {
                  updateCandidate({ level: value === "saved" ? "" : value });
                },
              }),
              h(
                "div",
                { className: "petasos-choice" },
                h("p", { className: "petasos-label" }, "Rules turned off for this trial"),
                quieted.filter(function (rule) { return savedSuppress.indexOf(rule) < 0; }).length
                  ? h(
                      "ul",
                      { className: "petasos-quieted" },
                      quieted
                        .filter(function (rule) {
                          return savedSuppress.indexOf(rule) < 0;
                        })
                        .map(function (rule) {
                          return h(
                            "li",
                            { key: rule },
                            h(Ident, null, rule),
                            h(LinkButton, { onClick: function () { unquiet(rule); }, label: "Turn " + rule + " back on" }, "Turn back on")
                          );
                        })
                    )
                  : h("p", { className: "petasos-help" }, "None. Use Try without this rule on a match.")
              )
            )
          : null,
        h(
          "details",
          { className: "petasos-advanced", open: Boolean(advancedState[0]) && leafCount((candidate && candidate.overrides) || {}) > (quieted.length ? 1 : 0) },
          h("summary", null, "Other settings, as JSON"),
          h(
            "p",
            { className: "petasos-help", id: "petasos-try-overrides-help" },
            'Keys are setting paths, as shown in faint type in Settings. For example {"rules": {"confidence_floor": 0.8}}.'
          ),
          h("textarea", {
            id: "petasos-try-overrides",
            className: "petasos-textarea petasos-mono-area",
            rows: 9,
            "aria-label": "Other trial settings, as JSON",
            "aria-describedby": "petasos-try-overrides-help",
            placeholder: '{"rules": {"confidence_floor": 0.8}}',
            value: advancedState[0],
            onChange: function (e) {
              var text = e.target.value;
              advancedState[1](text);
              if (!text.trim()) {
                updateCandidate({ overrides: "" });
                advancedErrorState[1]("");
                return;
              }
              try {
                updateCandidate({ overrides: JSON.parse(text) });
                advancedErrorState[1]("");
              } catch (_e) {
                advancedErrorState[1]("This needs to be JSON, in curly braces.");
              }
            },
          }),
          advancedErrorState[0] ? h("p", { className: "petasos-field-error", role: "alert" }, advancedErrorState[0]) : null
        ),
        candidate
          ? h(
              "div",
              { className: "petasos-row-actions" },
              h(Btn, { onClick: function () { run(); } }, "Check with these"),
              h(
                Btn,
                {
                  outlined: true,
                  onClick: function () {
                    props.onStage(candidate);
                    go("settings", { review: "1" });
                  },
                },
                "Stage these in Settings"
              ),
              h("span", { className: "petasos-help" }, "Staging lets you review them before anything is saved.")
            )
          : null
      )
    : null;

  return h(
    "div",
    { className: "petasos-stack" },
    h("div", { className: "petasos-split petasos-split-even" }, h("div", null, input), h("div", null, output)),
    trial
  );
}
