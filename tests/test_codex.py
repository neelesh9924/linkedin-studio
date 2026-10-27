"""ChatGPT's pictures (app/codex.py), through the stand-in tests/fake_codex.py.

Every test has a Codex home of its own and a home folder of its own (whose .codex is signed in to
another account, to show it is never used): no test reads a real sign-in or runs the real Codex CLI."""
import base64
import json
import shutil
import struct
import sys
import threading
import time
import tomllib
from pathlib import Path

import pytest
from conftest import ROOT, with_

from app import codex
from app.codex import CodexError

FAKE_CODEX = [sys.executable, str(Path(__file__).with_name("fake_codex.py"))]
PROMPT = "A paper boat sailing across a desk of sticky notes, flat illustration, warm teal and coral"


def _has_browser():
    from launch import find_browser
    return find_browser("") is not None


HAS_BROWSER = _has_browser()
needs_browser = pytest.mark.skipif(not HAS_BROWSER, reason="needs Chrome or Edge to fit the picture")


def sign_in(home, email="owner@example.com", plan="go"):
    """Codex signed in to ChatGPT in this home, as `codex login` leaves it."""
    part = lambda value: base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")  # noqa: E731
    claims = {"email": email, "https://api.openai.com/auth": {"chatgpt_plan_type": plan}}
    home.mkdir(parents=True, exist_ok=True)
    (home / "auth.json").write_text(json.dumps({"auth_mode": "chatgpt", "tokens": {
        "id_token": f"{part({'alg': 'none'})}.{part(claims)}.c2ln", "access_token": "ACCESS-TOKEN-SECRET",
        "refresh_token": "REFRESH-TOKEN-SECRET"}}), encoding="utf-8")


def png_size(data):
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


def calls(tmp_path):
    log = tmp_path / "codex.jsonl"
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.is_file() else []


def wait(test, timeout=15):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if test():
            return
        time.sleep(0.05)
    raise AssertionError("timed out")


@pytest.fixture(autouse=True)
def own_home(tmp_path, monkeypatch):
    """A home folder of the test's own, its .codex signed in to someone else (never to be used), and the
    studio's pictures not set up until the test configures them."""
    home = tmp_path / "home"
    sign_in(home / ".codex", "someone-else@example.com", "free")
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(codex, "_studio", {"codex": None, "local": None, "example": None})
    for name in ("CODEX_HOME", "FAKE_CODEX_MODE", "FAKE_CODEX_LOGIN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FAKE_CODEX_LOG", str(tmp_path / "codex.jsonl"))
    monkeypatch.setenv("FAKE_CODEX_LOGIN_DELAY", "0.2")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-not-for-codex")
    yield home
    codex.chatgpt_stop_sign_in()


@pytest.fixture
def studio(cfg, tmp_path):
    return codex.configure(with_(cfg, codex_home=str(tmp_path / "codex-home"), images_per_request=2), tmp_path / "data",
                           prefix=FAKE_CODEX)


@needs_browser
def test_a_picture_is_made_the_tested_way_fitted_and_counted(studio, tmp_path, monkeypatch):
    sign_in(tmp_path / "codex-home")
    data, width, height, mime = codex.make_picture(PROMPT, "landscape", threading.Event())
    assert (width, height, mime) == (1200, 627, "image/png")
    assert png_size(data) == (1200, 627), "fitted to LinkedIn's landscape size"
    made = calls(tmp_path)[-1]
    argv = made["argv"]
    assert argv[:5] == ["exec", "--skip-git-repo-check", "--ephemeral", "-C", argv[4]]
    assert argv[5] == codex.picture_prompt(PROMPT, "landscape") + "\n\n" + codex.ONCE
    for rule in ("made for one LinkedIn post", "not text-heavy", "No real people's faces",
                 "Nothing in it is presented as a real photo", PROMPT):
        assert rule in argv[5]
    assert Path(made["home"]).resolve() == (tmp_path / "codex-home").resolve(), "the Codex home named, and no other"
    assert made["stdin"] == "", "nothing on stdin: Codex would wait for it, or add it to the prompt"
    assert made["openai_key"] is False
    assert not Path(argv[4]).exists(), "its empty working folder is gone"
    assert codex.made_today(studio.cfg, tmp_path / "data") == 1
    monkeypatch.setenv("FAKE_CODEX_MODE", "three")
    data, width, height, _ = codex.make_picture(PROMPT, "square", threading.Event())
    assert (width, height) == png_size(data) == (1080, 1080)
    assert codex.made_today(studio.cfg, tmp_path / "data") == 4, "every picture spends the allowance, and is counted"
    assert sorted(p.name for p in (tmp_path / "data").iterdir()) == ["chatgpt.json", "chatgpt.log"], \
        "the bytes go back to the caller: no picture is kept here"


