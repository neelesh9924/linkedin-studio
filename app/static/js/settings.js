// Settings (Claude and who it is signed in as, publishing, ChatGPT, appearance, the health checks, recent runs,
// quitting) and the setup screen (the three folders: found on this PC, Browse…, or pasted, each login folder with the
// account it is signed in to; Save checks them, writes config.local.toml and restarts).
// Each panel has an address, #~settings-<id>: the jump links at the top use it, and it opens with that panel's heading
// focused. The focus stays where it was through every redraw (data-keep), and a health check says how it ended.
import { state, h, icon, api, post, put, number, announce, whileBusy, focusFirst, go } from "./core.js";
import { setTheme } from "./sidebar.js";

let box = null;
let polling = 0;
const PANELS = [["claude", "Claude"], ["publishing", "Publishing"], ["chatgpt", "ChatGPT"], ["appearance", "Appearance"],
  ["health", "Health checks"], ["runs", "Recent runs"], ["app", "The app"]];
const CHECKS = { check_config: "Connections", selftest: "Full self-test" };
const running = {};       // check -> running at the last draw, so its end is said once

export async function render(container, { page, sub } = {}) {
  box = container;
  clearTimeout(polling);
  put(box, h("p", { class: "lede" }, "Loading…"));
  if (page === "setup") return setup();
  await settings();
  if (sub) jumpTo(sub);
}

// A panel by its id: scrolled to, its heading focused (a screen reader then reads where it landed).
function jumpTo(id) {
  const panel = box && PANELS.some(([key]) => key === id) ? box.querySelector(`#settings-${id}`) : null;
  if (!panel) return;
  panel.scrollIntoView({ block: "start" });
  focusFirst(panel.querySelector("h2"));
}

const planOf = (s) => (s && s.plan ? ` (${s.plan[0].toUpperCase()}${s.plan.slice(1)})` : "");
const accountWords = (s) => (!s ? "" : s.ok ? `signed in as ${s.account || "an account with no email"}${planOf(s)}`
  : s.signed_in === false ? "not signed in" : "who is signed in could not be read");

export async function refresh() {
  if (state.page === "settings" && box) await settings(true);
}

function section(id, glyph, title, lede, ...body) {
  return h("section", { class: "panel", id: `settings-${id}`, "aria-labelledby": `settings-${id}-title` },
    h("header", { class: "panel-head" }, h("span", { class: "panel-mark" }, icon(glyph, 17)),
      h("div", null, h("h2", { id: `settings-${id}-title` }, title), lede ? h("p", null, lede) : null)),
    h("div", { class: "panel-body" }, ...body));
}

const facts = (...pairs) => h("dl", { class: "facts" }, pairs.filter(Boolean).map(([k, v]) => [h("dt", null, k), h("dd", null, v)]));
const note = (kind, ...lines) => h("div", { class: `result ${kind}` }, icon(kind === "ok" ? "check" : kind === "soft" ? "info" : "alert", 15),
  h("div", null, lines.filter(Boolean).map((l) => h("div", null, l))));
const OUTCOME = { ok: ["Done", "ok"], unparsed: ["Unreadable reply", "warn"], error: ["Failed", "bad"], timeout: ["Timed out", "bad"],
  cancelled: ["Stopped", "warn"], refused: ["Refused", "bad"] };

