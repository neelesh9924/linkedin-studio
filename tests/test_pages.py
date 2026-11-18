"""The pages beside the posts: which Claude account the login folder is signed in to (Settings, Schedule), the Guide's
pictures, and Story Bank headings that can never take one of the page's own ids."""
import json
import os
import re
import sys
from pathlib import Path

import pytest
from conftest import TOKEN
from fastapi.testclient import TestClient

from app import api_pages, apify_key, guide, paths, publishing, render
from app.claude_runner import build_command
from app.skills import build_request
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
def test_settings_and_schedule_name_the_account_the_login_folder_is_signed_in_to(web, cfg):
    signed_in_as(cfg, SIGNED_IN)
    shown = web.get("/api/settings").json()["claude"]
    assert shown["sign_in"] == {"ok": True, "signed_in": True, "account": "owner@example.com", "plan": "max", "error": ""}
    asked = json.loads((cfg.claude_config_dir / "fake-auth-env.json").read_text(encoding="utf-8"))
    # Asked as every run is: this login folder, no API key; a status question, never a request to Claude.
    assert asked == {"argv": ["auth", "status", "--json"], "config_dir": str(cfg.claude_config_dir), "api_key": False}
    schedule = web.get("/api/schedule").json()["claude"]
    assert schedule["sign_in"] == shown["sign_in"] and schedule["login"] == str(cfg.claude_config_dir)


def test_signed_out_and_unreadable_answers_are_said_and_check_the_sign_in_asks_again(web, cfg):
    signed_in_as(cfg, SIGNED_IN)
    assert web.get("/api/settings").json()["claude"]["sign_in"]["ok"] is True
    signed_in_as(cfg, {"loggedIn": False})
    assert web.get("/api/settings").json()["claude"]["sign_in"]["ok"] is True       # kept about a minute
    out = web.post("/api/settings/claude/check", json={}).json()["sign_in"]
    assert out["signed_in"] is False and out["error"].startswith("Not signed in: run claude once in a terminal")
    assert web.get("/api/schedule").json()["claude"]["sign_in"]["signed_in"] is False
    signed_in_as(cfg, "Unknown command: auth")
    out = web.post("/api/settings/claude/check", json={}).json()["sign_in"]
    assert out["ok"] is False and out["signed_in"] is None and out["account"] == "" and "did not say" in out["error"]


def test_another_site_cannot_run_the_sign_in_check(web):
    assert web.post("/api/settings/claude/check", json={}, headers={"Origin": "http://evil.example"}).status_code == 403


# ---- Schedule's Getting set up ------------------------------------------------------------
def test_getting_set_up_is_done_once_its_steps_are_and_the_key_is_the_publora_step(web, cfg):
    steps = {s["title"]: s["done"] for s in web.get("/api/schedule").json()["steps"]}
    assert steps["Connect Publora"] is True            # the key alone: the channel is worked out from it when scheduling
    assert not steps["Fill your Story Bank"] and "Plan your week" not in steps
    for name in ("story-bank.md", "voice-profile.md"):
        (cfg.skills_dir / "references" / name).write_text("# Made up\n\n## Status\n\n- filled: yes\n", encoding="utf-8")
    assert all(s["done"] for s in web.get("/api/schedule").json()["steps"])   # the page then shows no Getting set up


def test_the_guide_names_the_new_ways_once():
    words = json.dumps([guide.SCREENS, guide.LANES, guide.STATES])
    assert "Start a post from this" in words and "Save as a post" not in words
    assert "Earlier results" in words and "You in the preview" in words


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
    assert screens["post"] == "post" and screens["chat"] == "chat" and screens["schedule"] is None   # its own picture (coming), never Schedule…'s
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


