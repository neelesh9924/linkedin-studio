// Before you confirm: in the Schedule… dialog's final check, and before a post joins the posting queue, what is worth a
// second look before the post goes to Publora, each with what to do about it. It only warns: nothing here stops Schedule
// it or the queue, and the studio's own refusals stay as they are. It reads the post as the page already has it, with
// the studio's blanks pattern and LinkedIn's limit (state.slot, state.target), and the time picked as the dialog has it:
// "YYYY-MM-DDTHH:MM", in the studio's time zone, which is this PC's own (the studio and its window run on the same PC).
// The queue picks no time (value null): nothing is said about one. A draft (Approve and queue) is told what to do in a
// draft's words: Not yet, then the fix, where an approved post goes Back to draft first.
import { state, h, icon, number, plural } from "./core.js";

const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
  "November", "December"];
const DAY = 24 * 60;            // minutes
const WEEK = 7 * DAY;
const LINK = /\bhttps?:\/\/[^\s<>"]+|\bwww\.[a-z0-9-]+\.[^\s<>"]+/i;
const FEW = 3;                  // this month's posts left after this one, at most, before it says so

// How a fix starts: an approved post goes back to draft first; a draft waits (Not yet) and is fixed as it is.
const fix = (p, words, again = true) => (p.status === "draft" ? `Press Not yet, then ${words}.`
  : `Back to draft to ${words}${again ? ", then approve it again" : ""}.`);

// The section, or null when nothing applies.
export function beforeYouConfirm(p, value) {
  const at = parse(value);
  const lines = [blanks(p), ...tooLong(p), link(p), picture(p), ...timing(p, value, at), monthLeft(p, at)].filter(Boolean);
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
  if (!kept || p.picture) return "";
  return `It goes out without a picture, though ${kept === 1 ? "one is" : `${number(kept)} are`} kept with it. To send one: `
    + fix(p, "choose Use as the picture beside the post", false);
}

// A time already gone, and one far from the week plan's day and time for this post (a weekday and a time: the nearest
// such moment counts).
function timing(p, value, at) {
  if (!at) return [];
  const out = [];
  if (value.slice(0, 16) < clockNow()) out.push("That time has already passed. Change the time to a later one.");
  const slot = planSlot(p.plan);
  if (slot !== null) {
    const gap = Math.abs(at.weekday * DAY + at.minutes - slot) % WEEK;
    if (Math.min(gap, WEEK - gap) > DAY) {
      out.push(`The week plan has it on ${p.plan.day}, ${p.plan.time}, more than a day from this time. Change the time `
        + "to keep to the plan.");
    }
  }
  return out;
}

// p.used and p.limit are this month's (p.month): a time in another month is counted there, so it says nothing.
function monthLeft(p, at) {
  if (!at || typeof p.limit !== "number" || typeof p.used !== "number" || MONTHS[at.month - 1] !== p.month) return "";
  const left = p.limit - p.used - 1;
  if (left > FEW) return "";
  if (left < 0) return `Your ${number(p.limit)} posts for ${p.month} are all used, so this one will be refused. Pick a time next month.`;
  if (left === 0) return `This is the last of your ${number(p.limit)} posts for ${p.month}. Make it one that matters, or pick a time next month.`;
  return `After this one, ${plural(left, "post is", "posts are")} left of your ${number(p.limit)} for ${p.month}. `
    + `Keep ${left === 1 ? "it" : "them"} for the posts that matter most.`;
}

function parse(value) {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(typeof value === "string" ? value : "");
  if (!m) return null;
  const [y, mo, d, hh, mi] = m.slice(1).map(Number);
  if (mo < 1 || mo > 12 || hh > 23 || mi > 59) return null;
  return { month: mo, weekday: (new Date(Date.UTC(y, mo - 1, d)).getUTCDay() + 6) % 7, minutes: hh * 60 + mi };   // Monday 0
}

const pad = (n) => String(n).padStart(2, "0");
function clockNow() {
  const d = new Date();
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

// The plan's slot in minutes from Monday 00:00, read defensively: "Tue" or "Tuesday", "8:00 AM", "8 AM" or "20:00".
// Anything else: null, and no warning.
function planSlot(plan) {
  if (!plan || typeof plan.day !== "string" || typeof plan.time !== "string") return null;
  const day = DAYS.findIndex((d) => plan.day.trim().toLowerCase().startsWith(d));
  const m = /^\s*(\d{1,2})(?:[:.](\d{2}))?\s*(?:([ap])\.?\s*m\.?)?\s*$/i.exec(plan.time);
  if (day < 0 || !m || (!m[2] && !m[3])) return null;
  let hour = Number(m[1]);
  const minute = Number(m[2] || 0);
  if (m[3]) {
    if (hour < 1 || hour > 12) return null;
    hour = (hour % 12) + (m[3].toLowerCase() === "p" ? 12 : 0);
  }
  if (hour > 23 || minute > 59) return null;
  return day * DAY + hour * 60 + minute;
}
