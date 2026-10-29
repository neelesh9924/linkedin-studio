// A post at the top: its title, where it stands (the chip, drawn again after each poll), and the next step (Approve and
// queue, which gives it the next free posting time, or Approve only, then Add to queue or Schedule… for a time of its
// own; Take out of the queue while it waits; Check now once it is at Publora, which asks whether it went out; Open on
// LinkedIn and New draft from this once it is published); the gear (its title, its versions to compare with now and go
// back to, its earlier chats, Cancel on Publora, New draft from this, Move to Trash…); and the Schedule… dialog (a time,
// then the final text, picture, time and first comment to confirm).
import { $, state, h, icon, api, post, put, number, plural, announce, whileBusy, focusFirst, drawIfChanged, showDialog,
  closeDialog, closeButton, setTitle, go, toast, onPoll, currentPost } from "./core.js";
import { renderPost, saveNow, noticeBox, nextBlank, editorState } from "./editor.js";
import { statusOf, renderList, openNew } from "./sidebar.js";
import { wordDiff } from "./wdiff.js";
import { beforeYouConfirm } from "./precheck.js";

let shown = null;      // the post as the studio last said it
let asking = 0;        // the post being asked for, while its answer is on the way
let answer = null;     // that answer
let again = null;      // asked for the same post meanwhile: one more ask once that answer is in
let againFor = 0, againLoud = false;

// Asking again for the post whose answer is on the way never drops the ask: that answer may predate a change just made
// (Approve refused, a save, Claude's rewrite), so it asks once more after it, and every caller waits for that.
export function loadPost(id, { quiet = false } = {}) {
  if (asking === id) {
    if (againFor !== id) {
      againFor = id;
      againLoud = false;
      again = answer.then(() => askAgain(id));
    }
    againLoud ||= !quiet;
    return again;
  }
  asking = id;
  answer = fetchPost(id, quiet).finally(() => { if (asking === id) asking = 0; });
  return answer;
}

function askAgain(id) {
  const loud = againLoud;
  if (againFor === id) { againFor = 0; again = null; againLoud = false; }
  return state.postId === id ? loadPost(id, { quiet: !loud }) : undefined;
}

async function fetchPost(id, quiet) {
  if (shown && shown.id !== id) shown = null;   // the gear and the top bar never act on the post shown before
  const data = await api(`/api/post/${id}`);
  if (state.postId !== id) return;
  if (data.error) {
    if (data.gone || data.trashed) return void lost(id, data.trashed);
    if (!quiet) announce(data.error, { urgent: true });
    return;
  }
  shown = data;
  renderPost(data, () => loadPost(id, { quiet: true }));   // makes the stage (and its notice) the first time
  renderTop(data);
  renderNotice(data);
}

// The post went (to the Trash, or for good) while it was open: it leaves the list, and the page goes, once and quietly,
// to the Trash or to the first post.
function lost(id, trashed) {
  shown = null;
  state.posts = state.posts.filter((p) => p.id !== id);
  renderList();
  history.replaceState(null, "", trashed ? "#~trash" : "#~posts");
  window.dispatchEvent(new HashChangeEvent("hashchange"));
}

export const shownPost = () => shown;

// ---------- the top bar ----------

let chip = null;
function renderTop(p) {
  setTitle(`${p.first.slice(0, 60)} · LinkedIn Studio`);
  $("title").textContent = p.title;
  $("title").title = p.title;
  drawChip(p);
  $("postGear").hidden = false;
  const actions = $("topActions");
  drawIfChanged(actions, JSON.stringify([p.id, p.status, p.queued, p.busy, p.when, p.can_retry, p.can_back, p.slots, p.link]), () => {
    const on = actions.contains(document.activeElement) ? document.activeElement.dataset.act : null;
    put(actions, ...mainActions(p));
    if (on) focusFirst(actions.querySelector(`[data-act="${on}"]`), actions.querySelector("button, a"), $("postGear"));
  });
}

