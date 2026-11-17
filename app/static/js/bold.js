// LinkedIn's "bold": letters from Unicode's Mathematical Sans-Serif Bold block, as app/bold.py makes them from Claude's
// **words**. The same three starting points: A-Z, a-z and 0-9 map one to one, everything else stays as it is.
const UPPER = 0x1d5d4;
const LOWER = 0x1d5ee;
const DIGIT = 0x1d7ec;

export function toBold(text) {
  return Array.from(text, (ch) => {
    const c = ch.codePointAt(0);
    if (c >= 65 && c <= 90) return String.fromCodePoint(UPPER + c - 65);
    if (c >= 97 && c <= 122) return String.fromCodePoint(LOWER + c - 97);
    if (c >= 48 && c <= 57) return String.fromCodePoint(DIGIT + c - 48);
    return ch;
  }).join("");
}

export function fromBold(text) {
  return Array.from(text, (ch) => {
    const c = ch.codePointAt(0);
    if (c >= UPPER && c < UPPER + 26) return String.fromCharCode(65 + c - UPPER);
    if (c >= LOWER && c < LOWER + 26) return String.fromCharCode(97 + c - LOWER);
    if (c >= DIGIT && c < DIGIT + 10) return String.fromCharCode(48 + c - DIGIT);
    return ch;
  }).join("");
}

// The selection in a textarea made bold, or plain again when it has no plain letters left. Typed in, so Ctrl+Z undoes
// it, and the textarea's input event (saving) follows. Returns what it did, for the page to say.
export function toggleBold(ta) {
  const { selectionStart: from, selectionEnd: to, value } = ta;
  if (from === to) return "";
  const picked = value.slice(from, to);
  const plainLeft = /[A-Za-z0-9]/.test(picked);
  const next = plainLeft ? toBold(picked) : fromBold(picked);
  if (next === picked) return "";
  ta.focus();
  if (!document.execCommand || !document.execCommand("insertText", false, next)) {
    ta.setRangeText(next, from, to, "select");
    ta.dispatchEvent(new Event("input", { bubbles: true }));
  }
  ta.setSelectionRange(from, from + next.length);
  return plainLeft ? "Bold" : "Plain again";
}
