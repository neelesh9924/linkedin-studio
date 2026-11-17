// The search, one for the sidebar's box, Ctrl+K and Hot topics, so the three never differ: every word typed must be
// somewhere in what is looked in, in any case, LinkedIn's bold letters (𝗯𝗼𝗹𝗱) read as plain ones and curly quotes as
// straight. A post is looked in from /api/search (its text, its first comment, the words on its carousel or card, the
// news it came from, its title), asked again only once the studio changed (state.rev), and in what its caller adds
// (where it stands, as the list says it); until the words come, in its first line and title. A match is shown by the
// line it was found on, cut round the first word found, each word marked in the text as it is written.
import { state, h, api } from "./core.js";

const fold = (text) => String(text || "").normalize("NFKC").toLowerCase().replace(/[‘’ʼ]/g, "'").replace(/[“”]/g, '"');
export const wordsOf = (query) => fold(query).split(/\s+/).filter(Boolean);

// The text folded a letter at a time, and where each folded character came from: a word found in the folded text
// marks the same letters in the text as written (a bold letter is two characters of it, one folded).
function folding(text) {
  let folded = "";
  const from = [];
  let at = 0;
  for (const letter of text) {
    const f = fold(letter);
    folded += f;
    for (let i = 0; i < f.length; i++) from.push(at);
    at += letter.length;
  }
  from.push(at);
  return { folded, from };
}

// Each place a word is, in the text as written: [start, end) pairs, in order.
function places(text, words) {
  const { folded, from } = folding(text);
  const spans = [];
  for (const w of words) {
    for (let i = folded.indexOf(w); i >= 0; i = folded.indexOf(w, i + w.length)) spans.push([from[i], from[i + w.length]]);
  }
  return spans.sort((a, b) => a[0] - b[0]);
}

// Pieces as [where, text]: the line most of the words are on (the first such, by the pieces' order) as {where, line},
// or null unless every word is somewhere in them.
export function find(words, pieces) {
  if (!words.length) return null;
  const seen = new Set();
  let best = null;
  for (const [where, text] of pieces) {
    for (const line of String(text || "").split("\n")) {
      const folded = fold(line);
      const has = words.filter((w) => folded.includes(w));
      for (const w of has) seen.add(w);
      if (has.length && (!best || has.length > best.count)) best = { where, line: line.trim(), count: has.length };
    }
  }
  return seen.size === new Set(words).size ? best : null;
}

const WHERE = { comment: "First comment: ", carousel: "Carousel: ", card: "Card: ", news: "News: ", title: "Title: " };
const LONE = /[\uD800-\uDBFF]$/;   // the first half of a letter that takes two characters (a bold one)

// The line a match was found on, as a post's line under its name: where it was (not for its text), cut at spaces round
// the first word found when it is long, `lead` characters of what comes before it kept (the sidebar's line is narrow:
// a short lead keeps the word in sight).
export function lineOf(hit, words, size = 90, lead = 24) {
  const line = hit.line;
  const at = (places(line, words)[0] || [0])[0];
  let start = Math.max(0, at - lead);
  if (start > 0) start = line.lastIndexOf(" ", start) + 1;
  let end = Math.min(line.length, start + size);
  const space = line.lastIndexOf(" ", end);
  if (end < line.length && space > start + size / 2) end = space;
  if (LONE.test(line.slice(start, end))) end -= 1;
  return `${WHERE[hit.where] || ""}${start > 0 ? "…" : ""}${line.slice(start, end).trim()}${end < line.length ? "…" : ""}`;
}

// The text with each word marked where it is (in any case), as written: as nodes, never markup.
export function marked(text, words) {
  const shown = String(text || "");
  if (!words.length) return [shown];
  const out = [];
  let at = 0;
  for (const [from, to] of places(shown, words)) {
    if (to <= at) continue;
    const start = Math.max(from, at);
    if (start > at) out.push(shown.slice(at, start));
    out.push(h("mark", { class: "hit" }, shown.slice(start, to)));
    at = to;
  }
  if (at < shown.length) out.push(shown.slice(at));
  return out;
}

// ---------- the posts' words ----------

let said = new Map();    // post id → its pieces, from /api/search
let readAt = null;       // the state.rev they were read at
let asking = null;

// The posts' words as the studio has them now: true once they were read again (the caller draws again), false when
// they were already. A studio without /api/search, or one that did not answer, is asked again after its next change.
export function ensure() {
  if (asking) return asking;
  if (readAt === state.rev) return Promise.resolve(false);
  const rev = state.rev;
  asking = api("/api/search").then((reply) => {
    asking = null;
    readAt = rev;
    if (reply.error || !Array.isArray(reply.posts)) return false;
    said = new Map(reply.posts.map((p) => [p.id, p.words]));
    return true;
  });
  return asking;
}

// A post found by the words, as find() has it, looked in from its first line on (a match there needs no line of its
// own), then its words, its title and what the caller adds.
export function findPost(p, words, more = []) {
  return find(words, [["first", p.first], ...(said.get(p.id) || []), ["title", p.title], ...more]);
}

// A match its name already shows (its first line, its title, where it stands) needs no line under it.
export const shownAlready = (hit) => ["first", "title", "status"].includes(hit.where);
