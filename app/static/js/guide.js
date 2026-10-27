// The Guide: the routine as steps to click through, what happens while Claude works, a post's four states, an editor
// to practise in, each screen with its picture, and the keys and limits. Its words come from app/guide.py, with the
// figures the code enforces; its pictures (static/guide/, taken on the demo by dev/guide_shots.py) follow the theme,
// and a click shows one large.
import { $, state, h, icon, api, put, go, focusFirst, showDialog, closeButton } from "./core.js";
import { foldOf, withBlanks, meter, autosize } from "./editor.js";

let box = null;
let data = null;
let fitPractice = () => {};    // the practice editor measures its text once it is in the page

// A screen's picture, in the current theme (both are in the page; the theme shows one), as a button that enlarges it.
function picture(shot) {
  const frame = h("button", { class: "shot-frame", type: "button", "aria-label": `${shot.alt}. Show it larger` },
    h("img", { class: "when-light", src: shot.light, alt: "", loading: "lazy", width: 1200, height: 750 }),
    h("img", { class: "when-dark", src: shot.dark, alt: "", loading: "lazy", width: 1200, height: 750 }));
  frame.addEventListener("click", () => {
    showDialog(h("h2", null, shot.alt),
      h("div", { class: "shot-frame", style: "cursor:auto" },
        h("img", { class: "when-light", src: shot.light, alt: shot.alt }), h("img", { class: "when-dark", src: shot.dark, alt: shot.alt })),
      h("div", { class: "dialog-foot" }, closeButton()));
    $("dialog").classList.add("wide");
  });
  return frame;
}
const shotOf = (name) => (name && data.shots && data.shots[name]) || null;

export async function render(container) {
  box = container;
  if (!data) {
    put(box, h("p", { class: "lede" }, "Loading…"));
    data = await api("/api/guide");
  }
  if (data.error) return void put(box, h("p", { class: "lede" }, data.error));
  draw();
}

export function refresh() {}

