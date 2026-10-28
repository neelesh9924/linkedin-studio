"""The pages beside the posts in Chrome (headless, through Playwright), on the demo studio with its stand-ins: Ask Claude
on a locked post, Settings' sections and the account, You in the preview, the Planner's order, the Guide's pictures and
its practice editor. Skipped without Playwright or without Chrome or Edge. Made-up words only."""
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from support import PNG

playwright = pytest.importorskip("playwright.sync_api")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from launch import find_browser  # noqa: E402

pytestmark = pytest.mark.skipif(not find_browser(""), reason="needs Chrome or Edge")


@pytest.fixture(scope="module")
def studio(tmp_path_factory):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    folder = tmp_path_factory.mktemp("browser-pages")
    # The demo's made-up Story Bank and voice profile, already filled in: every Getting set up step is then done.
    (folder / "skills" / "references").mkdir(parents=True)
    for template, name in (("bank-template.md", "story-bank.md"), ("voice-template.md", "voice-profile.md")):
        text = (ROOT / "dev" / "demo" / template).read_text(encoding="utf-8").replace("- filled: no", "- filled: yes")
        (folder / "skills" / "references" / name).write_text(text, encoding="utf-8")
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


def test_ask_claude_on_an_approved_post_says_it_is_locked_and_changes_nothing(studio):
    page, errors = studio
    page.locator("#list .nav-item", has_text="Approved").click()
    page.wait_for_function("() => document.querySelector('#status').innerText.includes('Approved')")
    page.wait_for_selector("#assistEmpty:not([hidden])")
    empty = page.locator("#assistEmpty").inner_text()
    assert "The text is locked. Back to draft, in the top bar, unlocks it." in empty
    assert "Audit this post" in empty and "sharper hook" not in empty.lower()
    assert "Claude can audit it or advise" in page.locator("#askHint").inner_text()
    before = page.locator(".li-body").inner_text()
    page.fill("#askText", "Write a sharper hook")
    page.keyboard.press("Enter")
    page.wait_for_selector("#messages .msg.claude")
    assert "locked" in page.locator("#messages .msg.claude").last.inner_text()
    assert page.locator(".li-body").inner_text() == before and page.locator(".msg-note").count() == 0
    page.wait_for_timeout(300)
    assert page.evaluate("document.activeElement.id") == "askText"
    page.keyboard.press("ArrowUp")                                      # the last message, back in the empty box
    assert page.input_value("#askText") == "Write a sharper hook"
    page.fill("#askText", "")
    assert errors == []


def test_settings_names_the_account_and_opens_at_a_panel(studio):
    page, errors = studio
    page.evaluate("location.hash = '#~settings-health'")
    page.wait_for_selector("#settings-claude")
    page.wait_for_function("() => document.activeElement && document.activeElement.id === 'settings-health-title'")
    assert "signed in as you@example.com (Max)" in page.locator("#settings-claude").inner_text()
    ids = page.eval_on_selector_all("#settingsPage section.panel", "(all) => all.map((s) => s.id)")
    assert ids == [f"settings-{i}" for i in ("claude", "publishing", "chatgpt", "profile", "style", "appearance", "health", "runs", "app")]
    assert errors == []


def head_of(page):
    """The open post's head and first comment, as the preview shows them (read even while the post page is hidden)."""
    return page.evaluate("""() => {
      const card = document.querySelector('#postPage .li-card');
      const text = (sel) => (card.querySelector(sel) || {}).textContent;
      const img = card.querySelector('.li-head .li-avatar img');
      return { name: text('.li-head [data-who="name"]'), headline: text('.li-head [data-who="headline"]'),
        avatar: text('.li-head .li-avatar'), photo: img ? img.getAttribute('src') : null,
        comment: text('.li-comment [data-who="comment"]'), commentPhoto: !!card.querySelector('.li-comment .li-avatar img') };
    }""")


def open_draft(page):
    page.locator("#list .nav-item", has_text="On 14 March").first.click()
    page.wait_for_selector("#postPage .li-card .li-head [data-who='name']")


def test_with_no_profile_the_preview_says_you_and_your_headline(studio):
    page, errors = studio
    open_draft(page)
    assert head_of(page) == {"name": "You", "headline": "Your headline", "avatar": "You", "photo": None,
                             "comment": "You · first comment", "commentPhoto": False}
    assert errors == []


def test_a_name_headline_and_photo_saved_in_settings_show_in_the_open_post_at_once(studio):
    page, errors = studio
    open_draft(page)
    page.evaluate("location.hash = '#~settings-profile'")
    page.wait_for_function("() => document.activeElement && document.activeElement.id === 'settings-profile-title'")
    page.fill("#profile-name", "Asha Rao")
    page.fill("#profile-headline", "Makes tiny tools for writers")
    assert page.locator("#settings-profile .li-who b").inner_text() == "Asha Rao"     # its own preview follows the typing
    page.click("#settings-profile [data-keep='profile-save']")
    page.wait_for_function("() => document.querySelector('#postPage .li-head [data-who=\"name\"]').textContent === 'Asha Rao'")
    page.set_input_files("#settings-profile input[type=file]", files=[{"name": "me.png", "mimeType": "image/png", "buffer": PNG}])
    page.wait_for_selector("#settings-profile [data-keep='profile-remove']")
    shown = head_of(page)                                    # the post page, still hidden: drawn again already
    assert (shown["name"], shown["headline"], shown["comment"]) == ("Asha Rao", "Makes tiny tools for writers", "Asha Rao · first comment")
    assert shown["photo"].startswith("/api/profile/photo?v=") and shown["commentPhoto"]
    open_draft(page)
    assert page.locator("#postPage .li-head [data-who='name']").inner_text() == "Asha Rao"
    page.evaluate("location.hash = '#~settings-profile'")    # back as it was, for the tests after this one
    page.click("#settings-profile [data-keep='profile-remove']")
    page.wait_for_function("() => !document.querySelector('#settings-profile [data-keep=\"profile-remove\"]')")
    assert page.evaluate("document.activeElement.dataset.keep") == "profile-photo"
    page.fill("#profile-name", "")
    page.fill("#profile-headline", "")
    page.click("#settings-profile [data-keep='profile-save']")
    page.wait_for_function("() => document.querySelector('#postPage .li-head [data-who=\"name\"]').textContent === 'You'")
    assert head_of(page)["avatar"] == "You" and head_of(page)["photo"] is None
    assert errors == []


