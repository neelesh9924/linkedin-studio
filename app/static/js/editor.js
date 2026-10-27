// A post in the middle: as LinkedIn shows it (at a desktop's width or an iPhone 16's, folded at "…more", with its picture
// and first comment), and edited right there: click the text and it opens where you clicked, or press Edit text. It
// saves by itself a moment after you stop typing (Ctrl+S at once), the meter weighs its length, blanks are marked and
// Next blank finds them. Beside it: a revision shown word by word, the audit's findings, the post's pictures and the
// writer's notes. The text is read as a paragraph, and drawn again only when it changes, so the focus stays put.
// Above it and beside the first comment: your name, headline and photo from Settings › You in the preview, or You.
import { $, state, h, icon, api, post, put, plural, number, announce, whileBusy, focusFirst, drawIfChanged, forget, copyButton } from "./core.js";
import { drawWorking, problemCard } from "./jobs.js";
import { auditView } from "./audit.js";

const SAVE_AFTER = 900;   // ms after the last key
const ed = { id: null, data: null, editing: false, expanded: false, dirty: false, typed: false, seq: 0, sent: 0, timer: 0, onChange: () => {} };
const parts = {};         // the stage's pieces, made once per post

const slotRe = () => new RegExp(state.slot, "g");   // the studio's own pattern (publishing.SLOT), from /api/state
const editable = () => !!(ed.data && ed.data.editable);

// What a reader sees before "…more": the first three lines, at most about 210 characters.
export function foldOf(text) {
  const trimmed = (text || "").trim();
  const lines = trimmed.split("\n").slice(0, 3).join("\n");
  const cut = Array.from(lines).slice(0, state.target.fold).join("");
  const folded = cut.length < trimmed.length;
  return { shown: folded ? cut.trimEnd() : trimmed, folded };
}

// The text with its blanks marked, as pieces of text and <mark> elements.
export function withBlanks(text) {
  const out = [];
  let at = 0;
  for (const m of text.matchAll(slotRe())) {
    if (m.index > at) out.push(text.slice(at, m.index));
    out.push(h("mark", null, m[0]));
    at = m.index + m[0].length;
  }
  if (at < text.length) out.push(text.slice(at));
  return out;
}

// The meter's words: where the length sits against the sweet spot and LinkedIn's limit.
export function meterWords(n) {
  const { min, max, hard } = state.target;
  const state_ = n > hard ? "over" : n > max ? "long" : n >= min ? "good" : "short";
  const tail = state_ === "good" ? `in the ${number(min)}–${number(max)} sweet spot`
    : state_ === "short" ? (n ? `${number(min - n)} short of the sweet spot` : `aim for ${number(min)}–${number(max)}`)
      : state_ === "long" ? `${number(n - max)} past the sweet spot, still fine` : `${number(n - hard)} over LinkedIn’s ${number(hard)} limit`;
  return { state: state_, tail };
}

export function meter() {
  const box = h("div", { class: "meter" },
    h("div", { class: "meter-track", "aria-hidden": "true" }, h("span", { class: "meter-zone" }), h("span", { class: "meter-thumb" })),
    h("div", { class: "meter-text" }));
  const scale = 2000;
  box.querySelector(".meter-zone").style.left = `${(state.target.min / scale) * 100}%`;
  box.querySelector(".meter-zone").style.width = `${((state.target.max - state.target.min) / scale) * 100}%`;
  // A locked post (approved, scheduled, out) gets its count only: its length is no longer anything to act on.
  box.update = (text, locked = false) => {
    const n = Array.from(text || "").length;
    const said = meterWords(n);
    box.dataset.state = locked ? "locked" : said.state;
    box.querySelector(".meter-thumb").style.left = `${(Math.min(n, scale) / scale) * 100}%`;
    put(box.querySelector(".meter-text"), h("b", null, number(n)), `${n === 1 ? " character" : " characters"}${locked ? "" : ` · ${said.tail}`}`);
  };
  return box;
}

// Where (in px from the textarea's top) the character at `index` sits, measured on a copy laid out as it is.
export function caretY(ta, index) {
  const cs = getComputedStyle(ta);
  const mirror = document.createElement("div");
  for (const p of ["fontFamily", "fontSize", "fontWeight", "lineHeight", "letterSpacing", "paddingTop", "paddingRight", "paddingBottom",
    "paddingLeft", "boxSizing", "tabSize"]) mirror.style[p] = cs[p];
  Object.assign(mirror.style, { position: "absolute", left: "-9999px", top: "0", visibility: "hidden", whiteSpace: "pre-wrap",
    overflowWrap: "anywhere", width: `${ta.clientWidth}px` });
  mirror.textContent = ta.value.slice(0, index);
  const mark = document.createElement("span");
  mark.textContent = "x";
  mirror.append(mark);
  document.body.append(mirror);
  const y = mark.offsetTop + mark.offsetHeight;
  mirror.remove();
  return y;
}

