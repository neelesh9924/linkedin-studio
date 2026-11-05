"""ChatGPT's pictures, through OpenAI's Codex CLI signed in as the owner's ChatGPT account.

Ported from the owner's other studio (its app/codex.py), the way that was tried and found to work:

    codex exec --skip-git-repo-check --ephemeral -C <an empty folder> "<prompt> … exactly once …"

with nothing on stdin (it would wait for more, or add it to the prompt), then the picture is taken
from <CODEX_HOME>/generated_images/<the run's session id>/. Asked to save the file itself, Codex
runs read-only there, tries again, and makes three pictures for one: so it is told not to.

The CLI is run as codex.exe itself, never through npm's codex.cmd, so a prompt is never read by cmd.exe.

The sign-in is the CODEX_HOME that config.local.toml names as codex_home. It has no default: a PC's
own ~/.codex may be signed in to another account, so with no codex_home pictures are off and Codex
never runs. Who is signed in is read from that home's auth.json (the id_token's email and plan, nothing
else; no token is ever shown, logged or kept). "Sign in" runs `codex login` with that CODEX_HOME. Every
picture spends the owner's ChatGPT allowance, so each is counted (data/chatgpt.json).

What the studio calls (after configure(cfg), which create_app does with the app's own settings):
chatgpt_ready, chatgpt_status, chatgpt_sign_in, chatgpt_stop_sign_in, set_codex_home and make_picture,
which adds the studio's rules to the prompt and fits the picture to LinkedIn's size as a PNG, the way
That studio fits one: drawn on a canvas in the PC's Chrome or Edge, headless, in a profile of its own.
"""
from __future__ import annotations

import base64
import dataclasses
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

from . import paths
from .claude_runner import CREATE_NO_WINDOW, kill_tree
from .config import DATA_DIR, Config
from .winjob import Job

# Left out of Codex's environment: anything that would sign it in as someone other than the
# ChatGPT account in its CODEX_HOME.
BLOCKED = {"OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL", "CODEX_HOME", "CODEX_ACCESS_TOKEN"}
ONCE = ("Use your image generation tool exactly once to make this picture. Do not save, copy or move the image "
        "anywhere and do not run any commands; do not generate a second image. When it is generated, reply with "
        "the single word done.")
MAKE_TIMEOUT = 300
LOGIN_TIMEOUT = 600
PICTURES = (".png", ".jpg", ".jpeg", ".webp")
_SESSION = re.compile(r"session id:\s*([0-9A-Za-z-]{8,64})")
NO_HOME = ("ChatGPT's pictures are off: no Codex home is set. Name the folder Codex keeps your ChatGPT sign-in in "
           "(Settings › ChatGPT, or codex_home in config.local.toml, for example C:\\Users\\you\\.codex-personal), "
           "then press Sign in. The PC's own .codex folder is never used.")
NOT_SET_UP = "ChatGPT's pictures are not set up in this build yet."
SHAPES = {"landscape": (1200, 627), "square": (1080, 1080)}   # LinkedIn's sizes for a post's picture
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_lock = threading.Lock()


class CodexError(RuntimeError):
    """A picture that could not be made, in the owner's words. `made`: how many ChatGPT made all the same (one made just
    before a Stop or the time limit spent the owner's allowance, and is counted)."""

    def __init__(self, message: str, made: int = 0):
        super().__init__(message)
        self.made = made


# ---- where things are ----

def home_of(cfg: Config) -> Path | None:
    """The Codex home config.local.toml names (its sign-in, its generated_images), or None: there is no default."""
    text = (cfg.codex_home or "").strip()
    return Path(text) if text else None


def home_problem(cfg: Config) -> str:
    """Why the Codex home cannot be used, in plain words ("" when it can)."""
    home = home_of(cfg)
    if home is None:
        return NO_HOME
    if not home.is_absolute():
        return f"ChatGPT's pictures are off: codex_home in config.local.toml is not a full path ({home})."
    return ""


