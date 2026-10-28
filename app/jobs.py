"""One Claude job at a time: a queue, one worker thread, cancel, and a run log in SQLite.

A job's progress is kept as numbered steps (`jobs.activity`): each new thing Claude does, or a
studio tool says, is a step, with the time it came. A job that offers the studio's own tools (a
post's chat) gets a token good for that run only; /mcp finds the run by it.
"""
from __future__ import annotations

import hmac
import logging
import queue
import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from .claude_runner import ClaudeRefused, ClaudeRunner, RunRequest, RunResult
from .db import DB, dumps, loads, utcnow
from .skills import ACTIONS, build_request

log = logging.getLogger("studio.jobs")

# kind -> hooks that run around the Claude call. `prepare` may fetch input (Apify) or
# snapshot a file; `finish` stores side effects (plans, posts, chat messages).
Prepare = Callable[[int, dict, Callable[[str], None]], dict]
Finish = Callable[[int, dict, RunResult, dict], None]
SHOWN_STEPS = 60      # the steps a job keeps: the page shows the newest


@dataclass
class Run:
    """A job that is running with the studio's own tools: what /mcp needs to serve it."""
    job_id: int
    kind: str
    params: dict
    token: str
    tools: tuple
    cancel: threading.Event
    note: Callable[[str, str], None]
    images_left: int = 0
    images: list = field(default_factory=list)     # ids of the pictures made in this run
    versions: list = field(default_factory=list)   # ids of the versions this run wrote


