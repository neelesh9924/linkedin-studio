// Hot topics: the latest news in the owner's niche (app/hot.py), ranked for them, each item one press from a draft.
// One list, best for you first: each item's rank (1 to 10, from how it fits you and whether it makes a post), why, and
// the post it would become; then the items not ranked yet; those not for you (1 to 4) fold away under the list. The same
// story from several sources is one item, naming the others. The studio reads the news when the page opens and its
// copy is over an hour old (Refresh reads it again), then Claude ranks what is new, a batch at a time: the page says so,
// and a ranking that did not finish offers Try again. Draft has Claude write the post the rank saw in the item, its
// link in the first comment: the item shows the draft at work (Stop), then Open the post. Drawn again, an item keeps
// the focus that was in it. Search the news, between the panel and the lists and never drawn again (typing keeps its
// place): the items with every word in their title, source, area, rank, why or post (search.js), the words marked, the
// fold open while it holds some; Esc empties it, / comes back to it (palette.js).
import { $, state, h, icon, api, post, put, plural, announce, whileBusy, drawIfChanged, focusFirst, go } from "./core.js";
import { drawWorking, problemCard } from "./jobs.js";
import { wordsOf, find, marked } from "./search.js";

let box = null;
let head = null;          // the panel: drawn again with the news
let lists = null;         // the lists: drawn again with the news and the search
let data = null;
let query = "";
let foldOpen = false;     // Not for you, as the owner left it (while searching, it is open when it holds a match)

const poll = () => window.dispatchEvent(new Event("studio:poll"));

export async function render(container) {
  box = container;
  if (!$("hotSearch") || !box.contains($("hotSearch"))) frame();
  await refresh();
}

function frame() {
  head = h("div", { class: "hot-area" });
  lists = h("div", { class: "hot-area" }, h("p", { class: "lede" }, "Loading…"));
  const input = h("input", { id: "hotSearch", class: "input search-input", type: "search", placeholder: "Search the news",
    "aria-label": "Search the news", "aria-describedby": "hotFound", "aria-keyshortcuts": "/", autocomplete: "off", spellcheck: "false" });
  input.addEventListener("input", () => {
    query = input.value;
    redraw();
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && input.value) {
      event.preventDefault();
      input.value = query = "";
      redraw();
    }
  });
  put(box, h("div", { class: "page-width" }, head,
    h("div", { class: "hot-search", role: "search" }, icon("search", 16), input, h("span", { id: "hotFound", class: "soft", role: "status" })),
    lists));
}

export async function refresh() {
  if (!box || state.page !== "hot") return;
  const reply = await api("/api/hot");
  if (reply.error || state.page !== "hot") return;
  data = reply;
  redraw();
}

// Drawn again when the news or the search changed; the focus stays in the item it was in.
function redraw() {
  if (!data) return;
  const item = box.contains(document.activeElement) && document.activeElement.closest(".hot-row");
  const kept = box.contains(document.activeElement) ? document.activeElement.dataset.keep : null;
  const drew = drawIfChanged(box, JSON.stringify([query, data], (k, v) => (["seconds", "quiet", "progress", "activity"].includes(k) ? undefined : v)), draw);
  tick();
  if (drew && item && item.id) focusFirst(`#${item.id} .job-box button`, `#${item.id} .hot-acts button`, `#${item.id} .hot-title`);
  else if (drew && kept) focusFirst(box.querySelector(`[data-keep="${kept}"]`));
}

// An item found by the words: in its title, where it is from, its rank's words, why, the post it would make.
const findTopic = (t, words) => find(words, [["title", t.title], ["from", [t.source, t.area, ...(t.also || [])].join(" · ")],
  ["rank", t.label || ""], ["angle", t.angle || ""], ["why", t.why || t.summary || ""], ["post", t.post ? t.post.label : ""]]);

// Between polls only the jobs' words and timers change.
export function tick() {
  if (!data || !box) return;
  for (const job of state.jobs) {
    const spot = box.querySelector(`[data-job-box="${job.id}"]`);
    if (spot) drawWorking(spot, job);
  }
}

