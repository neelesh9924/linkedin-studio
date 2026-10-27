"""The pages beside the posts in Chrome (headless, through Playwright), on the demo studio with its stand-ins: Ask Claude
on a locked post, Settings' sections and the account, the Guide's pictures and its practice editor. Skipped without
Playwright or without Chrome or Edge."""
import json
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


@pytest.fixture(scope="module")
def studio(tmp_path_factory):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    folder = tmp_path_factory.mktemp("browser-pages")
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
    assert ids == [f"settings-{i}" for i in ("claude", "publishing", "chatgpt", "appearance", "health", "runs", "app")]
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
