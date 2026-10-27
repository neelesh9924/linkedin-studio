// Ask Claude: one chat component for a post's own chat, the interviewer (Story Bank) and the voice-profile chat.
// As in the owner's other studios:
// - The conversation is a log a screen reader follows (#messages, role=log), drawn a message at a time: what is new is
//   added, nothing earlier is drawn again; another conversation is drawn afresh in a log of its own.
// - Claude's steps (#activity) are updated in place: the step it is on, how long it has been on it ("Still on this step"),
//   a numbered line for each step. A screen reader hears the newest step at most every ten seconds.
// - The box is never disabled: the next message can be written while Claude works, and the focus stays in it through
//   Enter, Send and Stop. A refusal is said at once. Each conversation keeps its own unsent words.
// - After a run that did not finish, Try again (the same message) or Carry on (from where it stopped); Try again too
//   for a request no answer ever came to.
// - A post that is not a draft is locked: the panel says so and what unlocks it, and its ideas work on a locked post.
// - Copy on each of Claude's replies; ↑ in an empty box brings back the last message sent in this conversation.
import { $, state, h, icon, api, post, put, plural, clockOf, announce, whileBusy, suggestion, drawIfChanged, onPoll, focusFirst,
  copyButton } from "./core.js";
import { markdown } from "./md.js";
import { choosePicture } from "./editor.js";
import { attacher, chip } from "../attach.js";

const SPEAK_EVERY = 10000;   // ms between steps said aloud
const QUIET = 20;            // s with nothing new: "Still on this step"
const SHOWN = 12;            // steps shown at once
const CARRY_ON = "Carry on from where you stopped, and finish the request.";
const KEYS = "Enter sends · Shift+Enter new line · ↑ brings back your last message";
// Where a post that is not a draft stands, and what still changes it.
const LOCKED = {
  approved: "The text is locked. Back to draft, in the top bar, unlocks it.",
  scheduling: "It is on its way to Publora, so the text is locked.",
  scheduled: "The text is locked while it waits at Publora. To change it, cancel it on Publora first (the gear).",
  published: "It is on LinkedIn, so the text is locked. New draft from this makes an editable copy.",
  failed: "The text is locked. New draft from this makes an editable copy.",
  cancelled: "The text is locked. New draft from this makes an editable copy.",
};

// What the panel is about now: { kind: "post" | "bank" | "voice", id, conversation }, or null (panel hidden).
let ctx = null;
let thread = { key: "", messages: [], earlier: [], history: [], started: false, busy: false };
const drafts = new Map();     // a conversation's key -> what was being written for it: { text, files }
let draftFor = null;
let sending = false;
let att = null;               // the shared attachments module's attacher: the files waiting to go with the next message

const keyOf = (c) => (c ? `${c.kind}:${c.id || ""}` : "");
const ENDPOINT = {
  post: (c) => `/api/post/${c.id}/chat`,
  bank: (c) => `/api/chat/bank${c.conversation ? `?c=${c.conversation}` : ""}`,
  voice: (c) => `/api/chat/voice${c.conversation ? `?c=${c.conversation}` : ""}`,
};

// The job of Claude's that belongs to this conversation, while it runs or waits.
function jobHere() {
  if (!ctx) return null;
  if (ctx.kind === "post") return state.jobs.find((j) => j.kind === "post_chat" && j.post_id === ctx.id) || null;
  const kind = ctx.kind === "bank" ? "interview" : "voice";
  return state.jobs.find((j) => j.kind === kind && (!thread.conversation || j.conversation_id === thread.conversation)) || null;
}

// ---------- the panel follows the page ----------

export function showFor(next) {
  const was = keyOf(ctx);
  holdDraft(keyOf(next));
  ctx = next;
  $("app").classList.toggle("no-assist", !next || hidden());
  $("showAssist").hidden = !next || !hidden();
  if (!next) return;
  $("assistTitle").textContent = next.kind === "post" ? "Ask Claude" : next.kind === "bank" ? "Interviewer" : "Voice profile";
  if (keyOf(next) !== was) {
    thread = { key: "", messages: [], earlier: [], history: [], started: false, busy: false };
    forgetLog();
    refresh();
  }
}

