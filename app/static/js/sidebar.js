// The sidebar: + New post, the posts (each by its first line, with where it stands), the studio's pages, and light or
// dark. Nothing in it counts anything: the figures are on the pages.
import { $, state, h, icon, post, go, drawIfChanged, focusFirst, announce, whileBusy } from "./core.js";

const PAGE_OF = { goPlanner: ["planner"], goBank: ["bank", "voice"], goTools: ["tools"], goGuide: ["guide"], goSettings: ["settings", "setup"] };

// Where a post stands, in the sidebar's line and the top bar's chip: Claude at work on it first.
export function statusOf(p) {
  if (p.busy) return { text: "Claude is working", kind: "busy" };
  if (p.status === "scheduled" && p.when) return { text: `Scheduled · ${p.when.replace(/ [A-Z]{2,5}$/, "")}`, kind: "ok" };
  return { text: p.label, kind: p.kind };
}

// The posts, drawn again only when one of them changes, so a button the owner is on keeps the focus; when they are
// drawn again, the focus stays on the same post's button.
export function renderList() {
  const rows = state.posts.map((p) => ({ id: p.id, first: p.first, ...statusOf(p), current: state.page === "post" && p.id === state.postId }));
  const list = $("list");
  drawIfChanged(list, JSON.stringify(rows), () => {
    const on = list.contains(document.activeElement) ? document.activeElement.dataset.post : null;
    list.replaceChildren(...rows.map((row) => h("button",
      { class: "nav-item", type: "button", "aria-current": row.current ? "page" : null, title: row.first, "data-post": row.id,
        onclick: () => go(`#post-${row.id}`) },
      icon("file", 17),
      h("span", { class: "nav-text" }, h("span", { class: "name" }, row.first), h("span", { class: "sub" }, row.text)),
      h("i", { class: `dot ${row.kind}`, "aria-hidden": "true" }))));
    if (on) focusFirst([...list.children].find((button) => button.dataset.post === on));
  });
  for (const [id, pages] of Object.entries(PAGE_OF)) {
    const here = pages.includes(state.page);
    if ($(id).hasAttribute("aria-current") !== here) {
      if (here) $(id).setAttribute("aria-current", "page");
      else $(id).removeAttribute("aria-current");
    }
  }
}

export function themeChanged() {
  $("themeBtn").replaceChildren(icon(document.documentElement.dataset.theme === "dark" ? "sun" : "moon", 15));
}

export function setTheme(choice) {
  window.studioTheme.set(choice);
  themeChanged();
}

// + New post: a blank draft, opened at once; Claude drafts it from the chat beside it when asked.
async function newPost(button) {
  const reply = await whileBusy(button, () => post("/api/posts/new", {}));
  if (reply.error) return announce(reply.error, { urgent: true });
  go(`#post-${reply.id}`);
}

export function init() {
  $("newPost").prepend(icon("plus", 16));
  $("newPost").addEventListener("click", () => newPost($("newPost")));
  for (const [id, glyph] of [["goPlanner", "calendar"], ["goBank", "book"], ["goTools", "tool"], ["goGuide", "help"], ["goSettings", "settings"]]) {
    $(id).prepend(icon(glyph, 17));
    $(id).addEventListener("click", () => go(`#~${$(id).dataset.page}`));
  }
  $("sideFoot").prepend(icon("lock", 14));
  $("themeBtn").addEventListener("click", () => setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => setTimeout(themeChanged, 0));
  themeChanged();
}
