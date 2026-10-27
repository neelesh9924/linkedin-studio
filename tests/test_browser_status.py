"""Publora's answer on the page, in Chrome (headless, through Playwright), on the demo studio with its stand-ins
(dev/demo_server.py: no Claude, Publora or ChatGPT): a scheduled post's top bar says its time once and Check now answers
in words; a published post offers Open on LinkedIn, in a new window; Claude's reply in plain words; Compare with now
opens the word diff under its version, its removed and added words named for a screen reader; and going back says so
in the post's chat. Skipped without Playwright or without Chrome or Edge."""
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


@pytest.fixture(scope="module")
def studio(tmp_path_factory):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    folder = tmp_path_factory.mktemp("browser-status")
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


def open_post(page, has_text, status):
    page.locator("#list .nav-item", has_text=has_text).click()
    page.wait_for_function("(s) => document.querySelector('#status').innerText.includes(s)", arg=status)


NOTICE = "#postPage > .notice"


def test_the_scheduled_top_bar_says_its_time_once_and_check_now_answers_in_words(studio):
    page, errors = studio
    open_post(page, "Scheduled", "Scheduled ·")
    when = page.locator("#status").inner_text().split("·", 1)[1].strip()          # the chip says it: "Fri 30 Oct, 8:00 am"
    top = page.locator("#top").inner_text()
    assert top.count(when) == 1 and "Goes out" not in top and "Check status" not in top
    check = page.locator("#topActions [data-act=refresh]")
    assert check.inner_text().strip() == "Check now"
    check.click()
    page.wait_for_function("(n) => { const box = document.querySelector(n); return box && !box.hidden "
                           "&& box.innerText.includes('Publora has it scheduled'); }", arg=NOTICE)
    said = page.locator(NOTICE).inner_text().strip()
    assert re.fullmatch(r"All set: Publora has it scheduled \(checked \d{1,2}:\d{2} [ap]m\)\.", said), said
    page.wait_for_function("(s) => document.querySelector('#announce').textContent === s", arg=said)   # said aloud too
    assert page.evaluate("document.activeElement.dataset.act") == "refresh"                           # the focus stays
    assert errors == []


def test_a_published_post_offers_open_on_linkedin_in_a_new_window(studio):
    page, errors = studio
    open_post(page, "Published", "Published")
    link = page.locator("#topActions a[data-act=open]")
    link.wait_for()
    assert link.get_attribute("href").startswith("https://www.linkedin.com/")
    assert (link.get_attribute("target"), link.get_attribute("rel")) == ("_blank", "noreferrer")
    assert link.text_content() == "Open on LinkedIn (opens in a new window)"
    assert link.locator(".sr-only").text_content() == " (opens in a new window)"
    assert errors == []


def test_claude_replies_in_plain_words_and_compare_with_now_shows_the_words_that_changed(studio):
    page, errors = studio
    page.locator("#list .nav-item", has_text="On 14 March").click()
    page.wait_for_selector(".li-read")
    page.fill("#askText", "Write a sharper hook")
    page.keyboard.press("Enter")
    page.wait_for_selector("#activity .activity")
    page.wait_for_function("() => !document.querySelector('#activity .activity')", timeout=30000)
    page.wait_for_function("() => document.querySelector('.li-body').innerText.startsWith('14 March: the last night')")
    reply = page.locator("#messages .msg.claude .prose").last.inner_text().strip()
    assert reply == "I rewrote the hook: it now opens on 14 March. Two blanks are still yours to fill."
    assert "blank(s)" not in reply and "owner" not in reply                     # never the tool's own words

    page.click("#postGear")
    row = page.locator("dialog[open] .version-item", has_text="First draft")
    compare = row.get_by_role("button", name="Compare with now")
    assert compare.get_attribute("aria-expanded") == "false"
    diff = page.locator(f"#{compare.get_attribute('aria-controls')}")
    assert diff.is_hidden()
    compare.click()
    assert compare.get_attribute("aria-expanded") == "true" and diff.is_visible()
    removed, added = diff.locator("del"), diff.locator("ins")
    assert removed.count() >= 1 and added.count() >= 1
    assert all(t.startswith("removed: ") for t in removed.locator(".sr-only").all_text_contents())
    assert all(t.startswith("added: ") for t in added.locator(".sr-only").all_text_contents())
    assert "the last night" in " ".join(added.all_text_contents()) and "stopped" in " ".join(removed.all_text_contents())
    compare.click()
    assert compare.get_attribute("aria-expanded") == "false" and diff.is_hidden()

    row.get_by_role("button", name="Go back to this").click()
    page.wait_for_function("() => document.querySelector('.li-body').innerText.startsWith('On 14 March I stopped')")
    page.keyboard.press("Escape")
    line = page.locator("#messages .msg.info").last
    line.wait_for()
    assert re.fullmatch(r"You went back to the version of \d{1,2} [A-Z][a-z]{2}, \d{1,2}:\d{2} [ap]m \(First draft\)\.",
                        line.inner_text().strip())
    assert errors == []
