// Story Bank & Voice: both files as the skills keep them, formatted and read-only, with the sections that have
// material; whether git leaves them alone. The chat beside the page fills them: the interviewer (Story Bank) or the
// voice-profile chat (Voice profile), the same Ask Claude panel as a post's.
import { state, h, icon, api, put, go, drawIfChanged } from "./core.js";
import { markdown } from "./md.js";

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
      h("article", { class: "panel doc prose" }, markdown(f.text, { anchors: true })),
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