class JobManager:
    def __init__(self, db: DB, runner: ClaudeRunner, mcp_url: str = ""):
        self.db = db
        self.runner = runner
        self.mcp_url = mcp_url
        self.q: queue.Queue[int | None] = queue.Queue()
        self.prepare: dict[str, Prepare] = {}
        self.finish: dict[str, Finish] = {}
        self.session_for: dict[str, Callable[[dict], str | None]] = {}
        self.carry: dict[str, Callable[[dict], dict]] = {}   # kind -> params for a new session, when its saved one is gone
        self.tools_for: dict[str, Callable[[dict], tuple]] = {}   # kind -> the studio tools a run of it gets
        self.limits: dict[str, tuple[int, int]] = {}             # kind -> (max turns, timeout seconds)
        self.images_per_request = 0     # pictures one chat request may ask ChatGPT for (config: images_per_request)
        self.chat_note = ""   # extra rule for the chat skills (see privacy.CHAT_NOTE)
        self._lock = threading.Lock()
        self._current: tuple[int, threading.Event] | None = None
        self._run: Run | None = None
        self._stopping = False
        self._worker = threading.Thread(target=self._loop, name="claude-worker", daemon=True)
        self._worker.start()

    # ---- API used by the web layer -----------------------------------------
    def submit(self, kind: str, params: dict) -> int:
        if kind not in ACTIONS:
            raise ValueError(f"unknown job kind {kind!r}")
        if self._stopping:
            raise RuntimeError("The app is shutting down.")
        job_id = self.db.run("INSERT INTO jobs (kind, status, progress, params, created_at) "
                             "VALUES (?, 'queued', 'Waiting for the previous job', ?, ?)",
                             (kind, dumps(params), utcnow()))
        self.q.put(job_id)
        return job_id

    def cancel(self, job_id: int) -> None:
        # The user asked for this, so the cancelled job needs no "it failed" card afterwards.
        self.db.run("UPDATE jobs SET acked=1 WHERE id=? AND status IN ('queued','running')", (job_id,))
        with self._lock:
            if self._current and self._current[0] == job_id:
                self._current[1].set()
                return
        self.db.run("UPDATE jobs SET status='cancelled', progress=NULL, error='Cancelled before it started.', "
                    "finished_at=? WHERE id=? AND status='queued'", (utcnow(), job_id))

    def dismiss(self, job_id: int) -> None:
        self.db.run("UPDATE jobs SET acked=1 WHERE id=?", (job_id,))

    def active(self) -> list[Any]:
        return self.db.all("SELECT * FROM jobs WHERE status IN ('queued','running') ORDER BY id")

    def run_for_token(self, token: str) -> Run | None:
        """The running job this token was made for, or None. Only while it runs."""
        with self._lock:
            run = self._run
        if run and token and hmac.compare_digest(token.encode(), run.token.encode()):
            return run
        return None

    def shutdown(self, timeout: float = 15) -> None:
        """Cancel the running job (killing its process tree) and drop the queue."""
        self._stopping = True
        self.db.run("UPDATE jobs SET status='cancelled', progress=NULL, error='The app was closed.', "
                    "finished_at=? WHERE status='queued'", (utcnow(),))
        with self._lock:
            if self._current:
                self._current[1].set()
        self.q.put(None)
        self._worker.join(timeout=timeout)

    # ---- worker ------------------------------------------------------------
    def _loop(self) -> None:
        while True:
            job_id = self.q.get()
            if job_id is None:
                return
            row = self.db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
            if row is None or row["status"] != "queued" or self._stopping:
                continue
            cancel = threading.Event()
            with self._lock:
                self._current = (job_id, cancel)
            try:
                self._run_one(job_id, row["kind"], loads(row["params"], {}), cancel)
            except Exception as exc:  # never let one job kill the worker
                log.exception("job %s crashed", job_id)
                self.db.run("UPDATE jobs SET status='failed', error=?, progress=NULL, finished_at=? WHERE id=?",
                            (f"Internal error: {exc}", utcnow(), job_id))
            finally:
                with self._lock:
                    self._current = None
                    self._run = None

    def _steps(self, job_id: int) -> Callable[[str, str], None]:
        """A job's steps: each new thing it does, numbered, with the time it came (written quietly)."""
        state = {"steps": [], "last": None}
        lock = threading.Lock()

        def step(text: str, detail: str = "") -> None:
            text, detail = str(text)[:200], str(detail)[:200]
            with lock:
                if state["last"] == (text, detail):   # the stream repeats itself; write only real changes
                    return
                state["last"] = (text, detail)
                n = len(state["steps"]) + 1 if not state["steps"] else state["steps"][-1]["n"] + 1
                state["steps"].append({"n": n, "at": datetime.now().strftime("%H:%M:%S"), "text": text, "detail": detail})
                del state["steps"][:-SHOWN_STEPS]
                self.db.run("UPDATE jobs SET progress=?, activity=?, steps=?, last_step_at=? WHERE id=?",
                            (text, dumps(state["steps"]), n, utcnow(), job_id), quiet=True)

        return step

    def _run_one(self, job_id: int, kind: str, params: dict, cancel: threading.Event) -> None:
        self.db.run("UPDATE jobs SET status='running', started_at=? WHERE id=?", (utcnow(), job_id))
        step = self._steps(job_id)
        step("Starting")

        def progress(text: str) -> None:
            step(text)

        ctx: dict = {}
        if kind in self.prepare:
            try:
                ctx = self.prepare[kind](job_id, params, progress) or {}
            except Exception as exc:
                self.db.run("UPDATE jobs SET status='failed', error=?, progress=NULL, finished_at=? WHERE id=?",
                            (str(exc), utcnow(), job_id))
                return
            params = ctx.pop("params", params)
        if cancel.is_set():
            self._close(job_id, "cancelled", None, None, "Cancelled.")
            return
        action = ACTIONS[kind]
        session = self.session_for[kind](params) if kind in self.session_for else None
        mcp = None
        if action.mcp:
            tools = tuple(self.tools_for[kind](params)) if kind in self.tools_for else ()
            run = Run(job_id=job_id, kind=kind, params=params, token=secrets.token_urlsafe(32), tools=tools,
                      cancel=cancel, note=step, images_left=self.images_per_request if "make_image" in tools else 0)
            with self._lock:
                self._run = run
            ctx["run"] = run
            mcp = {"url": self.mcp_url, "token": run.token, "tools": tools}

        def request(params: dict, session: str | None) -> RunRequest:
            req = build_request(kind, params, resume_session=session, mcp=mcp)
            if kind in self.limits:
                req.max_turns, req.timeout = self.limits[kind]
            if action.chat:
                req.system += self.chat_note
            return req

        req = request(params, session)
        started = utcnow()
        try:
            result = self.runner.run(req, cancel=cancel, on_progress=progress)
            if session and kind in self.carry and result.outcome == "error" and not result.num_turns:
                # The saved session could not be resumed (Claude Code clears old ones, and each login folder keeps
                # its own): a new one starts with the conversation so far, and the finish hook keeps it from here.
                self._log_run(job_id, req.skill, started, result)
                progress("Picking the conversation up in a new session")
                params = self.carry[kind](params)
                req, started = request(params, None), utcnow()
                result = self.runner.run(req, cancel=cancel, on_progress=progress)
        except ClaudeRefused as exc:
            self._log_run(job_id, req.skill, started, RunResult(outcome="refused", error=str(exc)))
            if kind in self.finish:   # a chat says in its thread that the reply did not come
                try:
                    self.finish[kind](job_id, params, RunResult(outcome="refused", error=str(exc)), ctx)
                except Exception:
                    log.exception("finish hook for refused job %s failed", job_id)
            self._close(job_id, "failed", None, None, str(exc))
            return
        finally:
            with self._lock:
                self._run = None
        self._log_run(job_id, req.skill, started, result)
        status = {"ok": "done", "unparsed": "unparsed", "cancelled": "cancelled"}.get(result.outcome, "failed")
        if kind in self.finish and (status in ("done", "unparsed") or action.chat):
            try:
                self.finish[kind](job_id, params, result, ctx)
            except Exception as exc:
                log.exception("finish hook for job %s failed", job_id)
                status, result.error = "failed", f"Could not save the result: {exc}"
        raw = result.text if status == "unparsed" else (result.clean_text or result.text)
        self._close(job_id, status, result.data, raw, result.error or result.parse_error)

    def _close(self, job_id: int, status: str, data: Any, raw: str | None, error: str | None) -> None:
        self.db.run("UPDATE jobs SET status=?, result=?, raw_text=?, error=?, progress=NULL, finished_at=? "
                    "WHERE id=?", (status, dumps(data) if data is not None else None, raw, error, utcnow(), job_id))

    def _log_run(self, job_id: int, skill: str, started: str, r: RunResult) -> None:
        u = r.usage or {}
        self.db.run(
            "INSERT INTO runs (job_id, skill, started_at, duration_ms, exit_code, outcome, num_turns, input_tokens, "
            "output_tokens, cache_read_tokens, cache_creation_tokens, cost_usd, session_id, skill_invoked, denials, error) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (job_id, skill, started, r.duration_ms, r.exit_code, r.outcome, r.num_turns, u.get("input_tokens"),
             u.get("output_tokens"), u.get("cache_read_input_tokens"), u.get("cache_creation_input_tokens"),
             r.cost_usd, r.session_id, int(r.skill_invoked), len(r.denials or []), (r.error or "")[:500] or None))


def wait_for(db: DB, job_id: int, timeout: float = 300) -> Any:
    """Test/CLI helper: block until a job leaves the queue."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        row = db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
        if row and row["status"] not in ("queued", "running"):
            return row
        time.sleep(0.2)
    raise TimeoutError(f"job {job_id} still running")
