// The studio's page, its entry (a module: no build step, nothing from outside this PC). Here: the pages and the address
// they follow (#~posts-<tab>, the start: Drafts; #post-<id>, #~schedule, #~hot, #~bank, #~voice, #~tools, #~guide,
// #~settings, #~trash, #~setup), asking the studio what changed and having each area draw it, and the start. Each area is
// its module in js/.
import { $, state, h, icon, api, setTitle, polled, lost, banner, focusFirst, forget } from "./js/core.js";
import { renderSide, takeMade, init as initSidebar } from "./js/sidebar.js";
import { loadPost, shownPost, forgetRefusal, init as initPost } from "./js/post.js";
import { showFor, refresh as refreshChat, init as initAssist } from "./js/assist.js";
import { init as initJobs } from "./js/jobs.js";
import * as posts from "./js/posts.js";
import * as schedule from "./js/schedule.js";
import * as hot from "./js/hot.js";
import * as bank from "./js/bank.js";
import * as tools from "./js/tools.js";
import * as settings from "./js/settings.js";
import * as guide from "./js/guide.js";
import * as trash from "./js/trash.js";

const POLL_MS = 2000;
const PAGES = { posts: ["Posts", posts], schedule: ["Schedule", schedule], hot: ["Hot topics", hot], bank: ["Story Bank & Voice", bank],
  voice: ["Story Bank & Voice", bank], tools: ["Tools", tools], guide: ["Guide", guide], settings: ["Settings", settings],
  trash: ["Trash", trash], setup: ["Set up LinkedIn Studio", settings] };
const BOXES = ["postPage", "postsPage", "schedulePage", "hotPage", "bankPage", "toolsPage", "guidePage", "settingsPage", "trashPage",
  "setupPage"];
const SUMMARY = ["id", "title", "first", "status", "label", "kind", "when", "queued", "scheduled_at", "picture", "busy", "trashed"];

// ---------- pages ----------

// One box at a time; on any page but a post, the top bar's title lines up over the page's centred column (app.css).
function show(box) {
  for (const id of BOXES) $(id).hidden = id !== box;
  $("app").classList.toggle("on-page", box !== "postPage");
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
  const from = state.postId;   // the post left, whose row in its list takes the focus that went with it
  state.postId = null;
  $("postGear").hidden = true;
  $("backTo").hidden = true;
  $("topActions").replaceChildren();
  forget($("topActions"));   // so the same post, opened again unchanged, draws its buttons again
  $("status").replaceChildren();
  // A page, or the posts (the start, a post that is gone, an address not known): a tab's list, Drafts unless named; the
  // address said so, quietly, when it named something else.
  const [named, sub] = mark.startsWith("~") ? mark.slice(1).split("-") : ["posts"];
  const page = PAGES[named] ? named : "posts";
  if (mark && page === "posts" && !mark.startsWith("~posts")) return replace("#~posts-drafts");
  state.page = page;
  const [heading, module] = PAGES[page];
  const title = page === "posts" ? posts.tabNamed(sub).name : heading;
  $("title").textContent = title;
  setTitle(`${title} · LinkedIn Studio`);
  const box = `${page === "voice" ? "bank" : page === "setup" ? "setup" : page}Page`;
  show(box);
  showFor(page === "bank" || page === "voice" ? { kind: page } : null);
  module.render($(box), { page, sub, from });
  renderSide();
  posts.warnFailed();
}

// A post in the middle, its chat beside it. One made just now gets the focus in the Ask box (or on its text when the
// panel is hidden), so the next thing the owner types is what it should say. While the page still holds the post opened
// before (opened from a list, the page between them), it stays out of sight until this one is drawn.
function openPost(id) {
  state.page = "post";
  state.postId = id;
  $("postPage").classList.toggle("loading", !!shownPost() && shownPost().id !== id);
  show("postPage");
  $("postGear").hidden = false;
  showFor({ kind: "post", id });
  const fresh = takeMade(id);
  const asked = fresh && !$("app").classList.contains("no-assist") && focusFirst($("askText"));
  loadPost(id).then(() => {
    if (state.postId === id) $("postPage").classList.remove("loading");
    if (fresh && !asked && state.postId === id) focusFirst($("postPage").querySelector(".li-read, .li-edit"));
  });
  renderSide();
  posts.warnFailed();
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
      refreshChat();
    } else if (PAGES[state.page] && PAGES[state.page][1].tick) {
      PAGES[state.page][1].tick();
    }
    renderSide();
    posts.warnFailed();
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
