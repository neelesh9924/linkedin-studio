"""Take the Guide's pictures: every screen, light and dark, from the demo server.

    .venv\\Scripts\\python dev\\demo_server.py --empty      (leave it running)
    .venv\\Scripts\\python dev\\guide_shots.py              (in a second window)

Needs Playwright and Chrome or Edge. The app itself uses neither, so Playwright is not in the
requirements files:

    .venv\\Scripts\\python -m pip install playwright==1.63.0

The demo starts empty. This script fills it by using the UI the way a person would (a week
plan, two drafts, an audit, a scheduled post, a tool result, a short interview) and then
photographs each screen the Guide shows (and the setup screen, for the README) into app\\static\\guide\\. Run it again after a change to
the UI. Folders under your user profile are shown as C:\\Users\\you, so the pictures can be
shared.
"""
from __future__ import annotations

import sys
import tomllib
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "app" / "static" / "guide"
BASE = f"http://127.0.0.1:{sys.argv[sys.argv.index('--port') + 1] if '--port' in sys.argv else 8791}"
SIZE = {"width": 1200, "height": 750}
# The Guide's screens (app/guide.py SCREENS) and the page that shows each.
SCREENS = {"home": "/", "interviewer": "/interviewer", "bank": "/bank", "planner": "/planner", "drafts": "/drafts",
           "editor": "/drafts/1", "tools": "/tools", "settings": "/settings"}
# The Guide's tour shows SCREENS. The setup screen is photographed too, for the README.
EXTRA = {"setup": "/setup"}


def configured() -> dict:
    """The folders in this PC's own config, so the pictures can show ordinary ones in their place."""
    try:
        return tomllib.loads((ROOT / "config.local.toml").read_text(encoding="utf-8-sig"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


# What is on screen -> what the picture shows. Most specific first: the demo's folders sit inside
# this project, which sits inside the user profile.
USUAL = {"skills_dir": r"C:\Users\you\linkedin-skills", "claude_bin": r"C:\Users\you\.local\bin\claude.exe",
         "claude_config_dir": r"C:\Users\you\.claude"}
NEUTRAL = [(str(ROOT / "data" / "demo" / "skills"), USUAL["skills_dir"])]
NEUTRAL += [(str(Path(real)), USUAL[key]) for key, real in configured().items() if key in USUAL and real]
NEUTRAL += [(str(ROOT), r"C:\Users\you\linkedin-studio"), (str(Path.home()), r"C:\Users\you")]
REWRITE = """(pairs) => {
  const swap = (text) => pairs.reduce((out, [real, shown]) => out.split(real).join(shown), text);
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  for (const node of nodes) { const next = swap(node.nodeValue); if (next !== node.nodeValue) node.nodeValue = next; }
  for (const box of document.querySelectorAll("input[type=text], input:not([type])")) box.value = swap(box.value);
  // The setup screen lists every sign-in folder it found. A picture shows one per box, as on an ordinary PC.
  for (const field of document.querySelectorAll("[data-path-field]")) {
    const box = field.querySelector("input");
    field.querySelectorAll(".pick").forEach((pick, i) => {
      if (i) pick.remove(); else pick.classList.toggle("on", pick.textContent.trim() === box.value);
    });
  }
}"""


def job_done(page: Page, region: str) -> None:
    """A job's card appeared in `region` and has gone again."""
    page.wait_for_selector(f"{region} .working")
    page.wait_for_selector(f"{region} .working", state="detached")


def fill_the_demo(page: Page) -> None:
    page.goto(BASE + "/planner")
    page.fill("#audience", "engineers who build side projects")
    page.fill("#goal", "start conversations about building alongside a day job")
    page.click("form[hx-post='/planner'] button[type=submit]")
    job_done(page, "#board")
    for day in ("Thu", "Tue"):      # Thursday first, so it becomes draft 1
        page.locator("#board .post-card", has_text=day).locator("button:has-text('Draft this')").click()
        job_done(page, "#board")

    page.goto(BASE + "/drafts/1")
    page.click("button:has-text('Run the audit')")
    page.wait_for_selector("#rail .finding")

    page.goto(BASE + "/tools?tool=repurpose")
    page.fill("#text-repurpose", "1/ On 14 March I stopped coding my side project after 10 pm.\n"
                                 "2/ Commits fell from 31 a week to 14.\n3/ I slept seven hours instead of five.")
    page.click("form[hx-post='/tools/repurpose'] button[type=submit]")
    page.wait_for_selector("#tool-out-repurpose .out.fresh")
    with page.expect_navigation():
        page.click("#tool-out-repurpose button:has-text('Save as draft')")
    with page.expect_navigation():
        page.click("button:has-text('Approve this text')")
    page.click("#schedule-open")
    with page.expect_navigation():
        page.click("#schedule-dialog button[type=submit]")

    page.goto(BASE + "/tools")
    page.fill("#text-humanize", "In today's fast-paced digital landscape, it is crucial to leverage robust tooling. "
                                "Our team embarked on a transformative journey to streamline deployments, and the "
                                "result? A seamless experience that fosters collaboration.")
    page.click("form[hx-post='/tools/humanize'] button[type=submit]")
    page.wait_for_selector("#tool-out-humanize .out.fresh")

    page.goto(BASE + "/interviewer")
    page.click("button:has-text('Start the interview')")
    page.wait_for_selector("#thread .msg.assistant .bubble.prose")
    for answer in ("Mostly our deploy pipeline. It got a lot faster this year.",
                   "From 22 minutes to 9, team of four, Q2 2025."):
        page.click("#chat-text")
        page.keyboard.type(answer)
        page.keyboard.press("Enter")
        page.wait_for_selector("#thread .typing")
        page.wait_for_selector("#thread .typing", state="detached")
    page.wait_for_selector("#thread .file-change")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", headless=True)
        except Exception:
            browser = p.chromium.launch(channel="msedge", headless=True)
        for theme in ("light", "dark"):
            page = browser.new_context(viewport=SIZE, color_scheme=theme).new_page()
            page.set_default_timeout(45000)
            page.goto(f"{BASE}/auth?token=demo")
            if theme == "light":
                page.goto(BASE + "/drafts")
                if page.locator(".post-row").count():
                    sys.exit("The demo already has data. Restart it with --empty, then run this again.")
                fill_the_demo(page)
            for name, path in {**SCREENS, **EXTRA}.items():
                page.goto(BASE + path)
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(500)          # entry animations
                page.evaluate(REWRITE, NEUTRAL)
                page.wait_for_timeout(300)          # colour transitions on what was just changed
                page.screenshot(path=str(OUT / f"{name}-{theme}.png"))
        browser.close()
    for shot in sorted(OUT.glob("*.png")):
        print(f"{shot.name:24} {shot.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