const hidden = () => {
  try {
    return localStorage.getItem("assist") === "0";
  } catch {
    return false;
  }
};

function showPanel(show, focus) {
  try {
    localStorage.setItem("assist", show ? "1" : "0");
  } catch {}
  $("app").classList.toggle("no-assist", !show || !ctx);
  $("showAssist").hidden = show || !ctx;
  if (focus) focusFirst(show ? $("askText") : $("showAssist"));
}

// ---------- the conversation ----------

export async function refresh() {
  if (!ctx) return;
  const asked = ctx;
  const data = await api(ENDPOINT[asked.kind](asked));
  if (asked !== ctx || data.error) return;
  const box = $("thread");
  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 60;
  const changed = JSON.stringify(data.messages) !== JSON.stringify(thread.messages) || thread.key !== keyOf(ctx);
  thread = { key: keyOf(ctx), conversation: data.conversation, messages: data.messages || [], earlier: data.earlier || [],
    history: data.history || [], started: !!data.started, doc: data.doc, busy: !!data.busy };
  if (ctx.kind !== "post" && data.conversation) ctx.conversation = data.conversation;
  renderMessages();
  renderTools();
  renderOffer();
  renderActivity();
  renderComposer();
  if (changed || atBottom) box.scrollTop = box.scrollHeight;
}

function messageEl(m) {
  if (m.role === "user") {
    return h("div", { class: "msg user", "data-id": m.id }, h("div", { class: "bubble" }, m.text),
      (m.files || []).length ? h("div", { class: "msg-files", role: "list", "aria-label": "Attached" },
        m.files.map((f) => h("span", { role: "listitem" }, chip(f, { href: f.url, view: f.view })))) : null,
      (m.images || []).length ? h("div", { class: "msg-files" }, m.images.map((p) => usePicture(p, p.prompt))) : null);
  }
  if (m.role === "info") return h("div", { class: "msg info", "data-id": m.id }, m.text);
  if (m.role === "error") return h("div", { class: "msg error", "data-id": m.id }, icon("alert", 16), h("div", null, m.text));
  const who = ctx && ctx.kind === "bank" ? "Interviewer" : "Claude";
  const copy = m.text ? copyButton(m.text) : null;
  if (copy) {
    copy.classList.add("ghost");
    copy.setAttribute("aria-label", `Copy this reply from ${who === "Claude" ? "Claude" : "the interviewer"}`);
  }
  return h("div", { class: "msg claude", "data-id": m.id },
    h("div", { class: "msg-who" }, icon("sparkle", 14), who, h("time", null, m.at), copy),
    m.text ? h("div", { class: "prose" }, markdown(m.text, { breaks: true })) : null,
    m.versions ? h("div", { class: "msg-note" }, icon("check", 13), "Rewrote the post · the gear’s Versions can go back") : null,
    m.diff ? h("details", { class: "file-change" },
      h("summary", null, icon("file", 14), h("span", null, `Saved to ${thread.doc ? thread.doc.name : "the file"}`),
        h("span", { class: "plus" }, `+${m.diff.added}`), h("span", { class: "minus" }, `−${m.diff.removed}`)),
      h("pre", { class: "diff" }, m.diff.text.split("\n").filter((l) => !l.startsWith("+++") && !l.startsWith("---")).map((line) =>
        h("span", { class: line.startsWith("@@") ? "hunk" : line.startsWith("+") ? "add" : line.startsWith("-") ? "del" : "" }, `${line || " "}\n`)))) : null,
    (m.images || []).length ? h("div", { class: "msg-pictures" }, m.images.map(pictureEl)) : null);
}

// The post's picture from this one: "Use as the picture", or that it is on the post already.
function usePicture(p, name = "") {
  if (p.chosen) return h("span", { class: "chip ok" }, icon("check", 12), name ? `${name} is on the post` : "On the post");
  const use = h("button", { class: "btn small", type: "button" }, name ? `Use ${name} as the post’s picture` : "Use as the picture");
  use.addEventListener("click", () => whileBusy(use, () => choosePicture(p.id)));
  return use;
}

function pictureEl(p) {
  return h("figure", { class: "msg-picture" },
    h("img", { src: p.url, alt: p.prompt ? `Illustration: ${p.prompt.slice(0, 160)}` : "Illustration", width: p.width, height: p.height }),
    h("div", { class: "form-foot" }, h("small", null, `${p.width} × ${p.height} · ChatGPT`), usePicture(p)));
}

