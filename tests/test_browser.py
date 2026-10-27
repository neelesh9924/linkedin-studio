"""The page itself, in Chrome (headless, through Playwright), on the demo studio with its stand-ins (dev/demo_server.py
in a folder of its own: no Claude, Publora or ChatGPT). Skipped without Playwright or without Chrome or Edge.

The shell; a post's chat that rewrites the post; a file attached and sent, opened again, and the attached picture
chosen as the post's picture; Approve refused while blanks remain; the focus kept through the polls; every page and the
audit card in words (never "[object …]"); dialogs named by their heading; light and dark; New post opening the new post;
Move to Trash… on the top draft (one request, no alert, the focus on the next post), Put back and Delete forever…."""
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
    folder = tmp_path_factory.mktemp("browser")
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
        yield page, errors, folder
        browser.close()
    server.terminate()
    server.wait(timeout=20)


def idle(page):
    page.wait_for_function("() => !document.querySelector('#activity .activity')", timeout=30000)


def test_the_shell_lists_the_posts_with_no_counts_anywhere_in_the_sidebar(studio):
    page, errors, _ = studio
    names = page.locator("#list .nav-item .name").all_inner_texts()
    subs = page.locator("#list .nav-item .sub").all_inner_texts()
    assert len(names) == 3 and {"Draft", "Approved"} <= set(subs) and "Published" not in subs   # the published one: Earlier
    assert page.locator("#earlierFold").get_attribute("aria-expanded") == "false"
    page.click("#earlierFold")
    assert page.locator("#earlierList .nav-item .sub").all_inner_texts() == ["Published"]
    page.click("#earlierFold")                                         # closed again, as it was
    side = page.locator(".sidebar").inner_text()
    assert [w for w in ("Planner", "Story Bank & Voice", "Tools", "Guide", "Settings", "Trash") if w not in side] == []
    assert page.locator(".sidebar .chip, .sidebar .badge, .sidebar .count").count() == 0
    assert errors == []


def test_the_post_chat_rewrites_the_post_and_keeps_the_focus_in_the_box(studio):
    page, errors, _ = studio
    page.locator("#list .nav-item", has_text="On 14 March").click()
    page.wait_for_selector(".li-read")
    page.fill("#askText", "Write a sharper hook")
    page.keyboard.press("Enter")
    page.wait_for_selector("#activity .activity")
    idle(page)
    page.wait_for_function("() => document.querySelector('.li-body').innerText.startsWith('14 March: the last night')")
    page.wait_for_timeout(2500)                                       # two polls and more
    assert page.evaluate("document.activeElement.id") == "askText"
    assert page.locator("#messages").get_attribute("role") == "log" and page.locator(".msg-note").count() == 1
    assert errors == []


def test_a_file_attached_and_sent_opens_again_and_its_picture_goes_on_the_post(studio):
    page, errors, folder = studio
    with page.expect_file_chooser() as chooser:                       # the paperclip opens the picker, as for a person
        page.get_by_role("button", name="Attach files").click()
    chooser.value.set_files(files=[{"name": "chart.png", "mimeType": "image/png", "buffer": PNG}])
    page.wait_for_selector("#askFiles .att-chip")
    assert "chart.png" in page.locator("#askFiles").inner_text()
    page.fill("#askText", "Here is the chart for it")
    page.keyboard.press("Enter")
    page.wait_for_selector("#messages .msg.user a.att-chip")
    assert page.locator("#askFiles .att-chip").count() == 0          # sent: the box is empty again
    href = page.locator("#messages .msg.user a.att-chip").last.get_attribute("href")
    assert page.evaluate("(url) => fetch(url).then((r) => r.status)", href) == 200
    idle(page)
    page.locator("#messages button", has_text="Use chart.png as the post").click()
    page.wait_for_selector(".li-picture img")
    assert (folder / "attachments").is_dir()
    assert errors == []


def test_approve_is_refused_while_blanks_remain(studio):
    page, _errors, _ = studio
    page.click("[data-act=approve]")
    page.wait_for_selector("#postPage .notice.bad")
    assert "placeholder" in page.locator("#postPage .notice.bad").inner_text()
    assert page.locator("#status .chip-text").inner_text() == "Draft"


def test_every_page_and_the_audit_card_show_words_never_an_object(studio):
    page, errors, _ = studio
    page.fill("#askText", "Now audit it")                              # the scripted Claude keeps an audit with a blocker
    page.keyboard.press("Enter")
    page.wait_for_selector("#activity .activity")
    idle(page)
    page.wait_for_selector("#postPage .finding.blocker")
    assert "[object" not in page.locator("#postPage").inner_text()
    for button, box in (("#goPlanner", "#plannerPage .page-width"), ("#goBank", "#bankPage .page-width"),
                        ("#goTools", "#toolsPage .page-width"), ("#goGuide", "#guidePage .page-width"),
                        ("#goSettings", "#settingsPage .settings"), ("#goTrash", "#trashPage .page-width")):
        page.click(button)
        page.wait_for_selector(box)
        assert "[object" not in page.locator(box).inner_text(), button
    page.locator("#list .nav-item", has_text="14 March").click()      # its first line since the new hook
    page.wait_for_selector(".li-read")
    assert errors == []