let last = "";
async function settings(quiet = false) {
  const [data, codex] = await Promise.all([api("/api/settings"), api("/api/codex")]);
  if (data.error || state.page !== "settings") return;
  for (const [name, title] of Object.entries(CHECKS)) {        // a check that was running has ended: say how
    const check = data.checks[name];
    if (running[name] && !check.running && check.row) {
      announce(check.row.ok ? `${title}: all good` : `${title} found a problem: see What it reported`, { urgent: !check.row.ok });
    }
    running[name] = check.running;
  }
  const key = JSON.stringify([data, codex]);
  if (quiet && key === last) return;
  last = key;
  const on = box.contains(document.activeElement) ? document.activeElement.dataset.keep : null;
  const c = data.claude;
  const theme = h("div", { class: "segmented", role: "group", "aria-label": "Theme" }, [["auto", "Match Windows"], ["light", "Light"], ["dark", "Dark"]].map(([value, label]) => {
    const b = h("button", { class: "btn small", type: "button", "aria-pressed": String(window.studioTheme.get() === value), "data-keep": `theme-${value}` }, label);
    b.addEventListener("click", () => {
      setTheme(value);
      theme.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    });
    return b;
  }));
  const quit = h("button", { class: "btn danger", type: "button", "data-keep": "quit" }, icon("power", 15), h("span", null, "Quit LinkedIn Studio"));
  quit.addEventListener("click", () => whileBusy(quit, async () => {
    await post("/api/quit", {});
    put(document.body, h("main", { class: "stopped" }, h("div", { class: "panel stopped-card" }, h("h1", null, "LinkedIn Studio has stopped"),
      h("p", null, "Your posts are saved. This window closes by itself in a moment; if it stays, close it."))));
  }));
  const sign = c.sign_in || {};
  const version = (c.version.match(/\d+(?:\.\d+)+/) || [""])[0];
  const signedNote = !c.ready ? note("bad", `Not found: ${c.version}`)
    : sign.ok ? note("ok", `Claude Code ${version}, ${accountWords(sign)}`)
      : note(sign.signed_in === false ? "bad" : "warn", sign.error || "Who is signed in could not be read.", `Claude Code ${version}`);
  const check = h("button", { class: "btn small", type: "button", "data-keep": "sign-in",
    title: "Asks Claude Code who this login folder is signed in to. It sends Claude no request." }, icon("refresh", 14), h("span", null, "Check the sign-in"));
  check.addEventListener("click", () => whileBusy(check, async () => {
    const reply = await post("/api/settings/claude/check", {});
    if (reply.error) return announce(reply.error, { urgent: true });
    const s = reply.sign_in;
    announce(s.ok ? `Claude Code is ${accountWords(s)}.` : s.error, { urgent: !s.ok });
    await settings(true);
  }));
  const jump = h("nav", { class: "jump", "aria-label": "On this page" }, PANELS.map(([id, label]) => h("a", { href: `#~settings-${id}`,
    onclick: (event) => {
      event.preventDefault();
      history.replaceState(null, "", `#~settings-${id}`);
      jumpTo(id);
    } }, label)));
  put(box, h("div", { class: "settings" },
    jump,
    data.problems.map((p) => h("div", { class: "notice bad" }, icon("alert", 16), h("div", null, p))),
    section("claude", "sparkle", "Claude", "Every run uses the login in the folder below, whatever started the app.",
      signedNote,
      facts(["Login folder", h("code", null, c.login)], ["Model", c.model], ["Per run", `up to ${c.turns} turns and ${c.seconds} seconds`],
        ["Ask Claude", `up to ${c.chat_turns} turns and ${c.chat_seconds} seconds a request`], ["Program", h("code", null, c.program)],
        ["Skills", h("code", null, c.skills)]),
      h("div", { class: "form-foot" }, check, h("button", { class: "btn small", type: "button", "data-keep": "folders", onclick: () => go("#~setup") },
        icon("folder", 14), h("span", null, "Change folders")))),
    section("publishing", "plane", "Publishing", "Keys live in linkedin-skills\\.env. The app reads them and never shows them.",
      facts(["Publora key", data.publora.key ? "Set" : "Missing"],
        ["LinkedIn channel", data.publora.platform_id ? "Set" : "Worked out from the key when you schedule"],
        ["Apify token", data.publora.apify ? "Set: post links can be fetched" : "Not set: paste post text instead of links"],
        ["Story Bank & voice", data.protection.ok ? "Kept out of git" : `Not protected: ${data.protection.detail}`],
        ["Monthly limit", `${data.limit} posts`], ["Times shown in", `${data.timezone} (${data.tz})`])),
    chatgpt(codex),
    section("appearance", "moon", "Appearance", "Match Windows follows its light or dark setting.", theme),
    section("health", "activity", "Health checks", "The skills repo’s own scripts, run with this app’s Python.",
      health("check_config", "Connections", "Checks the Publora, Apify and Pixfaro keys against free endpoints. Shows key prefixes, never keys.", data.checks.check_config),
      health("selftest", "Full self-test", "Install, tests and coverage, offline. Takes a few minutes, and regenerates linkedin-skills\\.codex-marketplace (normally to identical files).", data.checks.selftest)),
    section("runs", "list", "Recent runs", `Every Claude run and how long it took. Stored in ${data.data_dir}.`,
      data.runs.length ? h("div", { class: "table-scroll" }, h("table", { class: "table" },
        h("thead", null, h("tr", null, ["When", "What", "Result", "Took", "Turns", "Tokens in / out"].map((t) => h("th", null, t)))),
        h("tbody", null, data.runs.map((r) => {
          const [word, kind] = OUTCOME[r.outcome] || [r.outcome, ""];
          return h("tr", null, h("td", null, r.when), h("td", null, r.what, h("small", null, r.skill)),
            h("td", null, h("span", { class: `chip ${kind}` }, word), r.error ? h("small", null, r.error) : null,
              r.denials ? h("small", null, `${r.denials} blocked tool call${r.denials === 1 ? "" : "s"}`) : null),
            h("td", null, `${r.seconds} s`), h("td", null, String(r.turns)), h("td", null, `${number(r.tokens_in)} / ${number(r.tokens_out)}`));
        })))) : h("p", { class: "soft" }, "No runs yet. Every Claude call the app makes is listed here.")),
    section("app", "power", "The app", "Closing the window stops LinkedIn Studio too. A job under way is stopped.", h("div", { class: "form-foot" }, quit))));
  if (on) focusFirst(box.querySelector(`[data-keep="${on}"]`));
  for (const name of ["check_config", "selftest"]) if (data.checks[name].running) watchHealth();
}

