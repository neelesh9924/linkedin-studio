// Schedule: Coming up first (what goes out when: the posts at Publora, then the posting queue in line order with Move
// up, Move down, First, Post now… and Take out, and the posting times still free; Check Publora), getting set up until
// every step is done, then this month (posts used against the limit, the next post, Claude's status). Drawn again, a row
// of Coming up keeps the focus on the same button of the same post.
import { state, h, icon, api, post, put, announce, whileBusy, drawIfChanged, focusFirst, go } from "./core.js";
import { drawWorking } from "./jobs.js";
import { confirmNow } from "./post.js";

let box = null;
let data = null;

export async function render(container) {
  box = container;
  if (!box.firstChild) put(box, h("p", { class: "lede" }, "Loading…"));
  await refresh();
}

export async function refresh() {
  if (!box || state.page !== "schedule") return;
  const reply = await api("/api/schedule");
  if (reply.error || state.page !== "schedule") return;
  data = reply;
  const kept = box.contains(document.activeElement) ? document.activeElement.dataset.keep : null;
  const drew = drawIfChanged(box, JSON.stringify(data, (k, v) => (k === "seconds" || k === "quiet" || k === "progress" || k === "activity" ? undefined : v)), draw);
  tick();
  if (drew && kept) {
    const [, post] = kept.split(":");
    focusFirst(box.querySelector(`[data-keep="${kept}"]:not([disabled])`), box.querySelector(`[data-keep$=":${post}"]:not([disabled])`));
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
  put(box, h("div", { class: "page-width" },
    d.problems.map((p) => h("div", { class: "notice bad" }, icon("alert", 16), h("div", null, p))),
    comingUp(d),
    left.length ? h("section", { class: "panel" },
      h("header", { class: "panel-head" }, h("span", { class: "panel-mark" }, icon("check", 17)),
        h("div", null, h("h2", null, "Getting set up"), h("p", null, `${d.steps.length - left.length} of ${d.steps.length} done`))),
      h("div", { class: "panel-body" }, h("div", { class: "steps" }, d.steps.map((s) => s.done
        ? h("div", { class: "step done" }, h("b", null, s.title), h("span", null, "Done"))
        : h("button", { class: "step", type: "button", onclick: () => go(s.href) }, h("b", null, s.title), h("span", null, s.text)))))) : null,
    h("div", { class: "section-title" }, h("h2", null, "This month")),
    h("div", { class: "grid cols-3" },
      h("section", { class: "panel" }, h("div", { class: "panel-body" },
        h("div", { class: "ring-row" }, ring(d.used, d.limit || d.used || 1),
          h("div", { class: "stat" }, h("span", { class: "label" }, `Posts in ${d.month}`), h("span", { class: "big" }, `${d.used} `,
            h("small", null, d.limit ? `of ${d.limit}` : "no limit")))),
        h("p", { class: "soft" }, `Scheduled or published from here, counted by ${d.tz} month. Publora keeps its own count.`))),
      h("section", { class: "panel" }, h("div", { class: "panel-body stat" },
        h("span", { class: "label" }, "Next post"),
        d.next ? [h("span", { class: "big", style: "font-size:19px" }, d.next.when),
          h("a", { href: `#post-${d.next.id}` }, d.next.first)]
          : [h("span", { class: "big", style: "font-size:19px;color:var(--text-3)" }, "Nothing scheduled"),
            h("span", { class: "soft" }, "Approve and queue a post: it takes your next free posting time.")])),
      h("section", { class: "panel" }, h("div", { class: "panel-body" },
        h("div", { class: "seg-row" }, h("span", { class: "stat" }, h("span", { class: "label" }, "Claude")),
          h("span", { class: `chip ${d.claude.working ? "busy" : ""}` }, d.claude.working || "Idle")),
        h("dl", { class: "facts" },
          d.claude.sign_in ? [h("dt", null, "Account"), h("dd", null, signedIn(d.claude.sign_in))] : null,
          h("dt", null, "Model"), h("dd", null, d.claude.model),
          h("dt", null, "Last run"), h("dd", null, d.claude.last_run || "None yet"),
          h("dt", null, "Health check"), h("dd", null, d.claude.health
            ? h("a", { href: "#~settings-health" }, `${d.claude.health.ok ? "All good" : "Found a problem"}, ${d.claude.health.when}`)
            : h("a", { href: "#~settings-health" }, "Not run yet"))))))));
}

// Coming up: what goes out and when, earliest first. A post at Publora keeps its time (Cancel on Publora, in its gear,
// frees the day); a queued one shows its place in line and the time that gives it, with Move up, Move down, First, Post
// now… and Take out; a posting time nobody has yet says Free. Each button names its post to a screen reader.
function comingUp(d) {
  const atPublora = d.coming.some((c) => c.kind === "publora");
  const check = atPublora ? h("button", { class: "btn small ghost", type: "button", "data-keep": "check-publora" }, icon("refresh", 14), h("span", null, "Check Publora")) : null;
  if (check) check.addEventListener("click", () => whileBusy(check, async () => {
    const reply = await post("/api/posts/refresh", {});
    announce(reply.error || reply.said, { urgent: !!reply.error });
    window.dispatchEvent(new Event("studio:poll"));
  }));
  const times = h("button", { class: "btn small ghost", type: "button", onclick: () => go("#~settings-posting") }, icon("clock", 14),
    h("span", null, "Posting times"));
  return h("section", { class: "panel", id: "coming-up", "aria-labelledby": "coming-title" },
    h("header", { class: "panel-head" }, h("span", { class: "panel-mark" }, icon("calendar", 17)),
      h("div", null, h("h2", { id: "coming-title" }, "Coming up"),
        h("p", null, `Your posting times: ${d.posting}. Each post you queue takes the next free one, a post a day at most, and `
          + `goes to Publora by itself once its time is ${d.window} days away${d.at_once ? ` and fewer than ${d.at_once} are waiting there` : ""}, `
          + "while the studio is open. Once a post’s time has passed, the studio asks Publora whether it went out.")),
      h("span", { class: "panel-tools" }, times, check)),
    d.coming.length ? h("ol", { class: "coming" }, d.coming.map(comingRow))
      : h("div", { class: "panel-body soft" }, "Nothing is coming up. Approve and queue a post: it takes your next free posting time."));
}

function comingRow(c) {
  if (c.kind === "free") {
    return h("li", { class: "coming-row free" }, h("span", { class: "coming-when" }, c.when),
      h("span", { class: "coming-what soft" }, "Free: no post yet"));
  }
  const p = c.post;
  const open = h("button", { class: "coming-what", type: "button", title: p.first, "data-keep": `open:${p.id}`, onclick: () => go(`#post-${p.id}`) },
    h("b", null, p.first));
  const chip = c.kind === "publora" ? h("span", { class: `chip ${p.kind}` }, p.status === "scheduling" ? "Sending" : "At Publora")
    : h("span", { class: "chip ok" }, `Queued · ${c.place} of ${c.of}`);
  const tools = c.kind === "queued" ? h("span", { class: "coming-tools" },
    moveButton(c, "up", "arrow-up", "Move up", c.place === 1),
    moveButton(c, "down", "arrow-down", "Move down", c.place === c.of),
    moveButton(c, "first", "chevrons-up", "First in line", c.place === 1),
    postNow(c),
    takeOut(c)) : null;
  return h("li", { class: `coming-row ${c.kind}` }, h("span", { class: "coming-when" }, c.when || "No free time"), open, chip, tools,
    c.error ? h("small", { class: "coming-note" }, icon("alert", 13), c.error) : null);
}

function moveButton(c, how, glyph, words, off) {
  const b = h("button", { class: "btn small ghost square", type: "button", disabled: off, title: words,
    "aria-label": `${words}: ${c.post.first}`, "data-keep": `${how}:${c.post.id}` }, icon(glyph, 14));
  b.addEventListener("click", () => whileBusy(b, async () => {
    const reply = await post("/api/queue/move", { id: c.post.id, how });
    announce(reply.error || `${words}.`, { urgent: !!reply.error });
    window.dispatchEvent(new Event("studio:poll"));
    await refresh();
  }));
  return b;
}

// Post now…: the post's own dialog (post.js), over this page, with the post as the studio has it now. It leaves the line
// as it goes, and the posts behind it move up.
function postNow(c) {
  const b = h("button", { class: "btn small ghost", type: "button", "aria-label": `Post now: ${c.post.first}`,
    "data-keep": `now:${c.post.id}` }, h("span", null, "Post now…"));
  b.addEventListener("click", () => whileBusy(b, async () => {
    const p = await api(`/api/post/${c.post.id}`);
    if (p.error) return announce(p.error, { urgent: true });
    confirmNow(p, refresh);
  }));
  return b;
}

function takeOut(c) {
  const b = h("button", { class: "btn small ghost", type: "button", "aria-label": `Take out of the queue: ${c.post.first}`,
    "data-keep": `out:${c.post.id}` }, h("span", null, "Take out"));
  b.addEventListener("click", () => whileBusy(b, async () => {
    const reply = await post(`/api/post/${c.post.id}/unqueue`, {});
    announce(reply.error || "Out of the queue. It stays approved, in your posts.", { urgent: !!reply.error });
    window.dispatchEvent(new Event("studio:poll"));
    await refresh();
  }));
  return b;
}

// Who Claude runs as: "Signed in as <account> (<plan>)", or a link to Settings › Claude when it is not (or can't tell).
function signedIn(si) {
  if (si.signed_in) return si.account ? `Signed in as ${si.account}${si.plan ? ` (${si.plan})` : ""}` : "Signed in";
  return h("a", { href: "#~settings-claude" }, si.ok === false && si.error ? `Could not tell: ${si.error}` : "Not signed in");
}
