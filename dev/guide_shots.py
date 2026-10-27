"""Take the Guide's pictures on the demo: made-up data, stand-ins for Claude, Publora and ChatGPT.

    .venv\\Scripts\\python dev\\guide_shots.py [--port 8795]

It starts dev/demo_server.py itself, in a folder with no user name in its path, uses the page the way a person would
and pictures, in light and dark: a post as LinkedIn shows it, Ask Claude at work, Schedule…, the Planner's week board,
Story Bank & Voice, Tools with a result, and the Trash when the page has one (a demo draft is moved there through the
API first). Each picture is the window at 1200 x 750, saved small as WebP by Chrome's own capture into app/static/guide/,
where the Guide shows them (app/guide.py SHOT_WORDS). Retake them when a screen changes.

It never pictures Settings, the setup screen or the Planner's Claude card (they show folders and the account), and it
refuses to save a picture whose visible text holds this PC's user name or home folder.

Needs Playwright and Chrome or Edge (requirements-dev.txt); it downloads no browser of its own.
"""
from __future__ import annotations

import base64
import getpass
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "app" / "static" / "guide"
SIZE = {"width": 1200, "height": 750}
QUALITY = 72                      # WebP quality: about 30 to 60 KB a picture
# The Trash's API, when the page has one: its list, and moving a post there.
TRASH_LIST, TRASH_MOVE = "/api/trash", "/api/post/{id}/trash"
DRAFT = "On 14 March"            # the demo's draft (dev/demo_server.py seed)


def neutral_folder() -> Path:
    """Where the demo keeps its files: Windows' shared Public folder, so no path on screen names anyone."""
    return Path(os.environ.get("PUBLIC") or r"C:\Users\Public") / "LinkedIn Studio demo"


def private_words() -> list[str]:
    """What a picture must never show: this PC's user name and home folder."""
    home = str(Path.home())
    return [w for w in {getpass.getuser(), home, home.replace("\\", "/")} if w and len(w) > 1]


def shows_private(text: str, words: list[str]) -> str:
    """The first private word in `text` (the user name as a whole word), or ""."""
    for word in words:
        pattern = re.escape(word) if ("\\" in word or "/" in word) else rf"(?<![\w.]){re.escape(word)}(?![\w])"
        if re.search(pattern, text, flags=re.I):
            return word
    return ""


VISIBLE_TEXT = """() => [document.title, document.body.innerText,
  ...[...document.querySelectorAll('input, textarea')].filter((e) => e.offsetParent).map((e) => e.value)].join('\\n')"""
# The Planner's Claude card names the login folder ("Login folder"): it must be out of the window.
CLAUDE_CARD_SHOWN = """() => [...document.querySelectorAll('dt')].some((dt) => {
  if (dt.textContent.trim() !== 'Login folder' || !dt.offsetParent) return false;
  const r = dt.getBoundingClientRect();
  return r.bottom > 0 && r.top < innerHeight;
})"""


class Camera:
    def __init__(self, page: Page):
        self.page = page
        self.cdp = page.context.new_cdp_session(page)
        self.words = private_words()
        self.saved: list[Path] = []

    def theme(self, which: str) -> None:
        """The page's own theme button, as a person switches it (its icon follows)."""
        if self.page.evaluate("document.documentElement.dataset.theme") != which:
            self.page.evaluate("document.getElementById('themeBtn').click()")
        self.page.wait_for_timeout(350)            # colour transitions

    def both(self, name: str) -> None:
        """This screen, in light then dark."""
        for which in ("light", "dark"):
            self.theme(which)
            self.shoot(name, which)
        self.theme("light")

    def shoot(self, name: str, which: str) -> None:
        page = self.page
        where = page.evaluate("location.hash")
        if where.startswith(("#~settings", "#~setup")) or page.evaluate(CLAUDE_CARD_SHOWN):
            sys.exit(f"Refused {name}-{which}: Settings, the setup screen and the Planner's Claude card are never pictured.")
        found = shows_private(page.evaluate(VISIBLE_TEXT), self.words)
        if found:
            sys.exit(f"Refused {name}-{which}: its text shows this PC's user name or home folder. Nothing was saved for it.")
        shot = self.cdp.send("Page.captureScreenshot", {"format": "webp", "quality": QUALITY, "captureBeyondViewport": False})
        path = OUT / f"{name}-{which}.webp"
        path.write_bytes(base64.b64decode(shot["data"]))
        self.saved.append(path)


def open_(page: Page, mark: str) -> None:
    page.evaluate("(mark) => { location.hash = mark; }", mark)


def idle(page: Page) -> None:
    page.wait_for_function("() => !document.querySelector('#activity .activity')", timeout=60000)


def ask(page: Page, words: str) -> None:
    page.fill("#askText", words)
    page.keyboard.press("Enter")
    page.wait_for_selector("#activity .activity")


