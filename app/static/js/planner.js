// The Planner: this week first (the latest plan's cards, each drafted with one press; a card whose post is in the Trash
// says so, with Put back; who to comment on and the inbound-readiness checklist), then getting set up until every step
// is done, this month (posts used against the limit, the next post, Claude's status), the scheduled posts with Check
// Publora, the form for a new week and earlier plans. Drawn again, a card keeps the focus that was in it: on its Cancel
// while it is being drafted, else on its first button.
import { $, state, h, icon, api, post, put, plural, announce, whileBusy, drawIfChanged, focusFirst, go } from "./core.js";
import { drawWorking, problemCard } from "./jobs.js";

let box = null;
let data = null;

export async function render(container) {
  box = container;
  if (!box.firstChild) put(box, h("p", { class: "lede" }, "Loading…"));
  await refresh();
}

export async function refresh() {
  if (!box || state.page !== "planner") return;
  const reply = await api("/api/planner");
  if (reply.error || state.page !== "planner") return;
  data = reply;
  const card = box.contains(document.activeElement) && document.activeElement.closest(".plan-card");
  const drew = drawIfChanged(box, JSON.stringify(data, (k, v) => (k === "seconds" || k === "quiet" || k === "progress" || k === "activity" ? undefined : v)), draw);
  tick();
  if (drew && card && card.id) {
    focusFirst(`#${card.id} .job-box button`, `#${card.id} .foot button`, `#${card.id}`);
  }
}

// Between polls only the jobs' words and timers change.
export function tick() {
  if (!data || !box) return;
  for (const job of state.jobs) {
    const spot = box.querySelector(`[data-job-box="${job.id}"]`);
    if (spot) drawWorking(spot, job);
  }
}

function ring(used, limit) {
  const pct = limit ? Math.min(used / limit, 1) : 1;
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  for (const [k, v] of Object.entries({ class: `ring${used >= limit ? " full" : ""}`, width: 68, height: 68, viewBox: "0 0 68 68", "aria-hidden": "true" })) svg.setAttribute(k, v);
  for (const cls of ["track", "value"]) {
    if (cls === "value" && !used) continue;
    const c = document.createElementNS(ns, "circle");
    for (const [k, v] of Object.entries({ class: cls, cx: 34, cy: 34, r: 28 })) c.setAttribute(k, v);
    if (cls === "value") c.setAttribute("stroke-dasharray", `${(175.93 * pct).toFixed(1)} 175.93`);
    svg.append(c);
  }
  return svg;
}