// Where the post stands, in the sidebar's words (statusOf): from the full post when it is drawn, and from the list after
// each poll, so the chip moves with the sidebar's line (Claude's working minutes among it). The chip sits in a live
// region: the minutes are shown but not said, so a screen reader hears the post move on, not each minute.
function drawChip(p) {
  const status = statusOf(p);
  if (!chip) chip = h("span", { class: "chip" }, h("i", { class: "dot", "aria-hidden": "true" }), h("span", { class: "chip-text" }));
  if (chip.parentNode !== $("status")) $("status").replaceChildren(chip);
  const kind = `chip ${status.kind}`.trim();
  if (chip.className !== kind) chip.className = kind;
  const text = chip.lastChild;
  const [said, ticking = ""] = status.text.split(/(?= · \d+ min$)/);
  if (!text.firstChild) text.append(document.createTextNode(""), h("span", { "aria-hidden": "true" }));
  if (text.firstChild.data !== said) text.firstChild.data = said;
  if (text.lastChild.textContent !== ticking) text.lastChild.textContent = ticking;
}

function chipAfterPoll() {
  if (state.page !== "post" || !shown || shown.id !== state.postId) return;
  const p = currentPost();
  if (p) drawChip(p);
}

function act(label, kind, name, work, glyph) {
  const button = h("button", { class: `btn ${kind}`.trim(), type: "button", "data-act": name }, glyph ? icon(glyph, 15) : null, h("span", null, label));
  button.addEventListener("click", () => whileBusy(button, () => work(button)));
  return button;
}

function mainActions(p) {
  switch (p.status) {
    case "draft":
      return [act("Approve only", "", "approve", approve),
        act("Approve and queue", "primary", "queue", queueIt, "check")];
    case "approved":
      if (p.queued) {
        return [act("Back to draft", "ghost", "back", () => change("unapprove", "Back in draft, and out of the queue. You can edit it again.")),
          act("Take out of the queue", "", "unqueue", () => change("unqueue", "Out of the queue. It stays approved."), "x")];
      }
      return [act("Back to draft", "ghost", "back", () => change("unapprove", "Back in draft. You can edit it again.")),
        act("Schedule…", "", "schedule", () => openSchedule(), "clock"),
        act("Add to queue", "primary", "queue", queueIt, "list")];
    case "scheduling":
      return [h("span", { class: "top-when" }, h("i", { class: "pulse" }), "Sending to Publora…")];
    case "scheduled": {   // its time is in the chip, once
      const check = act("Check now", "ghost", "refresh", checkNow, "refresh");
      check.title = "Ask Publora whether it went out. Nothing is sent.";
      return [check];
    }
    case "failed":   // failed at Publora itself, it can't be sent again: a new draft can
      return [p.can_back ? act("Back to draft", "ghost", "back", () => change("unapprove", "Back in draft.")) : null,
        p.can_retry ? act("Try again", "primary", "retry", () => change("retry", "Scheduled on Publora."), "refresh") : null,
        p.can_back || p.can_retry ? null : act("New draft from this", "", "copy", () => copyPost(p), "copy")].filter(Boolean);
    case "published":
      return [h("span", { class: "top-when" }, icon("check-circle", 15), p.when ? `Published ${p.when}` : "Published"),
        p.link ? outLink(p.link, "Open on LinkedIn", "", "open") : null,
        act("New draft from this", "", "copy", () => copyPost(p), "copy")].filter(Boolean);
    default:
      return [h("span", { class: "top-when" }, "Cancelled on Publora. It was never published."),
        act("New draft from this", "", "copy", () => copyPost(p), "copy")];
  }
}

// A link out of the studio (the post on LinkedIn, the Publora dashboard): a new window, which a screen reader is told.
function outLink(href, label, size = "", name = null) {
  return h("a", { class: `btn ${size}`.trim(), href, target: "_blank", rel: "noreferrer", "data-act": name },
    icon("external", size ? 14 : 15), h("span", null, label), h("span", { class: "sr-only" }, " (opens in a new window)"));
}

// Check now: Publora's word on it, read at once (nothing is sent). Its answer stays in the notice while the post stands
// as it was heard: published, failed in Publora's words, or still waiting, with the time it asked.
let heard = null;
async function checkNow() {
  if (!shown) return;
  const id = shown.id;
  refused = "";
  heard = null;
  const reply = await post(`/api/post/${id}/refresh`, {});
  if (reply.error) {
    refuse(reply.error);
    announce(reply.error, { urgent: true });
  } else {
    heard = { id, status: reply.status, words: reply.said, seen: JSON.stringify(reply.waiting || null) };
    announce(reply.said, { urgent: reply.status === "failed" });
  }
  await refresh();
}

