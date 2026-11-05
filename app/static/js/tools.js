// Tools: one skill each (Humanize, Audit, Hook extractor, Comment drafter, Repurposer, Profile optimizer). The input on
// the left, the result on the right with copy buttons, and under it the tool's earlier results, each shown again with a
// press. Start a post from this makes a post of a result that holds one (a rewrite, the draft audited, a repurposed
// post, a hook's template) and opens it. Nothing here goes out.
import { state, h, icon, api, post, put, number, announce, whileBusy, drawIfChanged, copyButton, go, focusFirst } from "./core.js";
import { drawWorking, problemCard } from "./jobs.js";
import { auditView } from "./audit.js";
import { wordDiff } from "./wdiff.js";

const LABELS = { humanize: ["Text to humanize", "Humanize", "Paste the text you want to sound like a person wrote it."],
  audit: ["Draft to audit", "Audit", "Paste a finished draft."], hook: ["Post text", "Find the hook", "Paste the post you want to learn from."],
  comment: ["Post text", "Draft comments", "Paste the post you want to comment on."],
  repurpose: ["Source content", "Repurpose", "Paste a tweet, a thread, a blog section, a transcript…"],
  profile: ["Profile text", "Review profile", "Paste your headline, About, Experience and Skills. A profile link cannot be read."] };
const MODE_WORDS = { default: "Recommended (forensic + strict)", forensic: "Light touch (forensic only)", strict: "Strict",
  aesthetic: "Aesthetic (also style habits)", all: "Everything (may flatten your voice)" };
const kept = (key) => {
  try {
    return sessionStorage.getItem(`tool:${key}`) || "";
  } catch {
    return "";
  }
};
const keep = (key, value) => {
  try {
    sessionStorage.setItem(`tool:${key}`, value);
  } catch {}
};

let box = null;
let data = null;
let current = "humanize";
const outs = {};
const runs = {};          // each tool's Run button: where the focus goes when its result box empties under it
const lists = {};         // each tool's Earlier results, under its result
const picks = {};         // kind -> { job, over }: an earlier result picked, shown until the tool's latest job changes

const latestKey = (t) => (t.job ? `${t.job.id}:${t.job.status}` : "");
const toolOf = (kind) => (data ? data.tools.find((t) => t.kind === kind) : null);

export async function render(container, { sub } = {}) {
  box = container;
  if (sub && LABELS[sub]) current = sub;
  data = null;
  put(box, h("p", { class: "lede" }, "Loading…"));
  await refresh();
}

export async function refresh() {
  if (!box || state.page !== "tools") return;
  const reply = await api("/api/tools");
  if (reply.error || state.page !== "tools") return;
  const first = !data;
  data = reply;
  if (first) draw();
  for (const t of data.tools) drawOut(t);
}

export function tick() {
  if (!data) return;
  for (const job of state.jobs) {
    if (job.source !== "tools") continue;
    const spot = box.querySelector(`[data-job-box="${job.id}"]`);
    if (spot) drawWorking(spot, job);
  }
}

function draw() {
  const tabs = h("div", { class: "tabs", role: "tablist", "aria-label": "Tools" }, data.tools.map((t) => {
    const tab = h("button", { class: "btn small", type: "button", role: "tab", id: `tool-tab-${t.kind}`, "aria-controls": `tool-pane-${t.kind}`,
      "aria-selected": String(t.kind === current), "data-tool": t.kind, tabindex: t.kind === current ? "0" : "-1" }, icon(t.icon, 14), t.title);
    tab.addEventListener("click", () => pick(t.kind, true));
    return tab;
  }));
  tabs.addEventListener("keydown", (event) => {
    const list = [...tabs.children];
    const at = list.indexOf(document.activeElement);
    const to = { ArrowRight: at + 1, ArrowLeft: at - 1, Home: 0, End: list.length - 1 }[event.key];
    if (at < 0 || to === undefined) return;
    event.preventDefault();
    pick(list[(to + list.length) % list.length].dataset.tool, false, true);
  });
  put(box, h("div", { class: "page-width" },
    h("p", { class: "lede" }, "One skill per tool. Nothing here posts to LinkedIn: you copy what you want."),
    tabs, data.tools.map((t) => pane(t))));
  pick(current);
}

function pick(kind, focusField = false, focusTab = false) {
  current = kind;
  history.replaceState(null, "", `#~tools-${kind}`);
  for (const tab of box.querySelectorAll("[data-tool]")) {
    const on = tab.dataset.tool === kind;
    tab.setAttribute("aria-selected", String(on));
    tab.tabIndex = on ? 0 : -1;
    if (on && focusTab) tab.focus();
  }
  for (const p of box.querySelectorAll("[data-pane]")) p.hidden = p.dataset.pane !== kind;
  if (focusField) box.querySelector(`[data-pane="${kind}"] textarea`).focus();
}