function draw() {
  const steps = data.lanes.flatMap((lane) => lane.steps.map((s) => ({ ...s, lane: lane.label })));
  let at = 0;
  const detail = h("div", { class: "flow-detail" });
  const nodes = [];
  const showStep = (i, focus) => {
    at = Math.max(0, Math.min(steps.length - 1, i));
    nodes.forEach((n, k) => {
      n.classList.toggle("done", k < at);
      if (k === at) n.setAttribute("aria-current", "step");
      else n.removeAttribute("aria-current");
    });
    const s = steps[at];
    const prev = h("button", { class: "btn small ghost", type: "button", disabled: at === 0, onclick: () => showStep(at - 1) }, icon("arrow-left", 14), "Previous");
    const next = h("button", { class: "btn small ghost", type: "button", disabled: at === steps.length - 1, onclick: () => showStep(at + 1) }, "Next step", icon("arrow-right", 14));
    put(detail, h("div", { class: "step-panel" },
      h("div", { class: "panel-body", style: "padding:0" },
        h("div", { class: "seg-row" }, h("h3", null, s.title), h("span", { class: "chip" }, s.lane),
          s.claude ? h("span", { class: "chip busy" }, icon("sparkle", 12), s.claude) : h("span", { class: "chip ok" }, "Instant, no Claude run")),
        h("div", null, h("div", { class: "field-label" }, "What you do"), h("ol", { class: "list" }, s.do.map((d) => h("li", null, d)))),
        h("div", null, h("div", { class: "field-label" }, "What you get"), h("p", null, s.gives)),
        h("div", { class: "form-foot" }, h("button", { class: "btn primary", type: "button", onclick: () => go(s.href) }, icon(s.icon, 15),
          h("span", null, `Open ${s.where.split(",")[0]}`)), s.where.includes(",") ? h("span", { class: "soft" }, s.where) : null)),
      h("div", { class: "step-demo" }, h("span", { class: "demo-tag" }, "Where it happens"), h("b", null, s.where),
        shotOf(s.shot) ? picture(shotOf(s.shot)) : null)),
    h("div", { class: "seg-row", style: "margin-top:14px;justify-content:space-between" }, prev, next));
    if (focus) focusFirst(nodes[at]);
  };
  const lanes = h("div", { class: "lanes" }, data.lanes.map((lane) => h("div", { class: "lane" },
    h("div", { class: "lane-label" }, h("b", null, lane.label), h("span", null, lane.note)),
    h("div", { class: "lane-steps" }, lane.steps.map((s, i) => {
      const n = nodes.length;
      const node = h("button", { class: "flow-node", type: "button" }, h("span", { class: "num" }, String(n + 1)), h("span", null, s.title),
        s.optional ? h("span", { class: "opt" }, "optional") : null);
      node.addEventListener("click", () => showStep(n));
      node.addEventListener("keydown", (event) => {
        const step = ["ArrowRight", "ArrowDown"].includes(event.key) ? 1 : ["ArrowLeft", "ArrowUp"].includes(event.key) ? -1 : 0;
        if (!step) return;
        event.preventDefault();
        showStep(at + step, true);
      });
      nodes.push(node);
      return h("span", { class: "flow-step" }, i ? h("span", { class: "flow-arrow", "aria-hidden": "true" }) : null, node);
    })))));
  const n = data.numbers;
  put(box, h("div", { class: "page-width" },
    h("p", { class: "lede" }, "LinkedIn Studio turns what you know into LinkedIn posts. The routine has four rhythms: once, every week, every post and every day. Click a step to see what you do there."),
    h("nav", { class: "jump", "aria-label": "On this page" }, [["routine", "The routine"], ["working", "When Claude is working"],
      ["states", "A post’s four states"], ["try", "Try the editor"], ["screens", "Screen by screen"], ["numbers", "Keys and limits"]]
      .map(([id, label]) => h("a", { href: "#~guide", onclick: (event) => {
        event.preventDefault();
        box.querySelector(`#guide-${id}`).scrollIntoView({ block: "start" });
      } }, label))),
    h("section", { class: "panel", id: "guide-routine" }, h("header", { class: "panel-head" }, h("span", { class: "panel-mark" }, icon("activity", 17)),
      h("div", null, h("h2", null, "The routine"))), h("div", { class: "panel-body" }, lanes, detail)),
    working(),
    states(),
    sandbox(),
    h("section", { class: "panel", id: "guide-screens" }, h("header", { class: "panel-head" }, h("span", { class: "panel-mark" }, icon("eye", 17)),
      h("div", null, h("h2", null, "Screen by screen"))),
      h("div", { class: "panel-body grid cols-2" }, data.screens.map((s) => h("div", { class: "card" },
        shotOf(s.shot) ? picture(shotOf(s.shot)) : null,
        h("div", { class: "card-head" }, h("h3", null, icon(s.icon, 15), s.title)),
        h("div", { class: "card-body" }, h("p", { class: "soft" }, s.purpose), h("ul", { class: "list" }, s.points.map((p) => h("li", null, p))),
          h("div", null, h("button", { class: "btn small", type: "button", onclick: () => go(s.href) }, `Open ${s.title}`))))))),
    h("section", { class: "panel", id: "guide-numbers" }, h("header", { class: "panel-head" }, h("span", { class: "panel-mark" }, icon("target", 17)),
      h("div", null, h("h2", null, "Keys and limits"))),
      h("div", { class: "panel-body grid cols-2" },
        h("dl", { class: "facts" }, data.shortcuts.map(([keys, what]) => [h("dt", null, h("kbd", null, keys)), h("dd", null, what)])),
        h("dl", { class: "facts" },
          h("dt", null, "Posts a month"), h("dd", null, `${n.limit}, counted by ${n.tz} calendar month`),
          h("dt", null, "Post length"), h("dd", null, `${n.target_min} to ${n.target_max} characters reads best; ${n.post_max} is LinkedIn’s limit`),
          h("dt", null, "Before “more”"), h("dd", null, `about ${n.fold} characters`),
          h("dt", null, "Scheduling"), h("dd", null, `${n.min_lead} minutes to ${n.max_days} days ahead`),
          h("dt", null, "Claude"), h("dd", null, `one job at a time, up to ${n.timeout} seconds each (a post’s chat gets longer)`),
          h("dt", null, "Your files"), h("dd", null, `stay on this computer${data.private ? "; the Story Bank and voice profile are kept out of git" : ""}`))))));
  showStep(0);
  fitPractice();
}

