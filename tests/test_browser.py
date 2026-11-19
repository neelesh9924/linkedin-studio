"""The page itself, in Chrome (headless, through Playwright), on the demo studio with its stand-ins (dev/demo_server.py
in a folder of its own: no Claude, Publora or ChatGPT). Skipped without Playwright or without Chrome or Edge.

The shell (the sidebar's tabs in groups, counting nothing; Drafts listing the posts); a post's chat that rewrites the
post; a file attached and sent, opened again, and the attached picture added to the post's pictures; a carousel in its
place, and each tile filling its frame in a narrow card; Approve refused while blanks remain; the focus kept through the
polls; every page and the audit card in words (never "[object …]"); dialogs named by their heading; light and dark; New
post opening the new post, and Back to Drafts; Move to Trash… on the top draft (one request, no alert, the list with the
focus on the next post), Put back and Delete forever…; Hot topics (the demo's made-up news) and its Draft, which opens
the post with its news beside it and the link in its first comment; the search, on the posts page and on Hot topics,
from / and gone with Esc; Back up's file, chosen again under Restore from a backup…, with only the parts ticked put
back."""
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
        page.wait_for_selector("#postList .post-row")
        yield page, errors, folder
        browser.close()
    server.terminate()
    server.wait(timeout=20)


def idle(page):
    page.wait_for_function("() => !document.querySelector('#activity .activity')", timeout=30000)


def listed(page, has_text, tab="drafts"):
    """A post's row in its tab's list, the tab picked in the sidebar as a person would."""
    page.click(f"#tab-{tab}")
    page.wait_for_function("(t) => location.hash === `#~posts-${t}` && !document.getElementById('postsPage').hidden", arg=tab)
    return page.locator("#postList .post-row", has_text=has_text).first


SIDEBAR = """() => [...document.querySelectorAll('#views > .side-label')].map((label) => ({ label: label.textContent,
  tabs: [...document.querySelectorAll(`[aria-labelledby="${label.id}"] .nav-item`)].map((b) => ({ name: b.textContent.trim(),
    tone: b.querySelector('.nav-mark').className.replace('nav-mark', '').trim() })) }))"""


def test_the_sidebar_holds_tabs_in_groups_and_drafts_lists_the_posts(studio):
    page, errors, _ = studio
    assert page.evaluate("location.hash") == "" and page.locator("#title").inner_text() == "Drafts"   # the start: Drafts
    assert page.locator("#tab-drafts").get_attribute("aria-current") == "page"
    groups = page.evaluate(SIDEBAR)
    assert [(g["label"], [t["name"] for t in g["tabs"]]) for g in groups] == [
        ("Posts", ["Drafts", "Approved", "Scheduled", "Published"]),
        ("Studio", ["Schedule", "Hot topics", "Story Bank & Voice", "Tools", "Guide"])]
    for g in groups:                                                   # a tint of its own in each group, never red
        tones = [t["tone"] for t in g["tabs"]]
        assert all(tones) and len(set(tones)) == len(tones) and "bad" not in tones, tones
    assert page.locator(".side-links").inner_text().split() == ["Settings", "Trash"]
    assert page.locator(".sidebar [data-post], .sidebar .chip, .sidebar .badge, .sidebar .count").count() == 0   # no posts, no counts
    assert page.locator("#postList .post-row").all_inner_texts() == ["–\nOn 14 March I stopped coding my side project after 10 pm on weekdays.\nDraft"]
    assert errors == []


def test_the_post_chat_rewrites_the_post_and_keeps_the_focus_in_the_box(studio):
    page, errors, _ = studio
    listed(page, "On 14 March").click()
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
    page.locator("#messages button", has_text="Add chart.png to the post").click()
    page.wait_for_selector(".li-media img")
    assert (folder / "attachments").is_dir()
    assert errors == []


