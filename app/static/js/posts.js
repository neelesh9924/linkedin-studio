// Your posts, a page of their own (the owner's word, 19 Nov 2026: the sidebar showed everything in one list). Each post is
// in one tab by where it stands (TABS, tabOf): Drafts; Approved, waiting for you to queue or schedule it; Scheduled, what
// goes out, soonest first: at Publora in green and queued in blue (the owner's word, 20 Nov 2026), with a post being sent
// and one that did not go out (first, in red: it waits on you); Published, the most recent first, with the ones cancelled
// on Publora after them. A tab's page lists its posts in the studio's order (as /api/state sends them), a row each: its
// rank, its first line and where it stands, with its date once it has one (statusOf, Claude at work on it first). The
// page says how many; the sidebar counts nothing. The search at the
// top looks in every post, whatever the tab (search.js); / comes to it from anywhere (palette.js), Esc empties it, ↓ goes
// to the first post and Enter opens it. A post opened from here has Back to its tab above it, and Alt+↑/↓ step through
// that tab (stepPost). A post that did not go out is named across the top of every page until it is dealt with.
import { $, state, h, icon, put, go, banner, drawIfChanged, focusFirst, announce, plural, currentPost } from "./core.js";
import { wordsOf, findPost, lineOf, marked, ensure, shownAlready } from "./search.js";

// The tabs, one definition for the sidebar, this page, Back, Alt+↑/↓ and Ctrl+K. Every status is in exactly one.
export const TABS = [
  { id: "drafts", name: "Drafts", icon: "pen", tone: "accent", statuses: ["draft"], hint: "Your drafts, best first",
    empty: "No drafts. Press New post, or Draft beside a news item in Hot topics." },
  { id: "approved", name: "Approved", icon: "check", tone: "ready", statuses: ["approved"],
    hint: "Approved posts waiting for you to queue or schedule them",
    empty: "Nothing waiting for you. Approve and queue a finished draft: it takes your next free posting time, under Scheduled." },
  { id: "scheduled", name: "Scheduled", icon: "clock", tone: "ok", statuses: ["scheduling", "scheduled", "failed"], also: ["queued"],
    hint: "What goes out, soonest first: at Publora in green, queued in blue; a post that did not go out comes first",
    empty: "Nothing scheduled or queued. Approve and queue a finished draft: it takes your next free posting time." },
  { id: "published", name: "Published", icon: "plane", tone: "plain", statuses: ["published", "cancelled"],
    hint: "On LinkedIn, the most recent first, then the posts cancelled on Publora",
    empty: "Nothing published yet. A post shows here once Publora says it went out." },
];
const TAB_OF = Object.fromEntries(TABS.flatMap((t) => t.statuses.map((s) => [s, t.id])));
// A queued post is approved, but it goes out by itself at its time: it is under Scheduled, with the posts at Publora.
export const tabOf = (p) => (p && p.status === "approved" && p.queued ? "scheduled" : p && TAB_OF[p.status]) || "drafts";
export const tabNamed = (id) => TABS.find((t) => t.id === id) || TABS[0];

// Where a post stands, in its row and the top bar's chip: Claude at work on it first, and for how long once that is a
// minute or more; the date it goes out, went out or was due, once it has one. The chip is drawn from the full post too,
// whose rank is the rank card's (its number in it).
export function statusOf(p) {
  const rank = p.rank && typeof p.rank === "object" ? p.rank.rank : p.rank;
  if (p.busy) {
    const job = state.jobs.find((j) => j.post_id === p.id && j.status === "running");
    const minutes = job ? Math.floor((job.seconds || 0) / 60) : 0;
    return { text: minutes >= 1 ? `Claude is working · ${minutes} min` : "Claude is working", kind: "busy" };
  }
  const when = (p.when || "").replace(/ [A-Z]{2,5}$/, "");
  if (p.status === "scheduled" && when) return { text: `Scheduled · ${when}`, kind: "ok" };
  if (p.queued && when) return { text: `Queued · ${when}`, kind: p.kind };
  if (p.status === "published" && when) return { text: `Published · ${when}`, kind: p.kind };
  if (p.status === "cancelled" && when) return { text: `Cancelled · was due ${when}`, kind: p.kind };
  return { text: rank && p.status === "draft" ? `${p.label} · ${rank}/10` : p.label, kind: p.kind };   // the owner asked: 3 Nov 2026
}

