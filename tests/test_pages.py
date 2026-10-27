"""The pages beside the posts: which Claude account the login folder is signed in to (Settings, the Planner), the Guide's
pictures, and Story Bank headings that can never take one of the page's own ids."""
import json
import re
import sys
from pathlib import Path

import pytest
from conftest import TOKEN
from fastapi.testclient import TestClient

from app import api_pages, guide, render
from app.main import create_app

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
SIGNED_IN = {"loggedIn": True, "email": "owner@example.com", "subscriptionType": "max"}


@pytest.fixture
def web(cfg, tmp_path, fake_runner, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-not-for-claude-runs")   # must never reach the check
    app = create_app(cfg, TOKEN, db_path=tmp_path / "pages.db", runner=fake_runner)
    with TestClient(app, base_url=f"http://127.0.0.1:{cfg.port}", headers={"Origin": cfg.origin}) as client:
        client.cookies.set("studio_session", TOKEN)
        yield client


def signed_in_as(cfg, said) -> None:
    """What the stand-in Claude answers for this login folder (tests/fake_claude.py)."""
    (cfg.claude_config_dir / "fake-account.json").write_text(said if isinstance(said, str) else json.dumps(said), encoding="utf-8")


# ---- which Claude account ------------------------------------------------------------------
def test_settings_and_the_planner_name_the_account_the_login_folder_is_signed_in_to(web, cfg):
    signed_in_as(cfg, SIGNED_IN)
    shown = web.get("/api/settings").json()["claude"]
    assert shown["sign_in"] == {"ok": True, "signed_in": True, "account": "owner@example.com", "plan": "max", "error": ""}
    asked = json.loads((cfg.claude_config_dir / "fake-auth-env.json").read_text(encoding="utf-8"))
    # Asked as every run is: this login folder, no API key; a status question, never a request to Claude.
    assert asked == {"argv": ["auth", "status", "--json"], "config_dir": str(cfg.claude_config_dir), "api_key": False}
    planner = web.get("/api/planner").json()["claude"]
    assert planner["sign_in"] == shown["sign_in"] and planner["login"] == str(cfg.claude_config_dir)


def test_signed_out_and_unreadable_answers_are_said_and_check_the_sign_in_asks_again(web, cfg):
    signed_in_as(cfg, SIGNED_IN)
    assert web.get("/api/settings").json()["claude"]["sign_in"]["ok"] is True
    signed_in_as(cfg, {"loggedIn": False})
    assert web.get("/api/settings").json()["claude"]["sign_in"]["ok"] is True       # kept about a minute
    out = web.post("/api/settings/claude/check", json={}).json()["sign_in"]
    assert out["signed_in"] is False and out["error"].startswith("Not signed in: run claude once in a terminal")
    assert web.get("/api/planner").json()["claude"]["sign_in"]["signed_in"] is False
    signed_in_as(cfg, "Unknown command: auth")
    out = web.post("/api/settings/claude/check", json={}).json()["sign_in"]
    assert out["ok"] is False and out["signed_in"] is None and out["account"] == "" and "did not say" in out["error"]


def test_another_site_cannot_run_the_sign_in_check(web):
    assert web.post("/api/settings/claude/check", json={}, headers={"Origin": "http://evil.example"}).status_code == 403


# ---- the Guide's pictures --------------------------------------------------------------------
def test_the_guide_lists_the_pictures_present_and_puts_them_on_their_steps_and_screens(web, tmp_path, monkeypatch):
    shots = tmp_path / "guide"
    shots.mkdir()
    for name in ("post-light.webp", "post-dark.webp", "chat-light.jpg", "notes.txt"):
        (shots / name).write_bytes(b"RIFF....WEBP")
    monkeypatch.setattr(api_pages, "GUIDE_SHOTS", shots)
    data = web.get("/api/guide").json()
    assert set(data["shots"]) == {"post", "chat"}
    assert data["shots"]["post"]["light"].startswith("/static/guide/post-light.webp?v=")
    assert data["shots"]["post"]["dark"].startswith("/static/guide/post-dark.webp?v=")
    assert data["shots"]["chat"]["dark"] == data["shots"]["chat"]["light"]            # one theme only: shown in both
    assert data["shots"]["post"]["alt"] == guide.SHOT_WORDS["post"]
    screens = {s["key"]: s["shot"] for s in data["screens"]}
    assert screens["post"] == "post" and screens["chat"] == "chat" and screens["planner"] is None
    assert screens["settings"] is None                                                   # never pictured
    steps = {s["id"]: s["shot"] for lane in data["lanes"] for s in lane["steps"]}
    assert steps["ask"] == "chat" and steps["blanks"] == "post" and steps["schedule"] is None


def test_the_guide_lists_every_key_once():
    keys = [k for k, _what in guide.SHORTCUTS]
    assert len(keys) == len(set(keys))
    assert {"Ctrl + K", "Alt + N", "Ctrl + /", "?", "↑"} <= set(keys)
    assert dict(guide.SHORTCUTS)["Ctrl + Enter"] == "Run the tool you are typing in"


def test_the_pictures_that_ship_show_no_settings_and_stay_small():
    folder = STATIC / "guide"
    pictures = sorted(folder.glob("*")) if folder.is_dir() else []
    assert all(p.suffix in (".webp", ".jpg") and p.stem.rsplit("-", 1)[0] in guide.SHOT_WORDS for p in pictures)
    assert sum(p.stat().st_size for p in pictures) < 1_600_000


# ---- Story Bank headings ---------------------------------------------------------------------
def test_story_bank_anchors_never_take_a_page_id():
    page_ids = set(re.findall(r'\bid="([^"]+)"', (STATIC / "index.html").read_text(encoding="utf-8")))
    page_ids |= {i for p in STATIC.rglob("*.js") for i in re.findall(r'\bid: "([^"]+)"', p.read_text(encoding="utf-8"))}
    text = "# Story Bank\n\n## Status\n\n## 1. Title\n\n- x\n\n## 2. Messages\n\n## 3. List\n"
    anchors = [s["anchor"] for s in render.doc_sections(text)]
    assert anchors == ["doc-1-title", "doc-2-messages", "doc-3-list"]
    assert not set(anchors) & page_ids and not any(i.startswith("doc-") for i in page_ids)
    md = (STATIC / "js" / "md.js").read_text(encoding="utf-8")
    assert "anchors ? { id: anchorOf(title) }" in md and "export const anchorOf = (text) => `doc-${slug(text)}`" in md


# ---- dev/guide_shots.py never saves a picture that names this PC's user ------------------------
class FakePage:
    """What Camera.shoot asks of a page: where it is and its visible text."""

    def __init__(self, text, where="#post-1", claude_card=False):
        self.text, self.where, self.claude_card = text, where, claude_card
        self.context = self

    def new_cdp_session(self, _page):
        return self

    def send(self, _method, _params):
        return {"data": "UklGRg=="}

    def evaluate(self, script, *_args):
        if script == "location.hash":
            return self.where
        return self.claude_card if "Login folder" in script else self.text


def test_the_picture_taker_refuses_the_user_name_settings_and_the_claude_card(tmp_path, monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dev"))
    import guide_shots  # noqa: PLC0415

    monkeypatch.setattr(guide_shots, "OUT", tmp_path)
    monkeypatch.setattr(guide_shots, "private_words", lambda: ["someone", r"C:\Users\someone"])
    for page in (FakePage(r"Story Bank at C:\USERS\SOMEONE\linkedin-skills"), FakePage("Hello Someone,"),
                 FakePage("all made up", where="#~settings"), FakePage("all made up", where="#~setup"),
                 FakePage("all made up", claude_card=True)):
        with pytest.raises(SystemExit):
            guide_shots.Camera(page).shoot("post", "light")
    assert list(tmp_path.iterdir()) == []                                  # nothing was saved
    assert guide_shots.shows_private("handsomeone and Someones", ["someone"]) == ""   # the name as a word only
    guide_shots.Camera(FakePage("all made up")).shoot("post", "light")
    assert [p.name for p in tmp_path.iterdir()] == ["post-light.webp"]
    assert "Public" in str(guide_shots.neutral_folder())
