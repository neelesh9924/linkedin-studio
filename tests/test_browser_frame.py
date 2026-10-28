"""The page's frame, in Chrome (headless, through Playwright) on the demo studio with its stand-ins (dev/demo_server.py in a
folder of its own: no Claude, Publora or ChatGPT). Skipped without Playwright or without Chrome or Edge.

The sidebar's Earlier fold (closed at first, no count, kept across a reload; Ctrl+K and Alt+↑/↓ still reach every post,
and the open post always shows); Ask Claude's edge (its keys, kept across a reload, the toasts following it, kept clear
of the post at 941 px); Before you confirm (js/precheck.js, on made-up posts); the status line while Claude works and
Approved's own colour."""
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

# The sidebar's own words, without the posts' (their first lines and times have figures of their own).
# The sidebar's words, without the posts and without the one count the owner asked for beside Posts (28 Oct 2026):
# nothing else in the frame counts.
SIDE_WORDS = """() => {
  const side = document.querySelector('.sidebar').cloneNode(true);
  side.querySelectorAll('[data-post], #postsCount').forEach((b) => b.remove());
  return side.textContent + ' ' + [...side.querySelectorAll('[aria-label], [title]')]
    .map((el) => `${el.getAttribute('aria-label') || ''} ${el.getAttribute('title') || ''}`).join(' ');
}"""
POSTS = "() => import('/static/js/core.js').then((m) => m.state.posts.map((p) => ({ id: p.id, status: p.status })))"
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
        page.wait_for_selector("#list .nav-item")
        yield page, errors
        browser.close()
    server.terminate()
    server.wait(timeout=20)


def open_draft(page) -> int:
    button = page.locator("#list .nav-item", has_text="14 March").first
    draft = int(button.get_attribute("data-post"))
    button.click()
    page.wait_for_function(f"() => location.hash === '#post-{draft}'")
    page.wait_for_selector(".li-read")
    return draft


def reload(page):
    page.reload()
    page.wait_for_selector("#list .nav-item")


def test_earlier_is_closed_at_first_counts_nothing_and_is_kept_across_a_reload(studio):
    page, errors = studio
    open_draft(page)
    published = [p["id"] for p in page.evaluate(POSTS) if p["status"] == "published"]
    fold = page.locator("#earlierFold")
    assert fold.get_attribute("aria-expanded") == "false" and fold.get_attribute("aria-controls") == "earlierList"
    assert fold.inner_text().strip().lower() == "earlier"
    assert published and all(page.locator(f'#list [data-post="{i}"]').count() == 0 for i in published)
    assert page.locator("#list [data-post]").count() == 3                  # the draft, the approved and the scheduled post
    assert not re.search(r"\d", page.evaluate(SIDE_WORDS))                 # no count anywhere: not a digit outside the posts
    fold.click()
    page.wait_for_selector("#earlierList [data-post]")
    assert page.locator("#earlierFold").get_attribute("aria-expanded") == "true"
    assert page.locator("#earlierList .sub").all_inner_texts() == ["Published"]
    assert page.evaluate("document.activeElement.id") == "earlierFold"     # drawn again, the focus stays on it
    assert not re.search(r"\d", page.evaluate(SIDE_WORDS))
    reload(page)
    assert page.locator("#earlierFold").get_attribute("aria-expanded") == "true"
    page.click("#earlierFold")
    reload(page)
    assert page.locator("#earlierFold").get_attribute("aria-expanded") == "false"
    assert page.locator("#earlierList [data-post]").count() == 0
    assert errors == []


def test_ctrl_k_opens_a_published_post_while_earlier_is_closed_and_the_list_shows_it(studio):
    page, errors = studio
    open_draft(page)
    assert page.locator("#earlierFold").get_attribute("aria-expanded") == "false"
    kept = page.evaluate("localStorage.getItem('earlier')")
    page.keyboard.press("Control+K")
    page.locator("dialog[open] .palette-input").wait_for()
    page.keyboard.type("Three years ago")
    page.keyboard.press("Enter")
    page.wait_for_function("() => document.getElementById('title').textContent === 'Three years of Rust'")
    here = page.evaluate("location.hash.replace('#post-', '')")
    row = page.locator(f'#earlierList [data-post="{here}"]')
    assert row.is_visible() and row.get_attribute("aria-current") == "page"
    assert page.locator("#earlierFold").get_attribute("aria-expanded") == "true"
    assert page.evaluate("localStorage.getItem('earlier')") == kept           # what is kept stays as it was
    page.click("#earlierFold")                                                 # closed by hand: the open post stays listed
    assert page.locator("#earlierFold").get_attribute("aria-expanded") == "false"
    assert row.is_visible() and page.evaluate("document.activeElement.id") == "earlierFold"
    open_draft(page)                                                           # another post: Earlier is closed again
    page.wait_for_function("() => !document.querySelector('#earlierList [data-post]')")
    assert errors == []


