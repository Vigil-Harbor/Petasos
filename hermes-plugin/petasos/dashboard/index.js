/*
 * Petasos tab for the Hermes dashboard.
 *
 * Generated from hermes-plugin/dashboard-src/ by scripts/build_dashboard.py.
 * Edit those files and run that script; a test fails when this file is stale.
 *
 * Plain script, no build step: React, the components and the API client
 * all come from window.__HERMES_PLUGIN_SDK__. Every Petasos fact shown here
 * comes from /api/plugins/petasos/.
 */
(function () {
  "use strict";

  // ===== dashboard-src/00-kit.js =====
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
  // Time. One convention everywhere: a 24-hour clock in the browser's time
  // zone, which a list names once at its head. A date from another year
  // carries the year. Relative age is secondary.
  // ---------------------------------------------------------------------------

  function whenText(seconds) {
    if (typeof seconds !== "number") return "";
    // Hermes's timeAgo takes unix seconds (its type comment says milliseconds).
    return SDK.utils.timeAgo(seconds);
  }

  function sameDay(a, b) {
    return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  }

  function clock24(date, seconds) {
    var options = { hour: "2-digit", minute: "2-digit", hourCycle: "h23" };
    if (seconds) options.second = "2-digit";
    return date.toLocaleTimeString(undefined, options);
  }

  function listTime(seconds) {
    if (typeof seconds !== "number") return "";
    var date = new Date(seconds * 1000);
    var now = new Date();
    if (sameDay(date, now)) return "Today " + clock24(date);
    var options = { day: "numeric", month: "short" };
    if (date.getFullYear() !== now.getFullYear()) options.year = "numeric";
    return date.toLocaleDateString(undefined, options) + " " + clock24(date);
  }

  function fullTime(seconds) {
    if (typeof seconds !== "number") return "";
    var date = new Date(seconds * 1000);
    var zone = "";
    try {
      var parts = new Intl.DateTimeFormat(undefined, { timeZoneName: "short" }).formatToParts(date);
      zone = (parts.filter(function (part) {
        return part.type === "timeZoneName";
      })[0] || {}).value || "";
    } catch (_e) {
      zone = "";
    }
    return (
      date.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", year: "numeric" }) +
      " " +
      clock24(date, true) +
      (zone ? " " + zone : "")
    );
  }

  function clockTime(ms) {
    return clock24(new Date(ms), true);
  }

  function timeZoneName() {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || "your time zone";
    } catch (_e) {
      return "your time zone";
    }
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
                  ? h(
                      "div",
                      { className: "petasos-panel-titlerow" },
                      h(C.CardTitle, { className: "text-sm petasos-panel-title", id: props.titleId }, props.title),
                      props.badge || null
                    )
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

  // A status that carries a safety meaning (an outcome, the verdict, a check's
  // state): Hermes's own Badge container (shape, border, tint), with its words
  // in the body face at the size of the text around them, so they read at a
  // glance. Hermes's condensed face stays on counts (Tag). Words always say the
  // same thing as the colour. Severity is not a badge (see Severity).
  var TONES = ["success", "warning", "destructive", "neutral"];
  var BADGE_TONE = { success: "success", warning: "warning", destructive: "destructive", neutral: "secondary" };

  function Status(props) {
    var tone = TONES.indexOf(props.tone) >= 0 ? props.tone : "neutral";
    return h(
      C.Badge,
      {
        tone: BADGE_TONE[tone],
        className: cn("petasos-status", "petasos-status-" + tone, props.large && "petasos-status-large", props.className),
        title: props.title,
        "data-petasos-state": props.state,
      },
      props.children
    );
  }

  // A count or an incidental label: Hermes's own badge, as Hermes draws it.
  function Tag(props) {
    return h(C.Badge, { tone: props.tone || "secondary", className: cn("petasos-tag", props.className), title: props.title }, props.children);
  }

  // How serious a finding is: a word beside the outcome, in plain text.
  // Critical is set heavier than High; there is no second coloured shape.
  function Severity(props) {
    var severity = String(props.value || "").toLowerCase();
    var known = { critical: 1, high: 1, medium: 1, low: 1, info: 1 };
    var label = props.label || (known[severity] ? capital(severity) : "");
    if (!label) return null;
    return h(
      "span",
      { className: cn("petasos-sev", known[severity] && "petasos-sev-" + severity) },
      h("span", { className: "sr-only" }, "Severity: "),
      label
    );
  }

  function outcomeTone(code) {
    var destructive = ["blocked", "stopped", "declined", "not_stopped", "attempt_blocked", "block"];
    var warning = ["asked", "attempt_asked", "flagged", "allowed", "degraded", "unchecked", "approve", "flag", "none"];
    if (destructive.indexOf(code) >= 0) return "destructive";
    if (warning.indexOf(code) >= 0) return "warning";
    if (code === "approved" || code === "allow") return "success";
    return "neutral";
  }

  // A notice. The tone is a mark and a word, not a thick edge; only an
  // exceptional warning (``strong``) keeps the marked edge. Success is a check
  // mark, so a confirmation never looks like a warning.
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
              tone === "success"
                ? h(Icon, { name: "check", size: 15, className: "petasos-notice-check" })
                : h("span", { className: "petasos-notice-dot", "aria-hidden": true }),
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
    check: ["M5 12.5l4.5 4.5L19 7.5"],
    calendar: ["M4 6h16v14H4z", "M4 10h16", "M8 3v4", "M16 3v4"],
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

  // Hermes's Button. Filled and outlined buttons are form buttons and are set
  // in upper case, as on Config and Plugins (SAVE, INSTALL); a ghost button is
  // a quiet page utility (Refresh) and keeps its own case. ``compact`` fits a
  // quiet button into a line of text.
  function Btn(props) {
    var rest = Object.assign({}, props);
    delete rest.children;
    delete rest.compact;
    rest.type = rest.type || "button";
    rest.size = rest.size || "sm";
    rest.className = cn(!props.ghost && "petasos-btn-caps", props.compact && "petasos-btn-compact", props.className);
    return h(C.Button, rest, props.children);
  }

  // Navigation: underlined, and used only for something that takes you
  // somewhere. An action that changes or runs something is a Btn.
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

  // A disclosure: a quiet toggle with a turning chevron. It is not underlined,
  // because underlined text only navigates. With ``remember``, the choice to open it is kept in this browser
  // so a technical reader opens it once.
  function readRemembered(key) {
    try {
      return window.localStorage.getItem("petasos." + key) === "open";
    } catch (_e) {
      return false;
    }
  }

  function writeRemembered(key, open) {
    try {
      if (open) window.localStorage.setItem("petasos." + key, "open");
      else window.localStorage.removeItem("petasos." + key);
    } catch (_e) {
      // Storage can be refused; the disclosure still works for this visit.
    }
  }

  function Disclosure(props) {
    var openState = useState(function () {
      return props.remember ? readRemembered(props.remember) : Boolean(props.defaultOpen);
    });
    var open = openState[0];
    var id = props.id || "petasos-disclosure-" + String(props.remember || props.label).replace(/[^a-z0-9]+/gi, "-").toLowerCase();
    return h(
      "div",
      { className: cn("petasos-disclosure", open && "petasos-disclosure-open", props.className) },
      h(
        "button",
        {
          type: "button",
          className: "petasos-disclosure-toggle",
          "aria-expanded": open,
          "aria-controls": id,
          onClick: function () {
            var next = !open;
            openState[1](next);
            if (props.remember) writeRemembered(props.remember, next);
          },
        },
        h(Icon, { name: "chevron", size: 14, className: "petasos-disclosure-chevron" }),
        h("span", null, open && props.openLabel ? props.openLabel : props.label)
      ),
      open ? h("div", { className: "petasos-disclosure-body", id: id }, props.children) : null
    );
  }

  // A command a person copies into a terminal: the command itself, and Copy.
  function Command(props) {
    return h(
      "div",
      { className: "petasos-command" },
      h("code", { className: "petasos-command-text" }, props.value),
      h(CopyButton, { value: props.value, label: props.label || "Copy the command" })
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
        "aria-describedby": props.describedBy,
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

  // Config's field layout: the label, the setting's key in Hermes's tertiary
  // text, one plain sentence, then the control across the panel. A switch sits
  // at the end of the label row instead.
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
  // The layout rules from dashboard-src/style.css, added once. Hermes's manifest can name
  // a style sheet, but the installer copies only this script, so it carries
  // the rules itself.
  // ---------------------------------------------------------------------------

  var STYLE = "/*\n * Petasos tab layout. Every colour, font and size is a Hermes variable, so\n * the tab follows whichever Hermes theme is active. Where Hermes's SDK does\n * not export a control (Segmented, Switch), these rules draw it the way\n * Hermes's own source does. No palette, font or icon set of Petasos's own.\n *\n * Text hierarchy uses Hermes's own tokens: primary text is the theme's ink;\n * secondary and tertiary text are the same ink at Hermes's 80% and 65%\n * (text-text-secondary and text-text-tertiary on its Config page). Values a\n * person typed and the current value of a control are primary.\n */\n\n.petasos {\n  --petasos-ink: var(--midground);\n  --petasos-secondary: var(\n    --color-text-secondary,\n    color-mix(in srgb, var(--midground-base, var(--midground)) 80%, transparent)\n  );\n  --petasos-tertiary: var(\n    --text-tertiary,\n    color-mix(in srgb, var(--midground-base, var(--midground)) 65%, transparent)\n  );\n  --petasos-line: color-mix(in srgb, var(--midground-base, var(--midground)) 15%, transparent);\n  --petasos-control-line: color-mix(in srgb, var(--midground-base, var(--midground)) 30%, transparent);\n  display: flex;\n  flex-direction: column;\n  gap: 1rem;\n  width: 100%;\n  min-width: 0;\n  color: var(--petasos-ink);\n  font-size: 0.9375rem;\n  line-height: 1.5;\n}\n\n.petasos code,\n.petasos pre {\n  background: transparent !important;\n  color: inherit;\n}\n\n.petasos p {\n  margin: 0;\n}\n\n.petasos .sr-only {\n  position: absolute;\n  width: 1px;\n  height: 1px;\n  padding: 0;\n  margin: -1px;\n  overflow: hidden;\n  clip: rect(0, 0, 0, 0);\n  white-space: nowrap;\n  border: 0;\n}\n\n/* Keyboard focus is always visible, in the theme's ring colour, on every\n * control the tab draws. Hermes's own controls keep their ring too. */\n.petasos button:focus-visible,\n.petasos a:focus-visible,\n.petasos input:focus-visible,\n.petasos textarea:focus-visible,\n.petasos summary:focus-visible,\n.petasos [tabindex]:focus-visible {\n  outline: 2px solid var(--midground);\n  outline-offset: 2px;\n}\n\n.petasos-detail:focus,\n.petasos-subhead:focus {\n  outline: none;\n}\n\n/* Controls: a typed value and a chosen value are primary text, and the\n * edge of an editable field is clear enough to read as editable. */\n.petasos input,\n.petasos textarea,\n.petasos [aria-haspopup=\"listbox\"] {\n  color: var(--petasos-ink);\n  border-color: var(--petasos-control-line);\n  font-family: var(--theme-font-mono);\n}\n\n.petasos input::placeholder,\n.petasos textarea::placeholder {\n  color: var(--petasos-tertiary);\n}\n\n.petasos [aria-haspopup=\"listbox\"] svg {\n  opacity: 1;\n  color: var(--petasos-ink);\n}\n\n.petasos input:disabled,\n.petasos textarea:disabled,\n.petasos [aria-haspopup=\"listbox\"]:disabled {\n  color: var(--petasos-tertiary);\n}\n\n.petasos-stack {\n  display: flex;\n  flex-direction: column;\n  gap: 1rem;\n  min-width: 0;\n}\n\n.petasos-grid-2 {\n  display: grid;\n  grid-template-columns: repeat(2, minmax(0, 1fr));\n  gap: 1rem;\n  align-items: start;\n}\n\n.petasos-grid-3 {\n  display: grid;\n  grid-template-columns: repeat(3, minmax(0, 1fr));\n  gap: 1rem;\n  align-items: start;\n}\n\n.petasos-help,\n.petasos-secondary {\n  font-size: 0.875rem;\n  line-height: 1.5;\n  color: var(--petasos-secondary);\n}\n\n.petasos-tertiary,\n.petasos-faint {\n  font-size: 0.8125rem;\n  color: var(--petasos-tertiary);\n}\n\n.petasos-dot {\n  color: var(--petasos-tertiary);\n}\n\n.petasos .petasos-faint {\n  color: var(--petasos-tertiary);\n}\n\n/* Form buttons (filled and outlined) in upper case, as Config and Plugins\n * set them. Ghost buttons are page utilities and keep their case. */\n.petasos .petasos-btn-caps {\n  text-transform: uppercase;\n}\n\n/* A quiet button inside a line of text: Undo, Reset, Show every outcome. */\n.petasos .petasos-btn-compact {\n  height: auto;\n  min-height: 0;\n  padding: 0.1rem 0.35rem;\n  vertical-align: baseline;\n}\n\n.petasos-strong,\n.petasos strong {\n  font-weight: 700;\n}\n\n.petasos-block {\n  display: block;\n}\n\n.petasos-gap-above {\n  margin-top: 0.4rem;\n}\n\n.petasos-end {\n  padding: 0.9rem 0 0.4rem;\n  text-align: center;\n}\n\n/* Underlined text navigates, and nothing else is underlined: an action\n * that changes or runs something is one of Hermes's buttons. */\n.petasos-link,\n.petasos a.petasos-link {\n  background: none;\n  border: 0;\n  padding: 0;\n  font: inherit;\n  font-size: inherit;\n  color: inherit;\n  text-decoration: underline;\n  text-decoration-thickness: 1px;\n  text-underline-offset: 3px;\n  cursor: pointer;\n  text-align: left;\n}\n\n.petasos-link:hover {\n  text-decoration-thickness: 2px;\n}\n\n.petasos-link:disabled {\n  cursor: not-allowed;\n  opacity: 0.6;\n}\n\n.petasos-row-actions {\n  display: flex;\n  flex-wrap: wrap;\n  align-items: center;\n  gap: 0.6rem 0.9rem;\n}\n\n.petasos-check-note {\n  flex: 1 1 16rem;\n  margin: 0;\n}\n\n.petasos-count {\n  font-size: 0.875rem;\n  font-weight: 600;\n  color: var(--petasos-ink);\n}\n\n.petasos-mono {\n  font-family: var(--theme-font-mono);\n  font-size: 0.85rem;\n}\n\n/* A technical id wraps only at the <wbr> after its separators. */\n.petasos-ident {\n  overflow-wrap: normal;\n  word-break: normal;\n  white-space: normal;\n  font-size: 0.82rem;\n}\n\n.petasos-idrow {\n  display: inline-flex;\n  flex-wrap: wrap;\n  align-items: baseline;\n  gap: 0.25rem 0.6rem;\n}\n\n.petasos-copy {\n  display: inline-flex;\n  align-items: center;\n  gap: 0.25rem;\n  padding: 0.1rem 0.35rem;\n  border: 1px solid transparent;\n  background: none;\n  color: var(--petasos-secondary);\n  font-size: 0.8rem;\n  cursor: pointer;\n}\n\n.petasos-copy:hover {\n  border-color: var(--petasos-line);\n  color: var(--petasos-ink);\n}\n\n.petasos-icon {\n  display: inline-block;\n  flex-shrink: 0;\n  vertical-align: middle;\n}\n\n/* ---- Disclosure, as Hermes's pages draw one ------------------------- */\n\n.petasos-disclosure {\n  display: flex;\n  flex-direction: column;\n  align-items: flex-start;\n  gap: 0.6rem;\n  min-width: 0;\n  width: 100%;\n}\n\n.petasos-disclosure-toggle {\n  display: inline-flex;\n  align-items: center;\n  gap: 0.3rem;\n  padding: 0;\n  border: 0;\n  background: none;\n  color: var(--petasos-secondary);\n  font: inherit;\n  font-size: 0.875rem;\n  font-weight: 500;\n  cursor: pointer;\n}\n\n.petasos-disclosure-toggle:hover {\n  color: var(--petasos-ink);\n}\n\n.petasos-disclosure-chevron {\n  transition: transform 120ms;\n}\n\n.petasos-disclosure-open > .petasos-disclosure-toggle .petasos-disclosure-chevron,\n.petasos-chevron-open {\n  transform: rotate(90deg);\n}\n\n.petasos-disclosure-body {\n  display: flex;\n  flex-direction: column;\n  gap: 0.6rem;\n  width: 100%;\n  min-width: 0;\n  padding-left: 1.1rem;\n}\n\n/* A command to copy into a terminal. */\n.petasos-command {\n  display: flex;\n  align-items: center;\n  justify-content: space-between;\n  gap: 0.75rem;\n  max-width: 40rem;\n  padding: 0.45rem 0.6rem 0.45rem 0.8rem;\n  border: 1px solid var(--petasos-control-line);\n  background: color-mix(in srgb, var(--background) 40%, transparent);\n}\n\n.petasos-command-text {\n  font-family: var(--theme-font-mono);\n  font-size: 0.875rem;\n  overflow-wrap: anywhere;\n}\n\n/* ---- Top bar: Hermes's enclosed tabs ------------------------------- */\n\n.petasos-topbar {\n  display: flex;\n  align-items: center;\n  justify-content: space-between;\n  gap: 1rem;\n  flex-wrap: wrap;\n}\n\n.petasos-topbar-main {\n  display: flex;\n  align-items: center;\n  gap: 0.75rem;\n  flex-wrap: wrap;\n}\n\n.petasos-topbar-side {\n  display: flex;\n  align-items: center;\n  gap: 0.75rem;\n}\n\n.petasos-topbar-side .petasos-help {\n  color: var(--petasos-tertiary);\n}\n\n.petasos-unsaved {\n  background: none;\n  border: 0;\n  padding: 0;\n  font-size: 0.875rem;\n  color: inherit;\n  text-decoration: underline;\n  text-underline-offset: 3px;\n  cursor: pointer;\n}\n\n/* Hermes's Segmented: joined rectangular buttons, the chosen one filled\n * with the theme's ink, regular weight, as on Sessions. */\n.petasos-segmented {\n  display: inline-flex;\n  flex-wrap: wrap;\n  border: 1px solid var(--petasos-line);\n  background: color-mix(in srgb, var(--background) 30%, transparent);\n  max-width: 100%;\n}\n\n.petasos-segment {\n  display: inline-flex;\n  align-items: center;\n  gap: 0.35rem;\n  height: 1.875rem;\n  padding: 0 0.75rem;\n  border: 0;\n  border-right: 1px solid var(--petasos-line);\n  background: transparent;\n  color: var(--petasos-secondary);\n  font-family: var(--font-mondwest);\n  font-size: 0.875rem;\n  font-weight: 400;\n  letter-spacing: 0.03em;\n  white-space: nowrap;\n  cursor: pointer;\n  transition: background-color 120ms, color 120ms;\n}\n\n.petasos-segment:last-child {\n  border-right: 0;\n}\n\n.petasos-segment:hover {\n  background: color-mix(in srgb, var(--midground) 10%, transparent);\n  color: var(--midground);\n}\n\n.petasos-segment-on,\n.petasos-segment-on:hover {\n  background: var(--midground);\n  color: var(--background);\n}\n\n.petasos-segment:disabled {\n  cursor: not-allowed;\n  opacity: 0.55;\n}\n\n.petasos-viewtabs .petasos-segment {\n  height: 1.875rem;\n  padding: 0 0.85rem;\n}\n\n/* ---- Hermes's Switch ------------------------------------------------ */\n\n.petasos-switch {\n  position: relative;\n  display: inline-flex;\n  align-items: center;\n  flex-shrink: 0;\n  width: 2.25rem;\n  height: 1.25rem;\n  padding: 0;\n  border: 1px solid color-mix(in srgb, var(--midground) 22%, transparent);\n  background: var(--background);\n  cursor: pointer;\n  transition: background-color 120ms, border-color 120ms;\n}\n\n.petasos-switch-thumb {\n  display: block;\n  width: 0.875rem;\n  height: 0.875rem;\n  margin-left: 0.125rem;\n  background: color-mix(in srgb, var(--midground) 40%, transparent);\n  transition: transform 120ms;\n}\n\n.petasos-switch-on {\n  background: color-mix(in srgb, var(--midground) 15%, transparent);\n  border-color: color-mix(in srgb, var(--midground) 35%, transparent);\n}\n\n.petasos-switch-on .petasos-switch-thumb {\n  transform: translateX(1rem);\n  background: var(--midground);\n}\n\n.petasos-switch:disabled {\n  cursor: not-allowed;\n  opacity: 0.5;\n}\n\n.petasos-inline-switch {\n  display: inline-flex;\n  align-items: center;\n  gap: 0.6rem;\n  font-size: 0.875rem;\n}\n\n/* ---- Panels --------------------------------------------------------- */\n\n.petasos-panel {\n  min-width: 0;\n}\n\n.petasos-panel-head {\n  padding: 0.85rem 1.1rem 0.6rem;\n}\n\n.petasos-panel-headrow {\n  display: flex;\n  align-items: flex-start;\n  justify-content: space-between;\n  gap: 1rem;\n}\n\n.petasos-panel-titles {\n  display: flex;\n  flex-direction: column;\n  gap: 0.25rem;\n  min-width: 0;\n}\n\n/* A panel title with its state badge beside it, as Plugins sets a badge\n * beside a name. */\n.petasos-panel-titlerow {\n  display: flex;\n  flex-wrap: wrap;\n  align-items: center;\n  gap: 0.6rem;\n}\n\n.petasos-panel-desc {\n  font-size: 0.875rem;\n  color: var(--petasos-secondary);\n}\n\n.petasos-panel-actions {\n  display: flex;\n  align-items: center;\n  gap: 0.75rem;\n  flex-shrink: 0;\n}\n\n.petasos-panel-body {\n  display: flex;\n  flex-direction: column;\n  gap: 0.85rem;\n  padding: 0.9rem 1.1rem 1.1rem;\n}\n\n/* Field and filter labels, as Hermes's Label and FilterGroup draw them:\n * Mondwest, upper case, regular weight, spaced; bold is kept for values. */\n.petasos-label,\n.petasos-filter-label,\n.petasos-sections-title {\n  font-family: var(--font-mondwest);\n  font-size: 0.78rem;\n  font-weight: 400;\n  letter-spacing: 0.08em;\n  line-height: 1.3;\n  text-transform: uppercase;\n  color: var(--petasos-secondary);\n}\n\n.petasos-subhead {\n  margin: 0.3rem 0 0;\n  font-family: var(--font-mondwest);\n  font-size: 0.8rem;\n  font-weight: 400;\n  letter-spacing: 0.08em;\n  text-transform: uppercase;\n  color: var(--petasos-secondary);\n}\n\n/* ---- Status: Hermes's Badge, legible -------------------------------- */\n\n/* Hermes's Badge container (shape, border, tint) with the words in the\n * body face, medium weight, at the size of the text around them. Hermes's\n * condensed face stays on counts (.petasos-tag). Light themes darken the\n * ink. */\n.petasos .petasos-status {\n  font-family: var(--theme-font-sans);\n  font-size: 0.875rem;\n  font-weight: 500;\n  letter-spacing: 0.01em;\n  text-transform: none;\n  padding: 0.22rem 0.55rem;\n  line-height: 1.2;\n  white-space: nowrap;\n  vertical-align: middle;\n}\n\n.petasos .petasos-status-large {\n  font-size: 0.9375rem;\n  padding: 0.28rem 0.65rem;\n}\n\n.petasos .petasos-status-success {\n  color: color-mix(in srgb, var(--color-success) 70%, white);\n}\n\n.petasos .petasos-status-warning {\n  color: color-mix(in srgb, var(--color-warning) 75%, white);\n}\n\n.petasos .petasos-status-destructive {\n  color: color-mix(in srgb, var(--color-destructive) 55%, white);\n  border-color: color-mix(in srgb, var(--color-destructive) 55%, transparent);\n}\n\n.petasos-light .petasos-status-success {\n  color: color-mix(in srgb, var(--color-success) 45%, black);\n  border-color: color-mix(in srgb, var(--color-success) 60%, black);\n}\n\n.petasos-light .petasos-status-warning {\n  color: color-mix(in srgb, var(--color-warning) 45%, black);\n  border-color: color-mix(in srgb, var(--color-warning) 60%, black);\n}\n\n.petasos-light .petasos-status-destructive {\n  color: color-mix(in srgb, var(--color-destructive) 70%, black);\n  border-color: color-mix(in srgb, var(--color-destructive) 70%, black);\n}\n\n.petasos-light .petasos-status-neutral {\n  color: var(--midground);\n}\n\n.petasos-tag {\n  white-space: nowrap;\n}\n\n.petasos .petasos-tag {\n  font-size: 0.85rem;\n}\n\n.petasos-none {\n  color: var(--petasos-tertiary);\n}\n\n/* Severity: a word in plain text beside the outcome. Critical is set\n * heavier than High; there is no second coloured shape. */\n.petasos-sev {\n  font-size: 0.875rem;\n  color: var(--petasos-secondary);\n  white-space: nowrap;\n}\n\n.petasos-sev-high {\n  color: var(--petasos-ink);\n  font-weight: 500;\n}\n\n.petasos-sev-critical {\n  color: var(--petasos-ink);\n  font-weight: 700;\n}\n\n/* ---- Notices: a mark and a title; only exceptional warnings keep an edge */\n\n.petasos-notice {\n  display: flex;\n  align-items: flex-start;\n  justify-content: space-between;\n  gap: 1rem;\n  padding: 0.8rem 1rem;\n  border: 1px solid var(--color-border);\n  background: var(--color-card);\n}\n\n.petasos-notice-strong {\n  border-left: 3px solid var(--color-destructive);\n}\n\n.petasos-notice-text {\n  display: flex;\n  flex-direction: column;\n  gap: 0.3rem;\n  min-width: 0;\n}\n\n.petasos-notice-title {\n  display: flex;\n  align-items: center;\n  gap: 0.5rem;\n  font-weight: 700;\n  font-size: 0.9375rem;\n}\n\n.petasos-notice-dot {\n  width: 0.5rem;\n  height: 0.5rem;\n  border-radius: 50%;\n  flex-shrink: 0;\n  background: var(--midground);\n}\n\n.petasos-notice-warning .petasos-notice-dot {\n  background: var(--color-warning);\n}\n\n.petasos-notice-destructive .petasos-notice-dot {\n  background: var(--color-destructive);\n}\n\n.petasos-notice-check {\n  color: var(--color-success);\n}\n\n.petasos-light .petasos-notice-check {\n  color: color-mix(in srgb, var(--color-success) 50%, black);\n}\n\n.petasos-notice-success {\n  border-color: color-mix(in srgb, var(--color-success) 45%, transparent);\n}\n\n.petasos-notice-body {\n  font-size: 0.875rem;\n  line-height: 1.55;\n  padding-left: 1.1rem;\n  color: var(--petasos-secondary);\n}\n\n.petasos-notice-body p + p {\n  margin-top: 0.3rem;\n}\n\n.petasos-notice-action {\n  flex-shrink: 0;\n}\n\n.petasos-steps {\n  margin: 0.4rem 0 0;\n  padding-left: 1.2rem;\n  display: flex;\n  flex-direction: column;\n  gap: 0.25rem;\n}\n\n/* A saved confirmation, and beneath it, separately and more quietly, what\n * waits for a restart. */\n.petasos-saved {\n  display: flex;\n  flex-direction: column;\n  gap: 0.4rem;\n}\n\n.petasos-restart-note {\n  padding: 0 0 0 1.1rem;\n  font-size: 0.875rem;\n  color: var(--petasos-secondary);\n}\n\n/* ---- Empty list, as Sessions draws it ------------------------------- */\n\n.petasos-empty {\n  display: flex;\n  flex-direction: column;\n  align-items: center;\n  gap: 0.3rem;\n  padding: 3rem 1rem;\n  text-align: center;\n}\n\n.petasos-empty-icon {\n  width: 1.75rem;\n  height: 1.75rem;\n  margin-bottom: 0.35rem;\n  color: var(--petasos-tertiary);\n}\n\n.petasos-empty-title {\n  font-size: 0.9375rem;\n  font-weight: 400;\n  color: var(--petasos-secondary);\n}\n\n.petasos-empty-body {\n  max-width: 30rem;\n  font-size: 0.875rem;\n  color: var(--petasos-secondary);\n}\n\n.petasos-empty-action {\n  margin-top: 0.6rem;\n}\n\n/* ---- Key and value lists -------------------------------------------- */\n\n.petasos-kv {\n  display: grid;\n  grid-template-columns: minmax(7rem, max-content) minmax(0, 1fr);\n  gap: 0.45rem 1.25rem;\n  margin: 0;\n  font-size: 0.9rem;\n}\n\n.petasos-kv dt {\n  font-family: var(--font-mondwest);\n  font-size: 0.8rem;\n  font-weight: 400;\n  letter-spacing: 0.08em;\n  text-transform: uppercase;\n  color: var(--petasos-secondary);\n  padding-top: 0.12rem;\n}\n\n.petasos-kv dd {\n  margin: 0;\n  min-width: 0;\n}\n\n.petasos-kv-stacked {\n  grid-template-columns: minmax(0, 1fr);\n  gap: 0.15rem;\n}\n\n.petasos-kv-stacked dd {\n  margin-bottom: 0.6rem;\n}\n\n/* ---- Overview: status, with the two choices inside ------------------ */\n\n/* The status panel's first line: the state, in one sentence. */\n.petasos-verdict-title {\n  margin: 0;\n  font-size: 1rem;\n  font-weight: 600;\n  line-height: 1.4;\n}\n\n.petasos-verdict-reason {\n  max-width: 56rem;\n  font-size: 0.9375rem;\n  color: var(--petasos-secondary);\n}\n\n.petasos-coverage {\n  margin-top: 0.15rem;\n}\n\n.petasos-fixbox {\n  display: flex;\n  flex-direction: column;\n  gap: 0.5rem;\n  padding: 0.75rem 0.9rem;\n  border: 1px solid var(--petasos-line);\n  background: color-mix(in srgb, var(--midground) 4%, transparent);\n  font-size: 0.9rem;\n}\n\n.petasos-setup {\n  display: flex;\n  flex-direction: column;\n  gap: 0.9rem;\n  margin-top: 0.25rem;\n  padding-top: 0.9rem;\n  border-top: 1px solid var(--color-border);\n}\n\n.petasos-setup-grid {\n  display: grid;\n  grid-template-columns: repeat(2, minmax(0, 1fr));\n  gap: 1rem 2rem;\n  align-items: start;\n}\n\n.petasos-choose {\n  display: flex;\n  flex-direction: column;\n  align-items: flex-start;\n  gap: 0.45rem;\n  min-width: 0;\n}\n\n.petasos-choose-desc {\n  font-size: 0.9rem;\n  max-width: 34rem;\n}\n\n.petasos-optlist {\n  list-style: none;\n  margin: 0;\n  padding: 0;\n  display: flex;\n  flex-direction: column;\n  gap: 0.35rem;\n}\n\n.petasos-opt {\n  display: grid;\n  grid-template-columns: 8.5rem minmax(0, 1fr);\n  gap: 0.75rem;\n  font-size: 0.875rem;\n  line-height: 1.45;\n  color: var(--petasos-secondary);\n}\n\n.petasos-opt-name {\n  font-weight: 600;\n}\n\n.petasos-opt-on {\n  color: var(--petasos-ink);\n}\n\n.petasos-opt-on .petasos-opt-name {\n  font-weight: 700;\n}\n\n.petasos-opt-note {\n  color: var(--petasos-tertiary);\n}\n\n/* The pending change: its own inset surface, a clear heading, then Apply. */\n.petasos-preview {\n  display: flex;\n  flex-direction: column;\n  gap: 0.6rem;\n  padding: 0.9rem 1rem 1rem;\n  border: 1px solid var(--petasos-control-line);\n  background: color-mix(in srgb, var(--midground) 7%, var(--color-card));\n}\n\n.petasos-preview-title {\n  margin: 0;\n  font-size: 1rem;\n  font-weight: 700;\n}\n\n.petasos-preview-text {\n  font-size: 0.9rem;\n  max-width: 56rem;\n}\n\n.petasos-when {\n  font-size: 0.9rem;\n  font-weight: 600;\n}\n\n/* A change: label above, the value from and to, where it would come from. */\n.petasos-changes {\n  list-style: none;\n  margin: 0;\n  padding: 0;\n  width: 100%;\n}\n\n.petasos-change {\n  display: flex;\n  flex-direction: column;\n  gap: 0.2rem;\n  padding: 0.6rem 0;\n  border-bottom: 1px solid var(--color-border);\n}\n\n.petasos-change:first-child {\n  border-top: 1px solid var(--color-border);\n}\n\n.petasos-change-name {\n  font-weight: 700;\n  font-size: 0.9rem;\n}\n\n.petasos-change .petasos-help {\n  font-size: 0.85rem;\n}\n\n.petasos-change-values {\n  font-size: 0.9rem;\n}\n\n.petasos-before {\n  text-decoration: line-through;\n  color: var(--petasos-secondary);\n}\n\n.petasos-arrow {\n  color: var(--petasos-tertiary);\n}\n\n.petasos-diff {\n  list-style: none;\n  margin: 0;\n  padding: 0;\n  display: flex;\n  flex-direction: column;\n  gap: 0.15rem;\n  font-size: 0.875rem;\n}\n\n.petasos-diff-sign {\n  display: inline-block;\n  width: 1rem;\n  font-weight: 700;\n}\n\n/* The line under a control: state and source, then Reset or Undo, which\n * stay on the line. */\n.petasos-provenance {\n  display: flex;\n  flex-wrap: wrap;\n  align-items: center;\n  column-gap: 0.3rem;\n  font-size: 0.8125rem;\n  color: var(--petasos-secondary);\n}\n\n.petasos .petasos-provenance .petasos-btn-compact {\n  font-size: 0.75rem;\n}\n\n.petasos-key {\n  font-family: var(--theme-font-mono);\n  font-size: 0.78rem;\n}\n\n/* ---- Overview: last 24 hours, as System lays out its figures -------- */\n\n/* The figures, as System lays out its own: a small label above, the value\n * beneath at a size that reads as the value. Each cell stretches to its\n * row, and the value sits at the cell's foot, so values in a row stay on\n * one line when a label wraps. */\n.petasos-stats {\n  display: grid;\n  grid-template-columns: repeat(auto-fit, minmax(8.5rem, 1fr));\n  gap: 0.9rem 1.5rem;\n  margin: 0;\n}\n\n.petasos-stat {\n  display: flex;\n  flex-direction: column;\n  justify-content: space-between;\n  gap: 0.3rem;\n  min-width: 0;\n}\n\n.petasos-stat dt {\n  font-size: 0.75rem;\n  letter-spacing: 0.06em;\n  line-height: 1.35;\n  text-transform: uppercase;\n  color: var(--petasos-secondary);\n}\n\n.petasos-stat dd {\n  margin: 0;\n}\n\n.petasos-stat-value {\n  background: none;\n  border: 0;\n  padding: 0;\n  color: inherit;\n  font: inherit;\n  font-size: 1.625rem;\n  font-weight: 600;\n  line-height: 1.1;\n  font-variant-numeric: tabular-nums;\n  cursor: pointer;\n  text-decoration: underline;\n  text-decoration-color: var(--petasos-line);\n  text-decoration-thickness: 1px;\n  text-underline-offset: 5px;\n}\n\n.petasos-stat-value:hover {\n  text-decoration-color: currentColor;\n}\n\n.petasos-stat-alarm .petasos-stat-value,\n.petasos-stat-alarm dt {\n  color: color-mix(in srgb, var(--color-destructive) 50%, white);\n}\n\n.petasos-light .petasos-stat-alarm .petasos-stat-value,\n.petasos-light .petasos-stat-alarm dt {\n  color: color-mix(in srgb, var(--color-destructive) 70%, black);\n}\n\n/* Setting changes that were not stopped: what that means, and the route. */\n.petasos-alarm-row {\n  display: flex;\n  align-items: center;\n  justify-content: space-between;\n  flex-wrap: wrap;\n  gap: 0.6rem 1rem;\n  padding: 0.65rem 0 0.1rem;\n  border-top: 1px solid var(--color-border);\n  font-size: 0.9rem;\n}\n\n.petasos-mini-list {\n  list-style: none;\n  margin: 0;\n  padding: 0;\n  border-top: 1px solid var(--color-border);\n}\n\n.petasos-mini-row {\n  display: grid;\n  grid-template-columns: 5rem minmax(0, 1fr) auto 1rem;\n  align-items: center;\n  gap: 0.9rem;\n  width: 100%;\n  padding: 0.55rem 0.15rem;\n  border: 0;\n  border-bottom: 1px solid var(--color-border);\n  background: none;\n  color: inherit;\n  font: inherit;\n  font-size: 0.9rem;\n  text-align: left;\n  cursor: pointer;\n}\n\n.petasos-mini-row:hover {\n  background: color-mix(in srgb, var(--midground) 6%, transparent);\n}\n\n.petasos-mini-when {\n  font-size: 0.8125rem;\n  color: var(--petasos-secondary);\n}\n\n/* A safety sentence wraps; it is never cut short. */\n.petasos-mini-text {\n  min-width: 0;\n  overflow-wrap: anywhere;\n}\n\n.petasos-repeat {\n  font-size: 0.8125rem;\n  font-weight: 700;\n}\n\n.petasos-chevron {\n  color: var(--petasos-tertiary);\n}\n\n/* ---- Overview: checks ------------------------------------------------ */\n\n.petasos-scanners {\n  list-style: none;\n  margin: 0;\n  padding: 0;\n  display: flex;\n  flex-direction: column;\n}\n\n.petasos-scanner {\n  display: flex;\n  flex-direction: column;\n  align-items: flex-start;\n  gap: 0.35rem;\n  padding: 0.7rem 0;\n  border-bottom: 1px solid var(--color-border);\n  font-size: 0.9rem;\n}\n\n.petasos-scanner:first-child {\n  padding-top: 0;\n}\n\n.petasos-scanner:last-child {\n  border-bottom: 0;\n  padding-bottom: 0;\n}\n\n.petasos-scanner-head {\n  display: flex;\n  align-items: center;\n  gap: 0.6rem;\n  width: 100%;\n}\n\n.petasos-scanner-name {\n  display: flex;\n  flex-direction: column;\n  gap: 0.1rem;\n  font-weight: 600;\n  margin-right: auto;\n}\n\n.petasos-scanner-product {\n  font-weight: 400;\n  font-size: 0.8125rem;\n  color: var(--petasos-secondary);\n}\n\n/* ---- Activity -------------------------------------------------------- */\n\n.petasos-filters {\n  display: flex;\n  flex-direction: column;\n  gap: 0.75rem;\n}\n\n.petasos-filter-row {\n  display: flex;\n  flex-wrap: wrap;\n  align-items: flex-end;\n  gap: 0.75rem 1.25rem;\n}\n\n.petasos-filter-row > .petasos-filter-group,\n.petasos-filter-row > .petasos-search {\n  align-self: center;\n}\n\n.petasos-filter-group {\n  display: flex;\n  align-items: center;\n  gap: 0.6rem;\n}\n\n.petasos-filter-label {\n  color: var(--petasos-secondary);\n}\n\n.petasos-search {\n  position: relative;\n  flex: 1 1 18rem;\n  max-width: 28rem;\n}\n\n.petasos-search input {\n  padding-left: 2rem;\n}\n\n.petasos-search-icon {\n  position: absolute;\n  left: 0.6rem;\n  top: 50%;\n  transform: translateY(-50%);\n  color: var(--petasos-tertiary);\n  pointer-events: none;\n}\n\n.petasos-range-row {\n  align-items: flex-start;\n}\n\n.petasos-tz {\n  align-self: center;\n}\n\n.petasos-datetime {\n  width: 15rem;\n}\n\n.petasos-datetime-box {\n  position: relative;\n}\n\n.petasos-datetime-box input {\n  padding-right: 2.2rem;\n}\n\n.petasos-datetime-pick {\n  position: absolute;\n  right: 0.25rem;\n  top: 50%;\n  transform: translateY(-50%);\n  display: inline-flex;\n  align-items: center;\n  justify-content: center;\n  width: 1.75rem;\n  height: 1.75rem;\n  border: 0;\n  background: none;\n  color: var(--petasos-ink);\n  cursor: pointer;\n}\n\n.petasos-datetime-pick:hover {\n  background: color-mix(in srgb, var(--midground) 10%, transparent);\n}\n\n/* The browser's picker, opened from the calendar button. Its own field is\n * not shown, so its date format never is. */\n.petasos-datetime-native {\n  position: absolute;\n  right: 0;\n  bottom: 0;\n  width: 1px;\n  height: 1px;\n  opacity: 0;\n  pointer-events: none;\n  border: 0;\n  padding: 0;\n  color-scheme: dark;\n}\n\n.petasos-light .petasos-datetime-native {\n  color-scheme: light;\n}\n\n.petasos-filter-selects {\n  display: grid;\n  grid-template-columns: repeat(4, minmax(0, 1fr));\n  gap: 0.75rem;\n}\n\n.petasos-choice {\n  display: flex;\n  flex-direction: column;\n  gap: 0.35rem;\n  min-width: 0;\n}\n\n.petasos-listbar {\n  display: flex;\n  align-items: center;\n  justify-content: space-between;\n  gap: 1rem;\n  flex-wrap: wrap;\n  padding-top: 0.25rem;\n  border-top: 1px solid var(--color-border);\n}\n\n.petasos-listbar-count {\n  padding-top: 0.6rem;\n}\n\n.petasos-listbar > .petasos-status,\n.petasos-listbar > .petasos-integrity {\n  margin-top: 0.6rem;\n}\n\n.petasos-integrity {\n  display: flex;\n  align-items: center;\n  flex-wrap: wrap;\n  gap: 0.35rem 0.8rem;\n}\n\n.petasos-split {\n  display: grid;\n  grid-template-columns: minmax(0, 1fr);\n  gap: 1rem;\n  align-items: start;\n}\n\n.petasos-split-open {\n  grid-template-columns: minmax(0, 1.3fr) minmax(24rem, 1fr);\n}\n\n/* With an event open, each row folds to two lines so the sentence keeps\n * its width: what happened and the outcome, then when and the severity. */\n.petasos-split-open .petasos-event-header {\n  display: none;\n}\n\n.petasos-split-open .petasos-event {\n  grid-template-columns: minmax(0, 1fr) auto 1rem;\n  row-gap: 0.3rem;\n}\n\n.petasos-split-open .petasos-event-what {\n  grid-column: 1;\n  grid-row: 1;\n}\n\n.petasos-split-open .petasos-event-outcome {\n  grid-column: 2;\n  grid-row: 1;\n  justify-self: end;\n}\n\n.petasos-split-open .petasos-event-when {\n  grid-column: 1;\n  grid-row: 2;\n}\n\n.petasos-split-open .petasos-event-when .petasos-block {\n  display: inline;\n  margin-right: 0.6rem;\n}\n\n.petasos-split-open .petasos-event-severity {\n  grid-column: 2;\n  grid-row: 2;\n  justify-self: end;\n}\n\n.petasos-split-open .petasos-chevron {\n  grid-column: 3;\n  grid-row: 1 / span 2;\n}\n\n.petasos-split-open .petasos-group-bar {\n  padding-left: 0.75rem;\n}\n\n.petasos-split-even {\n  grid-template-columns: repeat(2, minmax(0, 1fr));\n}\n\n/* Try it: the input beside a wider result; the checks run full width\n * beneath, so neither column is left half empty. */\n.petasos-split-try {\n  grid-template-columns: minmax(0, 1fr) minmax(0, 1.3fr);\n}\n\n.petasos-trial-grid {\n  display: grid;\n  grid-template-columns: repeat(2, minmax(0, 1fr));\n  gap: 1rem;\n}\n\n.petasos-split-main {\n  min-width: 0;\n}\n\n.petasos-list-card {\n  padding: 0.4rem 1rem 0.6rem;\n}\n\n.petasos-event-header,\n.petasos-event {\n  display: grid;\n  grid-template-columns: 8.5rem minmax(0, 1fr) 7rem 11rem 1rem;\n  align-items: center;\n  gap: 1rem;\n}\n\n.petasos-event-header {\n  padding: 0.6rem 0.75rem;\n  border-bottom: 1px solid var(--color-border);\n  font-family: var(--font-mondwest);\n  font-size: 0.78rem;\n  font-weight: 400;\n  letter-spacing: 0.08em;\n  text-transform: uppercase;\n  color: var(--petasos-secondary);\n}\n\n.petasos-events {\n  list-style: none;\n  margin: 0;\n  padding: 0;\n}\n\n.petasos-event-item {\n  border-bottom: 1px solid var(--color-border);\n}\n\n.petasos-events-nested {\n  border-top: 1px dashed var(--color-border);\n  margin-left: 1.5rem;\n}\n\n.petasos-events-nested .petasos-event-item:last-child {\n  border-bottom: 0;\n}\n\n.petasos-event {\n  position: relative;\n  width: 100%;\n  padding: 0.5rem 0.75rem;\n  border: 0;\n  background: none;\n  color: inherit;\n  font: inherit;\n  text-align: left;\n  cursor: pointer;\n}\n\n.petasos-event:hover {\n  background: color-mix(in srgb, var(--midground) 6%, transparent);\n}\n\n.petasos-event:hover .petasos-chevron {\n  color: var(--midground);\n}\n\n/* The open event: a tinted row with an edge marker, kept while its detail\n * is open. */\n.petasos-event-selected,\n.petasos-event-selected:hover {\n  background: color-mix(in srgb, var(--midground) 13%, transparent);\n  box-shadow: inset 3px 0 0 var(--midground);\n}\n\n.petasos-event-selected .petasos-chevron {\n  color: var(--midground);\n}\n\n.petasos-event-when {\n  font-size: 0.8125rem;\n  line-height: 1.45;\n  color: var(--petasos-secondary);\n}\n\n.petasos-event-what {\n  display: flex;\n  flex-direction: column;\n  gap: 0.15rem;\n  min-width: 0;\n}\n\n.petasos-event-summary {\n  font-size: 0.9375rem;\n}\n\n.petasos-event-meta {\n  display: flex;\n  flex-wrap: wrap;\n  align-items: center;\n  gap: 0.4rem;\n  font-size: 0.8125rem;\n  color: var(--petasos-secondary);\n}\n\n.petasos-event-meta .petasos-mono {\n  font-size: 0.8125rem;\n  color: var(--petasos-secondary);\n}\n\n.petasos-group-bar {\n  display: flex;\n  align-items: center;\n  gap: 1rem;\n  padding: 0 0.75rem 0.5rem 10.25rem;\n  font-size: 0.8125rem;\n  color: var(--petasos-secondary);\n}\n\n.petasos-more {\n  display: flex;\n  justify-content: center;\n  padding-top: 0.75rem;\n}\n\n.petasos-detail {\n  position: sticky;\n  top: 0.5rem;\n  display: flex;\n  flex-direction: column;\n  gap: 0.75rem;\n  padding: 1rem 1.1rem;\n  border: 1px solid var(--color-border);\n  box-shadow: inset 3px 0 0 var(--midground);\n  background: var(--color-card);\n  min-width: 0;\n}\n\n.petasos-detail-head {\n  display: flex;\n  align-items: center;\n  justify-content: space-between;\n  gap: 1rem;\n}\n\n.petasos-detail-which {\n  font-size: 0.875rem;\n  color: var(--petasos-secondary);\n}\n\n.petasos-detail-status {\n  display: flex;\n  align-items: center;\n  gap: 0.9rem;\n}\n\n.petasos-detail-title {\n  margin: 0;\n  font-size: 1.0625rem;\n  font-weight: 700;\n  line-height: 1.4;\n}\n\n.petasos-detail-note {\n  font-size: 0.9rem;\n  font-weight: 600;\n}\n\n/* ---- Try it ---------------------------------------------------------- */\n\n.petasos-try-desc {\n  font-size: 0.9375rem;\n}\n\n.petasos-trial-line {\n  font-size: 0.875rem;\n}\n\n.petasos-textarea {\n  width: 100%;\n  padding: 0.6rem 0.75rem;\n  border: 1px solid var(--petasos-control-line);\n  background: color-mix(in srgb, var(--background) 40%, transparent);\n  color: inherit;\n  font: inherit;\n  font-size: 0.9rem;\n  line-height: 1.5;\n  resize: vertical;\n}\n\n.petasos-mono-area {\n  font-family: var(--theme-font-mono);\n  font-size: 0.85rem;\n}\n\n.petasos-textarea:disabled {\n  opacity: 0.55;\n  cursor: not-allowed;\n}\n\n.petasos-field-error {\n  font-size: 0.875rem;\n  font-weight: 700;\n  color: color-mix(in srgb, var(--color-destructive) 45%, white);\n}\n\n.petasos-light .petasos-field-error {\n  color: color-mix(in srgb, var(--color-destructive) 70%, black);\n}\n\n.petasos-decision {\n  display: flex;\n  flex-direction: column;\n  align-items: flex-start;\n  gap: 0.5rem;\n}\n\n.petasos-decision-text {\n  font-size: 0.9375rem;\n}\n\n.petasos-compare {\n  display: grid;\n  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);\n  grid-template-rows: auto auto auto;\n  column-gap: 1.25rem;\n}\n\n.petasos-compare-cell {\n  display: grid;\n  grid-template-rows: subgrid;\n  grid-row: 1 / -1;\n  align-content: start;\n  row-gap: 0.45rem;\n  min-width: 0;\n}\n\n.petasos-compare-cell + .petasos-compare-cell {\n  padding-left: 1.25rem;\n  border-left: 1px solid var(--color-border);\n}\n\n.petasos-message,\n.petasos-marked {\n  margin: 0;\n  padding: 0.65rem 0.8rem;\n  border: 1px solid var(--color-border);\n  font-family: var(--theme-font-mono);\n  font-size: 0.85rem;\n  line-height: 1.55;\n  white-space: pre-wrap;\n  overflow-wrap: anywhere;\n}\n\n/* The matched text: a tinted, outlined span. Not underlined, because\n * underlined text only navigates. */\n.petasos-mark {\n  background: color-mix(in srgb, var(--color-destructive) 24%, transparent);\n  color: inherit;\n  outline: 1px solid color-mix(in srgb, var(--color-destructive) 65%, transparent);\n  outline-offset: 0;\n}\n\n.petasos-mark-n {\n  font-weight: 700;\n  margin-right: 0.1rem;\n}\n\n.petasos-findings,\n.petasos-tech-findings {\n  list-style: none;\n  margin: 0;\n  padding: 0;\n  display: flex;\n  flex-direction: column;\n}\n\n.petasos-tech-findings li {\n  display: grid;\n  grid-template-columns: 1.6rem minmax(0, 1fr);\n  gap: 0.6rem;\n  padding: 0.25rem 0;\n  font-size: 0.875rem;\n}\n\n.petasos-finding {\n  display: grid;\n  grid-template-columns: 1.6rem minmax(0, 1fr);\n  gap: 0.6rem;\n  padding: 0.6rem 0;\n  border-bottom: 1px solid var(--color-border);\n}\n\n.petasos-finding-n {\n  font-size: 0.85rem;\n  font-weight: 700;\n  text-align: center;\n  padding-top: 0.05rem;\n}\n\n.petasos-finding-body {\n  display: flex;\n  flex-direction: column;\n  gap: 0.35rem;\n  min-width: 0;\n}\n\n.petasos-finding-head {\n  display: flex;\n  align-items: flex-start;\n  justify-content: space-between;\n  gap: 0.75rem;\n}\n\n.petasos-finding-sentence {\n  font-size: 0.9375rem;\n}\n\n.petasos-took-part {\n  list-style: none;\n  margin: 0;\n  padding: 0;\n  display: grid;\n  grid-template-columns: max-content max-content minmax(0, 1fr);\n  gap: 0.45rem 0.85rem;\n  align-items: center;\n}\n\n.petasos-took-part li {\n  display: contents;\n}\n\n.petasos-took-name {\n  font-weight: 600;\n  font-size: 0.9rem;\n}\n\n.petasos-quieted {\n  list-style: none;\n  margin: 0;\n  padding: 0;\n  display: flex;\n  flex-direction: column;\n  gap: 0.35rem;\n  font-size: 0.875rem;\n}\n\n/* One row per rule: its sentence and id on the left, the action in a fixed\n * column on the right. */\n.petasos-quieted li {\n  display: grid;\n  grid-template-columns: minmax(0, 1fr) auto;\n  gap: 0.25rem 1rem;\n  align-items: center;\n  padding: 0.45rem 0;\n  border-bottom: 1px solid var(--color-border);\n}\n\n.petasos-quieted li:first-child {\n  border-top: 1px solid var(--color-border);\n}\n\n.petasos-quieted-name {\n  display: flex;\n  flex-direction: column;\n  gap: 0.1rem;\n  min-width: 0;\n}\n\n/* ---- Settings: Config's layout -------------------------------------- */\n\n.petasos-settings-toolbar {\n  position: relative;\n  display: flex;\n  flex-wrap: wrap;\n  align-items: center;\n  gap: 0.75rem 1.5rem;\n}\n\n.petasos-settings-toolbar .petasos-search {\n  max-width: 26rem;\n}\n\n.petasos-savebox {\n  display: flex;\n  align-items: center;\n  gap: 0.6rem;\n  margin-left: auto;\n}\n\n/* The count of staged changes opens the list beneath: a disclosure, so it\n * is a quiet toggle with a chevron, not underlined. */\n.petasos-changecount {\n  display: inline-flex;\n  align-items: center;\n  gap: 0.3rem;\n  padding: 0.2rem 0.1rem;\n  border: 0;\n  background: none;\n  color: var(--petasos-ink);\n  font: inherit;\n  font-size: 0.875rem;\n  font-weight: 600;\n  cursor: pointer;\n}\n\n.petasos-changecount-chevron {\n  transform: rotate(90deg);\n  transition: transform 120ms;\n}\n\n.petasos-changecount[aria-expanded=\"true\"] .petasos-changecount-chevron {\n  transform: rotate(-90deg);\n}\n\n.petasos-settings-body {\n  display: grid;\n  grid-template-columns: 13.5rem minmax(0, 1fr);\n  gap: 1rem;\n  align-items: start;\n}\n\n/* The section list, as Config draws it: small rows, a tint on the open\n * one, counts in tertiary text. */\n.petasos-sections {\n  display: flex;\n  flex-direction: column;\n  gap: 1px;\n  padding: 0.5rem;\n  border: 1px solid var(--color-border);\n  background: color-mix(in srgb, var(--color-muted, var(--color-card)) 20%, transparent);\n  position: sticky;\n  top: 0.5rem;\n}\n\n.petasos-sections-title {\n  padding: 0.2rem 0.5rem 0.35rem;\n  font-size: 0.75rem;\n  letter-spacing: 0.12em;\n  color: var(--petasos-tertiary);\n}\n\n.petasos-section {\n  display: flex;\n  align-items: center;\n  gap: 0.4rem;\n  padding: 0.25rem 0.5rem;\n  border: 0;\n  background: none;\n  color: var(--petasos-secondary);\n  font-family: var(--theme-font-mono);\n  font-size: 0.8rem;\n  text-align: left;\n  cursor: pointer;\n}\n\n.petasos-section:hover {\n  background: color-mix(in srgb, var(--midground) 7%, transparent);\n  color: var(--midground);\n}\n\n.petasos-section-on,\n.petasos-section-on:hover {\n  background: color-mix(in srgb, var(--midground) 12%, transparent);\n  color: var(--midground);\n}\n\n.petasos-section-name {\n  margin-right: auto;\n}\n\n.petasos-section-changed {\n  font-size: 0.55rem;\n}\n\n.petasos-section-count {\n  font-size: 0.75rem;\n  color: var(--petasos-tertiary);\n  font-variant-numeric: tabular-nums;\n}\n\n.petasos-section-on .petasos-section-count {\n  color: var(--petasos-secondary);\n}\n\n.petasos-settings-main {\n  min-width: 0;\n}\n\n.petasos-group {\n  display: flex;\n  flex-direction: column;\n}\n\n.petasos-group-head {\n  display: flex;\n  align-items: center;\n  gap: 0.6rem;\n  padding-top: 0.9rem;\n}\n\n.petasos-group-name {\n  font-family: var(--font-mondwest);\n  font-size: 0.75rem;\n  font-weight: 400;\n  letter-spacing: 0.1em;\n  text-transform: uppercase;\n  color: var(--petasos-secondary);\n}\n\n.petasos-group-rule {\n  flex: 1;\n  border-top: 1px solid var(--color-border);\n}\n\n/* One field, as Config draws it: label, key, sentence, control beneath.\n * Tight within a field, a larger gap between fields. */\n.petasos-field {\n  display: flex;\n  flex-direction: column;\n  gap: 0.4rem;\n  padding: 0.85rem 0 0.95rem;\n  scroll-margin: 1rem;\n}\n\n\n.petasos-field-head {\n  display: flex;\n  align-items: flex-start;\n  justify-content: space-between;\n  gap: 1.5rem;\n}\n\n.petasos-field-text {\n  display: flex;\n  flex-direction: column;\n  gap: 0.2rem;\n  min-width: 0;\n}\n\n.petasos .petasos-field-label {\n  font-family: var(--font-mondwest);\n  font-size: 0.875rem;\n  font-weight: 400;\n  letter-spacing: 0.08em;\n  line-height: 1.3;\n  text-transform: uppercase;\n  color: var(--petasos-ink);\n}\n\n.petasos-field-key {\n  font-family: var(--theme-font-mono);\n  font-size: 0.75rem;\n  color: var(--petasos-tertiary);\n}\n\n.petasos-field-help {\n  font-size: 0.8125rem;\n  color: var(--petasos-secondary);\n  max-width: 60rem;\n}\n\n.petasos-field-switch {\n  padding-top: 0.1rem;\n}\n\n.petasos-field-control {\n  min-width: 0;\n}\n\n.petasos-field-staged .petasos-field-label::after {\n  content: \" \u2022\";\n}\n\n.petasos-staged-word {\n  color: var(--petasos-ink);\n}\n\n.petasos-field-invalid input,\n.petasos-field-invalid textarea {\n  border-width: 2px;\n  border-style: solid;\n  border-color: var(--color-destructive) !important;\n}\n\n.petasos-field-invalid input:focus-visible,\n.petasos-field-invalid textarea:focus-visible {\n  outline: 2px solid var(--midground);\n  outline-offset: 2px;\n}\n\n/* Background emphasis only on the field being edited or in error. */\n.petasos-field-staged,\n.petasos-field-invalid {\n  background: color-mix(in srgb, var(--midground) 5%, transparent);\n  margin: 0 -0.6rem;\n  padding-left: 0.6rem;\n  padding-right: 0.6rem;\n}\n\n/* What a Required check that cannot run does, before Save. */\n.petasos-consequence {\n  font-size: 0.875rem;\n  padding-left: 0.6rem;\n  border-left: 2px solid var(--color-warning);\n}\n\n.petasos-maprows {\n  display: flex;\n  flex-direction: column;\n  gap: 0.4rem;\n}\n\n.petasos-maprow {\n  display: grid;\n  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) 5.5rem;\n  gap: 0.5rem;\n  align-items: center;\n}\n\n.petasos-rule-helper .petasos-kv {\n  font-size: 0.875rem;\n}\n\n/* ---- Narrow ---------------------------------------------------------- */\n\n@media (max-width: 1100px) {\n  .petasos-split-open,\n  .petasos-split-even,\n  .petasos-split-try,\n  .petasos-grid-3 {\n    grid-template-columns: minmax(0, 1fr);\n  }\n  .petasos-detail {\n    position: static;\n  }\n  .petasos-filter-selects {\n    grid-template-columns: repeat(2, minmax(0, 1fr));\n  }\n  .petasos-stats {\n    grid-template-columns: repeat(3, minmax(0, 1fr));\n  }\n}\n\n@media (max-width: 1000px) {\n  .petasos-grid-2,\n  .petasos-setup-grid,\n  .petasos-settings-body,\n  .petasos-compare {\n    grid-template-columns: minmax(0, 1fr);\n    grid-template-rows: none;\n  }\n  .petasos-compare-cell {\n    display: flex;\n    flex-direction: column;\n    grid-row: auto;\n  }\n  .petasos-compare-cell + .petasos-compare-cell {\n    padding-left: 0;\n    border-left: 0;\n    padding-top: 0.8rem;\n    border-top: 1px solid var(--color-border);\n  }\n  .petasos-sections {\n    position: static;\n    flex-direction: row;\n    flex-wrap: wrap;\n  }\n  .petasos-event-header {\n    display: none;\n  }\n  .petasos-event {\n    grid-template-columns: minmax(0, 1fr) auto 1rem;\n  }\n  .petasos-event-when {\n    grid-column: 1 / -1;\n  }\n  .petasos-event-severity {\n    display: none;\n  }\n  .petasos-group-bar {\n    padding-left: 0.75rem;\n  }\n  .petasos-opt {\n    grid-template-columns: 7rem minmax(0, 1fr);\n  }\n  .petasos-mini-row {\n    grid-template-columns: 3.5rem minmax(0, 1fr) auto 1rem;\n    gap: 0.7rem;\n  }\n}\n";

  (function addStyle() {
    if (document.getElementById("petasos-tab-style")) return;
    var element = document.createElement("style");
    element.id = "petasos-tab-style";
    element.textContent = STYLE;
    document.head.appendChild(element);
  })();
  // ===== dashboard-src/05-shared.js =====
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
            change.applies ? " · " + change.applies : "",
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
  // ===== dashboard-src/10-overview.js =====
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
      props.finding && props.finding.count
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
            currentRole: currentRole,
            currentLevel: currentLevel,
            busy: busyState[0],
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

  // The pending change, on its own inset surface: when it applies, the usual
  // pairing stated as a trade, and one button that names both controls as
  // they stand.
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

  // The figures, as Hermes's System page lays them out: a small label above,
  // the value beneath at a size that reads as the value. Each figure is a
  // grid cell whose value sits on the cell's last row, so values stay on one
  // line when a label wraps. The figures are the API's, and they add up to
  // the total above them.
  function RecentPanel(props) {
    var summary = props.summary;
    var events = props.events || [];
    var tiles = (summary && summary.figures) || [];
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
          var value = tile.count;
          return h(
            "div",
            { key: tile.code, className: "petasos-stat" },
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
                    go("activity", {
                      range: "24h",
                      outcome: (tile.outcomes || [tile.code]).join(","),
                      word: tile.label,
                    });
                  },
                },
                String(value)
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
          finding: summaryState[0] && summaryState[0].finding,
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
  // ===== dashboard-src/20-activity.js =====
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
  // are the API's outcome codes; the reader filters on them, so paging and
  // counts agree with the list.
  var OUTCOME_CODES = {
    blocked: ["blocked", "stopped", "attempt_blocked"],
    asked: ["asked", "attempt_asked"],
    flagged: ["flagged"],
    allowed: ["allowed"],
    not_stopped: ["not_stopped"],
  };

  var OUTCOME_FILTER_WORDS = {
    blocked: "blocked",
    asked: "asked a person",
    flagged: "flagged to the agent",
    allowed: "let through while paused",
    not_stopped: "setting changes not stopped",
  };

  // A custom range is kept as YYYY-MM-DDTHH:MM in the browser's time zone and
  // shown as YYYY-MM-DD HH:MM, which no reader can take for another date.
  function parseLocal(value) {
    var match = String(value || "").trim().match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})$/);
    if (!match) return null;
    var date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]), Number(match[4]), Number(match[5]));
    if (date.getMonth() !== Number(match[2]) - 1 || date.getDate() !== Number(match[3])) return null;
    return date;
  }

  function localSeconds(value) {
    var date = parseLocal(value);
    return date ? Math.floor(date.getTime() / 1000) : null;
  }

  function localStamp(date) {
    function pad(n) {
      return String(n).padStart(2, "0");
    }
    return (
      date.getFullYear() + "-" + pad(date.getMonth() + 1) + "-" + pad(date.getDate()) + "T" + pad(date.getHours()) + ":" + pad(date.getMinutes())
    );
  }

  // One end of a custom range: a text field in an unambiguous form, and a
  // calendar button that opens the browser's own picker.
  function DateTimeField(props) {
    var pickerRef = useRef(null);
    var textState = useState(String(props.value || "").replace("T", " "));
    useEffect(
      function () {
        textState[1](String(props.value || "").replace("T", " "));
      },
      [props.value]
    );
    var invalid = textState[0].trim() !== "" && !parseLocal(textState[0]);
    function commit(text) {
      var date = parseLocal(text);
      if (date) props.onChange(localStamp(date));
      else if (!text.trim()) props.onChange("");
    }
    return h(
      "div",
      { className: "petasos-choice petasos-datetime" },
      h(C.Label, { className: "petasos-label", htmlFor: props.id }, props.label),
      h(
        "div",
        { className: "petasos-datetime-box" },
        h(C.Input, {
          id: props.id,
          value: textState[0],
          placeholder: "YYYY-MM-DD HH:MM",
          inputMode: "numeric",
          "aria-invalid": invalid ? "true" : undefined,
          "aria-describedby": props.id + "-format",
          onChange: function (event) {
            textState[1](event.target.value);
          },
          onBlur: function () {
            commit(textState[0]);
          },
          onKeyDown: function (event) {
            if (event.key === "Enter") commit(textState[0]);
          },
        }),
        h(
          "button",
          {
            type: "button",
            className: "petasos-datetime-pick",
            "aria-label": "Choose " + props.label.toLowerCase() + " on a calendar",
            onClick: function () {
              var picker = pickerRef.current;
              if (!picker) return;
              picker.value = props.value || "";
              if (picker.showPicker) picker.showPicker();
              else picker.focus();
            },
          },
          h(Icon, { name: "calendar", size: 16 })
        ),
        h("input", {
          ref: pickerRef,
          type: "datetime-local",
          className: "petasos-datetime-native",
          tabIndex: -1,
          "aria-hidden": true,
          onChange: function (event) {
            if (event.target.value) props.onChange(event.target.value.slice(0, 16));
          },
        })
      ),
      h(
        "p",
        { className: cn("petasos-tertiary", invalid && "petasos-field-error"), id: props.id + "-format" },
        invalid ? "Write it as YYYY-MM-DD HH:MM." : "Year-month-day, 24-hour clock"
      )
    );
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
    var tone = integrity.mode === "verified" ? "success" : integrity.mode === "off" ? "warning" : "destructive";
    var badge = h(
      Status,
      { tone: tone, title: integrity.mode === "off" ? integrity.reason : undefined },
      integrity.label
    );
    if (!integrity.limit) return badge;
    return h(
      "div",
      { className: "petasos-integrity" },
      badge,
      h(Disclosure, { label: integrity.limit_label, openLabel: "Hide what a signature shows" }, integrity.limit)
    );
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
          title: "Records are not signed yet",
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
                openState[0] ? "Hide the steps" : "Set up record signing"
              )
            : null,
        },
        h("p", null, "Without a signature, a changed record could go unnoticed."),
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
        "A marked record was changed after Petasos wrote it, or written by something else. Do not trust it."
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
      if (key === "range" && value === "custom" && !next.from && !next.to) {
        var now = new Date();
        next.from = localStamp(new Date(now.getTime() - 86400000));
        next.to = localStamp(now);
      }
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
            "aria-label": "Search activity",
            placeholder: "Search activity",
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
            { className: "petasos-filter-row petasos-range-row" },
            h(DateTimeField, {
              id: "petasos-from",
              label: "From",
              value: filters.from || "",
              onChange: function (value) {
                set("from", value);
              },
            }),
            h(DateTimeField, {
              id: "petasos-to",
              label: "To",
              value: filters.to || "",
              onChange: function (value) {
                set("to", value);
              },
            })
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
        "aria-label": (props.selected ? "Open now: " : "Open details: ") + event.summary + ", " + listTime(event.timestamp),
        onClick: props.onOpen,
      },
      h(
        "span",
        { className: "petasos-event-when" },
        h("span", { className: "petasos-block" }, listTime(event.timestamp)),
        h("span", { className: "petasos-block petasos-tertiary" }, whenText(event.timestamp))
      ),
      h(
        "span",
        { className: "petasos-event-what" },
        h("span", { className: "petasos-event-summary" }, event.summary),
        h(
          "span",
          { className: "petasos-event-meta" },
          event.tool ? h(Mono, null, event.tool) : null,
          event.tool && event.session_id ? h("span", { "aria-hidden": true }, "·") : null,
          event.session_id ? h("span", null, event.session_id) : null,
          failed ? h(Status, { tone: "destructive" }, "Signature does not match") : null
        )
      ),
      h("span", { className: "petasos-event-severity" }, h(Severity, { value: event.severity, label: event.severity_label })),
      h("span", { className: "petasos-event-outcome" }, h(Status, { tone: outcomeTone(outcome.code), state: outcome.code }, outcome.label || "Recorded")),
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
    var open = openState[0] || (inside && first.scan_id !== props.selectedId);
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
          "button",
          {
            type: "button",
            className: "petasos-disclosure-toggle",
            "aria-expanded": open,
            onClick: function () {
              openState[1](!open);
            },
          },
          h(Icon, { name: "chevron", size: 14, className: cn("petasos-disclosure-chevron", open && "petasos-chevron-open") }),
          h("span", null, open ? "Hide the " + count : "Show all " + count)
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
    target: 1, outcome_note: 1, risk_block: 1, review_action: 1,
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
    var review = event.review_action;
    // Stopped by the conversation's risk score, which earlier warnings built up.
    var risky = Boolean(event.session_id && event.risk_block);
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
        h(
          "p",
          { className: "petasos-detail-which" },
          listTime(event.timestamp),
          event.session_id ? " · " + event.session_id : ""
        ),
        h(Btn, { ghost: true, onClick: props.onClose, "aria-label": "Close event details" }, "Close")
      ),
      h(
        "div",
        { className: "petasos-detail-status" },
        h(Status, { tone: outcomeTone(outcome.code), large: true, state: outcome.code }, outcome.label || "Recorded"),
        h(Severity, { value: event.severity, label: event.severity_label })
      ),
      h("h3", { className: "petasos-detail-title", id: "petasos-detail-title" }, event.summary),
      event.outcome_note ? h("p", { className: "petasos-detail-note" }, event.outcome_note) : null,
      review || risky
        ? h(
            "div",
            { className: "petasos-row-actions" },
            review
              ? h(Btn, { outlined: true, onClick: function () { go("settings", { changed: "1" }); } }, review)
              : null,
            risky
              ? h(
                  Btn,
                  {
                    outlined: true,
                    onClick: function () {
                      props.onFilter({ range: "all", session: event.session_id, event: event.scan_id });
                    },
                  },
                  "Show earlier warnings"
                )
              : null
          )
        : null,
      h(KeyValues, {
        rows: [
          ["When", h(Fragment, null, fullTime(event.timestamp), h("span", { className: "petasos-tertiary" }, " · " + whenText(event.timestamp)))],
          ["Kind", event.kind_label || event.event_type],
          ["Tool", event.tool ? h(Mono, null, event.tool) : null],
          ["Conversation", event.session_id ? h(Mono, null, event.session_id) : null],
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
                  h("span", { className: "petasos-idrow petasos-tertiary" }, h(Ident, null, rule), h(CopyButton, { value: rule, label: "Copy rule id" }))
                )
              : null,
          ],
          ["Matched text", event.matched_note || null],
          ["Signature", integrity.meaning || null],
        ],
      }),
      h(
        "div",
        { className: "petasos-row-actions" },
        // A rule that matches text can be tested by pasting the text again. A
        // settings-change rule matches the file a call targets, not text.
        rule && rule.indexOf("petasos.selfmod.") !== 0
          ? h(
              Btn,
              {
                outlined: true,
                onClick: function () {
                  go("tryit", {
                    rule: rule,
                    sentence: event.rule_sentence || "",
                    direction: event.event_type === "ingest_flagged" ? "inbound" : "outbound",
                  });
                },
              },
              "Try this rule"
            )
          : null,
        rule && rule.indexOf("petasos.syntactic.") === 0
          ? h(LinkButton, { onClick: function () { go("settings", { rule: rule }); } }, "Rule settings")
          : null,
        event.session_id && !risky
          ? h(
              LinkButton,
              {
                onClick: function () {
                  props.onFilter({ session: event.session_id, event: event.scan_id });
                },
              },
              "Show this conversation"
            )
          : null
      ),
      h(
        Disclosure,
        { label: "Technical detail", openLabel: "Hide technical detail", remember: "activity-technical" },
        h(KeyValues, {
          stacked: true,
          rows: [
            ["Event id", h("span", { className: "petasos-idrow" }, h(Ident, null, event.scan_id), h(CopyButton, { value: event.scan_id, label: "Copy event id" }))],
            ["Event type", h(Mono, null, event.event_type)],
            ["Rule's note", event.reason && !event.target ? event.reason : null],
          ].concat(
            others.map(function (key) {
              var value = event[key];
              return [key, h(Mono, null, typeof value === "object" ? JSON.stringify(value) : String(value))];
            })
          ),
        })
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
    var countState = useState(null);
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

    var codes = filters.outcome
      ? OUTCOME_CODES[filters.outcome] || filters.outcome.split(",").filter(Boolean)
      : [];
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
      outcome: codes.join(","),
    };
    var key = JSON.stringify([request, filters.range === "custom" ? 0 : Math.floor(Date.now() / 600000)]);

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
        // The choices in each filter list come from the time range and search
        // alone; the count above the list uses every filter, as the list does.
        call("/activity/summary" + query({ since: now.since, until: now.until, q: filters.q }))
          .then(optionsState[1])
          .catch(function () {});
        var counted = Object.assign({}, live);
        delete counted.limit;
        call("/activity/summary" + query(counted))
          .then(countState[1])
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
    var selected = events.filter(function (event) {
      return event.scan_id === selectedId;
    })[0];
    var selectedInList = Boolean(selected);

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

    // Keep the open event's row in view beside its detail.
    useEffect(
      function () {
        if (!selectedId || !selectedInList) return;
        var timer = window.setTimeout(function () {
          var row = document.getElementById("petasos-event-" + selectedId);
          if (!row) return;
          var box = row.getBoundingClientRect();
          if (box.top < 80 || box.bottom > window.innerHeight - 40) revealInView(row, "center");
        }, 60);
        return function () {
          window.clearTimeout(timer);
        };
      },
      [selectedId, selectedInList]
    );

    var tail = older.length ? older[older.length - 1] : page;
    var options = optionsState[0];
    var counts = countState[0];
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
      list = h("p", { className: "petasos-secondary", role: "status" }, "Loading activity…");
    } else if (!events.length && neverRecorded) {
      list = h(
        Empty,
        {
          title: "Nothing recorded yet",
          action: h(Btn, { outlined: true, onClick: function () { go("tryit", { example: "notes" }); } }, "Try it"),
        },
        "Blocks, approval requests and warnings are recorded here. Clean actions are not."
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
        filtered ? "Try a longer time range or fewer filters." : "No blocks, approval requests or warnings in this time."
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
          : page.complete === false
            ? h("p", { className: "petasos-secondary petasos-end" }, "Older events were not read.")
            : null
      );
    }

    var count = counts
      ? plural(counts.total, "event") + " · " + plural(counts.blocked || 0, "tool call") + " blocked"
      : "";

    return h(
      "div",
      { className: "petasos-stack petasos-activity" },
      h(ActivityFilters, { filters: filters, options: options, onChange: setFilters }),
      h(
        "div",
        { className: "petasos-listbar" },
        h(
          "p",
          { className: "petasos-listbar-count", role: "status" },
          count && !neverRecorded ? h("span", { className: "petasos-count" }, count) : null,
          filters.outcome
            ? h(
                "span",
                { className: "petasos-secondary" },
                " · Only " + (params.word || OUTCOME_FILTER_WORDS[filters.outcome] || filters.outcome) + " ",
                h(Btn, { ghost: true, compact: true, onClick: function () { setFilters(Object.assign({}, filters, { outcome: "" })); } }, "Show every outcome")
              )
            : null,
          events.length ? h("span", { className: "petasos-secondary" }, " · Newest first · Times in " + timeZoneName()) : null
        ),
        page ? h(IntegrityStatus, { integrity: page.integrity }) : null
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
  // ===== dashboard-src/30-tryit.js =====
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
  // ===== dashboard-src/40-settings.js =====
  // ---------------------------------------------------------------------------
  // Settings: every value, laid out as Hermes's Config page lays out its own.
  // Save sits in the toolbar and saves; the count of staged changes beside it
  // opens the list of what will change. Rows, labels, help, bounds, choices
  // and where each value comes from all come from the API.
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
    if (isMapping(row)) return "";
    return String(value);
  }

  // True when a value is not its default, compared as data.
  function differs(row) {
    return JSON.stringify(row.value === undefined ? null : row.value) !== JSON.stringify(row.default === undefined ? null : row.default);
  }

  // The value's state in words, for the line under a control: On, the
  // choice's label, a count, or the value itself.
  function stateWords(row, value) {
    if (row.type === "bool") return value === true ? "On" : "Off";
    if (row.choices && row.choices.length) return showValue(value, row);
    if (isList(row)) return value && value.length ? plural(value.length, "item") : "None";
    if (isMapping(row)) {
      if (value === null || value === undefined) return "Built in";
      var n = Object.keys(value).length;
      return n ? plural(n, "entry", "entries") : "None";
    }
    if (value === null || value === undefined || value === "") return "Not set";
    return String(value);
  }

  // A mapping, edited as rows: two labelled fields per entry, named by the
  // schema's entry labels, with Add and Remove. Built from Hermes's inputs and
  // buttons; Hermes's Config has no editor for adding entries to a mapping.
  function MappingRows(props) {
    var row = props.row;
    var labels = row.entry_labels || ["Name", "Value"];
    var numeric = String(row.type).indexOf("float") >= 0;
    function fromValue(value) {
      return Object.keys(value || {}).map(function (key) {
        return { key: key, value: value[key] === null || value[key] === undefined ? "" : String(value[key]) };
      });
    }
    var rowsState = useState(function () {
      return fromValue(props.value);
    });
    var entries = rowsState[0];
    function toValue(list) {
      var out = {};
      list.forEach(function (entry) {
        var key = entry.key.trim();
        if (!key) return;
        var text = entry.value.trim();
        var number = Number(text);
        out[key] = numeric && text !== "" && isFinite(number) ? number : text;
      });
      return out;
    }
    // A change from outside (Undo, Discard, a rule lowered elsewhere) resets
    // the rows; an edit made here produces the same value and keeps them.
    var incoming = JSON.stringify(props.value || {});
    useEffect(
      function () {
        if (JSON.stringify(toValue(entries)) !== incoming) rowsState[1](fromValue(props.value));
      },
      [incoming]
    );
    function update(list) {
      rowsState[1](list);
      var value = toValue(list);
      if (!Object.keys(value).length && row.nullable) props.onValue(null);
      else props.onValue(value);
    }
    var id = fieldId(row.path);
    return h(
      "div",
      { className: "petasos-maprows", role: "group", "aria-labelledby": id + "-label", "aria-describedby": props.describedBy },
      entries.length
        ? h(
            "div",
            { className: "petasos-maprow petasos-maprow-head", "aria-hidden": true },
            h("span", { className: "petasos-label" }, labels[0]),
            h("span", { className: "petasos-label" }, labels[1]),
            h("span", null)
          )
        : null,
      entries.map(function (entry, index) {
        return h(
          "div",
          { key: index, className: "petasos-maprow" },
          h(C.Input, {
            id: index === 0 ? id : undefined,
            value: entry.key,
            disabled: props.disabled,
            "aria-label": labels[0] + " " + (index + 1),
            onChange: function (e) {
              var next = entries.slice();
              next[index] = { key: e.target.value, value: entry.value };
              update(next);
            },
          }),
          h(C.Input, {
            value: entry.value,
            disabled: props.disabled,
            inputMode: numeric ? "decimal" : undefined,
            "aria-label": labels[1] + " " + (index + 1),
            onChange: function (e) {
              var next = entries.slice();
              next[index] = { key: entry.key, value: e.target.value };
              update(next);
            },
          }),
          h(
            Btn,
            {
              ghost: true,
              disabled: props.disabled,
              "aria-label": "Remove " + (entry.key || labels[0].toLowerCase() + " " + (index + 1)),
              onClick: function () {
                update(entries.filter(function (_item, at) {
                  return at !== index;
                }));
              },
            },
            "Remove"
          )
        );
      }),
      h(
        "div",
        null,
        h(
          Btn,
          {
            outlined: true,
            disabled: props.disabled,
            onClick: function () {
              rowsState[1](entries.concat([{ key: "", value: "" }]));
            },
          },
          "Add"
        )
      )
    );
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
    if (isMapping(row)) {
      return h(MappingRows, { row: row, value: props.value, disabled: props.disabled, describedBy: described, onValue: props.onValue });
    }
    if (isList(row)) {
      return h("textarea", {
        id: id,
        className: "petasos-textarea petasos-mono-area",
        rows: Math.min(8, Math.max(2, String(props.text).split("\n").length + 1)),
        value: props.text,
        disabled: props.disabled,
        placeholder: "One per line",
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

  // One field as Config draws it, with one secondary line beneath the control
  // that states the value and where it comes from together ("On · Default"),
  // and, where they apply, the allowed range, a restart, and Reset or Undo.
  function FieldRow(props) {
    var row = props.row;
    var saved = props.saved || row;
    var staged = props.staged;
    var change = props.change;
    var id = fieldId(row.path);
    var bounds = isNumber(row) ? boundsText(row) : "";
    var catalog = props.catalog;
    var stored = catalog.stored || {};
    var parts = [];
    var action = null;
    if (props.lockedHere) {
      parts.push(stateWords(row, props.value), "Locked by your administrator");
    } else if (staged) {
      parts.push(h("strong", { key: "s", className: "petasos-staged-word" }, "Changed, not saved"));
      if (change) parts.push("was " + stateWords(row, change.before));
      action = h(Btn, { ghost: true, compact: true, onClick: props.onUnstage }, "Undo");
    } else {
      parts.push(stateWords(row, props.value), originText(saved.origin, stored, catalog));
      var target = saved.origin === "override" ? saved.reset_to : null;
      if (target && !props.disabled) {
        action = h(
          Btn,
          { ghost: true, compact: true, onClick: props.onReset, "aria-label": "Reset " + rowLabel(row) + " to " + showValue(target.value, row) },
          "Reset to " + stateWords(row, target.value)
        );
      }
    }
    if (bounds) parts.push("Allowed: " + bounds);
    if (row.restart) parts.push("After a Hermes restart");
    var line = [];
    parts.forEach(function (part, index) {
      if (index) line.push(h("span", { key: "d" + index, "aria-hidden": true, className: "petasos-dot" }, " · "));
      line.push(typeof part === "string" ? h("span", { key: "p" + index }, part) : part);
    });
    if (action) {
      line.push(h("span", { key: "da", "aria-hidden": true, className: "petasos-dot" }, " · "));
      line.push(h(Fragment, { key: "a" }, action));
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
        className: cn(staged && "petasos-field-staged", props.error && "petasos-field-invalid"),
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
      props.consequence
        ? h(
            "p",
            { className: "petasos-consequence", role: "status" },
            h(
              "strong",
              null,
              (row.restart ? "Once in use: " : staged ? "On save: " : "") + props.consequence.title + ". "
            ),
            props.consequence.sentence
          )
        : null,
      h("p", { className: "petasos-provenance", id: id + "-state" }, line)
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
        actions: h(Btn, { ghost: true, onClick: props.onClose }, "Close"),
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
        h(LinkButton, { onClick: function () { go("tryit", { rule: rule, sentence: props.sentence || "" }); } }, "Test it in Try it")
      ),
      h("p", { className: "petasos-secondary" }, "Not saved until you press Save.")
    );
  }

  // The list of staged changes, opened from the count beside Save: an ordinary
  // panel under the toolbar that pushes the form down.
  function ChangeSheet(props) {
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
      "div",
      {
        id: "petasos-change-sheet",
        onKeyDown: function (event) {
          if (event.key === "Escape") props.onClose();
        },
      },
      h(
        Panel,
        {
          className: "petasos-sheet",
          title: "What will change",
          titleId: "petasos-sheet-title",
          description: draft.enabled === false ? "Pausing applies from the agent's next tool call." : (preview && preview.applies) || "",
          actions: h(Btn, { ghost: true, onClick: props.onClose, "aria-label": "Close the list of changes" }, "Close"),
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
                  h("p", { className: "petasos-change-values" }, h("span", { className: "petasos-before" }, item[1]), h("span", { className: "petasos-arrow", "aria-hidden": true }, " → "), h("span", { className: "sr-only" }, " becomes "), h("strong", null, item[2]))
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
        })
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
    var sectionState = useState(
      params.changed ? "changed" : params.rule ? "rules" : params.path ? topOf({ path: params.path }) || "general" : "basics"
    );
    var section = sectionState[0];
    var resetState = useState(null);
    var reviewState = useState(params.review === "1");
    var reviewing = reviewState[0];
    var toolbarRef = useRef(null);

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
      reviewState[1](false);
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
          var effect = String(body.restart_message || "").replace(/^Reset\.\s*/, "");
          afterWrite(body, [body.message, effect].filter(Boolean).join(" "));
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

    var changedRows = rows.filter(function (row) {
      return differs(row) || hasIn(draft.overrides, row.path);
    });
    var navItems = [
      { key: "basics", label: "Basics", count: 3 },
      { key: "changed", label: "Changed from default", count: changedRows.length },
    ].concat(
      tops.map(function (top) {
        return { key: top || "general", label: sectionLabel(top), count: counts[top] || 0, changed: changed[top] || 0 };
      })
    );
    var changedView = !search && section === "changed";
    var activeTop = section === "basics" || section === "changed" ? null : section === "general" ? "" : section;
    var shown = search
      ? rows.filter(visible)
      : changedView
        ? changedRows
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
      var consequences = (preview && preview.valid && preview.consequences) || (empty ? catalog.consequences : null) || {};
      return h(FieldRow, {
        consequence: row.value === "on" ? consequences[row.path] : null,
        key: row.path,
        catalog: catalog,
        row: row,
        saved: saved,
        staged: staged,
        change: changeBy[row.path],
        value: row.value,
        text: text,
        error: problem ? fieldProblem(row, row.path in texts ? texts[row.path] : undefined, problem) : null,
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
      }, h(
        "p",
        { className: "petasos-provenance" },
        enabledNow ? "On" : "Paused",
        draft.enabled !== undefined && draft.enabled !== (stored.enabled !== false) ? h(Fragment, null, h("span", { className: "petasos-dot", "aria-hidden": true }, " · "), h("strong", { className: "petasos-staged-word" }, "Changed, not saved")) : null
      )),
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

    var staged = changeCount + topChanges;
    var toolbar = h(
      "div",
      { className: "petasos-settings-toolbar", role: "toolbar", "aria-label": "Settings", ref: toolbarRef },
      h(
        "div",
        { className: "petasos-search" },
        h(Icon, { name: "search", className: "petasos-search-icon" }),
        h(C.Input, {
          type: "search",
          id: "petasos-settings-search",
          placeholder: "Search settings",
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
        empty
          ? h("span", { className: "petasos-secondary", role: "status" }, "No unsaved changes")
          : invalid
            ? h("span", { className: "petasos-secondary petasos-strong", role: "status" }, "Fix the marked setting to save")
            : preview
              ? h(
                  "button",
                  {
                    type: "button",
                    className: "petasos-changecount",
                    "aria-expanded": reviewing,
                    "aria-controls": "petasos-change-sheet",
                    onClick: function () {
                      reviewState[1](!reviewing);
                    },
                  },
                  plural(staged, "unsaved change"),
                  h(Icon, { name: "chevron", size: 14, className: "petasos-changecount-chevron" })
                )
              : h("span", { className: "petasos-secondary", role: "status" }, "Checking…"),
        empty ? null : h(Btn, { outlined: true, onClick: discard, "aria-label": "Discard all " + plural(staged, "unsaved change") }, "Discard all"),
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
            disabled: empty || invalid || !preview || lockedAll || savingState[0],
            onClick: save,
          },
          savingState[0] ? "Saving…" : "Save"
        )
      )
    );
    var sheet =
      reviewing && preview && !invalid && !empty
        ? h(ChangeSheet, {
            catalog: catalog,
            preview: preview,
            draft: draft,
            onClose: function () {
              reviewState[1](false);
            },
          })
        : null;

    var saved = savedState[0];

    return h(
      "div",
      { className: "petasos-stack petasos-settings" },
      toolbar,
      sheet,
      saved
        ? h(
            "div",
            { className: "petasos-saved" },
            h(
              Notice,
              {
                tone: "success",
                title: "Saved at " + clockTime(saved.at),
                action: h(Btn, { ghost: true, onClick: function () { savedState[1](null); } }, "Dismiss"),
              },
              h("p", null, saved.message)
            )
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
                  if (item.key === "changed") go("settings", { changed: "1" });
                  else if (params.changed) go("settings");
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
                  title: search ? "Matching settings" : changedView ? "Changed from default" : sectionLabel(activeTop),
                  description: search
                    ? plural(shown.length, "setting") + " match."
                    : changedView
                      ? "Every setting whose value is not its default, whoever changed it."
                      : (sections[activeTop] || {}).help || "Settings that apply everywhere.",
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
                  : changedView
                    ? h(Empty, { title: "Every setting is at its default", icon: "check" })
                    : h(Empty, { title: "No settings match", icon: "search" }, "Clear the search, or show rarely needed settings."),
                !search && hidden[activeTop]
                  ? h(
                      "p",
                      { className: "petasos-help petasos-end" },
                      plural(hidden[activeTop], "rarely needed setting") + " hidden. ",
                      h(Btn, { ghost: true, compact: true, onClick: function () { expertState[1](true); } }, "Show them")
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
                "). This saves now. " +
                (resetRow.restart
                  ? "An agent started from now on uses this. An agent already running keeps the previous value until it restarts."
                  : "It applies from the agent's next tool call.")
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
  // ===== dashboard-src/90-app.js =====
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
          Object.assign({ key: (route.params.example || "") + "|" + (route.params.settings || "") + "|" + (route.params.rule || ""), onStage: stage }, shared)
        );
      else if (view === "settings")
        body = h(
          Settings,
          Object.assign(
            { key: (route.params.rule || "") + "|" + (route.params.review || "") + "|" + (route.params.changed || ""), draft: draft, setDraft: draftState[1] },
            shared
          )
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

    var paused = Boolean(status && (status.paused || (status.switches && status.switches.petasos && status.switches.petasos.on === false)));
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
          paused ? h(Status, { tone: "warning", state: "paused" }, "Paused") : null,
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
            "Actions run unchecked. Each one is recorded."
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
          "Until you resume, the agent's actions run unchecked. Each one is still recorded in Activity. Applies from the agent's next action.",
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