def test_the_planner_shows_this_week_first_and_no_getting_set_up_once_every_step_is_done(studio):
    page, errors = studio
    page.evaluate("location.hash = '#~planner'")
    page.wait_for_selector("#plannerPage .board .plan-card")
    titles = page.eval_on_selector_all("#plannerPage .section-title h2", "(all) => all.map((t) => t.textContent)")
    assert titles[0] == "This week" and titles.index("This week") < titles.index("This month")
    assert "Getting set up" not in page.locator("#plannerPage").inner_text()
    assert "asks Publora by itself every few minutes" in page.locator("#plannerPage").inner_text()
    assert errors == []


def test_the_guides_pictures_follow_the_theme_and_its_editor_fits_its_text(studio):
    page, errors = studio
    if not list((ROOT / "app" / "static" / "guide").glob("*.webp")):
        pytest.skip("no pictures taken yet (dev/guide_shots.py)")
    page.click("#goGuide")
    frame = page.locator("#guidePage .step-demo .shot-frame").first
    frame.wait_for()
    shown = lambda: frame.evaluate("(f) => [...f.querySelectorAll('img')].find((i) => getComputedStyle(i).display !== 'none').src")  # noqa: E731
    first = shown()
    page.click("#themeBtn")
    assert shown() != first and ("-dark." in shown()) != ("-dark." in first)
    page.click("#themeBtn")
    frame.click()                                                        # a click shows it large, in the wide dialog
    page.wait_for_selector("dialog[open].wide img")
    page.keyboard.press("Escape")
    fits = page.locator("#guide-try textarea").evaluate("(t) => t.scrollHeight <= t.clientHeight + 4 && t.clientHeight > 100")
    assert fits
    assert errors == []


def test_post_style_saved_in_settings_is_a_posts_style_and_its_restyle_waits_beside_the_post(studio):
    page, errors = studio
    page.evaluate("location.hash = '#~settings-style'")
    page.wait_for_function("() => document.activeElement && document.activeElement.id === 'settings-style-title'")
    hook = page.locator("#style-default-hook")
    assert hook.get_attribute("aria-valuetext") == "Catchy"
    hook.focus()
    page.keyboard.press("ArrowRight")                                   # one step on from Catchy
    assert hook.get_attribute("aria-valuetext") == "Bold" and page.locator("#settings-style .slider-now").first.inner_text() == "Bold"
    page.click("#settings-style [data-keep='style-save']")
    page.wait_for_function("() => document.activeElement && document.activeElement.dataset.keep === 'style-save'")
    open_draft(page)
    page.click("#styleBtn")
    page.wait_for_selector("#stylePanel:not([hidden])")
    assert page.evaluate("document.activeElement.id") == "post-style-hook"
    assert page.locator("#post-style-hook").input_value() == "5"         # the default, as Settings has it now
    assert page.locator("#stylePanel .style-whose").inner_text() == "Your default, from Settings › Post style"
    page.keyboard.press("Escape")
    assert page.locator("#stylePanel").is_hidden() and page.evaluate("document.activeElement.id") == "styleBtn"
    page.click("#styleBtn")
    page.wait_for_selector("#stylePanel:not([hidden])")
    page.click("#stylePanel [data-act='restyle']")
    page.wait_for_selector("#postPage [data-restyle]")
    assert page.locator("#postPage [data-restyle]").inner_text() == "Hook bold, tone human, one emoji."
    page.locator("#postPage .card", has_text="Revised version").get_by_role("button", name="Discard").click()
    page.wait_for_function("() => !document.querySelector('#postPage [data-restyle]')")
    page.evaluate("location.hash = '#~settings-style'")                # the studio's default again, for any test after this
    page.wait_for_function("() => document.activeElement && document.activeElement.id === 'settings-style-title'")
    page.click("#settings-style [data-keep='style-studio']")
    page.click("#settings-style [data-keep='style-save']")
    page.wait_for_function("() => document.querySelector('#style-default-hook').getAttribute('aria-valuetext') === 'Catchy'")
    assert errors == []


def test_the_posts_heading_counts_the_drafts_and_what_waits_to_go_out(studio):
    page, errors = studio
    statuses = page.evaluate("fetch('/api/state').then((r) => r.json()).then((s) => s.posts.map((p) => p.status))")
    drafts = statuses.count("draft")
    said = page.locator("#postsLabel").text_content()
    assert said.startswith(f"Posts · {drafts} draft{'' if drafts == 1 else 's'}")
    for status in ("approved", "scheduled"):
        assert (f"{statuses.count(status)} {status}" in said) == (statuses.count(status) > 0)
    assert page.locator("#list").evaluate("(nav) => document.getElementById(nav.getAttribute('aria-labelledby')).textContent") == said
    assert errors == []
