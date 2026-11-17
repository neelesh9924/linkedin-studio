// Words compared, drawn one way wherever the page shows it (a version compared with now; the revision card): the
// studio's [op, text] pieces (render.wdiff) as removed words struck and added words marked, each led by a word that only
// a screen reader says ("removed:", "added:"), and a change of spacing alone named as one.
import { h } from "./core.js";

const SAID = { "+": ["ins", "added: "], "-": ["del", "removed: "] };

export function wordDiff(segments) {
  return (segments || []).map(([op, text]) => {
    if (!SAID[op]) return text;
    const [tag, word] = SAID[op];
    const blank = !text.trim() ? (text.includes("\n") ? "a line break" : "a space") : "";
    return h(tag, null, h("span", { class: "sr-only" }, word + blank), text);
  });
}