TILES = """() => {
  const card = document.querySelector('[data-card="pictures"]');
  card.style.width = '330px';                        // as narrow as the owner's window drew it (4 Nov 2026)
  const out = [...card.querySelectorAll('.thumb')].map((t) => {
    const frame = t.getBoundingClientRect();
    return { margin: getComputedStyle(t).marginLeft, fills: t.querySelector('img').getBoundingClientRect().width >= frame.width - 16,
             inside: [...t.querySelectorAll('img, figcaption, .btn')].every((c) => c.getBoundingClientRect().right <= frame.right + 0.5) };
  });
  card.style.width = '';
  return out;
}"""


def test_a_carousel_goes_on_the_post_alone_and_every_tile_fills_its_frame(studio):
    page, errors, _ = studio
    page.click("[data-act=carousel]")                                  # the stand-in Claude draws one in the chat
    page.locator("#messages button", has_text="Use this carousel").last.click(timeout=60000)
    page.wait_for_selector(".li-doc img")
    tiles = page.evaluate(TILES)                                       # the carousel on the post, chart.png beside it
    assert len(tiles) == 2 and all(t == {"margin": "0px", "fills": True, "inside": True} for t in tiles), tiles
    chat = page.evaluate("(() => { const s = getComputedStyle(document.querySelector('.msg-picture.carousel')); return [s.marginLeft, s.paddingLeft]; })()")
    assert chat == ["0px", "6px"]                                      # its own 6px: not 40px in, nor the Story Bank page's 28px
    tile = page.locator('[data-card="pictures"] .thumb.carousel')
    assert "Midnight" in tile.locator("figcaption").inner_text()
    first = tile.locator("img").get_attribute("src")
    tile.get_by_role("button", name="Try another look").click()       # the same slides in the next look, in their place
    page.wait_for_function("(old) => { const img = document.querySelector('[data-card=\"pictures\"] .thumb.carousel img');"
                           " return img && img.getAttribute('src') !== old; }", arg=first, timeout=60000)
    assert "Terminal" in page.locator('[data-card="pictures"] .thumb.carousel figcaption').inner_text()
    assert page.locator('[data-card="pictures"] .thumb.carousel').count() == 1                      # no copy beside it
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
    for button, box in (("#goSchedule", "#schedulePage .page-width"), ("#goHot", "#hotPage .page-width"), ("#goBank", "#bankPage .page-width"),
                        ("#goTools", "#toolsPage .page-width"), ("#goGuide", "#guidePage .page-width"),
                        ("#goSettings", "#settingsPage .settings"), ("#goTrash", "#trashPage .page-width")):
        page.click(button)
        page.wait_for_selector(box)
        assert "[object" not in page.locator(box).inner_text(), button
    for tab in ("drafts", "approved", "scheduled", "published"):
        listed(page, "", tab).wait_for()
        assert "[object" not in page.locator("#postsPage").inner_text(), tab
    listed(page, "14 March").click()                                   # its first line since the new hook
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


def test_new_post_opens_the_new_post_empty_with_the_focus_in_the_ask_box_and_back_lists_it(studio):
    page, errors, _ = studio
    listed(page, "").wait_for()
    before = page.locator("#postList .post-row").count()
    assert before >= 1
    with page.expect_response("**/api/posts/new") as made:
        page.click("#newPost")
    new = made.value.json()["id"]
    page.wait_for_function(f"() => location.hash === '#post-{new}' && document.activeElement.id === 'askText'")
    page.wait_for_selector(".li-text.placeholder")
    page.wait_for_timeout(2500)                                       # through a poll: still the new post, still the box
    assert page.evaluate("location.hash") == f"#post-{new}" and page.evaluate("document.activeElement.id") == "askText"
    assert page.locator("#tab-drafts").get_attribute("aria-current") == "true"      # the open post's tab
    back = page.locator("#backTo")
    assert back.get_attribute("aria-label") == "Back to Drafts" and back.inner_text().strip() == "Drafts"
    back.click()                                                       # Back: the list, the focus on the post left
    page.wait_for_function(f"() => location.hash === '#~posts-drafts' && document.activeElement.dataset.post === '{new}'")
    assert page.locator("#postList .post-row").count() == before + 1 and page.locator("#backTo").is_hidden()
    assert page.locator("#tab-drafts").get_attribute("aria-current") == "page"
    assert errors == []


