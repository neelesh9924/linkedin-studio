// Story Bank & Voice: both files as the skills keep them, formatted and read-only, with the sections that have
// material; whether git leaves them alone. The chat beside the page fills them: the interviewer (Story Bank) or the
// voice-profile chat (Voice profile), the same Ask Claude panel as a post's. On the Story Bank, each filled entry has
// Ask me about this: a short interview about that entry alone, in a new conversation (assist.askAbout).
import { state, h, icon, api, put, go, drawIfChanged, whileBusy } from "./core.js";
import { markdown } from "./md.js";
import { askAbout } from "./assist.js";

let box = null;

export async function render(container) {
  box = container;
  if (!box.firstChild) put(box, h("p", { class: "lede" }, "Loading…"));
  await refresh();
}

export async function refresh() {
  if (!box || (state.page !== "bank" && state.page !== "voice")) return;
  const data = await api("/api/bank");
  if (data.error || (state.page !== "bank" && state.page !== "voice")) return;
  const mode = state.page === "voice" ? "voice" : "bank";
  drawIfChanged(box, JSON.stringify([mode, data]), () => draw(data, mode));
}

function draw(data, mode) {
  const f = data.files[mode];
  const p = data.protection;
  const tab = (key, glyph, label) => h("button", { class: "btn small", type: "button", "aria-pressed": String(key === mode),
    onclick: () => go(`#~${key}`) }, icon(glyph, 14), label);
  const status = f.status;
  put(box, h("div", { class: "page-width" },
    h("div", { class: "seg-row" },
      h("div", { class: "segmented", role: "group", "aria-label": "Which file" }, tab("bank", "book", "Story Bank"), tab("voice", "feather", "Voice profile")),
      h("span", { class: "grow" }),
      h("span", { class: `chip ${p.ok ? "ok" : "warn"}`, title: p.detail }, icon(p.ok ? "lock" : "alert", 12), p.ok ? "Private: kept out of git" : "Not protected from git"),
      h("span", { class: `chip ${status.is_filled ? "ok" : ""}` }, status.is_filled ? "Filled" : "Still empty"),
      status.is_filled && status.updated ? h("span", { class: "soft" }, `Updated ${status.updated}`) : null,
      status.is_filled && status.sessions ? h("span", { class: "soft" }, `· ${status.sessions} interviews`) : null),
    !p.ok ? h("div", { class: "notice" }, icon("alert", 16), h("div", null, h("strong", null, "Not protected from git."),
      `${p.detail} Until then, do not commit or push the skills folder.`))
      : f.text.includes(".gitignore") ? h("div", { class: "notice ok" }, icon("lock", 16), h("div", null, h("strong", null, "Already private."),
        `${p.detail} The advice about .gitignore inside this file needs nothing more from you.`)) : null,
    f.text ? h("div", { class: "doc-grid" },
      mode === "bank" ? askButtons(h("article", { class: "panel doc prose" }, markdown(f.text, { anchors: true })), f.sections)
        : h("article", { class: "panel doc prose" }, markdown(f.text, { anchors: true })),
      h("nav", { class: "panel toc", "aria-label": "Sections" },
        h("div", { class: "toc-label" }, `${f.filled} of ${f.sections.length} sections have material`),
        f.sections.map((s) => h("a", { href: `#~${mode}`, class: s.filled ? "has" : "",
          onclick: (event) => {
            event.preventDefault();
            const target = box.querySelector(`#${CSS.escape(s.anchor)}`);
            if (target) target.scrollIntoView({ block: "start" });
          } }, h("span", { class: "dot" }), h("span", null, s.title), s.filled ? h("span", { class: "n" }, String(s.filled)) : null))))
      : h("div", { class: "notice bad" }, icon("alert", 16), h("div", null, `The file ${f.path} was not found. Check skills_dir (Settings › Change folders).`)),
    h("p", { class: "soft" }, `Read-only here, so the format stays what the skills expect. Change it through the chat on the right. The file is ${f.path}; back it up with data\\studio.db.`)));
}

// Ask me about this beside each entry the studio counts as filled. The studio lists them (render.doc_sections, by the rule
// its counts use), so the page never decides for itself what is filled: each list item of a section is matched, in order,
// to the next of that section's entries (its words without the * and ` marks, a continued line after it).
const plain = (text) => String(text).replace(/[*`]/g, "").replace(/\s+/g, " ").trim();

function askButtons(article, sections) {
  const byAnchor = new Map(sections.map((s) => [s.anchor, s]));
  let section = null;
  let next = 0;
  for (const el of [...article.children]) {
    if (el.tagName === "H4") {                       // "## " ends a section; "## N. Title" starts one
      section = byAnchor.get(el.id) || null;
      next = 0;
      continue;
    }
    if (!section || el.tagName !== "UL") continue;
    for (const li of el.children) {
      const entry = section.entries[next];
      if (entry === undefined || !plain(li.textContent).startsWith(plain(entry))) continue;
      next += 1;
      const s = section;
      const named = plain(entry).length > 120 ? `${plain(entry).slice(0, 120)}…` : plain(entry);
      const ask = h("button", { class: "btn ghost small ask-about", type: "button", "aria-label": `Ask me about this: ${named}`,
        title: "A short interview about this entry, in a new conversation" }, icon("chat", 13), h("span", null, "Ask me about this"));
      ask.addEventListener("click", () => whileBusy(ask, () => askAbout({ section: s.title, entry })));
      li.append(" ", ask);
    }
  }
  return article;
}