export function autosize(ta) {
  ta.style.height = "auto";
  ta.style.height = `${ta.scrollHeight + 2}px`;
}

// ---------- you, in the preview ----------

// Settings › You in the preview (/api/profile): the name, headline and photo the preview shows; until it answers, or
// with nothing set, You / Your headline and the You avatar.
export const YOU = { name: "You", headline: "Your headline" };
let me = { ...YOU, photo: null, saved: { name: "", headline: "" } };

async function loadProfile() {
  const reply = await api("/api/profile");
  if (!reply.error) setProfile(reply);
}

function setProfile(profile) {
  me = profile;
  paintWho(document);
}

// "Asha Rao" → "AR": the avatar of a name with no photo.
export function initials(name) {
  return String(name || "").trim().split(/\s+/).filter(Boolean).slice(0, 2).map((w) => Array.from(w)[0].toLocaleUpperCase()).join("");
}

// Fills every [data-who] inside root from a profile (the studio's, or one being typed in Settings): the avatar (the
// photo, shown round; else the name's initials; else You), the name, the headline, the first comment's name.
export function paintWho(root, profile = me) {
  const named = !!(profile.saved && profile.saved.name);
  for (const el of root.querySelectorAll("[data-who]")) {
    const what = el.dataset.who;
    if (what === "avatar") {
      drawIfChanged(el, JSON.stringify([profile.photo, named && profile.name]), () => {
        const size = Number(el.dataset.size || 48);
        const letters = (named && initials(profile.name)) || "You";
        put(el, profile.photo ? h("img", { src: profile.photo, alt: "", width: size, height: size, decoding: "async",
          onerror: () => put(el, letters) }) : letters);
      });
      continue;
    }
    const text = { name: profile.name, headline: profile.headline, comment: `${profile.name} · first comment` }[what];
    if (text !== undefined && el.textContent !== text) el.textContent = text;
  }
}

// The head of a post as LinkedIn shows it: the avatar, the name, the headline and a third line (when, or a hint).
export function liHead(...third) {
  const head = h("header", { class: "li-head" },
    h("span", { class: "li-avatar", "aria-hidden": "true", "data-who": "avatar", "data-size": "48" }),
    h("span", { class: "li-who" }, h("b", { "data-who": "name" }), h("span", { "data-who": "headline" }),
      third.length ? h("span", null, ...third) : null));
  paintWho(head);
  return head;
}

// The first comment's avatar and name, beside its bubble.
const commentAvatar = () => h("span", { class: "li-avatar", "aria-hidden": "true", "data-who": "avatar", "data-size": "32" });

// ---------- the stage, made once per post ----------

function build() {
  const page = $("postPage");
  parts.notice = h("div", { class: "notice", hidden: true });   // post.js says aloud what it puts here
  parts.desktop = h("button", { class: "btn small", type: "button", "aria-pressed": "true" }, icon("desktop", 14), "Desktop");
  parts.phone = h("button", { class: "btn small", type: "button", "aria-pressed": "false" }, icon("phone", 14), "Phone");
  parts.desktop.addEventListener("click", () => setView("desktop"));
  parts.phone.addEventListener("click", () => setView("phone"));
  parts.saved = h("span", { class: "save-state", "aria-live": "off" });
  // Edit text: the editor for the keyboard and a screen reader (a click on the text opens it where it lands).
  parts.edit = h("button", { class: "btn small", type: "button", "data-act": "edit" }, icon("pen", 14), h("span", null, "Edit text"));
  parts.edit.addEventListener("click", () => {
    const open = parts.body.querySelector("textarea");
    if (open) return void open.focus();
    openEditor((ed.data.text || "").length);
  });
  parts.copy = copyButton(() => fields().text, "Copy");
  parts.copy.dataset.act = "copy";
  parts.copy.title = "Copy the post’s text";
  parts.copyComment = copyButton(() => fields().first_comment, "Copy first comment");
  parts.copyComment.dataset.act = "copy-comment";
  parts.audit = h("button", { class: "btn small", type: "button", "data-act": "audit" }, icon("check-circle", 14), h("span", null, "Audit"));
  parts.audit.addEventListener("click", () => runAudit());
  parts.revise = reviseMenu();
  parts.bar = h("div", { class: "stage-bar" },
    h("div", { class: "segmented", role: "group", "aria-label": "Preview width" }, parts.desktop, parts.phone),
    parts.saved, h("div", { class: "stage-acts" }, parts.edit, parts.copy, parts.copyComment, parts.audit, parts.revise));
  parts.body = h("div", { class: "li-body" });
  parts.picture = h("figure", { class: "li-picture", hidden: true });
  parts.comment = h("div", { class: "li-comment" });
  parts.card = h("article", { class: "li-card", "aria-label": "The post as LinkedIn shows it" },
    liHead("now · ", icon("globe", 11)),
    parts.body, parts.picture,
    h("div", { class: "li-social", "aria-hidden": "true" }, h("span", { class: "li-reactions" }, h("i"), h("i"), h("i")), "Reactions and comments show here"),
    h("div", { class: "li-actions", "aria-hidden": "true" },
      ...[["like", "Like"], ["comment", "Comment"], ["repeat", "Repost"], ["plane", "Send"]].map(([g, w]) => h("span", null, icon(g, 18), w))),
    parts.comment);
  parts.meter = meter();
  parts.blanks = h("span", { class: "blanks" });
  parts.meterRow = h("div", { class: "meter-row" }, parts.meter, parts.blanks);
  parts.device = h("div", { class: "device" },
    h("div", { class: "phone-status", "aria-hidden": "true" }, h("span", null, "9:41"), h("span", { class: "phone-island" }),
      phoneLevels()),
    h("div", { class: "phone-feed" }, parts.card));
  parts.side = h("aside", { class: "side-col", "aria-label": "Beside the post" });
  parts.stage = h("div", { class: "stage", id: "stage" },
    h("div", { class: "stage-grid" }, h("div", { class: "feed-col" }, parts.device, parts.meterRow), parts.side));
  put(page, parts.notice, parts.bar, parts.stage);
  setView(readView());
}

