"""LinkedIn Studio: a JSON API on FastAPI, bound to 127.0.0.1 only, and the page that uses it (static/).

The page asks /api/state every two seconds (the posts, the jobs under way, `rev`, which changes
whenever something it shows was written) and fetches what it shows again only when that changed.
With check_publora, each ask also kicks the light check (status_check.py), which never holds it up.
Each area of the API is its own module: api_posts (a post, its chat, versions and picture),
api_trash (the posts moved to the Trash), api_pages (Planner, Story Bank & Voice, Tools, Settings,
setup, the Guide).
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import codex, flows, images, mcp, privacy, render
from .claude_runner import ClaudeRunner
from .config import DATA_DIR, HOST, Config, path_problems
from .db import DB, loads
from .health import Health
from .jobs import JobManager
from .publishing import POST_MAX, SLOT, Publisher, linkedin_link
from .security import LocalOnly
from .skills import ACTIONS
from .status_check import StatusCheck

HERE = Path(__file__).resolve().parent
ACTIVE = ("queued", "running")
PROBLEM = ("failed", "unparsed")
STATUS_LABEL = {"draft": "Draft", "approved": "Approved", "scheduling": "Sending", "scheduled": "Scheduled",
                "published": "Published", "failed": "Failed", "cancelled": "Cancelled"}
STATUS_KIND = {"draft": "", "approved": "ready", "scheduling": "busy", "scheduled": "ok", "published": "ok",
               "failed": "bad", "cancelled": "warn"}
ORDER = {"draft": 0, "approved": 1, "failed": 2, "scheduling": 3, "scheduled": 4, "published": 5, "cancelled": 6}
TRASHED_LABEL = "In the Trash"
TARGET = {"min": 900, "max": 1300, "hard": POST_MAX, "fold": 210}
MAX_BODY = 1_000_000
SETUP_OPEN = ("/api/state", "/api/setup", "/api/guide", "/api/quit")   # what works before the folders are set


def first_line(text: str | None) -> str:
    return next((line.strip() for line in (text or "").splitlines() if line.strip()), "")


@dataclass
class Studio:
    """Everything the API's areas share."""
    cfg: Config
    db: DB
    jobs: JobManager
    pub: Publisher
    health: Health
    protection: privacy.Protection
    needs_setup: bool
    tz_label: str
    checker: StatusCheck
    instance: str = field(default_factory=lambda: uuid.uuid4().hex)
    on_quit: Callable[[], None] | None = None
    on_restart: Callable[[], None] | None = None
    seq: int = 0

    @property
    def mode_file(self) -> dict[str, Path]:
        return {"bank": self.cfg.story_bank, "voice": self.cfg.voice_profile}

    # ---- words and times ----
    def when(self, value: str | None, year: bool = False) -> str:
        return render.local_time(value, self.cfg.tz, self.tz_label, year) if value else ""

    def clock(self, value: str | None) -> str:
        return render.clock(value, self.cfg.tz) if value else ""

    def ago(self, value: str | None) -> str:
        return render.ago(value, self.cfg.tz) if value else ""

    # ---- rows the page reads ----
    def post_summary(self, row) -> dict:
        """A post as the list, the Planner and the Trash show it. One in the Trash says so (the Planner's card). `link`:
        a published post on LinkedIn, once Publora gave its address (only ever a https://www.linkedin.com/ one)."""
        busy = self.post_busy(row["id"])
        keys = row.keys()
        trashed = bool(row["trashed_at"]) if "trashed_at" in keys else False
        link = linkedin_link(row["published_url"]) if "published_url" in keys and row["status"] == "published" else None
        return {"id": row["id"], "title": row["title"], "first": first_line(row["text"]) or "Nothing written yet",
                "status": row["status"], "label": TRASHED_LABEL if trashed else STATUS_LABEL.get(row["status"], row["status"]),
                "kind": "" if trashed else STATUS_KIND.get(row["status"], ""), "when": self.when(row["scheduled_at"]),
                "scheduled_at": row["scheduled_at"], "picture": bool(row["picture_id"]), "busy": busy, "trashed": trashed,
                "link": link}

    def post_busy(self, post_id: int) -> bool:
        """Claude is writing (or waiting to write) this post's chat reply: its text waits until it is done."""
        return self.db.one("SELECT 1 FROM jobs WHERE kind='post_chat' AND status IN ('queued','running') "
                           "AND json_extract(params,'$.post_id')=?", (post_id,)) is not None

    def post_working(self, post_id: int) -> bool:
        """Any job of Claude's for this post runs or waits: its chat, an audit or a revision."""
        return self.db.one("SELECT 1 FROM jobs WHERE status IN ('queued','running') AND json_extract(params,'$.post_id')=?",
                           (post_id,)) is not None

    def job_public(self, row) -> dict:
        params = loads(row["params"], {})
        kind = row["kind"]
        action = ACTIONS.get(kind)
        now = datetime.now(timezone.utc)
        began = render.parse_utc(row["started_at"] or row["created_at"] or "")
        last = render.parse_utc(row["last_step_at"] or "") if row["last_step_at"] else began
        running = row["status"] == "running"
        out = {"id": row["id"], "kind": kind, "status": row["status"], "title": action.title if action else kind,
               "doing": action.doing if action else "Working",
               "progress": ("Queued: waiting for the current job" if row["status"] == "queued"
                            else (row["progress"] or "Starting")),
               "activity": loads(row["activity"], []) or [], "steps": row["steps"] or 0,
               "seconds": int((now - began).total_seconds()) if began and running else 0,
               "quiet": int((now - last).total_seconds()) if last and running else 0,
               "post_id": params.get("post_id"), "conversation_id": params.get("conversation_id"),
               "plan_item_id": params.get("plan_item_id"), "source": params.get("source"),
               "acked": bool(row["acked"]), "error": row["error"] or "",
               "raw": row["raw_text"] if row["status"] == "unparsed" else "",
               "finished": row["finished_at"], "href": self.job_href(kind, params, row["status"])}
        out["summary"] = self.job_summary(out)
        return out

    @staticmethod
    def job_href(kind: str, params: dict, status: str) -> str:
        if params.get("post_id"):
            return f"#post-{params['post_id']}"
        if kind == "draft" and params.get("plan_item_id") and status != "done":
            return "#~planner"
        return {"plan": "#~planner", "draft": "#~planner", "interview": "#~bank", "voice": "#~voice"}.get(kind, f"#~tools-{kind}")

    @staticmethod
    def job_summary(job: dict) -> str:
        kind, status = job["kind"], job["status"]
        title = ACTIONS[kind].title if kind in ACTIONS else kind
        if status == "done":
            return {"draft": "Your draft is ready", "plan": "Your week plan is ready", "audit": "The audit is done",
                    "revise": "A revised version is ready", "interview": "The interviewer replied",
                    "voice": "Your voice profile chat has a reply", "post_chat": "Claude replied"}.get(kind, f"{title} is done")
        if status == "cancelled":
            return f"{title}: stopped"
        if status in PROBLEM:
            return f"{title} did not finish"
        return ""