def codex_found(cfg: Config) -> str:
    """The Codex CLI as config.local.toml names it, or as PATH has it ("" for none)."""
    return (cfg.codex_bin or "").strip() or shutil.which("codex") or ""


def codex_exe(found: str) -> str | None:
    """The Codex CLI's own program for the one found, or None. npm puts a codex.cmd on PATH, which runs
    codex.exe through Node; the studio runs codex.exe itself, so that a prompt is never read by cmd.exe."""
    path = Path(found) if found else None
    if path is None or not path.is_file():
        return None
    if path.suffix.lower() == ".exe":
        return str(path)
    package = path.parent / "node_modules" / "@openai" / "codex"
    for vendor in (package / "node_modules" / "@openai" / "codex-win32-x64" / "vendor", package / "vendor"):
        exe = vendor / "x86_64-pc-windows-msvc" / "bin" / "codex.exe"
        if exe.is_file():
            return str(exe)
    return None


# ---- who is signed in ----

def _claims(token: str) -> dict:
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def who(home: Path | None) -> dict | None:
    """Who is signed in to Codex in this home: {email, plan}, or None. Reads only the id_token's
    email and plan: no token leaves this function."""
    if home is None:
        return None
    try:
        raw = json.loads((Path(home) / "auth.json").read_text(encoding="utf-8"))
        claims = _claims(raw["tokens"]["id_token"])
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError):
        return None
    if not isinstance(claims, dict):
        return None
    auth = claims.get("https://api.openai.com/auth") if isinstance(claims.get("https://api.openai.com/auth"), dict) else {}
    email = claims.get("email") if isinstance(claims.get("email"), str) else ""
    plan = auth.get("chatgpt_plan_type") if isinstance(auth.get("chatgpt_plan_type"), str) else ""
    return {"email": email[:120], "plan": plan[:40]} if email or plan else None


# ---- the count: every picture spends the owner's allowance ----

def counter_file(data_dir: Path = DATA_DIR) -> Path:
    return Path(data_dir) / "chatgpt.json"


