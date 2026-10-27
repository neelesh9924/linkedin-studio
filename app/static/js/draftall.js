// Draft all, on the Planner's week plan (app/draft_all.py): Claude writes every planned post that has no draft yet, one at
// a time, each an ordinary draft that lands on its card and in the posts as a single Draft this does. It asks first. While
// it runs: "Writing 2 of 5" with Stop, each step said to a screen reader. At the end: how many were written and which did
// not finish (Try again is on that card), until dismissed. The planner draws this bar under "This week" (draftAllBar).
import { h, icon, post, plural, announce, whileBusy, showDialog, closeDialog, closeButton, focusFirst } from "./core.js";

const said = { step: "", end: "", saw: false };   // what was said aloud already, so a redraw says nothing twice
let want = "";                                    // where the focus goes once the bar is drawn again: "stop", "start"

const poll = () => window.dispatchEvent(new Event("studio:poll"));
const quoted = (angle) => `“${String(angle || "A planned post").replace(/\s+/g, " ").slice(0, 90)}${String(angle || "").length > 90 ? "…" : ""}”`;

export function draftAllBar(board) {
  const d = board && board.draft_all;
  if (!d) return null;
  // The bar is drawn again on each change: the focus that was on one of its buttons moves to the new one in its place.
  const on = document.activeElement && document.activeElement.closest(".draft-all") ? document.activeElement.dataset.act || "" : "";
  const bar = d.running ? runningBar(board, d.running) : d.last || d.left
    ? h("div", { class: "draft-all-wrap" }, d.last ? endLine(board, d.last) : null, d.left ? startRow(board, d.left) : null) : null;
  const target = want || on;
  want = "";
  if (target) {
    setTimeout(() => focusFirst(bar && bar.querySelector(`[data-act="${target}"]`), bar && bar.querySelector("button"),
      "#plannerPage .board button"), 0);
  }
  return bar;
}

function startRow(board, left) {
  const go = h("button", { class: "btn small", type: "button", "data-act": "start" }, icon("sparkle", 14),
    h("span", null, left === 1 ? "Draft the last one" : `Draft all ${left}`));
  go.addEventListener("click", () => confirmStart(board, left));
  return h("div", { class: "seg-row draft-all" }, go,
    h("span", { class: "soft" }, `${plural(left, "planned post has", "planned posts have")} no draft yet. Claude can write them one at a time while you work.`));
}

function confirmStart(board, left) {
  const yes = h("button", { class: "btn primary", type: "button" }, icon("sparkle", 15), h("span", null, "Draft all"));
  const out = h("div", { class: "results" });
  yes.addEventListener("click", () => whileBusy(yes, async () => {
    const reply = await post(`/api/planner/${board.id}/draft-all`, {});
    if (reply.error) {
      out.replaceChildren(h("div", { class: "result bad" }, icon("alert", 15), h("div", null, reply.error)));
      return announce(reply.error, { urgent: true });
    }
    closeDialog();
    want = "stop";
    said.saw = true;
    poll();
  }));
  showDialog(h("h2", null, left === 1 ? "Draft the 1 planned post left?" : `Draft all ${left} planned posts?`),
    h("p", null, "Each is a Claude run, written one at a time. You can keep working; Stop ends the rest."),
    out,
    h("div", { class: "dialog-foot" }, closeButton("Not now"), yes));
}

function runningBar(board, run) {
  const item = board.items.find((i) => i.job && i.job.id === run.job) || null;
  const waiting = item && item.job.status === "queued";
  const words = `Writing ${run.at} of ${run.of}`;
  const key = `${run.job}:${run.at}`;
  if (said.step !== key) {
    said.step = key;
    said.saw = true;
    announce(`Draft all: ${words}${item ? `, ${quoted(item.angle)}` : ""}.`);
  }
  const stop = h("button", { class: "btn small", type: "button", "data-act": "stop", "aria-label": `Stop Draft all (${words.toLowerCase()})` },
    icon("stop", 14), h("span", null, "Stop"));
  stop.addEventListener("click", () => whileBusy(stop, async () => {
    const reply = await post("/api/planner/draft-all/stop", {});
    announce(reply.error || reply.said, { urgent: !!reply.error });
    want = "start";
    poll();
  }));
  return h("div", { class: "notice busy draft-all", role: "group", "aria-label": "Draft all" },
    h("i", { class: "pulse", "aria-hidden": "true" }),
    h("div", null, h("strong", null, words), waiting ? "Waits for the job under way, then carries on." : item ? quoted(item.angle) : "One at a time; you can keep working."),
    stop);
}

// How it ended: how many were written of how many, and the ones that did not finish by name (Try again is on each card).
function endLine(board, last) {
  const failed = last.failed || [];
  const words = last.written === last.of ? `Draft all wrote ${plural(last.written, "post", "posts")}. Each is on its card and in your posts.`
    : `Draft all wrote ${last.written} of ${plural(last.of, "planned post", "planned posts")}.`;
  const why = failed.length ? `${failed.map((f) => quoted(f.angle)).join(", ")} did not finish: Try again is on ${failed.length === 1 ? "its card" : "their cards"}.` : "";
  const key = `${last.job}`;
  if (said.saw && said.end !== key) {
    said.end = key;
    announce(`${words} ${why}`.trim(), { urgent: !!failed.length });
  }
  const dismiss = h("button", { class: "btn small ghost", type: "button", "data-act": "dismiss", "aria-label": "Dismiss what Draft all did" }, "Dismiss");
  dismiss.addEventListener("click", () => whileBusy(dismiss, async () => {
    const reply = await post(`/api/jobs/${last.job}/dismiss`, {});
    if (reply.error) announce(reply.error, { urgent: true });
    want = "start";
    poll();
  }));
  return h("div", { class: `notice ${failed.length ? "bad" : "ok"} draft-all` }, icon(failed.length ? "alert" : "check", 16),
    h("div", null, h("strong", null, words), why || null), dismiss);
}