function working() {
  const stages = [["sparkle", "You ask", "Plan the week, Draft this, Audit, any tool, or a message in a chat."],
    ["clock", "It waits its turn", "Claude does one job at a time. Others queue behind it."],
    ["book", "Claude works", "It loads the skill, reads your Story Bank and the skill’s files, then writes. Each step shows, numbered, with how long it has taken."],
    ["check-circle", "The result appears in place", "No reload. If you went elsewhere, a note in the corner links to it."]];
  return h("section", { class: "panel", id: "guide-working" }, h("header", { class: "panel-head" }, h("span", { class: "panel-mark" }, icon("clock", 17)),
    h("div", null, h("h2", null, "When Claude is working"), h("p", null, "Every button that runs Claude behaves the same way."))),
    h("div", { class: "panel-body" }, h("ol", { class: "stages" }, stages.map(([g, b, s]) => h("li", null, icon(g, 16), h("div", null, h("b", null, b), h("span", null, s))))),
      h("p", { class: "soft" }, `Cancel or Stop ends a job at once. A run that passes its time limit is stopped for you; Try again repeats it, and Carry on picks up a chat from where it stopped.`)));
}

function states() {
  const panel = h("div");
  const tabs = h("div", { class: "state-tabs", role: "tablist", "aria-label": "Post states" });
  const pick = (i, focus) => {
    [...tabs.children].forEach((t, k) => {
      t.setAttribute("aria-selected", String(k === i));
      t.tabIndex = k === i ? 0 : -1;
      t.classList.toggle("past", k < i);
      if (k === i && focus) t.focus();
    });
    const [name, meaning, can] = data.states[i];
    put(panel, h("div", { class: "state-panel", role: "tabpanel", "aria-label": name },
      h("div", null, h("h3", null, meaning), h("div", { class: "field-label", style: "margin-top:8px" }, "What you can do"),
        h("ul", { class: "list" }, can.map((c) => h("li", null, c))))));
  };
  data.states.forEach(([name], i) => {
    const tab = h("button", { class: "state-tab", type: "button", role: "tab" }, h("i"), h("span", null, name));
    tab.addEventListener("click", () => pick(i));
    tab.addEventListener("keydown", (event) => {
      const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
      if (!step) return;
      event.preventDefault();
      pick((i + step + data.states.length) % data.states.length, true);
    });
    tabs.append(tab);
  });
  pick(0);
  return h("section", { class: "panel", id: "guide-states" }, h("header", { class: "panel-head" }, h("span", { class: "panel-mark" }, icon("check", 17)),
    h("div", null, h("h2", null, "A post’s four states"), h("p", null, "The chip beside a post’s title says which."))),
    h("div", { class: "panel-body" }, tabs, panel,
      h("div", { class: "result soft" }, icon("info", 15), h("div", null, "If the request to Publora fails, the post shows Failed with Try again. Try again resends the very same request, so it cannot post twice."))));
}

function sandbox() {
  const ta = h("textarea", { class: "input area", rows: 9, "aria-label": "Practice post", spellcheck: "false" });
  ta.value = data.sample;
  const m = meter();
  const preview = h("p", { class: "li-text" });
  const blanks = h("span", { class: "soft" });
  const draw = () => {
    autosize(ta);
    m.update(ta.value);
    const fold = foldOf(ta.value);
    put(preview, withBlanks(fold.shown), fold.folded ? h("span", { class: "li-more" }, " …more") : null);
    const count = (ta.value.match(new RegExp(state.slot, "g")) || []).length;
    blanks.textContent = count ? `${count} blank${count === 1 ? "" : "s"} to fill` : "No blanks left";
  };
  ta.addEventListener("input", draw);
  fitPractice = () => autosize(ta);       // measured once it is in the page: detached, its text has no height
  const nextBlank = h("button", { class: "btn small", type: "button" }, "Next blank", icon("arrow-right", 14));
  nextBlank.addEventListener("click", () => {
    const re = new RegExp(state.slot, "g");
    re.lastIndex = ta.selectionEnd || 0;
    let found = re.exec(ta.value);
    if (!found) {
      re.lastIndex = 0;
      found = re.exec(ta.value);
    }
    if (!found) return;
    ta.focus();
    ta.setSelectionRange(found.index, found.index + found[0].length);
  });
  draw();
  return h("section", { class: "panel", id: "guide-try" }, h("header", { class: "panel-head" }, h("span", { class: "panel-mark" }, icon("pen", 17)),
    h("div", null, h("h2", null, "Try the editor"), h("p", null, "A sandbox: nothing you type here is saved."))),
    h("div", { class: "panel-body grid cols-2" },
      h("div", { class: "field" }, ta, m, h("div", { class: "form-foot" }, blanks, nextBlank)),
      h("div", { class: "li-card" }, h("div", { class: "li-head" }, h("span", { class: "li-avatar" }, "You"),
        h("span", { class: "li-who" }, h("b", null, "You"), h("span", null, "How it opens in the feed"))), h("div", { class: "li-body", style: "padding-bottom:14px" }, preview))));
}
