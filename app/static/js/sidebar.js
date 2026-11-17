// The sidebar: + New post, the search, the posts (each by its first line, with where it stands; the ones done with
// folded away under Earlier), the studio's pages and the Trash, and light or dark. Nothing in it counts anything: the
// figures are on the pages.
import { $, state, h, icon, post, put, go, drawIfChanged, focusFirst, announce, whileBusy, recall, keep, plural } from "./core.js";
import { wordsOf, findPost, lineOf, marked, ensure, shownAlready } from "./search.js";

const PAGE_OF = { goSchedule: ["schedule"], goHot: ["hot"], goBank: ["bank", "voice"], goTools: ["tools"], goGuide: ["guide"],
  goSettings: ["settings", "setup"], goTrash: ["trash"] };
const EARLIER = new Set(["published", "cancelled"]);   // done with: on LinkedIn, or cancelled on Publora

// Where a post stands, in the sidebar's line and the top bar's chip: Claude at work on it first, and for how long once
// that is a minute or more. The chip is drawn from the full post too, whose rank is the rank card's (its number in it).
export function statusOf(p) {
  const rank = p.rank && typeof p.rank === "object" ? p.rank.rank : p.rank;
  if (p.busy) {
    const job = state.jobs.find((j) => j.post_id === p.id && j.status === "running");
    const minutes = job ? Math.floor((job.seconds || 0) / 60) : 0;
    return { text: minutes >= 1 ? `Claude is working · ${minutes} min` : "Claude is working", kind: "busy" };
  }
  if (p.status === "scheduled" && p.when) return { text: `Scheduled · ${p.when.replace(/ [A-Z]{2,5}$/, "")}`, kind: "ok" };
  if (p.queued && p.when) return { text: `Queued · ${p.when.replace(/ [A-Z]{2,5}$/, "")}`, kind: p.kind };
  return { text: rank && p.status === "draft" ? `${p.label} · ${rank}/10` : p.label, kind: p.kind };   // the owner asked: 3 Nov 2026
}

// Earlier, after the posts as they are today: closed at first, then as the owner left it (kept in this window's
// storage). The open post always shows: an earlier one opens the fold while it is the open post, and what is kept
// stays as it was; closed by hand meanwhile, the fold keeps that one post under it until another post opens.
let shut = 0;   // the earlier post the fold was closed on by hand

function fold(open, here) {
  keep("earlier", open ? "0" : "1");
  shut = open ? here : 0;
  renderList();
}

// A post's button; while searching, the words marked in it and under its name the line they were found on.
const postButton = (row, words = []) => h("button",
  { class: "nav-item", type: "button", "aria-current": row.current ? "page" : null, title: row.found ? `${row.first}\n${row.found}` : row.first,
    "data-post": row.id, onclick: () => go(`#post-${row.id}`) },
  icon("file", 17),
  h("span", { class: "nav-text" }, h("span", { class: "name" }, marked(row.first, words)),
    h("span", { class: "sub" }, marked(row.found || row.text, words))),
  h("i", { class: `dot ${row.kind}`, "aria-hidden": "true" }));

// ---------- the search ----------
// Under New post: as the owner types, the list is the posts with every word somewhere (search.js), today's and earlier
// ones together in the list's order, so the open post stays where it was. Esc empties it; ↓ goes to the first post found,
// Enter opens it; / comes back to it from anywhere (palette.js). It stays while posts are opened from it.
let query = "";
let told = 0;

function found(words) {
  const rows = [];
  for (const p of state.posts) {
    const where = statusOf(p);
    const hit = findPost(p, words, [["status", where.text]]);
    if (hit) rows.push({ id: p.id, first: p.first, ...where, found: shownAlready(hit) ? "" : lineOf(hit, words, 90, 8),
      current: state.page === "post" && p.id === state.postId });
  }
  return rows;
}

function drawFound(words) {
  const rows = found(words);
  const said = ` · ${rows.length ? plural(rows.length, "match", "matches") : "none match"}`;
  if ($("postsCount").textContent !== said) $("postsCount").textContent = said;
  const list = $("list");
  drawIfChanged(list, JSON.stringify(["found", words, rows]), () => {
    const at = list.contains(document.activeElement) ? document.activeElement.dataset.post : "";
    if (!rows.length) return void list.replaceChildren(h("p", { class: "soft side-none" }, `No posts match “${query.trim()}”.`));
    put(list, rows.map((row) => postButton(row, words)));
    if (at) focusFirst(list.querySelector(`[data-post="${at}"]`));
  });
  clearTimeout(told);    // said once the owner stops typing, not at each key
  told = setTimeout(() => announce(rows.length ? `${plural(rows.length, "post matches", "posts match")}` : "No posts match"), 700);
}

function searchBox() {
  const input = h("input", { id: "postSearch", class: "input side-search-input", type: "search", placeholder: "Search posts",
    "aria-label": "Search your posts", "aria-controls": "list", "aria-keyshortcuts": "/", autocomplete: "off", spellcheck: "false",
    title: "Every word somewhere in a post: its text, first comment, carousel or card, the news it came from, its title, where it stands (/)" });
  const look = () => {
    query = input.value;
    renderList();
    if (wordsOf(query).length) ensure().then((fresh) => fresh && renderList());
  };
  input.addEventListener("input", look);
  input.addEventListener("keydown", (event) => {
    const first = $("list").querySelector(".nav-item");
    if (event.key === "Escape" && input.value) {
      event.preventDefault();
      input.value = "";
      look();
    } else if (event.key === "ArrowDown" && first) {
      event.preventDefault();
      first.focus();
    } else if (event.key === "Enter" && first && wordsOf(query).length) {
      event.preventDefault();
      first.click();
    }
  });
  return h("div", { class: "side-search", role: "search" }, icon("search", 15), input,
    h("kbd", { class: "side-search-key", "aria-hidden": "true" }, "/"));
}

