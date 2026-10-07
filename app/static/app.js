// LinkedIn Studio front-end behaviour. Plain JS on top of htmx; no build step.
(function () {
  "use strict";

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const on = (target, type, fn) => target.addEventListener(type, fn);
  const store = {
    get(key, fallback) { try { return JSON.parse(sessionStorage.getItem(key)) ?? fallback; } catch (e) { return fallback; } },
    set(key, value) { try { sessionStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* ignore */ } },
  };

  // Icons are rendered once by the server into <template> tags, so JS and HTML share one set.
  function iconEl(name, size) {
    const tpl = document.getElementById("tpl-icon-" + name);
    const node = tpl ? tpl.content.firstElementChild.cloneNode(true) : document.createElement("span");
    if (tpl && size) { node.setAttribute("width", size); node.setAttribute("height", size); }
    return node;
  }

  // ───────────────────────── toasts ─────────────────────────
  function toast(text, kind, link) {
    const box = $("#toasts");
    if (!box || !text) return;
    const el = document.createElement("div");
    el.className = "toast " + (kind || "info");
    el.setAttribute("role", kind === "error" ? "alert" : "status");
    el.append(iconEl(kind === "ok" ? "check-circle" : kind === "error" ? "alert" : "info", 17));
    const span = document.createElement("span");
    span.textContent = text;
    el.append(span);
    if (link && link.href) {
      const a = document.createElement("a");
      a.href = link.href;
      a.textContent = link.label || "Open";
      el.append(a);
    }
    const close = document.createElement("button");
    close.type = "button";
    close.setAttribute("aria-label", "Dismiss");
    close.append(iconEl("x", 14));
    el.append(close);
    const remove = () => { el.classList.add("out"); setTimeout(() => el.remove(), 220); };
    on(close, "click", remove);
    box.append(el);
    setTimeout(remove, kind === "error" ? 9000 : link ? 10000 : 4200);
  }

  // ───────────────────────── dialogs ─────────────────────────
  on(document, "click", (ev) => {
    const opener = ev.target.closest("[data-open]");
    if (opener) {
      const dlg = document.getElementById(opener.dataset.open);
      if (dlg) { dlg.showModal(); const first = $("[autofocus], textarea, input:not([type=hidden])", dlg); if (first) first.focus(); }
      return;
    }
    if (ev.target.closest("[data-close]")) { ev.target.closest("dialog").close(); return; }
    if (ev.target instanceof HTMLDialogElement) ev.target.close();  // click on the backdrop
  });

  function confirmDialog(opts) {
    const dlg = $("#confirm-dialog");
    if (!dlg) return Promise.resolve(window.confirm(opts.text));
    $("[data-role=title]", dlg).textContent = opts.title || "Are you sure?";
    $("[data-role=text]", dlg).textContent = opts.text;
    const ok = $("[data-role=ok]", dlg);
    ok.textContent = opts.ok || "Continue";
    ok.className = "btn primary" + (opts.danger ? " danger" : "");
    return new Promise((resolve) => {
      let answer = false;
      const done = () => { ok.removeEventListener("click", yes); dlg.removeEventListener("close", done); resolve(answer); };
      const yes = () => { answer = true; dlg.close(); };
      on(ok, "click", yes);
      on(dlg, "close", done);
      dlg.showModal();
      ok.focus();
    });
  }

  // ───────────────────────── htmx wiring ─────────────────────────
  on(document.body, "toast", (ev) => toast(ev.detail.text, ev.detail.kind));

  on(document.body, "htmx:confirm", (ev) => {
    const question = ev.detail.question;
    if (!question) return;
    ev.preventDefault();
    const elt = ev.detail.elt;
    confirmDialog({ text: question, title: elt.dataset.confirmTitle, ok: elt.dataset.confirmOk, danger: "danger" in elt.dataset })
      .then((yes) => { if (yes) ev.detail.issueRequest(true); });
  });

  function errorText(xhr) {
    try {
      const body = JSON.parse(xhr.responseText);
      if (typeof body.error === "string") return body.error;
      if (typeof body.detail === "string") return body.detail;
    } catch (e) { /* not JSON */ }
    return "Something went wrong (" + xhr.status + ").";
  }

  on(document.body, "htmx:beforeRequest", (ev) => {
    const scope = ev.detail.elt.closest("[data-errors]");
    const slot = scope && $(".form-error", scope);
    if (slot) slot.hidden = true;
  });

  on(document.body, "htmx:responseError", (ev) => {
    const xhr = ev.detail.xhr;
    if (xhr.status === 401) { offline("This window belongs to an earlier session.", "Open LinkedIn Studio from its shortcut again."); return; }
    const msg = errorText(xhr);
    const scope = ev.detail.elt.closest("[data-errors]");
    const slot = scope && $(".form-error", scope);
    if (slot) { slot.textContent = msg; slot.hidden = false; } else toast(msg, "error");
  });

  on(document.body, "htmx:sendError", () => offline("LinkedIn Studio is not running.", "Start it again from the shortcut, then reload this window."));

  function offline(title, text) {
    if ($(".offline")) return;
    const wrap = document.createElement("div");
    wrap.className = "offline";
    const card = document.createElement("div");
    card.className = "card pad stopped";
    const h = document.createElement("h1"); h.textContent = title;
    const p = document.createElement("p"); p.className = "soft"; p.textContent = text;
    const btn = document.createElement("button"); btn.className = "btn"; btn.type = "button"; btn.textContent = "Reload";
    on(btn, "click", () => location.reload());
    card.append(h, p, btn);
    wrap.append(card);
    document.body.append(wrap);
  }

  // ───────────────────────── small things ─────────────────────────
  on(document, "click", (ev) => {
    const btn = ev.target.closest("[data-copy]");
    if (!btn) return;
    const src = document.getElementById(btn.dataset.copy);
    if (!src) return;
    const text = "value" in src ? src.value : src.textContent;
    navigator.clipboard.writeText(text).then(() => {
      const label = $("span", btn);
      const old = label ? label.textContent : "";
      btn.classList.add("copied");
      if (label) label.textContent = "Copied";
      setTimeout(() => { btn.classList.remove("copied"); if (label) label.textContent = old; }, 1400);
    }, () => toast("Could not copy. Select the text and press Ctrl+C.", "error"));
  });

  on(document, "click", (ev) => {
    if (ev.target.closest("#theme-toggle")) {
      window.studioTheme.set(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
      syncThemeChoice();
    }
    const choice = ev.target.closest("[data-theme-choice]");
    if (choice) { window.studioTheme.set(choice.dataset.themeChoice); syncThemeChoice(); }
  });
  function syncThemeChoice() {
    const current = document.documentElement.dataset.themePref;
    $$("[data-theme-choice]").forEach((b) => b.classList.toggle("on", b.dataset.themeChoice === current));
  }

  const topbar = $(".topbar");
  if (topbar) {
    const mark = () => topbar.classList.toggle("scrolled", window.scrollY > 4);
    on(window, "scroll", mark);
    mark();
  }

  function tickTimers() {
    $$("[data-since]").forEach((el) => {
      const started = Date.parse(el.dataset.since);
      if (!started) return;
      const s = Math.max(0, Math.floor((Date.now() - started) / 1000));
      el.textContent = Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
    });
  }
  setInterval(tickTimers, 1000);

  function autosize(ta) {
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, parseInt(ta.dataset.maxHeight || "100000", 10)) + 2 + "px";
  }
  on(document, "input", (ev) => {
    if (ev.target.matches("textarea[data-autosize]")) autosize(ev.target);
    if (ev.target.matches("[data-persist]")) store.set("persist:" + ev.target.dataset.persist, ev.target.value);
  });

  on(document, "keydown", (ev) => {
    const mod = ev.ctrlKey || ev.metaKey;
    if (ev.key === "Enter" && !ev.shiftKey && !mod && !ev.isComposing && ev.target.matches && ev.target.matches("textarea[data-enter-send]")) {
      ev.preventDefault();
      ev.target.form.requestSubmit();
      return;
    }
    if (mod && ev.key === "Enter") {
      const form = ev.target.closest && ev.target.closest("form");
      if (form && !form.id.startsWith("draft-form")) { ev.preventDefault(); form.requestSubmit(); }
      return;
    }
    if (mod && ev.key.toLowerCase() === "s") {
      const form = $("#draft-form[hx-post]");
      if (form) { ev.preventDefault(); window.htmx.trigger(form, "save-now"); }
    }
  });

  // ───────────────────────── job activity ─────────────────────────
  // The pill in the top bar polls /jobs/active. When a job id drops out of it, the job
  // ended; say so with a toast unless this page is already showing that job's result.
  const shownHere = new Set();
  const noteJobs = () => $$("[data-job]").forEach((el) => shownHere.add(el.dataset.job));

  function activityChanged() {
    noteJobs();
    const pill = $("#activity .activity");
    const now = pill && pill.dataset.ids ? pill.dataset.ids.split(",") : [];
    const before = store.get("active-jobs", []);
    store.set("active-jobs", now);
    before.filter((id) => !now.includes(id)).forEach(announce);
  }

  function announce(id) {
    fetch("/jobs/" + id + "/summary", { credentials: "same-origin" })
      .then((r) => (r.ok ? r.json() : null))
      .then((s) => {
        if (!s || !s.job) return;
        // Second path for "this job ended": the job's own card normally says so, but if that
        // signal is lost the regions would sit stale. Regions ignore a refresh that changes nothing.
        window.htmx.trigger(document.body, "jobs-changed", { id: +id, kind: s.job, status: s.status });
        if (s.silent) return;
        const draftReady = s.job === "draft" && s.kind === "ok";
        if (shownHere.has(String(id)) && !draftReady) return;
        if (location.pathname + location.search === s.href) return;
        toast(s.text, s.kind, { href: s.href, label: "Open" });
      })
      .catch(() => { /* the poll will notice if the server is gone */ });
  }

  // A region ([data-region]) re-fetches itself on jobs-changed. If the HTML it gets back is
  // what it already shows, leave the DOM alone: no flicker, no replayed animation.
  // Progress text inside a running job's card changes every second and is filled by its own
  // poll, so it does not count as a change.
  const lastHtml = new Map();
  const comparable = (html) => html.replace(/(hx-get="\/jobs\/\d+\/tick"[^>]*>)[^<]*/g, "$1");
  on(document.body, "htmx:beforeSwap", (ev) => {
    const target = ev.detail.target;
    if (!target || !target.id || !target.hasAttribute("data-region") || ev.detail.xhr.status !== 200) return;
    const html = comparable(ev.detail.serverResponse);
    if (lastHtml.get(target.id) === html) { ev.detail.shouldSwap = false; return; }
    lastHtml.set(target.id, html);
  });

  // ───────────────────────── draft editor ─────────────────────────
  function initEditor() {
    const ta = $("#post-text");
    const form = $("#draft-form");
    if (!ta || !form || ta.dataset.ready) return;
    ta.dataset.ready = "1";
    const meter = $("#meter");
    const min = +meter.dataset.min, max = +meter.dataset.max, hard = +meter.dataset.hard, fold = +meter.dataset.fold;
    const scale = 2000;
    const slotRe = new RegExp(form.dataset.slotRe, "g");
    const zone = $(".meter-zone", meter), thumb = $(".meter-thumb", meter), mtext = $(".meter-text", meter);
    const slotBox = $("#slot-box"), slotCount = $("#slot-count");
    const feed = $("#feed-text");
    const saveState = $("#save-state");
    const editable = form.hasAttribute("hx-post");
    let editSeq = 0, sentSeq = 0, dirty = false, expanded = false;
    zone.style.left = (min / scale) * 100 + "%";
    zone.style.width = ((max - min) / scale) * 100 + "%";
    const fmt = (n) => n.toLocaleString("en-IN");

    function refresh() {
      autosize(ta);
      const text = ta.value;
      const n = Array.from(text).length;
      const state = n > hard ? "over" : n > max ? "long" : n >= min ? "good" : "short";
      meter.dataset.state = state;
      thumb.style.left = (Math.min(n, scale) / scale) * 100 + "%";
      const tail = state === "good" ? "in the " + fmt(min) + "–" + fmt(max) + " sweet spot"
        : state === "short" ? (n ? fmt(min - n) + " short of the sweet spot" : "aim for " + fmt(min) + "–" + fmt(max))
        : state === "long" ? fmt(n - max) + " past the sweet spot, still fine"
        : fmt(n - hard) + " over LinkedIn's " + fmt(hard) + " limit";
      mtext.replaceChildren();
      const b = document.createElement("b");
      b.textContent = fmt(n);
      mtext.append(b, " characters · " + tail);
      const slots = text.match(slotRe) || [];
      if (slotBox) { slotBox.hidden = !slots.length; slotCount.textContent = slots.length + (slots.length === 1 ? " blank to fill" : " blanks to fill"); }
      renderFeed(text);
    }

    function renderFeed(text) {
      if (!feed) return;
      const trimmed = text.trim();
      feed.replaceChildren();
      feed.classList.toggle("empty-text", !trimmed);
      if (!trimmed) { feed.textContent = "Your post will preview here as you write."; return; }
      const lines = trimmed.split("\n").slice(0, 3).join("\n");
      const cut = Array.from(lines).slice(0, fold).join("");
      const folded = cut.length < trimmed.length;
      feed.append(expanded || !folded ? trimmed : cut.trimEnd());
      if (folded) {
        const more = document.createElement("span");
        more.className = "more";
        more.textContent = expanded ? "  show less" : " …more";
        on(more, "click", () => { expanded = !expanded; renderFeed(ta.value); });
        feed.append(more);
      }
    }

    function setSave(mode, at) {
      if (!saveState) return;
      saveState.className = "save-state" + (mode === "saving" ? " saving" : "");
      saveState.textContent = mode === "saving" ? "Saving…" : mode === "dirty" ? "Unsaved changes" : at ? "Saved " + at : saveState.textContent;
    }

    on(ta, "input", refresh);
    on(form, "submit", (ev) => ev.preventDefault());  // Enter in the title must not submit the page
    if (editable) {
      on(form, "input", () => { editSeq += 1; dirty = true; setSave("dirty"); });
      on(form, "htmx:beforeRequest", (ev) => { if (ev.target === form) { sentSeq = editSeq; setSave("saving"); } });
      on(document.body, "saved", (ev) => { if (sentSeq === editSeq) dirty = false; setSave(dirty ? "dirty" : "saved", ev.detail.at); });
      // Approve, "use this revision" and delete answer with a redirect after the server has
      // already stored (or replaced) the text. A parting save would then overwrite it.
      on(document.body, "htmx:beforeOnLoad", (ev) => {
        if (ev.detail.xhr.getResponseHeader("HX-Redirect")) dirty = false;
      });
      on(window, "pagehide", () => {
        if (dirty) navigator.sendBeacon(form.getAttribute("hx-post"), new URLSearchParams(new FormData(form)));
      });
    }

    const next = $("#slot-next");
    if (next) on(next, "click", () => {
      const text = ta.value;
      slotRe.lastIndex = ta.selectionEnd || 0;
      let m = slotRe.exec(text);
      if (!m) { slotRe.lastIndex = 0; m = slotRe.exec(text); }
      if (!m) return;
      ta.focus({ preventScroll: true });
      ta.setSelectionRange(m.index, m.index + m[0].length);
      const y = caretY(ta, m.index);
      window.scrollTo({ top: ta.getBoundingClientRect().top + window.scrollY + y - window.innerHeight / 3, behavior: "smooth" });
    });
    refresh();
  }

  // Where (in px from the textarea's top) the character at `index` sits, via an off-screen mirror.
  function caretY(ta, index) {
    const cs = getComputedStyle(ta);
    const mirror = document.createElement("div");
    ["fontFamily", "fontSize", "fontWeight", "lineHeight", "letterSpacing", "paddingTop", "paddingRight", "paddingBottom",
      "paddingLeft", "boxSizing", "tabSize"].forEach((p) => { mirror.style[p] = cs[p]; });
    Object.assign(mirror.style, { position: "absolute", left: "-9999px", top: "0", visibility: "hidden",
      whiteSpace: "pre-wrap", overflowWrap: "anywhere", width: ta.clientWidth + "px" });
    mirror.textContent = ta.value.slice(0, index);
    const mark = document.createElement("span");
    mark.textContent = "x";
    mirror.append(mark);
    document.body.append(mirror);
    const y = mark.offsetTop;
    mirror.remove();
    return y;
  }

  // Schedule: quick picks fill the time; the confirmation dialog repeats it in words.
  on(document, "click", (ev) => {
    const pick = ev.target.closest(".pick[data-when]");
    if (pick) {
      const input = $("#when");
      input.value = pick.dataset.when;
      $$(".pick[data-when]").forEach((p) => p.classList.toggle("on", p === pick));
      return;
    }
    if (ev.target.closest("#schedule-open")) {
      const input = $("#when");
      const value = input.value;
      const scope = ev.target.closest("[data-errors]");
      const slot = scope && $(".form-error", scope);
      const complain = (text) => { if (slot) { slot.textContent = text; slot.hidden = false; } input.focus(); };
      if (!value) { complain("Pick a date and time first."); return; }
      if (!input.checkValidity()) { complain("Pick a time between 2 minutes and 14 days from now."); return; }
      if (slot) slot.hidden = true;
      const [d, t] = value.split("T");
      const [y, mo, da] = d.split("-").map(Number);
      const [h, mi] = t.split(":").map(Number);
      const when = new Date(y, mo - 1, da, h, mi);  // wall-clock digits only; the server reads them as the app's zone
      $("#confirm-when").textContent = when.toLocaleString("en-IN", { weekday: "long", day: "numeric", month: "long",
        hour: "numeric", minute: "2-digit", hour12: true });
      const dlg = $("#schedule-dialog");
      const err = $(".form-error", dlg);
      if (err) err.hidden = true;
      dlg.showModal();
    }
  });
  on(document, "input", (ev) => { if (ev.target.id === "when") $$(".pick[data-when]").forEach((p) => p.classList.remove("on")); });

  // A segmented control that fills a hidden field: <div class="seg" data-input="name"><button data-value>.
  on(document, "click", (ev) => {
    const option = ev.target.closest(".seg[data-input] > [data-value]");
    if (!option) return;
    const seg = option.parentElement;
    $$("[data-value]", seg).forEach((b) => b.classList.toggle("on", b === option));
    const field = seg.closest("form").elements[seg.dataset.input];
    if (field) field.value = option.dataset.value;
  });

  // ───────────────────────── folders (setup screen) ─────────────────────────
  // A place the app found fills its box. Browse asks the app to open a Windows file window,
  // because a web page cannot learn a folder's real path by itself.
  on(document, "click", (ev) => {
    const found = ev.target.closest("[data-fill]");
    if (found) {
      const box = $("input", found.closest("[data-path-field]"));
      box.value = found.dataset.fill;
      $$(".pick", found.parentElement).forEach((p) => p.classList.toggle("on", p === found));
      return;
    }
    const browse = ev.target.closest("[data-browse]");
    if (!browse) return;
    const field = browse.closest("[data-path-field]");
    const box = $("input", field);
    browse.disabled = true;
    fetch("/setup/browse", { method: "POST", credentials: "same-origin",
      body: new URLSearchParams({ field: field.dataset.pathField, start: box.value }) })
      .then((r) => r.json().then((body) => ({ ok: r.ok, body })))
      .then((res) => {
        if (!res.ok) { toast(res.body.error || "Could not open the file window.", "error"); return; }
        if (!res.body.path) return;   // closed without choosing
        box.value = res.body.path;
        $$(".pick", field).forEach((p) => p.classList.toggle("on", p.dataset.fill === box.value));
      })
      .catch(() => toast("Could not open the file window. Type or paste the path instead.", "error"))
      .finally(() => { browse.disabled = false; });
  });

  // ───────────────────────── tools ─────────────────────────
  on(document, "click", (ev) => {
    const tab = ev.target.closest(".tooltab[data-tool]");
    if (!tab) return;
    const tool = tab.dataset.tool;
    $$(".tooltab").forEach((t) => { t.classList.toggle("on", t === tab); t.setAttribute("aria-selected", t === tab); });
    $$("[data-pane]").forEach((p) => { p.hidden = p.dataset.pane !== tool; });
    history.replaceState(null, "", "/tools?tool=" + tool);
    const first = $("[data-pane='" + tool + "'] textarea");
    if (first) first.focus({ preventScroll: true });
  });

  // ───────────────────────── interviewer ─────────────────────────
  function threadReady(fromSend) {
    const thread = $("#thread");
    if (!thread) return;
    thread.scrollTop = thread.scrollHeight;
    const busy = thread.dataset.busy === "1";
    const send = $("#chat-send"), box = $("#chat-text");
    if (send) send.disabled = busy;
    if (box) {
      box.placeholder = thread.dataset.placeholder || "";
      if (fromSend) { box.value = ""; autosize(box); }
      if (!busy) box.focus({ preventScroll: true });
    }
    const idField = $("#conv-id");
    if (idField && thread.dataset.conv) idField.value = thread.dataset.conv;
  }
  on(document.body, "htmx:afterRequest", (ev) => {
    if (ev.detail.elt.id === "composer" && ev.detail.successful) threadReady(true);
  });

  // ───────────────────────── init ─────────────────────────
  function init(root) {
    $$("textarea[data-autosize]", root).forEach(autosize);
    $$("[data-persist]", root).forEach((el) => {
      const saved = store.get("persist:" + el.dataset.persist, "");
      if (!el.value && saved) el.value = saved;
    });
    tickTimers();
    noteJobs();
  }

  on(document.body, "htmx:afterSettle", (ev) => {
    const el = ev.target;
    if (el.id === "activity") { activityChanged(); return; }
    init(el.parentElement || document);
    if (el.id === "thread") threadReady(false);
  });

  on(document, "change", (ev) => {
    if (ev.target.matches("select[data-nav-select]")) location.href = ev.target.value;
  });

  window.studio = { toast: toast };  // for page scripts such as guide.js

  init(document);
  initEditor();
  threadReady(false);
  syncThemeChoice();
  if (location.hash === "#write" && $("#write-dialog")) {
    $("#write-dialog").showModal();
    history.replaceState(null, "", location.pathname + location.search);
  }

  const flash = document.body.dataset;
  if (flash.flashText) {
    toast(flash.flashText, flash.flashKind);
    const url = new URL(location.href);
    url.searchParams.delete("done");
    history.replaceState(null, "", url.pathname + url.search + url.hash);
  }
})();