def create_app(cfg: Config, token: str, *, db_path: Path | None = None, runner: ClaudeRunner | None = None,
               publisher: Publisher | None = None, check_publora: bool = False,
               on_quit: Callable[[], None] | None = None, on_restart: Callable[[], None] | None = None) -> FastAPI:
    """`check_publora`: the light check asks Publora whether due posts went out (status_check.py). Off unless asked
    for: launch.py, `python -m app` and the demo turn it on; the tests' studios never reach Publora by themselves."""
    if HOST != "127.0.0.1":
        raise RuntimeError("LinkedIn Studio only binds 127.0.0.1.")
    # The config is read once, at start. If its folders are wrong, the page shows the setup screen.
    needs_setup = bool(path_problems(cfg))
    db = DB(db_path or DATA_DIR / "studio.db")
    jobs = JobManager(db, runner or ClaudeRunner(cfg), mcp_url=f"{cfg.origin}/mcp")
    codex.configure(cfg, data_dir=db.path.parent)   # ChatGPT's pictures: this app's settings, counted beside its database
    flows.register(jobs, db, cfg)
    protection = privacy.protect(cfg.skills_dir)   # the Story Bank and voice profile stay out of git
    if protection.state == "protected":
        jobs.chat_note = privacy.CHAT_NOTE
    pub = publisher or Publisher(db, cfg)
    health = Health(db, cfg)
    checker = StatusCheck(db, pub, enabled=check_publora and not needs_setup)   # never during setup
    studio = Studio(cfg=cfg, db=db, jobs=jobs, pub=pub, health=health, protection=protection,
                    needs_setup=needs_setup, tz_label=datetime.now(cfg.tz).tzname() or "", checker=checker,
                    on_quit=on_quit, on_restart=on_restart)
    tools = mcp.Studio(db=db, cfg=cfg, fetch_post=flows.fetch_post_text)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        jobs.shutdown()          # cancels the running Claude job and kills its process tree
        health.stop_all()
        codex.chatgpt_stop_sign_in()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def setup_first(request: Request, call_next):
        """With the folders wrong, nothing but the setup screen works (inside LocalOnly: signed-in requests only)."""
        path = request.url.path
        if needs_setup and path.startswith("/api/") and not path.startswith(SETUP_OPEN):
            return JSONResponse({"error": "Tell the studio where its three folders are first.", "setup": True},
                                status_code=409)
        return await call_next(request)

    app.add_middleware(LocalOnly, token=token, port=cfg.port)   # added last, so it runs first
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    app.state.studio, app.state.tools = studio, tools
    app.state.db, app.state.jobs, app.state.publisher, app.state.health = db, jobs, pub, health
    app.state.checker = checker

    @app.get("/health")
    def health_check():
        return {"ok": True, "app": "linkedin-studio", "instance": studio.instance, "pid": os.getpid()}

    @app.get("/")
    def page():
        return FileResponse(HERE / "static" / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/api/state")
    def state():
        studio.seq += 1
        rows = db.all("SELECT * FROM posts WHERE trashed_at IS NULL")   # the Trash's are on its own page
        checker.kick(rows)   # in the background, when a scheduled post is due: this answer never waits for Publora
        rows.sort(key=lambda r: (ORDER.get(r["status"], 9),
                                 (r["scheduled_at"] or "") if r["status"] in ("scheduling", "scheduled") else "",
                                 -r["id"] if r["status"] not in ("scheduling", "scheduled") else 0))
        active = [studio.job_public(r) for r in jobs.active()]
        ended = db.all("SELECT * FROM jobs WHERE status NOT IN ('queued','running') AND finished_at IS NOT NULL "
                       "ORDER BY finished_at DESC, id DESC LIMIT 12")
        return {"seq": studio.seq, "rev": db.rev, "instance": studio.instance, "setup": needs_setup,
                "tz": studio.tz_label, "posts": [studio.post_summary(r) for r in rows], "jobs": active,
                "ended": [studio.job_public(r) for r in ended], "chatgpt": codex.chatgpt_ready(),
                "target": TARGET, "slot": SLOT.pattern}

    @app.post("/api/quit")
    def quit_app():
        if on_quit:
            threading.Timer(0.5, on_quit).start()
        return {"ok": True}

    # ---- jobs ------------------------------------------------------------------------
    def job_row(job_id: int):
        return db.one("SELECT * FROM jobs WHERE id=?", (job_id,))

    @app.post("/api/jobs/{job_id}/cancel")
    def job_cancel(job_id: int):
        jobs.cancel(job_id)
        return {"ok": True}

    @app.post("/api/jobs/{job_id}/retry")
    def job_retry(job_id: int):
        row = job_row(job_id)
        if row is None or row["status"] in ACTIVE or ACTIONS[row["kind"]].chat:
            return JSONResponse({"error": "That job cannot be run again."}, status_code=422)
        jobs.dismiss(job_id)
        return {"job": jobs.submit(row["kind"], loads(row["params"], {}))}

    @app.post("/api/jobs/{job_id}/dismiss")
    def job_dismiss(job_id: int):
        if job_row(job_id) is None:
            return JSONResponse({"error": "That job no longer exists."}, status_code=404)
        jobs.dismiss(job_id)
        return {"ok": True}

    # ---- pictures ----------------------------------------------------------------------
    @app.get("/api/image/{image_id}")
    def image(image_id: int):
        row = db.one("SELECT * FROM images WHERE id=?", (image_id,))
        path = images.path_of(db, row)
        if path is None:
            return JSONResponse({"error": "That picture is not here."}, status_code=404)
        return FileResponse(path, media_type=row["mime"], headers={"Cache-Control": "private, max-age=31536000, immutable",
                                                                   "X-Content-Type-Options": "nosniff"})

    # ---- the studio's tools, for Claude ----------------------------------------------
    @app.post("/mcp")
    async def mcp_endpoint(request: Request):
        scheme, _, given = request.headers.get("authorization", "").partition(" ")
        run = jobs.run_for_token(given) if scheme == "Bearer" else None
        if run is None:
            return JSONResponse({"error": "No running request for this token."}, status_code=401)
        body = await request.body()
        if len(body) > MAX_BODY:
            return JSONResponse({"error": "Too large."}, status_code=413)
        try:
            message = json.loads(body)
        except ValueError:
            return JSONResponse({"error": "Bad request."}, status_code=400)
        reply = await _in_thread(mcp.handle, message, run, tools)
        if reply is None:
            return Response(status_code=202)
        return JSONResponse(reply)

    from . import api_pages, api_posts, api_trash  # noqa: PLC0415  (they use Studio, above)

    api_posts.register(app, studio)
    api_trash.register(app, studio)
    api_pages.register(app, studio)
    return app


async def _in_thread(fn: Callable, *args: Any):
    """A tool may take minutes (a picture): run it off the event loop."""
    from starlette.concurrency import run_in_threadpool  # noqa: PLC0415

    return await run_in_threadpool(fn, *args)