// New draft from this: a draft with its text, first comment and picture, opened at once (this post stays as it is).
async function copyPost(p) {
  const reply = await post(`/api/post/${p.id}/copy`, {});
  if (reply.error) return announce(reply.error, { urgent: true });
  if ($("dialog").open) closeDialog();
  announce("A new draft from it is open. This one stays as it was.");
  openNew(reply.post);
}

// The post's notice above it: Claude at work on it, a send that failed, Publora's warnings, a refusal just now (gone as
// soon as the text changes: typed here, or rewritten by Claude), Check now's answer, and a due post's light check.
let refused = "";
let refusedText = null;   // the text it was refused for
function refuse(words) {
  refused = words;
  refusedText = editorState.data ? editorState.data.text : null;
}
const HEARD = { published: ["ok", "check-circle"], failed: ["bad", "alert"], scheduled: ["soft", "clock"] };
function renderNotice(p) {
  const box = noticeBox();
  if (refused && refusedText !== null && p.text !== refusedText) refused = "";
  // Check now's answer gives way once the post moves on, or the light check has heard something newer. (A post fetched
  // before the answer still says what it said before: that is not newer.)
  if (heard && (heard.id !== p.id || heard.status !== p.status)) heard = null;
  else if (heard && JSON.stringify(p.waiting || null) !== heard.seen) {
    if (heard.fresh) heard = null;
  } else if (heard) heard.fresh = true;
  let kind = "";
  let words = null;
  if (refused) {
    kind = "bad";
    const next = p.slots && p.status === "draft" ? h("button", { class: "btn small", type: "button", onclick: () => nextBlank() }, "Next blank") : null;
    words = [icon("alert", 16), h("div", null, refused), next];
  } else if (p.busy) {
    kind = "busy";
    words = [h("i", { class: "pulse" }), h("div", null, h("strong", null, "Claude is working on this post."), "Its text waits until Claude is done; the chat on the right shows each step.")];
  } else if (heard) {
    const [tone, glyph] = HEARD[heard.status] || HEARD.scheduled;
    kind = tone;
    words = [icon(glyph, 16), h("div", null, heard.words)];
  } else if (p.error) {
    kind = p.status === "failed" ? "bad" : "";
    words = [icon("alert", 16), h("div", null, p.error)];
  } else if (p.waiting) {
    kind = "soft";
    words = [icon(p.waiting.failed ? "alert" : "clock", 16), h("div", null, p.waiting.text)];
  } else if (p.status === "approved" && p.queued) {
    kind = "soft";
    words = [icon("clock", 16), h("div", null, p.when
      ? `In the queue: it goes out ${p.when}. It goes to Publora by itself ${p.window} days before, while the studio is open; `
        + "the Planner's Coming up moves it. The text and picture are locked: Back to draft unlocks them, and takes it out of the queue."
      : "In the queue, but none of your posting times is free within a year. Settings › Posting times adds days.")];
  } else if (p.status === "approved") {
    kind = "soft";
    words = [icon("lock", 16), h("div", null, "Approved: the text and picture are locked. Add to queue gives it your next free "
      + `posting time (${p.posting}); Schedule… picks a time of its own. Back to draft unlocks them.`)];
  }
  drawIfChanged(box, JSON.stringify([refused, p.busy, p.error, p.status, p.queued, p.when, p.slots, heard && heard.words, p.waiting]), () => {
    box.hidden = !words;
    box.className = `notice ${kind}`.trim();
    if (words) put(box, words);
    else box.replaceChildren();
  });
}

async function refresh() {
  if (shown) await loadPost(shown.id, { quiet: true });
}

async function approve() {
  if (!shown) return;
  refused = "";
  const saved = await saveNow();
  if (saved && saved.error) return;
  const reply = await post(`/api/post/${shown.id}/approve`, {});
  if (reply.error) {
    refuse(reply.error);
    announce(reply.error, { urgent: true });
  } else {
    announce("Approved. Add it to the queue, or pick a time with Schedule….");
    window.dispatchEvent(new Event("studio:poll"));   // the sidebar's line follows at once
  }
  await refresh();
  if (!reply.error) focusFirst($("topActions").querySelector('[data-act="queue"]'));
}

