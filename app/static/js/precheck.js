// Before you confirm: in the Schedule… dialog's final check, in Post now…'s, and before a post joins the posting queue,
// what is worth a second look before the post goes to Publora, each with what to do about it. It only warns: nothing here
// stops Schedule it, Post it now or the queue, and the studio's own refusals stay as they are. It reads the post as the
// page already has it, with the studio's blanks pattern and LinkedIn's limit (state.slot, state.target), and the time
// picked as the dialog has it: "YYYY-MM-DDTHH:MM", in the studio's time zone, which is this PC's own (the studio and its
// window run on the same PC). The queue picks no time (value null): nothing is said about one. Post now (`now`) picks
// none either, and goes out this month: the month's last posts are said in its words. A draft (Approve and queue, Post
// now) is told what to do in a draft's words: Not yet, then the fix, where an approved post goes Back to draft first.
import { state, h, icon, number, plural } from "./core.js";

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
  "November", "December"];
const LINK = /\bhttps?:\/\/[^\s<>"]+|\bwww\.[a-z0-9-]+\.[^\s<>"]+/i;
const FEW = 3;                  // this month's posts left after this one, at most, before it says so

// How a fix starts: an approved post goes back to draft first; a draft waits (Not yet) and is fixed as it is.
const fix = (p, words, again = true) => (p.status === "draft" ? `Press Not yet, then ${words}.`
  : `Back to draft to ${words}${again ? ", then approve it again" : ""}.`);

// The section, or null when nothing applies.
export function beforeYouConfirm(p, value, now = false) {
  const at = now ? { month: MONTHS.indexOf(p.month) + 1 } : parse(value);
  const lines = [blanks(p), ...tooLong(p), link(p), picture(p), ...(now ? [] : timing(value, at)), monthLeft(p, at, now)]
    .filter(Boolean);
  if (!lines.length) return null;
  // data-describe: the dialog's description says these too (core.js nameDialog), so they are heard as it opens
  return h("section", { class: "results precheck", id: "precheck", "aria-labelledby": "precheckTitle", "data-describe": true },
    h("h3", { id: "precheckTitle" }, "Before you confirm"),
    lines.map((words) => h("div", { class: "result warn" }, icon("alert", 15), h("div", null, words))));
}

function blanks(p) {
  let pattern;
  try {
    pattern = state.slot ? new RegExp(state.slot, "g") : null;
  } catch {
    pattern = null;
  }
  if (!pattern) return "";
  const inText = String(p.text || "").match(pattern) || [];
  const inComment = String(p.first_comment || "").match(pattern) || [];
  const all = [...inText, ...inComment];
  if (!all.length) return "";
  const where = inText.length && inComment.length ? "The text and the first comment still have"
    : inText.length ? "The text still has" : "The first comment still has";
  const one = all.length === 1;
  return `${where} ${one ? "a blank" : `${number(all.length)} blanks, such as`} ${all[0]}. `
    + fix(p, `fill ${one ? "it in or cut it" : "them in or cut them"}`);
}

function tooLong(p) {
  const out = [];
  const hard = state.target && state.target.hard;
  const chars = String(p.text || "").length;
  if (hard && chars > hard) {
    out.push(`The text is ${number(chars)} characters; LinkedIn takes ${number(hard)}. ${fix(p, `cut ${number(chars - hard)}`)}`);
  }
  const max = p.first_comment_max;
  const comment = String(p.first_comment || "").trim().length;
  if (max && comment > max) {
    out.push(`The first comment is ${number(comment)} characters; LinkedIn takes ${number(max)}. `
      + fix(p, `cut ${number(comment - max)} from it`, false));
  }
  return out;
}

function link(p) {
  const found = LINK.exec(String(p.text || ""));
  if (!found) return "";
  const url = found[0].replace(/[).,;:!?'"’”]+$/, "");
  return `The text has a link in it (${url.length > 48 ? `${url.slice(0, 47)}…` : url}). A link reads better as the `
    + `first comment. ${fix(p, "move it there", false)}`;
}

function picture(p) {
  const kept = Array.isArray(p.pictures) ? p.pictures.length : 0;
  if (!kept || (p.media || []).length) return "";
  return `It goes out without a picture, though ${kept === 1 ? "one is" : `${number(kept)} are`} kept with it. To send one: `
    + fix(p, "choose Add to the post under Pictures, beside the post", false);
}

// A time already gone.
function timing(value, at) {
  return at && value.slice(0, 16) < clockNow() ? ["That time has already passed. Change the time to a later one."] : [];
}

// p.used and p.limit are this month's (p.month): a time in another month is counted there, so it says nothing. Post now
// can't wait for next month: the queue can.
function monthLeft(p, at, now) {
  if (!at || !p.limit || typeof p.used !== "number" || MONTHS[at.month - 1] !== p.month) return "";   // 0: no monthly limit
  const left = p.limit - p.used - 1;
  if (left > FEW) return "";
  if (left < 0) return `Your ${number(p.limit)} posts for ${p.month} are all used, so this one will be refused. `
    + (now ? "Queue it instead: the queue gives it a time next month." : "Pick a time next month.");
  if (left === 0) return `This is the last of your ${number(p.limit)} posts for ${p.month}. Make it one that matters, or `
    + (now ? "queue it for next month." : "pick a time next month.");
  return `After this one, ${plural(left, "post is", "posts are")} left of your ${number(p.limit)} for ${p.month}. `
    + `Keep ${left === 1 ? "it" : "them"} for the posts that matter most.`;
}

function parse(value) {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(typeof value === "string" ? value : "");
  if (!m) return null;
  const [, mo, , hh, mi] = m.slice(1).map(Number);
  if (mo < 1 || mo > 12 || hh > 23 || mi > 59) return null;
  return { month: mo };
}

const pad = (n) => String(n).padStart(2, "0");
function clockNow() {
  const d = new Date();
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
