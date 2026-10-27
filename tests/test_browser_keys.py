"""Keys, focus and layout, in Chrome (headless, through Playwright) on the demo studio with its stand-ins
(dev/demo_server.py in a folder of its own: no Claude, Publora or ChatGPT). Skipped without Playwright or without
Chrome or Edge, except the app window's command, which needs neither.

The post's text read as a paragraph, with an Edit text button; the focus kept through polls and after Use this
version, Discard, Try again and Dismiss; the Revise menu's keys; a toast clear of Send that waits while pointed at,
and a banner said once; the
palette (Ctrl+K) and the studio's keys; the layout at 1100 x 800 and at 320 px, light and dark."""
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import launch  # noqa: E402

try:
    from playwright.sync_api import sync_playwright
except ImportError:      # the app window's check below still runs
    sync_playwright = None

needs_browser = pytest.mark.skipif(sync_playwright is None or not launch.find_browser(""), reason="needs Playwright and Chrome or Edge")

# A real change the next poll sees (the post's title), so the page draws what changed while the focus is somewhere.
BUMP = """async ([id, n]) => {
  const p = await (await fetch(`/api/post/${id}`)).json();
  await fetch(`/api/post/${id}/save`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: `Kept ${n}`, text: p.text, first_comment: p.first_comment }) });
}"""
MARK = "() => { document.activeElement.dataset.mark = 'kept'; return document.activeElement !== document.body; }"
KEPT = "() => document.activeElement.dataset.mark === 'kept'"
ON_BODY = "() => document.activeElement === document.body || !document.activeElement"


