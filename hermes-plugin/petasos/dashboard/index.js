/*
 * Petasos tab for the Hermes dashboard.
 *
 * Generated from src/ by scripts/build_dashboard.py. Edit the files in src/
 * and run that script; a test fails when this file is stale.
 *
 * Plain script, no build step: React, the components and the API client
 * all come from window.__HERMES_PLUGIN_SDK__. Every Petasos fact shown here
 * comes from /api/plugins/petasos/.
 */
(function () {
  "use strict";

  // ===== src/00-kit.js =====
  // ---------------------------------------------------------------------------
  // Kit: the Hermes SDK, the API client, and small shared pieces.
  //
  // Everything visual comes from Hermes: its React, its components (Card,
  // Button, Badge, Select, Input, Label, ConfirmDialog, Toast), its fonts and
  // its colour variables. Where the SDK does not export a Hermes control
  // (Segmented, Switch), the tab draws the same markup with the same tokens.
  // Everything Petasos knows (roles, levels, settings, labels, rules,
  // sentences) comes from the plugin's API at /api/plugins/petasos/. This file
  // holds interface wording only.
  // ---------------------------------------------------------------------------

  var SDK = window.__HERMES_PLUGIN_SDK__;
  var PLUGINS = window.__HERMES_PLUGINS__;
  if (!SDK || !PLUGINS || !SDK.React) {
    return;
  }

  var React = SDK.React;
  var h = React.createElement;
  var Fragment = React.Fragment;
  var useState = SDK.hooks.useState;
  var useEffect = SDK.hooks.useEffect;
  var useCallback = SDK.hooks.useCallback;
  var useMemo = SDK.hooks.useMemo;
  var useRef = SDK.hooks.useRef;
  var C = SDK.components;
  var cn = SDK.utils.cn;

  var API = "/api/plugins/petasos";

  // One request to the plugin API. A failure is thrown as an ApiFailure with
  // the HTTP status and the API's own code and sentence when it sent one.
  function ApiFailure(status, code, message, path) {
    this.status = status;
    this.code = code;
    this.message = message;
    this.path = path || null;
  }

  // Hermes's fetchJSON throws an error carrying ``status`` and the raw
  // ``body``. Older hosts threw Error("<status>: <body>"); both are read.
  function parseFailure(err) {
    var raw = err && err.message ? String(err.message) : String(err || "");
    var status = 0;
    var body = "";
    if (err && typeof err.status === "number") {
      status = err.status;
      body = typeof err.body === "string" ? err.body : "";
    } else {
      var match = raw.match(/^(\d{3}):\s*([\s\S]*)$/);
      status = match ? Number(match[1]) : 0;
      body = match ? match[2] : "";
    }
    try {
      var parsed = JSON.parse(body);
      if (parsed && parsed.error) {
        return new ApiFailure(status, parsed.error.code, parsed.error.message, parsed.error.path);
      }
      if (parsed && typeof parsed.detail === "string") {
        return new ApiFailure(status, "http", parsed.detail, null);
      }
    } catch (_e) {
      // Not JSON. Fall through.
    }
    if (status === 0) {
      return new ApiFailure(0, "unreachable", "The dashboard could not reach Petasos.", null);
    }
    return new ApiFailure(status, "http", "Petasos answered with an error (" + status + ").", null);
  }

  function call(path, options) {
    var init = { method: (options && options.method) || "GET" };
    if (options && options.body !== undefined) {
      init.body = JSON.stringify(options.body);
      init.headers = { "Content-Type": "application/json" };
    }
    return SDK.fetchJSON(API + path, init).catch(function (err) {
      throw parseFailure(err);
    });
  }

  function query(params) {
    var parts = [];
    Object.keys(params).forEach(function (key) {
      var value = params[key];
      if (value === undefined || value === null || value === "") return;
      parts.push(encodeURIComponent(key) + "=" + encodeURIComponent(String(value)));
    });
    return parts.length ? "?" + parts.join("&") : "";
  }

  // ---------------------------------------------------------------------------
  // The tab's own address: #overview, #activity?event=…, #settings?rule=…
  // The view lives in the hash so a link (and the browser's back button) can
  // open a view, an event, or the settings for one rule.
  // ---------------------------------------------------------------------------

  var VIEWS = ["overview", "activity", "tryit", "settings"];

  // Hermes adds ?profile=… to the address on arrival and drops the fragment.
  // Put back the fragment the page was opened with, once, so a pasted link
  // still opens the view it names.
  (function restoreArrivalHash() {
    if (window.location.hash) return;
    var entries = window.performance && window.performance.getEntriesByType
      ? window.performance.getEntriesByType("navigation")
      : [];
    var first = entries && entries[0] && entries[0].name;
    var at = first ? first.indexOf("#") : -1;
    if (at < 0) return;
    var fragment = first.slice(at);
    if (VIEWS.indexOf(fragment.slice(1).split("?")[0]) < 0) return;
    window.history.replaceState(window.history.state, "", window.location.pathname + window.location.search + fragment);
  })();

  function readRoute() {
    var raw = (window.location.hash || "").replace(/^#/, "");
    var parts = raw.split("?");
    var view = VIEWS.indexOf(parts[0]) >= 0 ? parts[0] : "overview";
    var params = {};
    if (parts[1]) {
      parts[1].split("&").forEach(function (pair) {
        var kv = pair.split("=");
        if (kv[0]) params[decodeURIComponent(kv[0])] = decodeURIComponent(kv[1] || "");
      });
    }
    return { view: view, params: params };
  }

  function go(view, params) {
    var next = "#" + view + query(params || {});
    if (window.location.hash !== next) {
      window.location.hash = next;
    }
  }

  function useRoute() {
    var state = useState(readRoute);
    useEffect(function () {
      function onChange() {
        state[1](readRoute());
      }
      window.addEventListener("hashchange", onChange);
      return function () {
        window.removeEventListener("hashchange", onChange);
      };
    }, []);
    return state[0];
  }

  // Run ``load`` now and every ``ms`` while the page is visible. Polling is
  // the only refresh: the API has no stream. A hidden tab does not poll.
  function usePoll(load, ms, deps) {
    useEffect(function () {
      var stopped = false;
      function tick() {
        if (!stopped && document.visibilityState !== "hidden") load();
      }
      load();
      var timer = window.setInterval(tick, ms);
      document.addEventListener("visibilitychange", tick);
      return function () {
        stopped = true;
        window.clearInterval(timer);
        document.removeEventListener("visibilitychange", tick);
      };
    }, deps);
  }

  // ---------------------------------------------------------------------------
  // Names. Every name a person reads comes from the API's labels. These look
  // them up; a name the API did not label is shown as it was sent.
  // ---------------------------------------------------------------------------

  function roleOf(catalog, name) {
    return ((catalog && catalog.roles) || []).filter(function (role) {
      return role.name === name;
    })[0];
  }

  function levelOf(catalog, name) {
    return ((catalog && catalog.levels) || []).filter(function (level) {
      return level.name === name;
    })[0];
  }

  function roleLabel(catalog, name) {
    var role = roleOf(catalog, name);
    return (role && role.label) || name || "";
  }

  function levelLabel(catalog, name) {
    var level = levelOf(catalog, name);
    return (level && level.label) || name || "";
  }

  function rowsByPath(rows) {
    var found = {};
    (rows || []).forEach(function (row) {
      found[row.path] = row;
    });
    return found;
  }

  function sectionsByPath(catalog) {
    var found = {};
    ((catalog && catalog.sections) || []).forEach(function (item) {
      found[item.path] = item;
    });
    return found;
  }

  function rowLabel(row) {
    return (row && row.label) || (row && row.path) || "";
  }

  // Where a value comes from, in words. The job and strictness are named by
  // their labels.
  function originText(origin, stored, catalog) {
    if (origin === "role") return "From the job (" + roleLabel(catalog, stored && stored.role) + ")";
    if (origin === "level") return "From strictness (" + levelLabel(catalog, stored && stored.level) + ")";
    if (origin === "override") return "Your setting";
    if (origin === "default") return "Default";
    return "Unknown";
  }

  // One value as a person reads it. A choice uses the API's label for it.
  function showValue(value, row) {
    if (value === null || value === undefined) return "not set";
    if (row && row.choice_labels && Object.prototype.hasOwnProperty.call(row.choice_labels, String(value))) {
      return row.choice_labels[String(value)];
    }
    if (value === true) return "On";
    if (value === false) return "Off";
    if (Array.isArray(value)) return value.length ? value.join(", ") : "none";
    if (typeof value === "object") {
      var keys = Object.keys(value);
      if (!keys.length) return "none";
      return keys
        .map(function (key) {
          return key + ": " + showValue(value[key]);
        })
        .join(", ");
    }
    return String(value);
  }

  function plural(count, one, many) {
    return count + " " + (count === 1 ? one : many || one + "s");
  }

  function capital(word) {
    var text = String(word || "");
    return text ? text.charAt(0).toUpperCase() + text.slice(1).toLowerCase() : "";
  }

  // ---------------------------------------------------------------------------
  // Time. Lists show a full date when the record spans days; details show the
  // year and the time zone. Relative age is secondary.
  // ---------------------------------------------------------------------------

  function whenText(seconds) {
    if (typeof seconds !== "number") return "";
    // Hermes's timeAgo takes unix seconds (its type comment says milliseconds).
    return SDK.utils.timeAgo(seconds);
  }

  function sameDay(a, b) {
    return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  }

  function listTime(seconds) {
    if (typeof seconds !== "number") return "";
    var date = new Date(seconds * 1000);
    var now = new Date();
    var clock = date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
    if (sameDay(date, now)) return "Today " + clock;
    var options = { day: "numeric", month: "short" };
    if (date.getFullYear() !== now.getFullYear()) options.year = "numeric";
    return date.toLocaleDateString(undefined, options) + " " + clock;
  }

  function fullTime(seconds) {
    if (typeof seconds !== "number") return "";
    return new Date(seconds * 1000).toLocaleString(undefined, {
      weekday: "short",
      day: "numeric",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      timeZoneName: "short",
    });
  }

  function clockTime(ms) {
    return new Date(ms).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }

  // ---------------------------------------------------------------------------
  // Small pieces built from Hermes components.
  // ---------------------------------------------------------------------------

  // A Hermes Card with the title row Hermes uses on its own pages.
  function Panel(props) {
    return h(
      C.Card,
      { className: cn("petasos-panel", props.className), id: props.id },
      props.title || props.actions
        ? h(
            C.CardHeader,
            { className: "petasos-panel-head" },
            h(
              "div",
              { className: "petasos-panel-headrow" },
              h(
                "div",
                { className: "petasos-panel-titles" },
                props.title
                  ? h(C.CardTitle, { className: "text-sm petasos-panel-title", id: props.titleId }, props.title)
                  : null,
                props.description ? h("p", { className: "petasos-panel-desc" }, props.description) : null
              ),
              props.actions ? h("div", { className: "petasos-panel-actions" }, props.actions) : null
            )
          )
        : null,
      h(C.CardContent, { className: cn("petasos-panel-body", props.bodyClassName) }, props.children)
    );
  }

  // A status that carries a safety meaning (outcome, severity, verdict, check
  // state): Hermes's sans at a readable size, with stronger contrast. Words
  // always say the same thing as the colour.
  var TONES = ["success", "warning", "destructive", "neutral"];

  function Status(props) {
    var tone = TONES.indexOf(props.tone) >= 0 ? props.tone : "neutral";
    return h(
      "span",
      {
        className: cn("petasos-status", "petasos-status-" + tone, props.large && "petasos-status-large", props.className),
        title: props.title,
      },
      h("span", { className: "petasos-status-dot", "aria-hidden": true }),
      props.children
    );
  }

  // An incidental label: Hermes's own badge, as Hermes draws it.
  function Tag(props) {
    return h(C.Badge, { tone: props.tone || "secondary", className: cn("petasos-tag", props.className), title: props.title }, props.children);
  }

  var SEVERITY_TONE = {
    critical: "destructive",
    high: "destructive",
    medium: "warning",
    low: "neutral",
    info: "neutral",
  };

  function Severity(props) {
    var severity = String(props.value || "").toLowerCase();
    if (!severity) return h("span", { className: "petasos-none", "aria-label": "No severity" }, "—");
    return h(Status, { tone: SEVERITY_TONE[severity] || "neutral" }, capital(severity));
  }

  function outcomeTone(code) {
    var destructive = ["blocked", "stopped", "declined", "not_stopped", "attempt_blocked", "block"];
    var warning = ["asked", "attempt_asked", "flagged", "allowed", "degraded", "unchecked", "approve", "flag", "none"];
    if (destructive.indexOf(code) >= 0) return "destructive";
    if (warning.indexOf(code) >= 0) return "warning";
    if (code === "approved" || code === "allow") return "success";
    return "neutral";
  }

  // A notice. The tone is a dot and a word, not a thick edge; only an
  // exceptional warning (``strong``) keeps the marked edge.
  function Notice(props) {
    var tone = props.tone || "info";
    return h(
      "div",
      {
        className: cn("petasos-notice", "petasos-notice-" + tone, props.strong && "petasos-notice-strong", props.className),
        role: tone === "destructive" ? "alert" : "status",
      },
      h(
        "div",
        { className: "petasos-notice-text" },
        props.title
          ? h(
              "p",
              { className: "petasos-notice-title" },
              h("span", { className: "petasos-notice-dot", "aria-hidden": true }),
              props.title
            )
          : null,
        props.children ? h("div", { className: "petasos-notice-body" }, props.children) : null
      ),
      props.action ? h("div", { className: "petasos-notice-action" }, props.action) : null
    );
  }

  // The empty list, as Hermes's Sessions page draws it: a small icon, a short
  // title, one line, on the page background.
  function Empty(props) {
    return h(
      "div",
      { className: "petasos-empty", role: "status" },
      h(Icon, { name: props.icon || "clock", className: "petasos-empty-icon" }),
      h("p", { className: "petasos-empty-title" }, props.title),
      props.children ? h("p", { className: "petasos-empty-body" }, props.children) : null,
      props.action ? h("div", { className: "petasos-empty-action" }, props.action) : null
    );
  }

  // Outline icons drawn inline in the current colour, the style Hermes's
  // pages use. No image files.
  var ICONS = {
    clock: ["M12 6v6l4 2", "M12 2a10 10 0 1 0 0 20a10 10 0 1 0 0-20"],
    chevron: ["M9 6l6 6l-6 6"],
    copy: ["M9 9h11v11H9z", "M5 15H4V4h11v1"],
    search: ["M11 4a7 7 0 1 0 0 14a7 7 0 1 0 0-14", "M20 20l-4-4"],
    shield: ["M12 3l8 3v6c0 5-3.5 8-8 9c-4.5-1-8-4-8-9V6z"],
  };

  function Icon(props) {
    return h(
      "svg",
      {
        className: cn("petasos-icon", props.className),
        viewBox: "0 0 24 24",
        width: props.size || 16,
        height: props.size || 16,
        fill: "none",
        stroke: "currentColor",
        strokeWidth: 1.75,
        strokeLinecap: "round",
        strokeLinejoin: "round",
        "aria-hidden": true,
        focusable: "false",
      },
      (ICONS[props.name] || []).map(function (d, i) {
        return h("path", { key: i, d: d });
      })
    );
  }

  function Btn(props) {
    var rest = Object.assign({}, props);
    delete rest.children;
    rest.type = rest.type || "button";
    rest.size = rest.size || "sm";
    return h(C.Button, rest, props.children);
  }

  // A text action: underlined, so it reads as a link in every theme.
  function LinkButton(props) {
    return h(
      "button",
      {
        type: "button",
        className: cn("petasos-link", props.className),
        onClick: props.onClick,
        "aria-label": props.label,
        "aria-expanded": props.expanded,
        disabled: props.disabled,
      },
      props.children
    );
  }

  function Mono(props) {
    return h("code", { className: cn("petasos-mono", props.className), title: props.title }, props.children);
  }

  // A technical identifier that may wrap only after its separators, never
  // in the middle of a word.
  function Ident(props) {
    var text = String(props.children || "");
    var parts = [];
    var buffer = "";
    for (var i = 0; i < text.length; i += 1) {
      buffer += text[i];
      if (/[./_:-]/.test(text[i]) && i < text.length - 1) {
        parts.push(buffer);
        parts.push(h("wbr", { key: "w" + i }));
        buffer = "";
      }
    }
    parts.push(buffer);
    return h("code", { className: cn("petasos-mono petasos-ident", props.className) }, parts);
  }

  function CopyButton(props) {
    var doneState = useState(false);
    return h(
      "button",
      {
        type: "button",
        className: "petasos-copy",
        "aria-label": props.label || "Copy",
        title: props.label || "Copy",
        onClick: function () {
          var text = String(props.value || "");
          var write = navigator.clipboard && navigator.clipboard.writeText ? navigator.clipboard.writeText(text) : Promise.reject();
          write
            .then(function () {
              doneState[1](true);
              window.setTimeout(function () {
                doneState[1](false);
              }, 1500);
            })
            .catch(function () {});
        },
      },
      h(Icon, { name: "copy", size: 14 }),
      h("span", { className: "petasos-copy-text" }, doneState[0] ? "Copied" : "Copy")
    );
  }

  // Hermes's Select with a label above it.
  function Choice(props) {
    return h(
      "div",
      { className: cn("petasos-choice", props.className) },
      props.label ? h(C.Label, { className: "petasos-label", htmlFor: props.id }, props.label) : null,
      h(
        C.Select,
        {
          id: props.id,
          value: props.value,
          onValueChange: props.onChange,
          disabled: props.disabled,
          placeholder: props.placeholder,
          "aria-describedby": props.describedBy,
        },
        props.options.map(function (option) {
          return h(C.SelectOption, { key: option.value, value: option.value }, option.label);
        })
      )
    );
  }

  // Arrow keys move along a row of options, as a native radio group does.
  function arrowKeys(event, values, current, onChange, focusPrefix) {
    var keys = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1, Home: "first", End: "last" };
    var step = keys[event.key];
    if (step === undefined) return;
    event.preventDefault();
    var index = values.indexOf(current);
    var next;
    if (step === "first") next = 0;
    else if (step === "last") next = values.length - 1;
    else next = (index + step + values.length) % values.length;
    onChange(values[next]);
    var target = document.getElementById(focusPrefix + values[next]);
    if (target) target.focus();
  }

  // Hermes's Segmented control (Logs, Sessions): joined rectangular buttons,
  // the chosen one filled. One choice of several, with arrow keys.
  function Segmented(props) {
    var values = props.options.map(function (option) {
      return option.value;
    });
    var prefix = (props.id || "petasos-seg") + "-";
    return h(
      "div",
      {
        className: cn("petasos-segmented", props.className),
        role: "radiogroup",
        "aria-label": props.label,
        "aria-labelledby": props.labelledBy,
      },
      props.options.map(function (option) {
        var active = option.value === props.value;
        return h(
          "button",
          {
            key: option.value,
            id: prefix + option.value,
            type: "button",
            role: "radio",
            "aria-checked": active,
            tabIndex: active || (props.value === undefined && option === props.options[0]) ? 0 : -1,
            disabled: props.disabled,
            className: cn("petasos-segment", active && "petasos-segment-on"),
            onClick: function () {
              props.onChange(option.value);
            },
            onKeyDown: function (event) {
              arrowKeys(event, values, props.value, props.onChange, prefix);
            },
          },
          option.label,
          option.mark ? h("span", { className: "petasos-segment-mark" }, option.mark) : null
        );
      })
    );
  }

  // Hermes's Switch: a rectangular track and square thumb at the end of a row.
  function Switch(props) {
    return h(
      "button",
      {
        id: props.id,
        type: "button",
        role: "switch",
        "aria-checked": Boolean(props.checked),
        "aria-labelledby": props.labelledBy,
        "aria-label": props.label,
        "aria-describedby": props.describedBy,
        disabled: props.disabled,
        className: cn("petasos-switch", props.checked && "petasos-switch-on"),
        onClick: function () {
          props.onChange(!props.checked);
        },
      },
      h("span", { className: "petasos-switch-thumb", "aria-hidden": true })
    );
  }

  // The view tabs, drawn as Hermes's enclosed segmented tabs (Sessions, Logs).
  function ViewTabs(props) {
    var values = props.views.map(function (view) {
      return view.value;
    });
    return h(
      "div",
      { className: "petasos-segmented petasos-viewtabs", role: "tablist", "aria-label": props.label },
      props.views.map(function (view) {
        var active = view.value === props.value;
        return h(
          "button",
          {
            key: view.value,
            id: "petasos-tab-" + view.value,
            type: "button",
            role: "tab",
            "aria-selected": active,
            "aria-controls": "petasos-panel",
            tabIndex: active ? 0 : -1,
            className: cn("petasos-segment", active && "petasos-segment-on"),
            onClick: function () {
              props.onChange(view.value);
            },
            onKeyDown: function (event) {
              arrowKeys(event, values, props.value, props.onChange, "petasos-tab-");
            },
          },
          view.label
        );
      })
    );
  }

  // Config's field layout: the label, the setting's key in faint mono, one
  // plain sentence, then the control across the panel. A switch sits at the
  // end of the label row instead.
  function Field(props) {
    var labelId = props.id + "-label";
    var helpId = props.id + "-help";
    return h(
      "div",
      {
        className: cn("petasos-field", props.inline && "petasos-field-inline", props.className),
        id: props.rowId,
      },
      h(
        "div",
        { className: "petasos-field-head" },
        h(
          "div",
          { className: "petasos-field-text" },
          h(C.Label, { className: "petasos-field-label", htmlFor: props.inline ? undefined : props.id, id: labelId }, props.label),
          props.path ? h("span", { className: "petasos-field-key" }, props.path) : null,
          props.help ? h("p", { className: "petasos-field-help", id: helpId }, props.help) : null
        ),
        props.inline ? h("div", { className: "petasos-field-switch" }, props.control) : null
      ),
      props.inline ? null : h("div", { className: "petasos-field-control" }, props.control),
      props.children
    );
  }

  function KeyValues(props) {
    return h(
      "dl",
      { className: cn("petasos-kv", props.stacked && "petasos-kv-stacked", props.className) },
      props.rows
        .filter(function (row) {
          return row && row[1] !== undefined && row[1] !== null && row[1] !== "";
        })
        .map(function (row) {
          return h(Fragment, { key: row[0] }, h("dt", null, row[0]), h("dd", null, row[1]));
        })
    );
  }

  // Scroll the nearest scrolling container so ``element`` is in view. Unlike
  // scrollIntoView, this never moves Hermes's own page frame.
  function revealInView(element, where) {
    if (!element) return;
    var node = element.parentElement;
    while (node && node !== document.body) {
      var style = window.getComputedStyle(node);
      if (/(auto|scroll)/.test(style.overflowY) && node.scrollHeight > node.clientHeight) break;
      node = node.parentElement;
    }
    if (!node || node === document.body) return;
    var box = element.getBoundingClientRect();
    var frame = node.getBoundingClientRect();
    var offset = box.top - frame.top;
    if (where === "center") offset -= (frame.height - box.height) / 2;
    else offset -= 16;
    node.scrollTop += offset;
  }
  // ---------------------------------------------------------------------------
  // The layout rules from src/style.css, added once. Hermes's manifest can name
  // a style sheet, but the installer copies only this script, so it carries
  // the rules itself.
  // ---------------------------------------------------------------------------

  var STYLE = "/*\n * Petasos tab layout. Every colour, font and size is a Hermes variable, so\n * the tab follows whichever Hermes theme is active. Where Hermes's SDK does\n * not export a control (Segmented, Switch), these rules draw it the way\n * Hermes's own source does. No palette, font or icon set of Petasos's own.\n */\n\n.petasos {\n  display: flex;\n  flex-direction: column;\n  gap: 1rem;\n  width: 100%;\n  min-width: 0;\n  color: var(--midground);\n  font-size: 0.9rem;\n  line-height: 1.5;\n}\n\n.petasos code,\n.petasos pre {\n  background: transparent !important;\n  color: inherit;\n}\n\n.petasos p {\n  margin: 0;\n}\n\n.petasos .sr-only {\n  position: absolute;\n  width: 1px;\n  height: 1px;\n  padding: 0;\n  margin: -1px;\n  overflow: hidden;\n  clip: rect(0, 0, 0, 0);\n  white-space: nowrap;\n  border: 0;\n}\n\n/* Keyboard focus is always visible, in the theme's ring colour, on every\n * control the tab draws. Hermes's own controls keep their ring too. */\n.petasos button:focus-visible,\n.petasos a:focus-visible,\n.petasos input:focus-visible,\n.petasos textarea:focus-visible,\n.petasos summary:focus-visible,\n.petasos [tabindex]:focus-visible {\n  outline: 2px solid var(--midground);\n  outline-offset: 2px;\n}\n\n.petasos-detail:focus,\n.petasos-subhead:focus,\n.petasos [id=\"petasos-review-title\"]:focus {\n  outline: none;\n}\n\n.petasos-stack {\n  display: flex;\n  flex-direction: column;\n  gap: 1rem;\n  min-width: 0;\n}\n\n.petasos-grid-2 {\n  display: grid;\n  grid-template-columns: repeat(2, minmax(0, 1fr));\n  gap: 1rem;\n  align-items: start;\n}\n\n.petasos-grid-3 {\n  display: grid;\n  grid-template-columns: repeat(3, minmax(0, 1fr));\n  gap: 1rem;\n  align-items: start;\n}\n\n.petasos-help {\n  font-size: 0.82rem;\n  line-height: 1.5;\n  color: var(--text-secondary, var(--midground));\n}\n\n.petasos-faint {\n  color: var(--text-tertiary, var(--midground));\n}\n\n.petasos-strong,\n.petasos strong {\n  font-weight: 700;\n}\n\n.petasos-block {\n  display: block;\n}\n\n.petasos-gap-above {\n  margin-top: 0.4rem;\n}\n\n.petasos-end {\n  padding: 0.9rem 0 0.4rem;\n  text-align: center;\n}\n\n/* Links are underlined everywhere, so they read as links in a theme that\n * draws all text in one colour. */\n.petasos-link,\n.petasos a.petasos-link {\n  background: none;\n  border: 0;\n  padding: 0;\n  font: inherit;\n  font-size: inherit;\n  color: inherit;\n  text-decoration: underline;\n  text-decoration-thickness: 1px;\n  text-underline-offset: 3px;\n  cursor: pointer;\n  text-align: left;\n}\n\n.petasos-link:hover {\n  text-decoration-thickness: 2px;\n}\n\n.petasos-link:disabled {\n  cursor: not-allowed;\n  opacity: 0.6;\n}\n\n.petasos-row-actions {\n  display: flex;\n  flex-wrap: wrap;\n  align-items: center;\n  gap: 0.6rem;\n}\n\n.petasos-count {\n  font-family: var(--theme-font-mono);\n  font-size: 0.8rem;\n  color: var(--text-secondary, var(--midground));\n}\n\n.petasos-mono {\n  font-family: var(--theme-font-mono);\n  font-size: 0.82rem;\n}\n\n/* A technical id wraps only at the <wbr> after its separators. */\n.petasos-ident {\n  overflow-wrap: normal;\n  word-break: normal;\n  white-space: normal;\n}\n\n.petasos-idrow {\n  display: inline-flex;\n  flex-wrap: wrap;\n  align-items: baseline;\n  gap: 0.25rem 0.6rem;\n}\n\n.petasos-copy {\n  display: inline-flex;\n  align-items: center;\n  gap: 0.25rem;\n  padding: 0.05rem 0.3rem;\n  border: 1px solid transparent;\n  background: none;\n  color: var(--text-secondary, var(--midground));\n  font-size: 0.75rem;\n  cursor: pointer;\n}\n\n.petasos-copy:hover {\n  border-color: var(--color-border);\n  color: var(--midground);\n}\n\n.petasos-icon {\n  display: inline-block;\n  flex-shrink: 0;\n  vertical-align: middle;\n}\n\n/* ---- Top bar: Hermes's enclosed tabs ------------------------------- */\n\n.petasos-topbar {\n  display: flex;\n  align-items: center;\n  justify-content: space-between;\n  gap: 1rem;\n  flex-wrap: wrap;\n}\n\n.petasos-topbar-main {\n  display: flex;\n  align-items: center;\n  gap: 0.75rem;\n  flex-wrap: wrap;\n}\n\n.petasos-topbar-side {\n  display: flex;\n  align-items: center;\n  gap: 0.75rem;\n}\n\n.petasos-unsaved {\n  background: none;\n  border: 0;\n  padding: 0;\n  font-size: 0.82rem;\n  color: inherit;\n  text-decoration: underline;\n  text-underline-offset: 3px;\n  cursor: pointer;\n}\n\n/* Hermes's Segmented: joined rectangular buttons, the chosen one filled\n * with the theme's ink. The view tabs use the same treatment, as Sessions\n * and Logs do. */\n.petasos-segmented {\n  display: inline-flex;\n  flex-wrap: wrap;\n  border: 1px solid color-mix(in srgb, var(--midground) 18%, transparent);\n  background: color-mix(in srgb, var(--background) 30%, transparent);\n  max-width: 100%;\n}\n\n.petasos-segment {\n  display: inline-flex;\n  align-items: center;\n  gap: 0.35rem;\n  height: 2rem;\n  padding: 0 0.8rem;\n  border: 0;\n  border-right: 1px solid color-mix(in srgb, var(--midground) 18%, transparent);\n  background: transparent;\n  color: var(--text-secondary, var(--midground));\n  font-family: var(--font-mondwest);\n  font-size: 0.86rem;\n  letter-spacing: 0.04em;\n  white-space: nowrap;\n  cursor: pointer;\n  transition: background-color 120ms, color 120ms;\n}\n\n.petasos-segment:last-child {\n  border-right: 0;\n}\n\n.petasos-segment:hover {\n  background: color-mix(in srgb, var(--midground) 10%, transparent);\n  color: var(--midground);\n}\n\n.petasos-segment-on,\n.petasos-segment-on:hover {\n  background: var(--midground);\n  color: var(--background);\n}\n\n.petasos-segment:disabled {\n  cursor: not-allowed;\n  opacity: 0.55;\n}\n\n.petasos-viewtabs .petasos-segment {\n  height: 2.2rem;\n  padding: 0 1.1rem;\n  font-size: 0.92rem;\n  font-weight: 600;\n}\n\n/* ---- Hermes's Switch ------------------------------------------------ */\n\n.petasos-switch {\n  position: relative;\n  display: inline-flex;\n  align-items: center;\n  flex-shrink: 0;\n  width: 2.25rem;\n  height: 1.25rem;\n  padding: 0;\n  border: 1px solid color-mix(in srgb, var(--midground) 22%, transparent);\n  background: var(--background);\n  cursor: pointer;\n  transition: background-color 120ms, border-color 120ms;\n}\n\n.petasos-switch-thumb {\n  display: block;\n  width: 0.875rem;\n  height: 0.875rem;\n  margin-left: 0.125rem;\n  background: color-mix(in srgb, var(--midground) 40%, transparent);\n  transition: transform 120ms;\n}\n\n.petasos-switch-on {\n  background: color-mix(in srgb, var(--midground) 15%, transparent);\n  border-color: color-mix(in srgb, var(--midground) 35%, transparent);\n}\n\n.petasos-switch-on .petasos-switch-thumb {\n  transform: translateX(1rem);\n  background: var(--midground);\n}\n\n.petasos-switch:disabled {\n  cursor: not-allowed;\n  opacity: 0.5;\n}\n\n.petasos-inline-switch {\n  display: inline-flex;\n  align-items: center;\n  gap: 0.6rem;\n  font-size: 0.86rem;\n}\n\n/* ---- Panels --------------------------------------------------------- */\n\n.petasos-panel {\n  min-width: 0;\n}\n\n.petasos-panel-head {\n  padding: 0.85rem 1.1rem 0.6rem;\n}\n\n.petasos-panel-headrow {\n  display: flex;\n  align-items: flex-start;\n  justify-content: space-between;\n  gap: 1rem;\n}\n\n.petasos-panel-titles {\n  display: flex;\n  flex-direction: column;\n  gap: 0.3rem;\n  min-width: 0;\n}\n\n.petasos-panel-desc {\n  font-size: 0.85rem;\n  color: var(--text-secondary, var(--midground));\n}\n\n.petasos-panel-actions {\n  display: flex;\n  align-items: center;\n  gap: 0.75rem;\n  flex-shrink: 0;\n}\n\n.petasos-panel-body {\n  display: flex;\n  flex-direction: column;\n  gap: 0.85rem;\n  padding: 0.9rem 1.1rem 1.1rem;\n}\n\n.petasos-label,\n.petasos-filter-label,\n.petasos-sections-title {\n  font-family: var(--font-mondwest);\n  font-size: 0.8rem;\n  font-weight: 600;\n  letter-spacing: 0.06em;\n  text-transform: uppercase;\n  color: var(--text-secondary, var(--midground));\n}\n\n.petasos-subhead {\n  margin: 0.4rem 0 0;\n  font-family: var(--font-mondwest);\n  font-size: 0.82rem;\n  font-weight: 700;\n  letter-spacing: 0.06em;\n  text-transform: uppercase;\n}\n\n/* ---- Status: safety meaning, readable ------------------------------- */\n\n.petasos-status {\n  display: inline-flex;\n  align-items: center;\n  gap: 0.4rem;\n  padding: 0.2rem 0.55rem;\n  border: 1px solid var(--petasos-tone-line);\n  background: var(--petasos-tone-fill);\n  color: var(--petasos-tone-ink);\n  font-family: var(--theme-font-sans);\n  font-size: 0.8rem;\n  font-weight: 600;\n  line-height: 1.25;\n  letter-spacing: 0.01em;\n  white-space: nowrap;\n}\n\n.petasos-status-large {\n  padding: 0.3rem 0.7rem;\n  font-size: 0.92rem;\n}\n\n.petasos-status-dot {\n  width: 0.45rem;\n  height: 0.45rem;\n  border-radius: 50%;\n  background: var(--petasos-tone-dot);\n  flex-shrink: 0;\n}\n\n/* Dark themes: bright ink on a subdued fill. */\n.petasos-status-success {\n  --petasos-tone-ink: color-mix(in srgb, var(--color-success) 55%, white);\n  --petasos-tone-dot: var(--color-success);\n  --petasos-tone-fill: color-mix(in srgb, var(--color-success) 12%, transparent);\n  --petasos-tone-line: color-mix(in srgb, var(--color-success) 50%, transparent);\n}\n\n.petasos-status-warning {\n  --petasos-tone-ink: color-mix(in srgb, var(--color-warning) 55%, white);\n  --petasos-tone-dot: var(--color-warning);\n  --petasos-tone-fill: color-mix(in srgb, var(--color-warning) 12%, transparent);\n  --petasos-tone-line: color-mix(in srgb, var(--color-warning) 50%, transparent);\n}\n\n.petasos-status-destructive {\n  --petasos-tone-ink: color-mix(in srgb, var(--color-destructive) 45%, white);\n  --petasos-tone-dot: color-mix(in srgb, var(--color-destructive) 70%, white);\n  --petasos-tone-fill: color-mix(in srgb, var(--color-destructive) 16%, transparent);\n  --petasos-tone-line: color-mix(in srgb, var(--color-destructive) 60%, transparent);\n}\n\n.petasos-status-neutral {\n  --petasos-tone-ink: var(--midground);\n  --petasos-tone-dot: color-mix(in srgb, var(--midground) 55%, transparent);\n  --petasos-tone-fill: color-mix(in srgb, var(--midground) 7%, transparent);\n  --petasos-tone-line: color-mix(in srgb, var(--midground) 30%, transparent);\n}\n\n/* Light themes: the status colours are pale on a pale field, so the ink is\n * darkened. The tab marks a light theme from Hermes's own background. */\n.petasos-light .petasos-status-success {\n  --petasos-tone-ink: color-mix(in srgb, var(--color-success) 45%, black);\n  --petasos-tone-fill: color-mix(in srgb, var(--color-success) 12%, transparent);\n  --petasos-tone-line: color-mix(in srgb, var(--color-success) 55%, black);\n}\n\n.petasos-light .petasos-status-warning {\n  --petasos-tone-ink: color-mix(in srgb, var(--color-warning) 45%, black);\n  --petasos-tone-fill: color-mix(in srgb, var(--color-warning) 14%, transparent);\n  --petasos-tone-line: color-mix(in srgb, var(--color-warning) 60%, black);\n}\n\n.petasos-light .petasos-status-destructive {\n  --petasos-tone-ink: color-mix(in srgb, var(--color-destructive) 70%, black);\n  --petasos-tone-dot: var(--color-destructive);\n  --petasos-tone-fill: color-mix(in srgb, var(--color-destructive) 10%, transparent);\n  --petasos-tone-line: color-mix(in srgb, var(--color-destructive) 70%, black);\n}\n\n.petasos-tag {\n  white-space: nowrap;\n}\n\n.petasos-none {\n  color: var(--text-tertiary, var(--midground));\n}\n\n/* ---- Notices: a dot and a title; only exceptional warnings keep an edge */\n\n.petasos-notice {\n  display: flex;\n  align-items: flex-start;\n  justify-content: space-between;\n  gap: 1rem;\n  padding: 0.8rem 1rem;\n  border: 1px solid var(--color-border);\n  background: var(--color-card);\n}\n\n.petasos-notice-strong {\n  border-left: 3px solid var(--color-destructive);\n}\n\n.petasos-notice-text {\n  display: flex;\n  flex-direction: column;\n  gap: 0.3rem;\n  min-width: 0;\n}\n\n.petasos-notice-title {\n  display: flex;\n  align-items: center;\n  gap: 0.5rem;\n  font-weight: 700;\n  font-size: 0.9rem;\n}\n\n.petasos-notice-dot {\n  width: 0.5rem;\n  height: 0.5rem;\n  border-radius: 50%;\n  flex-shrink: 0;\n  background: var(--midground);\n}\n\n.petasos-notice-warning .petasos-notice-dot {\n  background: var(--color-warning);\n}\n\n.petasos-notice-destructive .petasos-notice-dot {\n  background: var(--color-destructive);\n}\n\n.petasos-notice-success .petasos-notice-dot {\n  background: var(--color-success);\n}\n\n.petasos-notice-body {\n  font-size: 0.85rem;\n  line-height: 1.55;\n  padding-left: 1rem;\n}\n\n.petasos-notice-body p + p {\n  margin-top: 0.3rem;\n}\n\n.petasos-notice-action {\n  flex-shrink: 0;\n}\n\n.petasos-steps {\n  margin: 0.4rem 0 0;\n  padding-left: 1.2rem;\n  display: flex;\n  flex-direction: column;\n  gap: 0.25rem;\n}\n\n/* ---- Empty list, as Sessions draws it ------------------------------- */\n\n.petasos-empty {\n  display: flex;\n  flex-direction: column;\n  align-items: center;\n  gap: 0.3rem;\n  padding: 3rem 1rem;\n  text-align: center;\n}\n\n.petasos-empty-icon {\n  width: 1.75rem;\n  height: 1.75rem;\n  margin-bottom: 0.35rem;\n  color: var(--text-secondary, var(--midground));\n}\n\n.petasos-empty-title {\n  font-size: 0.95rem;\n  font-weight: 600;\n}\n\n.petasos-empty-body {\n  max-width: 30rem;\n  font-size: 0.82rem;\n  color: var(--text-secondary, var(--midground));\n}\n\n.petasos-empty-action {\n  margin-top: 0.75rem;\n}\n\n/* ---- Key and value lists -------------------------------------------- */\n\n.petasos-kv {\n  display: grid;\n  grid-template-columns: minmax(7rem, max-content) minmax(0, 1fr);\n  gap: 0.45rem 1.25rem;\n  margin: 0;\n  font-size: 0.86rem;\n}\n\n.petasos-kv dt {\n  font-family: var(--font-mondwest);\n  font-size: 0.78rem;\n  font-weight: 600;\n  letter-spacing: 0.06em;\n  text-transform: uppercase;\n  color: var(--text-secondary, var(--midground));\n  padding-top: 0.1rem;\n}\n\n.petasos-kv dd {\n  margin: 0;\n  min-width: 0;\n}\n\n.petasos-kv-stacked {\n  grid-template-columns: minmax(0, 1fr);\n  gap: 0.15rem;\n}\n\n.petasos-kv-stacked dd {\n  margin-bottom: 0.6rem;\n}\n\n/* ---- Overview: status ----------------------------------------------- */\n\n.petasos-verdict {\n  display: grid;\n  grid-template-columns: minmax(0, 1fr) minmax(12rem, 16rem);\n  gap: 1.5rem;\n  padding: 1.1rem 1.2rem;\n  border: 1px solid var(--color-border);\n  background: var(--color-card);\n}\n\n.petasos-verdict-main {\n  display: flex;\n  flex-direction: column;\n  gap: 0.6rem;\n  min-width: 0;\n}\n\n.petasos-verdict-head {\n  display: flex;\n  align-items: center;\n  flex-wrap: wrap;\n  gap: 0.75rem;\n}\n\n.petasos-verdict-title {\n  margin: 0;\n  font-size: 1.08rem;\n  font-weight: 700;\n  line-height: 1.35;\n}\n\n.petasos-verdict-reason {\n  max-width: 52rem;\n  font-size: 0.88rem;\n}\n\n.petasos-verdict-side {\n  display: flex;\n  flex-direction: column;\n  align-items: flex-start;\n  gap: 0.5rem;\n  padding-left: 1.25rem;\n  border-left: 1px solid var(--color-border);\n}\n\n.petasos-coverage {\n  margin-top: 0.35rem;\n}\n\n/* ---- Overview: last 24 hours ---------------------------------------- */\n\n.petasos-stats {\n  display: flex;\n  flex-wrap: wrap;\n  gap: 0.5rem 2.25rem;\n  margin: 0;\n}\n\n.petasos-stat dt {\n  font-family: var(--font-mondwest);\n  font-size: 0.78rem;\n  font-weight: 600;\n  letter-spacing: 0.06em;\n  text-transform: uppercase;\n  color: var(--text-secondary, var(--midground));\n}\n\n.petasos-stat dd {\n  margin: 0;\n}\n\n.petasos-stat-value {\n  background: none;\n  border: 0;\n  padding: 0;\n  color: inherit;\n  font-family: var(--font-rules-expanded);\n  font-size: 1.5rem;\n  font-weight: 700;\n  line-height: 1.2;\n  cursor: pointer;\n  text-decoration: underline;\n  text-decoration-thickness: 1px;\n  text-underline-offset: 4px;\n}\n\n.petasos-stat-alarm .petasos-stat-value,\n.petasos-stat-alarm dt {\n  color: color-mix(in srgb, var(--color-destructive) 45%, white);\n}\n\n.petasos-light .petasos-stat-alarm .petasos-stat-value,\n.petasos-light .petasos-stat-alarm dt {\n  color: color-mix(in srgb, var(--color-destructive) 70%, black);\n}\n\n.petasos-mini-list {\n  list-style: none;\n  margin: 0;\n  padding: 0;\n  border-top: 1px solid var(--color-border);\n}\n\n.petasos-mini-row {\n  display: grid;\n  grid-template-columns: 5.5rem minmax(0, 1fr) auto 1rem;\n  align-items: center;\n  gap: 0.9rem;\n  width: 100%;\n  padding: 0.55rem 0.15rem;\n  border: 0;\n  border-bottom: 1px solid var(--color-border);\n  background: none;\n  color: inherit;\n  font: inherit;\n  font-size: 0.86rem;\n  text-align: left;\n  cursor: pointer;\n}\n\n.petasos-mini-row:hover {\n  background: color-mix(in srgb, var(--midground) 6%, transparent);\n}\n\n.petasos-mini-when {\n  font-family: var(--theme-font-mono);\n  font-size: 0.78rem;\n  color: var(--text-secondary, var(--midground));\n}\n\n.petasos-mini-text {\n  overflow: hidden;\n  text-overflow: ellipsis;\n  white-space: nowrap;\n}\n\n.petasos-repeat {\n  font-family: var(--theme-font-mono);\n  font-size: 0.8rem;\n  font-weight: 700;\n}\n\n.petasos-chevron {\n  color: var(--text-secondary, var(--midground));\n}\n\n/* ---- Overview: the two choices -------------------------------------- */\n\n.petasos-setup {\n  gap: 0.6rem 1.75rem;\n  align-items: start;\n}\n\n.petasos-setup .petasos-optlist {\n  align-self: start;\n}\n\n.petasos-choose {\n  display: flex;\n  flex-direction: column;\n  gap: 0.35rem;\n  min-width: 0;\n}\n\n.petasos-choose .petasos-segmented {\n  margin-top: 0.35rem;\n  align-self: flex-start;\n}\n\n.petasos-optlist {\n  list-style: none;\n  margin: 0.4rem 0 0;\n  padding: 0;\n  display: flex;\n  flex-direction: column;\n  gap: 0.3rem;\n}\n\n.petasos-opt {\n  display: grid;\n  grid-template-columns: 8.5rem minmax(0, 1fr);\n  gap: 0.75rem;\n  font-size: 0.83rem;\n  line-height: 1.45;\n  color: var(--text-secondary, var(--midground));\n}\n\n.petasos-opt-name {\n  font-weight: 600;\n}\n\n.petasos-opt-on {\n  color: var(--midground);\n}\n\n.petasos-opt-on .petasos-opt-name {\n  font-weight: 800;\n}\n\n.petasos-opt-note {\n  font-style: italic;\n}\n\n.petasos-preview {\n  display: flex;\n  flex-direction: column;\n  gap: 0.6rem;\n  padding-top: 1rem;\n  border-top: 1px solid var(--color-border);\n}\n\n.petasos-consequence {\n  font-size: 0.9rem;\n  max-width: 56rem;\n}\n\n.petasos-when {\n  font-size: 0.86rem;\n  font-weight: 600;\n}\n\n.petasos-disclosure {\n  display: flex;\n  flex-direction: column;\n  align-items: flex-start;\n  gap: 0.6rem;\n  font-size: 0.85rem;\n}\n\n/* A change: label and sentence above, value at full width below, where it\n * would come from beneath. */\n.petasos-changes {\n  list-style: none;\n  margin: 0;\n  padding: 0;\n  width: 100%;\n}\n\n.petasos-change {\n  display: flex;\n  flex-direction: column;\n  gap: 0.25rem;\n  padding: 0.65rem 0;\n  border-bottom: 1px solid var(--color-border);\n}\n\n.petasos-change:first-child {\n  border-top: 1px solid var(--color-border);\n}\n\n.petasos-change-name {\n  font-weight: 700;\n  font-size: 0.88rem;\n}\n\n.petasos-change-values {\n  font-size: 0.88rem;\n}\n\n.petasos-before {\n  text-decoration: line-through;\n  color: var(--text-secondary, var(--midground));\n}\n\n.petasos-arrow {\n  color: var(--text-secondary, var(--midground));\n}\n\n.petasos-diff {\n  list-style: none;\n  margin: 0;\n  padding: 0;\n  display: flex;\n  flex-direction: column;\n  gap: 0.15rem;\n  font-size: 0.85rem;\n}\n\n.petasos-diff-sign {\n  display: inline-block;\n  width: 1rem;\n  font-weight: 700;\n}\n\n.petasos-provenance {\n  font-size: 0.78rem;\n  color: var(--text-tertiary, var(--midground));\n}\n\n.petasos-key {\n  font-family: var(--theme-font-mono);\n  font-size: 0.76rem;\n}\n\n/* ---- Overview: checks ------------------------------------------------ */\n\n.petasos-scanners {\n  list-style: none;\n  margin: 0;\n  padding: 0;\n  display: flex;\n  flex-direction: column;\n}\n\n.petasos-scanner {\n  display: flex;\n  flex-direction: column;\n  align-items: flex-start;\n  gap: 0.3rem;\n  padding: 0.65rem 0;\n  border-bottom: 1px solid var(--color-border);\n  font-size: 0.86rem;\n}\n\n.petasos-scanner:last-child {\n  border-bottom: 0;\n}\n\n.petasos-scanner-head {\n  display: flex;\n  align-items: center;\n  gap: 0.6rem;\n  width: 100%;\n}\n\n.petasos-scanner-name {\n  font-weight: 700;\n  margin-right: auto;\n}\n\n.petasos-fix {\n  font-size: 0.83rem;\n  display: flex;\n  flex-direction: column;\n  gap: 0.3rem;\n}\n\n/* ---- Activity -------------------------------------------------------- */\n\n.petasos-filters {\n  display: flex;\n  flex-direction: column;\n  gap: 0.8rem;\n}\n\n.petasos-filter-row {\n  display: flex;\n  flex-wrap: wrap;\n  align-items: flex-end;\n  gap: 0.75rem 1.25rem;\n}\n\n.petasos-filter-group {\n  display: flex;\n  align-items: center;\n  gap: 0.6rem;\n}\n\n.petasos-search {\n  position: relative;\n  flex: 1 1 18rem;\n  max-width: 28rem;\n}\n\n.petasos-search input {\n  padding-left: 2rem;\n}\n\n.petasos-search-icon {\n  position: absolute;\n  left: 0.6rem;\n  top: 50%;\n  transform: translateY(-50%);\n  color: var(--text-secondary, var(--midground));\n  pointer-events: none;\n}\n\n.petasos-tz {\n  align-self: center;\n}\n\n.petasos-filter-selects {\n  display: grid;\n  grid-template-columns: repeat(4, minmax(0, 1fr));\n  gap: 0.75rem;\n}\n\n.petasos-choice {\n  display: flex;\n  flex-direction: column;\n  gap: 0.35rem;\n  min-width: 0;\n}\n\n.petasos-split {\n  display: grid;\n  grid-template-columns: minmax(0, 1fr);\n  gap: 1rem;\n  align-items: start;\n}\n\n.petasos-split-open {\n  grid-template-columns: minmax(0, 1.3fr) minmax(24rem, 1fr);\n}\n\n/* With an event open, each row folds to two lines so the sentence keeps\n * its width: what happened and the outcome, then when and the severity. */\n.petasos-split-open .petasos-event-header {\n  display: none;\n}\n\n.petasos-split-open .petasos-event {\n  grid-template-columns: minmax(0, 1fr) auto 1rem;\n  row-gap: 0.3rem;\n}\n\n.petasos-split-open .petasos-event-what {\n  grid-column: 1;\n  grid-row: 1;\n}\n\n.petasos-split-open .petasos-event-outcome {\n  grid-column: 2;\n  grid-row: 1;\n  justify-self: end;\n}\n\n.petasos-split-open .petasos-event-when {\n  grid-column: 1;\n  grid-row: 2;\n}\n\n.petasos-split-open .petasos-event-when .petasos-block {\n  display: inline;\n  margin-right: 0.6rem;\n}\n\n.petasos-split-open .petasos-event-severity {\n  grid-column: 2;\n  grid-row: 2;\n  justify-self: end;\n}\n\n.petasos-split-open .petasos-chevron {\n  grid-column: 3;\n  grid-row: 1 / span 2;\n}\n\n.petasos-split-open .petasos-group-bar {\n  padding-left: 0.6rem;\n}\n\n.petasos-split-even {\n  grid-template-columns: repeat(2, minmax(0, 1fr));\n}\n\n.petasos-split-main {\n  min-width: 0;\n}\n\n.petasos-list-card {\n  padding: 0.4rem 1rem 0.6rem;\n}\n\n.petasos-event-header,\n.petasos-event {\n  display: grid;\n  grid-template-columns: 8.5rem minmax(0, 1fr) 6rem 11.5rem 1rem;\n  align-items: center;\n  gap: 1rem;\n}\n\n.petasos-event-header {\n  padding: 0.6rem 0.6rem;\n  border-bottom: 1px solid var(--color-border);\n  font-family: var(--font-mondwest);\n  font-size: 0.76rem;\n  font-weight: 600;\n  letter-spacing: 0.06em;\n  text-transform: uppercase;\n  color: var(--text-secondary, var(--midground));\n}\n\n.petasos-events {\n  list-style: none;\n  margin: 0;\n  padding: 0;\n}\n\n.petasos-event-item {\n  border-bottom: 1px solid var(--color-border);\n}\n\n.petasos-events-nested {\n  border-top: 1px dashed var(--color-border);\n  margin-left: 1.5rem;\n}\n\n.petasos-events-nested .petasos-event-item:last-child {\n  border-bottom: 0;\n}\n\n.petasos-event {\n  width: 100%;\n  padding: 0.65rem 0.6rem;\n  border: 0;\n  background: none;\n  color: inherit;\n  font: inherit;\n  text-align: left;\n  cursor: pointer;\n}\n\n.petasos-event:hover {\n  background: color-mix(in srgb, var(--midground) 6%, transparent);\n}\n\n.petasos-event:hover .petasos-chevron {\n  color: var(--midground);\n}\n\n.petasos-event-selected,\n.petasos-event-selected:hover {\n  background: color-mix(in srgb, var(--midground) 11%, transparent);\n}\n\n.petasos-event-when {\n  font-family: var(--theme-font-mono);\n  font-size: 0.78rem;\n  line-height: 1.45;\n}\n\n.petasos-event-what {\n  display: flex;\n  flex-direction: column;\n  gap: 0.15rem;\n  min-width: 0;\n}\n\n.petasos-event-summary {\n  font-size: 0.9rem;\n}\n\n.petasos-event-meta {\n  display: flex;\n  flex-wrap: wrap;\n  align-items: center;\n  gap: 0.5rem;\n  font-size: 0.8rem;\n  color: var(--text-secondary, var(--midground));\n}\n\n.petasos-group-bar {\n  display: flex;\n  align-items: center;\n  gap: 1rem;\n  padding: 0 0.6rem 0.6rem 10.1rem;\n  font-size: 0.8rem;\n}\n\n.petasos-more {\n  display: flex;\n  justify-content: center;\n  padding-top: 0.75rem;\n}\n\n.petasos-detail {\n  position: sticky;\n  top: 0.5rem;\n  display: flex;\n  flex-direction: column;\n  gap: 0.75rem;\n  padding: 1rem 1.1rem;\n  border: 1px solid var(--color-border);\n  background: var(--color-card);\n  min-width: 0;\n}\n\n.petasos-detail-head {\n  display: flex;\n  align-items: center;\n  justify-content: space-between;\n}\n\n.petasos-detail-title {\n  margin: 0;\n  font-size: 1rem;\n  font-weight: 700;\n  line-height: 1.4;\n}\n\n.petasos-detail-note {\n  font-size: 0.86rem;\n  font-weight: 600;\n}\n\n.petasos-raw summary {\n  cursor: pointer;\n  font-size: 0.83rem;\n  text-decoration: underline;\n  text-underline-offset: 3px;\n}\n\n.petasos-raw[open] summary {\n  margin-bottom: 0.5rem;\n}\n\n/* ---- Try it ---------------------------------------------------------- */\n\n.petasos-textarea {\n  width: 100%;\n  padding: 0.6rem 0.75rem;\n  border: 1px solid color-mix(in srgb, var(--midground) 18%, transparent);\n  background: color-mix(in srgb, var(--background) 40%, transparent);\n  color: inherit;\n  font: inherit;\n  font-size: 0.88rem;\n  line-height: 1.5;\n  resize: vertical;\n}\n\n.petasos-mono-area {\n  font-family: var(--theme-font-mono);\n  font-size: 0.82rem;\n}\n\n.petasos-textarea:disabled {\n  opacity: 0.55;\n  cursor: not-allowed;\n}\n\n.petasos-field-error {\n  font-size: 0.83rem;\n  font-weight: 700;\n  color: color-mix(in srgb, var(--color-destructive) 45%, white);\n}\n\n.petasos-light .petasos-field-error {\n  color: color-mix(in srgb, var(--color-destructive) 70%, black);\n}\n\n.petasos-decision {\n  display: flex;\n  flex-direction: column;\n  align-items: flex-start;\n  gap: 0.45rem;\n}\n\n.petasos-decision-text {\n  font-size: 0.9rem;\n}\n\n.petasos-compare {\n  display: grid;\n  grid-template-columns: repeat(2, minmax(0, 1fr));\n  gap: 1.25rem;\n}\n\n.petasos-compare-cell {\n  display: flex;\n  flex-direction: column;\n  gap: 0.45rem;\n}\n\n.petasos-compare-cell + .petasos-compare-cell {\n  padding-left: 1.25rem;\n  border-left: 1px solid var(--color-border);\n}\n\n.petasos-message,\n.petasos-marked {\n  margin: 0;\n  padding: 0.65rem 0.8rem;\n  border: 1px solid var(--color-border);\n  font-family: var(--theme-font-mono);\n  font-size: 0.8rem;\n  line-height: 1.55;\n  white-space: pre-wrap;\n  overflow-wrap: anywhere;\n}\n\n.petasos-mark {\n  background: color-mix(in srgb, var(--color-destructive) 18%, transparent);\n  color: inherit;\n  text-decoration: underline;\n  text-decoration-color: var(--color-destructive);\n  text-decoration-thickness: 2px;\n  text-underline-offset: 3px;\n}\n\n.petasos-mark-n {\n  font-weight: 700;\n  margin-right: 0.1rem;\n}\n\n.petasos-findings {\n  list-style: none;\n  margin: 0;\n  padding: 0;\n  display: flex;\n  flex-direction: column;\n}\n\n.petasos-finding {\n  display: grid;\n  grid-template-columns: 1.6rem minmax(0, 1fr);\n  gap: 0.6rem;\n  padding: 0.6rem 0;\n  border-bottom: 1px solid var(--color-border);\n}\n\n.petasos-finding-n {\n  font-family: var(--theme-font-mono);\n  font-size: 0.82rem;\n  font-weight: 700;\n  text-align: center;\n  padding-top: 0.05rem;\n}\n\n.petasos-finding-body {\n  display: flex;\n  flex-direction: column;\n  gap: 0.35rem;\n  min-width: 0;\n}\n\n.petasos-finding-head {\n  display: flex;\n  align-items: flex-start;\n  justify-content: space-between;\n  gap: 0.75rem;\n}\n\n.petasos-finding-sentence {\n  font-size: 0.9rem;\n}\n\n.petasos-finding-meta {\n  font-size: 0.8rem;\n  color: var(--text-secondary, var(--midground));\n}\n\n.petasos-took-part {\n  list-style: none;\n  margin: 0;\n  padding: 0;\n  display: grid;\n  grid-template-columns: max-content max-content minmax(0, 1fr);\n  gap: 0.45rem 0.85rem;\n  align-items: center;\n}\n\n.petasos-took-part li {\n  display: contents;\n}\n\n.petasos-took-name {\n  font-weight: 700;\n  font-size: 0.86rem;\n}\n\n.petasos-quieted {\n  list-style: none;\n  margin: 0;\n  padding: 0;\n  display: flex;\n  flex-direction: column;\n  gap: 0.35rem;\n  font-size: 0.83rem;\n}\n\n.petasos-quieted li {\n  display: flex;\n  flex-wrap: wrap;\n  gap: 0.25rem 0.75rem;\n  align-items: baseline;\n}\n\n.petasos-advanced summary {\n  cursor: pointer;\n  font-size: 0.85rem;\n  text-decoration: underline;\n  text-underline-offset: 3px;\n}\n\n.petasos-advanced[open] {\n  display: flex;\n  flex-direction: column;\n  gap: 0.45rem;\n}\n\n/* ---- Settings: Config's layout -------------------------------------- */\n\n.petasos-settings-toolbar {\n  display: flex;\n  flex-wrap: wrap;\n  align-items: center;\n  gap: 0.75rem 1.5rem;\n}\n\n.petasos-settings-toolbar .petasos-search {\n  max-width: 26rem;\n}\n\n.petasos-savebox {\n  display: flex;\n  align-items: center;\n  gap: 0.6rem;\n  margin-left: auto;\n}\n\n.petasos-settings-body {\n  display: grid;\n  grid-template-columns: 13.5rem minmax(0, 1fr);\n  gap: 1rem;\n  align-items: start;\n}\n\n.petasos-sections {\n  display: flex;\n  flex-direction: column;\n  padding: 0.6rem 0.5rem;\n  border: 1px solid var(--color-border);\n  background: var(--color-card);\n  position: sticky;\n  top: 0.5rem;\n}\n\n.petasos-sections-title {\n  padding: 0.25rem 0.5rem 0.4rem;\n  font-size: 0.74rem;\n}\n\n.petasos-section {\n  display: flex;\n  align-items: center;\n  gap: 0.4rem;\n  padding: 0.35rem 0.5rem;\n  border: 0;\n  background: none;\n  color: var(--text-secondary, var(--midground));\n  font-family: var(--theme-font-mono);\n  font-size: 0.8rem;\n  text-align: left;\n  cursor: pointer;\n}\n\n.petasos-section:hover {\n  background: color-mix(in srgb, var(--midground) 7%, transparent);\n  color: var(--midground);\n}\n\n.petasos-section-on,\n.petasos-section-on:hover {\n  background: color-mix(in srgb, var(--midground) 12%, transparent);\n  color: var(--midground);\n  font-weight: 700;\n}\n\n.petasos-section-name {\n  margin-right: auto;\n}\n\n.petasos-section-changed {\n  font-size: 0.55rem;\n}\n\n.petasos-section-count {\n  font-size: 0.74rem;\n  color: var(--text-tertiary, var(--midground));\n}\n\n.petasos-settings-main {\n  min-width: 0;\n}\n\n.petasos-group {\n  display: flex;\n  flex-direction: column;\n  gap: 0.25rem;\n}\n\n.petasos-group-head {\n  display: flex;\n  align-items: center;\n  gap: 0.6rem;\n  padding-top: 0.75rem;\n}\n\n.petasos-group-name {\n  font-family: var(--font-mondwest);\n  font-size: 0.78rem;\n  font-weight: 700;\n  letter-spacing: 0.06em;\n  text-transform: uppercase;\n  color: var(--text-secondary, var(--midground));\n}\n\n.petasos-group-rule {\n  flex: 1;\n  border-top: 1px solid var(--color-border);\n}\n\n/* One field, as Config draws it: label, key, sentence, control beneath. */\n.petasos-field {\n  display: flex;\n  flex-direction: column;\n  gap: 0.35rem;\n  padding: 0.7rem 0 0.75rem;\n  scroll-margin: 1rem;\n}\n\n.petasos-field-head {\n  display: flex;\n  align-items: flex-start;\n  justify-content: space-between;\n  gap: 1.5rem;\n}\n\n.petasos-field-text {\n  display: flex;\n  flex-direction: column;\n  gap: 0.1rem;\n  min-width: 0;\n}\n\n.petasos-field-label {\n  font-family: var(--font-mondwest);\n  font-size: 0.86rem;\n  font-weight: 600;\n  letter-spacing: 0.04em;\n  text-transform: uppercase;\n}\n\n.petasos-field-key {\n  font-family: var(--theme-font-mono);\n  font-size: 0.76rem;\n  color: var(--text-tertiary, var(--midground));\n}\n\n.petasos-field-help {\n  font-size: 0.82rem;\n  color: var(--text-secondary, var(--midground));\n  max-width: 60rem;\n}\n\n.petasos-field-switch {\n  padding-top: 0.15rem;\n}\n\n.petasos-field-control {\n  min-width: 0;\n}\n\n.petasos-field-staged .petasos-field-label::after {\n  content: \" \u2022\";\n}\n\n.petasos-field-invalid input,\n.petasos-field-invalid textarea {\n  border-color: var(--color-destructive) !important;\n}\n\n.petasos-field-focused {\n  background: color-mix(in srgb, var(--midground) 5%, transparent);\n  margin: 0 -0.6rem;\n  padding-left: 0.6rem;\n  padding-right: 0.6rem;\n}\n\n.petasos-review .petasos-panel-body {\n  gap: 0.75rem;\n}\n\n.petasos-rule-helper .petasos-kv {\n  font-size: 0.85rem;\n}\n\n/* ---- Narrow ---------------------------------------------------------- */\n\n@media (max-width: 1100px) {\n  .petasos-split-open,\n  .petasos-split-even,\n  .petasos-grid-3 {\n    grid-template-columns: minmax(0, 1fr);\n  }\n  .petasos-detail {\n    position: static;\n  }\n  .petasos-filter-selects {\n    grid-template-columns: repeat(2, minmax(0, 1fr));\n  }\n}\n\n@media (max-width: 1000px) {\n  .petasos-grid-2,\n  .petasos-verdict,\n  .petasos-settings-body,\n  .petasos-compare {\n    grid-template-columns: minmax(0, 1fr);\n  }\n  .petasos-verdict-side {\n    padding-left: 0;\n    border-left: 0;\n    flex-direction: row;\n    align-items: center;\n  }\n  .petasos-compare-cell + .petasos-compare-cell {\n    padding-left: 0;\n    border-left: 0;\n  }\n  .petasos-sections {\n    position: static;\n    flex-direction: row;\n    flex-wrap: wrap;\n  }\n  .petasos-event-header {\n    display: none;\n  }\n  .petasos-event {\n    grid-template-columns: minmax(0, 1fr) auto 1rem;\n  }\n  .petasos-event-when {\n    grid-column: 1 / -1;\n  }\n  .petasos-event-severity {\n    display: none;\n  }\n  .petasos-group-bar {\n    padding-left: 0.6rem;\n  }\n  .petasos-opt {\n    grid-template-columns: 7rem minmax(0, 1fr);\n  }\n}\n";

  (function addStyle() {
    if (document.getElementById("petasos-tab-style")) return;
    var element = document.createElement("style");
    element.id = "petasos-tab-style";
    element.textContent = STYLE;
    document.head.appendChild(element);
  })();
  // ===== src/05-shared.js =====
  // ---------------------------------------------------------------------------
  // Shared: staged changes, the list of what a change would do, and grouping
  // of repeated events. Used by more than one view.
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

  function getIn(tree, path) {
    var node = tree;
    var parts = path.split(".");
    for (var i = 0; i < parts.length; i += 1) {
      if (!node || typeof node !== "object") return undefined;
      node = node[parts[i]];
    }
    return node;
  }

  var EMPTY_DRAFT = { overrides: {} };

  function draftIsEmpty(draft) {
    return (
      !draft ||
      (draft.enabled === undefined &&
        draft.role === undefined &&
        draft.level === undefined &&
        !Object.keys(draft.overrides || {}).length)
    );
  }

  function draftBody(draft) {
    var body = {};
    if (!draft) return body;
    if (draft.enabled !== undefined) body.enabled = draft.enabled;
    if (draft.role !== undefined) body.role = draft.role;
    if (draft.level !== undefined) body.level = draft.level;
    if (Object.keys(draft.overrides || {}).length) body.overrides = draft.overrides;
    return body;
  }

  function leafCount(tree) {
    var count = 0;
    (function walk(node) {
      Object.keys(node || {}).forEach(function (key) {
        var value = node[key];
        if (value && typeof value === "object" && !Array.isArray(value)) walk(value);
        else count += 1;
      });
    })(tree);
    return count;
  }

  // When a change applies, from the preview's restart flags and the labels.
  function whenItApplies(changes, rows) {
    var byPath = rowsByPath(rows);
    var waiting = (changes || []).filter(function (change) {
      return change.restart;
    });
    if (!waiting.length) return "Applies from the agent's next tool call. No restart is needed.";
    var names = waiting.map(function (change) {
      return rowLabel(byPath[change.path] || { path: change.path });
    });
    return (
      "Waits for Hermes to restart: " +
      names.join(", ") +
      ". " +
      (waiting.length < changes.length ? "The rest applies from the agent's next tool call." : "")
    ).trim();
  }

  // What a change would do, setting by setting: the label and plain sentence
  // above, the value below at full width, where it would come from beneath.
  function ChangeValues(props) {
    var before = props.before;
    var after = props.after;
    var row = props.row;
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
          return h(
            "li",
            { key: "+" + item },
            h("span", { className: "petasos-diff-sign", "aria-hidden": true }, "+"),
            h("span", { className: "sr-only" }, "Adds "),
            h(Ident, null, String(item))
          );
        }),
        removed.map(function (item) {
          return h(
            "li",
            { key: "-" + item },
            h("span", { className: "petasos-diff-sign", "aria-hidden": true }, "−"),
            h("span", { className: "sr-only" }, "Removes "),
            h(Ident, null, String(item))
          );
        })
      );
    }
    return h(
      "p",
      { className: "petasos-change-values" },
      h("span", { className: "petasos-before" }, showValue(before, row)),
      h("span", { "aria-hidden": true, className: "petasos-arrow" }, " → "),
      h("span", { className: "sr-only" }, " becomes "),
      h("strong", { className: "petasos-after" }, showValue(after, row))
    );
  }

  function ChangeList(props) {
    var changes = props.changes || [];
    var byPath = rowsByPath(props.rows);
    if (!changes.length) {
      return h("p", { className: "petasos-help" }, props.empty);
    }
    return h(
      "ul",
      { className: "petasos-changes", "aria-label": props.label || "What would change" },
      changes.map(function (change) {
        var row = byPath[change.path] || { path: change.path };
        return h(
          "li",
          { key: change.path, className: "petasos-change" },
          h("p", { className: "petasos-change-name" }, rowLabel(row)),
          row.help ? h("p", { className: "petasos-help" }, row.help) : null,
          h(ChangeValues, { before: change.before, after: change.after, row: row }),
          h(
            "p",
            { className: "petasos-provenance" },
            originText(change.origin_after, props.after || props.stored, props.catalog),
            change.origin_before !== change.origin_after
              ? " · was " + originText(change.origin_before, props.stored, props.catalog).toLowerCase()
              : "",
            change.restart ? " · waits for a Hermes restart" : "",
            " · ",
            h("span", { className: "petasos-key" }, change.path)
          )
        );
      })
    );
  }

  // Consecutive events that say the same thing about the same conversation
  // are one row with a count. The group can be opened to show each event.
  function groupEvents(events) {
    var groups = [];
    events.forEach(function (event) {
      var last = groups[groups.length - 1];
      var key = [
        event.summary,
        event.session_id || "",
        event.tool || "",
        (event.outcome && event.outcome.code) || "",
        String(event.severity || "").toLowerCase(),
      ].join("|");
      if (last && last.key === key) {
        last.events.push(event);
      } else {
        groups.push({ key: key, events: [event] });
      }
    });
    return groups;
  }
  // ===== src/10-overview.js =====
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
  // ===== src/20-activity.js =====
  // ---------------------------------------------------------------------------
  // Activity: what Petasos did and why, newest first, from the event record.
  // ---------------------------------------------------------------------------

  var RANGES = [
    { value: "1h", label: "1 hour", seconds: 3600 },
    { value: "24h", label: "24 hours", seconds: 86400 },
    { value: "7d", label: "7 days", seconds: 7 * 86400 },
    { value: "all", label: "All", seconds: null },
    { value: "custom", label: "Custom", seconds: null },
  ];

  // An outcome count on the overview opens the list filtered to it. These
  // are the API's outcome codes, matched against each event's outcome.
  var OUTCOME_CODES = {
    blocked: ["blocked", "stopped"],
    asked: ["asked"],
    flagged: ["flagged"],
    allowed: ["allowed"],
    not_stopped: ["not_stopped"],
  };

  var OUTCOME_FILTER_WORDS = {
    blocked: "blocked",
    asked: "asked a person",
    flagged: "flagged to the agent",
    allowed: "let through while paused",
    not_stopped: "settings changes not stopped",
  };

  // Seconds from a datetime-local value, read in the browser's time zone.
  function localSeconds(value) {
    if (!value) return null;
    var ms = new Date(value).getTime();
    return isFinite(ms) ? Math.floor(ms / 1000) : null;
  }

  function rangeWindow(filters) {
    if (filters.range === "custom") {
      return { since: localSeconds(filters.from), until: localSeconds(filters.to) };
    }
    var found = RANGES.filter(function (item) {
      return item.value === filters.range;
    })[0];
    if (!found || !found.seconds) return { since: null, until: null };
    return { since: Math.floor(Date.now() / 1000) - found.seconds, until: null };
  }

  function IntegrityStatus(props) {
    var integrity = props.integrity;
    if (!integrity) return null;
    if (integrity.mode === "verified") {
      return h(Status, { tone: "success", title: "Each record shown carries a signature that matches." }, "Signed · " + integrity.checked + " checked");
    }
    if (integrity.mode === "mixed") {
      return h(Status, { tone: "destructive" }, integrity.failed + " of " + integrity.checked + " do not match");
    }
    if (integrity.mode === "failed") {
      return h(Status, { tone: "destructive" }, "Signatures do not match");
    }
    return h(Status, { tone: "warning", title: integrity.reason }, "Not signed");
  }

  function IntegrityNotice(props) {
    var integrity = props.integrity;
    var signing = props.signing || {};
    var openState = useState(false);
    if (!integrity) return null;
    if (integrity.mode === "off") {
      return h(
        Notice,
        {
          tone: "warning",
          title: "Activity records cannot be checked for tampering yet",
          action: (signing.steps || []).length
            ? h(
                Btn,
                {
                  outlined: true,
                  "aria-expanded": openState[0],
                  onClick: function () {
                    openState[1](!openState[0]);
                  },
                },
                openState[0] ? "Hide the steps" : "Set up record checking"
              )
            : null,
        },
        h("p", null, "Protection still runs and every record is still written. Without a signature, something that can write to this profile could change a record unnoticed."),
        openState[0]
          ? h(
              "ol",
              { className: "petasos-steps" },
              (signing.steps || []).map(function (step) {
                return h("li", { key: step }, step);
              })
            )
          : null
      );
    }
    if (integrity.mode === "failed" || integrity.mode === "mixed") {
      return h(
        Notice,
        { tone: "destructive", strong: true, title: "Some records do not match their signatures" },
        "A marked record was changed after Petasos wrote it, or was written by something else. Do not trust those records."
      );
    }
    return null;
  }

  function ActivityFilters(props) {
    var filters = props.filters;
    var options = props.options || {};
    var searchState = useState(filters.q || "");
    useEffect(
      function () {
        searchState[1](filters.q || "");
      },
      [filters.q]
    );
    function set(key, value) {
      var next = Object.assign({}, filters);
      next[key] = value === "any" ? "" : value;
      if (key !== "outcome") next.outcome = "";
      props.onChange(next);
    }
    function listed(counts, labeller) {
      return [{ value: "any", label: "Any" }].concat(
        Object.keys(counts || {})
          .sort()
          .map(function (key) {
            return { value: key, label: (labeller ? labeller(key) : key) + " (" + counts[key] + ")" };
          })
      );
    }
    var active = ["kind", "tool", "session", "severity", "outcome", "q"].some(function (key) {
      return filters[key];
    });
    return h(
      "div",
      { className: "petasos-filters", role: "group", "aria-label": "Filter activity" },
      h(
        "div",
        { className: "petasos-filter-row" },
        h(
          "div",
          { className: "petasos-filter-group" },
          h("span", { className: "petasos-filter-label", id: "petasos-range-label" }, "Time"),
          h(Segmented, {
            id: "petasos-range",
            labelledBy: "petasos-range-label",
            value: filters.range,
            options: RANGES,
            onChange: function (value) {
              set("range", value);
            },
          })
        ),
        h(
          "form",
          {
            className: "petasos-search",
            role: "search",
            onSubmit: function (event) {
              event.preventDefault();
              set("q", searchState[0].trim());
            },
          },
          h(Icon, { name: "search", className: "petasos-search-icon" }),
          h(C.Input, {
            id: "petasos-activity-search",
            type: "search",
            "aria-label": "Search activity by event id or words",
            placeholder: "Search by event id or words…",
            value: searchState[0],
            onChange: function (event) {
              searchState[1](event.target.value);
            },
            onBlur: function () {
              if (searchState[0].trim() !== (filters.q || "")) set("q", searchState[0].trim());
            },
          })
        ),
        active
          ? h(
              Btn,
              {
                ghost: true,
                onClick: function () {
                  props.onChange({ range: filters.range, from: filters.from, to: filters.to });
                },
              },
              "Clear filters"
            )
          : null
      ),
      filters.range === "custom"
        ? h(
            "div",
            { className: "petasos-filter-row" },
            h(
              "div",
              { className: "petasos-choice" },
              h(C.Label, { className: "petasos-label", htmlFor: "petasos-from" }, "From"),
              h(C.Input, {
                id: "petasos-from",
                type: "datetime-local",
                value: filters.from || "",
                onChange: function (event) {
                  set("from", event.target.value);
                },
              })
            ),
            h(
              "div",
              { className: "petasos-choice" },
              h(C.Label, { className: "petasos-label", htmlFor: "petasos-to" }, "To"),
              h(C.Input, {
                id: "petasos-to",
                type: "datetime-local",
                value: filters.to || "",
                onChange: function (event) {
                  set("to", event.target.value);
                },
              })
            ),
            h("p", { className: "petasos-help petasos-tz" }, "Times are in your time zone (" + Intl.DateTimeFormat().resolvedOptions().timeZone + ").")
          )
        : null,
      h(
        "div",
        { className: "petasos-filter-selects" },
        h(Choice, {
          id: "petasos-filter-kind",
          label: "Kind",
          value: filters.kind || "any",
          options: listed(options.by_kind, function (kind) {
            return (options.kind_labels && options.kind_labels[kind]) || kind;
          }),
          onChange: function (value) {
            set("kind", value);
          },
        }),
        h(Choice, {
          id: "petasos-filter-tool",
          label: "Tool",
          value: filters.tool || "any",
          options: listed(options.by_tool),
          onChange: function (value) {
            set("tool", value);
          },
        }),
        h(Choice, {
          id: "petasos-filter-session",
          label: "Conversation",
          value: filters.session || "any",
          options: listed(options.by_session),
          onChange: function (value) {
            set("session", value);
          },
        }),
        h(Choice, {
          id: "petasos-filter-severity",
          label: "Severity",
          value: filters.severity || "any",
          options: listed(options.by_severity, capital),
          onChange: function (value) {
            set("severity", value);
          },
        })
      )
    );
  }

  function EventRow(props) {
    var event = props.event;
    var outcome = event.outcome || {};
    var failed = event.integrity && event.integrity.status === "failed";
    return h(
      "button",
      {
        type: "button",
        id: "petasos-event-" + event.scan_id,
        className: cn("petasos-event", props.selected && "petasos-event-selected", props.nested && "petasos-event-nested"),
        "aria-current": props.selected ? "true" : undefined,
        "aria-label": "Open details: " + event.summary + ", " + listTime(event.timestamp),
        onClick: props.onOpen,
      },
      h(
        "span",
        { className: "petasos-event-when" },
        h("span", { className: "petasos-block" }, listTime(event.timestamp)),
        h("span", { className: "petasos-block petasos-faint" }, whenText(event.timestamp))
      ),
      h(
        "span",
        { className: "petasos-event-what" },
        h("span", { className: "petasos-event-summary" }, event.summary),
        h(
          "span",
          { className: "petasos-event-meta" },
          event.tool ? h(Mono, null, event.tool) : null,
          event.session_id ? h("span", null, "in " + event.session_id) : null,
          failed ? h(Status, { tone: "destructive" }, "Signature does not match") : null
        )
      ),
      h("span", { className: "petasos-event-severity" }, h(Severity, { value: event.severity })),
      h("span", { className: "petasos-event-outcome" }, h(Status, { tone: outcomeTone(outcome.code) }, outcome.label || "Recorded")),
      h(Icon, { name: "chevron", className: "petasos-chevron" })
    );
  }

  // Repeats are one row with a count; opening the group lists each event.
  function EventGroup(props) {
    var group = props.group;
    var openState = useState(false);
    var first = group.events[0];
    var last = group.events[group.events.length - 1];
    var count = group.events.length;
    var inside = group.events.some(function (event) {
      return event.scan_id === props.selectedId;
    });
    var open = openState[0] || inside;
    if (count === 1) {
      return h(
        "li",
        { className: "petasos-event-item" },
        h(EventRow, { event: first, selected: first.scan_id === props.selectedId, onOpen: function () { props.onOpen(first); } })
      );
    }
    return h(
      "li",
      { className: "petasos-event-item petasos-event-group" },
      h(EventRow, {
        event: first,
        selected: first.scan_id === props.selectedId,
        onOpen: function () {
          props.onOpen(first);
        },
      }),
      h(
        "div",
        { className: "petasos-group-bar" },
        h(
          "span",
          { className: "petasos-repeat" },
          "Repeated " + count + " times, " + listTime(last.timestamp) + " to " + listTime(first.timestamp)
        ),
        h(
          LinkButton,
          {
            expanded: open,
            onClick: function () {
              openState[1](!open);
            },
          },
          open ? "Hide the " + count : "Show all " + count
        )
      ),
      open
        ? h(
            "ul",
            { className: "petasos-events petasos-events-nested", "aria-label": "The " + count + " repeated events" },
            group.events.slice(1).map(function (event) {
              return h(
                "li",
                { key: event.scan_id, className: "petasos-event-item" },
                h(EventRow, {
                  event: event,
                  nested: true,
                  selected: event.scan_id === props.selectedId,
                  onOpen: function () {
                    props.onOpen(event);
                  },
                })
              );
            })
          )
        : null
    );
  }

  // Everything recorded about one event, with the ways to act on it.
  var SHOWN_FIELDS = {
    scan_id: 1, timestamp: 1, event_type: 1, tool: 1, session_id: 1, severity: 1, rule_id: 1, reason: 1,
    summary: 1, outcome: 1, kind_label: 1, rule_sentence: 1, integrity: 1, sig: 1, matched_note: 1,
    target: 1, outcome_note: 1,
  };

  function EventDetail(props) {
    var event = props.event;
    var ref = useRef(null);
    var others = Object.keys(event)
      .filter(function (key) {
        return !SHOWN_FIELDS[key] && event[key] !== null && event[key] !== "" && event[key] !== undefined;
      })
      .sort();
    var rule = event.rule_id ? String(event.rule_id).replace(/^plugin_rule:/, "") : "";
    var integrity = event.integrity || {};
    var outcome = event.outcome || {};
    useEffect(
      function () {
        if (ref.current) ref.current.focus({ preventScroll: true });
      },
      [event.scan_id]
    );
    return h(
      "aside",
      {
        className: "petasos-detail",
        "aria-labelledby": "petasos-detail-title",
        tabIndex: -1,
        ref: ref,
        onKeyDown: function (keyEvent) {
          if (keyEvent.key === "Escape") props.onClose();
        },
      },
      h(
        "div",
        { className: "petasos-detail-head" },
        h(Status, { tone: outcomeTone(outcome.code), large: true }, outcome.label || "Recorded"),
        h(Btn, { ghost: true, onClick: props.onClose, "aria-label": "Close event details" }, "Close")
      ),
      h("h3", { className: "petasos-detail-title", id: "petasos-detail-title" }, event.summary),
      event.outcome_note ? h("p", { className: "petasos-detail-note" }, event.outcome_note) : null,
      h(KeyValues, {
        rows: [
          ["When", h(Fragment, null, fullTime(event.timestamp), h("span", { className: "petasos-faint" }, " · " + whenText(event.timestamp)))],
          ["Kind", event.kind_label ? h(Fragment, null, event.kind_label, " ", h(Mono, { className: "petasos-faint" }, event.event_type)) : event.event_type],
          ["Tool", event.tool ? h(Mono, null, event.tool) : null],
          ["Conversation", event.session_id ? h(Mono, null, event.session_id) : null],
          ["Severity", event.severity ? h(Severity, { value: event.severity }) : null],
        ],
      }),
      h(KeyValues, {
        stacked: true,
        rows: [
          ["Target", event.target ? h(Ident, null, event.target) : null],
          [
            "Rule",
            rule
              ? h(
                  Fragment,
                  null,
                  event.rule_sentence ? h("span", { className: "petasos-block" }, event.rule_sentence) : null,
                  h("span", { className: "petasos-idrow" }, h(Ident, null, rule), h(CopyButton, { value: rule, label: "Copy rule id" }))
                )
              : null,
          ],
          ["Rule's note", event.reason && !event.target ? event.reason : null],
          ["Matched text", event.matched_note || null],
          ["Signature", integrity.meaning || null],
        ],
      }),
      h(
        "div",
        { className: "petasos-row-actions" },
        rule && rule.indexOf("petasos.syntactic.") === 0
          ? h(Btn, { outlined: true, onClick: function () { go("settings", { rule: rule }); } }, "Rule settings")
          : null,
        event.session_id
          ? h(
              Btn,
              {
                ghost: true,
                onClick: function () {
                  props.onFilter({ session: event.session_id });
                },
              },
              "Filter to this conversation"
            )
          : null
      ),
      others.length
        ? h(
            "details",
            { className: "petasos-raw" },
            h("summary", null, "Other recorded fields (" + others.length + ")"),
            h(KeyValues, {
              stacked: true,
              rows: others.map(function (key) {
                var value = event[key];
                return [key, h(Mono, null, typeof value === "object" ? JSON.stringify(value) : String(value))];
              }),
            })
          )
        : null,
      h(
        "p",
        { className: "petasos-help petasos-idrow" },
        "Event id ",
        h(Ident, null, event.scan_id),
        h(CopyButton, { value: event.scan_id, label: "Copy event id" })
      )
    );
  }

  function filtersFromRoute(params) {
    return {
      range: params.range || "24h",
      from: params.from || "",
      to: params.to || "",
      q: params.q || "",
      kind: params.kind || "",
      tool: params.tool || "",
      session: params.session || "",
      severity: params.severity || "",
      outcome: params.outcome || "",
    };
  }

  function Activity(props) {
    var params = props.route.params;
    var filters = filtersFromRoute(params);
    var selectedId = params.event || "";
    var pageState = useState(null);
    var page = pageState[0];
    var olderState = useState([]);
    var older = olderState[0];
    var optionsState = useState(null);
    var failureState = useState(null);
    var loadingMore = useState(false);
    var extraEvent = useState(null);

    function setFilters(next) {
      var route = Object.assign({}, next);
      Object.keys(route).forEach(function (key) {
        if (!route[key]) delete route[key];
      });
      go("activity", route);
    }

    var codes = filters.outcome ? OUTCOME_CODES[filters.outcome] || [] : [];
    var span = rangeWindow(filters);
    var request = {
      limit: 100,
      since: span.since,
      until: span.until,
      q: filters.q,
      kind: filters.kind,
      tool: filters.tool,
      session: filters.session,
      severity: filters.severity,
    };
    var key = JSON.stringify([request, filters.outcome, filters.range === "custom" ? 0 : Math.floor(Date.now() / 600000)]);

    usePoll(
      function () {
        var now = rangeWindow(filters);
        var live = Object.assign({}, request, { since: now.since, until: now.until });
        call("/activity" + query(live))
          .then(function (body) {
            pageState[1](body);
            failureState[1](null);
          })
          .catch(function (failure) {
            failureState[1](failure);
          });
        call("/activity/summary" + query({ since: now.since, until: now.until, q: filters.q }))
          .then(optionsState[1])
          .catch(function () {});
      },
      15000,
      [key, props.refreshKey]
    );
    useEffect(
      function () {
        olderState[1]([]);
      },
      [key]
    );

    function loadOlder() {
      var last = older.length ? older[older.length - 1] : page;
      if (!last || !last.next_cursor) return;
      loadingMore[1](true);
      call("/activity" + query(Object.assign({}, request, { cursor: last.next_cursor })))
        .then(function (body) {
          olderState[1](older.concat([body]));
        })
        .catch(function (failure) {
          failureState[1](failure);
        })
        .finally(function () {
          loadingMore[1](false);
        });
    }

    var events = [];
    if (page) {
      events = (page.events || []).slice();
      older.forEach(function (chunk) {
        events = events.concat(chunk.events || []);
      });
    }
    if (codes.length) {
      events = events.filter(function (event) {
        return codes.indexOf(event.outcome && event.outcome.code) >= 0;
      });
    }
    var selected = events.filter(function (event) {
      return event.scan_id === selectedId;
    })[0];

    // An event linked from elsewhere may sit outside the current page.
    useEffect(
      function () {
        if (!selectedId || selected) return;
        call("/activity/" + encodeURIComponent(selectedId))
          .then(function (body) {
            extraEvent[1](body.event);
          })
          .catch(function () {
            extraEvent[1](null);
          });
      },
      [selectedId, Boolean(selected)]
    );
    if (!selected && extraEvent[0] && extraEvent[0].scan_id === selectedId) selected = extraEvent[0];

    var tail = older.length ? older[older.length - 1] : page;
    var options = optionsState[0];
    var filtered = filters.kind || filters.tool || filters.session || filters.severity || filters.q || filters.outcome;
    var neverRecorded = options && options.total === 0 && !filtered && filters.range === "all";

    function open(event) {
      var route = Object.assign({}, params, { event: event.scan_id });
      go("activity", route);
    }
    function close() {
      var id = selectedId;
      var route = Object.assign({}, params);
      delete route.event;
      go("activity", route);
      window.setTimeout(function () {
        var row = document.getElementById("petasos-event-" + id);
        if (row) row.focus({ preventScroll: true });
      }, 50);
    }

    var list;
    if (failureState[0] && !page) {
      list = h(Notice, { tone: "destructive", title: "The activity record could not be read" }, failureState[0].message);
    } else if (!page) {
      list = h("p", { className: "petasos-help", role: "status" }, "Loading activity…");
    } else if (!events.length && neverRecorded) {
      list = h(
        Empty,
        {
          title: "Nothing recorded yet",
          action: h(Btn, { outlined: true, onClick: function () { go("tryit", { example: "notes" }); } }, "Try it"),
        },
        "Blocks, approvals and warnings appear here with the reason. Clean tool calls are not listed."
      );
    } else if (!events.length) {
      list = h(
        Empty,
        {
          title: filtered ? "Nothing matches" : "Nothing in this time range",
          action: filtered
            ? h(Btn, { outlined: true, onClick: function () { setFilters({ range: filters.range, from: filters.from, to: filters.to }); } }, "Clear filters")
            : h(Btn, { outlined: true, onClick: function () { setFilters({ range: "all" }); } }, "Show all time"),
        },
        filtered ? "Try a longer time range or fewer filters." : "Petasos did not step in during this time. Clean tool calls are not listed."
      );
    } else {
      var groups = groupEvents(events);
      list = h(
        Fragment,
        null,
        h(
          "div",
          { className: "petasos-event-header", "aria-hidden": true },
          h("span", null, "When"),
          h("span", null, "What happened"),
          h("span", null, "Severity"),
          h("span", null, "Outcome"),
          h("span", null, "")
        ),
        h(
          "ul",
          { className: "petasos-events", "aria-label": "Events, newest first. Select one to see its details." },
          groups.map(function (group) {
            return h(EventGroup, { key: group.events[0].scan_id, group: group, selectedId: selectedId, onOpen: open });
          })
        ),
        tail && tail.next_cursor
          ? h(
              "div",
              { className: "petasos-more" },
              h(Btn, { outlined: true, onClick: loadOlder, disabled: loadingMore[0] }, loadingMore[0] ? "Loading…" : "Show older events")
            )
          : h("p", { className: "petasos-help petasos-end" }, page.complete === false ? "Older events were not read." : "That is everything in this range.")
      );
    }

    var count = options
      ? plural(options.total, "event") + " · " + (options.blocked || 0) + " blocked"
      : "";

    return h(
      "div",
      { className: "petasos-stack" },
      h(
        Panel,
        {
          title: "Activity",
          description: "What Petasos blocked, flagged or asked about, and why. Newest first. Checked again every 15 seconds.",
          actions: h(
            Fragment,
            null,
            count ? h("span", { className: "petasos-count" }, count) : null,
            page ? h(IntegrityStatus, { integrity: page.integrity }) : null
          ),
        },
        h(ActivityFilters, { filters: filters, options: options, onChange: setFilters }),
        filters.outcome
          ? h(
              "p",
              { className: "petasos-help" },
              "Showing only: ",
              h("strong", null, OUTCOME_FILTER_WORDS[filters.outcome] || filters.outcome),
              ". ",
              h(LinkButton, { onClick: function () { setFilters({ range: filters.range }); } }, "Show everything")
            )
          : null
      ),
      page ? h(IntegrityNotice, { integrity: page.integrity, signing: props.status.record_signing }) : null,
      neverRecorded && !events.length
        ? list
        : h(
            "div",
            { className: cn("petasos-split", selected && "petasos-split-open") },
            h("div", { className: "petasos-split-main" }, h(C.Card, { className: "petasos-panel petasos-list-card" }, list)),
            selected
              ? h(EventDetail, {
                  event: selected,
                  onClose: close,
                  onFilter: function (patch) {
                    setFilters(Object.assign({}, filters, patch));
                  },
                })
              : null
          )
    );
  }
  // ===== src/30-tryit.js =====
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
    if (example.mode === "tool") {
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
      h("p", { className: "petasos-help" }, "Choosing an example fills the input below. Nothing runs until you press Check."),
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
  // ===== src/40-settings.js =====
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
  // ===== src/90-app.js =====
  // ---------------------------------------------------------------------------
  // The tab: four views under one row of Hermes's enclosed tabs, and the
  // states that come before any view (loading, Petasos not answering).
  // ---------------------------------------------------------------------------

  var VIEW_TABS = [
    { value: "overview", label: "Overview" },
    { value: "activity", label: "Activity" },
    { value: "tryit", label: "Try it" },
    { value: "settings", label: "Settings" },
  ];

  function Unreachable(props) {
    var failure = props.failure;
    var notMounted = failure.status === 404;
    return h(
      Panel,
      { title: notMounted ? "Petasos's part of the dashboard is not loaded" : "Petasos is not answering" },
      h(
        "p",
        null,
        notMounted
          ? "Hermes loads this tab's data only for a plugin it is running. Petasos is switched off in Hermes's plugin list, or was switched on after the dashboard started."
          : "The dashboard could not get Petasos's status. " + (failure.message || "")
      ),
      h(
        "p",
        { className: "petasos-help" },
        notMounted
          ? "Turn Petasos on in Plugins, then restart the dashboard. Until then, tool calls are not being checked."
          : "This page tries again every 20 seconds. If it keeps failing, the dashboard's log has the detail."
      ),
      h(
        "div",
        { className: "petasos-row-actions" },
        h(Btn, { onClick: props.onRetry }, "Try again"),
        notMounted ? h("a", { className: "petasos-link", href: "/plugins" }, "Open Plugins") : null
      )
    );
  }

  // True when the active Hermes theme has a light background. Hermes rewrites
  // its colour variables on the root element when the theme changes.
  function useLightTheme() {
    function measure() {
      var raw = window.getComputedStyle(document.documentElement).getPropertyValue("--background-base").trim();
      var match = raw.match(/^#([0-9a-f]{6})$/i);
      if (!match) return false;
      var n = parseInt(match[1], 16);
      var r = (n >> 16) & 255;
      var g = (n >> 8) & 255;
      var b = n & 255;
      return 0.2126 * r + 0.7152 * g + 0.0722 * b > 140;
    }
    var state = useState(measure);
    useEffect(function () {
      var observer = new MutationObserver(function () {
        state[1](measure());
      });
      observer.observe(document.documentElement, { attributes: true, attributeFilter: ["style", "class"] });
      return function () {
        observer.disconnect();
      };
    }, []);
    return state[0];
  }

  function PetasosTab() {
    var route = useRoute();
    var light = useLightTheme();
    var statusState = useState(null);
    var status = statusState[0];
    var failureState = useState(null);
    var catalogState = useState(null);
    var catalog = catalogState[0];
    var checkedState = useState(null);
    var refreshState = useState(0);
    var lockedState = useState(null);
    var pauseState = useState(false);
    // Staged settings live here, so moving between views keeps them.
    var draftState = useState(EMPTY_DRAFT);
    var draft = draftState[0];
    var toast = SDK.hooks.useToast();

    var loadStatus = useCallback(function () {
      return call("/status")
        .then(function (body) {
          statusState[1](body);
          failureState[1](null);
          checkedState[1](Date.now());
        })
        .catch(function (failure) {
          failureState[1](failure);
        });
    }, []);
    var loadCatalog = useCallback(function () {
      return call("/settings")
        .then(catalogState[1])
        .catch(function () {});
    }, []);

    usePoll(loadStatus, 20000, []);
    useEffect(function () {
      loadCatalog();
    }, []);

    // Leaving the page with staged settings asks first.
    var dirty = !draftIsEmpty(draft);
    useEffect(
      function () {
        if (!dirty) return;
        function warn(event) {
          event.preventDefault();
          event.returnValue = "";
          return "";
        }
        window.addEventListener("beforeunload", warn);
        return function () {
          window.removeEventListener("beforeunload", warn);
        };
      },
      [dirty]
    );

    function refreshAll() {
      loadStatus();
      loadCatalog();
      refreshState[1](refreshState[0] + 1);
    }

    function onSaved(body) {
      if (body && body.settings) catalogState[1](body);
      loadCatalog();
      loadStatus();
      refreshState[1](refreshState[0] + 1);
    }

    function save(body) {
      return call("/settings", { method: "PUT", body: body })
        .then(function (saved) {
          toast.showToast(saved.restart_message || "Saved", "success");
          onSaved(saved);
          return saved;
        })
        .catch(function (failure) {
          if (failure.code === "managed") lockedState[1](failure.message);
          toast.showToast(failure.message, "error");
          throw failure;
        });
    }

    function stage(candidate) {
      var next = { overrides: {} };
      if (candidate.enabled !== undefined) next.enabled = candidate.enabled;
      if (candidate.role) next.role = candidate.role;
      if (candidate.level) next.level = candidate.level;
      if (candidate.overrides) next.overrides = clone(candidate.overrides);
      draftState[1](next);
    }

    var view = route.view;
    var locked = Boolean(lockedState[0]);
    var body;
    if (!status && failureState[0]) {
      body = h(Unreachable, { failure: failureState[0], onRetry: refreshAll });
    } else if (!status) {
      body = h("p", { className: "petasos-help", role: "status" }, "Loading Petasos…");
    } else {
      var shared = {
        route: route,
        status: status,
        catalog: catalog,
        refreshKey: refreshState[0],
        locked: locked,
        lockedMessage: lockedState[0],
        onLocked: lockedState[1],
        onSaved: onSaved,
        onSave: save,
      };
      if (view === "activity") body = h(Activity, shared);
      // Try it and Settings start from what the link carried (an example, a
      // candidate, a rule), so a new link starts them afresh.
      else if (view === "tryit")
        body = h(
          TryIt,
          Object.assign({ key: (route.params.example || "") + "|" + (route.params.settings || ""), onStage: stage }, shared)
        );
      else if (view === "settings")
        body = h(
          Settings,
          Object.assign({ key: (route.params.rule || "") + "|" + (route.params.review || ""), draft: draft, setDraft: draftState[1] }, shared)
        );
      else
        body = h(
          Overview,
          Object.assign({}, shared, {
            onPause: function () {
              pauseState[1](true);
            },
            onResume: function () {
              save({ enabled: true }).catch(function () {});
            },
          })
        );
    }

    var paused = status && status.switches && status.switches.petasos && status.switches.petasos.on === false;
    var viewLabel = (VIEW_TABS.filter(function (tab) {
      return tab.value === view;
    })[0] || VIEW_TABS[0]).label;

    return h(
      "div",
      { className: cn("petasos", light && "petasos-light") },
      h(C.Toast, { toast: toast.toast }),
      h(
        "div",
        { className: "petasos-topbar" },
        h(
          "div",
          { className: "petasos-topbar-main" },
          h(ViewTabs, {
            label: "Petasos views",
            views: VIEW_TABS,
            value: view,
            onChange: function (value) {
              go(value);
            },
          }),
          paused ? h(Status, { tone: "warning" }, "Paused") : null,
          dirty && view !== "settings"
            ? h(
                "button",
                { type: "button", className: "petasos-unsaved", onClick: function () { go("settings"); } },
                "Unsaved settings changes"
              )
            : null
        ),
        h(
          "div",
          { className: "petasos-topbar-side" },
          failureState[0] && status ? h(Status, { tone: "warning", title: failureState[0].message }, "Last check failed") : null,
          checkedState[0] ? h("span", { className: "petasos-help" }, "Checked " + whenText(checkedState[0] / 1000)) : null,
          h(Btn, { ghost: true, onClick: refreshAll, "aria-label": "Refresh now" }, "Refresh")
        )
      ),
      paused && view !== "overview"
        ? h(
            Notice,
            {
              tone: "warning",
              title: "Protection is paused",
              action: h(Btn, { onClick: function () { save({ enabled: true }).catch(function () {}); }, disabled: locked }, "Resume"),
            },
            "Tool calls go through unchecked. Each one is recorded."
          )
        : null,
      h(
        "div",
        { className: "petasos-view", id: "petasos-panel", role: "tabpanel", "aria-labelledby": "petasos-tab-" + view, "aria-label": viewLabel },
        body
      ),
      h(C.ConfirmDialog, {
        open: pauseState[0],
        title: "Pause protection?",
        description:
          "Until you resume, Petasos lets every tool call through without checking it. Each one is still recorded in Activity. Pausing applies from the agent's next tool call. Hermes keeps running the plugin.",
        confirmLabel: "Pause",
        cancelLabel: "Keep protecting",
        destructive: true,
        onCancel: function () {
          pauseState[1](false);
        },
        onConfirm: function () {
          pauseState[1](false);
          save({ enabled: false }).catch(function () {});
        },
      })
    );
  }

  PLUGINS.register("petasos", PetasosTab);
})();
