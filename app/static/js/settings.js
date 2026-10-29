// Settings (Claude and who it is signed in as, publishing, posting times, ChatGPT, you in the preview, post style, appearance,
// the health checks, recent runs, quitting) and the setup screen (the three folders: found on this PC, Browse…, or pasted, each login folder
// with the account it is signed in to; Save checks them, writes config.local.toml and restarts).
// Each panel has an address, #~settings-<id>: the jump links at the top use it, and it opens with that panel's heading
// focused. The focus stays where it was through every redraw (data-keep), with what was typed and not yet saved, and a
// health check says how it ended.
import { state, h, icon, api, post, put, number, announce, whileBusy, focusFirst, go } from "./core.js";
import { setTheme } from "./sidebar.js";
import { YOU, liHead, paintWho } from "./editor.js";
import { ALWAYS, styleSliders } from "./style.js";

let box = null;
let polling = 0;
export const PANELS = [["claude", "Claude"], ["publishing", "Publishing"], ["posting", "Posting times"], ["chatgpt", "ChatGPT"],
  ["profile", "You in the preview"], ["style", "Post style"], ["appearance", "Appearance"], ["health", "Health checks"],
  ["runs", "Recent runs"], ["app", "The app"]];
const CHECKS = { check_config: "Connections", selftest: "Full self-test" };
const running = {};       // check -> running at the last draw, so its end is said once
const typed = {};         // a box's words not yet saved (name, headline, codexHome, style, posting), kept through redraws
const PHOTO_PX = 256;     // the photo is made this size here, before it is sent

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
  const [data, codex, me, look, times] = await Promise.all([api("/api/settings"), api("/api/codex"), api("/api/profile"),
    api("/api/style"), api("/api/posting")]);
  if (data.error || state.page !== "settings") return;
  for (const [name, title] of Object.entries(CHECKS)) {        // a check that was running has ended: say how
    const check = data.checks[name];
    if (running[name] && !check.running && check.row) {
      announce(check.row.ok ? `${title}: all good` : `${title} found a problem: see What it reported`, { urgent: !check.row.ok });
    }
    running[name] = check.running;
  }
  const key = JSON.stringify([data, codex, me, look, times]);
  if (quiet && key === last) return;
  last = key;
  const on = box.contains(document.activeElement) ? document.activeElement.dataset.keep : null;
  const caret = on ? selectionOf(document.activeElement) : null;
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
      modelForm(c),
      facts(["Login folder", h("code", null, c.login)], ["Per run", `up to ${c.turns} turns and ${c.seconds} seconds`],
        ["Ask Claude", `up to ${c.chat_turns} turns and ${c.chat_seconds} seconds a request`], ["Program", h("code", null, c.program)],
        ["Skills", h("code", null, c.skills)]),
      h("div", { class: "form-foot" }, check, h("button", { class: "btn small", type: "button", "data-keep": "folders", onclick: () => go("#~setup") },
        icon("folder", 14), h("span", null, "Change folders")))),
    section("publishing", "plane", "Publishing", "Keys live in linkedin-skills\\.env. The app reads them and never shows them.",
      planForm(data),
      facts(["Publora key", data.publora.key ? "Set" : "Missing"],
        ["LinkedIn channel", data.publora.platform_id ? "Set" : "Worked out from the key when you schedule"],
        ["Apify token", data.publora.apify ? "Set: post links can be fetched" : "Not set: paste post text instead of links"],
        ["Story Bank & voice", data.protection.ok ? "Kept out of git" : `Not protected: ${data.protection.detail}`],
        ["Times shown in", `${data.timezone} (${data.tz})`])),
    postingSection(times),
    chatgpt(codex),
    profileSection(me),
    styleSection(look),
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
  if (on) keepFocus(on, caret);
  for (const name of ["check_config", "selftest"]) if (data.checks[name].running) watchHealth();
}