const drawn = { key: "", ids: [], keys: [] };
function forgetLog() {
  Object.assign(drawn, { key: "", ids: [], keys: [] });
}

function renderMessages() {
  const messages = thread.messages;
  $("assistEmpty").hidden = messages.length > 0;
  if (!messages.length) renderEmpty();
  const ids = messages.map((m) => m.id);
  const keys = messages.map((m) => JSON.stringify(m));
  const log = $("messages");
  const same = drawn.key === thread.key && drawn.ids.length <= ids.length && drawn.ids.every((id, i) => id === ids[i]);
  if (same) {
    const nodes = [...log.children];
    drawn.keys.forEach((key, i) => {
      if (key !== keys[i] && nodes[i]) nodes[i].replaceWith(messageEl(messages[i]));
    });
    log.append(...messages.slice(drawn.ids.length).map(messageEl));
  } else {
    const fresh = h("div", { id: "messages", role: "log", "aria-label": "The conversation" });
    fresh.append(...messages.map(messageEl));
    log.replaceWith(fresh);
  }
  Object.assign(drawn, { key: thread.key, ids, keys });
}

// What an empty conversation offers: for a post with no text yet, what to write it about; for a draft, ideas that are not
// the Audit and Revise buttons' jobs; for a locked post, where it stands and what still works; for the interviews, how
// they work and Start.
const postHere = () => (ctx && ctx.kind === "post" ? state.posts.find((p) => p.id === ctx.id) || null : null);
const lockedWords = () => {
  const p = postHere();
  return p && p.status !== "draft" ? LOCKED[p.status] || "The text is locked." : "";
};

function renderEmpty() {
  const box = $("assistEmpty");
  const post_ = postHere();
  const empty = post_ && post_.first === "Nothing written yet";
  const locked = lockedWords();
  drawIfChanged(box, `${keyOf(ctx)} ${empty} ${locked}`, () => {
    if (ctx.kind === "post") {
      const fill = (text) => () => {
        $("askText").value = text;
        $("askText").focus();
      };
      const ideas = locked ? ["Audit this post", "What would make the next one stronger?"]
        : empty
          ? ["Write a post about what we learned cutting our deploy time, for engineering managers. Goal: comments.",
            "Draft a receipt post from my Story Bank: one real number, what it measures, and what it changed."]
          : ["Use a real number from my Story Bank", "Add a first comment with the link", "Make an illustration for this post", "End on a question"];
      const head = locked ? `This post is ${post_.label.toLowerCase()}` : empty ? "What should this post say?" : "Ask for a change";
      const words = locked ? `${locked} Claude can still audit it, or talk through what would make the next one stronger.`
        : empty ? "Tell Claude the topic, the angle or a rough idea, and what the post should earn (comments, reposts, likes, saves). It drafts it with the post writer, in your voice, and leaves a [blank] wherever a real fact is missing."
          : "Say what should be different. Claude rewrites the post in place (each change is a version you can go back to), or asks ChatGPT for an illustration. For a check or a quick rewrite, Audit and Revise sit beside the post.";
      put(box, h("div", { class: "assist-empty" },
        h("b", null, head), words,
        h("div", { class: "suggests" }, h("div", { class: "suggest-label" }, "Try"), ideas.map((t) => suggestion(t, fill(t))))));
    } else {
      const bank = ctx.kind === "bank";
      const start = h("button", { class: "btn primary", type: "button" }, icon(bank ? "chat" : "feather", 15), h("span", null, bank ? "Start the interview" : "Start"));
      start.addEventListener("click", () => send(null, ""));
      put(box, h("div", { class: "assist-empty" },
        h("b", null, bank ? "Tell it your stories once" : "Teach it how you write"),
        bank ? "The interviewer asks one question at a time and presses once when an answer is vague. It keeps what you say in your Story Bank, so drafts stop asking you for numbers. Budget 20 to 40 minutes; stop any time and pick up later."
          : "Paste three to six of your own posts or comments. It works out your rhythm, openers and habits, shows you the profile, and saves it once you say yes.",
        h("div", null, start)));
    }
  });
}