def test_move_to_trash_on_the_top_draft_moves_on_quietly_and_the_trash_puts_it_back(studio):
    page, errors, _ = studio
    top = listed(page, "")
    gone, after = top.get_attribute("data-post"), page.locator("#postList .post-row").nth(1).get_attribute("data-post")
    top.click()
    page.wait_for_function(f"() => location.hash === '#post-{gone}'")
    page.wait_for_selector('#topActions [data-act="queue"]')         # it shows (the gear waits for the post it opens)
    page.evaluate(WATCH_ALARMS)
    seen = []
    page.on("response", lambda r: seen.append((r.request.method, r.url, r.status)))
    page.click("#postGear")
    page.get_by_role("button", name="Move to Trash…").click()
    assert "Untitled draft" in page.locator("dialog h2").inner_text()     # the dialog names the post
    page.locator("dialog").get_by_role("button", name="Move to Trash").click()
    page.wait_for_function(f"() => document.activeElement.dataset.post === '{after}'")   # its list, on the next post
    page.wait_for_timeout(2500)                                       # a poll and more
    assert page.locator(f'#postList [data-post="{gone}"]').count() == 0
    assert page.evaluate("document.activeElement.dataset.post") == after and page.evaluate("location.hash") == "#~posts-drafts"
    assert len([s for s in seen if s[0] == "POST" and s[1].endswith(f"/api/post/{gone}/trash")]) == 1
    assert len([s for s in seen if s[2] == 404]) <= 1 and page.evaluate("window.alarms") == []
    page.locator(".toast a", has_text="Open the Trash").click()
    page.wait_for_selector("#trashPage .trash-row")
    assert page.locator("#goTrash").get_attribute("aria-current") == "page"
    page.get_by_role("button", name="Put back, Untitled draft").click()
    page.wait_for_function("() => document.activeElement.closest('#trashPage .result.ok')")
    assert "back among your posts" in page.locator("#trashPage .result.ok").inner_text()
    listed(page, "")
    page.wait_for_selector(f'#postList [data-post="{gone}"]')
    assert page.locator(f'#postList [data-post="{gone}"] .post-where').inner_text() == "Draft"
    assert errors == []


def test_delete_forever_names_the_post_and_leaves_the_focus_on_what_it_did(studio):
    page, errors, _ = studio
    top = listed(page, "")
    gone = top.get_attribute("data-post")
    top.click()
    page.wait_for_function(f"() => location.hash === '#post-{gone}'")
    page.wait_for_selector('#topActions [data-act="queue"]')         # it shows (the gear waits for the post it opens)
    page.click("#postGear")
    page.get_by_role("button", name="Move to Trash…").click()
    page.locator("dialog").get_by_role("button", name="Move to Trash").click()
    page.wait_for_function(f"() => location.hash === '#~posts-drafts' && !document.querySelector('#postList [data-post=\"{gone}\"]')")
    page.click("#goTrash")
    page.get_by_role("button", name="Delete forever, Untitled draft").click()
    assert page.locator("dialog .trash-names").inner_text() == "Untitled draft"
    assert "can’t be undone" in page.locator("dialog").inner_text()
    page.locator("dialog").get_by_role("button", name="Delete forever").click()
    page.wait_for_function("() => document.activeElement.closest('#trashPage .result.ok')")
    assert page.locator("#trashPage .result.ok").inner_text() == "Deleted forever."
    assert page.locator("#trashPage .trash-row").count() == 0 and "The Trash is empty" in page.locator("#trashPage").inner_text()
    assert errors == []


