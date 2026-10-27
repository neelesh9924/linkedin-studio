// A job of Claude's wherever a page shows one: its card while it works (what it is doing, a timer, Cancel), updated in
// place so the focus stays on Cancel through the polls; its card when it did not finish (Try again, Dismiss); and, for
// every job, what its end says: once aloud, as a note in the corner when its result is not in sight, and in the
// window's title and the tab's icon (● Working, ✓ Ready, ! Needs you), as in the owner's other studios.
import { state, h, icon, post, put, clockOf, announce, whileBusy, onPoll, setTitle, title, toast } from "./core.js";

// The card of a job at work, in box: drawn once, then only its words and timer change.
export function drawWorking(box, job, { cancel = true, label = "" } = {}) {
  let card = box.querySelector(`.working[data-job="${job.id}"]`);
  if (!card) {
    const stop = cancel ? h("button", { class: "btn small", type: "button", "data-act": "cancel" }, "Cancel") : null;
    if (stop) stop.addEventListener("click", () => whileBusy(stop, () => post(`/api/jobs/${job.id}/cancel`, {})));
    card = h("div", { class: "working", "data-job": job.id },
      h("div", { class: "working-row" }, h("i", { class: "pulse" }),
        h("div", null, h("b", null, label || job.doing), h("span", { class: "working-step" })),
        h("span", { class: "timer" }), stop));
    put(box, card);
  }
  const step = card.querySelector(".working-step");
  if (step.textContent !== job.progress) step.textContent = job.progress;
  const timer = card.querySelector(".timer");
  const time = job.status === "running" ? clockOf(job.seconds) : "";
  if (timer.textContent !== time) timer.textContent = time;
  return card;
}

// The card of a job that did not finish: what stopped it, Claude's reply when it came in the wrong shape, Try again
// (the same job) and Dismiss. Where the focus goes when the card goes is the page's: the new card's Cancel after Try
// again, the control that starts the job after Dismiss (tools.drawOut, editor.drawSide).
export function problemCard(job, { retry = true, onDone = () => {} } = {}) {
  const again = retry ? h("button", { class: "btn small", type: "button", "data-act": "retry" }, icon("refresh", 14), h("span", null, "Try again")) : null;
  const dismiss = h("button", { class: "btn small ghost", type: "button", "data-act": "dismiss" }, "Dismiss");
  if (again) again.addEventListener("click", () => whileBusy(again, async () => {
    const reply = await post(`/api/jobs/${job.id}/retry`, {});
    announce(reply.error || "Trying again.", { urgent: !!reply.error });
    onDone();
  }));
  dismiss.addEventListener("click", () => whileBusy(dismiss, async () => {
    const reply = await post(`/api/jobs/${job.id}/dismiss`, {});
    if (reply.error) announce(reply.error, { urgent: true });
    onDone();
  }));
  return h("div", { class: "problem", "data-job": job.id },
    h("b", null, `${job.title} did not finish`),
    job.status === "unparsed"
      ? [h("div", null, "Claude answered, but not in the shape the app reads. Trying again usually fixes it."),
        h("details", { class: "fold" }, h("summary", null, "Claude’s reply"), h("pre", { class: "mono-out" }, job.raw))]
      : h("div", null, job.error || "It stopped before finishing."),
    h("div", { class: "form-foot" }, again, dismiss));
}

// ---------- every job's end ----------

const MARKS = { busy: "● Working — ", ready: "✓ Ready — ", needs: "! Needs you — " };
const DOTS = { busy: "#3355e0", ready: "#1f9d63", needs: "#d6452f" };
const seen = new Set();            // jobs under way at the last poll
let first = true;
let iconText;

// Where a job's result shows: is the owner looking at it now?
export function inSight(job) {
  if (document.hidden) return false;
  const page = state.page;
  if (job.post_id && page === "post" && state.postId === job.post_id) return true;
  if ((job.kind === "plan" || (job.kind === "draft" && job.plan_item_id)) && page === "planner") return true;
  if (job.kind === "interview") return page === "bank";
  if (job.kind === "voice") return page === "voice";
  if (job.source === "tools") return page === "tools";
  return false;
}

async function tabIcon(kind) {
  const link = document.querySelector('link[rel="icon"]');
  if (!link) return;
  if (!kind) return void link.setAttribute("href", "/static/icon.svg");
  if (iconText === undefined) iconText = await fetch("/static/icon.svg").then((r) => (r.ok ? r.text() : "")).catch(() => "");
  if (state.titleMark !== MARKS[kind] || !iconText.includes("</svg>")) return;
  const dot = `<circle cx="25" cy="25" r="6" fill="${DOTS[kind]}" stroke="#ffffff" stroke-width="2"/>`;
  link.setAttribute("href", `data:image/svg+xml,${encodeURIComponent(iconText.replace("</svg>", `${dot}</svg>`))}`);
}

function setMark(kind) {
  const text = MARKS[kind] || "";
  if (state.titleMark === text) return;
  state.titleMark = text;
  setTitle(title());
  tabIcon(kind);
}

function afterPoll(data) {
  const now = new Set(data.jobs.map((j) => j.id));
  const endedNow = first ? [] : data.ended.filter((j) => seen.has(j.id) && !now.has(j.id));
  for (const job of endedNow) {
    const words = job.summary || `${job.title} ended`;
    if (job.status === "cancelled") continue;
    if (inSight(job)) announce(job.status === "done" ? words : `${words}: ${job.error || "it stopped early"}`, { urgent: job.status !== "done" });
    else toast(words, job.href);
  }
  // The window's title and the tab's icon: working; then, if it ended while the window was not in front, Ready or
  // Needs you until it is looked at.
  if (data.jobs.length) setMark("busy");
  else if (state.titleMark === MARKS.busy) {
    const needs = endedNow.some((j) => j.status === "failed" || j.status === "unparsed");
    setMark(document.hasFocus() ? "" : needs ? "needs" : "ready");
  }
  seen.clear();
  for (const id of now) seen.add(id);
  first = false;
}

export function init() {
  onPoll(afterPoll);
  window.addEventListener("focus", () => {
    if (state.titleMark === MARKS.ready || state.titleMark === MARKS.needs) setMark("");
  });
}