// Approve and queue (a draft) and Add to queue (an approved post): one press. It goes in at the end of the line and takes
// the next free posting time; one inside the window goes to Publora at once. Before you confirm's warnings come first,
// when there are any (a link in the text, a picture kept but not on the post): then it asks. A draft with a blank left is
// refused by the studio as Approve refuses it, with Next blank.
async function queueIt() {
  if (!shown) return;
  refused = "";
  const p = shown;
  if (p.status === "draft") {
    const saved = await saveNow();
    if (saved && saved.error) return;
  }
  const check = p.status === "draft" && p.slots ? null : beforeYouConfirm(p, null);
  if (!check) return sendToQueue(p);
  const yes = h("button", { class: "btn primary", type: "button" }, icon("check", 15), h("span", null, p.status === "draft" ? "Approve and queue" : "Add to queue"));
  yes.addEventListener("click", () => whileBusy(yes, async () => {
    closeDialog();
    await sendToQueue(p);
  }));
  showDialog(h("h2", null, "Queue it as it is?"), h("p", null, `It takes your next free posting time (${p.posting}).`), check,
    h("div", { class: "dialog-foot" }, closeButton("Not yet"), yes));
}

async function sendToQueue(p) {
  const reply = await post(`/api/post/${p.id}/queue`, {});
  if (reply.error && reply.ok === undefined) {
    refuse(reply.error);
    announce(reply.error, { urgent: true });
  } else if (reply.ok === false) {
    announce(`It did not go through: ${reply.error} Try again resends the very same request.`, { urgent: true });
  } else {
    announce(reply.said);
    window.dispatchEvent(new Event("studio:poll"));   // the sidebar's line follows at once
  }
  await refresh();
  focusFirst($("topActions").querySelector("button"), $("postGear"));
}

async function change(what, said) {
  if (!shown) return;
  refused = "";
  const reply = await post(`/api/post/${shown.id}/${what}`, {});
  if (reply.error) {
    refuse(reply.error);
    announce(reply.error, { urgent: true });
  } else if (reply.ok === false) {
    announce(reply.error || "It did not go through.", { urgent: true });
  } else {
    announce(said);
    window.dispatchEvent(new Event("studio:poll"));   // the sidebar's line follows at once
  }
  await refresh();
}

// ---------- Schedule… ----------

function openSchedule() {
  const p = shown;
  const sch = p && p.schedule;
  if (!sch) return;
  const when = h("input", { class: "input", type: "datetime-local", id: "when", min: sch.min, max: sch.max, value: sch.quick[0] ? sch.quick[0].value : "" });
  const picks = h("div", { class: "picks", role: "group", "aria-label": "Recommended times" }, sch.quick.map((q, i) => {
    const pick = h("button", { class: "pick", type: "button", "aria-pressed": String(i === 0), "data-when": q.value }, q.label);
    pick.addEventListener("click", () => {
      when.value = q.value;
      picks.querySelectorAll(".pick").forEach((b) => b.setAttribute("aria-pressed", String(b === pick)));
    });
    return pick;
  }));
  when.addEventListener("input", () => picks.querySelectorAll(".pick").forEach((b) => b.setAttribute("aria-pressed", "false")));
  const err = h("div", { class: "results" });
  const next = h("button", { class: "btn primary", type: "button" }, "Continue");
  next.addEventListener("click", () => {
    if (!when.value || !when.checkValidity()) {
      put(err, h("div", { class: "result bad" }, icon("alert", 15), h("div", null, "Pick a time between 2 minutes and 14 days from now.")));
      announce("Pick a time between 2 minutes and 14 days from now.", { urgent: true });
      return void when.focus();
    }
    confirmSchedule(when.value);
  });
  const publora = p.publora.key ? null : h("div", { class: "result warn" }, icon("alert", 15),
    h("div", null, "Add your Publora key to linkedin-skills\\.env before scheduling."));
  // The recommended times are your free posting times (Settings › Posting times), after the queue's
  const free = sch.quick.length ? null : h("p", { class: "soft" }, `Every one of your posting times in the next ${p.window} days has a post. Pick any time.`);
  showDialog(h("h2", null, "When should it go out?"),
    h("p", { class: "soft" }, `${p.used} of ${p.limit} posts used in ${p.month}. Between 2 minutes and 14 days ahead.`),
    publora,
    h("div", { class: "form" }, h("label", { class: "field" }, h("span", { class: "field-label" }, `Date and time (${state.tz})`), when), picks, free),
    err,
    h("div", { class: "dialog-foot" }, closeButton("Cancel"), next));
}

