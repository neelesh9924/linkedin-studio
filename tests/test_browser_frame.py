"""The page's frame, in Chrome (headless, through Playwright) on the demo studio with its stand-ins (dev/demo_server.py in a
folder of its own: no Claude, Publora or ChatGPT). Skipped without Playwright or without Chrome or Edge.

The posts' tabs (every status in exactly one; each tab's list in the studio's order; the sidebar counting nothing; Ctrl+K
opening a published post, its tab marked and Back to it; Alt+↑/↓ within the open post's tab; a post that did not go out
first in Scheduled and named across the top of every page); Ask Claude's edge (its keys, kept across a reload, the
toasts following it, kept clear of the post at 941 px); Before you confirm (js/precheck.js, on made-up posts); the status
line while Claude works and Approved's own colour."""
import json
import re
import socket
import subprocess
import sys
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from launch import find_browser  # noqa: E402

pytestmark = pytest.mark.skipif(not find_browser(""), reason="needs Chrome or Edge")

# The sidebar's words, all of them (its buttons' names and titles too): navigation only, so not one figure (the owner's
# rule, 19 Nov 2026: no counts in a menu; the count once beside Posts went with the posts).
SIDE_WORDS = """() => {
  const side = document.querySelector('.sidebar');
  return side.textContent + ' ' + [...side.querySelectorAll('[aria-label], [title]')]
    .map((el) => `${el.getAttribute('aria-label') || ''} ${el.getAttribute('title') || ''}`).join(' ');
}"""
POSTS = "() => import(document.querySelector('meta[name=studio-static]').content + 'js/core.js').then((m) => m.state.posts.map((p) => ({ id: p.id, status: p.status })))"
ROWS = "() => [...document.querySelectorAll('#postList .post-row')].map((b) => Number(b.dataset.post))"
WIDTH = "() => Math.round(document.getElementById('assist').getBoundingClientRect().width)"


