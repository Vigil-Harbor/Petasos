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

// What matched, in words: the rule's sentence and how serious it is, with the
// two things a person may do about it. Rule ids and match strength are
// technical detail, listed in TechnicalFindings.
function FindingList(props) {
  var findings = props.findings || [];
  return h(
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
          syntactic
            ? h(
                "div",
                { className: "petasos-row-actions" },
                h(Btn, { outlined: true, onClick: function () { props.onQuiet(finding.rule, finding.sentence); } }, "Try without this rule"),
                h(LinkButton, { onClick: function () { go("settings", { rule: finding.rule }); } }, "Rule settings")
              )
            : null
        )
      );
    })
  );
}

function TechnicalFindings(props) {
  var findings = props.findings || [];
  if (!findings.length) return null;
  return h(
    Fragment,
    null,
    h("p", { className: "petasos-label" }, "Rules that matched"),
    h(
      "ol",
      { className: "petasos-tech-findings" },
      findings.map(function (finding, index) {
        return h(
          "li",
          { key: finding.rule + "-" + index },
          h("span", { className: "petasos-finding-n", "aria-hidden": true }, String(index + 1)),
          h(
            "span",
            null,
            h(Ident, null, finding.rule),
            h("span", { className: "petasos-secondary", title: props.confidenceHelp }, " · Match strength " + Math.round((finding.confidence || 0) * 100) + "%"),
            finding.span ? null : h("span", { className: "petasos-secondary" }, " · Not tied to one place in the text")
          )
        );
      })
    ),
    props.confidenceHelp ? h("p", { className: "petasos-secondary" }, props.confidenceHelp) : null
  );
}

