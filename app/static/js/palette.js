// Ctrl+K: one box to jump to a post, a page or a tool, or to press one of the page's own controls; and the studio's
// keys, as in the owner's other studios: Alt+N a new post, Ctrl+/ the Ask box, Alt+↑ / Alt+↓ the previous or next
// post, ? the list of keys (the Guide's own, from /api/guide). Also the two skip links at the top of the page and the
// search button beside light or dark. An accessible combobox: the input owns a listbox and points at the active option
// with aria-activedescendant, so the focus never leaves the input. It starts itself once, however often it is loaded.
import { $, state, h, icon, api, go, showDialog, closeButton, announce, focusFirst, onPoll } from "./core.js";

const GROUPS = ["Posts", "Pages", "Actions"];
const SETTINGS = [["claude", "Claude"], ["publishing", "Publishing"], ["chatgpt", "ChatGPT"], ["profile", "You in the preview"],
  ["appearance", "Appearance"], ["health", "Health checks"], ["runs", "Recent runs"], ["app", "The app"]];
let openNow = null;
let tools = null;        // Tools' tools, from /api/tools the first time the palette opens

const shown = (el) => !!el && el.isConnected && el.getClientRects().length > 0;
const usable = (el) => shown(el) && !el.disabled && el.getAttribute("aria-disabled") !== "true";
const typing = (el) => !!el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));

// ---------- what it offers ----------

function items() {
  const out = [];
  for (const p of state.posts) {
    out.push({ group: "Posts", label: p.first, hint: p.title && p.title !== p.first ? `${p.title} · ${p.label}` : p.label, icon: "file",
      keys: `${p.title} ${p.label}`, current: state.page === "post" && state.postId === p.id, run: () => go(`#post-${p.id}`) });
  }
  const page = (label, hash, glyph, hint = "", keys = "") => out.push({ group: "Pages", label, hash, icon: glyph, hint, keys,
    current: location.hash === hash, run: () => go(hash) });
  page("Planner", "#~planner", "calendar", "A week of posts", "plan week");
  page("Story Bank", "#~bank", "book", "The interviewer", "interview stories");
  page("Voice profile", "#~voice", "feather", "How you write", "voice style");
  for (const t of tools || []) page(`Tools: ${t.title}`, `#~tools-${t.kind}`, t.icon || "tool", "", `tool ${t.kind}`);
  page("Guide", "#~guide", "help", "How the studio works", "help");
  page("Settings", "#~settings", "settings");
  for (const [id, name] of SETTINGS) page(`Settings: ${name}`, `#~settings-${id}`, id === "profile" ? "user" : "settings", "",
    id === "profile" ? "name headline photo avatar" : "");
  page("Trash", "#~trash", "trash", "Posts you moved there", "deleted bin");

  const action = (label, glyph, run, hint = "", keys = "") => out.push({ group: "Actions", label, icon: glyph, run, hint, keys });
  const press = (el, label, glyph, hint = "", keys = "") => {
    if (usable(el)) action(label, glyph, () => el.click(), hint, keys);
  };
  press($("newPost"), "New post", "plus", "Alt+N", "add create draft");
  const top = $("topActions");
  press(top.querySelector('[data-act="approve"]'), "Approve this text", "check", "", "lock ready");
  press(top.querySelector('[data-act="schedule"]'), "Schedule…", "clock", "", "publish publora time");
  press(top.querySelector('[data-act="back"]'), "Back to draft", "arrow-left", "", "unapprove unlock edit");
  if (state.page === "post") {
    const stage = $("postPage");
    press(stage.querySelector('[data-act="edit"]'), "Edit text", "pen", "", "write type");
    press(stage.querySelector('[data-act="audit"]'), "Audit", "check-circle", "", "check review");
    const revise = stage.querySelector('[data-act="revise"]');
    if (usable(revise)) {
      for (const item of stage.querySelectorAll("[data-how]")) {
        const words = item.querySelector("b").textContent;
        action(`Revise: ${words}`, "sparkle", () => item.click(), item.querySelector("small").textContent, "revise rewrite");
      }
    }
  }
  if (state.page === "tools") {
    press([...document.querySelectorAll('#toolsPage [data-act="tool-post"]')].find(usable), "Start a post from this", "file", "",
      "new draft result tool");
  }
  if (shown($("askText"))) action("Ask Claude", "chat", focusAsk, "Ctrl+/", "chat question");
  if (shown($("showAssist"))) action("Show Ask Claude", "panel", () => $("showAssist").click(), "", "panel chat");
  else if (shown($("hideAssist"))) action("Hide Ask Claude", "panel", () => $("hideAssist").click(), "", "panel chat");
  const dark = document.documentElement.dataset.theme === "dark";
  press($("themeBtn"), dark ? "Switch to light" : "Switch to dark", dark ? "sun" : "moon", "", "theme appearance light dark");
  action("Keyboard shortcuts", "keyboard", showShortcuts, "?", "keys help");
  return out;
}