// ---------- the page ----------

let box = null;
let head = null;          // the tab's panel: its name and how many, drawn again when that changes
let list = null;          // the rows, drawn again when one changes (the search box is never drawn again)
let query = "";
let told = 0;
let wantSearch = false;   // / pressed on another page: the box takes the focus once this one shows
let aim = null;           // the post whose row takes the focus when the list next draws (0: the list's start)

export function render(container, { sub, from } = {}) {
  box = container;
  state.tab = tabNamed(sub).id;
  if (!$("postSearch") || !box.contains($("postSearch"))) frame();
  draw();
  if (wantSearch) {
    wantSearch = false;
    $("postSearch").focus();
    $("postSearch").select();
  } else if (aim !== null || (from && lostFocus())) {   // Back, Move to Trash, or the browser's back from a post
    const id = aim !== null ? aim : from;
    aim = null;
    focusFirst(id ? list.querySelector(`[data-post="${id}"]`) : null, list.querySelector(".post-row"), $("postSearch"));
  }
  if (wordsOf(query).length) ensure().then((fresh) => fresh && draw());
}

export const refresh = () => draw();
export const tick = () => draw();

const lostFocus = () => !document.activeElement || document.activeElement === document.body || !document.activeElement.getClientRects().length;

// A sidebar tab: that tab's posts, the search emptied.
export function openTab(id) {
  query = "";
  if ($("postSearch")) $("postSearch").value = "";
  go(`#~posts-${tabNamed(id).id}`);
}

// / from anywhere: this page's search, the tab shown last (the open post's, when one is open).
export function focusSearch() {
  if (state.page === "posts" && $("postSearch")) {
    $("postSearch").focus();
    $("postSearch").select();
    return;
  }
  wantSearch = true;
  go(`#~posts-${state.page === "post" ? tabOf(currentPost()) : state.tab || "drafts"}`);
}

// The row that takes the focus when the list next draws (Move to Trash: the post after the one that went).
export function takeFocus(id) {
  aim = id || 0;
}

