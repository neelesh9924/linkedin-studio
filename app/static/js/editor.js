// A post in the middle: as LinkedIn shows it (at a desktop's width or an iPhone 16's, folded at "…more", with its picture
// and first comment), and edited right there: click the text and it opens where you clicked. It saves by itself a moment
// after you stop typing (Ctrl+S at once), the meter weighs its length, blanks are marked and Next blank finds them.
// Beside it: a revision shown word by word, the audit's findings, the post's pictures and the writer's notes.
import { $, state, h, icon, post, put, plural, number, announce, whileBusy, focusFirst, drawIfChanged, forget } from "./core.js";
import { drawWorking, problemCard } from "./jobs.js";

const SAVE_AFTER = 900;   // ms after the last key
const ed = { id: null, data: null, editing: false, expanded: false, dirty: false, seq: 0, sent: 0, timer: 0, onChange: () => {} };
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
  box.update = (text) => {
    const n = Array.from(text || "").length;
    const said = meterWords(n);
    box.dataset.state = said.state;
    box.querySelector(".meter-thumb").style.left = `${(Math.min(n, scale) / scale) * 100}%`;
    put(box.querySelector(".meter-text"), h("b", null, number(n)), ` characters · ${said.tail}`);
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

// ---------- the stage, made once per post ----------

function build() {
  const page = $("postPage");
  parts.notice = h("div", { class: "notice", role: "status", hidden: true });
  parts.desktop = h("button", { class: "btn small", type: "button", "aria-pressed": "true" }, icon("desktop", 14), "Desktop");
  parts.phone = h("button", { class: "btn small", type: "button", "aria-pressed": "false" }, icon("phone", 14), "Phone");
  parts.desktop.addEventListener("click", () => setView("desktop"));
  parts.phone.addEventListener("click", () => setView("phone"));
  parts.saved = h("span", { class: "save-state", "aria-live": "off" });
  parts.audit = h("button", { class: "btn small", type: "button" }, icon("check-circle", 14), h("span", null, "Audit"));
  parts.audit.addEventListener("click", () => runAudit());
  parts.revise = reviseMenu();
  parts.bar = h("div", { class: "stage-bar" },
    h("div", { class: "segmented", role: "group", "aria-label": "Preview width" }, parts.desktop, parts.phone),
    parts.saved, h("span", { class: "grow" }), parts.audit, parts.revise);
  parts.body = h("div", { class: "li-body" });
  parts.picture = h("figure", { class: "li-picture", hidden: true });
  parts.comment = h("div", { class: "li-comment" });
  parts.card = h("article", { class: "li-card", "aria-label": "The post as LinkedIn shows it" },
    h("header", { class: "li-head" }, h("span", { class: "li-avatar", "aria-hidden": "true" }, "You"),
      h("span", { class: "li-who" }, h("b", null, "You"), h("span", null, "Your headline"),
        h("span", null, "now · ", icon("globe", 11)))),
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

function reviseMenu() {
  const button = h("button", { class: "btn small", type: "button", "aria-haspopup": "true", "aria-expanded": "false" },
    icon("pen", 14), h("span", null, "Revise"), icon("chevron-down", 13));
  const list = h("div", { class: "menu-list", role: "menu", hidden: true },
    REVISE.map(([how, label, promise]) => h("button", { class: "menu-item", type: "button", role: "menuitem", "data-how": how,
      onclick: () => {
        close();
        runRevise(how, button);
      } }, h("b", null, label), h("small", null, promise))));
  const open = () => {
    list.hidden = false;
    button.setAttribute("aria-expanded", "true");
    list.querySelector("button").focus();
  };
  const close = (back) => {
    list.hidden = true;
    button.setAttribute("aria-expanded", "false");
    if (back) button.focus();
  };
  button.addEventListener("click", () => (list.hidden ? open() : close()));
  list.addEventListener("keydown", (event) => {
    const items = [...list.querySelectorAll("button")];
    const at = items.indexOf(document.activeElement);
    if (event.key === "Escape") close(true);
    else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      items[(at + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length].focus();
    }
  });
  document.addEventListener("click", (event) => {
    if (!list.hidden && !wrap.contains(event.target)) close();
  });
  const wrap = h("div", { class: "menu" }, button, list);
  return wrap;
}

// ---------- the text: shown as LinkedIn shows it, edited where it is ----------

function drawBody() {
  const data = ed.data;
  if (ed.editing) return;
  const text = data.text || "";
  const fold = foldOf(text);
  const showAll = ed.expanded || !fold.folded;
  const shown = showAll ? text.trim() : fold.shown;
  const empty = !text.trim();
  let read;
  if (editable()) {
    read = h("button", { class: "li-read", type: "button", title: "Edit the text here",
      "aria-label": empty ? "Write the post" : "Edit the post’s text" }, empty ? h("span", { class: "placeholder" },
      "Write your post here, or ask Claude on the right. The first two lines are the hook.") : withBlanks(shown));
    read.addEventListener("click", (event) => openEditor(indexAt(event, read, shown)));
  } else {
    read = h("span", { class: "li-read locked" }, empty ? "Nothing written yet." : withBlanks(shown));
  }
  const more = fold.folded ? h("button", { class: "li-more", type: "button", "aria-expanded": String(showAll) }, showAll ? " …less" : "…more") : null;
  if (more) {
    more.addEventListener("click", () => {
      if (editable() && !showAll) return openEditor(text.length);
      ed.expanded = !ed.expanded;
      drawBody();
      focusFirst(parts.body.querySelector(".li-more"));
    });
  }
  put(parts.body, h("p", { class: `li-text${empty ? " placeholder" : ""}` }, read, fold.folded && !showAll ? " " : null, more));
}

// The character of the text a click landed on, so the editor opens with the caret there.
function indexAt(event, read, shown) {
  if (!event.clientX || !document.caretRangeFromPoint) return shown.length;
  const range = document.caretRangeFromPoint(event.clientX, event.clientY);
  if (!range || !read.contains(range.startContainer)) return shown.length;
  let at = 0;
  const walker = document.createTreeWalker(read, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    if (walker.currentNode === range.startContainer) return at + range.startOffset;
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
  autosize(ta);
  ta.addEventListener("input", () => {
    autosize(ta);
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

async function closeEditor(focusText) {
  if (!ed.editing) return;
  const ta = parts.body.querySelector("textarea");
  if (ta) ed.data.text = ta.value;
  ed.editing = false;
  await saveNow();
  drawBody();
  if (focusText) focusFirst(parts.body.querySelector(".li-read"));
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
  parts.meter.update(text);
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
      put(parts.comment, h("span", { class: "li-avatar", "aria-hidden": "true" }, "You"),
        h("div", { class: "li-bubble" }, h("b", null, "You · first comment"), fc));
    }
    if (!ed.dirty && fc.value !== value) fc.value = value;
    autosize(fc);
    return;
  }
  drawIfChanged(parts.comment, `ro ${value}`, () => {
    parts.comment.hidden = !value;
    put(parts.comment, h("span", { class: "li-avatar", "aria-hidden": "true" }, "You"),
      h("div", { class: "li-bubble" }, h("b", null, "You · first comment"), h("p", null, value)));
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

function drawSide() {
  const wanted = sideCards();
  const keep = new Map([...parts.side.children].map((el) => [el.dataset.card, el]));
  const next = [];
  for (const [name, key, make] of wanted) {
    let el = keep.get(name);
    if (!el || el.dataset.key !== key) {
      const fresh = make();
      fresh.dataset.card = name;
      fresh.dataset.key = key;
      if (el && el.contains(document.activeElement)) requestAnimationFrame(() => focusFirst(fresh.querySelector("button")));
      el = fresh;
    }
    next.push(el);
  }
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
  const passed = a && a.verdict === "PASS";
  const chip = a && !working ? h("span", { class: `chip ${passed ? "ok" : "bad"}` }, passed ? "Passed" : "Needs work") : null;
  const again = editable() && !working && ed.data.text.trim()
    ? h("button", { class: "btn small", type: "button" }, icon("refresh", 14), h("span", null, a ? "Audit again" : "Run the audit")) : null;
  if (again) again.addEventListener("click", () => runAudit(again));
  return card("check-circle", "Audit", chip, box,
    a && !working ? [
      a.stale ? h("div", { class: "result warn" }, icon("alert", 15), h("div", null, "The text changed after this audit.")) : null,
      a.summary ? h("p", { class: "soft" }, a.summary) : null,
      (a.blockers || []).map((b) => finding(b, true)), (a.warnings || []).map((b) => finding(b, false))] : null,
    again);
}

function finding(item, blocker) {
  const issue = typeof item === "string" ? item : item.issue;
  const fix = typeof item === "string" ? "" : item.fix;
  return h("div", { class: `finding${blocker ? " blocker" : ""}` }, h("b", null, issue), fix ? h("span", null, fix) : null);
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
  announce("Auditing. The findings appear beside the post.");
  ed.onChange();
}

async function runRevise(how, button) {
  await saveNow();
  const reply = await whileBusy(button, () => post(`/api/post/${ed.id}/revise`, { how, ...fields() }));
  if (reply.error) return announce(reply.error, { urgent: true });
  announce("Revising. The revised version appears beside the post; nothing changes until you choose it.");
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
  const wasEditable = editable();
  ed.data = { ...data };
  if (ed.editing && !editable()) {   // Claude began working on it, or it was approved elsewhere: back to the preview
    ed.editing = false;
  }
  if (ed.dirty && editable()) {
    const now = fields();   // what is being typed stays on screen until it is saved
    ed.data.text = now.text;
    ed.data.first_comment = now.first_comment;
  }
  if (!ed.editing) drawBody();
  else if (!wasEditable) drawBody();
  drawComment();
  drawPicture();
  refreshCounts(ed.editing ? fields().text : ed.data.text);
  const live = editable() && !!(ed.data.text || "").trim();
  parts.audit.hidden = !editable();
  parts.revise.hidden = !editable();
  parts.audit.setAttribute("aria-disabled", String(!live));
  parts.revise.querySelector("button").setAttribute("aria-disabled", String(!live || !!data.revision));
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

// Ctrl+S saves at once.
document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s" && state.page === "post" && editable()) {
    event.preventDefault();
    saveNow();
  }
});
// Closing the window with typing not yet saved: it is sent on the way out.
window.addEventListener("pagehide", () => {
  if (ed.dirty && editable()) {
    fetch(`/api/post/${ed.id}/save`, { method: "POST", keepalive: true, headers: { "Content-Type": "application/json" },
      body: JSON.stringify(fields()) });
  }
});
