// A post in the middle: as LinkedIn shows it (at a desktop's width or an iPhone 16's, folded at "…more", with its pictures
// in LinkedIn's grid or its carousel as a document to page through, and its first comment), and edited right there: click
// the text and it opens where you clicked, or press Edit text; Bold (Ctrl+B) makes the selection LinkedIn's bold. It
// saves by itself a moment after you stop typing (Ctrl+S at once), the meter weighs its length, blanks are marked and
// Next blank finds them. Style holds its sliders and Restyle; Carousel asks Claude for one. Beside it: a revision shown
// word by word, the audit's findings, the post's pictures (Add to the post, their order, Remove from post) and the writer's
// notes. The text is read as a paragraph, and drawn again only when it changes, so the focus stays put.
// Above it and beside the first comment: your name, headline and photo from Settings › You in the preview, or You.
import { $, state, h, icon, api, post, put, plural, number, announce, whileBusy, focusFirst, drawIfChanged, forget, copyButton,
  showDialog, closeDialog, closeButton,
  recall, keep } from "./core.js";
import { drawWorking, problemCard } from "./jobs.js";
import { auditView } from "./audit.js";
import { wordDiff } from "./wdiff.js";
import { ALWAYS, styleSliders } from "./style.js";
import { toggleBold } from "./bold.js";
import { askClaude } from "./assist.js";

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
  parts.style = styleMenu();
  parts.carousel = h("button", { class: "btn small", type: "button", "data-act": "carousel",
    title: "Ask Claude for a carousel or a card of this post: in a look unlike your last ones, with ChatGPT art where it helps" },
  icon("image", 14), h("span", null, "Carousel"));
  parts.carousel.addEventListener("click", () => {
    if (parts.carousel.getAttribute("aria-disabled") === "true") return;
    askClaude("Make a carousel or a card of this post: the layouts that teach it best, in a look unlike the last ones, "
      + "with ChatGPT art where a character or an object helps.");
  });
  parts.bar = h("div", { class: "stage-bar" },
    h("div", { class: "segmented", role: "group", "aria-label": "Preview width" }, parts.desktop, parts.phone),
    parts.saved, h("div", { class: "stage-acts" }, parts.edit, parts.copy, parts.copyComment, parts.audit, parts.revise, parts.style,
      parts.carousel));
  parts.body = h("div", { class: "li-body" });
  parts.picture = h("div", { class: "li-media", hidden: true });
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
  return recall("view") === "phone" ? "phone" : "desktop";
}

