// The page's shared parts, one definition each for every area (as in the owner's other studios): its state (as the
// studio last said it), making elements and icons, asking the studio, words and numbers, the dialog, and the helpers at
// the end (speaking to a screen reader, a busy button, moving the focus, drawing only what changed, after each poll, the
// window's title, a banner, a toast).

export const $ = (id) => document.getElementById(id);

export const state = {
  page: "", postId: null, posts: [], jobs: [], ended: [], rev: -1, seq: 0, setup: false, tz: "", chatgpt: false,
  target: { min: 900, max: 1300, hard: 3000, fold: 210 }, offline: false, view: "desktop", titleMark: "", first: true,
};

export function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (name === "class") el.className = value;
    else if (name.startsWith("on")) el.addEventListener(name.slice(2), value);
    else el.setAttribute(name, value === true ? "" : value);
  }
  for (const kid of kids.flat(Infinity)) {   // lists inside lists too: a card's findings come that way
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

const SVG = "http://www.w3.org/2000/svg";
// Line icons on a 24 x 24 grid, drawn with stroke only. The other studios' own, and shapes from Feather
// (https://feathericons.com, MIT, Copyright (c) 2013-2023 Cole Bemis: THIRD_PARTY_NOTICES.md).
export const ICONS = {
  plus: ["M12 5v14", "M5 12h14"],
  refresh: ["M20 11a8 8 0 1 0-2.3 6.3", "M20 4v7h-7"],
  external: ["M14 5h5v5", "M19 5l-8 8", "M17 14v4a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1h4"],
  sparkle: ["M11 3l1.9 5.1L18 10l-5.1 1.9L11 17l-1.9-5.1L4 10l5.1-1.9z", "M18.5 15l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z"],
  globe: ["M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z", "M3.5 9h17", "M3.5 15h17", "M12 3c2.5 2.7 3.6 5.7 3.6 9s-1.1 6.3-3.6 9", "M12 3c-2.5 2.7-3.6 5.7-3.6 9s1.1 6.3 3.6 9"],
  stop: ["M7 7h10v10H7z"],
  send: ["M12 19V5", "M6 11l6-6 6 6"],
  trash: ["M4 7h16", "M9 7V4h6v3", "M6.5 7l1 13h9l1-13"],
  panel: ["M4 5h16v14H4z", "M15 5v14"],
  lock: ["M6 11h12v9H6z", "M9 11V8a3 3 0 0 1 6 0v3"],
  alert: ["M12 4l9 16H3z", "M12 10v4", "M12 17.2v.3"],
  check: ["M5 12.5l4.5 4.5L19 7.5"],
  settings: ["M4 7h9", "M19 7h1", "M4 17h3", "M13 17h7", "M16 5a2 2 0 1 0 0 4 2 2 0 0 0 0-4z", "M10 15a2 2 0 1 0 0 4 2 2 0 0 0 0-4z"],
  gear: ["M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z", "M19.4 13.5l1.6 1-2 3.4-1.8-.6a7 7 0 0 1-2.4 1.4L14.4 21h-4l-.4-2.3a7 7 0 0 1-2.4-1.4l-1.8.6-2-3.4 1.6-1a7 7 0 0 1 0-3l-1.6-1 2-3.4 1.8.6A7 7 0 0 1 10 5.3L10.4 3h4l.4 2.3a7 7 0 0 1 2.4 1.4l1.8-.6 2 3.4-1.6 1a7 7 0 0 1 0 3z"],
  moon: ["M20 14.5A8 8 0 0 1 9.5 4a7 7 0 1 0 10.5 10.5z"],
  sun: ["M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z", "M12 3v2", "M12 19v2", "M3 12h2", "M19 12h2", "M5.6 5.6L7 7", "M17 17l1.4 1.4", "M5.6 18.4L7 17", "M17 7l1.4-1.4"],
  copy: ["M9 9h11v11H9z", "M5 15H4V4h11v1"],
  chat: ["M20.5 11.5a8.5 8.5 0 0 1-12.3 7.6L3.5 20.5l1.4-4.5A8.5 8.5 0 1 1 20.5 11.5z"],
  image: ["M4 5h16v14H4z", "M4 16l5-5 4 4 2-2 5 5", "M15.5 8.5h.01"],
  file: ["M6 3h8l4 4v14H6z", "M14 3v4h4", "M9 12h6", "M9 16h6"],
  x: ["M6 6l12 12", "M18 6L6 18"],
  phone: ["M8 3h8a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z", "M11 18h2"],
  desktop: ["M3 5h18v11H3z", "M8 20h8", "M12 16v4"],
  user: ["M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8z", "M4.5 20a7.5 7.5 0 0 1 15 0"],
  history: ["M3.5 12a8.5 8.5 0 1 0 2.6-6.1", "M3 4v4.5h4.5", "M12 8v4.5l3 2"],
  // from Feather
  calendar: ["M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z", "M16 2v4", "M8 2v4", "M3 10h18"],
  book: ["M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z", "M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"],
  tool: ["M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"],
  pen: ["M12 20h9", "M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"],
  feather: ["M20.24 12.24a6 6 0 0 0-8.49-8.49L5 10.5V19h8.5z", "M16 8L2 22", "M17.5 15H9"],
  anchor: ["M12 2a3 3 0 1 0 0 6 3 3 0 0 0 0-6z", "M12 22V8", "M5 12H2a10 10 0 0 0 20 0h-3"],
  comment: ["M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"],
  repeat: ["M17 1l4 4-4 4", "M3 11V9a4 4 0 0 1 4-4h14", "M7 23l-4-4 4-4", "M21 13v2a4 4 0 0 1-4 4H3"],
  help: ["M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20z", "M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3", "M12 17h.01"],
  play: ["M5 3l14 9-14 9V3z"],
  pause: ["M6 4h4v16H6z", "M14 4h4v16h-4z"],
  clock: ["M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20z", "M12 6v6l4 2"],
  power: ["M18.36 6.64a9 9 0 1 1-12.73 0", "M12 2v10"],
  target: ["M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20z", "M12 6a6 6 0 1 0 0 12 6 6 0 0 0 0-12z", "M12 10a2 2 0 1 0 0 4 2 2 0 0 0 0-4z"],
  eye: ["M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z", "M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z"],
  activity: ["M22 12h-4l-3 9L9 3l-3 9H2"],
  info: ["M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20z", "M12 16v-4", "M12 8h.01"],
  "check-circle": ["M22 11.08V12a10 10 0 1 1-5.93-9.14", "M22 4L12 14.01l-3-3"],
  folder: ["M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"],
  list: ["M8 6h13", "M8 12h13", "M8 18h13", "M3 6h.01", "M3 12h.01", "M3 18h.01"],
  "arrow-right": ["M5 12h14", "M12 5l7 7-7 7"],
  "arrow-left": ["M19 12H5", "M12 19l-7-7 7-7"],
  "chevron-down": ["M6 9l6 6 6-6"],
  plane: ["M22 2L11 13", "M22 2l-7 20-4-9-9-4 20-7z"],
  like: ["M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3z", "M7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"],
  search: ["M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z", "M20 20l-4.2-4.2"],
  keyboard: ["M3 6h18v12H3z", "M7 10h.01", "M11 10h.01", "M15 10h.01", "M7 14h10"],
};

export function icon(name, size = 16) {
  const svg = document.createElementNS(SVG, "svg");
  const attrs = { viewBox: "0 0 24 24", width: size, height: size, fill: "none", stroke: "currentColor", "stroke-width": 1.9,
    "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true", class: "icon" };
  for (const [key, value] of Object.entries(attrs)) svg.setAttribute(key, value);
  for (const d of ICONS[name] || ICONS.info) {
    const shape = document.createElementNS(SVG, "path");
    shape.setAttribute("d", d);
    svg.append(shape);
  }
  return svg;
}

// ---------- asking the studio ----------

// A window opened before the studio restarted holds the old cookie: everything it asks is refused (401).
export const lost = { said: false };

async function ask(path, options) {
  const response = await fetch(path, { credentials: "same-origin", ...options });
  if (response.status === 401) {
    lost.said = true;
    return { error: "This window belongs to an earlier session. Open LinkedIn Studio from its shortcut again.", lost: true };
  }
  try {
    const body = await response.json();
    if (!response.ok && !body.error) body.error = `Something went wrong (${response.status}).`;
    return body;
  } catch {
    return { error: `Something went wrong (${response.status}).` };
  }
}

export async function api(path) {
  try {
    return await ask(path);
  } catch {
    return { error: "The studio did not answer.", offline: true };
  }
}

export async function post(path, body) {
  try {
    return await ask(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  } catch {
    return { error: "The studio did not answer.", offline: true };
  }
}

// replaceChildren would print a missing piece as the word "null".
export function put(box, ...pieces) {
  box.replaceChildren(...pieces.flat().filter(Boolean));
}

export const plural = (n, one, many) => `${number(n)} ${n === 1 ? one : many}`;
export const number = (n) => Number(n || 0).toLocaleString("en-IN");
export const clockOf = (seconds) => `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
export const currentPost = () => state.posts.find((p) => p.id === state.postId) || null;
export const jobFor = (test) => state.jobs.find(test) || null;
export const running = () => state.jobs.find((j) => j.status === "running") || null;

export function go(hash) {
  if (location.hash === hash) window.dispatchEvent(new HashChangeEvent("hashchange"));
  else location.hash = hash;
}

export function suggestion(text, use) {
  return h("button", { class: "suggest", type: "button", onclick: use }, text);
}

// A copy button: what it copies, said and shown for a moment.
export function copyButton(text, label = "Copy", small = true) {
  const button = h("button", { class: `btn${small ? " small" : ""}`, type: "button" }, icon("copy", 14), h("span", null, label));
  button.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(typeof text === "function" ? text() : text);
      button.classList.add("copied");
      button.lastChild.textContent = "Copied";
      announce("Copied");
      setTimeout(() => {
        button.classList.remove("copied");
        button.lastChild.textContent = label;
      }, 1400);
    } catch {
      announce("Could not copy. Select the text and press Ctrl+C.", { urgent: true });
    }
  });
  return button;
}

// ---------- the dialog ----------

export function closeButton(label = "Close") {
  return h("button", { class: "btn", type: "button", onclick: () => closeDialog() }, label);
}

export function closeDialog() {
  $("dialog").close();
}

export function showDialog(...content) {
  $("dialog").classList.remove("wide", "palette");
  $("dialog").replaceChildren(...content.flat().filter(Boolean));
  if (!$("dialog").open) $("dialog").showModal();
  const first = $("dialog").querySelector("[autofocus], input:not([type=hidden]), textarea, select, button");
  if (first) first.focus();
}

// A screen reader names the dialog by its first heading, and describes it by the paragraph right after that heading
// when there is one. Done again whenever the dialog's content changes, however it changed.
function nameDialog() {
  const dialog = $("dialog");
  const title = dialog.querySelector("h2");
  const said = title && title.nextElementSibling && title.nextElementSibling.tagName === "P" ? title.nextElementSibling : null;
  for (const [attribute, el, id] of [["aria-labelledby", title, "dialog-title"], ["aria-describedby", said, "dialog-said"]]) {
    if (!el) {
      dialog.removeAttribute(attribute);
      continue;
    }
    if (!el.id) el.id = id;
    dialog.setAttribute(attribute, el.id);
  }
}
new MutationObserver(nameDialog).observe($("dialog"), { childList: true });

// A click on the dialog's backdrop closes it, as Esc does; a closed dialog keeps nothing.
$("dialog").addEventListener("click", (event) => {
  if (event.target === $("dialog")) closeDialog();
});
$("dialog").addEventListener("close", () => {
  if (!$("dialog").open) $("dialog").replaceChildren();
});

// ---------- helpers every area shares, one definition each ----------

// Says text once to a screen reader: politely through #announce (role=status), or at once through #alarm (role=alert)
// when urgent. The region is emptied first and the words put in on the next frame, so the same words twice are said
// twice. While the dialog is open the rest of the page is inert: the region speaks from inside the dialog meanwhile.
const regions = {};
const speaking = new Map();
export function announce(text, { urgent = false } = {}) {
  const id = urgent ? "alarm" : "announce";
  const region = regions[id] || (regions[id] = $(id));
  if (!region) return;
  const dialog = $("dialog");
  const home = dialog && dialog.open ? dialog : document.body;
  if (region.parentNode !== home) {
    home.append(region);
    if (home === dialog) dialog.addEventListener("close", () => document.body.append(region), { once: true });
  }
  cancelAnimationFrame(speaking.get(region));
  region.textContent = "";
  speaking.set(region, requestAnimationFrame(() => {
    speaking.delete(region);
    region.textContent = text;
  }));
}

// Runs work() with the button busy: aria-disabled and aria-busy while it runs and its clicks ignored, but never the
// disabled property, so the button keeps the focus and a screen reader stays on it. Returns work()'s result.
export async function whileBusy(button, work) {
  const before = ["aria-disabled", "aria-busy"].map((name) => [name, button.getAttribute(name)]);
  const ignore = (event) => {
    event.preventDefault();
    event.stopImmediatePropagation();
  };
  button.addEventListener("click", ignore, true);
  button.setAttribute("aria-disabled", "true");
  button.setAttribute("aria-busy", "true");
  try {
    return await work();
  } finally {
    button.removeEventListener("click", ignore, true);
    for (const [name, value] of before) {
      if (value === null) button.removeAttribute(name);
      else button.setAttribute(name, value);
    }
  }
}

// Moves the focus to the first of the candidates (elements, or selectors) that is in the page, shown and not disabled;
// one that can't take the focus by itself is given tabindex="-1" first. Returns the element, or null.
export function focusFirst(...candidates) {
  for (const candidate of candidates.flat()) {
    const el = typeof candidate === "string" ? document.querySelector(candidate) : candidate;
    if (!(el instanceof Element) || !el.isConnected || !el.getClientRects().length || getComputedStyle(el).visibility === "hidden"
      || el.matches(":disabled")) continue;
    el.focus();
    if (document.activeElement === el) return el;
    if (el.hasAttribute("tabindex")) continue;
    el.setAttribute("tabindex", "-1");
    el.focus();
    if (document.activeElement === el) return el;
    el.removeAttribute("tabindex");
  }
  return null;
}

// Draws into box only when key (what it would show, as a string) differs from the key last drawn there.
const drawn = new WeakMap();
export function drawIfChanged(box, key, draw) {
  if (drawn.has(box) && drawn.get(box) === key) return false;
  draw();
  drawn.set(box, key);
  return true;
}
export function forget(box) {
  drawn.delete(box);
}

// What runs after each poll that reached the studio, once every area has drawn, in the order registered.
const afterPoll = [];
export function onPoll(fn) {
  afterPoll.push(fn);
}
export function polled(data) {
  for (const fn of afterPoll.slice()) {
    try {
      fn(data);
    } catch (error) {
      reportError(error);
    }
  }
}

// The window's title: state.titleMark first ("" for none), then base. Every title is set here.
let titleBase = "LinkedIn Studio";
export function setTitle(base) {
  titleBase = base;
  document.title = `${state.titleMark || ""}${base}`;
}
export const title = () => titleBase;

// A notice across the top of the page, kept by its key in #banners: content puts it up or changes it; null takes it down.
// Its words (not its buttons) are said once when it goes up and again only when they change: urgently for "bad".
export function banner(key, content, kind = "") {
  const box = $("banners");
  let note = [...box.children].find((child) => child.dataset.banner === key) || null;
  if (content === null || content === undefined) {
    if (note) note.remove();
    note = null;
  } else {
    if (!note) note = box.appendChild(h("div", { class: "notice", "data-banner": key }));
    note.className = `notice ${kind}`.trim();
    put(note, content);
  }
  box.hidden = !box.children.length;
  if (note) {
    const words = wordsOf(note);
    if (words && note.dataset.said !== words) {
      note.dataset.said = words;
      announce(words, { urgent: kind === "bad" });
    }
  }
  return note;
}

function wordsOf(el) {
  return [...el.childNodes].map((node) => (node.nodeType === Node.TEXT_NODE ? node.nodeValue
    : node instanceof HTMLElement && !node.matches("button, .btn") ? node.innerText : ""))
    .join(" ").replace(/\s+/g, " ").trim();
}

// A short note at the foot of the main column, beside the sidebar and never over Ask Claude's box, with a link to where
// its news is: said aloud as well, politely. Its time stops while the pointer or the focus is on it. When it goes with
// the focus in it, the focus goes back to where it came from.
export function toast(text, href = "", label = "Open") {
  const box = $("toasts");
  const close = h("button", { class: "btn small square", type: "button", "aria-label": "Dismiss" }, icon("x", 14));
  const el = h("div", { class: "toast" }, h("span", null, text),
    href ? h("a", { href, onclick: () => remove() }, label) : null, close);
  let left = href ? 12000 : 6000;
  let since = 0;
  let timer = 0;
  let hovered = false;
  let focused = false;
  let cameFrom = null;
  const run = () => {
    since = Date.now();
    timer = setTimeout(remove, left);
  };
  const hold = () => {
    if ((hovered || focused) && timer) {
      clearTimeout(timer);
      timer = 0;
      left = Math.max(left - (Date.now() - since), 2500);
    } else if (!hovered && !focused && !timer && el.isConnected) run();
  };
  function remove() {
    clearTimeout(timer);
    const had = el.contains(document.activeElement);
    el.remove();
    if (had) focusFirst(cameFrom, box.querySelector(".toast .btn"), $("title"));
  }
  el.addEventListener("pointerenter", () => { hovered = true; hold(); });
  el.addEventListener("pointerleave", () => { hovered = false; hold(); });
  el.addEventListener("focusin", (event) => {
    if (!el.contains(event.relatedTarget)) cameFrom = event.relatedTarget;
    focused = true;
    hold();
  });
  el.addEventListener("focusout", (event) => {
    focused = el.contains(event.relatedTarget);
    hold();
  });
  close.addEventListener("click", remove);
  box.append(el);
  while (box.children.length > 3) box.firstElementChild.remove();
  run();
  announce(text);
}