def test_hot_topics_lists_the_news_and_draft_writes_a_post_from_one(studio):
    page, errors, _ = studio
    page.click("#goHot")
    page.wait_for_selector("#hotPage .hot-row", timeout=30000)        # read in the background: the demo's made-up news
    assert page.locator("#goHot").get_attribute("aria-current") == "page"
    page.wait_for_selector('#hotPage ol[aria-labelledby="hot-best"] .hot-row', timeout=60000)   # ranked by the stand-in
    page.wait_for_function("() => !document.querySelector('#hotPage .hot-rank.none')", timeout=60000)
    best = page.locator('#hotPage ol[aria-labelledby="hot-best"] .hot-row')
    assert [best.nth(n).locator(".hot-rank b").inner_text() for n in range(best.count())] == ["9", "8", "7", "6", "5"]
    assert "1 item, ranked 1 to 4" in page.locator("#hot-not-for-you summary").inner_text()      # Quokka 2, folded away
    assert "[object" not in page.locator("#hotPage").inner_text()
    first = best.first
    title = "A test helper that fails the build on an N+1 query"
    link = first.locator(".hot-title")
    assert link.inner_text() == title and "412 points" in first.locator(".hot-facts").inner_text()
    assert (link.get_attribute("href"), link.get_attribute("target")) == ("https://example.com/news/1", "_blank")
    angle = "Count your queries in tests: the one setting that fails the build on an N+1."
    assert first.locator(".hot-angle").inner_text() == f"The post: {angle}"
    first.get_by_role("button", name=f"Draft a post from: {title}").click()
    first.locator(".job-box").wait_for()
    page.wait_for_function("() => document.activeElement && document.activeElement.closest('#hotPage .hot-row')")
    opened = first.get_by_role("button", name=f"Open the post from: {title}")
    opened.wait_for(timeout=60000)
    opened.click()
    page.wait_for_selector('#postPage [data-card="news"]')
    assert title in page.locator('[data-card="news"]').inner_text()
    assert "https://example.com/news/1" in page.locator("#postPage .li-comment textarea").input_value()   # the link
    assert page.locator("#postPage .li-body").inner_text().startswith("Count your queries")             # the angle
    assert page.locator("#tab-drafts").get_attribute("aria-current") == "true"
    assert errors == []