// Where the caret was in a box, so it is put back after a redraw; null for anything else.
function selectionOf(el) {
  try {
    return typeof el.selectionStart === "number" ? [el.selectionStart, el.selectionEnd] : null;
  } catch {
    return null;
  }
}

function keepFocus(keep, caret, ...instead) {
  const el = focusFirst(box.querySelector(`[data-keep="${keep}"]`), ...instead);
  if (el && caret && el.dataset.keep === keep) {
    try {
      el.setSelectionRange(...caret);
    } catch {}
  }
}

// The model every run uses: a dropdown of the studio's list (/api/settings models: the account's own default, Sonnet,
// Opus, Haiku), saved the moment one is picked and used from the next run on. A name set by hand in config.local.toml
// that is not on the list shows as itself, so it stays chosen.
function modelForm(c) {
  const models = c.models.some((m) => m.value === c.model_value) ? c.models
    : [...c.models, { value: c.model_value, label: c.model_value, hint: "Set in config.local.toml" }];
  const pick = h("select", { class: "input", id: "claude-model", "data-keep": "claude-model", "aria-describedby": "claude-model-hint" },
    models.map((m) => h("option", { value: m.value }, m.label)));
  pick.value = c.model_value;
  const hint = h("span", { class: "field-hint", id: "claude-model-hint" });
  const say = () => { hint.textContent = (models.find((m) => m.value === pick.value) || {}).hint || ""; };
  say();
  const out = h("div", { class: "results" });
  pick.addEventListener("change", () => {
    say();
    whileBusy(pick, async () => {
      const reply = await post("/api/settings/model", { model: pick.value });
      if (reply.error) {
        pick.value = c.model_value;
        say();
        put(out, note("bad", reply.error));
        return announce(reply.error, { urgent: true });
      }
      const name = (models.find((m) => m.value === reply.model_value) || {}).label || reply.model_value;
      put(out, note("ok", `Saved. The next run uses ${reply.model_value ? name : "the account’s default"}.`));
      announce(`Saved. The next run uses ${reply.model_value ? name : "the account’s default"}.`);
      await settings(true);
    });
  });
  return h("div", { class: "model-form" }, h("label", { class: "field" }, h("span", { class: "field-label" }, "Model"), pick, hint), out);
}

// ---------- you, in the preview ----------

// A photo for the preview: the square in its middle, made 256 px (never larger than it was), as WebP, or PNG where the
// browser cannot write WebP. One the browser cannot draw (an iPhone's HEIC) gives null.
async function shrinkPhoto(file) {
  let bitmap;
  try {
    bitmap = await createImageBitmap(file);
  } catch {
    return null;
  }
  const side = Math.min(bitmap.width, bitmap.height);
  const size = Math.min(PHOTO_PX, side);
  const canvas = h("canvas", { width: size, height: size });
  canvas.getContext("2d").drawImage(bitmap, (bitmap.width - side) / 2, (bitmap.height - side) / 2, side, side, 0, 0, size, size);
  bitmap.close();
  const data = canvas.toDataURL("image/webp", 0.85);
  return data.startsWith("data:image/webp") ? data : canvas.toDataURL("image/png");
}

