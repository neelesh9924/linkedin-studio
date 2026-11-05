"""Stands in for the Codex CLI (codex.exe) in tests. It works in the CODEX_HOME it is given, as
Codex does, and never anywhere else.

--version      answers as codex-cli does
login          FAKE_CODEX_LOGIN: ok (default) signs in after FAKE_CODEX_LOGIN_DELAY seconds, writing an
               auth.json with an id_token for owner@example.com on the go plan; hang waits for ever
exec …         makes a picture as Codex does: a PNG in <CODEX_HOME>/generated_images/<session id>/, the
               session id said in its output, then "done". FAKE_CODEX_MODE: ok (default), three (three
               pictures for the one asked), none (says done, makes nothing), hang (waits for ever), late
               (makes the picture, then waits for ever before saying done: stopped after it was made).
               Stdin must be empty and closed: it reads it, as Codex does, and a pipe left open would
               keep it waiting.
Each call is one JSON line in FAKE_CODEX_LOG, when it is set: its argv, the CODEX_HOME it had, its
working folder, what it read on stdin.
"""
import base64
import json
import os
import sys
import time
import uuid
from pathlib import Path

argv = sys.argv[1:]
home = Path(os.environ.get("CODEX_HOME") or "no-codex-home")
# A photo: 16 x 12 pixels, red.
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAABAAAAAMCAIAAADkharWAAAAGklEQVR4nGM8IafBQApgIkk1w6gG4sBwCFYAiKYBJlhTV74AAAAASUVORK5CYII=")


def say(text):
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def record(extra=None):
    if os.environ.get("FAKE_CODEX_LOG"):
        with open(os.environ["FAKE_CODEX_LOG"], "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"argv": argv, "home": str(home), "cwd": os.getcwd(),
                                 "openai_key": "OPENAI_API_KEY" in os.environ, **(extra or {})}) + "\n")


def token(claims):
    part = lambda value: base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")  # noqa: E731
    return f"{part({'alg': 'none'})}.{part(claims)}.c2lnbmF0dXJl"


if argv[:1] == ["--version"]:
    say("codex-cli 0.163.0")
    sys.exit(0)

if argv[:1] == ["login"]:
    record()
    if os.environ.get("FAKE_CODEX_LOGIN") == "hang":
        time.sleep(120)
    time.sleep(float(os.environ.get("FAKE_CODEX_LOGIN_DELAY", "0.5")))
    home.mkdir(parents=True, exist_ok=True)
    claims = {"email": "owner@example.com", "https://api.openai.com/auth": {"chatgpt_plan_type": "go"}}
    (home / "auth.json").write_text(json.dumps({"auth_mode": "chatgpt", "OPENAI_API_KEY": None, "tokens": {
        "id_token": token(claims), "access_token": "ACCESS-TOKEN-SECRET", "refresh_token": "REFRESH-TOKEN-SECRET",
        "account_id": "acct"}}), encoding="utf-8")
    say("Successfully logged in")
    sys.exit(0)

if argv[:1] == ["exec"]:
    stdin = sys.stdin.read() if sys.stdin else ""
    record({"stdin": stdin})
    mode = os.environ.get("FAKE_CODEX_MODE", "ok")
    session = str(uuid.uuid4())
    say("OpenAI Codex v0.163.0 (research preview)\n--------")
    say(f"workdir: {argv[argv.index('-C') + 1] if '-C' in argv else os.getcwd()}")
    say(f"session id: {session}")
    say("--------")
    if mode == "hang":
        time.sleep(120)
    if mode in ("ok", "three", "late"):
        folder = home / "generated_images" / session
        folder.mkdir(parents=True, exist_ok=True)
        for n in range(3 if mode == "three" else 1):
            (folder / f"ig_{n}.png").write_bytes(PNG)
            time.sleep(0.05)
    if mode == "late":
        time.sleep(120)
    say("codex\ndone")
    sys.exit(0)

say(f"fake codex: unknown command {argv}")
sys.exit(2)