export function setView(view) {
  state.view = view;
  parts.desktop.setAttribute("aria-pressed", String(view === "desktop"));
  parts.phone.setAttribute("aria-pressed", String(view === "phone"));
  parts.stage.classList.toggle("phone", view === "phone");
  keep("view", view);
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
const styleButton = () => parts.style && parts.style.querySelector("button");

// Style: the post's three sliders (style.js), at its own style or the owner's default, and Restyle, which asks for the
// same post in them. Like Revise, the result waits beside the post until it is used or discarded; the sliders become
// this post's own style. Esc, Tab out or a click elsewhere closes the panel.
function styleMenu() {
  const button = h("button", { class: "btn small", type: "button", id: "styleBtn", "data-act": "style", "aria-haspopup": "dialog",
    "aria-expanded": "false", "aria-controls": "stylePanel" }, icon("sliders", 14), h("span", null, "Style"), icon("chevron-down", 13));
  const panel = h("div", { class: "menu-list style-panel", id: "stylePanel", role: "dialog", "aria-label": "Post style", hidden: true });
  const wrap = h("div", { class: "menu" }, button, panel);
  const me = { wrap, close };
  async function open() {
    const look = await api("/api/style");     // the steps' names, and the default as Settings has it now
    if (look.error) return announce(look.error, { urgent: true });
    const mine = ed.data.style || { value: look.style, own: false };
    const control = styleSliders(look, mine.value, "post-style");
    const go = h("button", { class: "btn primary small", type: "button", "data-act": "restyle" }, icon("sparkle", 14), h("span", null, "Restyle"));
    go.addEventListener("click", () => {
      close(true);
      runRestyle(control.values(), button);
    });
    const back = h("button", { class: "btn ghost small", type: "button", title: "Moves the sliders to your default from Settings › Post style" },
      "Your default");
    back.addEventListener("click", () => control.set(look.style));
    put(panel, h("p", { class: "style-whose" }, mine.own ? "This post’s own style" : "Your default, from Settings › Post style"),
      control.element, h("p", { class: "soft" }, ALWAYS), h("div", { class: "form-foot" }, go, back));
    panel.hidden = false;
    button.setAttribute("aria-expanded", "true");
    openMenu = me;
    panel.querySelector("input").focus();
  }
  function close(backToButton) {
    if (openMenu === me) openMenu = null;
    if (panel.hidden) return;
    panel.hidden = true;
    button.setAttribute("aria-expanded", "false");
    if (backToButton) button.focus();
  }
  button.addEventListener("click", () => {
    if (!panel.hidden) return close(true);
    if (button.getAttribute("aria-disabled") === "true") {
      return announce(ed.data && ed.data.revision ? `A revised version is waiting ${besideWords()}: use it or discard it first.`
        : "Write the post first: Restyle works on its text.");
    }
    open();
  });
  panel.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    event.preventDefault();
    event.stopPropagation();
    close(true);
  });
  wrap.addEventListener("focusout", (event) => {
    if (!wrap.contains(event.relatedTarget)) close(false);
  });
  return wrap;
}

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
  const boldBtn = h("button", { class: "btn small bold-btn", type: "button", title: "Bold the selection, as LinkedIn shows bold (Ctrl+B). Again makes it plain." },
    h("b", { "aria-hidden": "true" }, "B"), h("span", null, "Bold"));
  boldBtn.addEventListener("mousedown", (event) => event.preventDefault());   // the selection stays in the text
  boldBtn.addEventListener("click", () => sayBold(toggleBold(ta)));
  const tools = h("div", { class: "edit-tools", role: "toolbar", "aria-label": "Text" }, boldBtn,
    h("small", null, "Bold suits the first line and short heads; code and words people search for stay plain."));
  put(parts.body, tools, ta, foldLine);
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
    } else if ((event.ctrlKey || event.metaKey) && !event.altKey && event.key.toLowerCase() === "b") {
      event.preventDefault();
      sayBold(toggleBold(ta));
    }
  });
  ta.addEventListener("blur", () => setTimeout(() => {
    const at = document.activeElement;
    if (ed.editing && at !== ta && !(at && at.closest && (at.closest(".blanks") || at.closest(".edit-tools")))) closeEditor(false);
  }, 120));
  ta.focus({ preventScroll: true });
  ta.setSelectionRange(caret, caret + select);
  placeFold();
}