// Your name, headline and photo for every post's preview (kept beside the studio's database, on this PC), with a preview
// of its own that follows what you type.
function profileSection(me) {
  const title = "You in the preview";
  const lede = "Your name, headline and photo, above each post’s preview and beside its first comment. They stay on this PC: nothing here goes to LinkedIn, Publora or Claude.";
  if (!me || me.error) return section("profile", "user", title, lede, note("bad", (me && me.error) || "The studio did not answer."));
  const saved = me.saved || { name: "", headline: "" };
  const most = me.most || { name: 80, headline: 220 };
  const name = h("input", { class: "input", id: "profile-name", maxlength: most.name, autocomplete: "name", spellcheck: "false",
    placeholder: YOU.name, value: typed.name ?? saved.name, "data-keep": "profile-name" });
  const headline = h("input", { class: "input", id: "profile-headline", maxlength: most.headline, placeholder: YOU.headline,
    value: typed.headline ?? saved.headline, "data-keep": "profile-headline", "aria-describedby": "profile-headline-count" });
  const count = h("span", { class: "field-hint", id: "profile-headline-count" });
  const preview = h("div", { class: "li-card", style: "max-width:555px;padding-bottom:12px", role: "img",
    "aria-label": "How a post’s preview shows you" }, liHead("now · ", icon("globe", 11)));
  const show = () => {
    paintWho(preview, { name: name.value.trim() || YOU.name, headline: headline.value.trim() || YOU.headline, photo: me.photo,
      saved: { name: name.value.trim() } });
    count.textContent = `${number(Array.from(headline.value.trim()).length)} of ${number(most.headline)} characters`;
  };
  for (const [input, key] of [[name, "name"], [headline, "headline"]]) {
    input.addEventListener("input", () => {
      typed[key] = input.value;
      show();
    });
  }
  show();
  const out = h("div", { class: "results" });
  const save = h("button", { class: "btn primary small", type: "submit", "data-keep": "profile-save" }, icon("check", 14), h("span", null, "Save"));
  const form = h("form", { class: "grid" },
    h("div", { class: "fields" },
      h("label", { class: "field" }, h("span", { class: "field-label" }, "Name"), name),
      h("label", { class: "field" }, h("span", { class: "field-label" }, "Headline"), headline, count)),
    out,
    h("div", { class: "form-foot" }, save, h("span", { class: "soft" }, "Left empty, the preview says You and Your headline.")));
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    whileBusy(save, async () => {
      const reply = await post("/api/profile", { name: name.value, headline: headline.value });
      if (reply.error) {
        put(out, note("bad", reply.error));
        return announce(reply.error, { urgent: true });
      }
      delete typed.name;
      delete typed.headline;
      told(reply, "Saved. Every post’s preview shows it now.", "profile-save");
    });
  });
  const file = h("input", { type: "file", accept: "image/png,image/jpeg,image/webp", hidden: true, "data-photo": "" });
  const choose = h("button", { class: "btn small", type: "button", "data-keep": "profile-photo" }, icon("image", 14), h("span", null, "Choose a photo…"));
  choose.addEventListener("click", () => file.click());
  const said = h("div", { class: "results" });
  const refused = (why) => {
    put(said, note("bad", why));
    announce(why, { urgent: true });
  };
  file.addEventListener("change", () => {
    const picked = file.files && file.files[0];
    if (!picked) return;
    whileBusy(choose, async () => {
      const data = await shrinkPhoto(picked);
      file.value = "";
      if (!data) return refused(`${picked.name} could not be read here. Choose a PNG, JPEG or WebP photo.`);
      const reply = await post("/api/profile/photo", { data });
      if (reply.error) return refused(reply.error);
      told(reply, "Photo saved. Every post’s preview shows it now.", "profile-photo");
    });
  });
  const remove = me.photo ? h("button", { class: "btn small", type: "button", "data-keep": "profile-remove" }, icon("x", 14), h("span", null, "Remove")) : null;
  if (remove) remove.addEventListener("click", () => whileBusy(remove, async () => {
    const reply = await post("/api/profile/photo/remove", {});
    if (reply.error) return refused(reply.error);
    told(reply, "Photo removed. The preview shows your initials, or You.", "profile-photo");
  }));
  return section("profile", "user", title, lede, preview, form,
    h("div", { class: "field", role: "group", "aria-labelledby": "profile-photo-label" },
      h("span", { class: "field-label", id: "profile-photo-label" }, "Photo"),
      h("div", { class: "form-foot" }, choose, remove, file),
      h("span", { class: "field-hint" }, "A PNG, JPEG or WebP picture. It is cut to a square and made 256 px here, before it is saved."),
      said));
}

