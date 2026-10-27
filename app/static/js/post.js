// A post at the top: its title, where it stands, and the one next step (Approve this text, then Schedule…, then the time
// it goes out); the gear (its title, its versions to go back to, its earlier chats, Cancel on Publora, Delete); and the
// Schedule… dialog (a time, then the final text, picture, time and first comment to confirm).
import { $, state, h, icon, api, post, put, number, plural, announce, whileBusy, focusFirst, drawIfChanged, showDialog,
  closeDialog, closeButton, setTitle, go } from "./core.js";
import { renderPost, saveNow, noticeBox, nextBlank, editorState } from "./editor.js";
import { statusOf } from "./sidebar.js";

let shown = null;      // the post as the studio last said it
let asking = false;

export async function loadPost(id, { quiet = false } = {}) {
  if (asking) return;
  asking = true;
  try {
    const data = await api(`/api/post/${id}`);
    if (state.postId !== id) return;
    if (data.error) {
      if (!quiet) announce(data.error, { urgent: true });
      shown = null;
      return void go("#~posts");
    }
    shown = data;
    renderPost(data, () => loadPost(id, { quiet: true }));   // makes the stage (and its notice) the first time
    renderTop(data);
    renderNotice(data);
  } finally {
    asking = false;
  }
}

export const shownPost = () => shown;

// ---------- the top bar ----------

let chip = null;
function renderTop(p) {
  setTitle(`${p.first.slice(0, 60)} · LinkedIn Studio`);
  $("title").textContent = p.title;
  $("title").title = p.title;
  const status = statusOf(p);
  if (!chip) chip = h("span", { class: "chip" }, h("i", { class: "dot", "aria-hidden": "true" }), h("span", { class: "chip-text" }));
  if (chip.parentNode !== $("status")) $("status").replaceChildren(chip);
  chip.className = `chip ${status.kind}`.trim();
  if (chip.lastChild.textContent !== status.text) chip.lastChild.textContent = status.text;
  $("postGear").hidden = false;
  const actions = $("topActions");
  drawIfChanged(actions, JSON.stringify([p.id, p.status, p.busy, p.when, p.can_retry, p.can_back, p.slots]), () => {
    const on = actions.contains(document.activeElement) ? document.activeElement.dataset.act : null;
    put(actions, ...mainActions(p));
    if (on) focusFirst(actions.querySelector(`[data-act="${on}"]`), actions.querySelector("button"), $("postGear"));
  });
}

function act(label, kind, name, work, glyph) {
  const button = h("button", { class: `btn ${kind}`.trim(), type: "button", "data-act": name }, glyph ? icon(glyph, 15) : null, h("span", null, label));
  button.addEventListener("click", () => whileBusy(button, () => work(button)));
  return button;
}

function mainActions(p) {
  switch (p.status) {
    case "draft":
      return [act("Approve this text", "primary", "approve", approve, "check")];
    case "approved":
      return [act("Back to draft", "ghost", "back", () => change("unapprove", "Back in draft. You can edit it again.")),
        act("Schedule…", "primary", "schedule", () => openSchedule(), "clock")];
    case "scheduling":
      return [h("span", { class: "top-when" }, h("i", { class: "pulse" }), "Sending to Publora…")];
    case "scheduled":
      return [h("span", { class: "top-when" }, icon("clock", 15), `Goes out ${p.when}`),
        act("Check status", "ghost", "refresh", () => change("refresh", "Status read from Publora."), "refresh")];
    case "failed":
      return [p.can_back ? act("Back to draft", "ghost", "back", () => change("unapprove", "Back in draft.")) : null,
        p.can_retry ? act("Try again", "primary", "retry", () => change("retry", "Scheduled on Publora."), "refresh") : null].filter(Boolean);
    case "published":
      return [h("span", { class: "top-when" }, icon("check-circle", 15), p.when ? `Published ${p.when}` : "Published")];
    default:
      return [h("span", { class: "top-when" }, "Cancelled on Publora. It was never published.")];
  }
}