function sayBold(done) {
  announce(done ? `${done}.` : "Select the words to make bold first.");
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
    parts.comment.hidden = false;   // back in draft: the box shows, empty or not
    forget(parts.comment);          // and a read-only view later is drawn afresh
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

// What goes out with the post, as LinkedIn shows it: one picture whole; two side by side; three or more with the first
// across the top and the next three under it, "+N" on the last; a carousel as a document with its title, paged.
function drawMedia() {
  const media = ed.data.media || [];
  drawIfChanged(parts.picture, JSON.stringify([media.map((m) => m.url), editable()]), () => {   // a redrawn carousel: a new url
    parts.picture.hidden = !media.length;
    if (!media.length) return void parts.picture.replaceChildren();
    const off = editable() ? h("button", { class: "btn small off", type: "button",
      title: media.length > 1 ? "The pictures stay in Pictures, beside the post" : "It stays in Pictures, beside the post" },
    icon("x", 14), h("span", null, "Remove from post")) : null;
    if (off) off.addEventListener("click", () => whileBusy(off, () => setPictures([], media.length > 1 ? "Removed from the post. They stay in Pictures." : "Removed from the post. It stays in Pictures.")));
    put(parts.picture, media[0].kind === "carousel" ? documentView(media[0]) : pictureGrid(media), off);
  });
}

function altOf(p, n = 0) {
  if (p.kind === "carousel") return `Slide ${n + 1} of ${p.pages}: ${p.title}`;
  return p.source === "chatgpt" ? `Illustration: ${p.prompt.slice(0, 140)}` : p.prompt ? `Picture: ${p.prompt.slice(0, 140)}` : "Picture";
}

function pictureGrid(media) {
  const shown = media.slice(0, 4);
  const more = media.length - shown.length;
  return h("div", { class: `li-grid n${Math.min(media.length, 4)}` }, shown.map((p, i) => h("figure", null,
    h("img", { src: p.url, alt: altOf(p), width: p.width, height: p.height }),
    more && i === shown.length - 1 ? h("span", { class: "li-more-pics", "aria-label": `${more} more` }, `+${more}`) : null)));
}

const pageOf = new Map();   // a carousel's page shown in the preview, by its id
function documentView(doc) {
  let at = Math.min(pageOf.get(doc.id) || 0, doc.pages - 1);
  const img = h("img", { src: doc.page_urls[at], alt: altOf(doc, at), width: 1080, height: 1350 });
  const where = h("span", { class: "li-doc-at", "aria-live": "polite" }, `${at + 1} / ${doc.pages}`);
  const back = h("button", { class: "li-doc-turn back", type: "button", "aria-label": "Previous slide" }, icon("arrow-left", 18));
  const next = h("button", { class: "li-doc-turn next", type: "button", "aria-label": "Next slide" }, icon("arrow-right", 18));
  const turn = (step) => {
    at = Math.max(0, Math.min(doc.pages - 1, at + step));
    pageOf.set(doc.id, at);
    img.src = doc.page_urls[at];
    img.alt = altOf(doc, at);
    where.textContent = `${at + 1} / ${doc.pages}`;
    back.disabled = at === 0;
    next.disabled = at === doc.pages - 1;
  };
  back.addEventListener("click", () => turn(-1));
  next.addEventListener("click", () => turn(1));
  turn(0);
  return h("div", { class: "li-doc", role: "group", "aria-label": `Carousel: ${doc.title}` },
    h("div", { class: "li-doc-head" }, h("b", null, doc.title), h("span", null, ` • ${plural(doc.pages, "page", "pages")}`)),
    h("div", { class: "li-doc-page" }, img, back, next), h("div", { class: "li-doc-foot" }, where));
}

// What goes out with the post, in order: `ids` (an empty list sends it with none).
async function setPictures(ids, said) {
  const reply = await post(`/api/post/${ed.id}/pictures`, { ids });
  if (reply.error) return announce(reply.error, { urgent: true });
  announce(said);
  ed.onChange();
}

// A picture joins what goes out (in place of a carousel, which goes out alone); a carousel goes out alone.
export async function addToPost(p) {
  const now = (ed.data.media || []).map((m) => m.id);
  const carouselOn = (ed.data.media || []).some((m) => m.kind === "carousel");
  if (p.kind === "carousel") return setPictures([p.id], now.length ? "The carousel goes out with the post now, in place of the pictures." : "The carousel goes out with the post now.");
  if (carouselOn) return setPictures([p.id], "It goes out with the post now, in place of the carousel.");
  if (now.length >= ed.data.max_pictures) return announce(`A post takes up to ${ed.data.max_pictures} pictures. Take one off first.`, { urgent: true });
  return setPictures([...now, p.id], now.length ? `It goes out with the post now, as picture ${now.length + 1}.` : "It goes out with the post now.");
}

function takeOff(p) {
  return setPictures((ed.data.media || []).map((m) => m.id).filter((id) => id !== p.id), "Removed from the post. It stays in Pictures.");
}

function movePicture(p, step) {
  const ids = (ed.data.media || []).map((m) => m.id);
  const i = ids.indexOf(p.id);
  const j = i + step;
  if (i < 0 || j < 0 || j >= ids.length) return null;
  [ids[i], ids[j]] = [ids[j], ids[i]];
  return setPictures(ids, `Now picture ${j + 1} of ${ids.length}.`);
}

// Delete…: a picture or carousel kept with the post but not on it, after a confirm naming what goes.
function confirmDelete(p) {
  const what = p.kind === "carousel" ? "carousel" : "picture";
  const yes = h("button", { class: "btn danger", type: "button" }, icon("trash", 15), h("span", null, `Delete the ${what}`));
  const out = h("div", { class: "results" });
  yes.addEventListener("click", () => whileBusy(yes, async () => {
    const reply = await post(`/api/post/${ed.id}/picture/${p.id}/delete`, { confirmed: true });
    if (reply.error) {
      put(out, h("div", { class: "result bad" }, icon("alert", 15), h("div", null, reply.error)));
      return announce(reply.error, { urgent: true });
    }
    closeDialog();
    announce(`The ${what} is deleted.`);
    ed.onChange();
  }));
  showDialog(h("h2", null, `Delete this ${what}?`),
    h("p", null, `It isn't on the post. It goes from this post's pictures and from this computer, and it can't be undone.`),
    p.kind === "carousel" ? h("p", { class: "soft" }, `${p.title} · ${plural(p.pages, "slide", "slides")}`) : null,
    out, h("div", { class: "dialog-foot" }, closeButton(`Keep it`), yes));
}

async function makeAgain(p, look) {
  const reply = await post(`/api/post/${ed.id}/carousel`, look ? { again: p.id, look } : { again: p.id });
  if (reply.error) return announce(reply.error, { urgent: true });
  const how = look ? `Drawn in the ${reply.image.look} look` : "Redrawn";
  announce(p.chosen ? `${how} in its place, on the post still.` : `${how} in its place.`);
  ed.onChange();
}

// ---------- beside the post ----------

function sideCards() {
  const data = ed.data;
  const cards = [];
  if (data.revision) cards.push(["revision", JSON.stringify(data.revision), revisionCard]);
  if (data.revise_job) cards.push(["revise", JSON.stringify([data.revise_job.id, data.revise_job.status]), reviseJobCard]);
  if (data.audit || data.audit_job) cards.push(["audit", JSON.stringify([data.audit, data.audit_job && [data.audit_job.id, data.audit_job.status], editable()]), auditCard]);
  if (data.rank || (editable() && (data.text || "").trim())) cards.push(["rank", JSON.stringify([data.rank, editable(), data.busy]), rankCard]);
  if (data.pictures.length) cards.push(["pictures", JSON.stringify([data.pictures, data.media.map((m) => m.id), editable()]), picturesCard]);
  if (data.notes.length) cards.push(["notes", JSON.stringify(data.notes), notesCard]);
  if (data.news) cards.push(["news", JSON.stringify(data.news), newsCard]);
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
    r.how === "style" ? h("div", { class: "soft", "data-restyle": "" }, r.promise) : null,   // the sliders it was asked for
    h("p", { class: "wdiff" }, wordDiff(r.segments)),
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

// How worth posting it is, 1-10: the number and its verdict, why, and the one change that would lift it; the owner's own
// number in place of Claude's; Rank it (again) asks Claude in the chat beside the post.
function rankCard() {
  const r = ed.data.rank;
  const own = h("select", { class: "input small-select", "aria-label": "Your own rank for this post" },
    h("option", { value: "" }, r ? "Your own number…" : "Give it a number…"),
    Array.from({ length: 10 }, (_, i) => h("option", { value: String(10 - i), selected: !!(r && r.by === "you" && r.rank === 10 - i) },
      `${10 - i}/10`)));
  own.addEventListener("change", () => whileBusy(own, async () => {
    if (!own.value) return;
    const reply = await post(`/api/post/${ed.id}/rank`, { rank: Number(own.value) });
    if (reply.error) return announce(reply.error, { urgent: true });
    announce(`Ranked ${own.value} out of 10.`);
    ed.onChange();
  }));
  const ask = editable() && !ed.data.busy ? h("button", { class: "btn small", type: "button" }, icon("sparkle", 14),
    h("span", null, r ? "Rank it again" : "Ask Claude to rank it")) : null;
  if (ask) ask.addEventListener("click", () => askClaude("Rank this post: is it worth posting?"));
  const head = r ? h("p", { class: `rank-line ${r.verdict}` }, h("b", null, `${r.rank}/10`), h("span", null, ` · ${r.label}`),
    h("small", null, r.by === "you" ? " · your number" : " · Claude's rank")) : h("p", { class: "soft" }, "Not ranked yet.");
  return card("check-circle", "Rank", null, head,
    r && r.why ? h("p", null, r.by === "you" ? `Claude said: ${r.why}` : r.why) : null,
    r && r.fix ? h("p", { class: "soft" }, r.fix) : null,
    h("div", { class: "form-foot" }, ask, own));
}

// Every picture and carousel kept with the post, those going out first in their order. A picture: Add to the post, or
// its place with Earlier / Later and Remove from post. A carousel goes out alone: Use this carousel, Remove from post.
// A carousel or a card (one slide, a picture) can be drawn again: Try another look (the next look, its art kept) and
// Redraw. The line on top says which go out, in the words of their mark (On the post).
function picturesCard() {
  const data = ed.data;
  const media = data.media || [];
  const going = media.length && media[0].kind === "carousel" ? "The carousel marked On the post is posted with it. A carousel goes alone, without pictures."
    : media.length > 1 ? `The ${media.length} pictures marked On the post are posted with it, in this order. A post takes up to ${data.max_pictures}.`
      : media.length ? `The picture marked On the post is posted with it. A post takes up to ${data.max_pictures}.`
        : `Nothing is posted with it yet. A post takes up to ${data.max_pictures} pictures, or one carousel.`;
  const order = [...data.pictures].sort((a, b) => (a.order || 99) - (b.order || 99));
  return card("image", "Pictures", null, h("p", { class: "soft" }, going),
    h("div", { class: "thumbs" }, order.map((p) => thumb(p, media))));
}

function thumb(p, media) {
  const can = editable();
  const isDoc = p.kind === "carousel";
  const acts = [];
  if (can && !p.chosen) {
    const carouselOn = media.some((m) => m.kind === "carousel");
    const label = isDoc ? (carouselOn ? "Use this one instead" : media.length ? "Use instead of the pictures" : "Use this carousel")
      : carouselOn ? "Use instead of the carousel" : "Add to the post";
    const add = h("button", { class: "btn small", type: "button" }, label);
    add.addEventListener("click", () => whileBusy(add, () => addToPost(p)));
    acts.push(add);
  }
  if (can && p.chosen && !isDoc && media.length > 1) {
    const earlier = h("button", { class: "btn small icon-only", type: "button", "aria-label": `Earlier: picture ${p.order} moves to ${p.order - 1}`, disabled: p.order === 1 }, icon("arrow-left", 14));
    const later = h("button", { class: "btn small icon-only", type: "button", "aria-label": `Later: picture ${p.order} moves to ${p.order + 1}`, disabled: p.order === media.length }, icon("arrow-right", 14));
    earlier.addEventListener("click", () => whileBusy(earlier, () => movePicture(p, -1)));
    later.addEventListener("click", () => whileBusy(later, () => movePicture(p, 1)));
    acts.push(earlier, later);
  }
  if (can && p.chosen) {
    const off = h("button", { class: "btn small", type: "button", title: "It stays here, in Pictures" }, "Remove from post");
    off.addEventListener("click", () => whileBusy(off, () => takeOff(p)));
    acts.push(off);
  }
  if (can && !p.chosen) {
    const gone = h("button", { class: "btn small danger", type: "button" }, "Delete…");
    gone.addEventListener("click", () => confirmDelete(p));
    acts.push(gone);
  }
  if (can && p.look) {     // drawn from slides: a carousel, or a card (one slide, a picture)
    const other = h("button", { class: "btn small", type: "button", title: "The same slides in the next look: its art stays, and no ChatGPT picture is spent" },
      icon("refresh", 14), h("span", null, "Try another look"));
    other.addEventListener("click", () => whileBusy(other, () => makeAgain(p, "next")));
    const again = h("button", { class: "btn small", type: "button", title: "The same slides drawn again in its place: with your name on them only if Settings › You in the preview puts it on carousels" }, "Redraw");
    again.addEventListener("click", () => whileBusy(again, () => makeAgain(p)));
    acts.push(other, again);
  }
  const look = p.look ? ` · ${p.look[0].toUpperCase()}${p.look.slice(1)}` : "";
  const caption = isDoc ? `Carousel · ${plural(p.pages, "slide", "slides")}${look}` : p.card ? `Card${look}`
    : p.source === "chatgpt" ? `${p.width} × ${p.height} · ChatGPT` : `Attached: ${p.prompt}`;
  return h("figure", { class: `thumb${p.chosen ? " chosen" : ""}${p.shape === "square" ? " square" : ""}${isDoc ? " carousel" : p.card ? " tall" : ""}` },
    h("img", { src: isDoc ? p.page_urls[0] : p.url, alt: isDoc ? `Carousel, first slide: ${p.title}` : altOf(p), loading: "lazy" }),
    h("figcaption", { class: "soft" }, p.chosen ? h("span", { class: "chip ok" }, icon("check", 12), isDoc || media.length === 1 ? "On the post" : `On the post · ${p.order}`) : null,
      h("span", null, caption)),
    acts.length ? h("div", { class: "thumb-acts" }, acts) : null);
}

function notesCard() {
  return card("info", "Notes from the writer", null, h("ul", { class: "list" }, ed.data.notes.map((n) => h("li", null, n))));
}

// The news it was drafted from (Hot topics), to read before it goes out: its link is in the first comment too.
function newsCard() {
  const n = ed.data.news;
  const out = (href, words) => h("a", { href, target: "_blank", rel: "noreferrer" }, words);
  return card("flame", "From Hot topics", null,
    h("p", null, out(n.url, n.title)),
    h("p", { class: "soft" }, [n.source, n.area, n.points ? plural(n.points, "point", "points") : null,
      n.published ? new Date(n.published).toLocaleDateString("en-IN", { day: "numeric", month: "short" }) : null].filter(Boolean).join(" · "),
    n.discussion && n.discussion !== n.url ? [" · ", out(n.discussion, "The discussion")] : null));
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

async function runRestyle(chosen, button) {
  await saveNow();
  const reply = await whileBusy(button, () => post(`/api/post/${ed.id}/revise`, { how: "style", style: chosen, ...fields() }));
  if (reply.error) return announce(reply.error, { urgent: true });
  announce(`Restyling. The restyled version appears ${besideWords()}; nothing changes until you choose it.`);
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
  drawMedia();
  refreshCounts(ed.editing ? fields().text : ed.data.text);
  const can = editable();
  const live = can && !!(ed.data.text || "").trim();
  parts.edit.hidden = !can;
  parts.copy.hidden = !(ed.data.text || "").trim();
  parts.copyComment.hidden = !(ed.data.first_comment || "").trim();
  parts.audit.hidden = !can;
  parts.revise.hidden = !can;
  parts.style.hidden = !can;
  parts.carousel.hidden = !can || !data.carousels;
  parts.carousel.setAttribute("aria-disabled", String(!live));
  parts.audit.setAttribute("aria-disabled", String(!live));
  reviseButton().setAttribute("aria-disabled", String(!live || !!data.revision));
  styleButton().setAttribute("aria-disabled", String(!live || !!data.revision));
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