// Every word must appear somewhere; a label that starts with what was typed comes first.
function score(item, words, query) {
  const label = item.label.toLowerCase();
  const hay = `${label} ${item.hint || ""} ${item.keys || ""} ${item.group}`.toLowerCase();
  if (!words.every((w) => hay.includes(w))) return -1;
  if (label.startsWith(query)) return 0;
  if (words.every((w) => label.includes(w))) return label.split(/\s+/).some((x) => x.startsWith(words[0])) ? 1 : 2;
  return 3;
}

// ---------- the palette ----------

// Read from the dialog itself: its close event may not have come yet when the next Ctrl+K does.
const paletteOpen = () => !!openNow && $("dialog").open && $("dialog").contains(openNow.input);

export function openPalette() {
  if (paletteOpen()) {
    openNow.input.focus();
    openNow.input.select();
    return;
  }
  let all = items();
  let list = [];
  let active = 0;
  const input = h("input", { class: "palette-input", type: "text", role: "combobox", "aria-expanded": "true", "aria-controls": "paletteList",
    "aria-autocomplete": "list", "aria-label": "Search posts, pages and actions", placeholder: "Search posts, pages and actions…",
    autocomplete: "off", spellcheck: "false" });
  const box = h("div", { class: "palette-list", id: "paletteList", role: "listbox", "aria-label": "Results" });
  const count = h("div", { class: "sr-only", role: "status" });
  const foot = h("div", { class: "palette-foot", "aria-hidden": "true" },
    h("span", null, h("kbd", null, "↑"), h("kbd", null, "↓"), " to move"), h("span", null, h("kbd", null, "Enter"), " to open"),
    h("span", null, h("kbd", null, "Esc"), " to close"));
  showDialog(h("h2", { class: "sr-only" }, "Search and jump"),
    h("div", { class: "palette-box" }, h("div", { class: "palette-search" }, icon("search", 18), input), box, count, foot));
  const dialog = $("dialog");
  dialog.classList.add("palette");
  openNow = { input };
  const closed = () => {
    if (dialog.open) return;     // the close of what was open before, arriving late
    dialog.removeEventListener("close", closed);
    if (openNow && openNow.input === input) openNow = null;
    dialog.classList.remove("palette");
  };
  dialog.addEventListener("close", closed);

  let countTimer = 0;
  function draw() {
    const query = input.value.trim().toLowerCase();
    const words = query.split(/\s+/).filter(Boolean);
    let found = all.map((it, i) => ({ it, s: 0, i }));
    if (words.length) {
      found = found.map((x) => ({ ...x, s: score(x.it, words, query) })).filter((x) => x.s >= 0);
      found.sort((a, b) => a.s - b.s || GROUPS.indexOf(a.it.group) - GROUPS.indexOf(b.it.group) || a.i - b.i);
    }
    const order = words.length ? [...new Set(found.map((x) => x.it.group))] : GROUPS;
    list = [];
    const blocks = [];
    for (const group of order) {
      const its = found.filter((x) => x.it.group === group).map((x) => x.it);
      if (!its.length) continue;
      const gid = `palette-g-${group.toLowerCase()}`;
      blocks.push(h("div", { class: "palette-group", role: "group", "aria-labelledby": gid },
        h("div", { class: "palette-group-label", id: gid, role: "presentation" }, group),
        its.map((it) => {
          const n = list.length;
          list.push(it);
          return h("div", { class: "palette-item", role: "option", id: `palette-opt-${n}`, "aria-selected": "false", "data-n": n,
            onclick: () => choose(n), onmousemove: () => active !== n && setActive(n, false) },
          h("span", { class: "palette-icon" }, icon(it.icon, 16)),
          h("span", { class: "palette-label" }, it.label, it.current ? h("span", { class: "palette-tag" }, "open") : null),
          it.hint ? h("span", { class: "palette-hint" }, it.hint) : null);
        })));
    }
    if (!list.length) blocks.push(h("div", { class: "palette-empty" }, `Nothing matches “${input.value.trim()}”.`));
    box.replaceChildren(...blocks);
    setActive(0, true);
    clearTimeout(countTimer);
    countTimer = setTimeout(() => {
      count.textContent = list.length ? `${list.length} result${list.length === 1 ? "" : "s"}` : "No results";
    }, 350);
  }
  function setActive(n, scroll) {
    const before = box.querySelector('[aria-selected="true"]');
    if (before) before.setAttribute("aria-selected", "false");
    active = Math.max(0, Math.min(list.length - 1, n));
    const el = box.querySelector(`[data-n="${active}"]`);
    if (!el) return void input.removeAttribute("aria-activedescendant");
    el.setAttribute("aria-selected", "true");
    input.setAttribute("aria-activedescendant", el.id);
    if (scroll) el.scrollIntoView({ block: "nearest" });
  }
  function choose(n) {
    const it = list[n];
    if (!it) return;
    dialog.close();
    // after the dialog has given the focus back, so what runs can move it on
    setTimeout(() => {
      try {
        it.run();
      } catch (error) {
        reportError(error);
      }
    }, 0);
  }
  input.addEventListener("input", draw);
  input.addEventListener("keydown", (event) => {
    if (event.isComposing) return;
    const to = { ArrowDown: active + 1 >= list.length ? 0 : active + 1, ArrowUp: active - 1 < 0 ? list.length - 1 : active - 1,
      PageDown: active + 8, PageUp: active - 8 }[event.key];
    if (to !== undefined) {
      event.preventDefault();
      setActive(to, true);
    } else if (event.key === "Enter") {
      event.preventDefault();
      choose(active);
    } else if (event.key === "Tab") {
      event.preventDefault();      // the list is reached with the arrows
    }
  });
  draw();
  if (!tools) {
    api("/api/tools").then((reply) => {
      if (reply.error) return;
      tools = reply.tools.map((t) => ({ kind: t.kind, title: t.title, icon: t.icon }));
      if (!paletteOpen() || openNow.input !== input) return;
      all = items();
      draw();
    });
  }
}