# ---- the model -------------------------------------------------------------------------------
def test_the_model_box_saves_into_config_local_and_the_next_run_uses_it(web, cfg, tmp_path, monkeypatch):
    """Settings › Claude's Model, as the owner's other studios have it: a name --model takes, or empty for the account's
    default. Only the model line of config.local.toml changes, and every run from then on uses it."""
    local = tmp_path / "config.local.toml"
    local.write_text("# kept\nport = 8799\nmodel = 'sonnet'\n", encoding="utf-8")
    monkeypatch.setattr(paths, "LOCAL", local)
    runner = web.app.state.jobs.runner
    shown = web.get("/api/settings").json()["claude"]
    assert (shown["model"], shown["model_value"]) == ("sonnet", "sonnet")
    assert [m["value"] for m in shown["models"]] == ["", "sonnet", "opus", "haiku"]          # the dropdown's list, in order
    refused = web.post("/api/settings/model", json={"model": "op us; rm"})
    assert refused.status_code == 422 and refused.json()["error"] == "The model is a name like sonnet or opus."
    assert web.post("/api/settings/model", json={"model": "opus"}).json() == {"ok": True, "model": "opus", "model_value": "opus"}
    assert local.read_text(encoding="utf-8") == "# kept\nport = 8799\nmodel = 'opus'\n" and runner.model == "opus"
    req = build_request("humanize", {"text": "A post."})
    cmd = build_command(cfg, req, model=runner.model)
    assert cmd[cmd.index("--model") + 1] == "opus"
    assert web.get("/api/schedule").json()["claude"]["model"] == "opus"
    assert web.post("/api/settings/model", json={"model": ""}).json()["model"] == "Account default"
    assert "--model" not in build_command(cfg, req, model=runner.model)     # empty: the account's own default
    assert "model = ''" in local.read_text(encoding="utf-8")


# ---- the Apify key ---------------------------------------------------------------------------
def test_the_apify_key_is_asked_of_apify_then_kept_and_never_shown(web, cfg, monkeypatch):
    """Settings › Publishing's Apify key: only something shaped like a key is sent, and only to Apify (the demo's stand-in
    here), which is asked whether it takes it before it is kept, as the test's own variable (apify_key.REGISTRY is off:
    the Windows user variable is never written). Settings gets the keys for its boxes, and no other answer has them."""
    from dev.demo_server import DemoApify
    good, wrong = "apify_api_" + "e5" * 18, "apify_api_" + "f6" * 18
    apify = DemoApify(good)
    monkeypatch.setattr(apify_key, "API", apify.api)
    try:
        assert web.get("/api/settings").json()["publora"]["apify"] is False      # the .env holds only a placeholder
        for text, words in (("", "Paste your Apify API token"), ("my password", "isn't an Apify API token"),
                            ("apify_api_short", "isn't an Apify API token"), (good + "\r\nX: y", "isn't an Apify API token"),
                            (good + " " + good, "isn't an Apify API token"), (7, "Paste your Apify API token")):
            said = web.post("/api/settings/apify", json={"key": text})
            assert said.status_code == 422 and words in said.json()["error"], text
        assert apify.calls == []                                                  # none of those was sent
        refused = web.post("/api/settings/apify", json={"key": wrong})
        assert refused.status_code == 422 and "didn't take that key" in refused.json()["error"]
        assert (os.environ["LINKEDIN_STUDIO_TEST_APIFY_KEY"], web.get("/api/settings").json()["publora"]["apify"]) == ("", False)
        assert web.post("/api/settings/apify", json={"key": f"  {good}\n"}).json() == {"ok": True}
        assert apify.calls == ["/v2/users/me"] * 2
        assert os.environ["LINKEDIN_STUDIO_TEST_APIFY_KEY"] == good and apify_key.token(cfg) == good
        assert web.get("/api/settings").json()["publora"]["apify"] is True
        # the month as Apify says it, for this key's own account: used of the limit, the day the next month starts
        shown = web.get("/api/settings").json()["apify_month"]
        assert {k: shown[k] for k in ("used", "of", "renews")} == {"used": 0.42, "of": 5.0, "renews": "2026-12-05"}
        assert apify.calls[-1] == "/v2/users/me/limits"
        # the keys themselves, for Settings' boxes (dots, the eye showing one after a warning: the owner's word, 18 Nov 2026):
        # the Apify key with the variable it is kept in, and Publora's from the skills' .env; nowhere else
        assert web.get("/api/settings").json()["keys"] == {"apify": good, "apify_variable": "LINKEDIN_STUDIO_TEST_APIFY_KEY", "publora": "sk_test_secret"}
        assert all(good not in web.get(where).text for where in ("/api/state", "/api/tools"))
        # and the app window's browser keeps no copy of an answer, so the keys never land in its cache on disk
        assert all(web.get(where).headers["cache-control"] == "no-store" for where in ("/api/settings", "/api/state"))
        asked = len(apify.calls)
        assert web.post("/api/settings/apify", json={"key": good}).json() == {"ok": True}   # saved unchanged: Apify not asked
        assert len(apify.calls) == asked
    finally:
        apify.stop()
    if sys.platform == "win32":
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as kept, pytest.raises(FileNotFoundError):
            winreg.QueryValueEx(kept, "LINKEDIN_STUDIO_TEST_APIFY_KEY")