function inWords(value) {
  const [d, t] = value.split("T");
  const [y, mo, da] = d.split("-").map(Number);
  const [hh, mi] = t.split(":").map(Number);
  return new Date(y, mo - 1, da, hh, mi).toLocaleString("en-IN", { weekday: "long", day: "numeric", month: "long",
    hour: "numeric", minute: "2-digit", hour12: true });
}

function confirmSchedule(value) {
  const p = shown;
  const go = h("button", { class: "btn primary", type: "button" }, icon("plane", 15), h("span", null, "Schedule it"));
  const out = h("div", { class: "results" });
  const back = h("button", { class: "btn", type: "button", onclick: () => openSchedule() }, "Change the time");
  go.addEventListener("click", () => whileBusy(go, async () => {
    const reply = await post(`/api/post/${p.id}/schedule`, { when: value, first_comment: p.first_comment });
    if (reply.error && reply.ok === undefined) {
      put(out, h("div", { class: "result bad" }, icon("alert", 15), h("div", null, reply.error)));
      return announce(reply.error, { urgent: true });
    }
    closeDialog();
    if (reply.ok === false) announce(`It did not go through: ${reply.error} Try again resends the very same request.`, { urgent: true });
    else announce("Scheduled on Publora.");
    await refresh();
    focusFirst($("topActions").querySelector("button"), $("postGear"));
  }));
  showDialog(h("h2", null, "Schedule this post?"),
    h("p", null, h("b", null, inWords(value)), ` ${state.tz}, through Publora. This uses 1 of your ${p.limit} posts for the month (${p.used} used so far).`),
    beforeYouConfirm(p, value),
    h("div", { class: "textbox confirm-text", tabindex: "0", "aria-label": "The final text" }, p.text),
    p.picture ? h("img", { class: "confirm-picture", src: p.picture.url, alt: "The picture that goes out with it" }) : null,
    p.first_comment ? [h("h3", { style: "margin-top:12px" }, "First comment"), h("div", { class: "textbox" }, p.first_comment)] : null,
    out,
    h("div", { class: "dialog-foot" }, back, closeButton("Not yet"), go));
}

// ---------- the gear ----------

async function openGear() {
  const p = shown;
  if (!p || p.id !== state.postId) return;
  const name = h("input", { class: "input", value: p.title, maxlength: 120, "aria-describedby": "titleHint" });
  const keep = h("button", { class: "btn small", type: "button" }, "Save the title");
  const said = h("div", { class: "results" });
  keep.addEventListener("click", () => whileBusy(keep, async () => {
    const reply = await post(`/api/post/${p.id}/title`, { title: name.value });   // the title alone, in any state
    put(said, h("div", { class: `result ${reply.error ? "bad" : "ok"}` }, icon(reply.error ? "alert" : "check", 15), h("div", null, reply.error || "Saved.")));
    announce(reply.error || "Title saved.", { urgent: !!reply.error });
    await refresh();
  }));
  const versions = h("div", { class: "results" }, h("p", { class: "soft" }, "Loading its versions…"));
  const danger = h("div", { class: "zone" },
    p.status === "scheduled" ? h("div", { class: "danger-row" }, h("span", null, "Cancel on Publora: it will not be published. The text stays here."),
      gearAct("Cancel on Publora…", () => confirmCancel(p))) : null,
    ["scheduled", "published", "failed", "cancelled"].includes(p.status)
      ? h("div", { class: "danger-row" }, h("span", null, "Its status and history on Publora."),
        outLink(p.dashboard, "Publora dashboard", "small")) : null,
    h("div", { class: "danger-row" }, h("span", null, "New draft from this: its text, first comment and picture in a new draft. This post stays as it is."),
      gearAct("New draft from this", (event) => whileBusy(event.currentTarget, () => copyPost(p)))),
    p.deletable ? h("div", { class: "danger-row" }, h("span", null, "Move to Trash: it goes with its versions, chat and pictures. Put it back, or delete it forever, from the Trash."),
      gearAct("Move to Trash…", () => confirmTrash(p), "danger"))
      : h("p", { class: "soft" }, p.trash_why || "This post can’t go to the Trash just now."));
  showDialog(h("h2", null, p.title),
    h("label", { class: "field" }, h("span", { class: "field-label" }, "Title (only you see it)"), name),
    h("div", { class: "form-foot", style: "margin-top:8px" }, keep, h("span", { class: "soft", id: "titleHint" }, "The list shows the post’s first line.")),
    said,
    h("section", { class: "zone", "aria-label": "Versions" }, h("h3", null, "Versions"),
      h("p", { class: "soft" }, "Each change Claude makes is kept, and your own edits: before Claude’s change, when you leave the text, before a cut of a third or more, and when you approve it. Compare with now shows what changed since; going back is kept too, so it can be undone."),
      versions),
    danger,
    h("div", { class: "dialog-foot" }, closeButton("Close")));
  drawVersions(p, versions);
}

