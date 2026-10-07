// The Guide page: a flowchart to click or play through, a pretend job, tabs and picture zoom.
// Runs after app.js, which provides window.studio.toast and the editor behind "Try the editor".
(function () {
  "use strict";

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const on = (target, type, fn) => target.addEventListener(type, fn);

  // ───────────────────────── the routine ─────────────────────────
  const flow = $("[data-flow]");
  if (flow) {
    const nodes = $$(".flow-node", flow);
    const panels = $$("[data-step-panel]", flow);
    const count = $("[data-flow-count]", flow);
    const playBtn = $("[data-flow-play]", flow);
    const playLabel = $("span", playBtn);
    const detail = $(".flow-detail", flow);
    const DWELL = 5000;  // ms on each step while playing
    const last = nodes.length - 1;
    let current = 0, playing = false, held = false, timer = null, startedAt = 0, remaining = DWELL;

    flow.style.setProperty("--dwell", DWELL + "ms");

    function show(i) {
      current = Math.max(0, Math.min(last, i));
      nodes.forEach((node, k) => {
        node.classList.toggle("on", k === current);
        node.classList.toggle("done", k < current);
        node.classList.remove("timing");
        if (k === current) node.setAttribute("aria-current", "step"); else node.removeAttribute("aria-current");
        const arrow = node.previousElementSibling;
        if (arrow && arrow.classList.contains("flow-arrow")) arrow.classList.toggle("done", k <= current);
      });
      const id = nodes[current].dataset.step;
      panels.forEach((panel) => panel.classList.toggle("on", panel.dataset.stepPanel === id));
      count.textContent = "Step " + (current + 1) + " of " + nodes.length;
      $("[data-flow-prev]", flow).disabled = current === 0;
      $("[data-flow-next]", flow).disabled = current === last;
      if (!playing) playLabel.textContent = current === last ? "Play again" : "Play it through";
    }

    // Playing: each step stays for DWELL, shown as a bar filling the step's pill. Pointing at
    // (or tabbing into) the detail holds it there, so nothing changes under what you are reading.
    function arm() {
      clearTimeout(timer);
      if (!playing || held) return;
      startedAt = performance.now();
      timer = setTimeout(() => {
        if (current === last) { stop(); return; }
        show(current + 1);
        mark();
        remaining = DWELL;
        arm();
      }, remaining);
    }

    function mark() {
      void nodes[current].offsetWidth;  // restart the fill animation on this step
      nodes[current].classList.add("timing");
    }

    function play() {
      if (current === last) show(0);
      playing = true;
      remaining = DWELL;
      flow.classList.add("playing");
      playBtn.setAttribute("aria-pressed", "true");
      playLabel.textContent = "Pause";
      mark();
      arm();
    }

    function stop() {
      clearTimeout(timer);
      playing = false;
      held = false;
      flow.classList.remove("playing", "held");
      nodes.forEach((node) => node.classList.remove("timing"));
      playBtn.setAttribute("aria-pressed", "false");
      playLabel.textContent = current === last ? "Play again" : "Play it through";
    }

    function hold(yes) {
      if (!playing || held === yes) return;
      held = yes;
      flow.classList.toggle("held", yes);
      if (yes) {
        clearTimeout(timer);
        remaining = Math.max(400, remaining - (performance.now() - startedAt));
      } else {
        arm();
      }
    }

    on(playBtn, "click", () => (playing ? stop() : play()));
    on(flow, "click", (ev) => {
      const node = ev.target.closest(".flow-node");
      if (node) { stop(); show(nodes.indexOf(node)); return; }
      if (ev.target.closest("[data-flow-prev]")) { stop(); show(current - 1); }
      if (ev.target.closest("[data-flow-next]")) { stop(); show(current + 1); }
    });
    on(flow, "keydown", (ev) => {
      if (!ev.target.classList || !ev.target.classList.contains("flow-node")) return;
      const step = ev.key === "ArrowRight" || ev.key === "ArrowDown" ? 1 : ev.key === "ArrowLeft" || ev.key === "ArrowUp" ? -1 : 0;
      if (!step) return;
      ev.preventDefault();
      stop();
      show(current + step);
      nodes[current].focus();
    });
    on(detail, "mouseenter", () => hold(true));
    on(detail, "mouseleave", () => hold(false));
    on(detail, "focusin", () => hold(true));
    on(detail, "focusout", () => hold(false));
    on(document, "visibilitychange", () => { if (document.hidden) stop(); });

    show(0);
  }

  // Progress text that keeps changing, as it does on a real job's card.
  $$("[data-cycle]").forEach((el) => {
    const texts = el.dataset.cycle.split("|");
    let i = 0;
    setInterval(() => { i = (i + 1) % texts.length; el.textContent = texts[i]; }, 1700);
  });

  // ───────────────────────── a pretend job ─────────────────────────
  const pretend = $("[data-pretend]");
  if (pretend) {
    const steps = pretend.dataset.steps.split("|");
    const out = $("[data-pretend-out]", pretend);
    const start = $("[data-pretend-start]", pretend);
    const stages = $$("[data-stage]", pretend);
    let timers = [], ticking = null;

    const later = (ms, fn) => timers.push(setTimeout(fn, ms));
    const put = (name) => out.replaceChildren($("template[data-pretend-" + name + "]", pretend).content.cloneNode(true));

    function stage(name) {
      const at = stages.findIndex((li) => li.dataset.stage === name);
      stages.forEach((li, k) => { li.classList.toggle("now", k === at); li.classList.toggle("past", at >= 0 && k < at); });
    }

    function finish(name, where) {
      timers.forEach(clearTimeout);
      timers = [];
      clearInterval(ticking);
      start.disabled = false;
      put(name);
      stage(where);
    }

    on(start, "click", () => {
      start.disabled = true;
      put("working");
      const text = $(".working-step", out), clock = $(".timer", out);
      const began = Date.now();
      ticking = setInterval(() => {
        const s = Math.floor((Date.now() - began) / 1000);
        clock.textContent = Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
      }, 250);
      stage("press");
      later(700, () => { stage("queue"); text.textContent = "Queued: waiting for the current job"; });
      steps.forEach((label, k) => later(2100 + k * 1100, () => { stage("work"); text.textContent = label; }));
      later(2100 + steps.length * 1100, () => finish("done", "done"));
    });

    on(pretend, "click", (ev) => {
      if (ev.target.closest("[data-pretend-cancel]")) finish("stopped", "");
      if (ev.target.closest("[data-pretend-toast]") && window.studio) {
        window.studio.toast("Your draft is ready (an example)", "ok", { href: "/drafts", label: "Open" });
      }
    });
  }

  // ───────────────────────── tabs ─────────────────────────
  $$("[data-tabs]").forEach((root) => {
    const tabs = $$("[data-tab]", root);
    const panels = $$("[data-tab-panel]", root);
    function pick(name) {
      tabs.forEach((tab) => {
        const yes = tab.dataset.tab === name;
        tab.classList.toggle("on", yes);
        tab.setAttribute("aria-selected", yes ? "true" : "false");
        tab.tabIndex = yes ? 0 : -1;
      });
      panels.forEach((panel) => panel.classList.toggle("on", panel.dataset.tabPanel === name));
    }
    on(root, "click", (ev) => {
      const tab = ev.target.closest("[data-tab]");
      if (tab) pick(tab.dataset.tab);
    });
    on(root, "keydown", (ev) => {
      const at = tabs.indexOf(ev.target);
      const step = ev.key === "ArrowRight" ? 1 : ev.key === "ArrowLeft" ? -1 : 0;
      if (at < 0 || !step) return;
      ev.preventDefault();
      const next = tabs[(at + step + tabs.length) % tabs.length];
      pick(next.dataset.tab);
      next.focus();
    });
    const first = tabs.find((tab) => tab.classList.contains("on")) || tabs[0];
    if (first) pick(first.dataset.tab);
  });

  // ───────────────────────── enlarge a picture ─────────────────────────
  const viewer = $("#shot-dialog");
  on(document, "click", (ev) => {
    const frame = ev.target.closest("[data-zoom]");
    if (!frame || !viewer) return;
    const shown = $$("img", frame).find((img) => img.offsetParent !== null) || $("img", frame);
    const big = $("img", viewer);
    big.src = shown.currentSrc || shown.src;
    big.alt = shown.alt;
    $("[data-role=caption]", viewer).textContent = frame.dataset.caption || "";
    viewer.showModal();
  });
})();
