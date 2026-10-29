// The studio's page, its entry (a module: no build step, nothing from outside this PC). Here: the pages and the address
// they follow (#post-<id>, #~planner, #~bank, #~voice, #~tools, #~guide, #~settings, #~trash, #~setup), asking the studio
// what changed and having each area draw it, and the start. Each area is its module in js/.
import { $, state, h, icon, api, put, setTitle, polled, lost, go, banner, focusFirst, forget } from "./js/core.js";
import { renderList, takeMade, init as initSidebar } from "./js/sidebar.js";
import { loadPost, forgetRefusal, init as initPost } from "./js/post.js";
import { showFor, refresh as refreshChat, init as initAssist } from "./js/assist.js";
import { init as initJobs } from "./js/jobs.js";
import * as planner from "./js/planner.js";
import * as bank from "./js/bank.js";
import * as tools from "./js/tools.js";
import * as settings from "./js/settings.js";
import * as guide from "./js/guide.js";
import * as trash from "./js/trash.js";

const POLL_MS = 2000;
const PAGES = { planner: ["Planner", planner], bank: ["Story Bank & Voice", bank], voice: ["Story Bank & Voice", bank],
  tools: ["Tools", tools], guide: ["Guide", guide], settings: ["Settings", settings], trash: ["Trash", trash],
  setup: ["Set up LinkedIn Studio", settings] };
const BOXES = ["postPage", "emptyPage", "plannerPage", "bankPage", "toolsPage", "guidePage", "settingsPage", "trashPage", "setupPage"];
const SUMMARY = ["id", "title", "first", "status", "label", "kind", "when", "queued", "scheduled_at", "picture", "busy", "trashed"];

// ---------- pages ----------

function show(box) {
  for (const id of BOXES) $(id).hidden = id !== box;
}

function replace(hash) {
  history.replaceState(null, "", hash);
  return route();
}

let turn = 0;   // each route() is a turn; one that waited for the studio gives way to a later one
async function route() {
  const mine = ++turn;
  const mark = decodeURIComponent(location.hash.slice(1));
  forgetRefusal();
  if (state.setup && mark !== "~setup") return replace("#~setup");
  $("app").classList.toggle("bare", mark === "~setup" && state.setup);
  const postMatch = /^post-(\d+)$/.exec(mark);
  if (postMatch) {
    const id = Number(postMatch[1]);
    // Not in the list the studio last sent: made a moment ago, in the Trash, or gone. The studio says which.
    if (!state.posts.some((p) => p.id === id)) {
      const data = await api(`/api/post/${id}`);
      if (mine !== turn) return;
      if (data.trashed) return replace("#~trash");
      if (!data.error && !state.posts.some((p) => p.id === id)) {
        state.posts = [Object.fromEntries(SUMMARY.map((k) => [k, data[k]])), ...state.posts];
      }
    }
    if (state.posts.some((p) => p.id === id)) return void openPost(id);
  }
  state.postId = null;
  $("postGear").hidden = true;
  $("topActions").replaceChildren();
  forget($("topActions"));   // so the same post, opened again unchanged, draws its buttons again
  $("status").replaceChildren();
  const [page, sub] = mark.startsWith("~") ? mark.slice(1).split("-") : ["posts"];
  if (PAGES[page]) {
    state.page = page;
    const [heading, module] = PAGES[page];
    $("title").textContent = heading;
    setTitle(`${heading} · LinkedIn Studio`);
    const box = `${page === "voice" ? "bank" : page === "setup" ? "setup" : page}Page`;
    show(box);
    showFor(page === "bank" || page === "voice" ? { kind: page } : null);
    module.render($(box), { page, sub });
    renderList();
    return;
  }
  // Posts: the first one (quietly, in place of one that is gone), or the page that says there are none.
  const first = state.posts[0];
  if (first) return replace(`#post-${first.id}`);
  state.page = "empty";
  $("title").textContent = "LinkedIn Studio";
  setTitle("LinkedIn Studio");
  show("emptyPage");
  showFor(null);
  renderEmpty();
  renderList();
}

// A post in the middle, its chat beside it. One made just now gets the focus in the Ask box (or on its text when the
// panel is hidden), so the next thing the owner types is what it should say.
function openPost(id) {
  state.page = "post";
  state.postId = id;
  show("postPage");
  $("postGear").hidden = false;
  showFor({ kind: "post", id });
  const fresh = takeMade(id);
  const asked = fresh && !$("app").classList.contains("no-assist") && focusFirst($("askText"));
  loadPost(id).then(() => {
    if (fresh && !asked && state.postId === id) focusFirst($("postPage").querySelector(".li-read, .li-edit"));
  });
  renderList();
}

function renderEmpty() {
  const start = h("button", { class: "btn primary", type: "button", onclick: () => $("newPost").click() }, icon("plus", 15), h("span", null, "New post"));
  const plan = h("button", { class: "btn", type: "button", onclick: () => go("#~planner") }, icon("calendar", 15), h("span", null, "Plan the week"));
  put($("emptyPage"), h("div", { class: "empty" },
    h("div", { class: "empty-mark" }, icon("file", 26)),
    h("h2", null, "No posts yet"),
    h("p", null, "Start a post and tell Claude what it is about, or plan the week and draft from the plan. Each post shows here as LinkedIn will show it."),
    h("div", { class: "form-foot" }, start, plan)));
}

// ---------- asking the studio what changed ----------

let polling = false;
let timer = 0;
let again = false;

async function poll() {
  if (polling) return void (again = true);
  polling = true;
  clearTimeout(timer);
  try {
    const data = await api("/api/state");
    if (!data.posts) {
      state.offline = true;
      window.dispatchEvent(new Event("studio:offline"));   // each time: an area may hold what it sends until it is back
      banner("offline", [icon("alert", 17), h("div", null, h("strong", null, lost.said ? "This window belongs to an earlier session."
        : "LinkedIn Studio is not running."), lost.said ? "Open LinkedIn Studio from its shortcut again." : "Start it again from its shortcut, then reload this window."),
      h("button", { class: "btn small", type: "button", onclick: () => location.reload() }, "Reload")], "bad");
      return;
    }
    if (state.offline) banner("offline", null);
    state.offline = false;
    const contentChanged = data.rev !== state.rev;
    const jobsChanged = JSON.stringify(data.jobs.map((j) => [j.id, j.status])) !== JSON.stringify(state.jobs.map((j) => [j.id, j.status]));
    Object.assign(state, { posts: data.posts, jobs: data.jobs, ended: data.ended, rev: data.rev, seq: data.seq, setup: data.setup,
      tz: data.tz, chatgpt: data.chatgpt, target: data.target, slot: data.slot });
    if (state.first) {
      state.first = false;
      route();
    } else if (contentChanged || jobsChanged) {
      if (state.page === "post" && !state.posts.some((p) => p.id === state.postId)) route();   // moved to the Trash or deleted elsewhere
      else if (state.page === "post") loadPost(state.postId, { quiet: true });
      else if (PAGES[state.page]) PAGES[state.page][1].refresh();
      else if (state.page === "empty" && state.posts.length) route();
      refreshChat();
    } else if (PAGES[state.page] && PAGES[state.page][1].tick) {
      PAGES[state.page][1].tick();
    }
    renderList();
    polled(data);
  } finally {
    polling = false;
    const soon = again;
    again = false;
    timer = setTimeout(poll, soon ? 50 : state.jobs.length ? 1000 : POLL_MS);
  }
}

// ---------- the start ----------

initSidebar();
initPost();
initAssist();
initJobs();
window.addEventListener("hashchange", route);
window.addEventListener("studio:poll", () => poll());
poll();