def test_the_publora_key_is_asked_of_publora_then_written_to_its_env_line(web, cfg, monkeypatch):
    """Settings › Publishing's Publora key (the owner's word, 18 Nov 2026: "make this changeable too"): only something
    shaped like a key is sent, and only to Publora (a stand-in here, never the real one), which is asked for the key's
    channels before the key is written to linkedin-skills\\.env's PUBLORA_API_KEY line, every other line as it was. Saved
    unchanged, Publora is not asked; a key whose account lacks the .env's LinkedIn channel is kept, with what to change."""
    asked = []

    class StandIn:
        def __init__(self, api_key):
            self.key = api_key

        def list_platform_connections(self):
            asked.append(self.key)
            if self.key.endswith("refused"):
                raise RuntimeError("HTTP 401: {'error': 'Invalid API key'}")
            return [{"platformId": "linkedin-mine"}, {"platformId": "x-mine"}]

    monkeypatch.setattr(publishing, "studio_client_class", lambda _cfg: StandIn)
    env = cfg.skills_dir / ".env"
    before = "# from .env.example\nPUBLORA_API_KEY=sk_test_secret\nLINKEDIN_PLATFORM_ID=linkedin-mine\nAPIFY_TOKEN=apify_api_your_token_here\n"
    env.write_text(before, encoding="utf-8")
    for text, words in (("", "Paste your Publora API key"), ("my password", "isn't a Publora API key"),
                        ("sk_your_key_here", "isn't a Publora API key"), ("sk_live_good\r\nAPIFY_TOKEN=x", "isn't a Publora API key"),
                        (7, "Paste your Publora API key")):
        said = web.post("/api/settings/publora-key", json={"key": text})
        assert said.status_code == 422 and words in said.json()["error"], text
    assert asked == []                                                        # none of those was sent
    refused = web.post("/api/settings/publora-key", json={"key": "sk_live_refused"})
    assert refused.status_code == 422 and "didn't take that key" in refused.json()["error"] and "sk_live_refused" not in refused.text
    assert env.read_text(encoding="utf-8") == before                          # a refused key changes nothing
    good = "sk_live_" + "a1" * 12
    assert web.post("/api/settings/publora-key", json={"key": f"  {good}\n"}).json() == {"ok": True, "warning": None}
    assert asked[-1] == good
    assert env.read_text(encoding="utf-8") == before.replace("sk_test_secret", good)
    assert web.get("/api/settings").json()["keys"]["publora"] == good
    assert all(good not in web.get(where).text for where in ("/api/state", "/api/tools"))
    calls = len(asked)
    assert web.post("/api/settings/publora-key", json={"key": good}).json()["ok"] is True   # saved unchanged: not asked
    assert len(asked) == calls
    # a key whose Publora account lacks the channel the .env names: kept, and said what to change
    env.write_text(env.read_text(encoding="utf-8").replace("linkedin-mine", "linkedin-old"), encoding="utf-8")
    other = "sk_live_" + "b2" * 12
    warned = web.post("/api/settings/publora-key", json={"key": other}).json()
    assert warned["ok"] is True and "no channel linkedin-old" in warned["warning"] and "linkedin-mine" in warned["warning"]
    assert f"PUBLORA_API_KEY={other}\n" in env.read_text(encoding="utf-8")