// The post's notice above it: Claude at work on it, a send that failed, Publora's warnings, a refusal just now.
let refused = "";
function renderNotice(p) {
  const box = noticeBox();
  let kind = "";
  let words = null;
  if (refused) {
    kind = "bad";
    const next = p.slots && p.status === "draft" ? h("button", { class: "btn small", type: "button", onclick: () => nextBlank() }, "Next blank") : null;
    words = [icon("alert", 16), h("div", null, refused), next];
  } else if (p.busy) {
    kind = "busy";
    words = [h("i", { class: "pulse" }), h("div", null, h("strong", null, "Claude is working on this post."), "Its text waits until Claude is done; the chat on the right shows each step.")];
  } else if (p.error) {
    kind = p.status === "failed" ? "bad" : "";
    words = [icon("alert", 16), h("div", null, p.error)];
  } else if (p.status === "approved") {
    kind = "soft";
    words = [icon("lock", 16), h("div", null, "Approved: the text and picture are locked. Back to draft unlocks them.")];
  }
  drawIfChanged(box, JSON.stringify([refused, p.busy, p.error, p.status, p.slots]), () => {
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
  refused = "";
  const saved = await saveNow();
  if (saved && saved.error) return;
  const reply = await post(`/api/post/${shown.id}/approve`, {});
  if (reply.error) {
    refused = reply.error;
    announce(reply.error, { urgent: true });
  } else {
    announce("Approved. Pick a time and schedule it.");
  }
  await refresh();
  if (!reply.error) focusFirst($("topActions").querySelector('[data-act="schedule"]'));
}

async function change(what, said) {
  refused = "";
  const reply = await post(`/api/post/${shown.id}/${what}`, {});
  if (reply.error) {
    refused = reply.error;
    announce(reply.error, { urgent: true });
  } else if (reply.ok === false) {
    announce(reply.error || "It did not go through.", { urgent: true });
  } else {
    announce(said);
  }
  await refresh();
}

// ---------- Schedule… ----------

function openSchedule() {
  const p = shown;
  const sch = p.schedule;
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
  showDialog(h("h2", null, "When should it go out?"),
    h("p", { class: "soft" }, `${p.used} of ${p.limit} posts used in ${p.month}. Between 2 minutes and 14 days ahead.`),
    publora,
    h("div", { class: "form" }, h("label", { class: "field" }, h("span", { class: "field-label" }, `Date and time (${state.tz})`), when), picks),
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
    h("div", { class: "textbox confirm-text", tabindex: "0", "aria-label": "The final text" }, p.text),
    p.picture ? h("img", { class: "confirm-picture", src: p.picture.url, alt: "The picture that goes out with it" }) : null,
    p.first_comment ? [h("h3", { style: "margin-top:12px" }, "First comment"), h("div", { class: "textbox" }, p.first_comment)] : null,
    out,
    h("div", { class: "dialog-foot" }, back, closeButton("Not yet"), go));
}

// ---------- the gear ----------

async function openGear() {
  const p = shown;
  if (!p) return;
  const name = h("input", { class: "input", value: p.title, maxlength: 120, "aria-describedby": "titleHint" });
  const keep = h("button", { class: "btn small", type: "button" }, "Save the title");
  const said = h("div", { class: "results" });
  keep.addEventListener("click", () => whileBusy(keep, async () => {
    const reply = await post(`/api/post/${p.id}/save`, { title: name.value, text: editorState.data.text, first_comment: editorState.data.first_comment });
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
        h("a", { class: "btn small", href: p.dashboard, target: "_blank", rel: "noreferrer" }, icon("external", 14), "Publora dashboard")) : null,
    p.deletable ? h("div", { class: "danger-row" }, h("span", null, "Delete: the post, its versions, its chat and its pictures leave this computer."),
      gearAct("Delete…", () => confirmDelete(p), "danger")) : null);
  showDialog(h("h2", null, p.title),
    h("label", { class: "field" }, h("span", { class: "field-label" }, "Title (only you see it)"), name),
    h("div", { class: "form-foot", style: "margin-top:8px" }, keep, h("span", { class: "soft", id: "titleHint" }, "The list shows the post’s first line.")),
    said,
    h("section", { class: "zone", "aria-label": "Versions" }, h("h3", null, "Versions"),
      h("p", { class: "soft" }, "Each change Claude makes is kept, and your own edits before it. Going back is kept too, so it can be undone."),
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
      drawVersions(p, box, done.error || (done.changed ? `Went back to the version of ${v.when}. The post shows it.` : "It already reads like that."), !!done.error);
    }));
    return h("li", { class: `version${v.current ? " now" : ""}` }, icon(v.author === "claude" ? "sparkle" : v.author === "you" ? "user" : "history", 15),
      h("div", { class: "version-text" }, h("b", { title: v.first }, v.note || v.first || "A version"),
        h("small", null, `${v.when} · ${AUTHOR[v.author] || v.author} · ${number(v.chars)} characters`)), back);
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

function confirmDelete(p) {
  const yes = h("button", { class: "btn danger", type: "button" }, "Delete");
  yes.addEventListener("click", () => whileBusy(yes, async () => {
    const reply = await post(`/api/post/${p.id}/delete`, {});
    closeDialog();
    if (reply.error) return announce(reply.error, { urgent: true });
    announce("Post deleted.");
    go("#~posts");
  }));
  showDialog(h("h2", null, "Delete this post?"),
    h("p", null, "The post, its versions, its chat and its pictures are removed from this computer. This cannot be undone."),
    h("div", { class: "dialog-foot" }, closeButton("Keep it"), yes));
}

export function forgetRefusal() {
  refused = "";
}

export function init() {
  $("postGear").prepend(icon("gear", 17));
  $("postGear").addEventListener("click", openGear);
}