def _made(data_dir: Path) -> list:
    try:
        raw = json.loads(counter_file(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return raw["made"] if isinstance(raw, dict) and isinstance(raw.get("made"), list) else []


def made_today(cfg: Config, data_dir: Path = DATA_DIR) -> int:
    """How many pictures ChatGPT made for the studio today (in the app's time zone)."""
    today = datetime.now(cfg.tz).date().isoformat()
    return sum(int(e.get("count") or 0) for e in _made(data_dir)
               if isinstance(e, dict) and str(e.get("at", "")).startswith(today))


def count(cfg: Config, pictures: int, data_dir: Path = DATA_DIR) -> None:
    """Count pictures ChatGPT made: every one spends the owner's allowance, even one not used."""
    with _lock:
        made = _made(data_dir)
        made.append({"at": datetime.now(cfg.tz).isoformat(timespec="seconds"), "count": pictures})
        path = counter_file(data_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + ".tmp")
        temp.write_text(json.dumps({"made": made[-1000:]}), encoding="utf-8")
        os.replace(temp, path)


class Codex:
    """Runs the Codex CLI: its version, its sign-in, one picture. Tests give a stand-in as the prefix."""

    def __init__(self, cfg: Config, data_dir: Path = DATA_DIR, prefix: list[str] | None = None):
        self.cfg = cfg
        self.data_dir = Path(data_dir)
        self.prefix = prefix
        self._lock = threading.Lock()
        self.login = {"state": "idle", "error": ""}   # idle | waiting | done | failed
        self._login_cancel = threading.Event()

    def base_command(self) -> tuple[list[str] | None, str]:
        """(the program as a list, or None; where it was found, as the owner reads it)."""
        if self.prefix:
            return list(self.prefix), "a stand-in"
        found = codex_found(self.cfg)
        exe = codex_exe(found)
        return ([exe] if exe else None), found

    def env(self, home: Path) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k.upper() not in BLOCKED}
        env["CODEX_HOME"] = str(home)
        return env

    def _run(self, cmd: list[str], home: Path, timeout: float, cancel: threading.Event | None = None,
             cwd: str | None = None) -> tuple[str, int | None, str]:
        """(outcome, exit code, output): outcome is ok, timeout or cancelled. Its whole tree dies on a stop."""
        cancel = cancel or threading.Event()
        lines: list[str] = []
        job = Job()
        proc = subprocess.Popen(cmd, cwd=cwd, env=self.env(home), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
        job.assign(proc.pid)

        def read() -> None:
            for line in proc.stdout:
                if len(lines) < 2000:
                    lines.append(line.rstrip())

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        began = time.monotonic()
        outcome = "ok"
        try:
            while proc.poll() is None:
                if cancel.is_set():
                    outcome = "cancelled"
                    break
                if time.monotonic() - began > timeout:
                    outcome = "timeout"
                    break
                time.sleep(0.1)
        finally:
            if proc.poll() is None:
                kill_tree(proc, job)
            reader.join(timeout=5)
            try:
                proc.stdout.close()
            except OSError:
                pass
            job.close()
        return outcome, proc.returncode, "\n".join(lines)

    # ---- the Settings card ----

    def check(self) -> dict:
        base, found = self.base_command()
        home = home_of(self.cfg)
        out = {"ok": False, "error": "", "account": "", "plan": "", "version": "", "signedIn": False,
               "found": bool(base), "path": base[0] if base and not self.prefix else " ".join(base or []),
               "via": found if base and found and base[0] != found else "", "home": str(home or ""),
               "today": made_today(self.cfg, self.data_dir), "per_request": max(0, self.cfg.images_per_request),
               "login": dict(self.login)}
        off = home_problem(self.cfg)
        if off:
            return {**out, "ok": False, "off": True, "error": off}
        if not base:
            return {**out, "ok": False, "error": ("Codex was not found where codex_bin in config.local.toml says."
                                                  if self.cfg.codex_bin else
                                                  "The Codex CLI was not found. Install it (npm install -g @openai/codex), "
                                                  "or give its path as codex_bin in config.local.toml.")}
        try:
            outcome, code, said = self._run(base + ["--version"], home, 60)
        except OSError as exc:
            return {**out, "ok": False, "error": f"Codex did not start: {exc}"}
        version = next((m.group(0) for m in re.finditer(r"codex-cli \S+", said)), "")
        if outcome != "ok" or code != 0 or not version:
            return {**out, "ok": False, "error": "Codex did not start: " + (said.strip().splitlines() or [f"exit code {code}"])[-1]}
        account = who(home)
        if not account:
            return {**out, "ok": False, "version": version, "signedIn": False,
                    "error": f"Codex is not signed in to ChatGPT in {home}. Press Sign in."}
        return {**out, "ok": True, "version": version, "signedIn": True, "account": account["email"], "plan": account["plan"]}

    def sign_in(self, done=None) -> str | None:
        """Run `codex login` with the CODEX_HOME in use: it opens the browser and waits for the sign-in there.
        None when it started, else why not."""
        with self._lock:
            if self.login["state"] == "waiting":
                return "Codex is already waiting for the sign-in in your browser."
            off = home_problem(self.cfg)
            if off:
                return off
            base, _ = self.base_command()
            if not base:
                return "The Codex CLI was not found."
            home = home_of(self.cfg)
            try:
                home.mkdir(exist_ok=True)   # the folder the owner named; Codex wants it to be there
            except OSError as exc:
                return f"The Codex home {home} cannot be made: {exc}"
            self.login = {"state": "waiting", "error": "", "home": str(home)}
            self._login_cancel = threading.Event()
        cancel = self._login_cancel

        def work() -> None:
            try:
                outcome, code, said = self._run(base + ["login"], home, LOGIN_TIMEOUT, cancel)
            except OSError as exc:
                outcome, code, said = "error", None, str(exc)
            account = who(home)
            if outcome == "ok" and code == 0 and account:
                state = {"state": "done", "error": ""}
            elif outcome == "cancelled":
                state = {"state": "idle", "error": ""}
            elif outcome == "timeout":
                state = {"state": "failed", "error": "No sign-in came within ten minutes."}
            else:
                tail = [line for line in said.splitlines() if line.strip()][-1:]
                state = {"state": "failed", "error": "The sign-in did not finish" + (f": {tail[0]}" if tail else ".")}
            with self._lock:
                self.login = state
            if done:
                done()

        threading.Thread(target=work, name="codex-login", daemon=True).start()
        return None

    def stop_sign_in(self) -> None:
        self._login_cancel.set()

    # ---- one picture ----

    def make(self, prompt: str, cancel: threading.Event | None = None) -> tuple[Path, int]:
        """Have ChatGPT make one picture. Returns (the picture's path, how many it made): it is told to make
        one, and every one it made is counted by the caller. Raises CodexError, with how many it had made
        (CodexError.made) when it was stopped or ran out of time after making one."""
        off = home_problem(self.cfg)
        if off:
            raise CodexError(off)
        base, _ = self.base_command()
        if not base:
            raise CodexError("The Codex CLI is not on this PC, so ChatGPT cannot make pictures.")
        home = home_of(self.cfg)
        if not who(home):
            raise CodexError("Codex is not signed in to ChatGPT (Settings › ChatGPT › Sign in).")
        words = " ".join(str(prompt or "").split()).lstrip("-– ")
        if not words:
            raise CodexError("Say what the picture should show.")
        holder = tempfile.mkdtemp(prefix="linkedin-studio-codex-")   # an empty folder: nothing of the owner's
        try:
            outcome, code, said = self._run(base + ["exec", "--skip-git-repo-check", "--ephemeral", "-C", holder,
                                                    f"{words}\n\n{ONCE}"], home, MAKE_TIMEOUT, cancel, cwd=holder)
        except OSError as exc:
            raise CodexError(f"Codex did not start: {exc}") from None
        finally:
            shutil.rmtree(holder, ignore_errors=True)
        self._log(f"$ codex exec … ({len(words)} characters)\n{said[-4000:]}\n-> {outcome}, exit code {code}\n")
        session = _SESSION.search(said)
        folder = home / "generated_images" / session.group(1) if session else None
        made = sorted((p for p in folder.iterdir() if p.suffix.lower() in PICTURES), key=lambda p: p.stat().st_mtime) \
            if folder and folder.is_dir() else []
        if outcome == "cancelled":
            raise CodexError("Stopped.", made=len(made))
        if outcome == "timeout":
            raise CodexError(f"ChatGPT took longer than {MAKE_TIMEOUT} s, and was stopped.", made=len(made))
        if not made:
            tail = [line for line in said.splitlines() if line.strip()][-2:]
            raise CodexError("ChatGPT made no picture" + (": " + " / ".join(tail) if tail else "."))
        return made[0], len(made)

    def _log(self, text: str) -> None:
        try:
            path = self.data_dir / "chatgpt.log"
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(f"--- {datetime.now():%Y-%m-%d %H:%M:%S}\n{text}")
        except OSError:
            pass


# ---- a picture for a LinkedIn post ----

def picture_prompt(prompt: str, shape: str) -> str:
    """The prompt the studio sends ChatGPT: what was asked for, and the studio's rules."""
    width, height = SHAPES[shape]
    words = " ".join(str(prompt or "").split())
    return (f"An illustration made for one LinkedIn post, {shape} ({width} x {height} pixels). It shows: {words} "
            "Rules: make it for this post. It is not text-heavy: no words in it, or a word or two at most. No real "
            "people's faces. Nothing in it is presented as a real photo: it is plainly an illustration.")


_FIT = """<!doctype html><meta charset="utf-8"><body><img id="i" src="{src}"><pre id="out"></pre><script>
addEventListener("load", function () {{
  var img = document.getElementById("i"), out = document.getElementById("out");
  if (!img.naturalWidth) {{ out.textContent = "unreadable"; return; }}
  var W = {width}, H = {height}, s = Math.max(W / img.naturalWidth, H / img.naturalHeight);
  var sw = W / s, sh = H / s;
  var c = document.createElement("canvas");
  c.width = W; c.height = H;
  var g = c.getContext("2d");
  g.imageSmoothingQuality = "high";
  g.drawImage(img, (img.naturalWidth - sw) / 2, (img.naturalHeight - sh) / 2, sw, sh, 0, 0, W, H);
  img.remove();
  out.textContent = c.width + "x" + c.height + " " + c.toDataURL("image/png");
}});
</script>"""


def find_browser(cfg: Config) -> str | None:
    """Chrome, then Edge, as the launcher finds the one the studio's window opens in."""
    from launch import find_browser as found   # the launcher's own lookup: one way to find it

    return found(cfg.browser_path)


def fit(body: bytes, mime: str, shape: str, browser: str) -> tuple[bytes, int, int]:
    """The picture cropped to fill LinkedIn's size for this shape and scaled to it, as a PNG: (its bytes, width, height)."""
    width, height = SHAPES[shape]
    folder = tempfile.mkdtemp(prefix="linkedin-studio-picture-")
    try:
        page = Path(folder) / "fit.html"
        src = f"data:{mime};base64,{base64.b64encode(body).decode('ascii')}"
        page.write_text(_FIT.format(src=html.escape(src), width=width, height=height), encoding="utf-8")
        done = subprocess.run([browser, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                               "--no-default-browser-check", "--disable-extensions", "--mute-audio",
                               f"--user-data-dir={Path(folder) / 'profile'}", "--dump-dom", "--virtual-time-budget=10000",
                               page.as_uri()],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90,
                              stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
    except subprocess.TimeoutExpired:
        raise CodexError("the browser took longer than 90 s") from None
    except OSError as exc:
        raise CodexError(f"the browser did not start: {exc}") from None
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    found = re.search(r'<pre id="out">(\d+)x(\d+) data:image/png;base64,([A-Za-z0-9+/=]+)</pre>', done.stdout or "")
    if not found:
        raise CodexError("the picture could not be read")
    png = base64.b64decode(found.group(3))
    if not png.startswith(PNG_SIGNATURE):
        raise CodexError("the browser did not make a PNG")
    return png, int(found.group(1)), int(found.group(2))


def _mime(path: Path) -> str:
    suffix = path.suffix.lower()
    return "image/png" if suffix == ".png" else "image/jpeg" if suffix in (".jpg", ".jpeg") else "image/webp"


# ---- what the studio calls ----

_studio: dict = {"codex": None, "local": None, "example": None}


def configure(cfg: Config, data_dir: Path = DATA_DIR, prefix: list[str] | None = None,
              local: Path | None = None, example: Path | None = None) -> Codex:
    """Use these settings for ChatGPT's pictures: create_app calls it with the app's own (data_dir beside its
    database). Tests give their own settings, a stand-in Codex as the prefix, and their own config files for
    set_codex_home. Until it is called, pictures are off and nothing is read."""
    old = _studio["codex"]
    if old is not None:
        old.stop_sign_in()
    made = Codex(cfg, data_dir, prefix)
    _studio.update(codex=made, local=local, example=example)
    return made


def _current() -> Codex | None:
    return _studio["codex"]


def chatgpt_ready() -> bool:
    """Can a run offer make_image now: a Codex home named, pictures allowed, the CLI found, someone signed in,
    a browser to fit the picture with. Nothing is run to say so."""
    studio = _current()
    if studio is None:
        return False
    cfg = studio.cfg
    return (cfg.images_per_request > 0 and not home_problem(cfg) and bool(studio.base_command()[0])
            and bool(who(home_of(cfg))) and bool(find_browser(cfg)))


def chatgpt_status() -> dict:
    """Settings › ChatGPT: ok, error, account and plan (who is signed in: email and plan only, never a token),
    home, today (pictures made), per_request; also version, found, path, via, signedIn, login and ready."""
    studio = _current()
    if studio is None:
        return {"ok": False, "ready": False, "error": NOT_SET_UP, "account": "", "plan": "", "home": "", "today": 0,
                "per_request": 0}
    card = studio.check()
    if card["ok"] and card["per_request"] <= 0:
        card = {**card, "ok": False, "error": "ChatGPT's pictures are off: images_per_request is 0 in config.local.toml."}
    if card["ok"] and not find_browser(studio.cfg):
        card = {**card, "ok": False, "error": "Neither Chrome nor Edge was found, so a picture cannot be fitted to "
                                              "LinkedIn's size (browser_path in config.local.toml)."}
    return {**card, "ready": bool(card["ok"])}


def chatgpt_sign_in() -> str | None:
    """Start `codex login` with the Codex home in use. None when it started, else why not."""
    studio = _current()
    return NOT_SET_UP if studio is None else studio.sign_in()


def chatgpt_stop_sign_in() -> None:
    """Stop waiting for a sign-in."""
    studio = _current()
    if studio is not None:
        studio.stop_sign_in()


def set_codex_home(home: str) -> None:
    """Keep the Codex home the owner named as codex_home in config.local.toml (empty: pictures off), and use it.
    Raises CodexError, in plain words."""
    studio = _current()
    if studio is None:
        raise CodexError(NOT_SET_UP)
    text = str(home or "").strip().strip('"').strip()
    if text and (any(ord(ch) < 32 for ch in text) or not Path(text).is_absolute() or not Path(text).parent.is_dir()):
        raise CodexError("The Codex home is a folder's whole path, like C:\\Users\\you\\.codex-personal.")
    try:
        paths.save({"codex_home": text}, _studio["local"], _studio["example"])
    except paths.ConfigError as exc:
        raise CodexError(str(exc)) from None
    studio.stop_sign_in()   # a sign-in still waiting was for the old home
    studio.cfg = dataclasses.replace(studio.cfg, codex_home=text)


def make_picture(prompt: str, shape: str, cancel=None) -> tuple[bytes, int, int, str]:
    """One picture from ChatGPT for a post, the studio's rules added to the prompt, fitted to LinkedIn's size:
    (its bytes, width, height, MIME type). `cancel`: a threading.Event-like object; set, it stops Codex at once.
    Every picture ChatGPT made is counted, even one a Stop or the time limit cut off. Raises CodexError, in the
    owner's words."""
    studio = _current()
    if studio is None:
        raise CodexError(NOT_SET_UP)
    cfg = studio.cfg
    if shape not in SHAPES:
        raise CodexError("A picture is landscape (1200 x 627) or square (1080 x 1080).")
    off = home_problem(cfg)
    if off:
        raise CodexError(off)
    if cfg.images_per_request <= 0:
        raise CodexError("ChatGPT's pictures are off: images_per_request is 0 in config.local.toml.")
    browser = find_browser(cfg)
    if not browser:   # before ChatGPT spends the allowance on a picture that could not be fitted
        raise CodexError("Neither Chrome nor Edge was found, so a picture cannot be fitted to LinkedIn's size.")
    many = 0
    try:
        made, many = studio.make(picture_prompt(prompt, shape), cancel)
    except CodexError as exc:
        many = exc.made   # made before a Stop or the time limit: it spent the allowance all the same
        raise
    finally:
        if many:
            count(cfg, many, studio.data_dir)
    try:
        png, width, height = fit(made.read_bytes(), _mime(made), shape, browser)
    except (OSError, CodexError) as exc:
        raise CodexError(f"ChatGPT made the picture, but it could not be fitted to LinkedIn's size: {exc}") from None
    return png, width, height, "image/png"