// The posts, drawn again only when one of them changes, so a button the owner is on keeps the focus; when they are
// drawn again, the focus stays on the same post's button (or on Earlier, when the post went under it). No posts:
// "None yet", in words. The order is the studio's, as Ctrl+K and Alt+↑/↓ have it: today's, then the earlier ones.
// While searching: the posts found instead (drawFound), their words read again once the studio changed.
export function renderList() {
  const words = wordsOf(query);
  if (words.length) {
    drawFound(words);
    ensure().then((fresh) => fresh && renderList());
    return void pagesHere();
  }
  const now = [];
  const earlier = [];
  for (const p of state.posts) {
    (EARLIER.has(p.status) ? earlier : now).push({ id: p.id, first: p.first, ...statusOf(p), current: state.page === "post" && p.id === state.postId });
  }
  const onEarlier = (earlier.find((row) => row.current) || { id: 0 }).id;
  if (shut !== onEarlier) shut = 0;
  const open = earlier.length > 0 && (recall("earlier") === "1" || (onEarlier > 0 && shut !== onEarlier));
  const under = open ? earlier : earlier.filter((row) => row.current);
  // Beside Posts: how many drafts, and how many approved, queued or scheduled, when there are any (the list's name says
  // it too)
  const many = (test) => state.posts.filter(test).length;
  const counts = [plural(many((p) => p.status === "draft"), "draft", "drafts"),
    ...[[(p) => p.status === "approved" && !p.queued, "approved"], [(p) => p.queued, "queued"], [(p) => p.status === "scheduled", "scheduled"]]
      .filter(([test]) => many(test)).map(([test, word]) => `${many(test)} ${word}`)];
  const said = ` · ${counts.join(", ")}`;
  if ($("postsCount").textContent !== said) $("postsCount").textContent = said;
  const list = $("list");
  drawIfChanged(list, JSON.stringify([now, earlier.length > 0, open, under]), () => {
    const at = list.contains(document.activeElement) ? document.activeElement : null;
    const on = at ? at.dataset.post || at.id : "";
    if (!now.length && !earlier.length) return void list.replaceChildren(h("span", { class: "soft", style: "padding:6px 10px" }, "None yet"));
    const toggle = earlier.length ? h("button", { class: "side-fold", id: "earlierFold", type: "button", "aria-expanded": String(open),
      "aria-controls": "earlierList", title: "Published and cancelled posts", onclick: () => fold(open, onEarlier) },
    icon("chevron-down", 15), h("span", null, "Earlier")) : null;
    const group = earlier.length ? h("div", { class: "nav-group", id: "earlierList", role: "group", "aria-labelledby": "earlierFold",
      hidden: !under.length }, under.map((row) => postButton(row))) : null;
    put(list, now.map((row) => postButton(row)), toggle, group);
    if (on) focusFirst(on === "earlierFold" ? null : list.querySelector(`[data-post="${on}"]`), $("earlierFold"));
  });
  pagesHere();
}

// The page that is open, marked among the studio's pages.
function pagesHere() {
  for (const [id, pages] of Object.entries(PAGE_OF)) {
    const here = pages.includes(state.page);
    if ($(id).hasAttribute("aria-current") !== here) {
      if (here) $(id).setAttribute("aria-current", "page");
      else $(id).removeAttribute("aria-current");
    }
  }
}

// The theme button names where it goes ("Switch to dark theme"); pressed, it says where it went.
export function themeChanged() {
  const dark = document.documentElement.dataset.theme === "dark";
  const words = `Switch to ${dark ? "light" : "dark"} theme`;
  $("themeBtn").replaceChildren(icon(dark ? "sun" : "moon", 15));
  $("themeBtn").setAttribute("aria-label", words);
  $("themeBtn").title = words;
}

export function setTheme(choice) {
  window.studioTheme.set(choice);
  themeChanged();
}

// A post made just now (New post, New draft from this): listed at once, opened, and route() puts the focus in the Ask
// box once it shows (takeMade).
let made = 0;
export function openNew(p) {
  state.posts = [p, ...state.posts.filter((x) => x.id !== p.id)];
  made = p.id;
  go(`#post-${p.id}`);
}

export function takeMade(id) {
  if (made !== id) return false;
  made = 0;
  return true;
}

// + New post: a blank draft, opened at once; Claude drafts it from the chat beside it when asked.
async function newPost(button) {
  const reply = await whileBusy(button, () => post("/api/posts/new", {}));
  if (reply.error) return announce(reply.error, { urgent: true });
  openNew(reply.post);
}

export function init() {
  $("newPost").after(searchBox());
  $("newPost").prepend(icon("plus", 16));
  $("newPost").addEventListener("click", () => newPost($("newPost")));
  for (const [id, glyph] of [["goSchedule", "calendar"], ["goHot", "flame"], ["goBank", "book"], ["goTools", "tool"], ["goGuide", "help"],
    ["goSettings", "settings"], ["goTrash", "trash"]]) {
    $(id).prepend(icon(glyph, 17));
    $(id).addEventListener("click", () => go(`#~${$(id).dataset.page}`));
  }
  $("sideFoot").prepend(icon("lock", 14));
  $("themeBtn").addEventListener("click", () => {
    const dark = document.documentElement.dataset.theme !== "dark";
    setTheme(dark ? "dark" : "light");
    announce(dark ? "Dark theme" : "Light theme");
  });
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => setTimeout(themeChanged, 0));
  themeChanged();
}