def test_one_env_line_is_set_and_every_other_kept_as_written(cfg):
    """write_env_value changes the one line it is given (an export line too, never a commented one), keeps each line's own
    ending, and adds the line at the end when the file has none."""
    env = cfg.skills_dir / ".env"
    env.write_bytes(b"# PUBLORA_API_KEY=sk_example\r\nexport PUBLORA_API_KEY=sk_old\r\nLINKEDIN_PLATFORM_ID=linkedin-x\r\n")
    publishing.write_env_value(cfg, "PUBLORA_API_KEY", "sk_new_one")
    assert env.read_bytes() == b"# PUBLORA_API_KEY=sk_example\r\nPUBLORA_API_KEY=sk_new_one\r\nLINKEDIN_PLATFORM_ID=linkedin-x\r\n"
    env.write_text("LINKEDIN_PLATFORM_ID=linkedin-x", encoding="utf-8")       # no such line, and no newline at the end
    publishing.write_env_value(cfg, "PUBLORA_API_KEY", "sk_new_one")
    assert env.read_text(encoding="utf-8") == "LINKEDIN_PLATFORM_ID=linkedin-x\nPUBLORA_API_KEY=sk_new_one\n"
    assert not (cfg.skills_dir / ".env.saving").exists()


def test_the_key_is_read_from_windows_first_then_this_process_then_the_skills_env(cfg, monkeypatch):
    """A key set in another studio reaches this one while it runs: the Windows user variable comes first (read here
    through a stand-in for the registry), then this process's environment, then linkedin-skills' .env."""
    assert apify_key.token(cfg) == ""                                             # the .env's placeholder is no key
    (cfg.skills_dir / ".env").write_text("APIFY_TOKEN=apify_api_fromtheskillsenv\n", encoding="utf-8")
    assert apify_key.token(cfg) == "apify_api_fromtheskillsenv"
    monkeypatch.setenv("LINKEDIN_STUDIO_TEST_APIFY_KEY", "apify_api_fromthisprocess")
    assert apify_key.token(cfg) == "apify_api_fromthisprocess"
    if sys.platform == "win32":
        import winreg

        class Found:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        monkeypatch.setattr(apify_key, "REGISTRY", True)
        monkeypatch.setattr(winreg, "OpenKey", lambda *a, **k: Found())
        monkeypatch.setattr(winreg, "QueryValueEx", lambda key, name: ("apify_api_fromwindows", 1))
        assert apify_key.token(cfg) == "apify_api_fromwindows"


def test_the_pages_own_files_are_asked_for_again_on_every_load(web):
    """An updated studio's scripts reach the app window at once: no-cache, and a 304 when a file is unchanged."""
    client = web[0] if isinstance(web, tuple) else web
    first = client.get("/static/js/editor.js")
    assert first.status_code == 200 and first.headers["cache-control"] == "no-cache" and first.headers.get("etag")
    again = client.get("/static/js/editor.js", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304 and again.headers["cache-control"] == "no-cache"
    assert client.get("/static/app.css").headers["cache-control"] == "no-cache"


def test_the_page_loads_its_scripts_from_an_address_that_changes_with_them(web, tmp_path):
    """After an update the page asks for new addresses, so an app window can't run a copy it kept from before."""
    from app.main import build_of
    client = web[0] if isinstance(web, tuple) else web
    page = client.get("/").text
    found = re.search(r'src="/static/v-([0-9a-f]{12})/app\.js"', page)
    assert found and '"/static/app.js"' not in page and '"/static/app.css"' not in page
    served = client.get(f"/static/v-{found.group(1)}/js/editor.js")
    assert served.status_code == 200 and served.content == client.get("/static/js/editor.js").content
    (tmp_path / "a.js").write_text("one", encoding="utf-8")
    before = build_of(tmp_path)
    assert build_of(tmp_path) == before
    (tmp_path / "a.js").write_text("two", encoding="utf-8")
    assert build_of(tmp_path) != before