function phoneLevels() {
  const svg = icon("info", 14);
  svg.setAttribute("viewBox", "0 0 70 13");
  svg.setAttribute("class", "phone-levels");
  svg.replaceChildren();
  const ns = "http://www.w3.org/2000/svg";
  for (const [x, y, hgt] of [[0, 8, 4], [5, 5.5, 6.5], [10, 3, 9], [15, 0.5, 11.5]]) {
    const r = document.createElementNS(ns, "rect");
    Object.entries({ x, y, width: 3.2, height: hgt, rx: 1, fill: "currentColor", stroke: "none" }).forEach(([k, v]) => r.setAttribute(k, v));
    svg.append(r);
  }
  const battery = document.createElementNS(ns, "rect");
  Object.entries({ x: 47.5, y: 0.8, width: 20, height: 10.4, rx: 3, fill: "none", stroke: "currentColor" }).forEach(([k, v]) => battery.setAttribute(k, v));
  svg.append(battery);
  return svg;
}

function readView() {
  try {
    return localStorage.getItem("view") === "phone" ? "phone" : "desktop";
  } catch {
    return "desktop";
  }
}

export function setView(view) {
  state.view = view;
  parts.desktop.setAttribute("aria-pressed", String(view === "desktop"));
  parts.phone.setAttribute("aria-pressed", String(view === "phone"));
  parts.stage.classList.toggle("phone", view === "phone");
  try {
    localStorage.setItem("view", view);
  } catch {}
  if (ed.editing) placeFold();
}

// Revise: New hook, Shorter, More technical. A menu of three, each saying what it does.
const REVISE = [["hook", "New hook", "A fresh first two lines; the rest stays."], ["shorter", "Shorter", "Trim towards 900-1,000 characters."],
  ["technical", "More technical", "Concrete mechanisms, tools and numbers."]];

// The Revise menu while it is open. One listener for the whole page closes it on a click anywhere else.
let openMenu = null;
document.addEventListener("click", (event) => {
  if (openMenu && !openMenu.wrap.contains(event.target)) openMenu.close(false);
});