@pytest.fixture(scope="module")
def studio(tmp_path_factory):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    folder = tmp_path_factory.mktemp("frame")
    server = subprocess.Popen([sys.executable, str(ROOT / "dev" / "demo_server.py"), "--port", str(port), "--folder", str(folder)],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    info = json.loads(server.stdout.readline())
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome" if "chrome" in find_browser("").lower() else "msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.set_default_timeout(20000)
        page.goto(info["url"])
        page.wait_for_selector("#postList .post-row")
        yield page, errors
        browser.close()
    server.terminate()
    server.wait(timeout=20)


def show_tab(page, tab):
    page.click(f"#tab-{tab}")
    page.wait_for_function("(t) => location.hash === `#~posts-${t}` && !document.getElementById('postsPage').hidden"
                           " && (document.getElementById('posts-title') || {}).textContent === t[0].toUpperCase() + t.slice(1)", arg=tab)   # drawn on the hashchange, after the address changes


def open_draft(page) -> int:
    show_tab(page, "drafts")
    button = page.locator("#postList .post-row", has_text="14 March").first
    draft = int(button.get_attribute("data-post"))
    button.click()
    page.wait_for_function(f"() => location.hash === '#post-{draft}'")
    page.wait_for_selector('#topActions [data-act="approve"]')     # drawn: the page held the post before it till then
    page.wait_for_selector(".li-read")
    return draft


def reload(page):
    page.reload()
    page.wait_for_selector("#tab-drafts")
    page.wait_for_function("() => document.getElementById('title').textContent !== ''")


# Where each status goes (posts.js tabOf, the one definition): every status in exactly one tab.
TAB_OF = """async () => {
  const { tabOf, TABS } = await import(document.querySelector('meta[name=studio-static]').content + 'js/posts.js');
  const posts = [['draft'], ['approved'], ['approved', true], ['scheduling'], ['scheduled'], ['failed'], ['published'], ['cancelled']];
  return { tabs: Object.fromEntries(posts.map(([status, queued]) => [`${status}${queued ? ' queued' : ''}`, tabOf({ status, queued: !!queued })])),
           statuses: TABS.flatMap((t) => t.statuses) };
}"""


def test_every_status_is_in_one_tab_and_each_tab_lists_its_posts_in_the_studios_order(studio):
    page, errors = studio
    out = page.evaluate(TAB_OF)
    assert out["tabs"] == {"draft": "drafts", "approved": "approved", "approved queued": "scheduled", "scheduling": "scheduled",
                           "scheduled": "scheduled", "failed": "scheduled", "published": "published", "cancelled": "published"}
    assert sorted(out["statuses"]) == sorted(set(out["statuses"]))               # no status in two tabs
    for title in ("Feature flags are cheap to add and expensive to forget.", "A retry without a limit is an outage waiting for a reason."):
        made = page.evaluate("fetch('/api/posts/new', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }).then((r) => r.json())")
        page.evaluate("([id, text]) => fetch(`/api/post/${id}/save`, { method: 'POST', headers: { 'Content-Type': 'application/json' },"
                      " body: JSON.stringify({ text }) })", [made["id"], f"{title}\n\nA made-up draft for the list's order."])
        page.evaluate("([id, rank]) => fetch(`/api/post/${id}/rank`, { method: 'POST', headers: { 'Content-Type': 'application/json' },"
                      " body: JSON.stringify({ rank }) })", [made["id"], 9 if "flags" in title else 5])
    show_tab(page, "drafts")
    page.wait_for_function("() => [...document.querySelectorAll('#postList .rank')].map((r) => r.textContent).join() === '–,9,5'")
    posts = page.evaluate(POSTS)
    for tab, statuses in (("drafts", {"draft"}), ("approved", {"approved"}), ("scheduled", {"scheduled"}), ("published", {"published"})):
        show_tab(page, tab)
        page.wait_for_function(f"() => document.querySelectorAll('#postList .post-row').length === {sum(p['status'] in statuses for p in posts)}")
        assert page.evaluate(ROWS) == [p["id"] for p in posts if p["status"] in statuses], tab    # the studio's order, as sent
    show_tab(page, "drafts")
    firsts = page.locator("#postList .post-first").all_inner_texts()        # the one not ranked yet on top, then the best
    assert firsts[0].startswith("On 14 March") and firsts[1].startswith("Feature flags") and firsts[2].startswith("A retry")
    assert [t.strip() for t in page.locator("#postList .rank").all_inner_texts()] == ["–", "9", "5"]
    assert page.locator("#postList .rank").nth(1).get_attribute("class") == "rank post"
    assert page.locator("#postList .rank").nth(2).get_attribute("class") == "rank strengthen"
    assert errors == []


def test_each_tab_says_how_many_on_its_page_and_the_sidebar_counts_nothing(studio):
    page, errors = studio
    for tab, said in (("drafts", "3 drafts, best first"), ("approved", "1 approved post, waiting for you to queue or schedule it."),
                      ("scheduled", "1 scheduled at Publora, in green: soonest first."), ("published", "1 published on LinkedIn, the most recent first.")):
        show_tab(page, tab)
        assert page.locator("#posts-said").inner_text().startswith(said), tab
        assert page.locator(f"#tab-{tab}").get_attribute("aria-current") == "page"
        assert page.locator("#views [aria-current]").count() == 1
        assert not re.search(r"\d", page.evaluate(SIDE_WORDS)), tab          # not one figure in the frame
    open_draft(page)
    assert not re.search(r"\d", page.evaluate(SIDE_WORDS))
    assert errors == []


def test_ctrl_k_opens_a_published_post_its_tab_is_marked_and_back_returns_to_it(studio):
    page, errors = studio
    open_draft(page)
    page.keyboard.press("Control+K")
    page.locator("dialog[open] .palette-input").wait_for()
    page.keyboard.type("Three years ago")
    page.keyboard.press("Enter")
    page.wait_for_function("() => document.getElementById('title').textContent === 'Three years of Rust'")
    here = page.evaluate("location.hash.replace('#post-', '')")
    assert page.locator("#tab-published").get_attribute("aria-current") == "true"
    assert page.locator("#tab-drafts").get_attribute("aria-current") is None
    assert page.locator("#backTo").get_attribute("aria-label") == "Back to Published"
    page.click("#backTo")
    page.wait_for_function(f"() => location.hash === '#~posts-published' && document.activeElement.dataset.post === '{here}'")
    assert page.locator("#tab-published").get_attribute("aria-current") == "page" and page.locator("#title").inner_text() == "Published"
    assert errors == []


def test_a_post_that_is_gone_or_an_address_not_known_shows_drafts_at_its_own_address(studio):
    page, errors = studio
    for mark in ("#post-99999", "#~nowhere"):
        page.evaluate("(m) => { location.hash = m; }", mark)
        page.wait_for_function("() => location.hash === '#~posts-drafts' && document.getElementById('title').textContent === 'Drafts'")
        assert page.locator("#tab-drafts").get_attribute("aria-current") == "page"
    assert errors == []


def test_alt_arrows_walk_the_posts_of_the_open_posts_tab(studio):
    page, errors = studio
    open_draft(page)
    drafts = [str(p["id"]) for p in page.evaluate(POSTS) if p["status"] == "draft"]
    assert len(drafts) == 3
    # The page's own state, read as it polls: the next press waits until the post the address names is open, since the
    # browser takes a key press ahead of the hashchange that opens it (a press can come before the page has moved on)
    page.evaluate("async () => { window.coreForTest = await import(document.querySelector('meta[name=studio-static]').content + 'js/core.js'); }")
    opened = "window.coreForTest.state.postId === Number(location.hash.replace('#post-', ''))"
    seen = []
    for _ in drafts:
        before = page.evaluate("location.hash")
        page.keyboard.press("Alt+ArrowDown")
        page.wait_for_function(f"() => location.hash !== '{before}' && {opened} && document.getElementById('tab-drafts').getAttribute('aria-current') === 'true'")
        seen.append(page.evaluate("location.hash.replace('#post-', '')"))
    assert sorted(seen) == sorted(drafts) and seen[-1] == drafts[0]           # round the tab, back to the first: drafts only
    page.keyboard.press("Alt+ArrowUp")
    page.wait_for_function(f"() => location.hash === '#post-{drafts[-1]}' && {opened}")
    show_tab(page, "approved")                                                 # alone in its tab: it stays, and says so
    page.locator("#postList .post-row").first.click()
    page.wait_for_function("() => document.querySelector('#status').innerText.includes('Approved')")
    approved = page.evaluate("location.hash")
    page.keyboard.press("Alt+ArrowDown")
    page.wait_for_function("() => document.getElementById('announce').textContent === 'It is the only post under Approved.'")
    assert page.evaluate("location.hash") == approved
    assert errors == []


# A post that did not go out, as the list and the banner show it: made up in the page's own state, drawn, read and taken
# back before the next poll (the demo's stand-in Publora never fails).
FAILED = """async () => {
  const at = document.querySelector('meta[name=studio-static]').content;
  const { state } = await import(at + 'js/core.js');
  const posts = await import(at + 'js/posts.js');
  const kept = state.posts;
  state.posts = [{ id: 9900, title: 'Release notes', first: 'Nobody reads release notes. Here is how we made ours worth a click.',
    status: 'failed', label: 'Failed', kind: 'bad', when: '', queued: false, busy: false, rank: null }, ...kept];   // as the studio orders it
  posts.warnFailed();
  posts.refresh();
  const note = document.querySelector('#banners [data-banner="failed"]');
  const row = document.querySelector('#postList .post-row');
  const out = { banner: note ? note.innerText : '', bad: note ? note.classList.contains('bad') : false,
    first: row ? [row.dataset.post, row.classList.contains('failed'), row.querySelector('.post-where').innerText] : null,
    said: document.getElementById('posts-said').innerText };
  state.posts = kept;
  posts.warnFailed();
  posts.refresh();
  out.gone = !document.querySelector('#banners [data-banner="failed"]');
  return out;
}"""


def test_a_post_that_did_not_go_out_comes_first_in_scheduled_and_is_named_across_the_top(studio):
    page, errors = studio
    show_tab(page, "scheduled")
    out = page.evaluate(FAILED)
    assert out["banner"].startswith("A post did not go out.") and "Nobody reads release notes" in out["banner"] and out["bad"]
    assert "Open it" in out["banner"]
    assert out["first"] == ["9900", True, "Failed"]                            # first, in red, ahead of the scheduled one
    assert out["said"].startswith("1 did not go out: it comes first, in red.")
    assert out["gone"]                                                         # dealt with: the banner goes
    assert errors == []


# What goes out and what went out, as their tabs show them: made up in the page's own state (in the studio's order, as
# /api/state sends it), drawn, read and taken back before the next poll. Each row says its date, and a post at Publora
# and a queued one are told apart by their colour (the owner's word, 20 Nov 2026).
DATED = """async () => {
  const at = document.querySelector('meta[name=studio-static]').content;
  const { state } = await import(at + 'js/core.js');
  const posts = await import(at + 'js/posts.js');
  const kept = state.posts;
  const made = (id, status, label, kind, when, queued) => ({ id, title: 'Made up', first: `A made-up post, number ${id}.`,
    status, label, kind, when, queued, busy: false, rank: null });
  state.posts = [made(9911, 'scheduled', 'Scheduled', 'ok', 'Tue 24 Nov, 8:00 am IST', false),
    made(9912, 'approved', 'Queued', 'queued', 'Thu 26 Nov, 8:00 am IST', true),
    made(9913, 'published', 'Published', 'ok', 'Wed 18 Nov, 8:00 am IST', false),
    made(9914, 'cancelled', 'Cancelled', 'warn', 'Thu 12 Nov, 8:00 am IST', false), ...kept];
  posts.refresh();
  const rows = [...document.querySelectorAll('#postList .post-row')].filter((r) => Number(r.dataset.post) > 9900).map((r) => {
    const where = r.querySelector('.post-where');
    return [Number(r.dataset.post), where.className, where.innerText.trim(), getComputedStyle(where).color];
  });
  const said = document.getElementById('posts-said').innerText;
  state.posts = kept;
  posts.refresh();
  const colourOf = (token) => {   // a token's colour as the page computes it
    const probe = document.body.appendChild(Object.assign(document.createElement('span'), { style: `color: var(${token})` }));
    const colour = getComputedStyle(probe).color;
    probe.remove();
    return colour;
  };
  return { rows, said, ok: colourOf('--ok'), queue: colourOf('--queue'), warn: colourOf('--warn') };
}"""


def test_scheduled_and_published_give_each_posts_date_and_tell_a_queued_post_by_its_colour(studio):
    page, errors = studio
    show_tab(page, "scheduled")
    out = page.evaluate(DATED)
    one, two = out["rows"]
    assert one == [9911, "post-where ok", "Scheduled · Tue 24 Nov, 8:00 am", out["ok"]]       # green
    assert two == [9912, "post-where queued", "Queued · Thu 26 Nov, 8:00 am", out["queue"]]   # blue
    assert out["ok"] != out["queue"]                          # told apart by their colour, not by their words alone
    assert "scheduled at Publora, in green, and 1 queued, in blue: soonest first." in out["said"]
    show_tab(page, "published")
    out = page.evaluate(DATED)
    assert out["rows"] == [[9913, "post-where ok", "Published · Wed 18 Nov, 8:00 am", out["ok"]],
                           [9914, "post-where warn", "Cancelled · was due Thu 12 Nov, 8:00 am", out["warn"]]]
    assert errors == []


def test_the_panel_edge_widens_with_its_keys_and_is_kept_across_a_reload(studio):
    page, errors = studio
    open_draft(page)
    edge = page.locator("#assistResize")
    assert [edge.get_attribute(a) for a in ("role", "tabindex", "aria-orientation", "aria-controls", "aria-label")] == \
        ["separator", "0", "vertical", "assist", "Resize the Ask Claude panel"]
    start = int(edge.get_attribute("aria-valuenow"))
    assert start == page.evaluate(WIDTH) == 388 and edge.get_attribute("aria-valuemin") == "320"
    edge.focus()
    page.keyboard.press("ArrowLeft")
    assert int(edge.get_attribute("aria-valuenow")) == page.evaluate(WIDTH) == start + 16
    assert edge.get_attribute("aria-valuetext") == f"{start + 16} pixels wide"
    page.keyboard.press("Shift+ArrowLeft")
    page.keyboard.press("ArrowRight")
    assert int(edge.get_attribute("aria-valuenow")) == start + 64
    toasts = page.evaluate("getComputedStyle(document.getElementById('toasts')).maxWidth")
    assert toasts == f"{1440 - 244 - (start + 64) - 36}px"                     # the toasts keep clear of it
    reload(page)
    open_draft(page)
    assert int(page.locator("#assistResize").get_attribute("aria-valuenow")) == page.evaluate(WIDTH) == start + 64
    page.locator("#assistResize").dblclick()                                   # back to the layout's own width
    assert page.evaluate(WIDTH) == start and page.evaluate("localStorage.getItem('assistWidth')") is None
    assert errors == []


def test_at_941_px_three_columns_hold_and_the_panel_stops_at_its_maximum(studio):
    page, errors = studio
    try:
        open_draft(page)
        page.locator("#assistResize").focus()
        page.keyboard.press("End")                                             # as wide as it goes at 1440 px
        assert page.evaluate(WIDTH) == 720
        page.set_viewport_size({"width": 941, "height": 800})
        page.wait_for_function(f"() => ({WIDTH})() === 320")                   # the width kept, held to the room there
        edge = page.locator("#assistResize")
        where = page.evaluate("""() => {
          const [side, main, ask] = ['.sidebar', '.main', '#assist'].map((s) => document.querySelector(s).getBoundingClientRect());
          return { columns: side.right <= main.left + 1 && main.right <= ask.left + 1 && ask.top < 5 && main.width > 400,
                   sideways: document.documentElement.scrollWidth > document.documentElement.clientWidth };
        }""")
        assert where == {"columns": True, "sideways": False}, where
        assert edge.get_attribute("aria-valuemax") == "320" and edge.is_visible()
        box = edge.bounding_box()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 200)
        page.mouse.down()
        page.mouse.move(box["x"] - 240, box["y"] + 200, steps=6)
        page.mouse.up()
        assert page.evaluate(WIDTH) == 320 and edge.get_attribute("aria-valuenow") == "320"
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
        page.set_viewport_size({"width": 940, "height": 800})                  # stacked: no edge to drag
        assert page.locator("#assistResize").is_hidden()
    finally:
        page.set_viewport_size({"width": 1440, "height": 900})
        page.evaluate("localStorage.removeItem('assistWidth')")
        reload(page)
    assert page.evaluate(WIDTH) == 388
    assert errors == []