def test_alt_arrows_still_walk_every_post_with_earlier_closed(studio):
    page, errors = studio
    open_draft(page)
    posts = [str(p["id"]) for p in page.evaluate(POSTS)]
    assert page.locator("#earlierFold").get_attribute("aria-expanded") == "false" and len(posts) == 4
    seen = []
    for _ in posts:
        before = page.evaluate("location.hash")
        page.keyboard.press("Alt+ArrowDown")
        page.wait_for_function(f"""() => {{                      // opened, and listed as the open post: it always shows
          const on = document.querySelector('#list [data-post][aria-current="page"]');
          return location.hash !== '{before}' && !!on && location.hash === `#post-${{on.dataset.post}}`;
        }}""")
        seen.append(page.evaluate("location.hash.replace('#post-', '')"))
    assert sorted(seen) == sorted(posts) and seen[-1] == page.evaluate("location.hash.replace('#post-', '')")
    page.keyboard.press("Alt+ArrowUp")
    page.wait_for_function(f"() => location.hash === '#post-{posts[(posts.index(seen[-1]) - 1) % len(posts)]}'")
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
  const { beforeYouConfirm } = await import('/static/js/precheck.js');
  const { h, showDialog, closeDialog } = await import('/static/js/core.js');
  const pad = (n) => String(n).padStart(2, '0');
  const local = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  const soon = new Date(Date.now() + 60 * 60 * 1000);
  const value = local(soon);
  const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const weekday = (soon.getDay() + 6) % 7;
  const time = `${soon.getHours() % 12 || 12}:${pad(soon.getMinutes())} ${soon.getHours() < 12 ? 'AM' : 'PM'}`;
  const month = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November',
    'December'][soon.getMonth()];
  const clean = { id: 9001, text: 'We cut our deploy time from 22 minutes to 9. Here is what went first.', first_comment: 'Worth it.',
    pictures: [], picture: null, plan: { day: days[weekday], time }, limit: 15, used: 3, month, first_comment_max: 1250 };
  const busy = { ...clean, text: 'The write-up is at https://example.com/deploys, with every number.',
    first_comment: 'The numbers behind it: [link]', pictures: [{ id: 1 }], plan: { day: days[(weekday + 2) % 7], time }, used: 12 };
  const section = beforeYouConfirm(busy, value);
  const go = h('button', { class: 'btn primary', type: 'button' }, 'Schedule it');
  showDialog(h('h2', null, 'Schedule this post?'), h('p', null, 'When it goes out.'), section, h('div', { class: 'dialog-foot' }, go));
  await new Promise((r) => setTimeout(r, 0));                // the dialog names itself once its content is in
  const dialog = document.getElementById('dialog');
  const out = {
    clean: beforeYouConfirm(clean, value),
    unreadable: beforeYouConfirm({ ...clean, plan: { day: 'Someday', time: 'morning' } }, value),
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
    assert out["clean"] is None and out["unreadable"] is None                 # a clean post, or a plan it cannot read: nothing
    assert out["heading"] == "Before you confirm" and len(out["lines"]) == 5, out["lines"]
    blank, link, picture, plan, left = out["lines"]
    assert "first comment still has a blank" in blank and "[link]" in blank and "Back to draft" in blank
    assert "https://example.com/deploys" in link and "first comment" in link
    assert "without a picture" in picture and "Use as the picture" in picture
    assert "week plan" in plan and "more than a day" in plan and "Change the time" in plan
    assert left.startswith("After this one, 2 posts are left of your 15") and "matter most" in left
    assert out["past"] == ["That time has already passed. Change the time to a later one."]
    assert out["stopped"] == 0                                                 # it only warns: nothing is disabled
    assert out["described"].split() == ["dialog-said", "precheck"]            # said as the dialog opens
    assert errors == []


STATUS = """async () => {
  const { state, h } = await import('/static/js/core.js');
  const { statusOf } = await import('/static/js/sidebar.js');
  const jobs = state.jobs;
  const p = { id: 4242, busy: true, status: 'draft', label: 'Draft', kind: '' };
  const said = [];
  for (const seconds of [125, 59]) {
    state.jobs = [{ id: 77, kind: 'post_chat', status: 'running', post_id: 4242, seconds }];
    said.push(statusOf(p).text, statusOf({ ...p, id: 1 }).text);
  }
  state.jobs = jobs;
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
    assert out["said"] == ["Claude is working · 2 min", "Claude is working", "Claude is working", "Claude is working"]
    for theme, look in out["looks"].items():
        assert contrast(*look["chip"]) >= 4.5, theme                           # the chip's words, readable
        assert contrast(look["dot"], look["side"]) >= 3, theme                 # the dot, against the sidebar
        assert look["chip"][0] != look["okChip"] and look["dot"] != look["okDot"], theme   # not the green of Scheduled
    assert errors == []