function draw() {
  const d = data;
  const left = d.steps.filter((s) => !s.done);
  const checkPublora = d.upcoming.length ? h("button", { class: "btn small ghost", type: "button" }, icon("refresh", 14), h("span", null, "Check Publora")) : null;
  if (checkPublora) checkPublora.addEventListener("click", () => whileBusy(checkPublora, async () => {
    const reply = await post("/api/posts/refresh", {});
    announce(reply.error || reply.said, { urgent: !!reply.error });
    window.dispatchEvent(new Event("studio:poll"));
  }));
  put(box, h("div", { class: "page-width" },
    d.problems.map((p) => h("div", { class: "notice bad" }, icon("alert", 16), h("div", null, p))),
    weekOf(d),
    left.length ? h("section", { class: "panel" },
      h("header", { class: "panel-head" }, h("span", { class: "panel-mark" }, icon("check", 17)),
        h("div", null, h("h2", null, "Getting set up"), h("p", null, `${d.steps.length - left.length} of ${d.steps.length} done`))),
      h("div", { class: "panel-body" }, h("div", { class: "steps" }, d.steps.map((s) => s.done
        ? h("div", { class: "step done" }, h("b", null, s.title), h("span", null, "Done"))
        : h("button", { class: "step", type: "button", onclick: () => go(s.href) }, h("b", null, s.title), h("span", null, s.text)))))) : null,
    h("div", { class: "section-title" }, h("h2", null, "This month")),
    h("div", { class: "grid cols-3" },
      h("section", { class: "panel" }, h("div", { class: "panel-body" },
        h("div", { class: "ring-row" }, ring(d.used, d.limit),
          h("div", { class: "stat" }, h("span", { class: "label" }, `Posts in ${d.month}`), h("span", { class: "big" }, `${d.used} `, h("small", null, `of ${d.limit}`)))),
        h("p", { class: "soft" }, `Scheduled or published from here, counted by ${d.tz} month. Publora keeps its own count.`))),
      h("section", { class: "panel" }, h("div", { class: "panel-body stat" },
        h("span", { class: "label" }, "Next post"),
        d.next ? [h("span", { class: "big", style: "font-size:19px" }, d.next.when),
          h("a", { href: `#post-${d.next.id}` }, d.next.first)]
          : [h("span", { class: "big", style: "font-size:19px;color:var(--text-3)" }, "Nothing scheduled"),
            h("span", { class: "soft" }, "Approve a post and pick a time.")])),
      h("section", { class: "panel" }, h("div", { class: "panel-body" },
        h("div", { class: "seg-row" }, h("span", { class: "stat" }, h("span", { class: "label" }, "Claude")),
          h("span", { class: `chip ${d.claude.working ? "busy" : ""}` }, d.claude.working || "Idle")),
        h("dl", { class: "facts" },
          d.claude.sign_in ? [h("dt", null, "Account"), h("dd", null, signedIn(d.claude.sign_in))] : null,
          h("dt", null, "Model"), h("dd", null, d.claude.model),
          h("dt", null, "Last run"), h("dd", null, d.claude.last_run || "None yet"),
          h("dt", null, "Health check"), h("dd", null, d.claude.health
            ? h("a", { href: "#~settings-health" }, `${d.claude.health.ok ? "All good" : "Found a problem"}, ${d.claude.health.when}`)
            : h("a", { href: "#~settings-health" }, "Not run yet")))))),
    h("section", { class: "panel" },
      h("header", { class: "panel-head" }, h("span", { class: "panel-mark" }, icon("clock", 17)),
        h("div", null, h("h2", null, "Scheduled posts"), h("p", null, "Waiting at Publora. Once a post’s time has passed, the studio asks Publora by itself every few minutes; Check Publora asks now.")), checkPublora),
      d.upcoming.length ? h("div", { class: "rows" }, d.upcoming.map((p) => h("button", { class: "row-link", type: "button", onclick: () => go(`#post-${p.id}`) },
        h("b", null, p.first), h("small", null, p.when), h("span", { class: `chip ${p.kind}` }, p.label))))
        : h("div", { class: "panel-body soft" }, "Nothing is scheduled. Approve a post, then pick a time.")),
    planForm(d),
    earlierOf(d)));
}

// Who Claude runs as: "Signed in as <account> (<plan>)", or a link to Settings › Claude when it is not (or can't tell).
function signedIn(si) {
  if (si.signed_in) return si.account ? `Signed in as ${si.account}${si.plan ? ` (${si.plan})` : ""}` : "Signed in";
  return h("a", { href: "#~settings-claude" }, si.ok === false && si.error ? `Could not tell: ${si.error}` : "Not signed in");
}

