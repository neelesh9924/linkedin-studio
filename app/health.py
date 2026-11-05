"""Settings-page checks: the skills repo's own scripts, `claude --version` and `claude auth status`, run without a
shell."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

from .claude_runner import CREATE_NO_WINDOW, ClaudeRefused, build_env
from .config import Config
from .db import DB, utcnow

SCRIPTS = {
    # name: (argv after the script path, timeout seconds)
    "check_config": (["scripts/check_config.py"], 120),
    "selftest": (["scripts/selftest.py", "--offline"], 900),
}


def venv_python() -> str:
    exe = Path(sys.executable)
    console = exe.with_name("python.exe")  # under pythonw the console twin captures output the same way
    return str(console if console.is_file() else exe)


def _flags() -> int:
    return CREATE_NO_WINDOW if os.name == "nt" else 0


class Health:
    def __init__(self, db: DB, cfg: Config):
        self.db = db
        self.cfg = cfg
        self.running: dict[str, bool] = {}
        self._procs: dict[str, subprocess.Popen] = {}

    def start(self, name: str) -> bool:
        if name not in SCRIPTS or self.running.get(name):
            return False
        self.running[name] = True
        threading.Thread(target=self._run, args=(name,), daemon=True).start()
        return True

    def _run(self, name: str) -> None:
        args, timeout = SCRIPTS[name]
        env = {k: v for k, v in os.environ.items() if k != "STUDIO_TOKEN"}
        env["NO_COLOR"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        # The skills repo's scripts open files without naming an encoding. On Windows that means
        # the legacy code page: the self-test then fails its own suite and rewrites two generated
        # files with garbled punctuation. UTF-8 mode makes them read and write what is on disk.
        env["PYTHONUTF8"] = "1"
        try:
            proc = subprocess.Popen([venv_python(), *args], cwd=str(self.cfg.skills_dir), env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                    text=True, encoding="utf-8", errors="replace", creationflags=_flags())
            self._procs[name] = proc
            try:
                out, _ = proc.communicate(timeout=timeout)
                code = proc.returncode
            except subprocess.TimeoutExpired:
                proc.kill()
                out, _ = proc.communicate()
                code, out = -1, (out or "") + f"\n[stopped after {timeout} s]"
        except OSError as exc:
            code, out = -1, f"Could not start: {exc}"
        finally:
            self._procs.pop(name, None)
            self.running[name] = False
        self.db.run("INSERT INTO health (ran_at, script, exit_code, output) VALUES (?,?,?,?)",
                    (utcnow(), name, code, (out or "")[-20000:]))

    def stop_all(self) -> None:
        for proc in list(self._procs.values()):
            try:
                proc.kill()
            except OSError:
                pass

    def latest(self, name: str | None = None):
        if name:
            return self.db.one("SELECT * FROM health WHERE script=? ORDER BY id DESC LIMIT 1", (name,))
        return self.db.one("SELECT * FROM health ORDER BY id DESC LIMIT 1")


NOT_SIGNED_IN = "Not signed in: run claude once in a terminal and sign in"


def claude_account(cfg: Config, prefix: list[str] | None = None) -> dict:
    """Who the login folder is signed in to: `claude auth status --json`, with the environment every run gets (that
    folder as CLAUDE_CONFIG_DIR, no API key). It sends Claude no request. Email and plan only; nothing is stored.

    {ok, signed_in, account, plan, error}: signed_in is None when the answer could not be read.
    """
    unread = {"ok": False, "signed_in": None, "account": "", "plan": ""}
    try:
        env = build_env(cfg)
    except ClaudeRefused as exc:
        return {**unread, "error": str(exc)}
    try:
        done = subprocess.run([*(prefix or [str(cfg.claude_bin)]), "auth", "status", "--json"], env=env,
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
                              stdin=subprocess.DEVNULL, creationflags=_flags())
        said = json.loads(done.stdout or "")
    except (OSError, subprocess.SubprocessError, ValueError):
        said = None
    if not isinstance(said, dict) or not isinstance(said.get("loggedIn"), bool):
        return {**unread, "error": "Claude Code did not say who is signed in. Run claude once in a terminal."}
    if not said["loggedIn"]:
        return {**unread, "signed_in": False, "error": NOT_SIGNED_IN}
    return {"ok": True, "signed_in": True, "account": str(said.get("email") or ""),
            "plan": str(said.get("subscriptionType") or ""), "error": ""}


def claude_version(cfg: Config) -> str:
    try:
        env = build_env(cfg)
    except ClaudeRefused as exc:
        return f"refused: {exc}"
    try:
        out = subprocess.run([str(cfg.claude_bin), "--version"], env=env, capture_output=True, text=True,
                             timeout=30, stdin=subprocess.DEVNULL, creationflags=_flags())
        return (out.stdout or out.stderr).strip() or f"exit code {out.returncode}"
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"failed: {exc}"