// ---------- the keys ----------

// The keys' list, as the Guide has it: one list, written once (guide.SHORTCUTS).
export async function showShortcuts() {
  const reply = await api("/api/guide");
  if (reply.error) return announce(reply.error, { urgent: true });
  const keysOf = (keys) => keys.split(" / ").map((one, i) => [i ? " or " : null,
    ...one.split(" + ").map((part, j) => [j ? " + " : null, h("kbd", null, part)])]);
  showDialog(h("h2", null, "Keyboard shortcuts"),
    h("div", { class: "table-wrap" }, h("table", { class: "table keys" },
      h("thead", null, h("tr", null, h("th", { scope: "col" }, "Keys"), h("th", { scope: "col" }, "What it does"))),
      h("tbody", null, (reply.shortcuts || []).map(([keys, what]) => h("tr", null, h("td", null, keysOf(keys)), h("td", null, what)))))),
    h("div", { class: "dialog-foot" }, closeButton("Close")));
}

// Ctrl+/: the Ask box, the panel shown first when it was hidden.
function focusAsk() {
  if (shown($("askText"))) return void $("askText").focus();
  if (shown($("showAssist"))) return void $("showAssist").click();
  announce("Ask Claude is beside a post, the Story Bank and the voice profile. Open one of them first.");
}