def test_images_per_request_is_shown_and_0_turns_pictures_off(cfg, tmp_path):
    codex.configure(with_(cfg, codex_home=str(tmp_path / "codex-home"), images_per_request=0), tmp_path / "data",
                    prefix=FAKE_CODEX)
    sign_in(tmp_path / "codex-home")
    card = codex.chatgpt_status()
    assert (card["ok"], card["ready"], card["per_request"]) == (False, False, 0)
    assert "images_per_request is 0" in card["error"]
    assert codex.chatgpt_ready() is False
    with pytest.raises(CodexError, match="images_per_request is 0"):
        codex.make_picture(PROMPT, "landscape", threading.Event())
    assert calls(tmp_path) == [], "refused before Codex runs"
    codex.configure(with_(cfg, codex_home=str(tmp_path / "codex-home"), images_per_request=3), tmp_path / "data",
                    prefix=FAKE_CODEX)
    assert codex.chatgpt_status()["per_request"] == 3
    assert codex.chatgpt_ready() is HAS_BROWSER


def test_no_codex_home_means_pictures_are_off_with_words(cfg, tmp_path, own_home):
    codex.configure(with_(cfg, codex_home=""), tmp_path / "data", prefix=FAKE_CODEX)
    card = codex.chatgpt_status()
    assert (card["ok"], card["ready"], card["home"], card["account"], card["plan"]) == (False, False, "", "", "")
    assert card["error"] == codex.NO_HOME
    assert "no Codex home is set" in card["error"] and "codex_home in config.local.toml" in card["error"]
    assert codex.chatgpt_ready() is False
    with pytest.raises(CodexError, match="no Codex home is set"):
        codex.make_picture(PROMPT, "landscape", threading.Event())
    before = (own_home / ".codex" / "auth.json").read_bytes()
    assert codex.chatgpt_sign_in() == codex.NO_HOME
    assert calls(tmp_path) == [], "Codex never ran"
    assert (own_home / ".codex" / "auth.json").read_bytes() == before, "nor was the PC's own .codex signed in"


def test_until_configured_pictures_are_off_and_nothing_is_read(tmp_path):
    card = codex.chatgpt_status()
    assert (card["ok"], card["ready"], card["error"]) == (False, False, codex.NOT_SET_UP)
    assert codex.chatgpt_ready() is False and codex.chatgpt_sign_in() == codex.NOT_SET_UP
    with pytest.raises(CodexError):
        codex.make_picture(PROMPT, "landscape", threading.Event())
    with pytest.raises(CodexError):
        codex.set_codex_home(str(tmp_path / "codex-home"))
    assert calls(tmp_path) == []


def test_the_status_reads_email_and_plan_and_never_a_token(studio, tmp_path):
    card = codex.chatgpt_status()
    assert card["ok"] is False and "not signed in to ChatGPT" in card["error"]
    assert card["found"] and card["path"].endswith("fake_codex.py"), "what was found, by its path"
    sign_in(tmp_path / "codex-home")
    card = codex.chatgpt_status()
    assert {"ok", "error", "account", "plan", "home", "today", "per_request"} <= set(card)
    assert (card["version"], card["account"], card["plan"], card["home"], card["today"], card["per_request"]) == \
           ("codex-cli 0.163.0", "owner@example.com", "go", str(tmp_path / "codex-home"), 0, 2)
    assert card["ok"] is card["ready"] is HAS_BROWSER
    auth = json.loads((tmp_path / "codex-home" / "auth.json").read_text(encoding="utf-8"))
    everything = json.dumps(card)
    for secret in ("ACCESS-TOKEN-SECRET", "REFRESH-TOKEN-SECRET", auth["tokens"]["id_token"], "id_token"):
        assert secret not in everything, "no token is ever shown"
    assert codex.who(tmp_path / "codex-home") == {"email": "owner@example.com", "plan": "go"}