function chatgpt(c) {
  const home = h("input", { class: "input path", placeholder: "C:\\Users\\you\\.codex-personal", value: c.home || "", "aria-label": "Codex home", "data-keep": "codex-home" });
  const out = h("div", { class: "results" });
  const save = h("button", { class: "btn small", type: "button", "data-keep": "codex-save" }, "Save");
  save.addEventListener("click", () => whileBusy(save, async () => {
    const reply = await post("/api/codex/home", { home: home.value });
    put(out, note(reply.error ? "bad" : "ok", reply.error || "Saved. Pictures use this sign-in from now on."));
    announce(reply.error || "Saved.", { urgent: !!reply.error });
  }));
  const waiting = c.login && c.login.state === "waiting";
  const signIn = h("button", { class: "btn small", type: "button", "data-keep": "codex-signin",
    title: "Runs codex login with this Codex home: it opens ChatGPT’s sign-in in your browser and waits." }, "Sign in");
  signIn.addEventListener("click", () => whileBusy(signIn, async () => {
    const reply = await post("/api/codex/login", {});
    if (reply.error) {
      put(out, note("bad", reply.error));
      return announce(reply.error, { urgent: true });
    }
    announce("Waiting for the sign-in in your browser.");
    await settings(true);
    focusFirst(box.querySelector('[data-keep="codex-stop"]'));
  }));
  const stop = h("button", { class: "btn small", type: "button", "data-keep": "codex-stop" }, "Stop waiting");
  stop.addEventListener("click", () => whileBusy(stop, async () => {
    await post("/api/codex/stop", {});
    await settings(true);
  }));
  const status = waiting
    ? note("soft", "Waiting for you to sign in to ChatGPT in the browser window Codex opened…", `When you are done there, it is kept in ${c.home}.`)
    : c.ok ? note("ok", `Signed in to ChatGPT as ${c.account}${c.plan ? ` (${c.plan[0].toUpperCase()}${c.plan.slice(1)})` : ""}.`)
      : note("warn", c.error || "Not set up.", c.login && c.login.state === "failed" ? c.login.error : null);
  if (waiting) watchHealth();   // the card follows the sign-in as it happens
  return section("chatgpt", "image", "ChatGPT", "Claude asks ChatGPT for an illustration when you ask for one, through OpenAI’s Codex CLI signed in as your ChatGPT account. Each picture spends your ChatGPT allowance.",
    status,
    facts(c.found ? ["Codex CLI", c.path || "Found"] : null, ["Codex home", c.home || "Not set: pictures are off"],
      ["Pictures today", `${c.today || 0} made, at most ${c.per_request || 0} in one request`]),
    h("label", { class: "field" }, h("span", { class: "field-label" }, "Codex home (where your ChatGPT sign-in for Codex is kept)"), home,
      h("span", { class: "field-hint" }, "No default: Codex’s own .codex folder may be another account. Name the folder you signed in with; Sign in signs Codex in there.")),
    out,
    h("div", { class: "form-foot" }, save, waiting ? stop : c.ok || !c.home ? null : signIn));
}

