// The sidebar, navigation only (the owner's word, 19 Nov 2026: it showed every post in one list): + New post, then the
// tabs in groups, each with a tinted mark of its own as in Job Studio, so they never blend in. Posts: the tabs of
// posts.js (TABS), each one's posts a page in the centre; Studio: the pages. Settings, the Trash and light or dark stay at
// the foot. Nothing in it counts anything (the owner's rule): the figures are on the pages. The tab of the list shown, or
// of the open post, is marked current, as is the page that is open; the open post's Back to its tab is set here too.
import { $, state, h, icon, post, put, go, announce, whileBusy, currentPost } from "./core.js";
import { TABS, tabOf, tabNamed, openTab } from "./posts.js";

// The studio's pages: [button, icon, tone, the pages it is current on]
const PAGES = [["goSchedule", "calendar", "ok", ["schedule"]], ["goHot", "flame", "warn", ["hot"]],
  ["goBank", "book", "ready", ["bank", "voice"]], ["goTools", "tool", "accent", ["tools"]], ["goGuide", "help", "quiet", ["guide"]]];
const FOOT = [["goSettings", "settings", ["settings", "setup"]], ["goTrash", "trash", ["trash"]]];

const mark = (glyph, tone) => h("span", { class: `nav-mark ${tone}`, "aria-hidden": "true" }, icon(glyph, 15));

function current(el, value) {
  if (el.getAttribute("aria-current") === value) return;
  if (value) el.setAttribute("aria-current", value);
  else el.removeAttribute("aria-current");
}

// What is current: the list's tab ("page"), or the open post's tab ("true": the post is the page, inside it); the page
// that is open. The open post's way back names its tab, which moves with it (Approve takes a draft to Approved).
export function renderSide() {
  const open = state.page === "post" ? currentPost() : null;
  const here = open ? tabOf(open) : state.page === "posts" ? state.tab : "";
  for (const t of TABS) current($(`tab-${t.id}`), t.id !== here ? null : open ? "true" : "page");
  for (const [id, , , pages] of [...PAGES, ...FOOT.map(([id, glyph, pages]) => [id, glyph, "", pages])]) {
    current($(id), pages.includes(state.page) ? "page" : null);
  }
  const back = $("backTo");
  back.hidden = !open;
  if (!open) return;
  const words = `Back to ${tabNamed(here).name}`;
  if (back.getAttribute("aria-label") !== words) {
    back.setAttribute("aria-label", words);
    back.title = `${words} (Alt+↑ and Alt+↓ step through it)`;
    back.lastChild.textContent = tabNamed(here).name;
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
  $("newPost").prepend(icon("plus", 16));
  $("newPost").addEventListener("click", () => newPost($("newPost")));
  put($("postTabs"), TABS.map((t) => h("button", { class: "nav-item", type: "button", id: `tab-${t.id}`, "data-tab": t.id, title: t.hint,
    onclick: () => openTab(t.id) }, mark(t.icon, t.tone), h("span", { class: "nav-text" }, h("span", { class: "name" }, t.name)))));
  for (const [id, glyph, tone] of PAGES) {
    $(id).prepend(mark(glyph, tone));
    $(id).addEventListener("click", () => go(`#~${$(id).dataset.page}`));
  }
  for (const [id, glyph] of FOOT) {
    $(id).prepend(icon(glyph, 17));
    $(id).addEventListener("click", () => go(`#~${$(id).dataset.page}`));
  }
  $("backTo").prepend(icon("arrow-left", 15));
  $("backTo").addEventListener("click", () => go(`#~posts-${tabOf(currentPost())}`));
  $("sideFoot").prepend(icon("lock", 14));
  $("themeBtn").addEventListener("click", () => {
    const dark = document.documentElement.dataset.theme !== "dark";
    setTheme(dark ? "dark" : "light");
    announce(dark ? "Dark theme" : "Light theme");
  });
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => setTimeout(themeChanged, 0));
  themeChanged();
}