function planForm(d) {
  const last = d.last || {};
  const field = (label, input, opt) => h("label", { class: "field" }, h("span", { class: "field-label" }, label, opt ? h("span", { class: "opt" }, " optional") : null), input);
  const audience = h("input", { class: "input", name: "audience", value: last.audience || "", placeholder: "e.g. engineering managers at Indian SaaS startups", required: true });
  const goal = h("input", { class: "input", name: "goal", value: last.goal || "", placeholder: "e.g. inbound conversations about platform work", required: true });
  const theme = h("input", { class: "input", name: "theme", value: last.theme || "", placeholder: "Left empty, the plan draws on your Story Bank" });
  let count = Number(last.max_posts || 4);
  const counts = h("div", { class: "segmented", role: "group", "aria-label": "Posts this week" }, [3, 4, 5].map((n) => {
    const b = h("button", { class: "btn small", type: "button", "aria-pressed": String(n === count) }, String(n));
    b.addEventListener("click", () => {
      count = n;
      counts.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    });
    return b;
  }));
  const founder = h("input", { type: "checkbox", checked: !!last.founder });
  const out = h("div", { class: "results" });
  const go_ = h("button", { class: "btn primary", type: "submit" }, icon("sparkle", 15), h("span", null, "Plan the week"));
  const form = h("form", { class: "form" },
    h("p", { class: "soft" }, d.bank_filled ? "Angles come from your Story Bank." : "Your Story Bank is empty, so angles will be general until the interviewer fills it."),
    h("div", { class: "fields" }, field("Who you are writing for", audience), field("What the week should achieve", goal),
      field("Theme", theme, true), h("div", { class: "field" }, h("span", { class: "field-label" }, "Posts this week"),
        h("div", { class: "seg-row" }, counts, h("label", { class: "check" }, founder, "Founders edition")))),
    out,
    h("div", { class: "form-foot" }, go_, h("span", { class: "soft" }, "About a minute. You can leave this page while it runs.")));
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    whileBusy(go_, async () => {
      const reply = await post("/api/planner", { audience: audience.value, goal: goal.value, theme: theme.value, max_posts: count, founder: founder.checked });
      if (reply.error) {
        put(out, h("div", { class: "result bad" }, icon("alert", 15), h("div", null, reply.error)));
        return announce(reply.error, { urgent: true });
      }
      out.replaceChildren();
      announce("Planning your week.");
      window.dispatchEvent(new Event("studio:poll"));
    });
  });
  return h("section", { class: "panel", id: "plan-form" },
    h("header", { class: "panel-head" }, h("span", { class: "panel-mark" }, icon("calendar", 17)),
      h("div", null, h("h2", null, "Plan the next 7 days"), h("p", null, "Three to five posts from the content planner, each with a pillar, a hook formula and an angle."))),
    form);
}

function itemCard(item) {
  const job = item.job;
  let foot;
  if (item.post && item.post.trashed) {
    const back = h("button", { class: "btn small", type: "button", "aria-label": `Put back, ${item.post.first}` }, icon("history", 14), h("span", null, "Put back"));
    back.addEventListener("click", () => whileBusy(back, async () => {
      const reply = await post("/api/trash/back", { id: item.post.id });
      announce(reply.error || "Put back: the post is among your posts again, as it was.", { urgent: !!reply.error });
      window.dispatchEvent(new Event("studio:poll"));
    }));
    foot = [back, h("span", { class: "chip" }, item.post.label)];
  } else if (item.post) {
    foot = [h("button", { class: "btn small", type: "button", onclick: () => go(`#post-${item.post.id}`) }, icon("file", 14), h("span", null, "Open the post")),
      h("span", { class: `chip ${item.post.kind}` }, item.post.label)];
  } else if (job && ["queued", "running"].includes(job.status)) {
    foot = h("div", { class: "job-box", "data-job-box": job.id, style: "width:100%" });
  } else {
    const draft = h("button", { class: "btn small", type: "button" }, icon("sparkle", 14), h("span", null, "Draft this"));
    draft.addEventListener("click", () => whileBusy(draft, async () => {
      const reply = await post(`/api/planner/items/${item.id}/draft`, {});
      announce(reply.error || "Drafting. The post joins the list when it is ready.", { urgent: !!reply.error });
      window.dispatchEvent(new Event("studio:poll"));
    }));
    foot = [job ? problemCard(job, { onDone: () => window.dispatchEvent(new Event("studio:poll")) }) : null, draft];
  }
  return h("article", { class: "card plan-card", id: `item-${item.id}` },
    h("div", { class: "when" }, h("b", null, item.day || ""), h("span", null, item.time || ""), item.goal ? h("span", { class: "chip" }, icon("target", 12), item.goal) : null),
    h("div", { class: "angle" }, item.angle || ""),
    h("div", { class: "meta" },
      [item.pillar, item.format].filter(Boolean).length ? h("span", null, [item.pillar, item.format].filter(Boolean).join(" · ")) : null,
      item.formula ? h("span", null, item.formula) : null,
      item.cta ? h("span", null, `Close: ${item.cta}`) : null,
      item.bank_section ? h("span", null, `From your Story Bank: ${item.bank_section}`) : null),
    h("div", { class: "foot" }, foot));
}