function stepPost(dir) {
  const posts = state.posts;
  if (!posts.length) return;
  const at = state.page === "post" ? posts.findIndex((p) => p.id === state.postId) : -1;
  const next = at < 0 ? posts[dir > 0 ? 0 : posts.length - 1] : posts[(at + dir + posts.length) % posts.length];
  go(`#post-${next.id}`);
}

function onKey(event) {
  if (event.defaultPrevented || event.isComposing) return;
  const mod = event.ctrlKey || event.metaKey;
  const key = event.key.length === 1 ? event.key.toLowerCase() : event.key;
  if (state.setup) return;            // the setup screen has none of these
  if (mod && !event.altKey && !event.shiftKey && (key === "k" || event.code === "KeyK")) {
    event.preventDefault();
    if (!$("dialog").open || paletteOpen()) openPalette();    // never over a dialog that is asking something
    return;
  }
  if ($("dialog").open) return;
  if (mod && !event.altKey && (key === "/" || event.code === "Slash")) {
    event.preventDefault();
    return void focusAsk();
  }
  if (event.altKey && !mod && !event.shiftKey && (key === "n" || event.code === "KeyN")) {
    event.preventDefault();
    return void $("newPost").click();
  }
  if (event.altKey && !mod && !event.shiftKey && (event.key === "ArrowUp" || event.key === "ArrowDown") && event.target.tagName !== "SELECT") {
    event.preventDefault();
    return void stepPost(event.key === "ArrowUp" ? -1 : 1);
  }
  if (!mod && !event.altKey && event.key === "?" && !typing(event.target)) {
    event.preventDefault();
    showShortcuts();
  }
}

// ---------- the start ----------

function skipLinks() {
  const toPost = h("a", { class: "skip-link", href: "#", id: "skipPost" }, "Skip to the post");
  const toAsk = h("a", { class: "skip-link", href: "#", id: "skipAsk", "aria-keyshortcuts": "Control+/" }, "Skip to Ask Claude");
  toPost.addEventListener("click", (event) => {
    event.preventDefault();
    focusFirst(state.page === "post" ? "#postPage .li-card" : null, "main > .page:not([hidden])", $("title"));
  });
  toAsk.addEventListener("click", (event) => {
    event.preventDefault();
    focusAsk();
  });
  document.body.prepend(toPost, toAsk);
  const sync = () => {
    const words = state.page === "post" ? "Skip to the post" : "Skip to the page";
    if (toPost.textContent !== words) toPost.textContent = words;
    toAsk.hidden = !shown($("askText")) && !shown($("showAssist"));
  };
  onPoll(sync);
  window.addEventListener("hashchange", () => setTimeout(sync, 0));
}

function start() {
  const search = h("button", { id: "paletteBtn", class: "btn ghost small square", type: "button", "aria-label": "Search and jump",
    title: "Search and jump (Ctrl+K)", "aria-keyshortcuts": "Control+K", "aria-haspopup": "dialog" }, icon("search", 15));
  search.addEventListener("click", openPalette);
  $("themeBtn").before(search);
  $("newPost").setAttribute("aria-keyshortcuts", "Alt+N");
  $("askText").setAttribute("aria-keyshortcuts", "Control+/");
  skipLinks();
  document.addEventListener("keydown", onKey);
}

if (!window.studioPalette) {
  window.studioPalette = { open: openPalette, shortcuts: showShortcuts };
  start();
}