function health(name, title, blurb, check) {
  const run = h("button", { class: "btn small", type: "button", "data-keep": `health-${name}` }, icon("activity", 14), h("span", null, check.row ? "Run again" : "Run"));
  run.addEventListener("click", () => whileBusy(run, async () => {
    const reply = await post(`/api/settings/health/${name}`, {});
    announce(reply.error || `${title}: running.`, { urgent: !!reply.error });
    await settings(true);
  }));
  return h("div", { class: "card" }, h("div", { class: "card-head" }, h("h3", null, title), h("code", null, `${name}.py`)),
    h("div", { class: "card-body" }, h("p", { class: "soft" }, blurb),
      // "Running…" takes the Run button's place and its data-keep, so the focus stays on it and lands on Run again.
      h("div", { class: "form-foot" }, check.running ? [h("i", { class: "pulse" }), h("span", { class: "soft", "data-keep": `health-${name}` }, "Running…")] : run,
        check.row && !check.running ? [h("span", { class: `chip ${check.row.ok ? "ok" : "bad"}` }, check.row.ok ? "All good" : "Found a problem"),
          h("span", { class: "soft" }, check.row.when)] : null),
      check.row && !check.running ? h("details", { class: "fold", open: !check.row.ok }, h("summary", null, "What it reported"),
        h("pre", { class: "mono-out" }, check.row.output)) : null));
}

function watchHealth() {
  clearTimeout(polling);
  polling = setTimeout(() => settings(true), 2000);
}

// ---------- the setup screen ----------

async function setup() {
  const data = await api("/api/setup");
  if (data.error) return void put(box, note("bad", data.error));
  drawSetup(data);
}