// The head's own: a post's chat can start afresh (the old one is kept in the gear's Versions); an interview has its
// earlier conversations and New conversation.
function renderTools() {
  const box = $("assistTools");
  drawIfChanged(box, JSON.stringify([keyOf(ctx), thread.conversation, thread.history, thread.messages.length, !!jobHere()]), () => {
    if (ctx.kind === "post") {
      const fresh = thread.messages.length && !jobHere()
        ? h("button", { class: "btn ghost small square", type: "button", "aria-label": "Start this chat afresh",
          title: "Start this chat afresh. The post is not changed; the gear can bring this chat back." }, icon("plus", 15)) : null;
      if (fresh) fresh.addEventListener("click", () => whileBusy(fresh, async () => {
        const reply = await post(`/api/post/${ctx.id}/chat/clear`, {});
        if (reply.error) return refuse(reply.error);
        announce("The chat starts afresh. The gear’s Versions can bring the old one back.");
        await refresh();
        $("askText").focus();
      }));
      return put(box, fresh);
    }
    const pick = thread.history.length > 1 ? h("select", { class: "input", "aria-label": "Earlier conversations" },
      thread.history.map((c) => h("option", { value: c.id, selected: c.id === thread.conversation }, `${c.when} · ${plural(c.count, "message", "messages")}`))) : null;
    if (pick) pick.addEventListener("change", () => {
      ctx.conversation = Number(pick.value);
      forgetLog();
      refresh();
    });
    const fresh = h("button", { class: "btn ghost small", type: "button", title: "New conversation" }, icon("plus", 14), h("span", null, "New"));
    fresh.addEventListener("click", () => whileBusy(fresh, async () => {
      const reply = await post(`/api/chat/${ctx.kind}/new`, {});
      if (reply.error) return refuse(reply.error);
      ctx.conversation = reply.conversation;
      forgetLog();
      await refresh();
      $("askText").focus();
    }));
    put(box, pick, fresh);
  });
}

// ---------- after a run that did not finish ----------

function offerOf() {
  if (!ctx || jobHere() || sending) return null;
  const last = thread.messages[thread.messages.length - 1];
  if (last && last.role === "user") return unanswered(last);
  if (!last || !last.offer) return null;
  const asked = thread.messages.find((m) => m.id === last.request);
  const text = last.offer === "carry" ? CARRY_ON : asked ? asked.text : "";
  if (!text) return null;
  return { kind: last.offer, text,
    words: last.offer === "carry" ? "It stopped part-way. What it changed so far stays; Versions can undo it." : "Send the same message again." };
}

// The conversation ends with the owner's message and nothing for it runs or waits: no answer came (the app was closed
// while Claude worked, or the job ended without one). A job newer than any the last poll knew has simply not been seen yet.
function unanswered(last) {
  if (thread.busy) return null;
  const ended = last.job ? state.ended.find((j) => j.id === last.job) : null;
  const known = Math.max(0, ...state.jobs.map((j) => j.id), ...state.ended.map((j) => j.id));
  if (last.job && !ended && last.job > known) return null;
  const why = ended && ended.error ? ` ${ended.error}` : "";
  return { kind: "again", text: last.text, words: `No answer came to this request.${why}` };
}

function renderOffer() {
  const box = $("assistOffer");
  const offer = offerOf();
  drawIfChanged(box, JSON.stringify([keyOf(ctx), offer]), () => {
    box.hidden = !offer;
    if (!offer) return void box.replaceChildren();
    const carry = offer.kind === "carry";
    const button = h("button", { class: "btn small", type: "button" }, icon(carry ? "send" : "refresh", 14), h("span", null, carry ? "Carry on" : "Try again"));
    button.addEventListener("click", () => whileBusy(button, () => send(null, offer.text)));
    put(box, h("div", { class: "offer-row" }, h("span", { class: "offer-words" }, offer.words), button));
  });
}

// ---------- Claude's steps ----------