def test_dialogs_are_named_by_their_heading_and_both_themes_work(studio):
    page, errors, _ = studio
    page.click("#postGear")
    page.wait_for_selector("dialog[open]")
    named = page.evaluate("document.getElementById(document.getElementById('dialog').getAttribute('aria-labelledby')).textContent")
    assert named == page.locator("dialog h2").first.inner_text()
    page.keyboard.press("Escape")
    before = page.evaluate("document.documentElement.dataset.theme")
    page.click("#themeBtn")
    assert page.evaluate("document.documentElement.dataset.theme") != before
    assert page.locator("#themeBtn").get_attribute("aria-label") == f"Switch to {before} theme"   # names where it goes
    page.click("#themeBtn")
    assert errors == []


# ---- New post, Move to Trash…, Put back, Delete forever… ---------------------------------------
WATCH_ALARMS = """() => {
  window.alarms = [];
  const alarm = document.getElementById('alarm');
  alarm.textContent = '';
  new MutationObserver(() => alarm.textContent && window.alarms.push(alarm.textContent))
    .observe(alarm, { childList: true, characterData: true, subtree: true });
}"""


def test_new_post_opens_the_new_post_empty_with_the_focus_in_the_ask_box(studio):
    page, errors, _ = studio
    before = page.locator("#list .nav-item").count()
    assert before >= 3
    with page.expect_response("**/api/posts/new") as made:
        page.click("#newPost")
    new = made.value.json()["id"]
    page.wait_for_function(f"() => location.hash === '#post-{new}' && document.activeElement.id === 'askText'")
    page.wait_for_selector(".li-text.placeholder")
    page.wait_for_timeout(2500)                                       # through a poll: still the new post, still the box
    assert page.evaluate("location.hash") == f"#post-{new}" and page.evaluate("document.activeElement.id") == "askText"
    assert page.locator("#list .nav-item").count() == before + 1
    assert page.locator(f'#list [data-post="{new}"]').get_attribute("aria-current") == "page"
    assert errors == []


def test_move_to_trash_on_the_top_draft_moves_on_quietly_and_the_trash_puts_it_back(studio):
    page, errors, _ = studio
    top = page.locator("#list .nav-item").first
    gone, after = top.get_attribute("data-post"), page.locator("#list .nav-item").nth(1).get_attribute("data-post")
    top.click()
    page.wait_for_function(f"() => location.hash === '#post-{gone}'")
    page.wait_for_selector(".li-text.placeholder")
    page.evaluate(WATCH_ALARMS)
    seen = []
    page.on("response", lambda r: seen.append((r.request.method, r.url, r.status)))
    page.click("#postGear")
    page.get_by_role("button", name="Move to Trash…").click()
    assert "Untitled draft" in page.locator("dialog h2").inner_text()     # the dialog names the post
    page.locator("dialog").get_by_role("button", name="Move to Trash").click()
    page.wait_for_function(f"() => document.activeElement.dataset.post === '{after}'")
    page.wait_for_timeout(2500)                                       # a poll and more
    assert page.locator(f'#list [data-post="{gone}"]').count() == 0
    assert page.evaluate("document.activeElement.dataset.post") == after and page.evaluate("location.hash") == f"#post-{after}"
    assert len([s for s in seen if s[0] == "POST" and s[1].endswith(f"/api/post/{gone}/trash")]) == 1
    assert len([s for s in seen if s[2] == 404]) <= 1 and page.evaluate("window.alarms") == []
    page.locator(".toast a", has_text="Open the Trash").click()
    page.wait_for_selector("#trashPage .trash-row")
    assert page.locator("#goTrash").get_attribute("aria-current") == "page"
    page.get_by_role("button", name="Put back, Untitled draft").click()
    page.wait_for_function("() => document.activeElement.closest('#trashPage .result.ok')")
    assert "back among your posts" in page.locator("#trashPage .result.ok").inner_text()
    page.wait_for_selector(f'#list [data-post="{gone}"]')
    assert page.locator(f'#list [data-post="{gone}"] .sub').inner_text() == "Draft"
    assert errors == []


def test_delete_forever_names_the_post_and_leaves_the_focus_on_what_it_did(studio):
    page, errors, _ = studio
    gone = page.locator("#list .nav-item").first.get_attribute("data-post")
    page.locator("#list .nav-item").first.click()
    page.wait_for_function(f"() => location.hash === '#post-{gone}'")
    page.wait_for_selector(".li-text.placeholder")                    # it shows (the gear waits for the post it opens)
    page.click("#postGear")
    page.get_by_role("button", name="Move to Trash…").click()
    page.locator("dialog").get_by_role("button", name="Move to Trash").click()
    page.wait_for_function(f"() => !document.querySelector('#list [data-post=\"{gone}\"]')")
    page.click("#goTrash")
    page.get_by_role("button", name="Delete forever, Untitled draft").click()
    assert page.locator("dialog .trash-names").inner_text() == "Untitled draft"
    assert "can’t be undone" in page.locator("dialog").inner_text()
    page.locator("dialog").get_by_role("button", name="Delete forever").click()
    page.wait_for_function("() => document.activeElement.closest('#trashPage .result.ok')")
    assert page.locator("#trashPage .result.ok").inner_text() == "Deleted forever."
    assert page.locator("#trashPage .trash-row").count() == 0 and "The Trash is empty" in page.locator("#trashPage").inner_text()
    assert errors == []