PRECHECK = """async () => {
  const { beforeYouConfirm } = await import(document.querySelector('meta[name=studio-static]').content + 'js/precheck.js');
  const { h, showDialog, closeDialog } = await import(document.querySelector('meta[name=studio-static]').content + 'js/core.js');
  const pad = (n) => String(n).padStart(2, '0');
  const local = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  const soon = new Date(Date.now() + 60 * 60 * 1000);
  const value = local(soon);
  const month = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November',
    'December'][soon.getMonth()];
  const clean = { id: 9001, text: 'We cut our deploy time from 22 minutes to 9. Here is what went first.', first_comment: 'Worth it.',
    pictures: [], media: [], limit: 15, used: 3, month, first_comment_max: 1250 };
  const busy = { ...clean, text: 'The write-up is at https://example.com/deploys, with every number.',
    first_comment: 'The numbers behind it: [link]', pictures: [{ id: 1 }], used: 12 };
  const section = beforeYouConfirm(busy, value);
  const go = h('button', { class: 'btn primary', type: 'button' }, 'Schedule it');
  showDialog(h('h2', null, 'Schedule this post?'), h('p', null, 'When it goes out.'), section, h('div', { class: 'dialog-foot' }, go));
  await new Promise((r) => setTimeout(r, 0));                // the dialog names itself once its content is in
  const dialog = document.getElementById('dialog');
  const out = {
    clean: beforeYouConfirm(clean, value),
    heading: section.querySelector('h3').textContent,
    lines: [...section.querySelectorAll('.result.warn')].map((el) => el.textContent),
    past: [...beforeYouConfirm(clean, local(new Date(Date.now() - 2 * 60 * 60 * 1000))).querySelectorAll('.result')].map((el) => el.textContent),
    stopped: section.querySelectorAll('button, input, [disabled], [aria-disabled]').length + dialog.querySelectorAll(':disabled, [aria-disabled="true"]').length,
    described: dialog.getAttribute('aria-describedby'),
  };
  closeDialog();
  return out;
}"""


