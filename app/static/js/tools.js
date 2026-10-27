// Tools: one skill each (Humanize, Audit, Hook extractor, Comment drafter, Repurposer, Profile optimizer). The input on
// the left, the result on the right with copy buttons; a repurposed post can become a post. Nothing here goes out.
import { state, h, icon, api, post, put, number, announce, whileBusy, drawIfChanged, copyButton, go } from "./core.js";
import { drawWorking, problemCard } from "./jobs.js";

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
    const tab = h("button", { class: "btn small", type: "button", role: "tab", "aria-selected": String(t.kind === current),
      "aria-pressed": String(t.kind === current), "data-tool": t.kind, tabindex: t.kind === current ? "0" : "-1" }, icon(t.icon, 14), t.title);
    tab.addEventListener("click", () => pick(t.kind, true));
    return tab;
  }));
  tabs.addEventListener("keydown", (event) => {
    const list = [...tabs.children];
    const at = list.indexOf(document.activeElement);
    const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (at < 0 || !step) return;
    event.preventDefault();
    pick(list[(at + step + list.length) % list.length].dataset.tool, false, true);
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
    tab.setAttribute("aria-pressed", String(on));
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
  return h("section", { "data-pane": k, hidden: true },
    h("div", { class: "workbench" },
      h("section", { class: "panel" }, h("header", { class: "panel-head" }, h("span", { class: "panel-mark" }, icon(t.icon, 17)), h("div", null, h("h2", null, t.title))), form),
      h("section", { class: "panel", "aria-label": `${t.title}: result` }, h("header", { class: "panel-head" }, h("div", null, h("h2", null, "Result"))), outs[k])));
}

function drawOut(t) {
  const out = outs[t.kind];
  if (!out) return;
  const job = t.job;
  drawIfChanged(out, JSON.stringify(job && [job.id, job.status, job.result]), () => {
    if (!job) return void put(out, h("p", { class: "soft" }, "Nothing here yet. Run the tool and its result appears on this side."));
    if (["queued", "running"].includes(job.status)) return void put(out, h("div", { "data-job-box": job.id }));
    if (["failed", "unparsed"].includes(job.status)) return void put(out, problemCard(job, { onDone: () => window.dispatchEvent(new Event("studio:poll")) }));
    put(out, result(t.kind, job));
  });
  if (job && ["queued", "running"].includes(job.status)) drawWorking(out.querySelector("[data-job-box]"), job);
}

const bullets = (items) => (items && items.length ? h("ul", { class: "list" }, items.map((x) => h("li", null, String(x)))) : null);
const fold = (title, items, open = false) => (items && items.length ? h("details", { class: "fold", open }, h("summary", null, `${title} (${items.length})`), h("div", { class: "fold-body" }, bullets(items))) : null);

function result(kind, job) {
  const d = job.result || {};
  const p = job.params || {};
  const parts = [];
  if (kind === "humanize") {
    const read = String(d.reader_read || "").toLowerCase();
    parts.push(h("div", { class: "out-head" }, h("h3", null, "Rewritten"),
      read ? h("span", { class: `chip ${read.includes("human") ? "ok" : read.split(" ").includes("ai") ? "bad" : "warn"}` }, d.reader_read) : null,
      copyButton(String(d.rewritten || ""))));
    parts.push(h("p", { class: "textbox" }, String(d.rewritten || "")),
      h("p", { class: "soft" }, `${number(String(d.rewritten || "").length)} characters, from ${number(String(p.text || "").length)}`),
      fold("What changed", d.changes, true),
      job.compare ? h("details", { class: "fold" }, h("summary", null, "Compare with the original"),
        h("p", { class: "wdiff fold-body" }, job.compare.map(([op, text]) => (op === "+" ? h("ins", null, text) : op === "-" ? h("del", null, text) : text)))) : null,
      d.missing && d.missing.length ? h("details", { class: "fold" }, h("summary", null, `Worth adding (${d.missing.length})`),
        h("div", { class: "fold-body" }, h("p", { class: "soft" }, "Details only you know. Nothing was invented for you."), bullets(d.missing))) : null);
  } else if (kind === "audit") {
    const pass = String(d.verdict || "").toUpperCase() === "PASS";
    parts.push(h("div", { class: `verdict ${pass ? "pass" : "fail"}` }, icon(pass ? "check-circle" : "alert", 22),
      h("div", null, h("b", null, pass ? "Ready to post" : "Not ready yet"), h("div", null, d.summary || ""))));
    if ((d.blockers || []).length) parts.push(h("h3", null, `Fix before posting (${d.blockers.length})`), d.blockers.map((b) => finding(b, true)));
    if ((d.warnings || []).length) parts.push(h("h3", null, `Worth a look (${d.warnings.length})`), d.warnings.map((b) => finding(b, false)));
  } else if (kind === "hook") {
    parts.push(h("div", { class: "out-head" }, h("h3", null, d.formula || "The hook"), d.confidence ? h("span", { class: "chip busy" }, `${d.confidence} confidence`) : null),
      d.runner_up ? h("p", { class: "soft" }, `Runner-up: ${d.runner_up}`) : null,
      d.hook ? h("blockquote", { class: "textbox" }, d.hook) : null, d.why ? h("p", null, d.why) : null,
      h("div", { class: "out-head" }, h("h3", null, "Blank template"), copyButton(String(d.template || ""))),
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
    const save = h("button", { class: "btn primary small", type: "button" }, icon("file", 14), h("span", null, "Save as a post"));
    save.addEventListener("click", () => whileBusy(save, async () => {
      const reply = await post(`/api/tools/repurpose/${job.id}/draft`, {});
      if (reply.error) return announce(reply.error, { urgent: true });
      announce("Saved as a new post.");
      go(`#post-${reply.post}`);
    }));
    parts.push(h("div", { class: "out-head" }, h("h3", null, "LinkedIn post"), copyButton(String(d.post || "")), save),
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

function finding(item, blocker) {
  const issue = typeof item === "string" ? item : item.issue;
  const fix = typeof item === "string" ? "" : item.fix;
  return h("div", { class: `finding${blocker ? " blocker" : ""}` }, h("b", null, issue), fix ? h("span", null, fix) : null);
}