function pane(t) {
  const k = t.kind;
  const [label, run, placeholder] = LABELS[k];
  const text = h("textarea", { class: "input area", rows: 9, placeholder, "aria-label": label });
  text.value = kept(`${k}-text`);
  text.addEventListener("input", () => keep(`${k}-text`, text.value));
  const extra = {};
  const fields = [h("label", { class: "field" }, h("span", { class: "field-label" }, label), text)];
  if (k === "hook" || k === "comment") {
    extra.url = h("input", { class: "input", type: "url", placeholder: "https://www.linkedin.com/posts/…", disabled: !data.apify });
    extra.url.value = kept(`${k}-url`);
    extra.url.addEventListener("input", () => keep(`${k}-url`, extra.url.value));
    fields.unshift(h("label", { class: "field" }, h("span", { class: "field-label" }, "LinkedIn post link ", h("span", { class: "opt" }, "optional")), extra.url,
      h("span", { class: "field-hint" }, data.apify ? "Fetched through Apify before the skill runs." : "Links need an Apify token in linkedin-skills\\.env. Paste the post text instead.")));
  }
  if (k === "humanize") {
    extra.mode = h("select", { class: "input" }, data.modes.map((m) => h("option", { value: m }, MODE_WORDS[m] || m)));
    fields.push(h("label", { class: "field" }, h("span", { class: "field-label" }, "How hard to scrub"), extra.mode));
  } else if (k === "comment") {
    extra.angle = h("input", { class: "input", placeholder: "e.g. push back on point 2" });
    extra.angle.value = kept("comment-angle");
    extra.angle.addEventListener("input", () => keep("comment-angle", extra.angle.value));
    fields.push(h("label", { class: "field" }, h("span", { class: "field-label" }, "What you want to say ", h("span", { class: "opt" }, "optional")), extra.angle));
  } else if (k === "repurpose") {
    extra.goal = h("select", { class: "input" }, h("option", { value: "" }, "Let the skill pick"), data.goals.map((g) => h("option", { value: g }, g[0].toUpperCase() + g.slice(1))));
    fields.push(h("label", { class: "field" }, h("span", { class: "field-label" }, "What the post should earn"), extra.goal));
  } else if (k === "profile") {
    extra.goal = h("select", { class: "input" }, ["authority", "clients", "job seeking"].map((g) => h("option", { value: g }, g[0].toUpperCase() + g.slice(1))));
    fields.push(h("label", { class: "field" }, h("span", { class: "field-label" }, "What the profile is for"), extra.goal));
  }
  const err = h("div", { class: "results" });
  const go_ = h("button", { class: "btn primary", type: "submit" }, icon("sparkle", 15), h("span", null, run));
  runs[k] = go_;
  const form = h("form", { class: "panel-body" }, h("p", { class: "soft" }, t.blurb), fields, err,
    h("div", { class: "form-foot" }, go_, h("span", { class: "soft" }, "Ctrl + Enter")));
  form.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    whileBusy(go_, async () => {
      const body = { text: text.value, url: extra.url ? extra.url.value : "", mode: extra.mode ? extra.mode.value : "",
        goal: extra.goal ? extra.goal.value : "", angle: extra.angle ? extra.angle.value : "" };
      const reply = await post(`/api/tools/${k}`, body);
      if (reply.error) {
        put(err, h("div", { class: "result bad" }, icon("alert", 15), h("div", null, reply.error)));
        return announce(reply.error, { urgent: true });
      }
      err.replaceChildren();
      announce(`${t.title}: working. The result appears beside the form.`);
      window.dispatchEvent(new Event("studio:poll"));
    });
  });
  outs[k] = h("div", { class: "panel-body", "aria-live": "off" });
  lists[k] = h("section", { class: "earlier", "aria-labelledby": `earlier-${k}`, hidden: true });
  return h("section", { "data-pane": k, id: `tool-pane-${k}`, role: "tabpanel", "aria-labelledby": `tool-tab-${k}`, hidden: true },
    h("div", { class: "workbench" },
      h("section", { class: "panel" }, h("header", { class: "panel-head" }, h("span", { class: "panel-mark" }, icon(t.icon, 17)), h("div", null, h("h2", null, t.title))), form),
      h("section", { class: "panel", "aria-label": `${t.title}: result` }, h("header", { class: "panel-head" }, h("div", null, h("h2", null, "Result"))), outs[k],
        lists[k])));
}

