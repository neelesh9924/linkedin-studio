// The Trash, as in the owner's other studios: the posts moved there with Move to Trash…, newest first. Put back returns
// one as it was (its state, versions, chat and pictures); Delete forever… and Empty trash ask first and name what goes.
// Each button says whose it is ("Put back, <title>"). After each, the line that says what happened has the focus and is
// said; drawn again after a poll, the focus stays where it was (the same button of the same post, or that line).
import { state, h, icon, api, post, put, plural, announce, whileBusy, focusFirst, showDialog, closeDialog, closeButton,
  drawIfChanged } from "./core.js";

const SHOWN_NAMES = 8;   // a confirmation names this many, then "and N more"
const WAS = { draft: "it was a draft", approved: "it was approved", failed: "its sending had failed", cancelled: "it was cancelled on Publora" };

let box = null;
let entries = [];
let notice = null;       // { said, kind }: what the last action did, until the page is opened afresh

export async function render(container) {
  box = container;
  notice = null;
  if (!box.firstChild) put(box, h("p", { class: "lede" }, "Loading…"));
  await draw();
}

export async function refresh() {
  if (box && state.page === "trash") await draw();
}

const nameOf = (entry) => entry.title || entry.first;

function line(kind, said) {
  return h("div", { class: `result ${kind}`, "data-keep": "said" }, icon(kind === "ok" ? "check" : "alert", 15), h("div", null, said));
}

// After an action: `done` says what it did; it is shown above the list, takes the focus and is said.
async function draw(done = null) {
  const reply = await api("/api/trash");
  if (!box || state.page !== "trash") return;
  if (done) notice = done;
  if (!reply.entries) {
    put(box, h("div", { class: "page-width" }, line("bad", reply.error || "The Trash could not be read just now.")));
    return;
  }
  entries = reply.entries;
  const on = box.contains(document.activeElement) ? document.activeElement.dataset.keep || "" : "";
  const drew = drawIfChanged(box, JSON.stringify([entries, notice]), () => {
    let empty = null;
    if (entries.length) {
      empty = h("button", { class: "btn danger", type: "button", "data-keep": "empty" }, icon("trash", 15), h("span", null, "Empty trash"));
      empty.addEventListener("click", () => askEmpty());
    }
    put(box, h("div", { class: "page-width" },
      h("section", { class: "panel", id: "trash" },
        h("header", { class: "panel-head" }, h("span", { class: "panel-mark" }, icon("trash", 17)),
          h("div", null, h("h2", null, "Trash"),
            h("p", null, "The posts you moved here, newest first. Put one back as it was, or delete it forever."))),
        h("div", { class: "form" },
          notice ? h("div", { class: "results" }, line(notice.kind, notice.said)) : null,
          entries.length ? h("div", { class: "form-foot" },
            h("span", { class: "field-hint grow" }, `${plural(entries.length, "post", "posts")} in the Trash.`), empty) : null,
          entries.length
            ? h("ol", { class: "trash-list", "aria-label": "In the Trash" }, entries.map(row))
            : h("p", { class: "soft" }, "The Trash is empty. A post’s gear moves it here with Move to Trash…; scheduled and published posts stay where they are.")))));
  });
  const first = () => [box.querySelector(".trash-row button"), box.querySelector('[data-keep="empty"]')];
  if (done) {   // the button pressed is gone: the focus goes to what it did
    focusFirst(box.querySelector('[data-keep="said"]'), first());
    announce(done.said, { urgent: done.kind === "bad" });
  } else if (drew && on) {
    focusFirst(box.querySelector(`[data-keep="${CSS.escape(on)}"]`), box.querySelector('[data-keep="said"]'), first());
  }
}

function row(entry) {
  const name = nameOf(entry);
  const back = h("button", { class: "btn small", type: "button", "data-keep": `back-${entry.id}`, "aria-label": `Put back, ${name}` }, "Put back");
  back.addEventListener("click", () => putBack(entry, back));
  const gone = h("button", { class: "btn danger small", type: "button", "data-keep": `delete-${entry.id}`, "aria-label": `Delete forever, ${name}` },
    "Delete forever…");
  gone.addEventListener("click", () => askDelete(entry));
  const facts = [`Moved here ${entry.ago || entry.when}`, WAS[entry.status] || `it was ${entry.label.toLowerCase()}`,
    entry.versions ? plural(entry.versions, "version", "versions") : null, entry.picture ? "a picture" : null].filter(Boolean);
  return h("li", { class: "trash-row", "data-id": entry.id },
    icon(entry.picture ? "image" : "file", 16),
    h("div", { class: "version-text" }, h("b", { title: entry.first }, name),
      entry.first !== name ? h("small", { title: entry.first }, entry.first) : null,
      h("small", { title: entry.when }, facts.join(" · "))),
    back, gone);
}

async function putBack(entry, button) {
  await whileBusy(button, async () => {
    const reply = await post("/api/trash/back", { id: entry.id });
    if (reply.error) return draw({ said: reply.error, kind: "bad" });
    await draw({ said: `${nameOf(entry)} is back among your posts, as it was.`, kind: "ok" });
    window.dispatchEvent(new Event("studio:poll"));   // the list has it again
  });
}

function askDelete(entry) {
  confirmDelete(`Delete ${nameOf(entry)} forever?`,
    "Deletes the post, its versions, its chat and its pictures from this computer. This can’t be undone.",
    [nameOf(entry)], "Delete forever", { ids: [entry.id] }, "Deleted forever.");
}

function askEmpty() {
  const n = entries.length;
  confirmDelete("Empty the Trash?",
    `Deletes ${n === 1 ? "this post, its versions, its chat and its pictures" : `these ${plural(n, "post", "posts")}, their versions, chats and pictures`} from this computer. This can’t be undone.`,
    entries.map(nameOf), "Empty trash", { ids: entries.map((e) => e.id), all: true }, "The Trash is empty.");
}

// The confirmation names what goes (up to eight, then "and N more"); only its button sends the deletion, confirmed.
function confirmDelete(title, said, names, label, body, done) {
  const go = h("button", { class: "btn danger", type: "button" }, icon("trash", 15), h("span", null, label));
  const out = h("div", { class: "results" });
  go.addEventListener("click", () => whileBusy(go, async () => {
    const reply = await post("/api/trash/delete", { ...body, confirmed: true });
    if (reply.error) {
      put(out, line("bad", `Nothing was deleted: ${reply.error}`));
      return announce(reply.error, { urgent: true });
    }
    closeDialog();
    await draw({ said: done, kind: "ok" });
  }));
  showDialog(h("h2", null, title), h("p", null, said),
    h("ul", { class: "trash-names" }, names.slice(0, SHOWN_NAMES).map((name) => h("li", null, name)),
      names.length > SHOWN_NAMES ? h("li", null, `and ${names.length - SHOWN_NAMES} more`) : null),
    out,
    h("div", { class: "dialog-foot" }, closeButton("Cancel"), go));
}
