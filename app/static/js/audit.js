// The audit's findings, one view wherever they show (beside a post, and Tools' Audit): the verdict in words, then what
// to fix before posting and what is worth a look, each finding with its fix.
import { h, icon } from "./core.js";

export function finding(item, blocker) {
  const issue = typeof item === "string" ? item : item.issue;
  const fix = typeof item === "string" ? "" : item.fix;
  return h("div", { class: `finding${blocker ? " blocker" : ""}` }, h("b", null, issue), fix ? h("span", null, fix) : null);
}

// `level` is the headings' level where the view sits (h3 under a page's panel, h4 inside a card); `stale` says the text
// changed after this audit.
export function auditView(d, { level = 3, stale = false } = {}) {
  const pass = String(d.verdict || "").toUpperCase() === "PASS";
  const blockers = d.blockers || [];
  const warnings = d.warnings || [];
  const head = (words) => h(`h${level}`, { class: "audit-head" }, words);
  return [
    h("div", { class: `verdict ${pass ? "pass" : "fail"}` }, icon(pass ? "check-circle" : "alert", 22),
      h("div", null, h("b", null, pass ? "Ready to post" : "Not ready yet"), d.summary ? h("div", null, d.summary) : null)),
    stale ? h("div", { class: "result warn" }, icon("alert", 15), h("div", null, "The text changed after this audit.")) : null,
    blockers.length ? [head(`Fix before posting (${blockers.length})`), blockers.map((b) => finding(b, true))] : null,
    warnings.length ? [head(`Worth a look (${warnings.length})`), warnings.map((w) => finding(w, false))] : null,
  ];
}
