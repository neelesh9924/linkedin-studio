// Light Markdown drawn as elements: headings, lists, quotes, rules, fenced code, pipe tables, **bold**, *italic*,
// `code`. Every piece of text goes in as text (never as HTML), so a reply, a LinkedIn post or the Story Bank can never
// become markup. `breaks` keeps single line breaks (chat replies); without it they reflow (hard-wrapped files).
import { h } from "./core.js";

const HEADING = /^(#{1,4})\s+(.*)$/;
const BULLET = /^\s*[-*]\s+(.*)$/;
const NUMBER = /^\s*\d+[.)]\s+(.*)$/;
const TABLE_RULE = /^\|?[\s:|-]+\|[\s:|-]*$/;
const INLINE = /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|((?<![*\w])\*[^*\n]+\*(?![*\w]))/g;

export const slug = (text) => text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "section";
// A heading's id inside a document: "doc-" first, so no heading can take one of the page's own ids (#status, #title…);
// render.doc_sections gives the table of contents the same anchors.
export const anchorOf = (text) => `doc-${slug(text)}`;

// **bold**, *italic* and `code` inside one line, as elements holding text.
export function inline(text) {
  const out = [];
  let at = 0;
  for (const m of text.matchAll(INLINE)) {
    if (m.index > at) out.push(text.slice(at, m.index));
    const piece = m[0];
    if (m[1]) out.push(h("code", null, piece.slice(1, -1)));
    else if (m[2]) out.push(h("strong", null, piece.slice(2, -2)));
    else out.push(h("em", null, piece.slice(1, -1)));
    at = m.index + piece.length;
  }
  if (at < text.length) out.push(text.slice(at));
  return out;
}

const cells = (line) => line.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());

export function markdown(text, { anchors = false, breaks = false } = {}) {
  const lines = String(text || "").replace(/\r\n/g, "\n").split("\n");
  const out = [];
  let para = [];
  let list = null;      // { tag, items }
  let quote = [];

  const joined = (parts) => (breaks ? parts.flatMap((p, i) => (i ? [h("br"), ...inline(p)] : inline(p))) : inline(parts.join(" ")));
  const flushPara = () => {
    if (para.length) out.push(h("p", null, joined(para)));
    para = [];
  };
  const closeList = () => {
    if (list) out.push(h(list.tag, null, list.items.map((item) => h("li", null, inline(item)))));
    list = null;
  };
  const flushQuote = () => {
    if (quote.length) out.push(h("blockquote", null, joined(quote)));
    quote = [];
  };
  const closeAll = () => {
    flushPara();
    closeList();
    flushQuote();
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const stripped = line.trim();
    if (stripped.startsWith("```")) {
      closeAll();
      const block = [];
      for (i += 1; i < lines.length && !lines[i].trim().startsWith("```"); i++) block.push(lines[i]);
      out.push(h("pre", null, h("code", null, block.join("\n"))));
      continue;
    }
    if (!stripped) {
      closeAll();
      continue;
    }
    const heading = HEADING.exec(stripped);
    if (heading) {
      closeAll();
      const level = Math.min(heading[1].length + 2, 6);   // '#' is the document title inside a page: h3
      const title = heading[2].trim();
      out.push(h(`h${level}`, anchors ? { id: anchorOf(title) } : null, inline(title)));
      continue;
    }
    if (/^[-*_]{3,}$/.test(stripped)) {
      closeAll();
      out.push(h("hr"));
      continue;
    }
    if (stripped.startsWith("|") && i + 1 < lines.length && TABLE_RULE.test(lines[i + 1].trim())) {
      closeAll();
      const head = cells(stripped);
      const rows = [];
      for (i += 2; i < lines.length && lines[i].trim().startsWith("|"); i++) rows.push(cells(lines[i]));
      i -= 1;
      out.push(h("div", { class: "table-wrap" }, h("table", null,
        h("thead", null, h("tr", null, head.map((c) => h("th", null, inline(c))))),
        h("tbody", null, rows.map((r) => h("tr", null, r.map((c) => h("td", null, inline(c)))))))));
      continue;
    }
    if (stripped.startsWith(">")) {
      flushPara();
      closeList();
      quote.push(stripped.replace(/^>+/, "").trim());
      continue;
    }
    const bullet = BULLET.exec(line);
    const numbered = NUMBER.exec(line);
    if (bullet || numbered) {
      flushPara();
      flushQuote();
      const tag = bullet ? "ul" : "ol";
      if (!list || list.tag !== tag) {
        closeList();
        list = { tag, items: [] };
      }
      list.items.push((bullet || numbered)[1].trim());
      continue;
    }
    if (list && list.items.length && /^[ \t]/.test(line)) {
      list.items[list.items.length - 1] += ` ${stripped}`;   // an indented line continues the item above it
      continue;
    }
    closeList();
    flushQuote();
    para.push(stripped);
  }
  closeAll();
  return out;
}