def test_before_you_confirm_names_what_to_look_at_and_stops_nothing(studio):
    page, errors = studio
    open_draft(page)
    out = page.evaluate(PRECHECK)
    assert out["clean"] is None                                               # a clean post: nothing
    assert out["heading"] == "Before you confirm" and len(out["lines"]) == 4, out["lines"]
    blank, link, picture, left = out["lines"]
    assert "first comment still has a blank" in blank and "[link]" in blank and "Back to draft" in blank
    assert "https://example.com/deploys" in link and "first comment" in link
    assert "without a picture" in picture and "Add to the post" in picture
    assert left.startswith("After this one, 2 posts are left of your 15") and "matter most" in left
    assert out["past"] == ["That time has already passed. Change the time to a later one."]
    assert out["stopped"] == 0                                                 # it only warns: nothing is disabled
    assert out["described"].split() == ["dialog-said", "precheck"]            # said as the dialog opens
    assert errors == []


STATUS = """async () => {
  const { state, h } = await import(document.querySelector('meta[name=studio-static]').content + 'js/core.js');
  const { statusOf } = await import(document.querySelector('meta[name=studio-static]').content + 'js/posts.js');
  const jobs = state.jobs;
  const p = { id: 4242, busy: true, status: 'draft', label: 'Draft', kind: '' };
  const said = [];
  for (const seconds of [125, 59]) {
    state.jobs = [{ id: 77, kind: 'post_chat', status: 'running', post_id: 4242, seconds }];
    said.push(statusOf(p).text, statusOf({ ...p, id: 1 }).text);
  }
  state.jobs = jobs;
  const ranked = { id: 4243, status: 'draft', label: 'Draft', kind: '' };   // the list's number, and the full post's card
  said.push(statusOf({ ...ranked, rank: 9 }).text, statusOf({ ...ranked, rank: { rank: 9, verdict: 'post', label: 'Worth posting' } }).text,
            statusOf({ ...ranked, rank: null }).text);
  const looks = {};
  for (const theme of ['light', 'dark']) {
    window.studioTheme.set(theme);
    const side = getComputedStyle(document.querySelector('.sidebar')).backgroundColor;
    const box = h('div', { class: 'sidebar', style: 'position:fixed;left:0;top:0' },
      ...['ready', 'ok'].map((kind) => h('span', { class: `chip ${kind}` }, h('i', { class: 'dot' }), 'A post')),
      ...['ready', 'ok'].map((kind) => h('i', { class: `dot ${kind}` })));
    document.body.append(box);
    const [chipReady, chipOk, dotReady, dotOk] = [...box.children].map((el) => getComputedStyle(el));
    looks[theme] = { side, chip: [chipReady.color, chipReady.backgroundColor], okChip: chipOk.color,
                     dot: dotReady.backgroundColor, okDot: dotOk.backgroundColor };
    box.remove();
  }
  window.studioTheme.set('auto');
  return { said, looks };
}"""