// A menu button: Enter, Space or ↓ opens it on its first item (↑ on its last); ↑ ↓ Home End move; Esc closes it back
// onto Revise; Tab, or the focus going anywhere else, closes it.
function reviseMenu() {
  const button = h("button", { class: "btn small", type: "button", id: "reviseBtn", "data-act": "revise", "aria-haspopup": "menu",
    "aria-expanded": "false", "aria-controls": "reviseMenu" }, icon("sparkle", 14), h("span", null, "Revise"), icon("chevron-down", 13));
  const list = h("div", { class: "menu-list", id: "reviseMenu", role: "menu", "aria-labelledby": "reviseBtn", hidden: true },
    REVISE.map(([how, label, promise]) => h("button", { class: "menu-item", type: "button", role: "menuitem", tabindex: "-1", "data-how": how,
      onclick: () => {
        close(true);      // back on Revise, busy while the request goes
        runRevise(how, button);
      } }, h("b", null, label), h("small", null, promise))));
  const wrap = h("div", { class: "menu" }, button, list);
  const me = { wrap, close };
  const items = () => [...list.querySelectorAll('[role="menuitem"]')];
  function open(at = 0) {
    list.hidden = false;
    button.setAttribute("aria-expanded", "true");
    openMenu = me;
    const all = items();
    all[(at + all.length) % all.length].focus();
  }
  function close(back) {
    if (openMenu === me) openMenu = null;
    if (list.hidden) return;
    list.hidden = true;
    button.setAttribute("aria-expanded", "false");
    if (back) button.focus();
  }
  button.addEventListener("click", () => {
    if (!list.hidden) return close(true);
    if (button.getAttribute("aria-disabled") === "true") {
      return announce(ed.data && ed.data.revision ? `A revised version is waiting ${besideWords()}: use it or discard it first.`
        : "Write the post first: Revise works on its text.");
    }
    open();
  });
  button.addEventListener("keydown", (event) => {
    if ((event.key === "ArrowDown" || event.key === "ArrowUp") && button.getAttribute("aria-disabled") !== "true") {
      event.preventDefault();
      open(event.key === "ArrowDown" ? 0 : -1);
    }
  });
  list.addEventListener("keydown", (event) => {
    const all = items();
    const at = all.indexOf(document.activeElement);
    const to = { ArrowDown: at + 1, ArrowUp: at - 1, Home: 0, End: all.length - 1 }[event.key];
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      close(true);
    } else if (event.key === "Tab") {
      button.focus();     // Tab goes on from Revise itself, and the menu shuts
      close(false);
    } else if (to !== undefined) {
      event.preventDefault();
      all[(to + all.length) % all.length].focus();
    }
  });
  wrap.addEventListener("focusout", (event) => {
    if (!wrap.contains(event.relatedTarget)) close(false);
  });
  return wrap;
}

const reviseButton = () => parts.revise && parts.revise.querySelector("button");

// ---------- the text: shown as LinkedIn shows it, edited where it is ----------

// The text, as a paragraph a screen reader reads; drawn only when the text, its fold or whether it can be edited
// changed, and with the focus put back on …more when it was there.
function drawBody() {
  if (ed.editing) return;
  const text = ed.data.text || "";
  const fold = foldOf(text);
  const showAll = ed.expanded || !fold.folded;
  const can = editable();
  drawIfChanged(parts.body, JSON.stringify([text, fold.folded, showAll, can]), () => {
    const onMore = !!(document.activeElement && document.activeElement.closest && document.activeElement.closest(".li-more")
      && parts.body.contains(document.activeElement));
    const shown = showAll ? text.trim() : fold.shown;
    const empty = !text.trim();
    const more = fold.folded ? h("button", { class: "li-more", type: "button", "aria-expanded": String(showAll) }, showAll ? " …less" : "…more") : null;
    if (more) {
      more.addEventListener("click", () => {
        ed.expanded = !ed.expanded;   // for everyone: reading it whole is not editing it
        drawBody();
      });
    }
    const read = h("p", { class: `li-text li-read${can ? "" : " locked"}${empty ? " placeholder" : ""}` },
      empty ? (can ? "Write your post here, or ask Claude on the right. The first two lines are the hook." : "Nothing written yet.") : withBlanks(shown),
      fold.folded && !showAll ? " " : null, more);
    if (can) {
      read.addEventListener("click", (event) => {
        if (event.target.closest(".li-more")) return;
        openEditor(empty ? 0 : indexAt(event, read, shown));
      });
    }
    put(parts.body, read);
    if (onMore) focusFirst(parts.body.querySelector(".li-more"));
  });
}

// The character of the text a click landed on, so the editor opens with the caret there.
function indexAt(event, read, shown) {
  if (!event.clientX || !document.caretRangeFromPoint) return shown.length;
  const range = document.caretRangeFromPoint(event.clientX, event.clientY);
  if (!range || !read.contains(range.startContainer)) return shown.length;
  let at = 0;
  const walker = document.createTreeWalker(read, NodeFilter.SHOW_TEXT,
    { acceptNode: (node) => (node.parentElement.closest(".li-more") ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT) });
  while (walker.nextNode()) {
    if (walker.currentNode === range.startContainer) return Math.min(at + range.startOffset, shown.length);
    at += walker.currentNode.nodeValue.length;
  }
  return shown.length;
}