// Each check in this run, named by what it does, with its state from the
// API: checked, skipped, or paused while protection is paused.
function ScannerTakePart(props) {
  return h(
    "ul",
    { className: "petasos-took-part" },
    (props.scanners || []).map(function (row) {
      var operating = row.operating || { code: row.participated ? "checked" : "skipped", label: row.participated ? "Checked" : "Skipped" };
      return h(
        "li",
        { key: row.id },
        h(CheckState, { operating: operating }),
        h("span", { className: "petasos-took-name" }, row.name || row.label),
        row.reason && operating.code !== "checked"
          ? h(
              "span",
              { className: "petasos-secondary" },
              row.link && row.link.href
                ? h("a", { className: "petasos-link", href: row.link.href }, row.reason)
                : row.reason
            )
          : null
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

function lastPart(rule) {
  var text = String(rule || "");
  return text.slice(text.lastIndexOf(".") + 1);
}

// What a trial changes, by name: the job, the strictness, each rule turned
// off, and each other setting by its label.
function trialNames(candidate, catalog) {
  if (!candidate) return [];
  var byPath = rowsByPath(catalog && catalog.settings);
  var names = [];
  if (candidate.role) names.push(roleLabel(catalog, candidate.role) + " job");
  if (candidate.level) names.push(levelLabel(catalog, candidate.level) + " strictness");
  var overrides = candidate.overrides || {};
  var saved = (byPath["rules.suppress"] || {}).value || [];
  var quieted = (getIn(overrides, "rules.suppress") || []).filter(function (rule) {
    return saved.indexOf(rule) < 0;
  });
  if (quieted.length) {
    names.push(plural(quieted.length, "rule") + " turned off");
  }
  (function walk(node, prefix) {
    Object.keys(node || {}).forEach(function (key) {
      var path = prefix ? prefix + "." + key : key;
      if (path === "rules.suppress") return;
      var value = node[key];
      if (value && typeof value === "object" && !Array.isArray(value) && !byPath[path]) walk(value, path);
      else names.push(rowLabel(byPath[path] || { path: path }) + ": " + showValue(value, byPath[path]));
    });
  })(overrides, "");
  return names;
}

function OutcomeHead(props) {
  var outcome = props.outcome || {};
  return h(
    "div",
    { className: "petasos-decision" },
    h(Status, { tone: outcomeTone(outcome.code), large: true, state: outcome.code }, (props.prefix || "") + (outcome.label || "")),
    h("p", { className: "petasos-decision-text" }, outcome.sentence)
  );
}

// Opened from an event: the rule to test, and the one fact that matters,
// that the original text is not kept.
function RuleFocus(props) {
  return h(
    Notice,
    { tone: "info", title: "Testing one rule", action: h(Btn, { ghost: true, onClick: props.onClose }, "Close") },
    props.sentence ? h("p", null, props.sentence) : null,
    h("p", null, h(Ident, { className: "petasos-faint" }, props.rule)),
    h("p", null, "The original text is not kept. Paste it below, then press Check.")
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
  var noteState = useState("");
  var checkNote = noteState[0];
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
  // Each rule turned off for a trial, by its sentence; the id is secondary.
  var sentencesState = useState({});
  var focusState = useState(params.rule ? { rule: params.rule, sentence: params.sentence || "" } : null);
  var focus = focusState[0];

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
        noteState[1](body.check_note || "");
        if (params.rule) {
          // Opened to test a rule: an empty input to paste into, nothing run.
          modeState[1]("text");
          textState[1]("");
          directionState[1](params.direction === "inbound" ? "inbound" : "outbound");
          return;
        }
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

  function quiet(rule, sentence) {
    if (sentence) {
      var known = Object.assign({}, sentencesState[0]);
      known[rule] = sentence;
      sentencesState[1](known);
    }
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

  var trial = trialNames(candidate, catalog);
  var chosen = exampleIn(examples, exampleState[0]);
  var running = runningState[0];
  var checkLabel = running ? "Checking…" : candidate ? "Check with trial settings" : "Check";
  var input = h(
    Panel,
    {
      title: focus ? "Test a rule" : "Try an example",
    },
    focus
      ? h(RuleFocus, {
          rule: focus.rule,
          sentence: focus.sentence,
          onClose: function () {
            focusState[1](null);
            go("tryit");
          },
        })
      : null,
    focus
      ? null
      : h(Choice, {
          id: "petasos-try-example",
          label: "Example",
          value: exampleState[0] || "",
          placeholder: examples ? (mode === "tool" || textState[0] ? "Your own input" : "Choose an example…") : "Loading examples…",
          options: (examples || []).map(function (example) {
            return { value: example.id, label: example.label };
          }),
          onChange: function (value) {
            var example = exampleIn(examples, value);
            if (!example) return;
            load(example);
            run(undefined, Object.assign({ text: "", direction: "inbound", tool: "", args: "{}" }, inputOf(example)));
          },
        }),
    chosen && chosen.description && !focus ? h("p", { className: "petasos-try-desc" }, chosen.description) : null,
    h(
      Disclosure,
      {
        label: "Show and edit the input",
        openLabel: "Hide the input",
        remember: focus ? undefined : "tryit-input",
        defaultOpen: Boolean(focus),
      },
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
              placeholder: focus ? "Paste the text here" : undefined,
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
            h("p", { className: "petasos-help", id: "petasos-try-tool-help" }, "The tool's name in Hermes, such as terminal or write_file."),
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
          )
    ),
    inputErrorState[0] ? h("p", { className: "petasos-field-error", role: "alert" }, inputErrorState[0]) : null,
    h(
      "div",
      { className: "petasos-row-actions" },
      h(Btn, { onClick: function () { run(); }, disabled: running }, checkLabel),
      checkNote ? h("p", { className: "petasos-secondary petasos-check-note" }, checkNote) : null,
      h(
        Btn,
        {
          ghost: true,
          "aria-expanded": trialOpenState[0],
          "aria-controls": "petasos-trial",
          onClick: function () {
            trialOpenState[1](!trialOpenState[0]);
          },
        },
        trialOpenState[0] ? "Hide trial settings" : "Change trial settings"
      )
    ),
    trial.length
      ? h("p", { className: "petasos-trial-line" }, h("strong", null, "Trying: "), trial.join(", ") + ". Not saved.")
      : null
  );

  var output;
  var checksPanel = null;
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
    output = h(
      Panel,
      { title: "Result" },
      h("p", { className: "petasos-help", role: "status" }, running ? "Checking…" : focus ? "Paste the text, then press Check." : "Press Check to see what Petasos would do.")
    );
  } else {
    var ruleSeen = focus
      ? (result.findings || []).some(function (finding) {
          return finding.rule === focus.rule;
        })
      : null;
    output = h(
      Panel,
      { title: baseline ? "Trial result" : "Result", className: "petasos-result" },
      result.paused_note ? h(Notice, { tone: "warning", title: "Protection is paused" }, result.paused_note) : null,
      stale
        ? h(Notice, { tone: "info", title: "Out of date" }, "The input or the trial settings changed since this check.")
        : null,
      baseline
        ? h(
            "div",
            { className: "petasos-compare", role: "group", "aria-label": "Trial and live results" },
            h(
              "div",
              { className: "petasos-compare-cell" },
              h("p", { className: "petasos-label" }, "With trial settings (not saved)"),
              h(Status, { tone: outcomeTone(result.outcome.code), large: true, state: result.outcome.code }, "Trial: " + (result.outcome.label || "")),
              h("p", { className: "petasos-decision-text" }, result.outcome.sentence)
            ),
            h(
              "div",
              { className: "petasos-compare-cell" },
              h("p", { className: "petasos-label" }, "With your live settings"),
              h(Status, { tone: outcomeTone(baseline.outcome.code), large: true, state: baseline.outcome.code }, "Live: " + (baseline.outcome.label || "")),
              h("p", { className: "petasos-decision-text" }, baseline.outcome.sentence)
            )
          )
        : h(OutcomeHead, { outcome: result.outcome }),
      focus ? h("p", { className: "petasos-strong" }, ruleSeen ? "This rule matched." : "This rule did not match this text.") : null,
      (result.findings || []).length
        ? h(
            Fragment,
            null,
            h("h4", { className: "petasos-subhead" }, "Where it matched"),
            ran && ran.text
              ? h(Marked, { text: ran.text, findings: result.findings, label: "The checked input with matches marked" })
              : null,
            h(FindingList, { findings: result.findings, onQuiet: quiet }),
            result.findings_omitted ? h("p", { className: "petasos-secondary" }, plural(result.findings_omitted, "more match", "more matches") + " not shown.") : null
          )
        : h("p", { className: "petasos-secondary" }, "Nothing in this input matched a rule."),
      h("h4", { className: "petasos-subhead" }, "Personal information"),
      h("p", { className: "petasos-secondary" }, result.anonymization.sentence),
      result.anonymized ? h("pre", { className: "petasos-message", "aria-label": "Text with personal information hidden" }, result.anonymized) : null,
      h("h4", { className: "petasos-subhead" }, "Conversation risk"),
      h("p", null, result.risk.sentence),
      h("p", { className: "petasos-secondary" }, result.risk.threshold_sentence),
      h("p", { className: "petasos-help" }, result.risk.note),
      h(
        Disclosure,
        { label: "Technical detail", openLabel: "Hide technical detail", remember: "tryit-technical" },
        result.message
          ? h(
              Fragment,
              null,
              h("p", { className: "petasos-label" }, "What the agent would see"),
              h("pre", { className: "petasos-message" }, result.message)
            )
          : null,
        h(TechnicalFindings, { findings: result.findings, confidenceHelp: result.confidence_help }),
        result.normalized_changed && result.normalized
          ? h(
              Fragment,
              null,
              h("p", { className: "petasos-label" }, "How Petasos read it"),
              h("p", { className: "petasos-secondary" }, "Disguised characters were turned into plain ones before checking:"),
              h("pre", { className: "petasos-message" }, result.normalized)
            )
          : null
      )
    );
    checksPanel = h(
      Panel,
      { title: "Checks in this run", className: "petasos-checks-run" },
      h(ScannerTakePart, { scanners: result.scanners })
    );
  }

  var quieted = suppressed() || [];
  var savedSuppress = (rowsByPath(catalog && catalog.settings)["rules.suppress"] || {}).value || [];
  var trialQuieted = quieted.filter(function (rule) {
    return savedSuppress.indexOf(rule) < 0;
  });
  var sentences = sentencesState[0];
  var trialPanel = trialOpenState[0]
    ? h(
        Panel,
        {
          id: "petasos-trial",
          title: "Trial settings",
          description: "For Try it only. Nothing is saved.",
          actions: candidate ? h(Btn, { ghost: true, onClick: function () { setCandidate(null); advancedState[1](""); baselineState[1](null); } }, "Use live settings") : null,
        },
        catalog
          ? h(
              "div",
              { className: "petasos-trial-grid" },
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
              })
            )
          : null,
        h(
          "div",
          { className: "petasos-choice" },
          h("p", { className: "petasos-label" }, "Rules turned off for this trial"),
          trialQuieted.length
            ? h(
                "ul",
                { className: "petasos-quieted" },
                trialQuieted.map(function (rule) {
                  return h(
                    "li",
                    { key: rule },
                    h(
                      "span",
                      { className: "petasos-quieted-name" },
                      h("span", { className: "petasos-block" }, sentences[rule] || lastPart(rule)),
                      h(Ident, { className: "petasos-faint" }, rule)
                    ),
                    h(Btn, { outlined: true, onClick: function () { unquiet(rule); }, "aria-label": "Turn " + rule + " back on" }, "Turn back on")
                  );
                })
              )
            : h("p", { className: "petasos-secondary" }, "None. Use Try without this rule on a match.")
        ),
        h(
          Disclosure,
          {
            label: "Technical detail",
            openLabel: "Hide technical detail",
            defaultOpen: Boolean(advancedState[0]) && leafCount((candidate && candidate.overrides) || {}) > (quieted.length ? 1 : 0),
          },
          h(C.Label, { className: "petasos-label", htmlFor: "petasos-try-overrides" }, "Other trial settings, as JSON"),
          h(
            "p",
            { className: "petasos-help", id: "petasos-try-overrides-help" },
            'Keys are setting paths, as shown in Settings. For example {"rules": {"confidence_floor": 0.8}}.'
          ),
          h("textarea", {
            id: "petasos-try-overrides",
            className: "petasos-textarea petasos-mono-area",
            rows: 7,
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
              h(
                Btn,
                {
                  outlined: true,
                  onClick: function () {
                    props.onStage(candidate);
                    go("settings", { review: "1" });
                  },
                },
                "Copy to Settings"
              ),
              h("span", { className: "petasos-secondary" }, "Not saved until you press Save there.")
            )
          : null
      )
    : null;

  return h(
    "div",
    { className: "petasos-stack" },
    h("div", { className: "petasos-split petasos-split-try" }, h("div", null, input), h("div", null, output)),
    trialPanel,
    checksPanel
  );
}