def luminance(rgb: str) -> float:
    def channel(c: float) -> float:
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (float(x) for x in re.findall(r"[\d.]+", rgb)[:3])
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a: str, b: str) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_the_status_line_says_how_long_claude_has_worked_and_approved_has_its_own_colour(studio):
    page, errors = studio
    out = page.evaluate(STATUS)
    assert out["said"] == ["Claude is working · 2 min", "Claude is working", "Claude is working", "Claude is working",
                           "Draft · 9/10", "Draft · 9/10", "Draft"]            # the top bar's chip read "[object Object]/10"
    for theme, look in out["looks"].items():
        assert contrast(*look["chip"]) >= 4.5, theme                           # the chip's words, readable
        assert contrast(look["dot"], look["side"]) >= 3, theme                 # the dot, against the sidebar
        assert look["chip"][0] != look["okChip"] and look["dot"] != look["okDot"], theme   # not the green of Scheduled
    assert errors == []


def test_move_to_trash_from_mid_list_leaves_the_focus_on_the_post_after_it(studio):
    """Last here: a draft from the middle of Drafts goes to the Trash (and is put back after, through the API)."""
    page, errors = studio
    show_tab(page, "drafts")
    first, middle, last = page.evaluate(ROWS)
    page.click(f'#postList [data-post="{middle}"]')
    page.wait_for_selector('#topActions [data-act="approve"]')
    page.click("#postGear")
    page.get_by_role("button", name="Move to Trash…").click()
    page.locator("dialog").get_by_role("button", name="Move to Trash").click()
    page.wait_for_function(f"() => location.hash === '#~posts-drafts' && document.activeElement.dataset.post === '{last}'")
    assert page.evaluate(ROWS) == [first, last]                                # its list, without it, on the post after it
    page.evaluate("(id) => fetch('/api/trash/back', { method: 'POST', headers: { 'Content-Type': 'application/json' },"
                  " body: JSON.stringify({ id }) })", middle)
    page.wait_for_function(f"() => document.querySelectorAll('#postList .post-row').length === 3")
    assert errors == []