function openEditor(caret = 0, select = 0) {
  if (!editable()) return;
  ed.editing = true;
  const ta = h("textarea", { class: "li-edit", "aria-label": "The post’s text", spellcheck: "true",
    placeholder: "Write your post. The first two lines are the hook." });
  ta.value = ed.data.text || "";
  const foldLine = h("div", { class: "li-fold", "aria-hidden": "true" }, h("span", null, "…more"));
  put(parts.body, ta, foldLine);
  forget(parts.body);     // the text is drawn afresh when the editor closes
  autosize(ta);
  ta.addEventListener("input", () => {
    autosize(ta);
    ed.typed = true;
    edited();
    placeFold();
    refreshCounts(ta.value);
  });
  ta.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      closeEditor(true);
    }
  });
  ta.addEventListener("blur", () => setTimeout(() => {
    if (ed.editing && document.activeElement !== ta && !(document.activeElement && document.activeElement.closest && document.activeElement.closest(".blanks"))) closeEditor(false);
  }, 120));
  ta.focus({ preventScroll: true });
  ta.setSelectionRange(caret, caret + select);
  placeFold();
}

function placeFold() {
  const ta = parts.body.querySelector("textarea");
  const line = parts.body.querySelector(".li-fold");
  if (!ta || !line) return;
  const fold = foldOf(ta.value);
  line.hidden = !fold.folded;
  if (!fold.folded) return;
  const at = ta.value.length - ta.value.trimStart().length + fold.shown.length;   // where "…more" falls in the text
  line.style.top = `${ta.offsetTop + caretY(ta, at)}px`;
}

// Leaving the text (Esc puts the focus back on Edit text): saved, and when it was typed in this time, kept as a version
// of its own (the checkpoint; a studio without that endpoint answers 404, which is fine).
async function closeEditor(focusBack) {
  if (!ed.editing) return;
  const ta = parts.body.querySelector("textarea");
  if (ta) ed.data.text = ta.value;
  ed.editing = false;
  const typed = ed.typed;
  ed.typed = false;
  const id = ed.id;
  const saved = await saveNow();
  drawBody();
  if (focusBack) focusFirst(parts.edit, parts.copy, $("postGear"));
  if (typed && !saved.error) post(`/api/post/${id}/checkpoint`, {});
}

// ---------- saving ----------

function fields() {
  const ta = parts.body.querySelector("textarea");
  const fc = parts.comment.querySelector("textarea");
  return { text: ta ? ta.value : ed.data.text, first_comment: fc ? fc.value : ed.data.first_comment };
}

function edited() {
  ed.seq += 1;
  ed.dirty = true;
  parts.saved.textContent = "Unsaved changes";
  parts.saved.classList.add("dirty");
  clearTimeout(ed.timer);
  ed.timer = setTimeout(saveNow, SAVE_AFTER);
}

// Saves what is on screen (when it changed), and answers once it is kept. Approve, Audit and Revise save first.
export async function saveNow() {
  clearTimeout(ed.timer);
  if (!ed.data || !ed.dirty || !editable()) return { ok: true };
  const id = ed.id;
  const seq = ed.seq;
  const now = fields();
  parts.saved.textContent = "Saving…";
  const reply = await post(`/api/post/${id}/save`, now);
  if (id !== ed.id) return reply;
  if (reply.error) {
    parts.saved.textContent = "Not saved";
    announce(reply.error, { urgent: true });
    return reply;
  }
  ed.data.text = now.text.replace(/\r\n/g, "\n").trim();
  ed.data.first_comment = (now.first_comment || "").trim();
  if (seq === ed.seq) {
    ed.dirty = false;
    parts.saved.classList.remove("dirty");
    parts.saved.textContent = `Saved ${reply.saved}`;
  }
  ed.onChange();
  return reply;
}

function refreshCounts(text) {
  parts.meter.update(text, !editable());
  const blanks = (text.match(slotRe()) || []).length;
  drawIfChanged(parts.blanks, `${blanks} ${editable()}`, () => {
    if (!blanks) return void parts.blanks.replaceChildren();
    const next = editable() ? h("button", { class: "btn small", type: "button", title: "Select the next [blank] in the text" },
      h("span", null, "Next blank"), icon("arrow-right", 14)) : null;
    if (next) next.addEventListener("click", nextBlank);
    put(parts.blanks, h("span", { class: "chip warn" }, plural(blanks, "blank to fill", "blanks to fill")), next);
  });
}

export function nextBlank() {
  if (!editable()) return;
  const text = fields().text;
  const re = slotRe();
  const ta = parts.body.querySelector("textarea");
  re.lastIndex = ta ? ta.selectionEnd || 0 : 0;
  let m = re.exec(text);
  if (!m) {
    re.lastIndex = 0;
    m = re.exec(text);
  }
  if (!m) return;
  if (!ed.editing) openEditor(m.index, m[0].length);
  const area = parts.body.querySelector("textarea");
  area.focus({ preventScroll: true });
  area.setSelectionRange(m.index, m.index + m[0].length);
  const y = caretY(area, m.index);
  const stage = parts.stage;
  stage.scrollTo({ top: Math.max(0, area.getBoundingClientRect().top - stage.getBoundingClientRect().top + stage.scrollTop + y - stage.clientHeight / 3), behavior: "smooth" });
}