function gearAct(label, work, kind = "") {
  const button = h("button", { class: `btn small ${kind}`.trim(), type: "button" }, label);
  button.addEventListener("click", work);
  return button;
}

const AUTHOR = { you: "You", claude: "Claude", studio: "The studio" };

async function drawVersions(p, box, said, bad = false) {
  const [reply, chat] = await Promise.all([api(`/api/post/${p.id}/versions`), api(`/api/post/${p.id}/chat`)]);
  if (!box.isConnected) return;
  if (reply.error) return void put(box, h("div", { class: "result bad" }, icon("alert", 15), h("div", null, reply.error)));
  const line = said ? h("div", { class: `result ${bad ? "bad" : "ok"}` }, icon(bad ? "alert" : "check", 15), h("div", null, said)) : null;
  const rows = reply.versions.map((v) => {
    const back = v.current ? h("span", { class: "chip ok" }, "Now")
      : h("button", { class: "btn small", type: "button", disabled: !reply.editable }, "Go back to this");
    if (!v.current) back.addEventListener("click", () => whileBusy(back, async () => {
      const done = await post(`/api/post/${p.id}/versions/back`, { version: v.id });
      await refresh();
      if (done.changed) window.dispatchEvent(new Event("studio:chat"));   // the chat's line saying so
      drawVersions(p, box, done.error || (done.changed ? `Went back to the version of ${v.when}. The post shows it.` : "It already reads like that."), !!done.error);
    }));
    const [compare, diff] = v.segments ? comparison(v) : [null, null];
    return h("li", { class: "version-item" },
      h("div", { class: `version${v.current ? " now" : ""}` }, icon(v.author === "claude" ? "sparkle" : v.author === "you" ? "user" : "history", 15),
        h("div", { class: "version-text" }, h("b", { title: v.first }, v.note || v.first || "A version"),
          h("small", null, `${v.when} · ${AUTHOR[v.author] || v.author} · ${number(v.chars)} characters`)), compare, back),
      diff);
  });
  const earlier = (chat.earlier || []).map((c) => {
    const back = h("button", { class: "btn small", type: "button" }, "Bring the chat back");
    back.addEventListener("click", () => whileBusy(back, async () => {
      const done = await post(`/api/post/${p.id}/chat/back`, { conversation: c.id });
      drawVersions(p, box, done.error || `The chat is back (${plural(c.count, "message", "messages")}).`, !!done.error);
      window.dispatchEvent(new Event("studio:chat"));
    }));
    return h("li", { class: "version" }, icon("chat", 15),
      h("div", { class: "version-text" }, h("b", null, `Chat started afresh (${plural(c.count, "message", "messages")})`), h("small", null, c.when)), back);
  });
  put(box, line,
    rows.length || earlier.length ? h("ol", { class: "version-list" }, rows, earlier)
      : h("p", { class: "soft" }, "No versions yet: the first is kept once the post has text and Claude changes it."),
    reply.editable ? null : h("p", { class: "soft" }, p.busy ? "Claude is working on this post: going back waits until it is done."
      : "Only a draft can go back to a version."));
  if (line) {
    focusFirst(line);
    announce(said, { urgent: bad });
  }
}

