
// See docs/architecture/rationale.md, "Dashboard source packaging".
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

function Marked(props) {
  // Offsets from the API count characters, so the text is cut by code point.
  var points = Array.from(props.text || "");
  var text = {
    length: points.length,
    slice: function (start, end) {
      return points.slice(start, end).join("");
    },
  };
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
                finding.can_turn_off === false
                  ? h("span", { className: "petasos-secondary" }, "These settings do not let this rule be turned off.")
                  : h(
                      Btn,
                      {
                        outlined: true,
                        disabled: !props.canQuiet,
                        title: props.canQuiet ? undefined : "Not available until the settings load and the trial settings can be read",
                        onClick: function () {
                          props.onQuiet(finding.rule, finding.sentence);
                        },
                      },
                      "Try without this rule"
                    ),
                h(LinkButton, { onClick: function () { go("settings", { rule: finding.rule, sentence: finding.sentence || "" }); } }, "Rule settings")
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
  // Finding offsets index string arguments joined by newline.
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

function listOf(value) {
  return Array.isArray(value) ? value : [];
}

// What is wrong with trial settings typed as JSON, or "" when they can be used.
function trialProblem(parsed) {
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return "This needs to be a JSON object, in curly braces.";
  var rules = parsed.rules;
  if (rules !== undefined && (!rules || typeof rules !== "object" || Array.isArray(rules))) return "\"rules\" needs to be an object, in curly braces.";
  if (rules && rules.suppress !== undefined) {
    var list = rules.suppress;
    var strings =
      Array.isArray(list) &&
      list.every(function (item) {
        return typeof item === "string";
      });
    if (!strings) return "\"rules.suppress\" needs to be a list of rule ids, in square brackets.";
  }
  return "";
}

// What one run can say about its matches, given whether it finished and whether its list was cut.
function matchWords(run) {
  var count = (run.findings || []).length;
  if (run.timed_out) return count ? plural(count, "match", "matches") + " before the check ran out of time; there may be more" : "no match before the check ran out of time";
  if (run.checks_incomplete) return count ? plural(count, "match", "matches") + " from the checks that finished; a check reported an error" : "no match from the checks that finished; a check reported an error";
  if (run.findings_omitted) return count + " matches listed and " + run.findings_omitted + " more not listed";
  return count ? plural(count, "match", "matches") : "no rule matched";
}

function trialNames(candidate, catalog) {
  if (!candidate) return [];
  var byPath = rowsByPath(catalog && catalog.settings);
  var names = [];
  if (candidate.role) names.push(roleLabel(catalog, candidate.role) + " job");
  if (candidate.level) names.push(levelLabel(catalog, candidate.level) + " strictness");
  var overrides = candidate.overrides || {};
  var saved = (byPath["rules.suppress"] || {}).value || [];
  var quieted = listOf(getIn(overrides, "rules.suppress")).filter(function (rule) {
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
  var sentencesState = useState({});
  var focusState = useState(params.rule ? { rule: params.rule, sentence: params.sentence || "" } : null);
  var focus = focusState[0];
  var beginRun = useLatest();
  var examplesFailureState = useState(null);
  var examplesRetryState = useState(0);
  var copyState = useState(null);
  var announceState = useState("");
  var showResult = useRef(false);
  var rememberCopyOpener = useReturnFocus(Boolean(copyState[0]), "petasos-try-copy");

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

  useEffect(function () {
    examplesFailureState[1](null);
    call("/playground/examples")
      .then(function (body) {
        var list = body.examples || [];
        examplesState[1](list);
        noteState[1](body.check_note || "");
        if (params.rule) {
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
        examplesFailureState[1](failure);
      });
  }, [examplesRetryState[0]]);

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

  // A result belongs to the input, the trial settings, and the saved settings and protection state it ran under.
  // An unconfirmed or unread change counts: a result from before it describes settings that may be gone.
  var statusNow = props.status || {};
  var savedStamp = JSON.stringify([
    catalog && catalog.stored,
    Boolean(statusNow.paused),
    statusNow.protection,
    statusNow.role,
    statusNow.level,
    Boolean(props.pending),
    Boolean(props.stale),
    Boolean(props.saving),
    // A check that started or stopped working, or a status that could not be re-read, also dates a result.
    (statusNow.scanners || []).map(function (row) {
      return row.id + ":" + ((row.operating && row.operating.code) || "");
    }),
    props.detailsCurrent === false,
  ]);
  // Only what the request carries: fields of the editor that is not in use do not make a result stale.
  function signature(input, using) {
    var sent = input.mode === "text" ? ["text", input.text, input.direction] : ["tool", String(input.tool || "").trim(), input.args];
    return JSON.stringify([sent, using || null, savedStamp]);
  }

  function run(nextCandidate, given) {
    var using = nextCandidate === undefined ? (trialOpenState[0] ? candidate : null) : nextCandidate;
    var input = given || current();
    // With Trial settings chosen and its editor unreadable, nothing runs: not the last trial that parsed, and not a live check passed off as the trial.
    if (trialOpenState[0] && advancedErrorState[0] && nextCandidate === undefined) {
      beginRun();
      runningState[1](false);
      resultState[1](null);
      baselineState[1](null);
      failureState[1](null);
      announceState[1]("Not checked: the trial settings cannot be read.");
      return;
    }
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
    var latest = beginRun();
    Promise.all(jobs)
      .then(function (answers) {
        if (!latest()) return;
        resultState[1](answers[0]);
        baselineState[1](answers[1] || null);
        ranState[1]({ text: checked, mode: input.mode, signature: stamp, trial: Boolean(using) });
        var outcome = answers[0].outcome || {};
        announceState[1]((using ? "Trial result: " : "Result: ") + (outcome.label || "") + ". " + (outcome.sentence || ""));
        if (readStart().begun) writeStart({ tried: true });
      })
      .catch(function (failure) {
        if (!latest()) return;
        failureState[1](failure);
        resultState[1](null);
        baselineState[1](null);
        announceState[1]("Petasos could not check this. " + (failure.message || ""));
      })
      .finally(function () {
        if (latest()) runningState[1](false);
      });
  }

  // A check the person asked for brings its result into view when the result sits below the input.
  function check() {
    showResult.current = true;
    run();
  }
  useEffect(
    function () {
      if (!showResult.current || runningState[0]) return;
      showResult.current = false;
      var panel = document.getElementById("petasos-try-result");
      if (panel && window.innerWidth <= 1100) revealInView(panel, "start");
    },
    [resultState[0], failureState[0], runningState[0]]
  );

  function suppressed() {
    var overrides = (candidate && candidate.overrides) || {};
    return overrides.rules && Array.isArray(overrides.rules.suppress) ? overrides.rules.suppress : null;
  }

  function quiet(rule, sentence) {
    // Nothing is built on trial settings that cannot be read; the editor keeps what was typed.
    if (trialOpenState[0] && advancedErrorState[0]) return;
    if (sentence) {
      var known = Object.assign({}, sentencesState[0]);
      known[rule] = sentence;
      sentencesState[1](known);
    }
    var next = Object.assign({}, candidate || {});
    var overrides = clone(next.overrides || {});
    overrides.rules = overrides.rules || {};
    var saved = rowsByPath(catalog && catalog.settings)["rules.suppress"];
    var list = (Array.isArray(overrides.rules.suppress) ? overrides.rules.suppress : listOf(saved && saved.value)).slice();
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
    var list = listOf(next.overrides && next.overrides.rules && next.overrides.rules.suppress).filter(function (item) {
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
  // The trial is kept while Live settings is chosen; it only takes part when Trial settings is.
  var trialOn = trialOpenState[0];
  var active = trialOn ? candidate : null;
  var trialInvalid = trialOn && Boolean(advancedErrorState[0]);
  var stale = Boolean(result && ran && (trialInvalid || ran.signature !== signature(current(), active)));

  var trial = trialNames(active, catalog);
  var chosen = exampleIn(examples, exampleState[0]);
  var running = runningState[0];
  var checkLabel = running ? "Checking…" : active ? "Check with trial settings" : "Check";
  var preview = (function () {
    var now = current();
    var text = "";
    var tool = "";
    if (now.mode === "text") text = now.text;
    else {
      tool = String(now.tool || "").trim();
      try {
        text = argumentText(JSON.parse(now.args || "{}"));
      } catch (_e) {
        text = "";
      }
    }
    return { text: text, tool: tool, marked: Boolean(result && ran && !stale && ran.text === text) };
  })();
  var checkRow = h(
    Fragment,
    null,
    h(
      "div",
      { className: "petasos-row-actions" },
      h(Btn, { onClick: check, disabled: running || trialInvalid }, checkLabel),
      checkNote ? h("p", { className: "petasos-secondary petasos-check-note" }, checkNote) : null
    ),
    trialInvalid ? h("p", { className: "petasos-secondary" }, "Fix the trial settings above to check with them.") : null,
    trial.length && !trialInvalid
      ? h("p", { className: "petasos-trial-line" }, h("strong", null, "Trying: "), trial.join(", ") + ". Not saved.")
      : null
  );
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
    examplesFailureState[0] && !focus
      ? h(
          Notice,
          {
            tone: "destructive",
            title: "The examples could not be loaded",
            action: h(Btn, { onClick: function () { examplesRetryState[1](examplesRetryState[0] + 1); } }, "Try again"),
          },
          examplesFailureState[0].message + " You can still type your own input under Edit the input."
        )
      : null,
    chosen && chosen.description && !focus ? h("p", { className: "petasos-try-desc" }, chosen.description) : null,
    preview.text
      ? h(
          "div",
          { className: "petasos-try-preview" },
          h(
            "p",
            { className: "petasos-label", id: "petasos-try-preview-label" },
            "What gets checked"
          ),
          preview.tool
            ? h("p", { className: "petasos-secondary" }, "The text the agent passes to the ", h(Mono, null, preview.tool), " tool.")
            : null,
          h(Marked, {
            text: preview.text,
            findings: preview.marked ? result.findings : [],
            label: preview.marked ? "The checked input with matches marked" : "The input",
          })
        )
      : null,
    h(
      Disclosure,
      {
        label: "Edit the input",
        openLabel: "Hide the editor",
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
      { className: "petasos-filter-group petasos-try-using" },
      h("span", { className: "petasos-filter-label", id: "petasos-try-using-label" }, "Check with"),
      h(Segmented, {
        id: "petasos-try-using",
        labelledBy: "petasos-try-using-label",
        value: trialOn ? "trial" : "live",
        options: [
          { value: "live", label: "Live settings" },
          { value: "trial", label: "Trial settings" },
        ],
        onChange: function (value) {
          if (value === "trial") {
            trialOpenState[1](true);
            return;
          }
          trialOpenState[1](false);
          if (!candidate) return;
          beginRun();
          runningState[1](false);
          // The live result for the same input was already computed beside the trial.
          var live = baselineState[0];
          var same = ran && !trialInvalid && ran.signature === signature(current(), candidate);
          if (live && same) {
            resultState[1](live);
            ranState[1](Object.assign({}, ran, { signature: signature(current(), null), trial: false }));
            announceState[1]("Showing the result with live settings: " + ((live.outcome && live.outcome.label) || "") + ".");
          } else {
            resultState[1](null);
          }
          baselineState[1](null);
        },
      })
    ),
    trialOn ? null : checkRow
  );

  var output;
  var live = h("p", { className: "sr-only", role: "status", "aria-live": "polite" }, announceState[0]);
  if (failureState[0]) {
    var failure = failureState[0];
    var byPath = rowsByPath(catalog && catalog.settings);
    var failedPath = failure.path ? String(failure.path).replace(/^overrides\./, "").replace(/\[\d+\]$/, "") : "";
    output = h(
      Panel,
      { title: "Result", id: "petasos-try-result" },
      live,
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
      { title: "Result", id: "petasos-try-result" },
      live,
      h(
        "p",
        { className: "petasos-help" },
        running
          ? "Checking…"
          : trialInvalid
            ? "Not checked. Fix the trial settings, then press Check."
            : focus
              ? "Paste the text, then press Check."
              : "Press Check to see what Petasos would do."
      )
    );
  } else {
    // A run that ran out of time, or in which a check reported an error, cannot prove an absence.
    var cut = Boolean(result.timed_out);
    var incomplete = cut || Boolean(result.checks_incomplete);
    var why = cut ? "The check ran out of time" : "A check reported an error";
    var ruleSeen = focus
      ? (result.findings || []).some(function (finding) {
          return finding.rule === focus.rule;
        })
      : null;
    var focusLine = null;
    if (focus && ruleSeen) focusLine = "This rule matched.";
    else if (focus && incomplete) focusLine = why + ", so this run cannot say whether this rule matches.";
    else if (focus && result.findings_omitted) focusLine = "Not every match is listed, so this run cannot say whether this rule matched.";
    else if (focus) focusLine = "This rule did not match this text.";
    var trialPaused = Boolean(active && active.enabled === false);
    var sameWords = baseline && result.outcome.sentence === baseline.outcome.sentence;
    output = h(
      Panel,
      { title: ran && ran.trial ? "Trial result" : "Result", className: "petasos-result", id: "petasos-try-result" },
      live,
      result.paused_note && !baseline
        ? h(Notice, { tone: "warning", title: trialPaused ? "Protection is paused in these trial settings" : "Protection is paused" }, result.paused_note)
        : null,
      stale
        ? h(Notice, { tone: "info", title: "Out of date" }, "The input, the trial settings or the saved settings changed since this check. Press Check to run it again.")
        : null,
      baseline
        ? h(
            "div",
            { className: "petasos-compare", role: "group", "aria-label": "Trial and live results" },
            h(
              "div",
              { className: "petasos-compare-cell", "data-petasos-run": "trial" },
              h("p", { className: "petasos-label" }, "With trial settings (not saved)"),
              h(Status, { tone: outcomeTone(result.outcome.code), large: true, state: result.outcome.code }, result.outcome.label || ""),
              sameWords ? null : h("p", { className: "petasos-decision-text" }, result.outcome.sentence),
              h("p", { className: "petasos-compare-note" }, sentenceCase(matchWords(result)) + "."),
              result.paused_note ? h("p", { className: "petasos-compare-note" }, "Protection is paused in the trial settings. " + result.paused_note) : null
            ),
            h(
              "div",
              { className: "petasos-compare-cell", "data-petasos-run": "live" },
              h("p", { className: "petasos-label" }, "With your live settings"),
              h(Status, { tone: outcomeTone(baseline.outcome.code), large: true, state: baseline.outcome.code }, baseline.outcome.label || ""),
              sameWords ? null : h("p", { className: "petasos-decision-text" }, baseline.outcome.sentence),
              h(
                "p",
                { className: "petasos-compare-note" },
                sentenceCase(matchWords(baseline)) +
                  ((baseline.findings || []).length
                    ? ": " +
                      baseline.findings
                        .map(function (finding) {
                          return finding.sentence;
                        })
                        .join(" ")
                    : ".")
              ),
              baseline.paused_note ? h("p", { className: "petasos-compare-note" }, "Protection is paused now. " + baseline.paused_note) : null
            )
          )
        : h(OutcomeHead, { outcome: result.outcome }),
      baseline && sameWords ? h("p", { className: "petasos-decision-text" }, "Both: " + result.outcome.sentence) : null,
      incomplete || (baseline && (baseline.timed_out || baseline.checks_incomplete))
        ? h(
            Notice,
            { tone: "warning", title: "This result is incomplete" },
            (incomplete && baseline && (baseline.timed_out || baseline.checks_incomplete)
              ? "Neither run completed every check"
              : incomplete
                ? baseline
                  ? why + " in the run with trial settings"
                  : why
                : "The run with your live settings did not complete every check") +
              ", so matches may be missing. “Checks in this run” shows which checks are confirmed."
          )
        : null,
      focusLine ? h("p", { className: "petasos-strong" }, focusLine) : null,
      (result.findings || []).length
        ? h(
            Fragment,
            null,
            h("h4", { className: "petasos-subhead" }, baseline ? "What matched with the trial settings" : "What matched"),
            h(FindingList, { findings: result.findings, onQuiet: quiet, canQuiet: Boolean(catalog) && !trialInvalid }),
            result.findings_omitted ? h("p", { className: "petasos-secondary" }, plural(result.findings_omitted, "more match", "more matches") + " not shown.") : null
          )
        : h(
            "p",
            { className: "petasos-secondary" },
            incomplete
              ? "No match was found, but the result is incomplete: " + why.charAt(0).toLowerCase() + why.slice(1) + "."
              : baseline
                ? "Nothing in this input matched a rule with the trial settings."
                : "Nothing in this input matched a rule."
          ),
      h("h4", { className: "petasos-subhead" }, "Personal information"),
      h("p", { className: "petasos-secondary" }, result.anonymization.sentence),
      result.anonymized && result.anonymized.trim() ? h("pre", { className: "petasos-message", "aria-label": "Text with personal information hidden" }, result.anonymized) : null,
      h("h4", { className: "petasos-subhead" }, "Conversation risk"),
      h("p", null, result.risk.sentence),
      h(
        Disclosure,
        { label: "How conversation risk works", openLabel: "Hide how conversation risk works" },
        h("p", { className: "petasos-secondary" }, result.risk.threshold_sentence),
        h("p", { className: "petasos-secondary" }, result.risk.note)
      ),
      h("h4", { className: "petasos-subhead" }, "Checks in this run"),
      h(ScannerTakePart, { scanners: result.scanners }),
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
  }

  var quieted = suppressed() || [];
  var savedSuppress = (rowsByPath(catalog && catalog.settings)["rules.suppress"] || {}).value || [];
  var trialQuieted = quieted.filter(function (rule) {
    return savedSuppress.indexOf(rule) < 0;
  });
  var sentences = sentencesState[0];
  var trialPanel = trialOn
    ? h(
        Panel,
        {
          id: "petasos-trial",
          title: "Trial settings",
          description: "For Try it only. Nothing is saved. Choosing Live settings keeps this trial for later.",
          actions: candidate || advancedState[0]
            ? h(
                Btn,
                {
                  ghost: true,
                  onClick: function () {
                    beginRun();
                    runningState[1](false);
                    setCandidate(null);
                    advancedState[1]("");
                    advancedErrorState[1]("");
                    baselineState[1](null);
                    resultState[1](null);
                  },
                },
                "Clear trial"
              )
            : null,
        },
        !catalog && props.catalogFailure
          ? h(
              Notice,
              {
                tone: "destructive",
                title: "The saved settings could not be loaded",
                action: h(Btn, { onClick: props.onRetryCatalog }, "Try again"),
              },
              "The job, the strictness and the rules already turned off are unknown until they load, so a trial cannot be built on them."
            )
          : null,
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
            "aria-invalid": advancedErrorState[0] ? "true" : undefined,
            "aria-describedby": "petasos-try-overrides-help" + (advancedErrorState[0] ? " petasos-try-overrides-error" : ""),
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
              var parsed;
              try {
                parsed = JSON.parse(text);
              } catch (_e) {
                parsed = undefined;
              }
              var wrong = parsed === undefined ? "This is not valid JSON yet." : trialProblem(parsed);
              if (wrong) {
                advancedErrorState[1](wrong + " Until it is fixed, nothing is checked or copied with these trial settings.");
                return;
              }
              updateCandidate({ overrides: parsed });
              advancedErrorState[1]("");
            },
          }),
          advancedErrorState[0] ? h("p", { className: "petasos-field-error", id: "petasos-try-overrides-error", role: "alert" }, advancedErrorState[0]) : null
        ),
        checkRow,
        candidate
          ? h(
              "div",
              { className: "petasos-row-actions" },
              h(
                Btn,
                {
                  outlined: true,
                  id: "petasos-try-copy",
                  disabled: trialInvalid,
                  onClick: function () {
                    var clash = draftConflicts(props.draft, candidate, knownPaths(catalog && catalog.settings));
                    if (clash.length) {
                      rememberCopyOpener();
                      copyState[1](clash);
                      return;
                    }
                    props.onStage(candidate);
                    go("settings", { review: "1" });
                  },
                },
                "Copy to Settings"
              ),
              h(
                "span",
                { className: "petasos-secondary" },
                draftIsEmpty(props.draft)
                  ? "Nothing is saved until you press Save there."
                  : "Copying adds this trial to the unsaved changes already in Settings. Nothing is saved until you press Save there."
              )
            )
          : null
      )
    : null;

  var clashes = copyState[0] || [];
  var settingRows = rowsByPath(catalog && catalog.settings);
  var settingLabels = (catalog && catalog.labels) || {};
  return h(
    "div",
    { className: "petasos-stack" },
    h(
      "div",
      { className: "petasos-split petasos-split-try" },
      h("div", { className: "petasos-stack" }, input, trialPanel),
      h("div", null, output)
    ),
    h(C.ConfirmDialog, {
      open: clashes.length > 0,
      title: "Replace unsaved changes in Settings?",
      description:
        "Settings already has a different unsaved value for: " +
        clashes
          .map(function (path) {
            return settingLabels[path] || rowLabel(settingRows[path] || { path: path });
          })
          .join(", ") +
        ". Copying replaces " +
        (clashes.length === 1 ? "it" : "them") +
        " with the trial's value. Your other unsaved changes are kept.",
      confirmLabel: "Replace and copy",
      cancelLabel: "Keep mine",
      onCancel: function () {
        copyState[1](null);
      },
      onConfirm: function () {
        copyState[1](null);
        props.onStage(candidate);
        go("settings", { review: "1" });
      },
    })
  );
}