def test_the_search_finds_a_post_by_any_word_in_it_and_hot_topics_by_the_news(studio):
    page, errors, _ = studio
    box, rows = page.locator("#postSearch"), page.locator("#postList .post-row")
    page.locator("#title").click()
    page.keyboard.press("/")                                           # from anywhere (a post): its tab's list, the search
    page.wait_for_function("() => location.hash === '#~posts-drafts' && document.activeElement.id === 'postSearch'")
    drafts = rows.count()
    box.fill("tax-export")                                             # deep in the draft, not on its first line
    march = page.locator("#postList .post-row", has_text="14 March")
    march.locator(".post-found mark.hit").first.wait_for()
    assert "tax-export" in march.locator(".post-found").inner_text() and march.locator(".post-where").inner_text() == "Draft"
    assert all("tax-export" in line for line in page.locator("#postList .post-found").all_inner_texts())   # each, by its line
    box.fill("BILLING 40,000")                                         # any case, every word: a published post too, from Drafts
    page.wait_for_function("() => document.querySelector('#postList .post-first')?.textContent.startsWith('Three years ago')")
    assert rows.count() == 1 and page.locator("#postFound").inner_text().startswith("1 of ")
    assert rows.first.locator(".post-where").inner_text() == "Published"
    box.fill("scheduled")                                              # where a post stands, as the list says it
    page.locator("#postList .post-row", has_text="Our deploys").wait_for()
    box.fill("zebra")
    page.wait_for_selector("#postList .posts-none")
    assert page.locator("#postList").inner_text() == "No posts match “zebra”." and page.locator("#postFound").inner_text() == ""
    box.press("Escape")                                                # the list as it was
    page.wait_for_function(f"() => document.querySelectorAll('#postList .post-row').length === {drafts}")
    assert box.input_value() == "" and page.evaluate("document.activeElement.id") == "postSearch"
    box.fill("BILLING")
    box.press("ArrowDown")                                             # ↓: the first post found; Enter opens it
    assert page.evaluate("document.activeElement.textContent").startswith("–Three years ago")
    page.keyboard.press("Enter")
    page.wait_for_function("() => document.getElementById('title').textContent === 'Three years of Rust'")
    page.click("#backTo")                                              # back to its tab, the search as it was
    page.wait_for_function("() => location.hash === '#~posts-published' && document.activeElement.classList.contains('post-row')")
    assert box.input_value() == "BILLING" and rows.count() == 1
    page.click("#tab-drafts")                                          # a tab picked: its posts, the search emptied
    page.wait_for_function(f"() => document.querySelectorAll('#postList .post-row').length === {drafts}")
    assert box.input_value() == ""
    page.click("#goHot")
    page.wait_for_selector('#hotPage ol[aria-labelledby="hot-best"] .hot-row', timeout=60000)
    page.locator("#hot-title").click()
    page.keyboard.press("/")                                           # on Hot topics: its own search
    assert page.evaluate("document.activeElement.id") == "hotSearch"
    news = page.locator("#hotPage .hot-row")
    total = news.count()
    page.locator("#hotSearch").fill("coroutines")
    page.wait_for_function("() => document.querySelectorAll('#hotPage .hot-row').length === 1")
    assert news.first.locator(".hot-title").inner_text() == "Kotlin coroutines cancel more than you think"
    assert page.locator("#hotFound").inner_text() == f"1 of {total} items" and news.first.locator(".hot-title mark.hit").count() == 1
    page.locator("#hotSearch").fill("quokka")                          # Not for you: open, while it holds a match
    page.wait_for_function("() => document.querySelector('#hot-not-for-you')?.open")
    assert news.count() == 1 and "Quokka" in news.first.inner_text()
    page.locator("#hotSearch").fill("zebra")
    page.wait_for_selector("#hotPage .hot-none")
    assert "Nothing matches “zebra”." in page.locator("#hotPage").inner_text()
    page.locator("#hotSearch").press("Escape")
    page.wait_for_function(f"() => document.querySelectorAll('#hotPage .hot-row').length === {total}")
    assert page.locator("#hot-not-for-you").get_attribute("open") is None and page.locator("#hotFound").inner_text() == ""
    assert errors == []


def test_back_up_downloads_a_file_that_restore_reads_back_and_puts_back_only_what_is_ticked(studio, tmp_path):
    page, errors, _ = studio
    page.goto(page.url.split("#")[0] + "#~settings-backup")
    page.wait_for_selector("#settings-backup")
    with page.expect_download() as got:
        page.locator('[data-keep="backup-down"]').click()
    name = got.value.suggested_filename
    assert name.startswith("linkedin-studio-backup-") and name.endswith(".zip")
    saved = tmp_path / name
    got.value.save_as(saved)
    page.locator("#settings-backup input[type=file]").set_input_files(str(saved))
    page.wait_for_selector("#restore-title")
    ticks = page.locator("#settings-backup .restore-parts label")
    assert ticks.all_inner_texts()[0].startswith("The Story Bank") and ticks.count() == 4
    page.locator('[data-keep="restore-studio"]').uncheck()                # the demo's posts stay as they are
    page.locator('[data-keep="restore-settings"]').uncheck()
    page.locator('[data-keep="restore-go"]').click()
    dialog = page.locator("dialog")
    assert "The Story Bank, The voice profile: what the studio has now is replaced" in dialog.inner_text()
    dialog.get_by_role("button", name="Restore", exact=True).click()
    page.wait_for_selector("#settings-backup .result.ok")
    said = page.locator("#settings-backup .result.ok").inner_text()
    assert "Put back: The Story Bank, The voice profile." in said and "before-restore-" in said
    assert page.locator("#restore-title").count() == 0 and errors == []
