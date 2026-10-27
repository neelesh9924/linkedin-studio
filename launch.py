"""Start LinkedIn Studio: check config, start the server, open an app window, stop when it closes.

Run by "Launch LinkedIn Studio.vbs" with .venv\\Scripts\\pythonw.exe (no console). With --setup
(first run, visible console) it creates the venv and installs requirements.txt first. After an
update that changed requirements.txt, the next start installs it again (no console; the log says
how it went) before the app starts.

If the folders in the config are missing or wrong (always the case on a new PC), the app still
starts and shows its setup screen. Saving there ends this process and starts a fresh one, which
reads the new config.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
VENV_PY = VENV / "Scripts" / "python.exe"
VENV_PYW = VENV / "Scripts" / "pythonw.exe"
REQUIREMENTS = ROOT / "requirements.txt"
STAMP = VENV / "requirements.sha256"     # the requirements.txt the venv was last installed from
DATA = ROOT / "data"
SESSION = DATA / "session.json"
LOG = DATA / "studio.log"
PROFILE = DATA / "browser-profile"
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000


def requirements_hash() -> str:
    return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()


def install_requirements(console: bool) -> bool:
    """pip install -r requirements.txt into the venv; the stamp is written once it worked."""
    want = requirements_hash()
    cmd = [str(VENV_PY), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(REQUIREMENTS)]
    if console:
        done = subprocess.run(cmd)
    else:
        done = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
        log("pip: " + (done.stdout or "").strip()[-1500:].replace("\n", " | "))
        if done.returncode:
            log("pip failed: " + (done.stderr or "").strip()[-1500:].replace("\n", " | "))
    if done.returncode == 0:
        STAMP.write_text(want, encoding="utf-8")
    return done.returncode == 0


def requirements_changed() -> bool:
    try:
        return STAMP.read_text(encoding="utf-8").strip() != requirements_hash()
    except OSError:
        return True


# ---------------------------------------------------------------- first run ----
def setup() -> int:
    print("LinkedIn Studio - first-run setup\n")
    try:
        if sys.version_info < (3, 11):
            raise RuntimeError(f"Python 3.11 or newer is needed; this is {sys.version.split()[0]}.")
        if not VENV_PY.is_file():
            print(f"Creating the virtual environment in {VENV} ...")
            subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
        print("Installing pinned packages from requirements.txt ...\n")
        if not install_requirements(console=True):
            raise RuntimeError("pip could not install requirements.txt (see above).")
        print("\nSetup done. Starting LinkedIn Studio; this window closes in a few seconds.")
        subprocess.Popen([str(VENV_PYW), str(ROOT / "launch.py")], cwd=str(ROOT),
                         creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP, close_fds=True)
        time.sleep(4)
        return 0
    except Exception as exc:  # show it; this console is the only place it can be seen
        print(f"\nSetup failed: {exc}")
        input("Press Enter to close this window.")
        return 1


# ---------------------------------------------------------------- helpers -------
def log(msg: str) -> None:
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


def quiet_logs() -> None:
    """pythonw has no stdout/stderr; send both to data/studio.log."""
    DATA.mkdir(parents=True, exist_ok=True)
    if sys.stdout is None or sys.stderr is None or "pythonw" in Path(sys.executable).name.lower():
        stream = open(LOG, "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = stream


def http_json(url: str, timeout: float = 2.0) -> dict | None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (OSError, ValueError):
        return None


def port_free(port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        sock.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def registry_app_path(exe: str) -> str | None:
    import winreg

    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}") as key:
                value, _ = winreg.QueryValueEx(key, "")
                if value and Path(value.strip('"')).is_file():
                    return value.strip('"')
        except OSError:
            continue
    return None


def find_browser(override: str) -> str | None:
    if override:
        return override if Path(override).is_file() else None
    env = os.environ
    chrome = [Path(env.get(v, "")) / "Google" / "Chrome" / "Application" / "chrome.exe"
              for v in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA") if env.get(v)]
    edge = [Path(env.get(v, "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            for v in ("ProgramFiles(x86)", "ProgramFiles") if env.get(v)]
    for found in (registry_app_path("chrome.exe"), *map(str, chrome),
                  registry_app_path("msedge.exe"), *map(str, edge)):
        if found and Path(found).is_file():
            return found
    return None


def open_window(browser: str, url: str) -> subprocess.Popen:
    return subprocess.Popen([browser, f"--app={url}", f"--user-data-dir={PROFILE}",
                             "--no-first-run", "--no-default-browser-check"], cwd=str(ROOT))


def kill_tree(pid: int) -> None:
    import psutil

    try:
        root = psutil.Process(pid)
        family = root.children(recursive=True) + [root]
    except psutil.Error:
        return
    for p in family:
        try:
            p.kill()
        except psutil.Error:
            pass
    psutil.wait_procs(family, timeout=5)


# Shown from a file:// URL when the server cannot start, so it carries its own few styles.
ERROR_STYLE = """
:root { color-scheme: light dark; --bg: #f4f5f8; --card: #fff; --line: #e4e7ed; --text: #141821; --soft: #465061;
  --bad: #b92c1b; --bad-soft: #fde8e4; --code: #f1f3f7; }
@media (prefers-color-scheme: dark) { :root { --bg: #0d0f13; --card: #15181e; --line: #232831; --text: #e9ecf2;
  --soft: #b2b9c8; --bad: #ff8573; --bad-soft: #3a1914; --code: #1c2028; } }
body { margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 24px; background: var(--bg);
  color: var(--text); font: 15px/1.55 "Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif; }
main { max-width: 560px; padding: 26px 28px; border: 1px solid var(--line); border-radius: 14px; background: var(--card); }
h1 { margin: 0 0 14px; font-size: 20px; letter-spacing: -.01em; }
.why { margin: 0 0 10px; padding: 11px 14px; border-radius: 10px; background: var(--bad-soft); color: var(--bad); }
.next { margin: 14px 0 0; color: var(--soft); font-size: 13.5px; }
code { padding: .1em .35em; border-radius: 5px; background: var(--code); font: 12.5px "Cascadia Code", Consolas, monospace;
  overflow-wrap: anywhere; }
"""
ERROR_PAGE = """<!doctype html><html lang="en"><meta charset="utf-8"><title>LinkedIn Studio cannot start</title>
<style>{style}</style><body><main>
<h1>LinkedIn Studio cannot start</h1>{items}
<p class="next">Fix the above in <code>{config}</code>, close this window and open LinkedIn Studio again.
Details are in <code>{log}</code>. See README &gt; Troubleshooting.</p></main></body></html>"""


def fail(reasons: list[str], browser_override: str = "") -> int:
    for r in reasons:
        log(f"cannot start: {r}")
    DATA.mkdir(parents=True, exist_ok=True)
    page = DATA / "launch-error.html"
    page.write_text(ERROR_PAGE.format(style=ERROR_STYLE,
                                      items="".join(f'<p class="why">{html.escape(r)}</p>' for r in reasons),
                                      config=html.escape(str(ROOT / "config.local.toml")), log=html.escape(str(LOG))),
                    encoding="utf-8")
    browser = find_browser(browser_override)
    if browser:
        subprocess.Popen([browser, f"--app={page.as_uri()}", f"--user-data-dir={PROFILE}",
                          "--no-first-run", "--no-default-browser-check"])
    else:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, "\n\n".join(reasons), "LinkedIn Studio cannot start", 0x10)
    return 1


# ---------------------------------------------------------------- main ----------
def main() -> int:
    if "--setup" in sys.argv:
        return setup()
    if Path(sys.prefix).resolve() != VENV.resolve():
        return setup()  # started with a system Python: build the venv, then relaunch inside it
    quiet_logs()
    if requirements_changed():
        log("requirements.txt changed since the last install: installing it")
        install_requirements(console=False)   # if it fails (offline), the app still starts; the log says why
    sys.path.insert(0, str(ROOT))
    from app.config import ConfigError, load_config, path_problems, problems

    try:
        cfg = load_config()
    except ConfigError as exc:
        return fail([str(exc)])
    for_setup_screen = set(path_problems(cfg).values())    # fixed inside the app, so no reason to stop here
    issues = [p for p in problems(cfg) if p not in for_setup_screen]
    if issues:
        return fail(issues, cfg.browser_path)
    if for_setup_screen:
        log("folders are not set up yet; the app will open its setup screen")
    browser = find_browser(cfg.browser_path)
    if not browser:
        return fail(["No browser found: set browser_path in config.local.toml to chrome.exe or msedge.exe."
                     if cfg.browser_path else "Neither Chrome nor Edge was found."], cfg.browser_path)

    # Single instance: if our server already runs, just open another window onto it.
    if SESSION.is_file():
        try:
            sess = json.loads(SESSION.read_text(encoding="utf-8"))
        except ValueError:
            sess = {}
        info = http_json(f"http://127.0.0.1:{sess.get('port')}/health") if sess.get("port") else None
        if info and info.get("app") == "linkedin-studio" and info.get("instance") == sess.get("instance"):
            log("already running; opening another window")
            open_window(browser, f"http://127.0.0.1:{sess['port']}/auth?token={sess['token']}")
            return 0
    if not port_free(cfg.port):
        return fail([f"Port {cfg.port} on 127.0.0.1 is in use by another program. Set a different port in "
                     f"config.local.toml (for example {cfg.port + 1})."], cfg.browser_path)

    import uvicorn
    from app.main import create_app

    token = secrets.token_urlsafe(32)
    holder: dict = {}
    def restart() -> None:      # the setup screen saved new folders: stop, then start again (below)
        holder["restart"] = True
        holder["server"].should_exit = True

    app = create_app(cfg, token, on_quit=lambda: setattr(holder["server"], "should_exit", True), on_restart=restart)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=cfg.port, log_config=None,
                                           access_log=False, lifespan="on", timeout_graceful_shutdown=5))
    holder["server"] = server
    thread = threading.Thread(target=server.run, name="uvicorn", daemon=True)
    thread.start()

    base = f"http://127.0.0.1:{cfg.port}"
    info = None
    for _ in range(100):
        if not thread.is_alive():
            break
        info = http_json(base + "/health", timeout=1)
        if info and info.get("app") == "linkedin-studio":
            break
        time.sleep(0.2)
    if not info:
        server.should_exit = True
        return fail([f"The server did not start on {base}. See {LOG}."], cfg.browser_path)
    SESSION.write_text(json.dumps({"port": cfg.port, "token": token, "instance": info["instance"],
                                   "pid": os.getpid()}), encoding="utf-8")
    log(f"server up on {base} (pid {os.getpid()}); opening {Path(browser).name}")

    window = open_window(browser, f"{base}/auth?token={token}")
    try:
        while True:
            if window.poll() is not None:
                log("window closed; shutting down")
                break
            if not thread.is_alive():
                log("server stopped (%s); closing the window" % ("new folders saved" if holder.get("restart") else "Quit"))
                kill_tree(window.pid)
                break
            time.sleep(0.5)
    finally:
        server.should_exit = True
        thread.join(timeout=30)
        try:
            SESSION.unlink()
        except OSError:
            pass
        log("stopped")
    if holder.get("restart"):
        log("starting again with the saved folders")
        subprocess.Popen([str(VENV_PYW), str(ROOT / "launch.py")], cwd=str(ROOT),
                         creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP, close_fds=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