// ---------- the first comment and the picture ----------

function drawComment() {
  const data = ed.data;
  const value = data.first_comment || "";
  if (editable()) {
    let fc = parts.comment.querySelector("textarea");
    if (!fc) {
      fc = h("textarea", { rows: 1, maxlength: data.first_comment_max, "aria-label": "First comment",
        placeholder: "Add a first comment (optional). Links go here, not in the post." });
      fc.addEventListener("input", () => {
        autosize(fc);
        edited();
      });
      put(parts.comment, commentAvatar(), h("div", { class: "li-bubble" }, h("b", { "data-who": "comment" }), fc));
      paintWho(parts.comment);
    }
    if (!ed.dirty && fc.value !== value) fc.value = value;
    autosize(fc);
    return;
  }
  drawIfChanged(parts.comment, `ro ${value}`, () => {
    parts.comment.hidden = !value;
    put(parts.comment, commentAvatar(), h("div", { class: "li-bubble" }, h("b", { "data-who": "comment" }), h("p", null, value)));
    paintWho(parts.comment);
  });
  if (value) parts.comment.hidden = false;
}

function drawPicture() {
  const pic = ed.data.picture;
  drawIfChanged(parts.picture, JSON.stringify([pic && pic.id, editable()]), () => {
    parts.picture.hidden = !pic;
    if (!pic) return void parts.picture.replaceChildren();
    const remove = editable() ? h("button", { class: "btn small", type: "button", title: "Take the picture off the post (it stays in Pictures)" },
      icon("x", 14), h("span", null, "Remove")) : null;
    if (remove) remove.addEventListener("click", () => whileBusy(remove, () => choosePicture(null)));
    put(parts.picture, h("img", { src: pic.url, alt: pic.prompt ? `The post’s picture: ${pic.prompt.slice(0, 140)}` : "The post’s picture",
      width: pic.width, height: pic.height }), remove);
  });
}

export async function choosePicture(imageId) {
  const reply = await post(`/api/post/${ed.id}/picture`, { image: imageId });
  if (reply.error) return announce(reply.error, { urgent: true });
  announce(imageId === null ? "The picture is off the post." : "It goes out with the post now.");
  ed.onChange();
}

// ---------- beside the post ----------

function sideCards() {
  const data = ed.data;
  const cards = [];
  if (data.revision) cards.push(["revision", JSON.stringify(data.revision), revisionCard]);
  if (data.revise_job) cards.push(["revise", JSON.stringify([data.revise_job.id, data.revise_job.status]), reviseJobCard]);
  if (data.audit || data.audit_job) cards.push(["audit", JSON.stringify([data.audit, data.audit_job && [data.audit_job.id, data.audit_job.status], editable()]), auditCard]);
  if (data.pictures.length) cards.push(["pictures", JSON.stringify([data.pictures, editable()]), picturesCard]);
  if (data.notes.length) cards.push(["notes", JSON.stringify(data.notes), notesCard]);
  if (data.plan) cards.push(["plan", JSON.stringify(data.plan), planCard]);
  return cards;
}

// Where the focus goes when the card it was in goes away: Use this version, Discard, a dismissed job → Revise or Audit.
function besideFallback(name) {
  const order = name === "audit" ? [parts.audit, reviseButton()] : [reviseButton(), parts.audit];
  return [...order, parts.edit, parts.copy, $("postGear")];
}

function drawSide() {
  const wanted = sideCards();
  const keep = new Map([...parts.side.children].map((el) => [el.dataset.card, el]));
  const holding = [...parts.side.children].find((el) => el.contains(document.activeElement)) || null;
  let refocus = null;
  const next = [];
  for (const [name, key, make] of wanted) {
    let el = keep.get(name);
    if (!el || el.dataset.key !== key) {
      const fresh = make();
      fresh.dataset.card = name;
      fresh.dataset.key = key;
      if (el && el === holding) refocus = [fresh.querySelector(".working button"), fresh.querySelector("button"), ...besideFallback(name)];
      el = fresh;
    }
    next.push(el);
  }
  if (holding && !next.includes(holding) && !refocus) refocus = besideFallback(holding.dataset.card);
  if (next.length !== parts.side.children.length || next.some((el, i) => parts.side.children[i] !== el)) parts.side.replaceChildren(...next);
  // a job at work: only its words and timer change
  if (ed.data.audit_job && ["queued", "running"].includes(ed.data.audit_job.status)) {
    const box = parts.side.querySelector('[data-card="audit"] .job-box');
    if (box) drawWorking(box, ed.data.audit_job);
  }
  if (ed.data.revise_job && ["queued", "running"].includes(ed.data.revise_job.status)) {
    const box = parts.side.querySelector('[data-card="revise"] .job-box');
    if (box) drawWorking(box, ed.data.revise_job);
  }
  parts.side.hidden = !next.length;
  if (refocus && !parts.side.contains(document.activeElement)) focusFirst(refocus);
}