@pytest.fixture(scope="module")
def studio(tmp_path_factory):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    folder = tmp_path_factory.mktemp("keys")
    server = subprocess.Popen([sys.executable, str(ROOT / "dev" / "demo_server.py"), "--port", str(port), "--folder", str(folder)],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    info = json.loads(server.stdout.readline())
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome" if "chrome" in launch.find_browser("").lower() else "msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.set_default_timeout(20000)
        page.goto(info["url"])
        page.wait_for_selector("#list .nav-item")
        if not page.evaluate("!!window.studioPalette"):            # until index.html loads it itself
            page.add_script_tag(url="/static/js/palette.js", type="module")
            page.wait_for_function("!!window.studioPalette")
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


def through_two_polls(page, draft):
    for n in (1, 2):
        page.evaluate(BUMP, [draft, n])
        page.wait_for_timeout(2300)


@needs_browser
def test_the_post_is_read_as_its_text_with_an_edit_text_button(studio):
    page, errors = studio
    open_draft(page)
    snap = page.locator(".li-body").aria_snapshot()
    assert "paragraph" in snap and "On 14 March" in snap and "Edit the post" not in snap
    assert page.locator(".li-read").evaluate("(el) => el.tagName") == "P"
    assert page.locator(".li-body").inner_text().startswith("On 14 March I stopped")
    assert page.get_by_role("button", name="Edit text", exact=True).is_visible()
    page.locator(".li-more").click()                                   # …more reads it whole, for everyone
    assert page.locator("#postPage textarea.li-edit").count() == 0
    assert page.locator(".li-more").get_attribute("aria-expanded") == "true"
    assert page.evaluate("document.activeElement.classList.contains('li-more')")
    page.locator(".li-more").click()
    page.locator(".li-read").click(position={"x": 40, "y": 8})        # a click on the text opens it where it landed
    page.wait_for_selector("#postPage textarea.li-edit")
    assert page.evaluate("document.activeElement.selectionStart") < 30
    page.keyboard.press("Escape")                                      # Esc: back on Edit text
    page.wait_for_function("() => document.activeElement.dataset.act === 'edit'")
    page.get_by_role("button", name="Edit text", exact=True).press("Enter")
    page.wait_for_selector("#postPage textarea.li-edit")
    page.keyboard.press("Escape")
    page.wait_for_function("() => document.activeElement.dataset.act === 'edit'")
    assert errors == []


@needs_browser
def test_the_top_bar_keeps_its_next_step_after_another_page(studio):
    """Another page clears the top bar; the same post, opened again unchanged, draws its next step again."""
    page, errors = studio
    draft = open_draft(page)
    page.wait_for_selector('#topActions [data-act="approve"]')
    for leave in ("#goPlanner", "#goTrash"):
        page.click(leave)
        page.wait_for_function("() => !location.hash.startsWith('#post-')")
        page.click(f'#list [data-post="{draft}"]')
        page.wait_for_selector('#topActions [data-act="approve"]', timeout=5000)
    assert errors == []


@needs_browser
def test_back_to_draft_and_approve_reach_ask_claude_at_the_next_poll(studio):
    """Publora's side of a post (Approve, Back to draft) moves the page's poll too: Ask Claude's panel follows it."""
    page, errors = studio
    page.locator("#list .nav-item", has_text="The best code review").first.click()
    locked = "() => document.querySelector('#assistEmpty').innerText.includes('locked')"
    page.wait_for_function(locked, timeout=6000)
    page.locator('#topActions [data-act="back"]').click()
    page.wait_for_function(f"() => !({locked})()", timeout=6000)
    page.locator('#topActions [data-act="approve"]').click()
    page.wait_for_function(locked, timeout=6000)
    assert errors == []


@needs_browser
def test_the_focus_stays_put_through_polls(studio):
    page, errors = studio
    draft = open_draft(page)
    for target in ("[data-act=edit]", ".li-more", "#reviseBtn"):
        page.focus(target)
        assert page.evaluate(MARK), target
        through_two_polls(page, draft)
        assert page.evaluate(KEPT), target
    page.evaluate("location.hash = '#~tools-humanize'")
    page.wait_for_selector("#tool-pane-humanize:not([hidden]) textarea")
    for target in ("#tool-tab-humanize", "#tool-pane-humanize button[type=submit]"):
        page.focus(target)
        assert page.evaluate(MARK), target
        through_two_polls(page, draft)
        assert page.evaluate(KEPT), target
    tab = page.locator("#tool-tab-humanize")
    assert tab.get_attribute("aria-pressed") is None and tab.get_attribute("aria-controls") == "tool-pane-humanize"
    assert page.locator("#tool-pane-humanize").get_attribute("role") == "tabpanel"
    assert page.locator("#tool-pane-humanize").get_attribute("aria-labelledby") == "tool-tab-humanize"
    assert errors == []


@needs_browser
def test_the_revise_menu_moves_with_its_keys_and_closes_on_tab(studio):
    page, errors = studio
    open_draft(page)
    page.click("#reviseBtn")
    assert page.locator("#reviseBtn").get_attribute("aria-expanded") == "true"
    assert page.locator("#reviseMenu [role=menuitem]:not([tabindex='-1'])").count() == 0
    how = "() => document.activeElement.dataset.how"
    assert page.evaluate(how) == "hook"
    page.keyboard.press("ArrowDown")
    assert page.evaluate(how) == "shorter"
    page.keyboard.press("End")
    assert page.evaluate(how) == "technical"
    page.keyboard.press("Home")
    assert page.evaluate(how) == "hook"
    page.keyboard.press("Tab")
    assert page.locator("#reviseMenu").is_hidden()
    assert page.locator("#reviseBtn").get_attribute("aria-expanded") == "false"
    assert not page.evaluate(ON_BODY)
    assert errors == []


@needs_browser
def test_use_discard_try_again_and_dismiss_leave_the_focus_on_a_control(studio):
    page, errors = studio
    open_draft(page)
    for choice in ("Discard", "Use this version"):
        page.click("#reviseBtn")
        page.click("[data-how=hook]")
        page.wait_for_function("() => document.activeElement.id === 'reviseBtn'")    # a menu item chosen: back on Revise
        card = page.locator("[data-card=revision]")
        card.wait_for(timeout=30000)
        card.get_by_role("button", name=choice).click()
        card.wait_for(state="detached")
        page.wait_for_function("() => document.activeElement.dataset.act === 'revise'", timeout=5000)
    page.evaluate("location.hash = '#~tools-humanize'")
    pane = "#tool-pane-humanize"
    page.wait_for_selector(f"{pane}:not([hidden]) textarea")
    page.fill(f"{pane} textarea", "FAIL-ME so the card shows")
    page.click(f"{pane} button[type=submit]")
    page.wait_for_selector(f"{pane} .problem", timeout=30000)
    page.click(f"{pane} .problem [data-act=retry]")
    page.wait_for_function(f"() => document.activeElement.closest('{pane} .working') && document.activeElement.dataset.act === 'cancel'")
    page.wait_for_selector(f"{pane} .problem", timeout=30000)          # fails again, as asked
    assert not page.evaluate(ON_BODY)
    page.click(f"{pane} .problem [data-act=dismiss]")
    page.wait_for_selector(f"{pane} .problem", state="detached")
    page.wait_for_function(f"() => document.activeElement === document.querySelector('{pane} button[type=submit]')")
    assert errors == []


@needs_browser
def test_a_toast_stays_clear_of_send_and_a_banner_is_said_once(studio):
    page, errors = studio
    open_draft(page)
    page.evaluate("""() => import('/static/js/core.js').then((m) => m.toast(
      'Humanize finished. Its result is on the Tools page, waiting with every change it made.', '#~tools', 'Open'))""")
    page.wait_for_selector("#toasts .toast")
    assert page.evaluate("""() => {
      const r = document.getElementById('sendBtn').getBoundingClientRect();
      const el = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      const t = document.querySelector('#toasts .toast').getBoundingClientRect();
      const c = document.getElementById('composer').getBoundingClientRect();
      const apart = t.right <= c.left || t.left >= c.right || t.bottom <= c.top || t.top >= c.bottom;
      return !!el && !!el.closest('#sendBtn') && apart;
    }""")
    page.locator("#toasts .toast .btn").click()
    page.evaluate("() => import('/static/js/core.js').then((m) => m.toast('Copied the text.'))")
    note = page.locator("#toasts .toast", has_text="Copied the text.")
    note.hover()
    page.wait_for_timeout(6500)                                        # past its 6 seconds: it waits while pointed at
    assert note.count() == 1
    page.mouse.move(5, 5)
    note.wait_for(state="detached", timeout=9000)                     # what was left of its 6 seconds, with room for a busy PC
    heard = page.evaluate("""async () => {
      const m = await import('/static/js/core.js');
      const frame = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
      const alarm = document.getElementById('alarm');
      const words = () => [m.h('div', null, m.h('strong', null, 'LinkedIn Studio is not running.'), 'Start it again from its shortcut.'),
        m.h('button', { class: 'btn small', type: 'button' }, 'Reload')];
      const heard = [];
      m.banner('keys-check', words(), 'bad');
      await frame();
      heard.push(alarm.textContent);
      alarm.textContent = '';
      m.banner('keys-check', words(), 'bad');                          // the next poll: the same words
      await frame();
      heard.push(alarm.textContent);
      m.banner('keys-check', null);
      return heard;
    }""")
    assert heard == ["LinkedIn Studio is not running. Start it again from its shortcut.", ""]
    assert errors == []


@needs_browser
def test_the_palette_and_the_keys(studio):
    page, errors = studio
    open_draft(page)
    assert page.evaluate("document.body.firstElementChild.textContent") == "Skip to the post"
    assert page.evaluate("document.getElementById('themeBtn').previousElementSibling.id") == "paletteBtn"
    assert page.get_attribute("#newPost", "aria-keyshortcuts") == "Alt+N"
    page.focus("[data-act=edit]")
    page.keyboard.press("Control+K")
    box = page.locator("dialog[open] .palette-input")
    box.wait_for()
    assert box.get_attribute("role") == "combobox" and box.get_attribute("aria-expanded") == "true"
    assert page.locator(f"#{box.get_attribute('aria-controls')}").get_attribute("role") == "listbox"
    assert box.get_attribute("aria-activedescendant")
    assert page.evaluate("document.getElementById(document.getElementById('dialog').getAttribute('aria-labelledby')).textContent") == "Search and jump"
    page.keyboard.press("Escape")                                      # Esc: the focus back where it was
    page.wait_for_selector("dialog[open]", state="detached")
    assert page.evaluate("document.activeElement.dataset.act") == "edit"

    page.keyboard.press("Control+K")
    box.wait_for()
    page.keyboard.type("Three years ago")
    page.keyboard.press("Enter")
    page.wait_for_function("() => document.getElementById('title').textContent === 'Three years of Rust'")

    # every post, in the studio's order: the published ones are under Earlier, and Alt+↑/↓ reaches them too
    order = page.evaluate("import('/static/js/core.js').then((m) => m.state.posts.map((p) => String(p.id)))")
    here = page.evaluate("location.hash.replace('#post-', '')")
    page.keyboard.press("Alt+ArrowDown")
    after = order[(order.index(here) + 1) % len(order)]
    page.wait_for_function(f"() => location.hash === '#post-{after}'")

    page.keyboard.press("?")
    page.wait_for_selector("dialog[open] table.keys")
    named = page.evaluate("document.getElementById(document.getElementById('dialog').getAttribute('aria-labelledby')).textContent")
    assert named == "Keyboard shortcuts"
    listed = page.evaluate("fetch('/api/guide').then((r) => r.json()).then((g) => g.shortcuts.length)")
    assert page.locator("dialog[open] table.keys tbody tr").count() == listed
    page.keyboard.press("Escape")
    page.wait_for_selector("dialog[open]", state="detached")

    page.keyboard.press("Control+/")
    page.wait_for_function("() => document.activeElement.id === 'askText'")
    before = page.locator("#list [data-post]").count()
    page.keyboard.press("Alt+N")
    page.wait_for_function(f"() => document.querySelectorAll('#list [data-post]').length === {before + 1}")
    assert errors == []


@needs_browser
def test_the_layout_at_1100_by_800_and_at_320_in_light_and_dark(studio):
    page, errors = studio
    try:
        page.set_viewport_size({"width": 1100, "height": 800})
        open_draft(page)
        for theme in ("light", "dark"):
            page.evaluate("(t) => window.studioTheme.set(t)", theme)
            where = page.evaluate("""() => {
              const card = document.querySelector('.li-card').getBoundingClientRect();
              const main = document.querySelector('.main').getBoundingClientRect();
              const ask = document.getElementById('assist').getBoundingClientRect();
              return { card: card.top, beside: ask.left >= main.right - 1 && ask.top < 5 && ask.width > 250,
                       sideways: document.documentElement.scrollWidth > innerWidth };
            }""")
            assert 0 < where["card"] < 800 and where["beside"] and not where["sideways"], (theme, where)
        page.set_viewport_size({"width": 320, "height": 720})
        page.evaluate("location.hash = '#~settings'")
        page.wait_for_selector("#settingsPage .settings")
        for theme in ("light", "dark"):
            page.evaluate("(t) => window.studioTheme.set(t)", theme)
            wide = page.evaluate("() => [document.documentElement.scrollWidth, document.body.scrollWidth, innerWidth]")
            assert max(wide[:2]) <= wide[2], (theme, wide)
    finally:
        page.evaluate("() => window.studioTheme.set('auto')")
        page.set_viewport_size({"width": 1440, "height": 900})
    assert errors == []


def test_the_app_window_opens_maximized(monkeypatch):
    seen = []
    monkeypatch.setattr(launch.subprocess, "Popen", lambda args, **kw: seen.append(args))
    launch.open_window("chrome.exe", "http://127.0.0.1:1/auth?token=x")
    assert "--start-maximized" in seen[0] and seen[0][1].startswith("--app=")