// Post style: the sliders new drafts are written with (style.js draws them, the same as a post's Style panel). What
// is moved and not yet saved stays through redraws.
function styleSection(look) {
  const title = "Post style";
  const lede = "How new drafts are written: the Planner’s drafts, Draft all, Ask Claude and the Repurposer. A post you restyle keeps its own style.";
  if (!look || look.error) return section("style", "sliders", title, lede, note("bad", (look && look.error) || "The studio did not answer."));
  const out = h("div", { class: "results" });
  const control = styleSliders(look, typed.style || look.style, "style-default", (values) => { typed.style = values; });
  const save = h("button", { class: "btn primary small", type: "submit", "data-keep": "style-save" }, icon("check", 14), h("span", null, "Save"));
  const studio = h("button", { class: "btn small", type: "button", "data-keep": "style-studio",
    title: "Moves the sliders back to the studio’s own setting. Save keeps it." }, icon("refresh", 14), h("span", null, "Studio default"));
  studio.addEventListener("click", () => control.set(look.studio));
  const form = h("form", { class: "style-form" }, control.element, h("p", { class: "soft" }, ALWAYS), out,
    h("div", { class: "form-foot" }, save, studio));
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    whileBusy(save, async () => {
      const reply = await post("/api/style", control.values());
      if (reply.error) {
        put(out, note("bad", reply.error));
        return announce(reply.error, { urgent: true });
      }
      delete typed.style;
      announce("Saved. New drafts are written in this style.");
      await settings(true);
    });
  });
  return section("style", "sliders", title, lede, form);
}

// The Publora plan (Starter or Pro, from /api/settings plans): what the studio may ask of Publora, a month and at a time.
// Picked, it goes into config.local.toml and the studio restarts to use it. Limits set by hand in that file show as Custom.
function planForm(data) {
  const plans = data.plan === "custom" ? [...data.plans, { value: "custom", label: "Custom (set in config.local.toml)", hint: data.plan_words }]
    : data.plans;
  const pick = h("select", { class: "input", id: "publora-plan", "data-keep": "publora-plan", "aria-describedby": "publora-plan-hint" },
    plans.map((p) => h("option", { value: p.value }, p.label)));
  pick.value = data.plan;
  const hint = h("span", { class: "field-hint", id: "publora-plan-hint" });
  const say = () => {
    const chosen = plans.find((p) => p.value === pick.value) || {};
    hint.textContent = `${chosen.hint || ""}. Pick the plan you have on Publora: the studio never asks it for more.`;
  };
  say();
  const out = h("div", { class: "results" });
  pick.addEventListener("change", () => {
    say();
    if (pick.value === "custom") return;
    whileBusy(pick, async () => {
      const reply = await post("/api/settings/publora-plan", { plan: pick.value });
      if (reply.error) {
        pick.value = data.plan;
        say();
        put(out, note("bad", reply.error));
        return announce(reply.error, { urgent: true });
      }
      const words = reply.restarts ? "Saved. LinkedIn Studio is restarting with this plan: this window closes and a new one opens."
        : "Saved in config.local.toml. Close LinkedIn Studio and open it again to use this plan.";
      put(out, note("ok", words));
      announce(words);
    });
  });
  return h("div", { class: "model-form" }, h("label", { class: "field" }, h("span", { class: "field-label" }, "Publora plan"), pick, hint), out);
}