const steps = { job: null, time: null, note: null, list: null };
function renderActivity() {
  const job = jobHere();
  const box = $("activity");
  if (!job) {
    if (box.firstChild) box.replaceChildren();
    steps.job = null;
    return;
  }
  if (steps.job !== job.id || !box.firstChild) {
    steps.job = job.id;
    steps.time = h("span", { class: "activity-time" });
    steps.note = h("div", { class: "activity-note" });
    steps.list = h("ol");
    put(box, h("div", { class: "activity" },
      h("div", { class: "activity-head" }, h("i", { class: "pulse" }), job.doing, steps.time), steps.note, steps.list));
  }
  const time = job.status === "running" ? clockOf(job.seconds) : "";
  if (steps.time.textContent !== time) steps.time.textContent = time;
  const note = job.status === "queued" ? "Waits for the job under way to finish"
    : job.steps && job.quiet >= QUIET ? `Still on this step · ${job.quiet} s` : `Step ${job.steps || 0}`;
  if (steps.note.textContent !== note) steps.note.textContent = note;
  const shown = new Map([...steps.list.children].map((li) => [Number(li.dataset.n), li]));
  for (const entry of job.activity.slice(-SHOWN)) {
    const key = JSON.stringify([entry.text, entry.detail]);
    const li = shown.get(entry.n);
    const fresh = () => h("li", { "data-n": entry.n, "data-key": key }, h("time", null, entry.at), entry.text, entry.detail ? h("small", null, entry.detail) : null);
    if (!li) steps.list.append(fresh());
    else if (li.dataset.key !== key) li.replaceWith(fresh());
  }
  while (steps.list.children.length > SHOWN) steps.list.firstElementChild.remove();
}

// ---------- the box ----------

function refuse(text) {
  $("askRefused").textContent = text;
  $("askRefused").hidden = false;
  $("askHint").hidden = true;
  announce(text, { urgent: true });
}

function unrefuse() {
  if ($("askRefused").hidden) return;
  $("askRefused").hidden = true;
  $("askRefused").textContent = "";
  $("askHint").hidden = false;
}

function renderComposer() {
  const job = jobHere();
  const any = state.jobs.find((j) => j.status === "running");
  const box = $("askText");
  box.readOnly = state.offline || sending;
  $("sendBtn").setAttribute("aria-disabled", String(!!job || state.offline || sending));
  $("stopBtn").hidden = !job;
  const locked = lockedWords();
  box.placeholder = job ? "Write your next message: it can be sent once Claude is done…"
    : locked ? "Ask about this post…" : ctx && ctx.kind === "post" ? "Ask for a change to this post…" : "Your answer. Enter sends, Shift+Enter adds a line.";
  let hint = "";
  if (state.offline) hint = "LinkedIn Studio is not running, so nothing can be sent.";
  else if (job) hint = job.status === "queued" ? "Waiting for the job under way." : `${job.doing}.`;
  else if (any) hint = `Claude is busy with ${any.title.toLowerCase()}; this waits its turn.`;
  else if (locked) hint = "The text is locked: Claude can audit it or advise, not rewrite it.";
  else if (ctx && ctx.kind === "post") hint = "Claude rewrites the post in place.";
  if ($("askHint").textContent !== hint) $("askHint").textContent = hint;
  const p = ctx && ctx.kind === "post" ? state.posts.find((x) => x.id === ctx.id) : null;
  $("assistContext").textContent = p ? `About: ${p.first}` : ctx && ctx.kind === "bank" ? "Fills your Story Bank" : ctx ? "Fills your voice profile" : "";
}

// Another conversation shown: what was being written, and the files attached to it, stay with the one they were for.
function holdDraft(to) {
  if (draftFor === to) return;
  if (draftFor) drafts.set(draftFor, { text: $("askText").value, files: att ? att.files.slice() : [] });
  const held = (to && drafts.get(to)) || { text: "", files: [] };
  $("askText").value = held.text;
  if (att) att.set(held.files.slice());
  draftFor = to;
  unrefuse();
}