// Compare with now: an earlier version's words against the post's now, opened under its row (the studio worked them out).
function comparison(v) {
  const id = `compare-${v.id}`;
  const diff = h("div", { class: "version-compare", id, hidden: true },
    h("p", { class: "soft" }, "Struck words are in this version only; marked words were added since."),
    h("p", { class: "wdiff" }, wordDiff(v.segments)),
    v.first_comment_differs ? h("p", { class: "soft" }, "Its first comment differs from now too.") : null);
  const button = h("button", { class: "btn small", type: "button", "aria-expanded": "false", "aria-controls": id },
    h("span", null, "Compare with now"), icon("chevron-down", 13));
  button.addEventListener("click", () => {
    const open = button.getAttribute("aria-expanded") !== "true";
    button.setAttribute("aria-expanded", String(open));
    diff.hidden = !open;
  });
  return [button, diff];
}

function confirmCancel(p) {
  const yes = h("button", { class: "btn danger", type: "button" }, "Cancel the post");
  yes.addEventListener("click", () => whileBusy(yes, async () => {
    const reply = await post(`/api/post/${p.id}/cancel`, {});
    closeDialog();
    announce(reply.error || "Cancelled on Publora.", { urgent: !!reply.error });
    await refresh();
  }));
  showDialog(h("h2", null, "Cancel this scheduled post?"), h("p", null, "Publora will not publish it. The text stays here."),
    h("div", { class: "dialog-foot" }, closeButton("Keep it"), yes));
}

// Move to Trash…: the dialog names the post (its title and first line). Afterwards the post is out of the list at once,
// the next one opens with the focus on its button in the list, and a note links to the Trash.
function confirmTrash(p) {
  const yes = h("button", { class: "btn danger", type: "button" }, icon("trash", 15), h("span", null, "Move to Trash"));
  const out = h("div", { class: "results" });
  yes.addEventListener("click", () => whileBusy(yes, async () => {
    await saveNow();
    const reply = await post(`/api/post/${p.id}/trash`, {});
    if (reply.error) {
      put(out, h("div", { class: "result bad" }, icon("alert", 15), h("div", null, reply.error)));
      return announce(reply.error, { urgent: true });
    }
    closeDialog();
    moveOn(p.id);
    toast("Moved to the Trash", "#~trash", "Open the Trash");
  }));
  const first = p.first === "Nothing written yet" ? "It has no text yet." : `It begins: “${p.first}”`;
  showDialog(h("h2", null, `Move “${p.title}” to the Trash?`),
    h("p", null, "It moves to the Trash with its versions, chat and pictures. Put it back or delete it forever from there."),
    h("p", { class: "soft" }, first),
    out,
    h("div", { class: "dialog-foot" }, closeButton("Keep it"), yes));
}

// The list without that post, at once (the next poll agrees), and the post after it opened in its place.
function moveOn(id) {
  const at = state.posts.findIndex((x) => x.id === id);
  state.posts = state.posts.filter((x) => x.id !== id);
  const next = state.posts[Math.max(at, 0)] || state.posts[at - 1] || null;
  shown = null;
  state.postId = next ? next.id : null;
  renderList();
  go(next ? `#post-${next.id}` : "#~posts");
  focusFirst(next ? $("list").querySelector(`[data-post="${next.id}"]`) : null, $("newPost"));
}

export function forgetRefusal() {
  refused = "";
  heard = null;
}

export function init() {
  $("postGear").prepend(icon("gear", 17));
  $("postGear").addEventListener("click", openGear);
  onPoll(chipAfterPoll);
  // A refusal (Approve's blanks, say) goes as soon as the text changes.
  $("postPage").addEventListener("input", (event) => {
    if (!refused || !(event.target instanceof HTMLTextAreaElement)) return;
    refused = "";
    if (shown) renderNotice(shown);
  });
}