// Posting times: the days and times the queue gives its posts, one a day at most, and the Planner plans for. Each day is
// on or off, with its own time. What is changed and not yet saved stays through redraws.
function postingSection(pt) {
  const title = "Posting times";
  if (!pt || pt.error) return section("posting", "clock", title, "", note("bad", (pt && pt.error) || "The studio did not answer."));
  const lede = `Each post you queue takes the next free one of these: one post a day at most${pt.limit ? `, and no more than ${pt.limit} a month` : ""}. `
    + `It goes to Publora by itself once its time is ${pt.window} days away${pt.at_once ? ` and fewer than ${pt.at_once} are waiting there` : ""}, `
    + "while the studio is open. The Planner plans one post for each day.";
  const now = { ...(typed.posting || pt.times) };
  const keep = () => { typed.posting = { ...now }; };
  const boxes = {};
  const rows = pt.days.map(([day, name]) => {
    const on = h("input", { type: "checkbox", id: `posting-${day}`, "data-keep": `posting-${day}` });
    on.checked = day in now;
    const at = h("input", { class: "input time", type: "time", step: 60, value: now[day] || pt.studio[day] || "08:30",
      disabled: !(day in now), "aria-label": `${name}: time`, "data-keep": `posting-${day}-time` });
    on.addEventListener("change", () => {
      at.disabled = !on.checked;
      if (on.checked) now[day] = at.value;
      else delete now[day];
      keep();
    });
    at.addEventListener("input", () => {
      if (!on.checked || !at.value) return;
      now[day] = at.value;
      keep();
    });
    boxes[day] = { on, at };
    return h("div", { class: "posting-row" }, h("label", { class: "check", for: `posting-${day}` }, on, name), at);
  });
  const out = h("div", { class: "results" });
  const save = h("button", { class: "btn primary small", type: "submit", "data-keep": "posting-save" }, icon("check", 14), h("span", null, "Save"));
  const studio = h("button", { class: "btn small", type: "button", "data-keep": "posting-studio",
    title: "Puts back the studio’s own times. Save keeps them." }, icon("refresh", 14), h("span", null, "Studio default"));
  studio.addEventListener("click", () => {
    for (const day of Object.keys(now)) delete now[day];
    for (const [day, { on, at }] of Object.entries(boxes)) {
      on.checked = day in pt.studio;
      at.disabled = !on.checked;
      if (on.checked) {
        at.value = pt.studio[day];
        now[day] = pt.studio[day];
      }
    }
    keep();
  });
  const form = h("form", { class: "posting-form" }, h("div", { class: "posting-days" }, rows), out,
    h("div", { class: "form-foot" }, save, studio, h("span", { class: "soft" }, `Saved: ${pt.words}.`)));
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    whileBusy(save, async () => {
      const reply = await post("/api/posting", { times: now });
      if (reply.error) {
        put(out, note("bad", reply.error));
        return announce(reply.error, { urgent: true });
      }
      delete typed.posting;
      announce(`Saved: ${reply.words}. Every queued post's time follows them.`);
      await settings(true);
    });
  });
  return section("posting", "clock", title, lede, form);
}

// A change was saved: every preview takes it at once (studio:profile), and this section is drawn again from the answer.
function told(profile, words, keep) {
  window.dispatchEvent(new CustomEvent("studio:profile", { detail: profile }));
  const old = box && box.querySelector("#settings-profile");
  const now = old && old.contains(document.activeElement) ? document.activeElement : null;
  const caret = now ? selectionOf(now) : null;
  if (old) old.replaceWith(profileSection(profile));
  keepFocus((now && now.dataset.keep) || keep, caret, box.querySelector('[data-keep="profile-photo"]'));
  announce(words);
}

function chatgpt(c) {
  const home = h("input", { class: "input path", placeholder: "C:\\Users\\you\\.codex-personal", value: typed.codexHome ?? (c.home || ""),
    "aria-label": "Codex home", "data-keep": "codex-home" });
  home.addEventListener("input", () => {
    typed.codexHome = home.value;
  });
  const out = h("div", { class: "results" });
  const save = h("button", { class: "btn small", type: "button", "data-keep": "codex-save" }, "Save");
  save.addEventListener("click", () => whileBusy(save, async () => {
    const reply = await post("/api/codex/home", { home: home.value });
    if (!reply.error) delete typed.codexHome;
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