// Whether the side column sits beside the post or has wrapped under it (a narrow window, or the Phone view).
function besideWords() {
  const side = parts.side;
  const was = side.hidden;
  side.hidden = false;      // measured as it would stand, and put back before anything is painted
  const under = side.getBoundingClientRect().top >= parts.device.getBoundingClientRect().bottom - 1;
  side.hidden = was;
  return under ? "under the post" : "beside the post";
}

function card(glyph, heading, extra, ...body) {
  return h("section", { class: "card fresh" },
    h("div", { class: "card-head" }, h("h3", null, icon(glyph, 15), heading), extra),
    h("div", { class: "card-body" }, ...body));
}

function revisionCard() {
  const r = ed.data.revision;
  const use = h("button", { class: "btn primary small", type: "button" }, icon("check", 14), h("span", null, "Use this version"));
  const discard = h("button", { class: "btn small", type: "button" }, "Discard");
  const act = (button, yes) => button.addEventListener("click", () => whileBusy(button, async () => {
    const reply = await post(`/api/post/${ed.id}/revision`, { job: r.job, use: yes ? 1 : 0 });
    if (reply.error) return announce(reply.error, { urgent: true });
    announce(yes ? "The revised version is the post now. Versions can go back." : "Revision discarded.");
    ed.dirty = false;
    ed.onChange();
  }));
  act(use, true);
  act(discard, false);
  return card("sparkle", "Revised version", h("span", { class: "chip busy" }, r.label),
    h("p", { class: "wdiff", "aria-label": "The revision, word by word: added words marked, removed words struck" },
      r.segments.map(([op, text]) => (op === "+" ? h("ins", null, text) : op === "-" ? h("del", null, text) : text))),
    h("div", { class: "soft" }, `${number(r.chars)} characters (yours has ${number(ed.data.chars)}). Green is added, red is removed.`),
    r.changes.length ? h("details", { class: "fold" }, h("summary", null, `Why these changes (${r.changes.length})`),
      h("ul", { class: "list fold-body" }, r.changes.map((c) => h("li", null, c)))) : null,
    h("div", { class: "form-foot" }, use, discard));
}

function reviseJobCard() {
  const job = ed.data.revise_job;
  const box = h("div", { class: "job-box" });
  if (["queued", "running"].includes(job.status)) drawWorking(box, job);
  else put(box, problemCard(job, { retry: false, onDone: () => ed.onChange() }));
  return card("pen", "Revise", null, box);
}

function auditCard() {
  const a = ed.data.audit;
  const job = ed.data.audit_job;
  const working = job && ["queued", "running"].includes(job.status);
  const box = h("div", { class: "job-box" });
  if (working) drawWorking(box, job);
  else if (job) put(box, problemCard(job, { retry: false, onDone: () => ed.onChange() }));
  const again = editable() && !working && ed.data.text.trim()
    ? h("button", { class: "btn small", type: "button" }, icon("refresh", 14), h("span", null, a ? "Audit again" : "Run the audit")) : null;
  if (again) again.addEventListener("click", () => runAudit(again));
  return card("check-circle", "Audit", null, box, a && !working ? auditView(a, { level: 4, stale: !!a.stale }) : null, again);
}

function picturesCard() {
  const data = ed.data;
  return card("image", "Pictures", null,
    h("p", { class: "soft" }, data.picture ? "The one marked goes out with the post." : "None goes out with the post yet."),
    h("div", { class: "thumbs" }, data.pictures.map((p) => {
      const choose = p.chosen
        ? h("span", { class: "chip ok" }, icon("check", 12), "On the post")
        : editable() ? h("button", { class: "btn small", type: "button" }, "Use as the picture") : null;
      if (choose && choose.tagName === "BUTTON") choose.addEventListener("click", () => whileBusy(choose, () => choosePicture(p.id)));
      return h("figure", { class: `thumb${p.chosen ? " chosen" : ""}${p.shape === "square" ? " square" : ""}` },
        h("img", { src: p.url, alt: p.source === "chatgpt" ? `Illustration: ${p.prompt.slice(0, 140)}` : `Attached picture ${p.prompt}`, loading: "lazy" }),
        h("figcaption", { class: "soft" }, p.source === "chatgpt" ? `${p.width} × ${p.height} · ChatGPT` : `Attached: ${p.prompt}`), choose);
    })));
}