function drawOut(t) {
  const out = outs[t.kind];
  if (!out) return;
  if (picks[t.kind] && picks[t.kind].over !== latestKey(t)) delete picks[t.kind];   // a new run takes the box back
  const job = picks[t.kind] ? picks[t.kind].job : t.job;
  drawEarlier(t, job);
  const had = out.contains(document.activeElement);
  const drew = drawIfChanged(out, JSON.stringify(job && [job.id, job.status, job.result]), () => {
    if (!job) return void put(out, h("p", { class: "soft" }, "Nothing here yet. Run the tool and its result appears on this side."));
    if (["queued", "running"].includes(job.status)) return void put(out, h("div", { "data-job-box": job.id }));
    if (["failed", "unparsed"].includes(job.status)) return void put(out, problemCard(job, { onDone: () => window.dispatchEvent(new Event("studio:poll")) }));
    put(out, result(t.kind, job));
  });
  if (job && ["queued", "running"].includes(job.status)) drawWorking(out.querySelector("[data-job-box]"), job);
  // The control the focus was on went with what was drawn (Try again, Dismiss, Cancel): on to the new card's own
  // button (Cancel while it works), or else the tool's Run.
  if (drew && had && !out.contains(document.activeElement)) {
    focusFirst(out.querySelector(".working button"), out.querySelector(".problem button"), runs[t.kind]);
  }
}

// Earlier results: the tool's finished results (newest first, the one shown marked), shown while there is one other than
// the result in the box. The focus stays on the row it was on through a redraw.
function drawEarlier(t, shown) {
  const list = lists[t.kind];
  const items = t.earlier || [];
  const at = shown && shown.status === "done" ? shown.id : null;
  const on = list.contains(document.activeElement) ? document.activeElement.dataset.job : null;
  const drew = drawIfChanged(list, JSON.stringify([items, at]), () => {
    list.hidden = !items.some((e) => e.id !== at);
    put(list, h("header", { class: "panel-head" }, h("div", null, h("h3", { id: `earlier-${t.kind}` }, "Earlier results"),
      h("p", null, `The last ${items.length === 1 ? "one" : number(items.length)}, newest first. Pick one to see it again.`))),
    h("div", { class: "rows" }, items.map((e) => h("button", { class: "row-link", type: "button", "data-job": e.id,
      "aria-current": e.id === at ? "true" : null, onclick: () => pickEarlier(t.kind, e) },
    h("b", null, e.first || "(no text)"), h("small", null, e.when), e.id === at ? h("span", { class: "chip" }, "Showing") : null))));
  });
  if (drew && on) focusFirst(list.querySelector(`[data-job="${on}"]`), runs[t.kind]);
}

async function pickEarlier(kind, entry) {
  const t = toolOf(kind);
  if (!t) return;
  if (t.job && t.job.id === entry.id) {
    delete picks[kind];         // the latest: the box follows the tool again
  } else {
    const reply = await api(`/api/tools/${kind}/${entry.id}`);
    if (reply.error) return announce(reply.error, { urgent: true });
    picks[kind] = { job: reply.job, over: latestKey(t) };
  }
  drawOut(toolOf(kind));
  announce(`Showing the result from ${entry.when}: ${entry.first || "no text"}.`);
}

// Start a post from this: a new post from this result, opened at once (the one way, for every tool whose result is a
// post's text).
function startButton(kind, job) {
  const start = h("button", { class: "btn primary small", type: "button", "data-act": "tool-post" }, icon("file", 14), h("span", null, "Start a post from this"));
  start.addEventListener("click", () => whileBusy(start, async () => {
    const reply = await post(`/api/tools/${kind}/${job.id}/draft`, {});
    if (reply.error) return announce(reply.error, { urgent: true });
    announce("A new post, from this result. It is open now.");
    go(`#post-${reply.post}`);
  }));
  return start;
}

const bullets = (items) => (items && items.length ? h("ul", { class: "list" }, items.map((x) => h("li", null, String(x)))) : null);
const fold = (title, items, open = false) => (items && items.length ? h("details", { class: "fold", open }, h("summary", null, `${title} (${items.length})`), h("div", { class: "fold-body" }, bullets(items))) : null);