def api(page: Page, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    """A call of the studio's API from inside the page (its cookie, its Origin), as the page itself makes one."""
    said = page.evaluate("""async ([method, path, body]) => {
      const r = await fetch(path, method === 'GET' ? {} : { method, headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body || {}) });
      let data = {};
      try { data = await r.json(); } catch {}
      return [r.status, data];
    }""", [method, path, body])
    return said[0], said[1]


def post_id(page: Page, first: str = "", status: str = "") -> int:
    _code, data = api(page, "GET", "/api/state")
    return next(p["id"] for p in data["posts"] if p["first"].startswith(first) and (not status or p["status"] == status))


def take(page: Page) -> list[Path]:
    cam = Camera(page)
    page.wait_for_selector("#list .nav-item")
    has_trash = api(page, "GET", TRASH_LIST)[0] == 200
    if has_trash:                                  # a demo draft in the Trash, so its picture has something in it
        _code, made = api(page, "POST", "/api/posts/new")
        api(page, "POST", f"/api/post/{made['id']}/save", {"text": "Why our standups moved to Thursdays.\n\nA draft I set aside."})
        code, said = api(page, "POST", TRASH_MOVE.format(id=made["id"]))
        has_trash = code == 200 and not said.get("error")

    # A post as LinkedIn shows it, after one request in its chat.
    open_(page, f"#post-{post_id(page, DRAFT)}")
    page.wait_for_selector(".li-read")
    ask(page, "Write a sharper hook")
    idle(page)
    page.wait_for_function("() => document.querySelector('.li-body').innerText.startsWith('14 March')")
    cam.both("post")

    # Ask Claude at work: a request with its numbered steps.
    ask(page, "Make it shorter, about 1,000 characters")
    page.wait_for_selector("#activity .activity li:nth-child(3)")
    cam.both("chat")
    idle(page)

    # Schedule… on the approved post.
    open_(page, f"#post-{post_id(page, status='approved')}")
    page.wait_for_function("() => document.querySelector('#status') && document.querySelector('#status').innerText.includes('Approved')")
    page.wait_for_selector("[data-act=schedule]")
    page.click("[data-act=schedule]")
    page.wait_for_selector("dialog[open]")
    page.wait_for_timeout(400)
    cam.both("schedule")
    page.keyboard.press("Escape")

    # The Planner's week board, scrolled so the cards above it (Claude's among them) are out of the window.
    open_(page, "#~planner")
    page.wait_for_selector("#plannerPage .board")
    page.evaluate("document.querySelector('#plannerPage .board').previousElementSibling.scrollIntoView({ block: 'start' })")
    page.wait_for_timeout(300)
    cam.both("planner")

    # Story Bank & Voice, with the interviewer beside it.
    open_(page, "#~bank")
    page.wait_for_selector("#bankPage .doc")
    cam.both("bank")

    # Tools, with a Humanize result.
    open_(page, "#~tools-humanize")
    pane = page.locator('[data-pane="humanize"]')
    pane.locator("textarea").fill("In today's fast-paced digital landscape, our team embarked on a transformative journey to "
                                  "streamline deployments, fostering seamless collaboration.")
    pane.locator("button[type=submit]").click()
    page.wait_for_selector('[data-pane="humanize"] .out', timeout=60000)
    page.wait_for_timeout(300)
    cam.both("tools")

    if has_trash:
        open_(page, "#~trash")
        page.wait_for_selector("#app .trash-list, #app .trash-row", timeout=20000)
        page.wait_for_timeout(300)
        cam.both("trash")
    return cam.saved


def main() -> None:
    args = sys.argv[1:]
    if "--port" in args:
        port = int(args[args.index("--port") + 1])
    else:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
    folder = neutral_folder()
    if shows_private(str(folder), private_words()):
        sys.exit(f"{folder} names this PC's user: set PUBLIC to a shared folder and run again.")
    shutil.rmtree(folder, ignore_errors=True)       # the demo seeds a fresh database only
    folder.mkdir(parents=True)
    server = subprocess.Popen([sys.executable, str(ROOT / "dev" / "demo_server.py"), "--port", str(port), "--folder", str(folder)],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        info = json.loads(server.stdout.readline())
        OUT.mkdir(parents=True, exist_ok=True)
        from playwright.sync_api import sync_playwright  # noqa: PLC0415 - only for taking pictures

        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(channel="chrome", headless=True)
            except Exception:  # noqa: BLE001 - Edge when there is no Chrome
                browser = p.chromium.launch(channel="msedge", headless=True)
            page = browser.new_context(viewport=SIZE, device_scale_factor=1, color_scheme="light").new_page()
            page.set_default_timeout(30000)
            page.goto(info["url"])
            saved = take(page)
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=20)
        shutil.rmtree(folder, ignore_errors=True)
    total = 0
    for path in saved:
        total += path.stat().st_size
        print(f"{path.name:22} {path.stat().st_size // 1024:4} KB")
    print(f"{len(saved)} pictures, {total / 1_000_000:.2f} MB")


if __name__ == "__main__":
    main()