function draw() {
  const d = data;
  const words = wordsOf(query);
  const hits = words.length ? d.topics.filter((t) => findTopic(t, words)) : d.topics;
  const good = hits.filter((t) => t.rank != null && t.verdict !== "drop");
  const waiting = hits.filter((t) => t.rank == null);
  const not = hits.filter((t) => t.verdict === "drop");
  const again = h("button", { class: "btn small ghost", type: "button", "data-keep": "refresh", disabled: d.reading },
    icon("refresh", 14), h("span", null, d.reading ? "Reading…" : "Refresh"));
  again.addEventListener("click", () => whileBusy(again, async () => {
    const reply = await post("/api/hot/refresh", {});
    announce(reply.error || "Reading the news again.", { urgent: !!reply.error });
    await refresh();
  }));
  const read = d.reading ? (d.fetched ? `Reading the news again. Below: what was read ${d.fetched}.` : "Reading the news…")
    : d.fetched ? `Read ${d.fetched}.` : "";
  put(head,
    h("section", { class: "panel", "aria-labelledby": "hot-title" },
      h("header", { class: "panel-head" }, h("span", { class: "panel-mark" }, icon("flame", 17)),
        h("div", null, h("h2", { id: "hot-title" }, "The news in your niche, ranked for you"),
          h("p", null, `The last ${d.days} days from the teams behind your tools, the Android and iOS newsletters, the Swift and `
            + "Django forums, engineering blogs, dev.to and Hacker News. Each item is ranked by how it fits you and whether it "
            + "makes a post; Draft writes the post its rank saw, with the link in the first comment.")),
        h("span", { class: "panel-tools" }, h("span", { class: "soft hot-read", role: "status" }, read), again)),
      ranking(d)),
    d.problems.length ? h("p", { class: "soft hot-problems" }, icon("info", 14),
      `Nothing came from ${d.problems.map((p) => `${p.source} (${p.error})`).join(", ")} this time.`) : null);
  const fold = not.length ? h("details", { class: "fold hot-fold", id: "hot-not-for-you", open: words.length ? true : foldOpen },
    h("summary", null, `Not for you: ${plural(not.length, "item", "items")}, ranked 1 to 4`),
    h("ol", { class: "hot-list" }, not.map((t) => row(t, words)))) : null;
  if (fold) fold.addEventListener("toggle", () => !wordsOf(query).length && (foldOpen = fold.open));
  put(lists,
    good.length ? list("best", "Best for you", "The highest rank first", good, words) : null,
    waiting.length ? list("waiting", "Not ranked yet", "The hottest, then the newest", waiting, words) : null,
    !d.topics.length ? h("p", { class: "soft hot-none" }, d.reading ? "Reading…" : "Nothing in your niche in this time.")
      : !hits.length ? h("p", { class: "soft hot-none" }, `Nothing matches “${query.trim()}”.`) : null,
    fold);
  $("hotFound").textContent = words.length && d.topics.length ? `${hits.length} of ${plural(d.topics.length, "item", "items")}` : "";
}

// Claude ranking what is new: its steps and Stop while it runs; Try again when it did not finish.
function ranking(d) {
  const run = d.ranking;
  if (!run) return null;
  if (["queued", "running"].includes(run.status)) {
    return h("div", { class: "panel-body" }, h("p", { class: "soft" }, `${plural(d.unranked, "item is", "items are")} waiting for a rank. `
      + "A batch at a time, so a Draft you press goes next."), h("div", { class: "job-box", "data-job-box": run.id }));
  }
  return h("div", { class: "panel-body" }, problemCard(run, { onDone: poll }));
}

function list(key, title, note, items, words) {
  return [h("div", { class: "section-title" }, h("h2", { id: `hot-${key}` }, title), h("span", null, note)),
    h("ol", { class: "hot-list", "aria-labelledby": `hot-${key}` }, items.map((t) => row(t, words)))];
}

function row(t, words) {
  let acts;
  if (t.post) {
    acts = [h("button", { class: "btn small", type: "button", "aria-label": `Open the post from: ${t.title}`, onclick: () => go(`#post-${t.post.id}`) },
      icon("file", 14), h("span", null, "Open the post")), h("span", { class: `chip ${t.post.kind}` }, t.post.label)];
  } else if (t.job && ["queued", "running"].includes(t.job.status)) {
    acts = h("div", { class: "job-box", "data-job-box": t.job.id });
  } else {
    const draft = h("button", { class: "btn small", type: "button", "aria-label": `Draft a post from: ${t.title}` },
      icon("sparkle", 14), h("span", null, "Draft"));
    draft.addEventListener("click", () => whileBusy(draft, async () => {
      const reply = await post(`/api/hot/${t.id}/draft`, {});
      announce(reply.error || "Drafting. The post joins the list when it is ready.", { urgent: !!reply.error });
      poll();
      await refresh();
    }));
    acts = [t.job ? problemCard(t.job, { onDone: poll }) : null, draft];
  }
  const facts = [t.source, t.area, t.when, t.points ? plural(t.points, "point", "points") : null,
    t.reactions ? plural(t.reactions, "reaction", "reactions") : null,
    t.comments ? plural(t.comments, "comment", "comments") : null].filter(Boolean).join(" · ");
  const talk = t.discussion && t.discussion !== t.url
    ? [" · ", h("a", { href: t.discussion, target: "_blank", rel: "noreferrer" }, "The discussion")] : null;
  const rank = t.rank != null
    ? h("span", { class: `hot-rank ${t.verdict}`, title: t.label }, h("b", null, String(t.rank)), h("small", null, "/10"))
    : h("span", { class: "hot-rank none" }, "Not ranked yet");
  return h("li", { class: "hot-row", id: `hot-${t.id}` },
    h("div", { class: "hot-main" },
      h("div", { class: "hot-head" }, rank,
        h("a", { class: "hot-title", href: t.url, target: "_blank", rel: "noreferrer", title: "Opens in your browser" }, marked(t.title, words))),
      h("div", { class: "hot-facts" }, marked(facts, words), talk, t.also.length ? marked(` · Also on ${t.also.join(", ")}`, words) : null),
      t.angle ? h("p", { class: "hot-angle" }, h("b", null, "The post: "), marked(t.angle, words)) : null,
      t.why ? h("p", { class: "hot-why soft" }, marked(t.why, words))
        : t.summary ? h("p", { class: "hot-summary" }, marked(t.summary, words)) : null),
    h("div", { class: "hot-acts" }, acts));
}