async function send(event, given) {
  if (event) event.preventDefault();
  if (!ctx || sending) return;
  const box = $("askText");
  const text = given === undefined ? box.value.trim() : given;
  const interview = ctx.kind !== "post";
  if (!text && !(interview && !thread.started)) return refuse("Say what you want first.");
  if (jobHere()) return refuse("Claude is still working on the last message. What you wrote stays here: send it once Claude is done.");
  const kept = $("composer").contains(document.activeElement);
  const target = ctx;
  sending = true;
  box.readOnly = true;
  box.setAttribute("aria-busy", "true");
  const files = given === undefined ? att.payload() : [];   // Try again and Carry on send words only
  let reply;
  try {
    reply = await whileBusy($("sendBtn"), () => (target.kind === "post"
      ? post(`/api/post/${target.id}/ask`, { text, files })
      : post(`/api/chat/${target.kind}/send`, { text, conversation: thread.conversation, files })));
  } finally {
    sending = false;
    box.readOnly = false;
    box.removeAttribute("aria-busy");
  }
  if (reply.error) {
    refuse(reply.error);
  } else {
    unrefuse();
    if (given === undefined && keyOf(target) === draftFor) {
      box.value = "";
      att.clear();
    }
    drafts.delete(keyOf(target));
    if (target.kind !== "post" && reply.conversation) target.conversation = reply.conversation;
  }
  window.dispatchEvent(new Event("studio:poll"));
  await refresh();
  if (kept) box.focus();
}

// ---------- what a run says of itself, aloud ----------

const heard = { job: null, at: 0, step: 0 };
function afterPoll() {
  if (!ctx) return;
  renderActivity();
  renderComposer();
  renderOffer();
  const job = jobHere();
  if (job && job.status === "running") {
    if (heard.job !== job.id) Object.assign(heard, { job: job.id, at: 0, step: 0 });
    const newest = job.activity[job.activity.length - 1];
    if (newest && newest.n > heard.step && Date.now() - heard.at >= SPEAK_EVERY && !$("app").classList.contains("no-assist")) {
      announce(newest.detail ? `${newest.text}: ${newest.detail}` : newest.text);
      Object.assign(heard, { at: Date.now(), step: newest.n });
    }
  }
}

export function init() {
  // Attachments (the shared module): the paperclip in the box, a drop on this panel, a paste of files in the box.
  const clip = h("button", { class: "btn ghost small square", type: "button", "aria-label": "Attach files",
    title: "Attach pictures, PDFs, documents or anything else for Claude to read. An attached picture can go out with the post." });
  $("attachSlot").append(clip);
  att = attacher({ button: clip, chips: $("askFiles"), zones: [$("assist")], paste: [$("askText")],
    active: () => !!ctx && !$("app").classList.contains("no-assist"),
    blocked: () => state.offline || sending,
    announce: (words, options) => announce(words, options),
    onError: (words) => refuse(words) });
  $("assistMark").append(icon("sparkle", 18));
  $("hideAssist").append(icon("panel", 15));
  $("sendBtn").append(icon("send", 15));
  $("stopBtn").prepend(icon("stop", 14));
  $("showAssist").prepend(icon("sparkle", 15));
  $("askForm").addEventListener("submit", (event) => send(event));
  $("askText").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      $("askForm").requestSubmit();
    } else if (event.key === "ArrowUp" && !event.altKey && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.isComposing
      && !$("askText").value && !$("askText").readOnly) {
      // ↑ in an empty box: the last message sent in this conversation, to send again or change.
      const mine = thread.messages.filter((m) => m.role === "user" && m.text).pop();
      if (!mine) return;
      event.preventDefault();
      $("askText").value = mine.text;
      $("askText").setSelectionRange(mine.text.length, mine.text.length);
      unrefuse();
    }
  });
  const keys = h("div", { class: "field-hint", id: "askKeys", style: "margin-top:6px" }, KEYS);
  $("askForm").append(keys);
  $("askText").setAttribute("aria-describedby", "askHint askRefused askKeys");
  window.addEventListener("studio:offline", () => {      // the poll failed: the box says so at once, not on the next draw
    state.offline = true;
    if (ctx) renderComposer();
  });
  $("askText").addEventListener("input", unrefuse);
  $("stopBtn").addEventListener("click", async () => {
    const job = jobHere();
    if (job) await whileBusy($("stopBtn"), () => post(`/api/jobs/${job.id}/cancel`, {}));
    $("askText").focus();
  });
  $("hideAssist").addEventListener("click", () => showPanel(false, true));
  $("showAssist").addEventListener("click", () => showPanel(true, true));
  window.addEventListener("studio:chat", () => {
    forgetLog();
    refresh();
  });
  onPoll(afterPoll);
}