function notesCard() {
  return card("info", "Notes from the writer", null, h("ul", { class: "list" }, ed.data.notes.map((n) => h("li", null, n))));
}

function planCard() {
  const p = ed.data.plan;
  return card("calendar", "From the week plan", null,
    h("dl", { class: "facts" },
      p.day ? [h("dt", null, "When"), h("dd", null, [p.day, p.time].filter(Boolean).join(", "))] : null,
      p.angle ? [h("dt", null, "Angle"), h("dd", null, p.angle)] : null,
      p.formula ? [h("dt", null, "Formula"), h("dd", null, p.formula)] : null,
      p.goal ? [h("dt", null, "Goal"), h("dd", null, p.goal)] : null));
}

// ---------- audit and revise ----------

async function runAudit(button = parts.audit) {
  await saveNow();
  const reply = await whileBusy(button, () => post(`/api/post/${ed.id}/audit`, fields()));
  if (reply.error) return announce(reply.error, { urgent: true });
  announce(`Auditing. The findings appear ${besideWords()}.`);
  ed.onChange();
}

async function runRevise(how, button) {
  await saveNow();
  const reply = await whileBusy(button, () => post(`/api/post/${ed.id}/revise`, { how, ...fields() }));
  if (reply.error) return announce(reply.error, { urgent: true });
  announce(`Revising. The revised version appears ${besideWords()}; nothing changes until you choose it.`);
  ed.onChange();
}

// ---------- drawing a post ----------

// Shows the post the studio sent. `onChange` asks for it again (after something here changed it).
export function renderPost(data, onChange) {
  ed.onChange = onChange;
  if (ed.id !== data.id || !parts.stage || !parts.stage.isConnected) {
    clearTimeout(ed.timer);
    Object.assign(ed, { id: data.id, editing: false, expanded: false, dirty: false, seq: 0 });
    build();
    for (const key of Object.keys(parts)) if (parts[key] instanceof Element) forget(parts[key]);
  }
  ed.data = { ...data };
  const hadText = parts.body.contains(document.activeElement);
  if (ed.editing && !editable()) {   // Claude began working on it, or it was approved elsewhere: back to the preview
    ed.editing = false;
  }
  if (ed.dirty && editable()) {
    const now = fields();   // what is being typed stays on screen until it is saved
    ed.data.text = now.text;
    ed.data.first_comment = now.first_comment;
  }
  drawBody();               // nothing while the editor is open; otherwise only what changed
  drawComment();
  drawPicture();
  refreshCounts(ed.editing ? fields().text : ed.data.text);
  const can = editable();
  const live = can && !!(ed.data.text || "").trim();
  parts.edit.hidden = !can;
  parts.copy.hidden = !(ed.data.text || "").trim();
  parts.copyComment.hidden = !(ed.data.first_comment || "").trim();
  parts.audit.hidden = !can;
  parts.revise.hidden = !can;
  parts.audit.setAttribute("aria-disabled", String(!live));
  reviseButton().setAttribute("aria-disabled", String(!live || !!data.revision));
  if (hadText && !parts.body.contains(document.activeElement)) focusFirst(parts.edit, parts.copy, $("postGear"));
  if (!ed.dirty) {
    parts.saved.classList.remove("dirty");
    parts.saved.textContent = data.status === "draft" ? (data.busy ? "Claude is working on it" : `Saved ${data.saved}`) : "";
  }
  drawSide();
}

export function noticeBox() {
  return parts.notice;
}

export const editorState = ed;

// Settings › You in the preview was saved (its answer is the event's detail): every preview shows it at once.
window.addEventListener("studio:profile", (event) => (event.detail && !event.detail.error ? setProfile(event.detail) : loadProfile()));
loadProfile();

// Ctrl+S saves at once.
document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s" && state.page === "post" && editable()) {
    event.preventDefault();
    saveNow();
  }
});
// Going to another page or post (a click, Alt+↑ / Alt+↓, the palette) with typing not yet saved: it is saved at once,
// to the post it was typed in.
window.addEventListener("hashchange", () => {
  if (ed.dirty && editable()) saveNow();
});
// Closing the window with typing not yet saved: it is sent on the way out.
window.addEventListener("pagehide", () => {
  if (ed.dirty && editable()) {
    fetch(`/api/post/${ed.id}/save`, { method: "POST", keepalive: true, headers: { "Content-Type": "application/json" },
      body: JSON.stringify(fields()) });
  }
});