function result(kind, job) {
  const d = job.result || {};
  const p = job.params || {};
  const parts = [];
  const start = (toolOf(kind) || {}).can_post ? startButton(kind, job) : null;
  if (kind === "humanize") {
    const read = String(d.reader_read || "").toLowerCase();
    parts.push(h("div", { class: "out-head" }, h("h3", null, "Rewritten"),
      read ? h("span", { class: `chip ${read.includes("human") ? "ok" : read.split(" ").includes("ai") ? "bad" : "warn"}` }, d.reader_read) : null,
      copyButton(String(d.rewritten || "")), start));
    parts.push(h("p", { class: "textbox" }, String(d.rewritten || "")),
      h("p", { class: "soft" }, `${number(String(d.rewritten || "").length)} characters, from ${number(String(p.text || "").length)}`),
      fold("What changed", d.changes, true),
      job.compare ? h("details", { class: "fold" }, h("summary", null, "Compare with the original"),
        h("p", { class: "wdiff fold-body" }, wordDiff(job.compare))) : null,
      d.missing && d.missing.length ? h("details", { class: "fold" }, h("summary", null, `Worth adding (${d.missing.length})`),
        h("div", { class: "fold-body" }, h("p", { class: "soft" }, "Details only you know. Nothing was invented for you."), bullets(d.missing))) : null);
  } else if (kind === "audit") {
    parts.push(auditView(d, { level: 3 }),
      start ? h("div", { class: "form-foot" }, start, h("span", { class: "soft" }, "The draft you audited, with these findings beside it.")) : null);
  } else if (kind === "hook") {
    parts.push(h("div", { class: "out-head" }, h("h3", null, d.formula || "The hook"), d.confidence ? h("span", { class: "chip busy" }, `${d.confidence} confidence`) : null),
      d.runner_up ? h("p", { class: "soft" }, `Runner-up: ${d.runner_up}`) : null,
      d.hook ? h("blockquote", { class: "textbox" }, d.hook) : null, d.why ? h("p", null, d.why) : null,
      h("div", { class: "out-head" }, h("h3", null, "Blank template"), copyButton(String(d.template || "")), d.template ? start : null),
      h("p", { class: "textbox" }, String(d.template || "")),
      fold("How the post is built", d.structure), fold("Do not copy these", d.cautions, true));
  } else if (kind === "comment") {
    parts.push(h("div", { class: "result soft" }, icon("info", 15), h("div", null, "The app never posts comments. Copy the one you like and post it yourself.")));
    (d.variants || []).forEach((v, i) => parts.push(h("div", { class: "out" },
      h("div", { class: "out-head" }, h("h3", null, v.template || `Option ${i + 1}`),
        v.reaction ? h("span", { class: "chip" }, `React: ${data.reactions[String(v.reaction).toUpperCase()] || v.reaction}`) : null, copyButton(String(v.text || ""))),
      h("p", { class: "textbox" }, String(v.text || "")),
      h("p", { class: "soft" }, `${String(v.text || "").length} characters${v.why ? ` · ${v.why}` : ""}`))));
  } else if (kind === "repurpose") {
    parts.push(h("div", { class: "out-head" }, h("h3", null, "LinkedIn post"), copyButton(String(d.post || "")), start),
      h("p", { class: "textbox" }, String(d.post || "")),
      h("p", { class: "soft" }, `${number(String(d.post || "").length)} characters${d.formula ? ` · ${d.formula}` : ""}`),
      d.first_comment ? [h("div", { class: "out-head" }, h("h3", null, "First comment"), copyButton(String(d.first_comment))), h("p", { class: "textbox" }, String(d.first_comment))] : null,
      fold("What became what", d.mapping));
  } else if (kind === "profile") {
    parts.push(h("div", { class: "score" }, (d.scorecard || []).map((s) => {
      const v = String(s.verdict || "").toLowerCase();
      return h("div", null, h("div", { class: "head" }, h("b", null, s.section), h("span", { class: `chip ${v === "pass" ? "ok" : v === "fail" ? "bad" : v.includes("work") ? "warn" : ""}` }, s.verdict)),
        h("span", { class: "soft" }, s.note || ""));
    })), d.priority_fixes && d.priority_fixes.length ? [h("h3", null, "Start here"), h("ol", { class: "list" }, d.priority_fixes.map((f) => h("li", null, String(f))))] : null,
    (d.rewrites || []).map((r, i) => h("details", { class: "fold", open: i === 0 }, h("summary", null, r.section),
      h("div", { class: "fold-body out" }, h("p", { class: "textbox" }, String(r.after || "")),
        h("div", { class: "form-foot" }, copyButton(String(r.after || "")), h("span", { class: "soft" }, `${number(String(r.after || "").length)} characters`)),
        r.before ? h("details", { class: "fold" }, h("summary", null, "Before"), h("p", { class: "textbox fold-body" }, String(r.before))) : null))));
  }
  parts.push(h("p", { class: "soft" }, `Finished ${job.finished_ago || ""}`));
  return h("div", { class: "out" }, parts);
}