// This week: the plan being made (or the one that did not finish), the latest plan's cards and what came with them.
function weekOf(d) {
  const out = [];
  const pj = d.plan_job;
  if (pj) {
    out.push(h("div", { class: "section-title" }, h("h2", null, ["queued", "running"].includes(pj.status) ? "Planning your week" : "The plan did not finish")));
    out.push(["queued", "running"].includes(pj.status) ? h("div", { class: "job-box", "data-job-box": pj.id })
      : problemCard(pj, { onDone: () => window.dispatchEvent(new Event("studio:poll")) }));
  }
  const latest = d.boards[0];
  if (!latest) {
    const toForm = h("button", { class: "btn primary", type: "button" }, icon("calendar", 15), h("span", null, "Plan the next 7 days"));
    toForm.addEventListener("click", () => {
      $("plan-form").scrollIntoView({ block: "start" });
      focusFirst('#plan-form input[name="audience"]');
    });
    if (!pj) out.push(h("div", { class: "empty" }, h("div", { class: "empty-mark" }, icon("calendar", 24)), h("h2", null, "No plan yet"),
      h("p", null, "Say who you write for and what the week should achieve. The plan appears here, and each post can be drafted with one press."),
      h("div", { class: "form-foot" }, toForm)));
    return out;
  }
  out.push(h("div", { class: "section-title" }, h("h2", null, "This week"), h("span", null, `Planned ${latest.planned} for ${latest.inputs.audience || "your audience"}`)));
  out.push(h("div", { class: "board" }, latest.items.map(itemCard)));
  const targets = latest.comment_targets;
  const ready = latest.readiness;
  if (targets.length || ready.length || latest.notes.length) {
    out.push(h("div", { class: "grid cols-3" },
      targets.length ? h("section", { class: "card" }, h("div", { class: "card-head" }, h("h3", null, icon("comment", 15), "Who to comment on")),
        h("div", { class: "card-body" }, targets.map((c) => (typeof c === "object" && c
          ? h("div", null, h("b", null, c.day || ""), " ", h("span", { class: "soft" }, c.who || ""), c.pattern ? h("div", { class: "soft" }, c.pattern) : null)
          : h("div", { class: "soft" }, String(c)))))) : null,
      ready.length ? h("section", { class: "card" }, h("div", { class: "card-head" }, h("h3", null, icon("check-circle", 15), "Inbound readiness")),
        h("div", { class: "card-body" }, h("ul", { class: "checks" }, ready.map((c) => {
          const ok = typeof c === "object" && c ? !!c.ok : !/missing/i.test(String(c));
          const words = typeof c === "object" && c ? [c.check, c.note ? h("span", { class: "soft" }, ` ${c.note}`) : null] : [String(c)];
          return h("li", { class: ok ? "yes" : "no" }, icon(ok ? "check" : "alert", 15), h("span", null, words));
        })))) : null,
      latest.notes.length ? h("section", { class: "card" }, h("div", { class: "card-head" }, h("h3", null, icon("info", 15), "Planner’s notes")),
        h("div", { class: "card-body" }, h("ul", { class: "list" }, latest.notes.map((n) => h("li", null, String(n)))))) : null));
  }
  return out;
}

// Earlier plans, under the form for a new week.
function earlierOf(d) {
  const out = [];
  const earlier = d.boards.slice(1);
  if (earlier.length) {
    out.push(h("div", { class: "section-title" }, h("h2", null, "Earlier plans")));
    out.push(h("section", { class: "panel", style: "padding:0 16px" }, earlier.map((b) => h("details", { class: "fold" },
      h("summary", null, `${b.planned} · ${plural(b.items.length, "post", "posts")} · ${b.inputs.audience || ""}`),
      h("div", { class: "fold-body" }, b.items.map((i) => h("div", { class: "seg-row" }, h("b", null, i.day || ""), h("span", { class: "grow" }, i.angle || ""),
        i.post && i.post.trashed ? h("a", { href: "#~trash" }, "In the Trash") : i.post ? h("a", { href: `#post-${i.post.id}` }, "Open the post") : null)))))));
  }
  return out;
}

