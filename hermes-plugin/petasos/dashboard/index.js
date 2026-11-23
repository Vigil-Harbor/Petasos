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
  // See docs/architecture/rationale.md, "Dashboard source packaging".

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

  function ApiFailure(status, code, message, path) {
    this.status = status;
    this.code = code;
    this.message = message;
    this.path = path || null;
  }

  // Hosts report status/body properties or a status-prefixed response body.
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
    }
    if (status === 0) {
      return new ApiFailure(0, "unreachable", "The dashboard could not reach Petasos.", null);
    }
    return new ApiFailure(status, "http", "Petasos answered with an error (" + status + ").", null);
  }

  // A request that gets no answer must not hold a control forever.
  var READ_TIMEOUT_MS = 20000;
  var WRITE_TIMEOUT_MS = 30000;

  function call(path, options) {
    var method = (options && options.method) || "GET";
    var init = { method: method };
    if (options && options.body !== undefined) {
      init.body = JSON.stringify(options.body);
      init.headers = { "Content-Type": "application/json" };
    }
    var controller = typeof AbortController === "function" ? new AbortController() : null;
    if (controller) init.signal = controller.signal;
    var limit = (options && options.timeout) || (method === "GET" ? READ_TIMEOUT_MS : WRITE_TIMEOUT_MS);
    var timer;
    // The timer settles the promise itself: an aborted body read may never reject.
    var waited = new Promise(function (_resolve, reject) {
      timer = window.setTimeout(function () {
        reject(new ApiFailure(0, "timeout", "Petasos did not answer in " + Math.round(limit / 1000) + " seconds.", null));
        if (controller) controller.abort();
      }, limit);
    });
    var asked = SDK.fetchJSON(API + path, init).catch(function (err) {
      throw parseFailure(err);
    });
    return Promise.race([asked, waited]).finally(function () {
      window.clearTimeout(timer);
    });
  }

  // True when a write's failure does not say whether the write happened.
  function unknownOutcome(failure) {
    if (!failure) return false;
    if (failure.code === "timeout" || failure.code === "unreachable") return true;
    return failure.status >= 500 || failure.status === 0;
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


  var VIEWS = ["overview", "activity", "tryit", "settings"];

  // Hermes profile navigation drops fragments; restore the initial fragment once.
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

  // The API has no event stream; only visible tabs poll.
  // A tick is skipped while the read before it is still unanswered, so a slow
  // read is never replaced by its own repeat. `load` may return a promise.
  function usePoll(load, ms, deps) {
    useEffect(function () {
      var stopped = false;
      var busy = false;
      function run() {
        var pending = load();
        if (!pending || typeof pending.then !== "function") return;
        busy = true;
        var done = function () {
          busy = false;
        };
        pending.then(done, done);
      }
      function tick() {
        if (!stopped && !busy && document.visibilityState !== "hidden") run();
      }
      run();
      var timer = window.setInterval(tick, ms);
      document.addEventListener("visibilitychange", tick);
      return function () {
        stopped = true;
        window.clearInterval(timer);
        document.removeEventListener("visibilitychange", tick);
      };
    }, deps);
  }


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

  function originText(origin, stored, catalog) {
    if (origin === "role") return "From the job (" + roleLabel(catalog, stored && stored.role) + ")";
    if (origin === "level") return "From strictness (" + levelLabel(catalog, stored && stored.level) + ")";
    if (origin === "override") return "Your setting";
    if (origin === "default") return "Default";
    return "Unknown";
  }

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


  function whenText(seconds) {
    if (typeof seconds !== "number") return "";
    // Hermes timeAgo accepts Unix seconds despite its milliseconds type annotation.
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
      props.bare ? null : h(C.CardContent, { className: cn("petasos-panel-body", props.bodyClassName) }, props.children)
    );
  }

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

  function Tag(props) {
    return h(C.Badge, { tone: props.tone || "secondary", className: cn("petasos-tag", props.className), title: props.title }, props.children);
  }

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

  function Btn(props) {
    var rest = Object.assign({}, props);
    delete rest.children;
    delete rest.compact;
    rest.type = rest.type || "button";
    rest.size = rest.size || "sm";
    rest.className = cn(!props.ghost && "petasos-btn-caps", props.compact && "petasos-btn-compact", props.className);
    return h(C.Button, rest, props.children);
  }

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
      // Storage may be refused; disclosure state must still work for this visit.
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

  // Hermes's dialogs do not hand focus back. Remember what opened one, and when it
  // closes put focus there, or on `fallback` when that control is gone.
  function useReturnFocus(open, fallback) {
    var opener = useRef(null);
    var was = useRef(false);
    useEffect(
      function () {
        if (open) {
          was.current = true;
          return;
        }
        if (!was.current) return;
        was.current = false;
        var target = opener.current;
        opener.current = null;
        if (!target || !document.contains(target) || target.disabled) {
          var id = typeof fallback === "function" ? fallback() : fallback;
          target = id ? document.getElementById(id) : null;
        }
        if (target) target.focus({ preventScroll: true });
      },
      [open]
    );
    return function remember() {
      opener.current = document.activeElement;
    };
  }

  // Scrolling the inner container keeps the Hermes page frame stationary.
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

  var STYLE = "/* See docs/architecture/rationale.md, \"Dashboard visual constraints\". */\n\n.petasos {\n  --petasos-ink: var(--midground);\n  --petasos-secondary: var(\n    --color-text-secondary,\n    color-mix(in srgb, var(--midground-base, var(--midground)) 80%, transparent)\n  );\n  --petasos-tertiary: var(\n    --text-tertiary,\n    color-mix(in srgb, var(--midground-base, var(--midground)) 65%, transparent)\n  );\n  --petasos-line: color-mix(in srgb, var(--midground-base, var(--midground)) 15%, transparent);\n  --petasos-control-line: color-mix(in srgb, var(--midground-base, var(--midground)) 30%, transparent);\n  display: flex;\n  flex-direction: column;\n  gap: 1rem;\n  width: 100%;\n  min-width: 0;\n  color: var(--petasos-ink);\n  font-size: 0.9375rem;\n  line-height: 1.5;\n}\n\n.petasos code,\n.petasos pre {\n  background: transparent !important;\n  color: inherit;\n}\n\n.petasos p {\n  margin: 0;\n}\n\n.petasos .sr-only {\n  position: absolute;\n  width: 1px;\n  height: 1px;\n  padding: 0;\n  margin: -1px;\n  overflow: hidden;\n  clip: rect(0, 0, 0, 0);\n  white-space: nowrap;\n  border: 0;\n}\n\n/* Keyboard focus must remain visible in every theme. */\n.petasos button:focus-visible,\n.petasos a:focus-visible,\n.petasos input:focus-visible,\n.petasos textarea:focus-visible,\n.petasos summary:focus-visible,\n.petasos [tabindex]:focus-visible {\n  outline: 2px solid var(--midground);\n  outline-offset: 2px;\n}\n\n.petasos-detail:focus,\n.petasos-subhead:focus {\n  outline: none;\n}\n\n\n.petasos input,\n.petasos textarea,\n.petasos [aria-haspopup=\"listbox\"] {\n  color: var(--petasos-ink);\n  border-color: var(--petasos-control-line);\n  font-family: var(--theme-font-mono);\n}\n\n.petasos input::placeholder,\n.petasos textarea::placeholder {\n  color: var(--petasos-tertiary);\n}\n\n.petasos [aria-haspopup=\"listbox\"] svg {\n  opacity: 1;\n  color: var(--petasos-ink);\n}\n\n.petasos input:disabled,\n.petasos textarea:disabled,\n.petasos [aria-haspopup=\"listbox\"]:disabled {\n  color: var(--petasos-tertiary);\n}\n\n.petasos-stack {\n  display: flex;\n  flex-direction: column;\n  gap: 1rem;\n  min-width: 0;\n}\n\n.petasos-grid-2 {\n  display: grid;\n  grid-template-columns: repeat(2, minmax(0, 1fr));\n  gap: 1rem;\n  align-items: start;\n}\n\n.petasos-grid-3 {\n  display: grid;\n  grid-template-columns: repeat(3, minmax(0, 1fr));\n  gap: 1rem;\n  align-items: start;\n}\n\n.petasos-help,\n.petasos-secondary {\n  font-size: 0.875rem;\n  line-height: 1.5;\n  color: var(--petasos-secondary);\n}\n\n.petasos-tertiary,\n.petasos-faint {\n  font-size: 0.8125rem;\n  color: var(--petasos-tertiary);\n}\n\n.petasos-dot {\n  color: var(--petasos-tertiary);\n}\n\n.petasos .petasos-faint {\n  color: var(--petasos-tertiary);\n}\n\n\n.petasos .petasos-btn-caps {\n  text-transform: uppercase;\n}\n\n\n.petasos .petasos-btn-compact {\n  height: auto;\n  min-height: 0;\n  padding: 0.1rem 0.35rem;\n  vertical-align: baseline;\n}\n\n.petasos-strong,\n.petasos strong {\n  font-weight: 700;\n}\n\n.petasos-block {\n  display: block;\n}\n\n.petasos-gap-above {\n  margin-top: 0.4rem;\n}\n\n.petasos-end {\n  padding: 0.9rem 0 0.4rem;\n  text-align: center;\n}\n\n/* Underlining denotes navigation; state-changing actions use buttons. */\n.petasos-link,\n.petasos a.petasos-link {\n  background: none;\n  border: 0;\n  padding: 0;\n  font: inherit;\n  font-size: inherit;\n  color: inherit;\n  text-decoration: underline;\n  text-decoration-thickness: 1px;\n  text-underline-offset: 3px;\n  cursor: pointer;\n  text-align: left;\n}\n\n.petasos-link:hover {\n  text-decoration-thickness: 2px;\n}\n\n.petasos-link:disabled {\n  cursor: not-allowed;\n  opacity: 0.6;\n}\n\n.petasos-row-actions {\n  display: flex;\n  flex-wrap: wrap;\n  align-items: center;\n  gap: 0.6rem 0.9rem;\n}\n\n.petasos-check-note {\n  flex: 1 1 16rem;\n  margin: 0;\n}\n\n.petasos-count {\n  font-size: 0.875rem;\n  font-weight: 600;\n  color: var(--petasos-ink);\n}\n\n.petasos-mono {\n  font-family: var(--theme-font-mono);\n  font-size: 0.85rem;\n}\n\n/* Technical ids wrap only at explicit separator break opportunities. */\n.petasos-ident {\n  overflow-wrap: normal;\n  word-break: normal;\n  white-space: normal;\n  font-size: 0.82rem;\n}\n\n.petasos-idrow {\n  display: inline-flex;\n  flex-wrap: wrap;\n  align-items: baseline;\n  gap: 0.25rem 0.6rem;\n}\n\n.petasos-copy {\n  display: inline-flex;\n  align-items: center;\n  gap: 0.25rem;\n  padding: 0.1rem 0.35rem;\n  border: 1px solid transparent;\n  background: none;\n  color: var(--petasos-secondary);\n  font-size: 0.8rem;\n  cursor: pointer;\n}\n\n.petasos-copy:hover {\n  border-color: var(--petasos-line);\n  color: var(--petasos-ink);\n}\n\n.petasos-icon {\n  display: inline-block;\n  flex-shrink: 0;\n  vertical-align: middle;\n}\n\n\n\n.petasos-disclosure {\n  display: flex;\n  flex-direction: column;\n  align-items: flex-start;\n  gap: 0.6rem;\n  min-width: 0;\n  width: 100%;\n}\n\n.petasos-disclosure-toggle {\n  display: inline-flex;\n  align-items: center;\n  gap: 0.3rem;\n  padding: 0;\n  border: 0;\n  background: none;\n  color: var(--petasos-secondary);\n  font: inherit;\n  font-size: 0.875rem;\n  font-weight: 500;\n  cursor: pointer;\n}\n\n.petasos-disclosure-toggle:hover {\n  color: var(--petasos-ink);\n}\n\n.petasos-disclosure-chevron {\n  transition: transform 120ms;\n}\n\n.petasos-disclosure-open > .petasos-disclosure-toggle .petasos-disclosure-chevron,\n.petasos-chevron-open {\n  transform: rotate(90deg);\n}\n\n.petasos-disclosure-body {\n  display: flex;\n  flex-direction: column;\n  gap: 0.6rem;\n  width: 100%;\n  min-width: 0;\n  padding-left: 1.1rem;\n}\n\n\n.petasos-command {\n  display: flex;\n  align-items: center;\n  justify-content: space-between;\n  gap: 0.75rem;\n  max-width: 40rem;\n  padding: 0.45rem 0.6rem 0.45rem 0.8rem;\n  border: 1px solid var(--petasos-control-line);\n  background: color-mix(in srgb, var(--background) 40%, transparent);\n}\n\n.petasos-command-text {\n  font-family: var(--theme-font-mono);\n  font-size: 0.875rem;\n  overflow-wrap: anywhere;\n}\n\n\n\n.petasos-topbar {\n  display: flex;\n  align-items: center;\n  justify-content: space-between;\n  gap: 1rem;\n  flex-wrap: wrap;\n}\n\n.petasos-topbar-main {\n  display: flex;\n  align-items: center;\n  gap: 0.75rem;\n  flex-wrap: wrap;\n}\n\n.petasos-topbar-side {\n  display: flex;\n  align-items: center;\n  gap: 0.75rem;\n}\n\n.petasos-topbar-side .petasos-help {\n  color: var(--petasos-tertiary);\n}\n\n.petasos-unsaved {\n  background: none;\n  border: 0;\n  padding: 0;\n  font-size: 0.875rem;\n  color: inherit;\n  text-decoration: underline;\n  text-underline-offset: 3px;\n  cursor: pointer;\n}\n\n\n.petasos-segmented {\n  display: inline-flex;\n  flex-wrap: wrap;\n  border: 1px solid var(--petasos-line);\n  background: color-mix(in srgb, var(--background) 30%, transparent);\n  max-width: 100%;\n}\n\n.petasos-segment {\n  display: inline-flex;\n  align-items: center;\n  gap: 0.35rem;\n  height: 1.875rem;\n  padding: 0 0.75rem;\n  border: 0;\n  border-right: 1px solid var(--petasos-line);\n  background: transparent;\n  color: var(--petasos-secondary);\n  font-family: var(--font-mondwest);\n  font-size: 0.875rem;\n  font-weight: 400;\n  letter-spacing: 0.03em;\n  white-space: nowrap;\n  cursor: pointer;\n  transition: background-color 120ms, color 120ms;\n}\n\n.petasos-segment:last-child {\n  border-right: 0;\n}\n\n.petasos-segment:hover {\n  background: color-mix(in srgb, var(--midground) 10%, transparent);\n  color: var(--midground);\n}\n\n.petasos-segment-on,\n.petasos-segment-on:hover {\n  background: var(--midground);\n  color: var(--background);\n}\n\n.petasos-segment:disabled {\n  cursor: not-allowed;\n  opacity: 0.55;\n}\n\n.petasos-viewtabs .petasos-segment {\n  height: 1.875rem;\n  padding: 0 0.85rem;\n}\n\n\n\n.petasos-switch {\n  position: relative;\n  display: inline-flex;\n  align-items: center;\n  flex-shrink: 0;\n  width: 2.25rem;\n  height: 1.25rem;\n  padding: 0;\n  border: 1px solid color-mix(in srgb, var(--midground) 22%, transparent);\n  background: var(--background);\n  cursor: pointer;\n  transition: background-color 120ms, border-color 120ms;\n}\n\n.petasos-switch-thumb {\n  display: block;\n  width: 0.875rem;\n  height: 0.875rem;\n  margin-left: 0.125rem;\n  background: color-mix(in srgb, var(--midground) 40%, transparent);\n  transition: transform 120ms;\n}\n\n.petasos-switch-on {\n  background: color-mix(in srgb, var(--midground) 15%, transparent);\n  border-color: color-mix(in srgb, var(--midground) 35%, transparent);\n}\n\n.petasos-switch-on .petasos-switch-thumb {\n  transform: translateX(1rem);\n  background: var(--midground);\n}\n\n.petasos-switch:disabled {\n  cursor: not-allowed;\n  opacity: 0.5;\n}\n\n.petasos-inline-switch {\n  display: inline-flex;\n  align-items: center;\n  gap: 0.6rem;\n  font-size: 0.875rem;\n}\n\n\n\n.petasos-panel {\n  min-width: 0;\n}\n\n.petasos-panel-head {\n  padding: 0.85rem 1.1rem 0.6rem;\n}\n\n.petasos-panel-headrow {\n  display: flex;\n  align-items: flex-start;\n  justify-content: space-between;\n  gap: 1rem;\n}\n\n.petasos-panel-titles {\n  display: flex;\n  flex-direction: column;\n  gap: 0.25rem;\n  min-width: 0;\n}\n\n\n.petasos-panel-titlerow {\n  display: flex;\n  flex-wrap: wrap;\n  align-items: center;\n  gap: 0.6rem;\n}\n\n.petasos-panel-desc {\n  font-size: 0.875rem;\n  color: var(--petasos-secondary);\n}\n\n.petasos-panel-actions {\n  display: flex;\n  align-items: center;\n  gap: 0.75rem;\n  flex-shrink: 0;\n}\n\n.petasos-panel-body {\n  display: flex;\n  flex-direction: column;\n  gap: 0.85rem;\n  padding: 0.9rem 1.1rem 1.1rem;\n}\n\n\n.petasos-label,\n.petasos-filter-label,\n.petasos-sections-title {\n  font-family: var(--font-mondwest);\n  font-size: 0.78rem;\n  font-weight: 400;\n  letter-spacing: 0.08em;\n  line-height: 1.3;\n  text-transform: uppercase;\n  color: var(--petasos-secondary);\n}\n\n.petasos-subhead {\n  margin: 0.3rem 0 0;\n  font-family: var(--font-mondwest);\n  font-size: 0.8rem;\n  font-weight: 400;\n  letter-spacing: 0.08em;\n  text-transform: uppercase;\n  color: var(--petasos-secondary);\n}\n\n\n\n\n.petasos .petasos-status {\n  font-family: var(--theme-font-sans);\n  font-size: 0.875rem;\n  font-weight: 500;\n  letter-spacing: 0.01em;\n  text-transform: none;\n  padding: 0.22rem 0.55rem;\n  line-height: 1.2;\n  white-space: nowrap;\n  vertical-align: middle;\n}\n\n.petasos .petasos-status-large {\n  font-size: 0.9375rem;\n  padding: 0.28rem 0.65rem;\n}\n\n.petasos .petasos-status-success {\n  color: color-mix(in srgb, var(--color-success) 70%, white);\n}\n\n.petasos .petasos-status-warning {\n  color: color-mix(in srgb, var(--color-warning) 75%, white);\n}\n\n.petasos .petasos-status-destructive {\n  color: color-mix(in srgb, var(--color-destructive) 55%, white);\n  border-color: color-mix(in srgb, var(--color-destructive) 55%, transparent);\n}\n\n.petasos-light .petasos-status-success {\n  color: color-mix(in srgb, var(--color-success) 45%, black);\n  border-color: color-mix(in srgb, var(--color-success) 60%, black);\n}\n\n.petasos-light .petasos-status-warning {\n  color: color-mix(in srgb, var(--color-warning) 45%, black);\n  border-color: color-mix(in srgb, var(--color-warning) 60%, black);\n}\n\n.petasos-light .petasos-status-destructive {\n  color: color-mix(in srgb, var(--color-destructive) 70%, black);\n  border-color: color-mix(in srgb, var(--color-destructive) 70%, black);\n}\n\n.petasos-light .petasos-status-neutral {\n  color: var(--midground);\n}\n\n.petasos-tag {\n  white-space: nowrap;\n}\n\n.petasos .petasos-tag {\n  font-size: 0.85rem;\n}\n\n.petasos-none {\n  color: var(--petasos-tertiary);\n}\n\n\n.petasos-sev {\n  font-size: 0.875rem;\n  color: var(--petasos-secondary);\n  white-space: nowrap;\n}\n\n.petasos-sev-high {\n  color: var(--petasos-ink);\n  font-weight: 500;\n}\n\n.petasos-sev-critical {\n  color: var(--petasos-ink);\n  font-weight: 700;\n}\n\n\n\n.petasos-notice {\n  display: flex;\n  align-items: flex-start;\n  justify-content: space-between;\n  gap: 1rem;\n  padding: 0.8rem 1rem;\n  border: 1px solid var(--color-border);\n  background: var(--color-card);\n}\n\n.petasos-notice-strong {\n  border-left: 3px solid var(--color-destructive);\n}\n\n.petasos-notice-text {\n  display: flex;\n  flex-direction: column;\n  gap: 0.3rem;\n  min-width: 0;\n}\n\n.petasos-notice-title {\n  display: flex;\n  align-items: center;\n  gap: 0.5rem;\n  font-weight: 700;\n  font-size: 0.9375rem;\n}\n\n.petasos-notice-dot {\n  width: 0.5rem;\n  height: 0.5rem;\n  border-radius: 50%;\n  flex-shrink: 0;\n  background: var(--midground);\n}\n\n.petasos-notice-warning .petasos-notice-dot {\n  background: var(--color-warning);\n}\n\n.petasos-notice-destructive .petasos-notice-dot {\n  background: var(--color-destructive);\n}\n\n.petasos-notice-check {\n  color: var(--color-success);\n}\n\n.petasos-light .petasos-notice-check {\n  color: color-mix(in srgb, var(--color-success) 50%, black);\n}\n\n.petasos-notice-success {\n  border-color: color-mix(in srgb, var(--color-success) 45%, transparent);\n}\n\n.petasos-notice-body {\n  font-size: 0.875rem;\n  line-height: 1.55;\n  padding-left: 1.1rem;\n  color: var(--petasos-secondary);\n}\n\n.petasos-notice-body p + p {\n  margin-top: 0.3rem;\n}\n\n.petasos-notice-action {\n  flex-shrink: 0;\n}\n\n.petasos-steps {\n  margin: 0.4rem 0 0;\n  padding-left: 1.2rem;\n  display: flex;\n  flex-direction: column;\n  gap: 0.25rem;\n}\n\n\n.petasos-saved {\n  display: flex;\n  flex-direction: column;\n  gap: 0.4rem;\n}\n\n.petasos-restart-note {\n  padding: 0 0 0 1.1rem;\n  font-size: 0.875rem;\n  color: var(--petasos-secondary);\n}\n\n\n\n.petasos-empty {\n  display: flex;\n  flex-direction: column;\n  align-items: center;\n  gap: 0.3rem;\n  padding: 3rem 1rem;\n  text-align: center;\n}\n\n.petasos-empty-icon {\n  width: 1.75rem;\n  height: 1.75rem;\n  margin-bottom: 0.35rem;\n  color: var(--petasos-tertiary);\n}\n\n.petasos-empty-title {\n  font-size: 0.9375rem;\n  font-weight: 400;\n  color: var(--petasos-secondary);\n}\n\n.petasos-empty-body {\n  max-width: 30rem;\n  font-size: 0.875rem;\n  color: var(--petasos-secondary);\n}\n\n.petasos-empty-action {\n  margin-top: 0.6rem;\n}\n\n\n\n.petasos-kv {\n  display: grid;\n  grid-template-columns: minmax(7rem, max-content) minmax(0, 1fr);\n  gap: 0.45rem 1.25rem;\n  margin: 0;\n  font-size: 0.9rem;\n}\n\n.petasos-kv dt {\n  font-family: var(--font-mondwest);\n  font-size: 0.8rem;\n  font-weight: 400;\n  letter-spacing: 0.08em;\n  text-transform: uppercase;\n  color: var(--petasos-secondary);\n  padding-top: 0.12rem;\n}\n\n.petasos-kv dd {\n  margin: 0;\n  min-width: 0;\n}\n\n.petasos-kv-stacked {\n  grid-template-columns: minmax(0, 1fr);\n  gap: 0.15rem;\n}\n\n.petasos-kv-stacked dd {\n  margin-bottom: 0.6rem;\n}\n\n\n\n\n.petasos-verdict-title {\n  margin: 0;\n  font-size: 1rem;\n  font-weight: 600;\n  line-height: 1.4;\n}\n\n.petasos-verdict-reason {\n  max-width: 56rem;\n  font-size: 0.9375rem;\n  color: var(--petasos-secondary);\n}\n\n.petasos-coverage {\n  margin-top: 0.15rem;\n}\n\n.petasos-fixbox {\n  display: flex;\n  flex-direction: column;\n  gap: 0.5rem;\n  padding: 0.75rem 0.9rem;\n  border: 1px solid var(--petasos-line);\n  background: color-mix(in srgb, var(--midground) 4%, transparent);\n  font-size: 0.9rem;\n}\n\n.petasos-setup-grid {\n  display: grid;\n  grid-template-columns: repeat(2, minmax(0, 1fr));\n  gap: 1rem 2rem;\n  align-items: start;\n}\n\n.petasos-choose {\n  display: flex;\n  flex-direction: column;\n  align-items: flex-start;\n  gap: 0.45rem;\n  min-width: 0;\n}\n\n.petasos-choose-desc {\n  font-size: 0.9rem;\n  max-width: 34rem;\n}\n\n.petasos-optlist {\n  list-style: none;\n  margin: 0;\n  padding: 0;\n  display: flex;\n  flex-direction: column;\n  gap: 0.35rem;\n}\n\n.petasos-opt {\n  display: grid;\n  grid-template-columns: 8.5rem minmax(0, 1fr);\n  gap: 0.75rem;\n  font-size: 0.875rem;\n  line-height: 1.45;\n  color: var(--petasos-secondary);\n}\n\n.petasos-opt-name {\n  font-weight: 600;\n}\n\n.petasos-opt-on {\n  color: var(--petasos-ink);\n}\n\n.petasos-opt-on .petasos-opt-name {\n  font-weight: 700;\n}\n\n.petasos-opt-note {\n  color: var(--petasos-tertiary);\n}\n\n\n.petasos-preview {\n  display: flex;\n  flex-direction: column;\n  gap: 0.6rem;\n  padding: 0.9rem 1rem 1rem;\n  border: 1px solid var(--petasos-control-line);\n  background: color-mix(in srgb, var(--midground) 7%, var(--color-card));\n}\n\n.petasos-preview-title {\n  margin: 0;\n  font-size: 1rem;\n  font-weight: 700;\n}\n\n.petasos-preview-text {\n  font-size: 0.9rem;\n  max-width: 56rem;\n}\n\n.petasos-when {\n  font-size: 0.9rem;\n  font-weight: 600;\n}\n\n\n.petasos-changes {\n  list-style: none;\n  margin: 0;\n  padding: 0;\n  width: 100%;\n}\n\n.petasos-change {\n  display: flex;\n  flex-direction: column;\n  gap: 0.2rem;\n  padding: 0.6rem 0;\n  border-bottom: 1px solid var(--color-border);\n}\n\n.petasos-change:first-child {\n  border-top: 1px solid var(--color-border);\n}\n\n.petasos-change-name {\n  font-weight: 700;\n  font-size: 0.9rem;\n}\n\n.petasos-change .petasos-help {\n  font-size: 0.85rem;\n}\n\n.petasos-change-values {\n  font-size: 0.9rem;\n}\n\n.petasos-before {\n  text-decoration: line-through;\n  color: var(--petasos-secondary);\n}\n\n.petasos-arrow {\n  color: var(--petasos-tertiary);\n}\n\n.petasos-diff {\n  list-style: none;\n  margin: 0;\n  padding: 0;\n  display: flex;\n  flex-direction: column;\n  gap: 0.15rem;\n  font-size: 0.875rem;\n}\n\n.petasos-diff-sign {\n  display: inline-block;\n  width: 1rem;\n  font-weight: 700;\n}\n\n\n.petasos-provenance {\n  display: flex;\n  flex-wrap: wrap;\n  align-items: center;\n  column-gap: 0.3rem;\n  font-size: 0.8125rem;\n  color: var(--petasos-secondary);\n}\n\n.petasos .petasos-provenance .petasos-btn-compact {\n  font-size: 0.75rem;\n}\n\n.petasos-key {\n  font-family: var(--theme-font-mono);\n  font-size: 0.78rem;\n}\n\n\n\n/* See docs/architecture/rationale.md, \"Dashboard visual constraints\". */\n.petasos-figures {\n  display: flex;\n  flex-wrap: wrap;\n  gap: 0.5rem;\n  margin: 0;\n  padding: 0;\n  list-style: none;\n}\n\n.petasos-figure {\n  display: inline-flex;\n  align-items: baseline;\n  gap: 0.5rem;\n  padding: 0.35rem 0.7rem;\n  border: 1px solid var(--petasos-control-line);\n  background: none;\n  color: inherit;\n  font: inherit;\n  cursor: pointer;\n}\n\n.petasos-figure:hover:not(:disabled) {\n  border-color: var(--petasos-ink);\n}\n\n.petasos-figure-n {\n  font-size: 1.125rem;\n  font-weight: 600;\n  line-height: 1.2;\n  font-variant-numeric: tabular-nums;\n}\n\n.petasos-figure-label {\n  font-size: 0.875rem;\n  color: var(--petasos-secondary);\n}\n\n.petasos-figure-zero {\n  border-color: var(--petasos-line);\n  cursor: default;\n}\n\n.petasos-figure-zero .petasos-figure-n,\n.petasos-figure-zero .petasos-figure-label {\n  font-weight: 400;\n  color: var(--petasos-tertiary);\n}\n\n.petasos-statechip {\n  display: inline-flex;\n  align-items: center;\n  gap: 0.5rem;\n  padding: 0;\n  border: 0;\n  background: none;\n  color: var(--petasos-secondary);\n  font: inherit;\n  font-size: 0.875rem;\n  cursor: pointer;\n}\n\n.petasos-steps-list {\n  display: flex;\n  flex-direction: column;\n  margin: 0;\n  padding: 0;\n  list-style: none;\n}\n\n.petasos-step {\n  display: grid;\n  grid-template-columns: 1.75rem minmax(0, 1fr) auto;\n  gap: 0.25rem 0.9rem;\n  align-items: center;\n  padding: 0.8rem 0;\n  border-top: 1px solid var(--petasos-line);\n}\n\n.petasos-step:first-child {\n  padding-top: 0;\n  border-top: 0;\n}\n\n.petasos-step:last-child {\n  padding-bottom: 0;\n}\n\n.petasos-step-mark {\n  display: inline-flex;\n  align-items: center;\n  justify-content: center;\n  width: 1.75rem;\n  height: 1.75rem;\n  border: 1px solid var(--petasos-control-line);\n  font-family: var(--theme-font-mono);\n  font-size: 0.8rem;\n  font-variant-numeric: tabular-nums;\n}\n\n.petasos-step-done .petasos-step-mark {\n  border-color: var(--color-success);\n  color: var(--color-success);\n}\n\n.petasos-step-title {\n  font-weight: 600;\n}\n\n.petasos-step-text {\n  min-width: 0;\n  max-width: 44rem;\n}\n\n.petasos-step-action {\n  display: flex;\n  flex-wrap: wrap;\n  gap: 0.5rem;\n  justify-content: flex-end;\n}\n\n@media (max-width: 700px) {\n  .petasos-step {\n    grid-template-columns: 1.75rem minmax(0, 1fr);\n  }\n\n  .petasos-step-action {\n    grid-column: 2;\n    justify-content: flex-start;\n  }\n}\n\n\n.petasos-alarm-row {\n  display: flex;\n  align-items: center;\n  justify-content: space-between;\n  flex-wrap: wrap;\n  gap: 0.6rem 1rem;\n  padding: 0.65rem 0 0.1rem;\n  border-top: 1px solid var(--color-border);\n  font-size: 0.9rem;\n}\n\n.petasos-mini-list {\n  list-style: none;\n  margin: 0;\n  padding: 0;\n  border-top: 1px solid var(--color-border);\n}\n\n.petasos-mini-row {\n  display: grid;\n  grid-template-columns: 5rem minmax(0, 1fr) auto 1rem;\n  align-items: center;\n  gap: 0.9rem;\n  width: 100%;\n  padding: 0.55rem 0.15rem;\n  border: 0;\n  border-bottom: 1px solid var(--color-border);\n  background: none;\n  color: inherit;\n  font: inherit;\n  font-size: 0.9rem;\n  text-align: left;\n  cursor: pointer;\n}\n\n.petasos-mini-row:hover {\n  background: color-mix(in srgb, var(--midground) 6%, transparent);\n}\n\n.petasos-mini-when {\n  font-size: 0.8125rem;\n  color: var(--petasos-secondary);\n}\n\n/* Safety disclosures must wrap without clipping. */\n.petasos-mini-text {\n  min-width: 0;\n  overflow-wrap: anywhere;\n}\n\n.petasos-repeat {\n  font-size: 0.8125rem;\n  font-weight: 700;\n}\n\n.petasos-chevron {\n  color: var(--petasos-tertiary);\n}\n\n\n\n.petasos-scanners {\n  list-style: none;\n  margin: 0;\n  padding: 0;\n  display: flex;\n  flex-direction: column;\n}\n\n.petasos-scanner {\n  display: flex;\n  flex-direction: column;\n  align-items: flex-start;\n  gap: 0.35rem;\n  padding: 0.7rem 0;\n  border-bottom: 1px solid var(--color-border);\n  font-size: 0.9rem;\n}\n\n.petasos-scanner:first-child {\n  padding-top: 0;\n}\n\n.petasos-scanner:last-child {\n  border-bottom: 0;\n  padding-bottom: 0;\n}\n\n.petasos-scanner-head {\n  display: flex;\n  align-items: center;\n  gap: 0.6rem;\n  width: 100%;\n}\n\n.petasos-scanner-name {\n  display: flex;\n  flex-direction: column;\n  gap: 0.1rem;\n  font-weight: 600;\n  margin-right: auto;\n}\n\n.petasos-scanner-product {\n  font-weight: 400;\n  font-size: 0.8125rem;\n  color: var(--petasos-secondary);\n}\n\n\n\n.petasos-filters {\n  display: flex;\n  flex-direction: column;\n  gap: 0.75rem;\n}\n\n.petasos-filter-row {\n  display: flex;\n  flex-wrap: wrap;\n  align-items: flex-end;\n  gap: 0.75rem 1.25rem;\n}\n\n.petasos-filter-row > .petasos-filter-group,\n.petasos-filter-row > .petasos-search {\n  align-self: center;\n}\n\n.petasos-filter-group {\n  display: flex;\n  align-items: center;\n  gap: 0.6rem;\n}\n\n.petasos-filter-label {\n  color: var(--petasos-secondary);\n}\n\n.petasos-search {\n  position: relative;\n  flex: 1 1 18rem;\n  max-width: 28rem;\n}\n\n.petasos-search input {\n  padding-left: 2rem;\n}\n\n.petasos-search-icon {\n  position: absolute;\n  left: 0.6rem;\n  top: 50%;\n  transform: translateY(-50%);\n  color: var(--petasos-tertiary);\n  pointer-events: none;\n}\n\n.petasos-range-row {\n  align-items: flex-start;\n}\n\n.petasos-tz {\n  align-self: center;\n}\n\n.petasos-datetime {\n  width: 15rem;\n}\n\n.petasos-datetime-box {\n  position: relative;\n}\n\n.petasos-datetime-box input {\n  padding-right: 2.2rem;\n}\n\n.petasos-datetime-pick {\n  position: absolute;\n  right: 0.25rem;\n  top: 50%;\n  transform: translateY(-50%);\n  display: inline-flex;\n  align-items: center;\n  justify-content: center;\n  width: 1.75rem;\n  height: 1.75rem;\n  border: 0;\n  background: none;\n  color: var(--petasos-ink);\n  cursor: pointer;\n}\n\n.petasos-datetime-pick:hover {\n  background: color-mix(in srgb, var(--midground) 10%, transparent);\n}\n\n\n.petasos-datetime-native {\n  position: absolute;\n  right: 0;\n  bottom: 0;\n  width: 1px;\n  height: 1px;\n  opacity: 0;\n  pointer-events: none;\n  border: 0;\n  padding: 0;\n  color-scheme: dark;\n}\n\n.petasos-light .petasos-datetime-native {\n  color-scheme: light;\n}\n\n.petasos-filter-selects {\n  display: grid;\n  grid-template-columns: repeat(5, minmax(0, 1fr));\n  gap: 0.75rem;\n}\n\n.petasos-choice {\n  display: flex;\n  flex-direction: column;\n  gap: 0.35rem;\n  min-width: 0;\n}\n\n.petasos-listbar {\n  display: flex;\n  align-items: center;\n  justify-content: space-between;\n  gap: 1rem;\n  flex-wrap: wrap;\n  padding-top: 0.25rem;\n  border-top: 1px solid var(--color-border);\n}\n\n.petasos-listbar-count {\n  padding-top: 0.6rem;\n}\n\n.petasos-listbar > .petasos-status,\n.petasos-listbar > .petasos-integrity {\n  margin-top: 0.6rem;\n}\n\n.petasos-integrity {\n  display: flex;\n  align-items: center;\n  flex-wrap: wrap;\n  gap: 0.35rem 0.8rem;\n}\n\n.petasos-split {\n  display: grid;\n  grid-template-columns: minmax(0, 1fr);\n  gap: 1rem;\n  align-items: start;\n}\n\n.petasos-split-open {\n  grid-template-columns: minmax(0, 1.3fr) minmax(24rem, 1fr);\n}\n\n\n.petasos-split-open .petasos-event-header {\n  display: none;\n}\n\n.petasos-split-open .petasos-event {\n  grid-template-columns: minmax(0, 1fr) auto 1rem;\n  row-gap: 0.3rem;\n}\n\n.petasos-split-open .petasos-event-what {\n  grid-column: 1;\n  grid-row: 1;\n}\n\n.petasos-split-open .petasos-event-outcome {\n  grid-column: 2;\n  grid-row: 1;\n  justify-self: end;\n}\n\n.petasos-split-open .petasos-event-when {\n  grid-column: 1;\n  grid-row: 2;\n}\n\n.petasos-split-open .petasos-event-when .petasos-block {\n  display: inline;\n  margin-right: 0.6rem;\n}\n\n.petasos-split-open .petasos-event-severity {\n  grid-column: 2;\n  grid-row: 2;\n  justify-self: end;\n}\n\n.petasos-split-open .petasos-chevron {\n  grid-column: 3;\n  grid-row: 1 / span 2;\n}\n\n.petasos-split-open .petasos-group-bar {\n  padding-left: 0.75rem;\n}\n\n.petasos-split-even {\n  grid-template-columns: repeat(2, minmax(0, 1fr));\n}\n\n\n.petasos-split-try {\n  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);\n}\n\n.petasos-try-preview {\n  display: flex;\n  flex-direction: column;\n  gap: 0.35rem;\n}\n\n.petasos-try-preview .petasos-marked {\n  max-height: 16rem;\n  overflow: auto;\n}\n\n.petasos-try-using {\n  flex-wrap: wrap;\n}\n\n.petasos-trial-grid {\n  display: grid;\n  grid-template-columns: repeat(2, minmax(0, 1fr));\n  gap: 1rem;\n}\n\n.petasos-split-main {\n  min-width: 0;\n}\n\n.petasos-list-card {\n  padding: 0.4rem 1rem 0.6rem;\n}\n\n.petasos-event-header,\n.petasos-event {\n  display: grid;\n  grid-template-columns: 8.5rem minmax(0, 1fr) 7rem 11rem 1rem;\n  align-items: center;\n  gap: 1rem;\n}\n\n.petasos-event-header {\n  padding: 0.6rem 0.75rem;\n  border-bottom: 1px solid var(--color-border);\n  font-family: var(--font-mondwest);\n  font-size: 0.78rem;\n  font-weight: 400;\n  letter-spacing: 0.08em;\n  text-transform: uppercase;\n  color: var(--petasos-secondary);\n}\n\n.petasos-events {\n  list-style: none;\n  margin: 0;\n  padding: 0;\n}\n\n.petasos-event-item {\n  border-bottom: 1px solid var(--color-border);\n}\n\n.petasos-events-nested {\n  border-top: 1px dashed var(--color-border);\n  margin-left: 1.5rem;\n}\n\n.petasos-events-nested .petasos-event-item:last-child {\n  border-bottom: 0;\n}\n\n.petasos-event {\n  position: relative;\n  width: 100%;\n  padding: 0.5rem 0.75rem;\n  border: 0;\n  background: none;\n  color: inherit;\n  font: inherit;\n  text-align: left;\n  cursor: pointer;\n}\n\n.petasos-event:hover {\n  background: color-mix(in srgb, var(--midground) 6%, transparent);\n}\n\n.petasos-event:hover .petasos-chevron {\n  color: var(--midground);\n}\n\n\n.petasos-event-selected,\n.petasos-event-selected:hover {\n  background: color-mix(in srgb, var(--midground) 13%, transparent);\n  box-shadow: inset 3px 0 0 var(--midground);\n}\n\n.petasos-event-selected .petasos-chevron {\n  color: var(--midground);\n}\n\n.petasos-event-when {\n  font-size: 0.8125rem;\n  line-height: 1.45;\n  color: var(--petasos-secondary);\n}\n\n.petasos-event-what {\n  display: flex;\n  flex-direction: column;\n  gap: 0.15rem;\n  min-width: 0;\n}\n\n.petasos-event-summary {\n  font-size: 0.9375rem;\n}\n\n.petasos-event-meta {\n  display: flex;\n  flex-wrap: wrap;\n  align-items: center;\n  gap: 0.4rem;\n  font-size: 0.8125rem;\n  color: var(--petasos-secondary);\n}\n\n.petasos-event-meta .petasos-mono {\n  font-size: 0.8125rem;\n  color: var(--petasos-secondary);\n}\n\n.petasos-group-bar {\n  display: flex;\n  align-items: center;\n  gap: 1rem;\n  padding: 0 0.75rem 0.5rem 10.25rem;\n  font-size: 0.8125rem;\n  color: var(--petasos-secondary);\n}\n\n.petasos-more {\n  display: flex;\n  justify-content: center;\n  padding-top: 0.75rem;\n}\n\n.petasos-detail {\n  position: sticky;\n  top: 0.5rem;\n  display: flex;\n  flex-direction: column;\n  gap: 0.75rem;\n  padding: 1rem 1.1rem;\n  border: 1px solid var(--color-border);\n  box-shadow: inset 3px 0 0 var(--midground);\n  background: var(--color-card);\n  min-width: 0;\n}\n\n.petasos-detail-head {\n  display: flex;\n  align-items: center;\n  justify-content: space-between;\n  gap: 1rem;\n}\n\n.petasos-detail-which {\n  font-size: 0.875rem;\n  color: var(--petasos-secondary);\n}\n\n.petasos-detail-status {\n  display: flex;\n  align-items: center;\n  gap: 0.9rem;\n}\n\n.petasos-detail-title {\n  margin: 0;\n  font-size: 1.0625rem;\n  font-weight: 700;\n  line-height: 1.4;\n}\n\n.petasos-detail-note {\n  font-size: 0.9rem;\n  font-weight: 600;\n}\n\n\n\n.petasos-try-desc {\n  font-size: 0.9375rem;\n}\n\n.petasos-trial-line {\n  font-size: 0.875rem;\n}\n\n.petasos-textarea {\n  width: 100%;\n  padding: 0.6rem 0.75rem;\n  border: 1px solid var(--petasos-control-line);\n  background: color-mix(in srgb, var(--background) 40%, transparent);\n  color: inherit;\n  font: inherit;\n  font-size: 0.9rem;\n  line-height: 1.5;\n  resize: vertical;\n}\n\n.petasos-mono-area {\n  font-family: var(--theme-font-mono);\n  font-size: 0.85rem;\n}\n\n.petasos-textarea:disabled {\n  opacity: 0.55;\n  cursor: not-allowed;\n}\n\n.petasos-field-error {\n  font-size: 0.875rem;\n  font-weight: 700;\n  color: color-mix(in srgb, var(--color-destructive) 45%, white);\n}\n\n.petasos-light .petasos-field-error {\n  color: color-mix(in srgb, var(--color-destructive) 70%, black);\n}\n\n.petasos-decision {\n  display: flex;\n  flex-direction: column;\n  align-items: flex-start;\n  gap: 0.5rem;\n}\n\n.petasos-decision-text {\n  font-size: 0.9375rem;\n}\n\n.petasos-compare {\n  display: grid;\n  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);\n  grid-template-rows: auto auto auto;\n  column-gap: 1.25rem;\n}\n\n.petasos-compare-cell {\n  display: grid;\n  grid-template-rows: subgrid;\n  grid-row: 1 / -1;\n  align-content: start;\n  row-gap: 0.45rem;\n  min-width: 0;\n}\n\n.petasos-compare-cell + .petasos-compare-cell {\n  padding-left: 1.25rem;\n  border-left: 1px solid var(--color-border);\n}\n\n.petasos-message,\n.petasos-marked {\n  margin: 0;\n  padding: 0.65rem 0.8rem;\n  border: 1px solid var(--color-border);\n  font-family: var(--theme-font-mono);\n  font-size: 0.85rem;\n  line-height: 1.55;\n  white-space: pre-wrap;\n  overflow-wrap: anywhere;\n}\n\n/* Matched content is not a navigation link, so it is not underlined. */\n.petasos-mark {\n  background: color-mix(in srgb, var(--color-destructive) 24%, transparent);\n  color: inherit;\n  outline: 1px solid color-mix(in srgb, var(--color-destructive) 65%, transparent);\n  outline-offset: 0;\n}\n\n.petasos-mark-n {\n  font-weight: 700;\n  margin-right: 0.1rem;\n}\n\n.petasos-findings,\n.petasos-tech-findings {\n  list-style: none;\n  margin: 0;\n  padding: 0;\n  display: flex;\n  flex-direction: column;\n}\n\n.petasos-tech-findings li {\n  display: grid;\n  grid-template-columns: 1.6rem minmax(0, 1fr);\n  gap: 0.6rem;\n  padding: 0.25rem 0;\n  font-size: 0.875rem;\n}\n\n.petasos-finding {\n  display: grid;\n  grid-template-columns: 1.6rem minmax(0, 1fr);\n  gap: 0.6rem;\n  padding: 0.6rem 0;\n  border-bottom: 1px solid var(--color-border);\n}\n\n.petasos-finding-n {\n  font-size: 0.85rem;\n  font-weight: 700;\n  text-align: center;\n  padding-top: 0.05rem;\n}\n\n.petasos-finding-body {\n  display: flex;\n  flex-direction: column;\n  gap: 0.35rem;\n  min-width: 0;\n}\n\n.petasos-finding-head {\n  display: flex;\n  align-items: flex-start;\n  justify-content: space-between;\n  gap: 0.75rem;\n}\n\n.petasos-finding-sentence {\n  font-size: 0.9375rem;\n}\n\n.petasos-took-part {\n  list-style: none;\n  margin: 0;\n  padding: 0;\n  display: flex;\n  flex-direction: column;\n  gap: 0.5rem;\n}\n\n.petasos-took-part li {\n  display: grid;\n  grid-template-columns: 5.5rem minmax(0, 1fr);\n  gap: 0.1rem 0.85rem;\n  align-items: baseline;\n}\n\n.petasos-took-part li > .petasos-secondary {\n  grid-column: 2;\n  font-size: 0.875rem;\n}\n\n.petasos-took-part .petasos-status {\n  justify-self: start;\n}\n\n.petasos-took-name {\n  font-weight: 600;\n  font-size: 0.9rem;\n}\n\n.petasos-quieted {\n  list-style: none;\n  margin: 0;\n  padding: 0;\n  display: flex;\n  flex-direction: column;\n  gap: 0.35rem;\n  font-size: 0.875rem;\n}\n\n\n.petasos-quieted li {\n  display: grid;\n  grid-template-columns: minmax(0, 1fr) auto;\n  gap: 0.25rem 1rem;\n  align-items: center;\n  padding: 0.45rem 0;\n  border-bottom: 1px solid var(--color-border);\n}\n\n.petasos-quieted li:first-child {\n  border-top: 1px solid var(--color-border);\n}\n\n.petasos-quieted-name {\n  display: flex;\n  flex-direction: column;\n  gap: 0.1rem;\n  min-width: 0;\n}\n\n\n\n.petasos-settings-toolbar {\n  position: relative;\n  display: flex;\n  flex-wrap: wrap;\n  align-items: center;\n  gap: 0.75rem 1.5rem;\n}\n\n.petasos-settings-toolbar .petasos-search {\n  max-width: 26rem;\n}\n\n.petasos-savebox {\n  display: flex;\n  align-items: center;\n  gap: 0.6rem;\n  margin-left: auto;\n}\n\n\n.petasos-changecount {\n  display: inline-flex;\n  align-items: center;\n  gap: 0.3rem;\n  padding: 0.2rem 0.1rem;\n  border: 0;\n  background: none;\n  color: var(--petasos-ink);\n  font: inherit;\n  font-size: 0.875rem;\n  font-weight: 600;\n  cursor: pointer;\n}\n\n.petasos-changecount-chevron {\n  transform: rotate(90deg);\n  transition: transform 120ms;\n}\n\n.petasos-changecount[aria-expanded=\"true\"] .petasos-changecount-chevron {\n  transform: rotate(-90deg);\n}\n\n.petasos-settings-body {\n  display: grid;\n  grid-template-columns: 13.5rem minmax(0, 1fr);\n  gap: 1rem;\n  align-items: start;\n}\n\n\n.petasos-sections {\n  display: flex;\n  flex-direction: column;\n  gap: 1px;\n  padding: 0.5rem;\n  border: 1px solid var(--color-border);\n  background: color-mix(in srgb, var(--color-muted, var(--color-card)) 20%, transparent);\n  position: sticky;\n  top: 0.5rem;\n}\n\n.petasos-sections-title {\n  padding: 0.2rem 0.5rem 0.35rem;\n  font-size: 0.75rem;\n  letter-spacing: 0.12em;\n  color: var(--petasos-tertiary);\n}\n\n.petasos-section {\n  display: flex;\n  align-items: center;\n  gap: 0.4rem;\n  padding: 0.25rem 0.5rem;\n  border: 0;\n  background: none;\n  color: var(--petasos-secondary);\n  font-family: var(--theme-font-mono);\n  font-size: 0.8rem;\n  text-align: left;\n  cursor: pointer;\n}\n\n.petasos-section:hover {\n  background: color-mix(in srgb, var(--midground) 7%, transparent);\n  color: var(--midground);\n}\n\n.petasos-section-on,\n.petasos-section-on:hover {\n  background: color-mix(in srgb, var(--midground) 12%, transparent);\n  color: var(--midground);\n}\n\n.petasos-section-name {\n  margin-right: auto;\n}\n\n.petasos-section-changed {\n  font-size: 0.55rem;\n}\n\n.petasos-section-count {\n  font-size: 0.75rem;\n  color: var(--petasos-tertiary);\n  font-variant-numeric: tabular-nums;\n}\n\n.petasos-section-on .petasos-section-count {\n  color: var(--petasos-secondary);\n}\n\n.petasos-settings-main {\n  min-width: 0;\n}\n\n.petasos-group {\n  display: flex;\n  flex-direction: column;\n}\n\n.petasos-group-head {\n  display: flex;\n  align-items: center;\n  gap: 0.6rem;\n  padding-top: 0.9rem;\n}\n\n.petasos-group-name {\n  font-family: var(--font-mondwest);\n  font-size: 0.75rem;\n  font-weight: 400;\n  letter-spacing: 0.1em;\n  text-transform: uppercase;\n  color: var(--petasos-secondary);\n}\n\n.petasos-group-rule {\n  flex: 1;\n  border-top: 1px solid var(--color-border);\n}\n\n\n.petasos-field {\n  display: flex;\n  flex-direction: column;\n  gap: 0.4rem;\n  padding: 0.85rem 0 0.95rem;\n  scroll-margin: 1rem;\n}\n\n\n.petasos-field-head {\n  display: flex;\n  align-items: flex-start;\n  justify-content: space-between;\n  gap: 1.5rem;\n}\n\n.petasos-field-text {\n  display: flex;\n  flex-direction: column;\n  gap: 0.2rem;\n  min-width: 0;\n}\n\n.petasos .petasos-field-label {\n  font-family: var(--font-mondwest);\n  font-size: 0.875rem;\n  font-weight: 400;\n  letter-spacing: 0.08em;\n  line-height: 1.3;\n  text-transform: uppercase;\n  color: var(--petasos-ink);\n}\n\n.petasos-field-key {\n  font-family: var(--theme-font-mono);\n  font-size: 0.75rem;\n  color: var(--petasos-tertiary);\n}\n\n.petasos-field-help {\n  font-size: 0.8125rem;\n  color: var(--petasos-secondary);\n  max-width: 60rem;\n}\n\n.petasos-field-switch {\n  padding-top: 0.1rem;\n}\n\n.petasos-field-control {\n  min-width: 0;\n}\n\n.petasos-field-staged .petasos-field-label::after {\n  content: \" \u2022\";\n}\n\n.petasos-staged-word {\n  color: var(--petasos-ink);\n}\n\n.petasos-field-invalid input,\n.petasos-field-invalid textarea {\n  border-width: 2px;\n  border-style: solid;\n  border-color: var(--color-destructive) !important;\n}\n\n.petasos-field-invalid input:focus-visible,\n.petasos-field-invalid textarea:focus-visible {\n  outline: 2px solid var(--midground);\n  outline-offset: 2px;\n}\n\n\n.petasos-field-staged,\n.petasos-field-invalid {\n  background: color-mix(in srgb, var(--midground) 5%, transparent);\n  margin: 0 -0.6rem;\n  padding-left: 0.6rem;\n  padding-right: 0.6rem;\n}\n\n\n.petasos-consequence {\n  font-size: 0.875rem;\n  padding-left: 0.6rem;\n  border-left: 2px solid var(--color-warning);\n}\n\n.petasos-maprows {\n  display: flex;\n  flex-direction: column;\n  gap: 0.4rem;\n}\n\n.petasos-maprow {\n  display: grid;\n  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) 5.5rem;\n  gap: 0.5rem;\n  align-items: center;\n}\n\n.petasos-rule-helper .petasos-kv {\n  font-size: 0.875rem;\n}\n\n\n\n@media (max-width: 1100px) {\n  .petasos-split-open,\n  .petasos-split-even,\n  .petasos-split-try,\n  .petasos-grid-3 {\n    grid-template-columns: minmax(0, 1fr);\n  }\n  .petasos-detail {\n    position: static;\n  }\n  .petasos-filter-selects {\n    grid-template-columns: repeat(2, minmax(0, 1fr));\n  }\n}\n\n@media (max-width: 560px) {\n  .petasos-filter-selects {\n    grid-template-columns: minmax(0, 1fr);\n  }\n}\n\n@media (max-width: 1000px) {\n  .petasos-grid-2,\n  .petasos-settings-body,\n  .petasos-compare {\n    grid-template-columns: minmax(0, 1fr);\n    grid-template-rows: none;\n  }\n  .petasos-compare-cell {\n    display: flex;\n    flex-direction: column;\n    grid-row: auto;\n  }\n  .petasos-compare-cell + .petasos-compare-cell {\n    padding-left: 0;\n    border-left: 0;\n    padding-top: 0.8rem;\n    border-top: 1px solid var(--color-border);\n  }\n  .petasos-sections {\n    position: static;\n    flex-direction: row;\n    flex-wrap: wrap;\n  }\n  .petasos-event-header {\n    display: none;\n  }\n  .petasos-event {\n    grid-template-columns: minmax(0, 1fr) auto 1rem;\n  }\n  .petasos-event-when {\n    grid-column: 1 / -1;\n  }\n  .petasos-event-severity {\n    display: none;\n  }\n  .petasos-group-bar {\n    padding-left: 0.75rem;\n  }\n  .petasos-opt {\n    grid-template-columns: 7rem minmax(0, 1fr);\n  }\n  .petasos-mini-row {\n    grid-template-columns: 3.5rem minmax(0, 1fr) auto 1rem;\n    gap: 0.7rem;\n  }\n}\n\n@media (max-width: 560px) {\n  .petasos-kv {\n    grid-template-columns: minmax(0, 1fr);\n    gap: 0.1rem;\n  }\n\n  .petasos-kv dd {\n    margin-bottom: 0.5rem;\n  }\n\n  .petasos-panel-headrow {\n    flex-wrap: wrap;\n  }\n}\n\n.petasos-integrity-note {\n  max-width: 60rem;\n  font-size: 0.9rem;\n  color: var(--petasos-secondary);\n}\n\n@media (max-width: 1100px) {\n  /* One column: the open event's details come first, above the list. */\n  .petasos-split-open .petasos-detail {\n    order: -1;\n  }\n}\n\n@media (max-width: 560px) {\n  .petasos-list-card {\n    padding: 0.2rem 0.5rem 0.4rem;\n  }\n\n  .petasos-event,\n  .petasos-split-open .petasos-event {\n    grid-template-columns: minmax(0, 1fr) 1rem;\n    gap: 0.3rem 0.5rem;\n    padding: 0.6rem 0.4rem;\n  }\n\n  .petasos-event .petasos-event-what,\n  .petasos-split-open .petasos-event-what {\n    grid-column: 1;\n    grid-row: 1;\n  }\n\n  .petasos-event .petasos-event-outcome,\n  .petasos-split-open .petasos-event-outcome {\n    grid-column: 1;\n    grid-row: 2;\n    justify-self: start;\n  }\n\n  .petasos-event .petasos-event-when,\n  .petasos-split-open .petasos-event-when {\n    grid-column: 1;\n    grid-row: 3;\n  }\n\n  .petasos-event .petasos-event-severity,\n  .petasos-split-open .petasos-event-severity {\n    display: none;\n  }\n\n  .petasos-event .petasos-chevron,\n  .petasos-split-open .petasos-chevron {\n    grid-column: 2;\n    grid-row: 1 / span 3;\n    align-self: center;\n  }\n\n  .petasos-event-when .petasos-block {\n    display: inline;\n    margin-right: 0.5rem;\n  }\n}\n\n.petasos-busy {\n  opacity: 0.7;\n  cursor: progress;\n}\n\n.petasos-compare-note {\n  font-size: 0.875rem;\n  color: var(--petasos-secondary);\n}\n\n.petasos-section-pick {\n  display: none;\n}\n\n@media (max-width: 700px) {\n  .petasos-section-pick {\n    display: flex;\n  }\n\n  .petasos-settings-body > .petasos-sections {\n    display: none;\n  }\n}\n\n@media (max-width: 560px) {\n  .petasos-version {\n    display: none;\n  }\n\n  /* Choices wrap into even cells instead of a ragged second row. */\n  .petasos-choose .petasos-segmented {\n    display: grid;\n    grid-template-columns: repeat(auto-fit, minmax(7.5rem, 1fr));\n    width: 100%;\n  }\n\n  .petasos-event,\n  .petasos-split-open .petasos-event {\n    grid-template-columns: auto minmax(0, 1fr) 1rem;\n  }\n\n  .petasos-event .petasos-event-what,\n  .petasos-split-open .petasos-event-what,\n  .petasos-event .petasos-event-when,\n  .petasos-split-open .petasos-event-when {\n    grid-column: 1 / span 2;\n  }\n\n  .petasos-event .petasos-event-severity,\n  .petasos-split-open .petasos-event-severity {\n    display: block;\n    grid-column: 2;\n    grid-row: 2;\n    justify-self: start;\n    align-self: center;\n  }\n\n  .petasos-event .petasos-chevron,\n  .petasos-split-open .petasos-chevron {\n    grid-column: 3;\n  }\n}\n\n.petasos-event-explain {\n  font-size: 0.875rem;\n  color: var(--petasos-secondary);\n}\n\n.petasos-field-help {\n  max-width: 46rem;\n}\n\n@media (max-width: 560px) {\n  .petasos-trial-grid {\n    grid-template-columns: minmax(0, 1fr);\n  }\n\n  /* Tabs first, then one row for the protection state, freshness and Refresh. */\n  .petasos-topbar-main,\n  .petasos-topbar-side {\n    display: contents;\n  }\n\n  .petasos-viewtabs {\n    flex-basis: 100%;\n  }\n\n  .petasos-topbar {\n    justify-content: flex-start;\n    gap: 0.4rem 0.9rem;\n  }\n\n  .petasos-choose .petasos-segmented {\n    gap: 1px;\n    border: 0;\n    background: none;\n  }\n\n  .petasos-choose .petasos-segment {\n    border: 1px solid var(--petasos-control-line);\n    min-height: 2.5rem;\n  }\n}\n\n@media (max-width: 760px) {\n  .petasos-setup-grid {\n    grid-template-columns: minmax(0, 1fr);\n  }\n}\n\n@media (max-width: 560px) {\n  /* The four view tabs share the row; the outline ends where they do. */\n  .petasos-viewtabs {\n    display: grid;\n    grid-template-columns: repeat(4, minmax(0, 1fr));\n  }\n\n  .petasos-viewtabs .petasos-segment {\n    display: flex;\n    justify-content: center;\n    padding-left: 0.25rem;\n    padding-right: 0.25rem;\n    text-align: center;\n  }\n\n  .petasos-listbar {\n    gap: 0.4rem 1rem;\n  }\n\n  .petasos-listbar > .petasos-status,\n  .petasos-listbar > .petasos-integrity {\n    margin-top: 0;\n  }\n}\n";

  (function addStyle() {
    if (document.getElementById("petasos-tab-style")) return;
    var element = document.createElement("style");
    element.id = "petasos-tab-style";
    element.textContent = STYLE;
    document.head.appendChild(element);
  })();
  // ===== dashboard-src/05-shared.js =====

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
            change.applies && change.applies !== props.sharedApplies ? " · " + change.applies : "",
            " · ",
            h("span", { className: "petasos-key" }, change.path)
          )
        );
      })
    );
  }

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

  // Staged settings survive a reload, including Hermes's own reload after a sign-in.
  // One draft per Hermes profile: a tab that moves between profiles must not carry edits across.
  function draftKeyFor(home) {
    return "petasos.draft" + (home ? ":" + home : "");
  }

  function readDraft(home) {
    try {
      var parsed = JSON.parse(window.sessionStorage.getItem(draftKeyFor(home)) || "null");
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return EMPTY_DRAFT;
      var draft = { overrides: {} };
      if (typeof parsed.enabled === "boolean") draft.enabled = parsed.enabled;
      if (typeof parsed.role === "string") draft.role = parsed.role;
      if (typeof parsed.level === "string") draft.level = parsed.level;
      if (parsed.overrides && typeof parsed.overrides === "object" && !Array.isArray(parsed.overrides)) draft.overrides = parsed.overrides;
      return draftIsEmpty(draft) ? EMPTY_DRAFT : draft;
    } catch (_e) {
      return EMPTY_DRAFT;
    }
  }

  function writeDraft(draft, home) {
    try {
      if (draftIsEmpty(draft)) window.sessionStorage.removeItem(draftKeyFor(home));
      else window.sessionStorage.setItem(draftKeyFor(home), JSON.stringify(draftBody(draft)));
    } catch (_e) {
      // Storage may be refused; the draft still lives for this visit.
    }
  }

  function isPlain(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  // Equal values, whatever order a mapping's keys come in.
  function sameValue(a, b) {
    if (a === undefined) a = null;
    if (b === undefined) b = null;
    if (isPlain(a) && isPlain(b)) {
      var keys = Object.keys(a);
      return (
        keys.length === Object.keys(b).length &&
        keys.every(function (key) {
          return Object.prototype.hasOwnProperty.call(b, key) && sameValue(a[key], b[key]);
        })
      );
    }
    if (Array.isArray(a) && Array.isArray(b)) {
      return (
        a.length === b.length &&
        a.every(function (item, index) {
          return sameValue(item, b[index]);
        })
      );
    }
    return a === b;
  }

  // Whether a stored value holds what was sent. Petasos merges a mapping into
  // the entries already stored, so a stored mapping may hold more than the patch.
  function holdsValue(stored, sent) {
    if (isPlain(sent) && isPlain(stored)) {
      return Object.keys(sent).every(function (key) {
        return Object.prototype.hasOwnProperty.call(stored, key) && holdsValue(stored[key], sent[key]);
      });
    }
    return sameValue(stored, sent);
  }

  // The schema's setting paths, as a lookup. `rows` is a settings body's `settings`.
  function knownPaths(rows) {
    if (!rows) return null;
    var known = {};
    rows.forEach(function (row) {
      known[row.path] = true;
    });
    return known;
  }

  // The settings a tree of overrides names. A mapping-valued setting, such as
  // rule ids to severities, is one setting whatever dots its keys hold, so the
  // walk stops at a path the schema knows. Without the schema it stops at
  // "section.setting", which compares anything deeper whole.
  function leafPaths(tree, known) {
    var found = [];
    (function walk(node, parts) {
      Object.keys(node || {}).forEach(function (key) {
        var next = parts.concat([key]);
        var path = next.join(".");
        var value = node[key];
        var plain = value && typeof value === "object" && !Array.isArray(value) && Object.keys(value).length;
        if (!plain || (known ? known[path] : next.length >= 2)) found.push(path);
        else walk(value, next);
      });
    })(tree, []);
    return found;
  }

  // Whether the settings Petasos holds already contain everything in `body`.
  function holdsChange(settings, body) {
    var stored = (settings && settings.stored) || {};
    var chosen = (settings && settings.chosen) || [];
    var keys = ["enabled", "role", "level"];
    for (var i = 0; i < keys.length; i += 1) {
      if (body[keys[i]] === undefined) continue;
      if (!sameValue(body[keys[i]], stored[keys[i]])) return false;
      // A job or strictness that only equals the default has not been written.
      if (keys[i] !== "enabled" && chosen.indexOf(keys[i]) < 0) return false;
    }
    var paths = leafPaths(body.overrides || {}, knownPaths(settings && settings.settings));
    for (var j = 0; j < paths.length; j += 1) {
      if (!holdsValue(getIn(stored.overrides || {}, paths[j]), getIn(body.overrides, paths[j]))) return false;
    }
    return true;
  }

  // A write whose answer is lost says nothing about whether it happened, so the
  // settings are read back and the result is reported as what that reading shows.
  function settleWrite(failure, held) {
    if (!unknownOutcome(failure)) {
      failure.outcome = "refused";
      throw failure;
    }
    return call("/settings", { timeout: 10000 }).then(
      function (settings) {
        if (held(settings)) return { settings: settings, readBack: true };
        var missing = new ApiFailure(
          failure.status,
          failure.code,
          "Petasos did not confirm the change, and it was not there when this page read the settings back at " +
            clockTime(Date.now()) +
            ". A request that got no answer can still finish later; Refresh shows what is saved now.",
          failure.path
        );
        missing.outcome = "not_saved";
        missing.settings = settings;
        throw missing;
      },
      function () {
        var unknown = new ApiFailure(
          failure.status,
          failure.code,
          "Petasos did not answer, so this page cannot tell whether the change was saved. Check again before you retry.",
          failure.path
        );
        unknown.outcome = "unknown";
        throw unknown;
      }
    );
  }

  var READ_BACK_NOTE = "Petasos's answer was lost, so this page read the settings back: the change is saved.";

  // `applies` is the sentence a preview gave for when this change takes effect.
  function writeSettings(body, applies) {
    return call("/settings", { method: "PUT", body: body }).then(
      function (saved) {
        return { settings: saved, readBack: false, message: saved.restart_message || "Saved" };
      },
      function (failure) {
        return settleWrite(failure, function (settings) {
          return holdsChange(settings, body);
        }).then(function (result) {
          result.message = READ_BACK_NOTE + (applies ? " " + applies : "");
          return result;
        });
      }
    );
  }

  // What is left of `draft` once `sent` has been saved: anything edited since stays.
  function draftAfterSave(draft, sent, known) {
    var left = { overrides: clone((draft && draft.overrides) || {}) };
    ["enabled", "role", "level"].forEach(function (key) {
      if (draft && draft[key] !== undefined && !sameValue(draft[key], sent[key])) left[key] = draft[key];
    });
    leafPaths(sent.overrides || {}, known).forEach(function (path) {
      if (hasIn(left.overrides, path) && sameValue(getIn(left.overrides, path), getIn(sent.overrides, path))) {
        removeIn(left.overrides, path);
      }
    });
    return draftIsEmpty(left) ? EMPTY_DRAFT : left;
  }

  // The staged values a trial would overwrite with something different.
  function draftConflicts(draft, candidate, known) {
    var found = [];
    if (!draft || !candidate) return found;
    ["enabled", "role", "level"].forEach(function (key) {
      if (draft[key] !== undefined && candidate[key] !== undefined && !sameValue(draft[key], candidate[key])) found.push(key);
    });
    leafPaths(candidate.overrides || {}, known).forEach(function (path) {
      if (hasIn(draft.overrides || {}, path) && !sameValue(getIn(draft.overrides, path), getIn(candidate.overrides, path))) {
        found.push(path);
      }
    });
    return found;
  }

  function mergeDraft(draft, candidate, known) {
    var next = { overrides: clone((draft && draft.overrides) || {}) };
    ["enabled", "role", "level"].forEach(function (key) {
      if (draft && draft[key] !== undefined) next[key] = draft[key];
      if (candidate[key] !== undefined && candidate[key] !== "") next[key] = candidate[key];
    });
    leafPaths(candidate.overrides || {}, known).forEach(function (path) {
      setIn(next.overrides, path, clone(getIn(candidate.overrides, path)));
    });
    return next;
  }

  // Only the newest request of a kind may publish its answer.
  function useLatest() {
    var count = useRef(0);
    return function begin() {
      count.current += 1;
      var mine = count.current;
      return function isLatest() {
        return mine === count.current;
      };
    };
  }

  function resetSettings(path) {
    var url = path === "*" ? "/overrides" : "/overrides/" + path;
    return call(url, { method: "DELETE" }).then(
      function (body) {
        var effect = String(body.restart_message || "").replace(/^Reset\.\s*/, "");
        return { settings: body.settings, readBack: false, message: [body.message, effect].filter(Boolean).join(" ") };
      },
      function (failure) {
        return settleWrite(failure, function (settings) {
          var overrides = (settings.stored && settings.stored.overrides) || {};
          return path === "*" ? !Object.keys(overrides).length : !hasIn(overrides, path);
        }).then(function (result) {
          result.message = READ_BACK_NOTE;
          return result;
        });
      }
    );
  }
  // ===== dashboard-src/10-overview.js =====

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
  // ===== dashboard-src/20-activity.js =====

  var RANGES = [
    { value: "1h", label: "1 hour", seconds: 3600 },
    { value: "24h", label: "24 hours", seconds: 86400 },
    { value: "7d", label: "7 days", seconds: 7 * 86400 },
    { value: "all", label: "All", seconds: null },
    { value: "custom", label: "Custom", seconds: null },
  ];

  // An outcome filter is the list of outcome codes one of the API's figures covers.
  function figureCodes(figure) {
    return (figure.outcomes || [figure.code]).slice().sort().join(",");
  }

  function figureFor(figures, value) {
    var wanted = String(value || "").split(",").filter(Boolean).sort().join(",");
    return (figures || []).filter(function (figure) {
      return figureCodes(figure) === wanted;
    })[0];
  }

  // Custom date ranges use browser-local time with an unambiguous year-month-day form.
  function parseLocal(value) {
    var match = String(value || "").trim().match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})$/);
    if (!match) return null;
    var date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]), Number(match[4]), Number(match[5]));
    if (date.getMonth() !== Number(match[2]) - 1 || date.getDate() !== Number(match[3])) return null;
    if (Number(match[4]) > 23 || Number(match[5]) > 59) return null;
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
    useEffect(
      function () {
        if (props.onInvalid) props.onInvalid(invalid);
      },
      [invalid]
    );
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
    var tone =
      integrity.mode === "verified"
        ? integrity.unsigned
          ? "warning"
          : "success"
        : integrity.mode === "off" || integrity.mode === "unsigned"
          ? "warning"
          : "destructive";
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
      h(
        LinkButton,
        { expanded: props.open, onClick: props.onToggle },
        props.open ? "Hide what a signature shows" : integrity.limit_label
      )
    );
  }

  function IntegrityNotice(props) {
    var integrity = props.integrity;
    var signing = props.signing || {};
    var openState = useState(false);
    if (!integrity) return null;
    if (integrity.mode === "off" && props.secretSet) {
      return h(
        Notice,
        { tone: "warning", title: "Signatures cannot be checked" },
        h(
          "p",
          null,
          "A session secret is set, but Petasos cannot make a signing key from it, so this page cannot tell which records are genuine." +
            (integrity.reason ? " " + sentenceCase(integrity.reason).replace(/\.?$/, ".") : "")
        ),
        h("p", null, "Running hermes petasos doctor names what is wrong with the secret.")
      );
    }
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
    var unsigned = integrity.unsigned
      ? h(
          Notice,
          { tone: "info", title: plural(integrity.unsigned, "record has", "records have") + " no signature" },
          "A record without a signature may have been written before signing was set up, or by something other than Petasos. This page cannot tell which, and cannot say whether it changed."
        )
      : null;
    if (integrity.mode === "failed" || integrity.mode === "mixed") {
      return h(
        Fragment,
        null,
        h(
          Notice,
          { tone: "destructive", strong: true, title: "Some records do not match their signatures" },
          "A marked record could not be verified with this profile's current key. It may have been changed, written by something else, or signed with an earlier key. Treat its contents as unverified."
        ),
        unsigned
      );
    }
    return unsigned;
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
    var chosen = ["outcome", "kind", "tool", "session", "severity"].filter(function (key) {
      return filters[key];
    });
    var active = chosen.length > 0 || Boolean(filters.q);
    var openState = useState(chosen.length > 0);
    var open = openState[0];
    var figures = options.figures || [];
    var shownFigure = figureFor(figures, filters.outcome);
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
        h(
          Btn,
          {
            outlined: true,
            className: "petasos-filter-toggle",
            "aria-expanded": open,
            "aria-controls": "petasos-filter-selects",
            onClick: function () {
              openState[1](!open);
            },
          },
          (open ? "Hide filters" : "Filters") + (chosen.length ? " (" + chosen.length + " on)" : "")
        ),
        active
          ? h(
              Btn,
              {
                ghost: true,
                onClick: function () {
                  openState[1](false);
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
              onInvalid: function (bad) {
                props.onRangeInvalid("from", bad);
              },
              value: filters.from || "",
              onChange: function (value) {
                set("from", value);
              },
            }),
            h(DateTimeField, {
              id: "petasos-to",
              label: "To",
              onInvalid: function (bad) {
                props.onRangeInvalid("to", bad);
              },
              value: filters.to || "",
              onChange: function (value) {
                set("to", value);
              },
            })
          )
        : null,
      open
        ? h(
        "div",
        { className: "petasos-filter-selects", id: "petasos-filter-selects" },
        h(Choice, {
          id: "petasos-filter-outcome",
          label: "Outcome",
          value: shownFigure ? shownFigure.code : filters.outcome ? "__current" : "any",
          options: [{ value: "any", label: "Any" }]
            .concat(
              figures.map(function (figure) {
                return { value: figure.code, label: figure.label + " (" + figure.count + ")" };
              })
            )
            .concat(filters.outcome && !shownFigure ? [{ value: "__current", label: props.word || filters.outcome }] : []),
          onChange: function (value) {
            if (value === "__current") return;
            var figure = figures.filter(function (item) {
              return item.code === value;
            })[0];
            set("outcome", figure ? figureCodes(figure) : value);
          },
        }),
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
        : null
    );
  }

  function EventRow(props) {
    var event = props.event;
    var outcome = event.outcome || {};
    var failed = event.integrity && event.integrity.status === "failed";
    var headline = event.headline || event.summary;
    var severityWord = event.severity_label || capital(event.severity);
    return h(
      "button",
      {
        type: "button",
        id: "petasos-event-" + event.scan_id,
        className: cn("petasos-event", props.selected && "petasos-event-selected", props.nested && "petasos-event-nested"),
        "aria-current": props.selected ? "true" : undefined,
        "aria-label":
          (props.selected ? "Open now: " : "Open details: ") +
          [
            headline,
            event.headline && event.explanation ? event.explanation : "",
            outcome.label || "Recorded",
            severityWord ? "severity " + severityWord : "",
            failed ? "signature does not match" : "",
            event.integrity && event.integrity.status === "unsigned" ? "no signature" : "",
            event.tool ? "tool " + event.tool : "",
            event.session_id ? "conversation " + event.session_id : "",
            listTime(event.timestamp),
          ]
            .filter(Boolean)
            .join(", "),
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
        h("span", { className: "petasos-event-summary" }, headline),
        event.headline && event.explanation ? h("span", { className: "petasos-event-explain" }, event.explanation) : null,
        h(
          "span",
          { className: "petasos-event-meta" },
          event.tool ? h(Mono, null, event.tool) : null,
          event.tool && event.session_id ? h("span", { "aria-hidden": true }, "·") : null,
          event.session_id ? h("span", null, event.session_id) : null,
          failed ? h(Status, { tone: "destructive" }, "Signature does not match") : null,
          event.integrity && event.integrity.status === "unsigned" ? h(Status, { tone: "neutral" }, "No signature") : null
        )
      ),
      h("span", { className: "petasos-event-severity" }, h(Severity, { value: event.severity, label: event.severity_label })),
      h("span", { className: "petasos-event-outcome" }, h(Status, { tone: outcomeTone(outcome.code), state: outcome.code }, outcome.label || "Recorded")),
      h(Icon, { name: "chevron", className: "petasos-chevron" })
    );
  }

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

  var SHOWN_FIELDS = {
    scan_id: 1, timestamp: 1, event_type: 1, tool: 1, session_id: 1, severity: 1, rule_id: 1, reason: 1,
    summary: 1, outcome: 1, kind_label: 1, rule_sentence: 1, integrity: 1, sig: 1, matched_note: 1,
    deferred_to: 1, score: 1, tier: 1, target: 1, outcome_note: 1, risk_block: 1, review_action: 1, risk_sentence: 1,
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
    var risky = Boolean(event.session_id && event.risk_block);
    useEffect(
      function () {
        if (!ref.current) return;
        ref.current.focus({ preventScroll: true });
        // In one column the details sit above the list, possibly out of view.
        var box = ref.current.getBoundingClientRect();
        if (box.top < 0 || box.top > window.innerHeight - 160) revealInView(ref.current, "start");
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
      h("h3", { className: "petasos-detail-title", id: "petasos-detail-title" }, event.headline || event.summary),
      event.headline && event.explanation ? h("p", { className: "petasos-detail-note" }, event.explanation) : null,
      event.outcome_note ? h("p", { className: "petasos-detail-note" }, event.outcome_note) : null,
      event.risk_sentence ? h("p", { className: "petasos-detail-note" }, event.risk_sentence) : null,
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
          ["Left for", event.deferred_to || null],
          ["Conversation risk", typeof event.score === "number" ? String(event.score) + " points" : null],
          ["Risk tier", event.tier || null],
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

  function sideBySide() {
    return window.innerWidth > 1100;
  }

  function inView(element) {
    var box = element.getBoundingClientRect();
    return box.top >= 80 && box.bottom <= window.innerHeight - 40;
  }

  function Activity(props) {
    var params = props.route.params;
    var filters = filtersFromRoute(params);
    var selectedId = params.event || "";
    // Rows, counts and signature status are read together and kept with the
    // filters that produced them, so one selection is never shown under another.
    var filterKey = JSON.stringify(filters);
    var dataState = useState(null);
    var failureState = useState(null);
    var olderState = useState({ key: filterKey, chunks: [] });
    var loadingMore = useState(false);
    var extraEvent = useState(null);
    var limitState = useState(false);
    var retryState = useState(0);
    var returnTo = useRef("");
    var anchored = useRef(false);
    var noteState = useState("");
    var lookupState = useState(0);
    var olderFailureState = useState(null);
    var badDateState = useState({});
    var begin = useLatest();

    function setFilters(next) {
      var route = Object.assign({}, next);
      Object.keys(route).forEach(function (key) {
        if (!route[key]) delete route[key];
      });
      go("activity", route);
    }

    function requestNow() {
      var span = rangeWindow(filters);
      return {
        limit: 100,
        since: span.since,
        until: span.until,
        q: filters.q,
        kind: filters.kind,
        tool: filters.tool,
        session: filters.session,
        severity: filters.severity,
        outcome: filters.outcome,
      };
    }

    var unreadableDate = filters.range === "custom" && (badDateState[0].from || badDateState[0].to);
    var customSpan = filters.range === "custom" ? rangeWindow(filters) : null;
    var backwards = Boolean(customSpan && customSpan.since && customSpan.until && customSpan.since > customSpan.until);
    usePoll(
      function () {
        // With older pages open the list is one fixed reading: a refreshed first
        // page under them could drop or repeat events at the seam.
        if (anchored.current || backwards) return null;
        var latest = begin();
        var live = requestNow();
        if (!live.until) live.until = Math.floor(Date.now() / 1000);
        var counted = Object.assign({}, live);
        delete counted.limit;
        return Promise.all([
          call("/activity" + query(live)),
          call("/activity/summary" + query({ since: live.since, until: live.until, q: filters.q })),
          call("/activity/summary" + query(counted)),
        ]).then(
          function (answers) {
            if (!latest()) return;
            dataState[1]({ key: filterKey, page: answers[0], options: answers[1], counts: answers[2], request: live, readAt: Date.now() });
            failureState[1](null);
          },
          function (failure) {
            if (latest()) failureState[1]({ key: filterKey, failure: failure });
          }
        );
      },
      15000,
      [filterKey, props.refreshKey, retryState[0]]
    );

    var data = dataState[0] && dataState[0].key === filterKey ? dataState[0] : null;
    var failure = failureState[0] && failureState[0].key === filterKey ? failureState[0].failure : null;
    var page = data && data.page;
    var older = olderState[0].key === filterKey ? olderState[0].chunks : [];
    var olderFailure = olderFailureState[0] && olderFailureState[0].key === filterKey ? olderFailureState[0].failure : null;
    if (!older.length && !loadingMore[0] && !olderFailure) anchored.current = false;

    function loadOlder() {
      var last = older.length ? older[older.length - 1] : page;
      if (!last || !last.next_cursor) return;
      var key = filterKey;
      // From here the list is one reading: a refresh already under way must not
      // replace the first page, and older pages use the same time bounds as it.
      anchored.current = true;
      begin();
      loadingMore[1](true);
      olderFailureState[1](null);
      call("/activity" + query(Object.assign({}, data.request, { cursor: last.next_cursor })))
        .then(
          function (body) {
            if (body.cursor_reset) {
              // The record was rotated under the cursor: rows, counts and signatures are all read again.
              reload("The record was rotated while you were reading, so the list was reloaded from the newest event.");
              return;
            }
            olderState[1](function (held) {
              return { key: key, chunks: (held.key === key ? held.chunks : []).concat([body]) };
            });
          },
          function (problem) {
            olderFailureState[1]({ key: key, failure: problem });
          }
        )
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

    useEffect(
      function () {
        if (!selectedId || selected || !page) return;
        var live = true;
        extraEvent[1]({ id: selectedId, state: "loading" });
        call("/activity/" + encodeURIComponent(selectedId)).then(
          function (body) {
            if (live) extraEvent[1](body.event ? { id: selectedId, state: "found", event: body.event } : { id: selectedId, state: "missing" });
          },
          function (problem) {
            if (live) extraEvent[1]({ id: selectedId, state: problem.status === 404 ? "missing" : "failed", failure: problem });
          }
        );
        return function () {
          live = false;
        };
      },
      [selectedId, Boolean(selected), Boolean(page), lookupState[0]]
    );
    var lookup = !selected && extraEvent[0] && extraEvent[0].id === selectedId ? extraEvent[0] : null;
    if (lookup && lookup.state === "found") selected = lookup.event;

    // Beside the details, keep the open row in sight. In one column the details
    // own the scroll position; the row is shown again when they close.
    useEffect(
      function () {
        if (selectedId) {
          if (!selectedInList || !sideBySide()) return;
          var row = document.getElementById("petasos-event-" + selectedId);
          if (row && !inView(row)) revealInView(row, "center");
          return;
        }
        var id = returnTo.current;
        returnTo.current = "";
        if (!id) return;
        var closed = document.getElementById("petasos-event-" + id);
        if (!closed) return;
        closed.focus({ preventScroll: true });
        if (!inView(closed)) revealInView(closed, "center");
      },
      [selectedId, selectedInList]
    );

    var tail = older.length ? older[older.length - 1] : page;
    var skipped = older.reduce(function (most, chunk) {
      return Math.max(most, chunk.skipped_lines || 0);
    }, page ? page.skipped_lines || 0 : 0);
    var skippedWords = (older.length ? "at least " : "") + plural(skipped, "line");
    var options = data && data.options;
    var counts = data && data.counts;
    var filtered = filters.kind || filters.tool || filters.session || filters.severity || filters.q || filters.outcome;
    var neverRecorded = options && options.total === 0 && options.complete !== false && !filtered && filters.range === "all";

    function open(event) {
      go("activity", Object.assign({}, params, { event: event.scan_id }));
    }
    function close() {
      returnTo.current = selectedId;
      var route = Object.assign({}, params);
      delete route.event;
      go("activity", route);
    }
    function reload(note) {
      olderState[1]({ key: filterKey, chunks: [] });
      olderFailureState[1](null);
      anchored.current = false;
      noteState[1](note || "");
      retryState[1](function (n) {
        return n + 1;
      });
    }
    function retry() {
      reload("");
    }

    var list;
    if ((!page && failure) || backwards || unreadableDate) {
      list = null;
    } else if (!page) {
      list = h("p", { className: "petasos-secondary", role: "status" }, "Loading activity…");
    } else if (!events.length && skipped) {
      list = h(
        Empty,
        { title: "No readable events" },
        plural(skipped, "line") + " of the record could not be read as events, so this page cannot say what " + (skipped === 1 ? "it holds" : "they hold") + "."
      );
    } else if (!events.length && neverRecorded) {
      list = h(
        Empty,
        {
          title: "Nothing recorded yet",
          action: h(Btn, { outlined: true, onClick: function () { go("tryit", { example: "notes" }); } }, "Try it"),
        },
        "Blocks, approval requests and warnings are recorded here. Clean actions are not."
      );
    } else if (!events.length && page.complete === false) {
      list = h(
        Empty,
        { title: "Nothing found in the part of the record that was read" },
        "The record is too large to read in full here, so older events were not searched."
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
              olderFailure
                ? h("p", { className: "petasos-field-error", role: "alert" }, "Older events could not be loaded. " + olderFailure.message + " The events above are unchanged.")
                : null,
              h(
                Btn,
                { outlined: true, onClick: loadOlder, disabled: loadingMore[0] },
                loadingMore[0] ? "Loading…" : olderFailure ? "Try loading older events again" : "Show older events"
              )
            )
          : tail && tail.complete === false
            ? h("p", { className: "petasos-secondary petasos-end" }, "Older events were not read.")
            : null
      );
    }

    // The badge speaks for every counted event, not only the page on screen.
    var listIntegrity = (counts && counts.integrity) || (page && page.integrity);
    var count = counts
      ? plural(counts.total, "event") +
        " · " +
        plural(counts.blocked || 0, "tool call") +
        " blocked" +
        (counts.complete === false ? " · counted in the part of the record that was read" : "")
      : "";

    return h(
      "div",
      { className: "petasos-stack petasos-activity" },
      h(ActivityFilters, {
        filters: filters,
        options: options,
        word: params.word,
        onChange: setFilters,
        onRangeInvalid: function (which, bad) {
          badDateState[1](function (held) {
            var next = Object.assign({}, held);
            next[which] = bad;
            return next;
          });
        },
      }),
      unreadableDate
        ? h(
            Notice,
            { tone: "warning", title: "A date in the time range cannot be read" },
            "Nothing is shown until it is fixed, because the list would be for a different range than the one typed."
          )
        : null,
      backwards
        ? h(Notice, { tone: "warning", title: "The time range ends before it starts" }, "Nothing was searched. Set From earlier than To.")
        : null,
      !page && failure
        ? h(
            Notice,
            {
              tone: "destructive",
              title: "The activity record could not be read",
              action: h(Btn, { onClick: retry }, "Try again"),
            },
            h("p", null, "Nothing is listed because the read failed, not because nothing happened."),
            h("p", { className: "petasos-tertiary" }, failure.message)
          )
        : null,
      page && failure
        ? h(
            Notice,
            {
              tone: "warning",
              title: "Could not refresh",
              action: h(Btn, { ghost: true, onClick: retry }, "Try again"),
            },
            "These events, counts and signatures were read at " + clockTime(data.readAt) + ". " + failure.message
          )
        : null,
      page && !unreadableDate
        ? h(
            "div",
            { className: "petasos-listbar" },
            h(
              "p",
              { className: "petasos-listbar-count", role: "status" },
              count && (!neverRecorded || skipped) ? h("span", { className: "petasos-count" }, count) : null,
              events.length ? h("span", { className: "petasos-secondary" }, " · Newest first · Times in " + timeZoneName()) : null,
              skipped
                ? h(
                    "span",
                    { className: "petasos-strong" },
                    " · " + skippedWords + " of the record could not be read and " + (skipped === 1 ? "is" : "are") + " not counted or verified"
                  )
                : null
            ),
            h(IntegrityStatus, {
              integrity: listIntegrity,
              open: limitState[0],
              onToggle: function () {
                limitState[1](!limitState[0]);
              },
            })
          )
        : null,
      listIntegrity && listIntegrity.limit && limitState[0]
        ? h("p", { className: "petasos-integrity-note", role: "status" }, listIntegrity.limit)
        : null,
      noteState[0] ? h(Notice, { tone: "info", title: "List reloaded" }, noteState[0]) : null,
      anchored.current && data
        ? h(
            "p",
            { className: "petasos-secondary", role: "status" },
            "Showing one reading from " + clockTime(data.readAt) + " so older pages stay in order. New events are not added. ",
            h(Btn, { ghost: true, compact: true, onClick: retry }, "Reload from the newest")
          )
        : null,
      page
        ? h(IntegrityNotice, {
            integrity: listIntegrity,
            signing: props.status.record_signing,
            secretSet: Boolean(props.status.secrets && props.status.secrets.session_secret === "set"),
          })
        : null,
      !list
        ? null
        : neverRecorded && !events.length && !skipped
          ? list
          : h(
              "div",
              { className: cn("petasos-split", (selected || lookup) && "petasos-split-open") },
              h("div", { className: "petasos-split-main" }, h(C.Card, { className: "petasos-panel petasos-list-card" }, list)),
              selected
                ? h(EventDetail, {
                    event: selected,
                    onClose: close,
                    onFilter: function (patch) {
                      setFilters(Object.assign({}, filters, patch));
                    },
                  })
                : lookup
                  ? h(
                      "aside",
                      { className: "petasos-detail", "aria-label": "Event details", role: "status" },
                      h(
                        "div",
                        { className: "petasos-detail-head" },
                        h("p", { className: "petasos-detail-which" }, "Event ", h(Ident, null, selectedId)),
                        h(Btn, { ghost: true, onClick: close, "aria-label": "Close event details" }, "Close")
                      ),
                      lookup.state === "loading"
                        ? h("p", { className: "petasos-secondary" }, "Loading this event…")
                        : lookup.state === "missing"
                          ? h("p", null, (lookup.failure && lookup.failure.message) || "That event was not found.")
                          : h(
                              Fragment,
                              null,
                              h("p", null, "This event could not be read. " + ((lookup.failure && lookup.failure.message) || "")),
                              h("div", { className: "petasos-row-actions" }, h(Btn, { onClick: function () { lookupState[1](lookupState[0] + 1); } }, "Try again"))
                            )
                    )
                  : null
            )
    );
  }
  // ===== dashboard-src/30-tryit.js =====

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
  // ===== dashboard-src/40-settings.js =====

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

  function differs(row) {
    return JSON.stringify(row.value === undefined ? null : row.value) !== JSON.stringify(row.default === undefined ? null : row.default);
  }

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

  // Hermes Config has no mapping-entry editor; schema labels name both fields.
  function MappingRows(props) {
    var row = props.row;
    var labels = row.entry_labels || ["Name", "Value"];
    var numeric = String(row.type).indexOf("float") >= 0;
    function fromValue(value) {
      var saved = props.savedValue || {};
      return Object.keys(value || {}).map(function (key) {
        return {
          key: key,
          value: value[key] === null || value[key] === undefined ? "" : String(value[key]),
          // Whether this row is an entry already saved, whatever is typed into other rows later.
          saved: Object.prototype.hasOwnProperty.call(saved, key),
        };
      });
    }
    var rowsState = useState(function () {
      return fromValue(props.value);
    });
    var entries = rowsState[0];
    var hasSaved = entries.some(function (entry) {
      return entry.saved;
    });
    var names = entries.map(function (entry) {
      return entry.key.trim();
    });
    var repeated = names.filter(function (name, index) {
      return name && names.indexOf(name) !== index;
    });
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
    // Outside changes reset rows; local edits retain their editing state.
    var incoming = JSON.stringify(props.value || {});
    useEffect(
      function () {
        if (JSON.stringify(toValue(entries)) !== incoming) rowsState[1](fromValue(props.value));
      },
      [incoming]
    );
    // Once a save lands, the rows it stored are saved entries.
    var savedNow = JSON.stringify(Object.keys(props.savedValue || {}).sort());
    useEffect(
      function () {
        var saved = props.savedValue || {};
        rowsState[1](function (held) {
          return held.map(function (entry) {
            return Object.prototype.hasOwnProperty.call(saved, entry.key.trim()) && !entry.saved ? Object.assign({}, entry, { saved: true }) : entry;
          });
        });
      },
      [savedNow]
    );
    function update(list) {
      rowsState[1](list);
      var seen = {};
      var clash = list.some(function (entry) {
        var name = entry.key.trim();
        if (!name) return false;
        if (seen[name]) return true;
        seen[name] = true;
        return false;
      });
      // Two rows with one name would silently become one entry: nothing is staged until they differ.
      if (props.onProblem) props.onProblem(clash ? "Two entries have the same name. Give each its own name." : null);
      if (clash) return;
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
            disabled: props.disabled || entry.saved,
            "aria-invalid": repeated.indexOf(entry.key.trim()) >= 0 ? "true" : undefined,
            "aria-label": labels[0] + " " + (index + 1),
            onChange: function (e) {
              var next = entries.slice();
              next[index] = { key: e.target.value, value: entry.value, saved: entry.saved };
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
              next[index] = { key: entry.key, value: e.target.value, saved: entry.saved };
              update(next);
            },
          }),
          entry.saved
            ? h("span", { className: "petasos-tertiary" }, "Saved")
            : h(
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
      repeated.length
        ? h(
            "p",
            { className: "petasos-field-error", role: "alert" },
            "Two entries are named “" + repeated[0] + "”. Give each entry its own name; until then this change is not staged."
          )
        : null,
      hasSaved
        ? h(
            "p",
            { className: "petasos-secondary" },
            "A saved entry can be changed, but not removed or renamed by itself. Reset, below, removes every saved entry of this setting; add back the ones to keep."
          )
        : null,
      h(
        "div",
        null,
        h(
          Btn,
          {
            outlined: true,
            disabled: props.disabled,
            onClick: function () {
              rowsState[1](entries.concat([{ key: "", value: "", saved: false }]));
            },
          },
          "Add"
        )
      )
    );
  }

  // Unparsed numbers stay text so the API can return its validation reason.
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
      return h(MappingRows, {
        row: row,
        value: props.value,
        savedValue: props.savedValue,
        disabled: props.disabled,
        describedBy: described,
        onValue: props.onValue,
        onProblem: props.onProblem,
      });
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
          sameValue(target.value, saved.value) ? "Use the inherited value" : "Reset to " + stateWords(row, target.value)
        );
      }
    }
    if (bounds && !props.error) parts.push("Allowed: " + bounds);
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
          savedValue: saved.origin === "override" ? saved.value : null,
          onProblem: props.onProblem,
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

  function ruleState(rows, rule, props) {
    var byPath = rowsByPath(rows);
    var suppress = byPath["rules.suppress"] || { value: [], origin: "default" };
    var severity = byPath["rules.severity_overrides"] || { value: {}, origin: "default" };
    var quiet = (Array.isArray(suppress.value) ? suppress.value : []).indexOf(rule) >= 0;
    var lowered = severity.value && severity.value[rule];
    return {
      suppress: Array.isArray(suppress.value) ? suppress.value : [],
      severity: severity.value || {},
      quiet: quiet,
      words: quiet
        ? "Turned off (" + originText(suppress.origin, props.stored, props.catalog).toLowerCase() + "). It does not block, is not recorded, and adds no risk."
        : lowered
          ? "Counts as " + lowered + " (" + originText(severity.origin, props.stored, props.catalog).toLowerCase() + ")."
          : "On, at its usual severity.",
    };
  }

  function RuleHelper(props) {
    var rule = props.rule;
    var saved = ruleState(props.savedRows, rule, props);
    var staged = ruleState(props.rows, rule, props);
    var changed = props.dirty && staged.words !== saved.words;
    // Each action is "loading", "allowed", "refused" or "unknown" (the question could not be asked).
    var askedState = useState({ rule: rule, quiet: "loading", lower: "loading" });
    var asked = askedState[0].rule === rule ? askedState[0] : { quiet: "loading", lower: "loading" };
    var retryState = useState(0);
    var lowerValue = Object.assign({}, staged.severity);
    lowerValue[rule] = "low";
    useEffect(
      function () {
        var live = true;
        askedState[1]({ rule: rule, quiet: "loading", lower: "loading" });
        function accepted(overrides) {
          if (props.draftInvalid) return Promise.resolve("blocked");
          var body = draftBody(mergeDraft(props.draft, { overrides: overrides }, knownPaths(props.savedRows)));
          return call("/settings/preview", { method: "POST", body: body }).then(
            function (body) {
              if (body.valid !== false) return "allowed";
              var aboutRules = (body.problems || []).some(function (problem) {
                return /(^|\.)rules\.(suppress|severity_overrides)/.test(String(problem.path || ""));
              });
              // Another unsaved change is what Petasos objects to; that says nothing about this rule.
              return aboutRules ? "refused" : "blocked";
            },
            function () {
              return "unknown";
            }
          );
        }
        Promise.all([
          staged.quiet ? Promise.resolve("allowed") : accepted({ rules: { suppress: staged.suppress.concat([rule]) } }),
          accepted({ rules: { severity_overrides: lowerValue } }),
        ]).then(function (answers) {
          if (live) askedState[1]({ rule: rule, quiet: answers[0], lower: answers[1] });
        });
        return function () {
          live = false;
        };
      },
      [rule, Boolean(props.draftInvalid), JSON.stringify(draftBody(props.draft)), JSON.stringify(staged.suppress), JSON.stringify(staged.severity), retryState[0]]
    );
    var refused = [];
    if (!staged.quiet && asked.quiet === "refused") refused.push("turned off");
    if (asked.lower === "refused") refused.push("set to report without blocking");
    var unknown = asked.quiet === "unknown" || asked.lower === "unknown";
    var blocked = asked.quiet === "blocked" || asked.lower === "blocked";
    var loading = asked.quiet === "loading" || asked.lower === "loading";
    var offered = (!staged.quiet && asked.quiet === "allowed") || asked.lower === "allowed";
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
          ["Saved", saved.words],
          changed ? ["With your unsaved changes", staged.words] : null,
        ],
      }),
      h(
        "div",
        { className: "petasos-row-actions" },
        staged.quiet || asked.quiet !== "allowed"
          ? null
          : h(Btn, { outlined: true, disabled: props.disabled, onClick: function () { props.onQuiet(rule); } }, "Turn this rule off"),
        asked.lower !== "allowed"
          ? null
          : h(Btn, { outlined: true, disabled: props.disabled, onClick: function () { props.onLower(rule); } }, "Report it without blocking"),
        h(
          LinkButton,
          {
            onClick: function () {
              var route = { rule: rule, sentence: props.sentence || "" };
              if (props.dirty && props.testable) route.settings = JSON.stringify(draftBody(props.draft));
              go("tryit", route);
            },
          },
          props.dirty && props.testable ? "Test your unsaved changes in Try it" : "Test it in Try it"
        )
      ),
      props.dirty && !props.testable
        ? h("p", { className: "petasos-secondary" }, "Try it would use the saved settings: your unsaved changes have not been checked yet, or need fixing.")
        : null,
      refused.length
        ? h("p", { className: "petasos-secondary", role: "status" }, "These settings do not let this rule be " + refused.join(" or ") + ".")
        : null,
      loading ? h("p", { className: "petasos-secondary", role: "status" }, "Checking what can be changed for this rule…") : null,
      blocked && !loading
        ? h(
            "p",
            { className: "petasos-secondary", role: "status" },
            "Another unsaved change needs fixing before Petasos can say what is allowed for this rule. Use “Go to it” in the bar above."
          )
        : null,
      unknown && !loading
        ? h(
            "p",
            { className: "petasos-secondary", role: "status" },
            "Petasos could not be asked what can be changed for this rule. ",
            h(Btn, { ghost: true, compact: true, onClick: function () { retryState[1](retryState[0] + 1); } }, "Try again")
          )
        : null,
      offered ? h("p", { className: "petasos-secondary" }, "Not saved until you press Save.") : null
    );
  }

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
          sharedApplies: draft.enabled === false ? "" : (preview && preview.applies) || "",
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
    // A preview is kept with the draft it describes; only a matching one may be reviewed or saved.
    var previewState = useState(null);
    var preview = previewState[0] ? previewState[0].body : null;
    var previewRetryState = useState(0);
    var saveErrorState = useState(null);
    var focusPathState = useState(null);
    var discardedState = useState(null);
    var savedState = useState(null);
    var expertState = useState(false);
    var searchState = useState("");
    var sectionState = useState(
      params.changed ? "changed" : params.section ? params.section : params.rule ? "rules" : params.path ? topOf({ path: params.path }) || "general" : "basics"
    );
    var section = sectionState[0];
    var resetState = useState(null);
    var reviewState = useState(params.review === "1");
    var reviewing = reviewState[0];
    var toolbarRef = useRef(null);
    var lastReset = useRef(null);
    // After a reset the Reset control is gone, so focus goes to the setting it belonged to.
    var rememberResetOpener = useReturnFocus(Boolean(resetState[0]), function () {
      var path = lastReset.current;
      return path && path !== "*" && document.getElementById(fieldId(path)) ? fieldId(path) : "petasos-settings-search";
    });

    var empty = draftIsEmpty(draft);
    // The draft and the saved settings it would change: a preview describes exactly this pair.
    var draftKey = JSON.stringify([draftBody(draft), catalog && catalog.stored]);

    useEffect(
      function () {
        if (empty) {
          previewState[1](null);
          reviewState[1](false);
          return;
        }
        var live = true;
        var key = draftKey;
        var timer = window.setTimeout(function () {
          call("/settings/preview", { method: "POST", body: draftBody(draft) })
            .then(function (body) {
              if (live) previewState[1]({ key: key, body: body });
            })
            .catch(function (failure) {
              if (live) previewState[1]({ key: key, failed: failure, body: preview });
            });
        }, 250);
        return function () {
          live = false;
          window.clearTimeout(timer);
        };
      },
      [draftKey, previewRetryState[0]]
    );
    var previewCurrent = Boolean(previewState[0] && previewState[0].key === draftKey && !previewState[0].failed && previewState[0].body);
    var previewFailed = previewState[0] && previewState[0].key === draftKey ? previewState[0].failed : null;

    useEffect(
      function () {
        if (params.path) sectionState[1](topOf({ path: params.path }) || "general");
      },
      [params.path]
    );
    // Typed text is kept only for settings that are still staged or still wrong.
    useEffect(
      function () {
        setTexts(function (held) {
          var kept = {};
          Object.keys(held).forEach(function (path) {
            if (hasIn(draft.overrides, path) || localErrorsState[0][path]) kept[path] = held[path];
          });
          return Object.keys(kept).length === Object.keys(held).length ? held : kept;
        });
      },
      [draftKey]
    );
    // "Fix the marked setting": open its section, then put focus on it.
    useEffect(
      function () {
        var path = focusPathState[0];
        if (!path) return;
        var field = document.getElementById(fieldId(path));
        if (!field) return;
        focusPathState[1](null);
        revealInView(field, "center");
        field.focus({ preventScroll: true });
      },
      [focusPathState[0], section]
    );
    useEffect(
      function () {
        if (!params.path) return;
        var target = document.getElementById("petasos-row-" + params.path);
        if (target) revealInView(target, "center");
      },
      [params.path, section, Boolean(catalog)]
    );

    if (props.pending) {
      // The notice above this view explains the unconfirmed change and offers Check again.
      return h(
        Panel,
        { title: "Settings" },
        h(
          "p",
          { role: "status" },
          "Settings are not shown while a change is unconfirmed: what this page last read may no longer be what is saved. Use Check again, above."
        ),
        empty ? null : h("p", { className: "petasos-secondary" }, "Your unsaved changes are kept.")
      );
    }
    if (!catalog && props.catalogFailure) {
      return h(
        Panel,
        { title: "Settings" },
        h(
          Notice,
          {
            tone: "destructive",
            title: "The settings could not be loaded",
            action: h(Btn, { onClick: props.onRetryCatalog }, "Try again"),
          },
          h("p", null, props.catalogFailure.message),
          empty ? null : h("p", null, "Your unsaved changes are kept.")
        )
      );
    }
    if (!catalog) {
      return h(Panel, { title: "Settings" }, h("p", { className: "petasos-help", role: "status" }, "Loading settings…"));
    }

    var savedRows = catalog.settings || [];
    // Until a preview of this exact draft arrives, a staged value is shown as typed and nothing derived from it is.
    var rows =
      previewCurrent && preview.settings && preview.valid
        ? preview.settings
        : savedRows.map(function (row) {
            if (!hasIn(draft.overrides, row.path)) return row;
            return Object.assign({}, row, { value: getIn(draft.overrides, row.path), origin: "override" });
          });
    var savedBy = rowsByPath(savedRows);
    var changeBy = {};
    ((previewCurrent && preview.changes) || []).forEach(function (change) {
      changeBy[change.path] = change;
    });
    var problems = {};
    ((previewCurrent && preview.problems) || []).forEach(function (problem) {
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
      discardedState[1](null);
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
      discardedState[1](null);
      var next = clone(draft);
      if (value === stored[key] && !props.saving) delete next[key];
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
      discardedState[1]({ draft: draft, count: staged });
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
    var DRAFT_NOTES = {
      unknown: "Your draft is still here. Refresh to check what is saved before you save again.",
      other: "Your changes are still here, not saved.",
    };
    // Only what was sent is cleared: an edit made while the save was in flight stays staged.
    function save() {
      if (props.saving || !previewCurrent) return;
      var sent = clone(draftBody(draft));
      saveErrorState[1](null);
      props
        .onWrite(
          function () {
            return writeSettings(sent, preview && preview.applies);
          },
          "Save settings",
          DRAFT_NOTES,
          sent
        )
        .then(function (result) {
          afterWrite(result.settings, result.message);
        })
        .catch(function (failure) {
          if (failure.path) saveErrorState[1](failure);
          reviewState[1](false);
          if (toolbarRef.current) revealInView(toolbarRef.current, "start");
        });
    }
    function reset(path) {
      if (props.saving) return;
      var row = path === "*" ? null : savedBy[path];
      props
        .onWrite(
          function () {
            return resetSettings(path);
          },
          path === "*" ? "Reset every setting you set" : "Reset " + rowLabel(row || { path: path })
        )
        .then(function (result) {
          afterWrite(result.settings, result.message);
        })
        .catch(function () {})
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

    function pickSection(key) {
      searchState[1]("");
      sectionState[1](key);
      if (key === "changed") go("settings", { changed: "1" });
      else if (params.changed) go("settings", { section: key });
    }
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
      var consequences = (previewCurrent && preview.valid && preview.consequences) || (empty ? catalog.consequences : null) || {};
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
        onProblem: function (message) {
          localErrorsState[1](function (held) {
            if ((held[row.path] || null) === message) return held;
            var next = Object.assign({}, held);
            if (message) next[row.path] = message;
            else delete next[row.path];
            return next;
          });
        },
        onReset: function () {
          rememberResetOpener();
          lastReset.current = row.path;
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
          [
            "Session secret",
            secrets.session_secret !== "set"
              ? "Not set. Activity records are not signed."
              : props.status.record_signing && props.status.record_signing.signed
                ? "Set and usable. New activity records are signed; Activity shows whether each one still matches."
                : "Set, but Petasos cannot make a signing key from it, so records are not signed. Running hermes petasos doctor says what is wrong with it.",
          ],
          ["Hash key", secrets.hash_key === "set" ? "Set." : "Not set. Only needed to hide personal details as fingerprints."],
        ],
      }),
      h("p", { className: "petasos-help" }, "The session secret and hash key live in the profile's .env file and are never shown here."),
      overrideCount && !lockedAll
        ? h(
            "div",
            { className: "petasos-row-actions" },
            h(Btn, { outlined: true, onClick: function () { rememberResetOpener(); lastReset.current = "*"; resetState[1]("*"); } }, "Reset all " + plural(overrideCount, "setting") + " you set")
          )
        : null
    );

    var changeCount = previewCurrent && preview.changes ? preview.changes.length : 0;
    var topChanges = ["enabled", "role", "level"].filter(function (key) {
      return draft[key] !== undefined && draft[key] !== stored[key];
    }).length;
    var invalid = (previewCurrent && preview.valid === false) || Object.keys(localErrorsState[0]).length > 0;
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
          : previewFailed
            ? h(
                "span",
                { className: "petasos-secondary petasos-strong", role: "status" },
                "These changes could not be checked. ",
                h(Btn, { ghost: true, compact: true, onClick: function () { previewRetryState[1](previewRetryState[0] + 1); } }, "Try again")
              )
            : invalid
            ? h(
                "span",
                { className: "petasos-secondary petasos-strong", role: "status" },
                "A setting needs fixing before you can save. ",
                h(
                  Btn,
                  {
                    ghost: true,
                    compact: true,
                    onClick: function () {
                      var path = Object.keys(problems)[0];
                      if (!path) return;
                      searchState[1]("");
                      sectionState[1](topOf({ path: path }) || "general");
                      focusPathState[1](path);
                    },
                  },
                  "Go to it"
                )
              )
            : previewCurrent
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
              : h("span", { className: "petasos-secondary", role: "status" }, "Checking changes…"),
        empty
          ? null
          : h(
              Btn,
              {
                outlined: true,
                onClick: discard,
                disabled: props.saving,
                title: props.saving ? "Wait for the save in progress to finish" : undefined,
                "aria-label": "Discard all " + plural(staged, "unsaved change"),
              },
              "Discard all"
            ),
        empty
          ? null
          : h(
              Btn,
              {
                outlined: true,
                disabled: invalid || !previewCurrent,
                title: invalid ? "Fix the marked setting first" : undefined,
                onClick: function () {
                  go("tryit", { settings: JSON.stringify(draftBody(draft)) });
                },
              },
              "Try it first"
            ),
        h(
          Btn,
          {
            disabled: empty || invalid || !previewCurrent || lockedAll || props.saving,
            onClick: save,
          },
          props.saving ? "Saving…" : "Save"
        )
      )
    );
    var sheet =
      reviewing && previewCurrent && !invalid && !empty
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
      discardedState[0] && empty
        ? h(
            Notice,
            {
              tone: "info",
              title: "Discarded " + plural(discardedState[0].count, "unsaved change"),
              action: h(
                Btn,
                {
                  outlined: true,
                  onClick: function () {
                    setDraft(discardedState[0].draft);
                    discardedState[1](null);
                  },
                },
                "Undo"
              ),
            },
            "Nothing was saved. Undo puts the changes back as they were."
          )
        : null,
      props.catalogFailure
        ? h(
            Notice,
            {
              tone: "warning",
              title: "The settings could not be re-read",
              action: h(Btn, { ghost: true, onClick: props.onRetryCatalog }, "Try again"),
            },
            "The saved values shown here were read at " + (props.catalogReadAt ? clockTime(props.catalogReadAt) : "an earlier time") + " and may have changed since. " + props.catalogFailure.message
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
      params.rule
        ? h(RuleHelper, {
            catalog: catalog,
            rule: params.rule,
            rows: rows,
            savedRows: savedRows,
            dirty: !empty,
            draft: draft,
            draftInvalid: invalid,
            testable: previewCurrent && !invalid,
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
        h(Choice, {
          id: "petasos-section-pick",
          className: "petasos-section-pick",
          label: "Section",
          value: search ? "" : section,
          placeholder: "Search results",
          options: navItems.map(function (item) {
            return { value: item.key, label: item.label + " (" + item.count + ")" + (item.changed ? " · changed" : "") };
          }),
          onChange: pickSection,
        }),
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
                  pickSection(item.key);
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
                  ? groups.map(function (group, index) {
                      var sub = group.section !== activeTop && group.section;
                      var info = sub ? sections[group.section] || {} : null;
                      // A section's rows can resume after a nested group, so its name alone is not a unique key.
                      return h(
                        "div",
                        { key: (group.section || "root") + ":" + index, className: "petasos-group" },
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
                (sameValue(resetRow.value, resetRow.reset_to.value)
                  ? "stays " +
                    showValue(resetRow.value, resetRow) +
                    " for now, and from then on follows " +
                    originText(resetRow.reset_to.origin, stored, catalog).toLowerCase() +
                    " instead of your setting"
                  : showValue(resetRow.value, resetRow) +
                    " becomes " +
                    showValue(resetRow.reset_to.value, resetRow) +
                    " (" +
                    originText(resetRow.reset_to.origin, stored, catalog).toLowerCase() +
                    ")") +
                ". This saves now. " +
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
          ? "Turn Petasos on in Plugins, then restart the dashboard. Until this page loads, it cannot confirm whether tool calls are being checked."
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

  // Hermes rewrites root colour variables when the theme changes.
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

  // What the page says about protection while a change is unconfirmed: the last
  // state it read is history, not the present.
  function unconfirmed(verdict, pending) {
    return {
      code: "unconfirmed",
      tone: "warning",
      word: "Unconfirmed",
      title: "Petasos did not confirm the last change",
      reason:
        "This page cannot tell whether “" +
        pending.what +
        "” took effect. The last state it read was “" +
        verdict.word +
        "”, which may no longer be true.",
    };
  }

  // A change was saved, but the status could not be read afterwards. What the
  // save itself settled (paused or not) is stated; nothing from the earlier
  // reading is repeated as current.
  function sinceSaved(status, catalog) {
    var enabled = !catalog || !catalog.stored || catalog.stored.enabled !== false;
    var wasPaused = Boolean(status.paused || (status.switches && status.switches.petasos && status.switches.petasos.on === false));
    if (!enabled) {
      return {
        code: "paused",
        tone: "warning",
        word: "Paused",
        title: "Pause is saved",
        reason: "Actions run unchecked. This page has not been able to read what Hermes is running or recording since the change.",
      };
    }
    return {
      code: "saved",
      tone: "warning",
      word: "Saved, not re-read",
      title: wasPaused ? "Resume is saved; the running state is unconfirmed" : "Settings saved; the running state is unconfirmed",
      reason: "This page has not been able to read what Hermes is running since the change.",
    };
  }

  // Any other write in flight: the reading on screen is from before it, and says so.
  function savingOver(verdict, readAt) {
    return {
      code: "saving",
      was: verdict.code,
      tone: "warning",
      word: "Saving…",
      title: "Saving a change…",
      reason: "Before it, this page read “" + verdict.title + "”" + (readAt ? " at " + clockTime(readAt) : "") + ".",
    };
  }

  // Pause or Resume has been sent and not yet answered: neither the old state nor the new one is claimed.
  function changing(what) {
    var pausing = what === "Pause protection";
    return {
      code: "changing",
      tone: "warning",
      word: pausing ? "Pausing…" : "Resuming…",
      title: pausing ? "Pausing protection…" : "Turning protection back on…",
      reason: "Waiting for Petasos to confirm.",
    };
  }

  // Pause or Resume, whichever control sent it, is read from the value being written.
  function changeOf(payload, catalog) {
    if (!payload || typeof payload.enabled !== "boolean") return null;
    var enabled = !catalog || !catalog.stored || catalog.stored.enabled !== false;
    if (payload.enabled === enabled) return null;
    return payload.enabled ? "Resume protection" : "Pause protection";
  }

  // The status could not be re-read on the last attempt: what is shown is the
  // reading before it, named as such.
  function lastKnown(verdict, readAt) {
    return {
      code: "lastknown",
      tone: "warning",
      word: verdict.word + (readAt ? ", as of " + clock24(new Date(readAt)) : ", earlier"),
      title: "The last check failed",
      reason:
        "“" + verdict.title + "” is what this page read" + (readAt ? " at " + clockTime(readAt) : " earlier") + ". It has not been able to read the state since.",
    };
  }

  // The one rule for every view: the status is shown as current only when it was
  // read after the last write settled and the last attempt to read it succeeded.
  // `flags`: changing (a Pause or Resume in flight), saving (any write in flight),
  // pending (a write with an unknown outcome), stale (saved, status not re-read),
  // failed (the last status read failed), readAt.
  function protectionView(status, catalog, flags) {
    var verdict = verdictOf(status);
    var shown = verdict;
    if (flags.changing) shown = changing(flags.changing);
    else if (flags.saving) shown = savingOver(verdict, flags.readAt);
    else if (flags.pending) shown = unconfirmed(verdict, flags.pending);
    else if (flags.stale) shown = sinceSaved(status, catalog);
    else if (flags.failed) shown = lastKnown(verdict, flags.readAt);
    return {
      verdict: shown,
      // Coverage, per-check states and anything else derived from the status reading.
      current: !flags.changing && !flags.saving && !flags.pending && !flags.stale && !flags.failed,
      waiting: Boolean(flags.saving || flags.changing),
    };
  }

  function PetasosTab() {
    var route = useRoute();
    var light = useLightTheme();
    var statusState = useState(null);
    var status = statusState[0];
    var failureState = useState(null);
    var catalogState = useState(null);
    var catalog = catalogState[0];
    var catalogFailureState = useState(null);
    var checkedState = useState(null);
    var refreshState = useState(0);
    var lockedState = useState(null);
    var pauseState = useState(false);
    // Staged settings outlive view changes.
    var draftState = useState(EMPTY_DRAFT);
    var draft = draftState[0];
    // The profile whose draft is loaded; null until the first status read names it.
    var draftHome = useRef(null);
    var catalogReadState = useState(null);
    // The name of the write in flight, or null.
    var savingState = useState(null);
    var problemState = useState(null);
    // Set when a write was saved but the status read that follows it failed; cleared by the next status read.
    var staleState = useState(null);
    // "Pause protection" or "Resume protection" while a write that changes it is in flight, whichever view sent it.
    var changingState = useState(null);
    // A write whose outcome is unknown, until both reads succeed again.
    var pendingState = useState(null);
    var pendingRef = useRef(null);
    var checkingState = useState(false);
    var toast = SDK.hooks.useToast();
    var rememberPauseOpener = useReturnFocus(pauseState[0], "petasos-protection-action");
    var beginStatus = useLatest();
    var beginCatalog = useLatest();

    function readStatus() {
      var latest = beginStatus();
      return call("/status").then(
        function (body) {
          if (!latest()) return false;
          statusState[1](body);
          failureState[1](null);
          checkedState[1](Date.now());
          staleState[1](null);
          return true;
        },
        function (failure) {
          if (latest()) failureState[1](failure);
          return false;
        }
      );
    }
    function readCatalog() {
      var latest = beginCatalog();
      return call("/settings").then(
        function (body) {
          if (!latest()) return false;
          catalogState[1](body);
          catalogFailureState[1](null);
          catalogReadState[1](Date.now());
          return true;
        },
        function (failure) {
          if (latest()) catalogFailureState[1](failure);
          return false;
        }
      );
    }
    // Both reads, started now. Only this clears an unconfirmed change.
    function reconcile() {
      checkingState[1](true);
      refreshState[1](function (n) {
        return n + 1;
      });
      return Promise.all([readStatus(), readCatalog()]).then(function (read) {
        checkingState[1](false);
        if (!read[0] || !read[1]) return false;
        pendingRef.current = null;
        pendingState[1](null);
        problemState[1](function (problem) {
          return problem && problem.outcome === "unknown" ? null : problem;
        });
        return true;
      });
    }

    usePoll(
      function () {
        return pendingRef.current ? reconcile() : readStatus();
      },
      20000,
      []
    );
    useEffect(function () {
      readCatalog();
    }, []);

    var dirty = !draftIsEmpty(draft);
    var home = status ? status.home || "" : null;
    useEffect(
      function () {
        if (home === null || draftHome.current === home) return;
        draftHome.current = home;
        draftState[1](readDraft(home));
      },
      [home]
    );
    useEffect(
      function () {
        if (draftHome.current !== null) writeDraft(draft, draftHome.current);
      },
      [draft]
    );
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

    // Settings a write returned replace the catalog; the status is then read
    // again, and the promise says whether that read succeeded.
    function onSaved(body) {
      if (body && body.settings) {
        beginCatalog();
        catalogState[1](body);
        catalogFailureState[1](null);
        catalogReadState[1](Date.now());
      } else {
        readCatalog();
      }
      refreshState[1](function (n) {
        return n + 1;
      });
      return readStatus();
    }

    // Every write goes through here, one at a time. `run` performs it; `what`
    // names it for the person. A refusal tied to one field is left to the caller.
    // `sent`, when given, is the draft body this write carries: once saved, those
    // values leave the draft, and anything staged since stays.
    function write(run, what, notes, sent, payload) {
      if (savingState[0]) return Promise.reject(new ApiFailure(0, "busy", "The last change is still being saved.", null));
      savingState[1](what || "Save");
      changingState[1](changeOf(sent || payload, catalog));
      return run()
        .then(function (result) {
          problemState[1](null);
          if (sent) {
            var known = knownPaths(result.settings && result.settings.settings);
            draftState[1](function (held) {
              return draftAfterSave(held, sent, known);
            });
          }
          // The write stays in flight until the status has been read again, so
          // the reading from before it is never shown as current.
          var readAt = checkedState[0];
          return onSaved(result.settings).then(function (read) {
            if (!read) staleState[1]({ readAt: readAt });
            return result;
          });
        })
        .catch(function (failure) {
          failure.what = what;
          failure.note = notes ? (failure.outcome === "unknown" ? notes.unknown : notes.other) || "" : "";
          if (failure.code === "managed") lockedState[1](failure.message);
          if (failure.outcome === "unknown") {
            pendingRef.current = { what: what };
            pendingState[1](pendingRef.current);
          }
          // The reason stays on the page until dismissed; a toast would vanish with it.
          if (!failure.path) problemState[1](failure);
          if (failure.settings) onSaved(failure.settings);
          throw failure;
        })
        .finally(function () {
          savingState[1](null);
          changingState[1](null);
        });
    }

    function save(body, what, applies) {
      return write(
        function () {
          return writeSettings(body, applies);
        },
        what,
        null,
        null,
        body
      ).then(function (result) {
        toast.showToast(result.message, "success");
        return result;
      });
    }

    function stage(candidate) {
      var known = knownPaths(catalog && catalog.settings);
      draftState[1](function (held) {
        return mergeDraft(held, candidate, known);
      });
    }

    if (status) startProfile = status.home || "";
    var view = route.view;
    var locked = Boolean(lockedState[0]);
    var pending = pendingState[0];
    var stale = !pending && staleState[0] && status ? staleState[0] : null;
    var view_ = status
      ? protectionView(status, catalog, {
          changing: changingState[0],
          saving: Boolean(savingState[0]),
          pending: pending,
          stale: stale,
          failed: Boolean(failureState[0]),
          readAt: checkedState[0],
        })
      : null;
    var body;
    if (!status && failureState[0]) {
      body = h(Unreachable, { failure: failureState[0], onRetry: reconcile });
    } else if (!status) {
      body = h("p", { className: "petasos-help", role: "status" }, "Loading Petasos…");
    } else {
      var shared = {
        route: route,
        status: status,
        catalog: catalog,
        catalogFailure: catalogFailureState[0],
        catalogReadAt: catalogReadState[0],
        onRetryCatalog: readCatalog,
        refreshKey: refreshState[0],
        locked: locked,
        lockedMessage: lockedState[0],
        onSave: save,
        onWrite: write,
        saving: Boolean(savingState[0]),
        savingWhat: savingState[0],
        pending: pending,
        stale: stale,
        verdict: view_.verdict,
        detailsCurrent: view_.current,
        waiting: view_.waiting,
        checking: checkingState[0],
        onCheck: reconcile,
      };
      if (view === "activity") body = h(Activity, shared);
      // Each linked candidate or example requires fresh Try it and Settings state.
      else if (view === "tryit")
        body = h(
          TryIt,
          Object.assign(
            { key: (route.params.example || "") + "|" + (route.params.settings || "") + "|" + (route.params.rule || ""), draft: draft, onStage: stage },
            shared
          )
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
              rememberPauseOpener();
              pauseState[1](true);
            },
            onResume: function () {
              save({ enabled: true }, "Resume protection").catch(function () {});
            },
          })
        );
    }

    var verdict = view_ ? view_.verdict : null;
    var paused = Boolean(verdict && verdict.code === "paused");
    // An unconfirmed change is explained once, by the notice or panel that offers Check again.
    var problem = problemState[0] && !(pending && problemState[0].outcome === "unknown") ? problemState[0] : null;
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
          verdict && view !== "overview"
            ? h(
                "button",
                {
                  type: "button",
                  className: "petasos-statechip",
                  "aria-label": "Protection: " + verdict.word + ". Open Overview.",
                  onClick: function () {
                    go("overview");
                  },
                },
                h("span", { className: "petasos-statechip-label", "aria-hidden": true }, "Protection"),
                h(Status, { tone: verdict.tone, state: verdict.code }, verdict.word)
              )
            : null,
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
          status && status.petasos_version ? h("span", { className: "petasos-help petasos-version" }, "Petasos " + status.petasos_version) : null,
          checkedState[0] ? h("span", { className: "petasos-help" }, "Checked " + whenText(checkedState[0] / 1000)) : null,
          h(Btn, { ghost: true, onClick: reconcile, "aria-label": "Refresh now" }, "Refresh")
        )
      ),
      problem
        ? h(
            Notice,
            {
              tone: problem.outcome === "unknown" ? "warning" : "destructive",
              title:
                (problem.what ? problem.what + ": " : "") +
                (problem.outcome === "unknown" ? "not confirmed" : problem.outcome === "not_saved" ? "not there when read back" : "not saved"),
              action: h(Btn, { ghost: true, onClick: function () { problemState[1](null); } }, "Dismiss"),
            },
            h("p", null, problem.message),
            problem.note ? h("p", null, problem.note) : null
          )
        : null,
      pending && view !== "overview"
        ? h(
            Notice,
            {
              tone: "warning",
              title: "Protection state not confirmed",
              action: h(Btn, { onClick: reconcile, disabled: checkingState[0] }, checkingState[0] ? "Checking…" : "Check again"),
            },
            verdict.reason
          )
        : paused && view !== "overview"
          ? h(
              Notice,
              {
                tone: "warning",
                title: "Protection is paused",
                action: h(
                  Btn,
                  {
                    onClick: function () {
                      save({ enabled: true }, "Resume protection").catch(function () {});
                    },
                    disabled: locked || Boolean(savingState[0]),
                  },
                  savingState[0] === "Resume protection" ? "Resuming…" : "Resume"
                ),
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
          save({ enabled: false }, "Pause protection").catch(function () {});
        },
      })
    );
  }

  PLUGINS.register("petasos", PetasosTab);
})();