function frame() {
  head = h("div");
  list = h("div", { id: "postList" });
  const input = h("input", { id: "postSearch", class: "input search-input", type: "search", placeholder: "Search all your posts",
    "aria-label": "Search all your posts", "aria-controls": "postList", "aria-describedby": "postFound", "aria-keyshortcuts": "/",
    autocomplete: "off", spellcheck: "false",
    title: "Every word somewhere in a post, in every tab: its text, first comment, carousel or card, the news it came from, its title, where it stands (/)" });
  const look = () => {
    query = input.value;
    draw();
    clearTimeout(told);     // said once the owner stops typing, not at each key
    if (wordsOf(query).length) {
      ensure().then((fresh) => fresh && draw());
      told = setTimeout(() => {
        const n = list.querySelectorAll(".post-row").length;
        announce(n ? plural(n, "post matches", "posts match") : "No posts match");
      }, 700);
    }
  };
  input.addEventListener("input", look);
  input.addEventListener("keydown", (event) => {
    const first = list.querySelector(".post-row");
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
  // ↑ and ↓ move between the rows; ↑ on the first goes back to the search
  list.addEventListener("keydown", (event) => {
    if (!["ArrowUp", "ArrowDown"].includes(event.key) || !event.target.classList.contains("post-row") || event.altKey) return;
    const rows = [...list.querySelectorAll(".post-row")];
    const at = rows.indexOf(event.target);
    event.preventDefault();
    focusFirst(event.key === "ArrowDown" ? rows[at + 1] : at > 0 ? rows[at - 1] : input);
  });
  put(box, h("div", { class: "page-width" }, head,
    h("div", { class: "hot-search post-search", role: "search" }, icon("search", 16), input,
      h("kbd", { class: "search-key", "aria-hidden": "true" }, "/"), h("span", { id: "postFound", class: "soft" })),
    list));
}

// How many, in words: the tab's posts by where they stand, in the list's order (none: what the tab holds).
function saidOf(tab, mine) {
  const n = (test) => mine.filter(test).length;
  if (!mine.length) return `${tab.hint}.`;
  if (tab.id === "drafts") return `${plural(mine.length, "draft", "drafts")}, best first: any not ranked yet on top, then the highest rank.`;
  if (tab.id === "approved") {
    return `${plural(mine.length, "approved post", "approved posts")}, waiting for you to queue or schedule ${mine.length === 1 ? "it" : "them"}.`;
  }
  if (tab.id === "scheduled") {
    const failed = n((p) => p.status === "failed");
    const sending = n((p) => p.status === "scheduling");
    const going = [[n((p) => p.status === "scheduled"), "scheduled at Publora, in green"], [n((p) => p.queued), "queued, in blue"]]
      .filter(([count]) => count).map(([count, words]) => `${count} ${words}`);
    return [failed ? `${failed} did not go out: ${failed === 1 ? "it comes" : "they come"} first, in red.` : "",
      going.length ? `${going.join(", and ")}: soonest first.` : "",
      sending ? `${sending} being sent to Publora.` : ""].filter(Boolean).join(" ");
  }
  const cancelled = n((p) => p.status === "cancelled");
  const out = mine.length - cancelled;
  return `${[out ? `${out} published on LinkedIn, the most recent first` : "", cancelled ? `${cancelled} cancelled on Publora` : ""].filter(Boolean).join(", then ")}.`;
}

const rowOf = (p) => ({ id: p.id, first: p.first, status: p.status, rank: p.rank, verdict: p.verdict || "", ...statusOf(p) });

// While searching: every post with all the words somewhere, in the studio's order, each with the line they were found
// on when its first line, title or status does not show them already.
function found(words) {
  const rows = [];
  for (const p of state.posts) {
    const row = rowOf(p);
    const hit = findPost(p, words, [["status", row.text]]);
    if (hit) rows.push({ ...row, found: shownAlready(hit) ? "" : lineOf(hit, words, 140, 24) });
  }
  return rows;
}

function draw() {
  if (!box || !list || state.page !== "posts") return;
  const tab = tabNamed(state.tab);
  const words = wordsOf(query);
  const mine = state.posts.filter((p) => tabOf(p) === tab.id);
  const rows = words.length ? found(words) : mine.map(rowOf);
  const said = saidOf(tab, mine);
  drawIfChanged(head, JSON.stringify([tab.id, said]), () => put(head,
    h("section", { class: "panel posts-head", "aria-labelledby": "posts-title" },
      h("header", { class: "panel-head" }, h("span", { class: `panel-mark ${tab.tone}` }, icon(tab.icon, 17)),
        h("div", null, h("h2", { id: "posts-title" }, tab.name), h("p", { id: "posts-said" }, said))))));
  const counted = words.length && rows.length ? `${rows.length} of ${plural(state.posts.length, "post", "posts")} match, in every tab` : "";
  if ($("postFound").textContent !== counted) $("postFound").textContent = counted;
  drawIfChanged(list, JSON.stringify([tab.id, words, rows, !state.posts.length]), () => {
    const at = list.contains(document.activeElement) ? document.activeElement.dataset.post : "";
    put(list, rows.length
      ? h("ol", { class: "post-list", "aria-label": words.length ? "Posts found, in every tab" : tab.name }, rows.map((r) => row(r, words)))
      : empty(tab, words));
    if (at) focusFirst(list.querySelector(`[data-post="${at}"]`), list.querySelector(".post-row"), $("postSearch"));
  });
}

// A post's row: its rank, its first line, where it stands and, while searching, the line its words are on, marked.
function row(r, words) {
  const ranked = r.rank && !r.text.includes("/10") ? h("span", { class: "sr-only" }, `, ranked ${r.rank} of 10`) : null;
  return h("li", null, h("button", { class: `post-row${r.status === "failed" ? " failed" : ""}`, type: "button", "data-post": r.id,
    title: r.found ? `${r.first}\n${r.found}` : r.first, onclick: () => go(`#post-${r.id}`) },
  r.rank ? h("span", { class: `rank ${r.verdict}`.trim(), "aria-hidden": "true", title: `Ranked ${r.rank} of 10` }, String(r.rank))
    : h("span", { class: "rank none", "aria-hidden": "true", title: "Not ranked yet" }, "–"),
  h("span", { class: "post-first" }, marked(r.first, words), ranked),
  h("span", { class: `post-where ${r.kind || ""}`.trim() }, h("i", { class: `dot ${r.kind}`, "aria-hidden": "true" }), h("span", null, marked(r.text, words))),
  r.found ? h("span", { class: "post-found" }, marked(r.found, words)) : null));
}

// Nothing to list, in words: none match the search; no posts at all (where to start); or none in this tab.
function empty(tab, words) {
  if (words.length) return h("p", { class: "soft posts-none" }, `No posts match “${query.trim()}”.`);
  if (!state.posts.length) {
    return h("div", { class: "empty" },
      h("div", { class: "empty-mark" }, icon("file", 26)),
      h("h2", null, "No posts yet"),
      h("p", null, "Start a post and tell Claude what it is about, or draft one from the news in Hot topics. A post opens as LinkedIn will show it."),
      h("div", { class: "form-foot" },
        h("button", { class: "btn primary", type: "button", onclick: () => $("newPost").click() }, icon("plus", 15), h("span", null, "New post")),
        h("button", { class: "btn", type: "button", onclick: () => go("#~hot") }, icon("flame", 15), h("span", null, "Hot topics"))));
  }
  return h("div", { class: "posts-empty" }, h("span", { class: `panel-mark ${tab.tone}` }, icon(tab.icon, 18)), h("p", null, tab.empty));
}

// ---------- the open post's tab ----------

// Alt+↑ / Alt+↓: the previous or next post in the open post's tab, round from the last to the first; on another page,
// the first or last post of the tab shown last.
export function stepPost(dir) {
  const open = state.page === "post" ? currentPost() : null;
  const tab = tabNamed(open ? tabOf(open) : state.tab);
  const mine = state.posts.filter((p) => tabOf(p) === tab.id);
  if (!mine.length) return void announce(`No posts under ${tab.name}.`);
  const at = open ? mine.findIndex((p) => p.id === open.id) : -1;
  const next = at < 0 ? mine[dir > 0 ? 0 : mine.length - 1] : mine[(at + dir + mine.length) % mine.length];
  if (open && next.id === open.id) return void announce(`It is the only post under ${tab.name}.`);
  go(`#post-${next.id}`);
}

// ---------- a post that did not go out ----------

// Named across the top of every page, said once as it goes up, with the way to it; not on its own page, whose notice says
// what happened. Drawn again only when what it names changes, so its button keeps the focus through the polls.
let failedSaid = "";
export function warnFailed() {
  const failed = state.posts.filter((p) => p.status === "failed" && !(state.page === "post" && p.id === state.postId));
  const key = JSON.stringify(failed.map((p) => [p.id, p.first]));
  if (key === failedSaid) return;
  failedSaid = key;
  if (!failed.length) return void banner("failed", null);
  const one = failed.length === 1 ? failed[0] : null;
  const cut = one && one.first.length > 70 ? `${one.first.slice(0, 68).trim()}…` : one && one.first;
  banner("failed", [icon("alert", 17),
    h("div", null, h("strong", null, one ? "A post did not go out." : `${failed.length} posts did not go out.`),
      one ? `“${cut}” Open it to see why and what to do.` : "They come first under Scheduled, each with what to do."),
    h("button", { class: "btn small", type: "button", onclick: () => go(one ? `#post-${one.id}` : "#~posts-scheduled") },
      one ? "Open it" : "Open Scheduled")], "bad");
}