def test_sign_in_runs_codex_login_with_the_codex_home(studio, tmp_path, own_home, monkeypatch):
    before = (own_home / ".codex" / "auth.json").read_bytes()
    assert codex.chatgpt_sign_in() is None
    wait(lambda: studio.login["state"] == "done")
    assert calls(tmp_path)[-1]["argv"] == ["login"]
    assert Path(calls(tmp_path)[-1]["home"]).resolve() == (tmp_path / "codex-home").resolve()
    assert codex.chatgpt_status()["account"] == "owner@example.com"
    assert (own_home / ".codex" / "auth.json").read_bytes() == before
    monkeypatch.setenv("FAKE_CODEX_LOGIN", "hang")
    assert codex.chatgpt_sign_in() is None
    assert codex.chatgpt_status()["login"]["state"] == "waiting"
    assert codex.chatgpt_sign_in() == "Codex is already waiting for the sign-in in your browser."
    codex.chatgpt_stop_sign_in()
    wait(lambda: studio.login["state"] == "idle")


@needs_browser
def test_what_stops_a_picture(studio, tmp_path, monkeypatch):
    with pytest.raises(CodexError, match="not signed in to ChatGPT"):
        codex.make_picture(PROMPT, "landscape", threading.Event())
    sign_in(tmp_path / "codex-home")
    with pytest.raises(CodexError, match="landscape .* or square"):
        codex.make_picture(PROMPT, "portrait", threading.Event())
    monkeypatch.setenv("FAKE_CODEX_MODE", "none")
    with pytest.raises(CodexError, match="ChatGPT made no picture"):
        codex.make_picture(PROMPT, "landscape", threading.Event())
    monkeypatch.setenv("FAKE_CODEX_MODE", "hang")
    cancel = threading.Event()
    threading.Timer(1.0, cancel.set).start()
    began = time.monotonic()
    with pytest.raises(CodexError) as stopped:
        codex.make_picture(PROMPT, "landscape", cancel)
    assert str(stopped.value) == "Stopped."
    assert time.monotonic() - began < 15, "a stop ends Codex at once"
    assert codex.made_today(studio.cfg, tmp_path / "data") == 0, "nothing was made, nothing is counted"


def test_set_codex_home_keeps_it_in_config_local(cfg, tmp_path):
    example = tmp_path / "config.example.toml"
    shutil.copy(ROOT / "config.example.toml", example)
    local = tmp_path / "config.local.toml"
    codex.configure(with_(cfg, codex_home=""), tmp_path / "data", prefix=FAKE_CODEX, local=local, example=example)
    codex.set_codex_home(str(tmp_path / "codex-home"))
    assert tomllib.loads(local.read_text(encoding="utf-8"))["codex_home"] == str(tmp_path / "codex-home")
    assert codex.chatgpt_status()["home"] == str(tmp_path / "codex-home")
    for bad in ("relative\\folder", str(tmp_path / "missing" / "codex-home")):
        with pytest.raises(CodexError, match="whole path"):
            codex.set_codex_home(bad)
    codex.set_codex_home("")
    assert tomllib.loads(local.read_text(encoding="utf-8"))["codex_home"] == ""
    assert codex.chatgpt_status()["error"] == codex.NO_HOME


def test_codex_runs_as_codex_exe_never_through_codex_cmd(cfg, tmp_path):
    npm = tmp_path / "npm"
    exe = (npm / "node_modules" / "@openai" / "codex" / "node_modules" / "@openai" / "codex-win32-x64" / "vendor"
           / "x86_64-pc-windows-msvc" / "bin" / "codex.exe")
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    (npm / "codex.cmd").write_text("@echo off", encoding="utf-8")
    assert codex.codex_exe(str(npm / "codex.cmd")) == str(exe), "codex.exe itself: a prompt never goes through cmd.exe"
    assert codex.codex_exe(str(exe)) == str(exe)
    named = codex.Codex(with_(cfg, codex_bin=str(npm / "codex.cmd")))
    assert named.base_command() == ([str(exe)], str(npm / "codex.cmd"))
    exe.unlink()
    assert codex.codex_exe(str(npm / "codex.cmd")) is None
    assert named.base_command()[0] is None