function drawSetup(data) {
  const inputs = {};
  const form = h("form", { class: "panel-body" }, data.fields.map((f) => {
    const input = h("input", { class: "input path", id: `path-${f.key}`, value: data.values[f.key] || "", placeholder: data.examples[f.key],
      spellcheck: "false", autocomplete: "off", readonly: data.saved });
    inputs[f.key] = input;
    const browse = data.saved ? null : h("button", { class: "btn", type: "button", title: "Choose it in a Windows file window" }, icon("folder", 15), h("span", null, "Browse…"));
    if (browse) browse.addEventListener("click", () => whileBusy(browse, async () => {
      const reply = await post("/api/setup/browse", { field: f.key, start: input.value });
      if (reply.error) return announce(reply.error, { urgent: true });
      if (reply.path) input.value = reply.path;
    }));
    // A login folder: who it is signed in to, beside each one found and under the box for the one chosen.
    const accounts = f.key === "claude_config_dir" ? data.accounts || {} : null;
    const who = accounts ? h("div", { class: "field-hint", "aria-live": "polite" }) : null;
    const showWho = (place) => {
      if (!who) return;
      const s = accounts[place];
      who.className = s && s.signed_in === false ? "field-error" : "field-hint";
      who.textContent = !s ? (place ? "Save checks who this folder is signed in to." : "")
        : s.ok ? `Claude Code is ${accountWords(s)} in this folder.`
          : s.signed_in === false ? "Not signed in: run claude once in a terminal and sign in, or choose the folder you signed in with."
            : `Who is signed in here could not be read (${s.error}). Save still works.`;
    };
    if (who) input.addEventListener("input", () => showWho(input.value.trim()));
    const found = (data.found[f.key] || []).length && !data.saved ? h("div", { class: "picks" }, h("span", { class: "field-hint" }, "Found on this PC:"),
      data.found[f.key].map((place) => {
        const pick = h("button", { class: "pick path", type: "button", "aria-pressed": String(place === input.value) }, place,
          accounts && accounts[place] ? h("span", { class: "field-hint" }, ` · ${accountWords(accounts[place])}`) : null);
        pick.addEventListener("click", () => {
          input.value = place;
          pick.parentElement.querySelectorAll(".pick").forEach((p) => p.setAttribute("aria-pressed", String(p === pick)));
          showWho(place);
        });
        return pick;
      })) : null;
    showWho(input.value);
    return h("div", { class: "field" }, h("label", { class: "field-label", for: `path-${f.key}` }, f.label),
      h("div", { class: "path-row" }, input, browse),
      data.errors[f.key] ? h("div", { class: "field-error" }, data.errors[f.key])
        : data.values[f.key] ? h("div", { class: "field-hint good" }, icon("check", 13), data.saved ? "Saved" : "Found") : null,
      data.errors[f.key] ? null : who,
      found, h("div", { class: "field-hint" }, `${f.what} For example `, h("code", null, data.examples[f.key])));
  }), data.errors[""] ? h("div", { class: "field-error" }, data.errors[""]) : null);
  const save = h("button", { class: "btn primary", type: "submit" }, icon("check", 15),
    h("span", null, data.first_run ? "Save and start" : data.restarts ? "Save and restart" : "Save"));
  form.append(data.saved
    ? note("ok", data.restarts ? "Saved. LinkedIn Studio is restarting with these folders: this window closes and a new one opens."
      : "Saved in config.local.toml. Close LinkedIn Studio and open it again to use these folders.")
    : h("div", { class: "form-foot" }, save, data.first_run ? null : h("button", { class: "btn ghost", type: "button", onclick: () => go("#~settings") }, "Cancel"),
      h("span", { class: "field-hint" }, "Kept in config.local.toml in the app’s folder. Nothing else in that file changes.")));
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    whileBusy(save, async () => {
      const values = Object.fromEntries(Object.entries(inputs).map(([k, input]) => [k, input.value]));
      const reply = await post("/api/setup", values);
      if (reply.error) return announce(reply.error, { urgent: true });
      drawSetup(reply);
      announce(reply.saved ? "Saved." : "Something is not right yet: see the boxes.", { urgent: !reply.saved });
    });
  });
  put(box, h("div", { class: "setup" },
    data.first_run ? h("div", { class: "brand" }, h("img", { class: "logo", src: "/static/icon.svg", width: 30, height: 30, alt: "" }), "LinkedIn Studio") : null,
    h("p", { class: "lede" }, data.first_run ? "One step before the app can start: tell it where three things are on this PC." : "Where the skills, the Claude program and its sign-in are on this PC.",
      " For each one, click a place it found, press Browse, or paste the path."),
    h("section", { class: "panel" }, form),
    h("section", { class: "panel" }, h("header", { class: "panel-head" }, h("div", null, h("h2", null, "If one of them is not on this PC yet"))),
      h("div", { class: "panel-body" }, facts(
        ["The skills", h("div", null, "Turn on Developer Mode in Windows Settings, so git can make the links Claude needs. Then, in PowerShell:",
          h("pre", { class: "mono-out" }, "git -c core.symlinks=true clone https://github.com/sergebulaev/linkedin-skills"))],
        ["Claude Code", "Install it as Anthropic’s setup page describes, then run claude once in a terminal and sign in. If yours came from npm, run claude install to get claude.exe."],
        ["The login folder", "It appears after that first sign-in: the .claude folder in your user folder, unless you keep a separate login for this app."])))));
}
