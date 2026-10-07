"""LinkedIn Studio web app: FastAPI + Jinja2 + HTMX, bound to 127.0.0.1 only.

Pages render from the database. While a Claude job runs, its card polls `/jobs/<id>/tick`
for progress text; when the job ends the tick fires a `jobs-changed` event and the page
region that shows that job re-fetches itself, so nothing reloads and nothing flickers.
"""
from __future__ import annotations

import html
import json
import os
import re
import subprocess
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader

from . import flows, guide, paths, privacy, render
from .claude_runner import ClaudeRunner
from .config import DATA_DIR, HOST, Config, ConfigError, path_problems, problems
from .db import DB, loads, utcnow
from .health import Health, claude_version
from .icons import icon, logo
from .jobs import JobManager
from .publishing import (DASHBOARD_URL, FIRST_COMMENT_MAX, MAX_AHEAD, MIN_LEAD, POST_MAX, SLOT, Publisher,
                         ScheduleError, placeholder_slots)
from .security import LocalOnly
from .skills import ACTIONS, REVISION_LABELS, REVISIONS, TOOL_KINDS

HERE = Path(__file__).resolve().parent
INSTANCE = uuid.uuid4().hex
GOALS = ("comments", "reposts", "likes", "saves")
ACTIVE = ("queued", "running")
PROBLEM = ("failed", "unparsed")
TARGET = {"min": 900, "max": 1300, "hard": POST_MAX, "fold": 210}
STATUS_LABEL = {"draft": "Draft", "approved": "Approved", "scheduling": "Sending", "scheduled": "Scheduled",
                "published": "Published", "failed": "Failed", "cancelled": "Cancelled"}
REACTIONS = {"LIKE": "Like", "PRAISE": "Celebrate", "EMPATHY": "Love", "INTEREST": "Insightful",
             "APPRECIATION": "Support", "ENTERTAINMENT": "Funny"}
# Messages shown once after a redirect: /drafts/3?done=approved. Only these keys are accepted.
FLASH = {
    "approved": ("ok", "Approved. Pick a time and schedule it."),
    "draft": ("info", "Back in draft. You can edit it again."),
    "scheduled": ("ok", "Scheduled on Publora."),
    "cancelled": ("info", "Cancelled on Publora."),
    "revised": ("ok", "Revision applied."),
    "discarded": ("info", "Revision discarded."),
    "deleted": ("info", "Draft deleted."),
    "created": ("ok", "Saved as a new draft."),
    "refreshed": ("info", "Status updated from Publora."),
}
MODES = {"bank": "interview", "voice": "voice"}
MODE_TITLE = {"bank": "Story Bank", "voice": "Voice profile"}


def create_app(cfg: Config, token: str, *, db_path: Path | None = None, runner: ClaudeRunner | None = None,
               publisher: Publisher | None = None, on_quit: Callable[[], None] | None = None,
               on_restart: Callable[[], None] | None = None) -> FastAPI:
    if HOST != "127.0.0.1":
        raise RuntimeError("LinkedIn Studio only binds 127.0.0.1.")
    # The config is read once, at start. If its folders are wrong, every page leads to the setup screen.
    needs_setup = bool(path_problems(cfg))
    db = DB(db_path or DATA_DIR / "studio.db")
    jobs = JobManager(db, runner or ClaudeRunner(cfg))
    flows.register(jobs, db, cfg)
    protection = privacy.protect(cfg.skills_dir)   # the Story Bank and voice profile stay out of git
    if protection.state == "protected":
        jobs.chat_note = privacy.CHAT_NOTE
    pub = publisher or Publisher(db, cfg)
    health = Health(db, cfg)
    tz_label = datetime.now(cfg.tz).tzname() or ""
    mode_file = {"bank": cfg.story_bank, "voice": cfg.voice_profile}

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        jobs.shutdown()          # cancels the running Claude job and kills its process tree
        health.stop_all()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(LocalOnly, token=token, port=cfg.port)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    app.state.db, app.state.jobs, app.state.publisher, app.state.health = db, jobs, pub, health

    env = Environment(loader=FileSystemLoader(HERE / "templates"), autoescape=True, trim_blocks=True,
                      lstrip_blocks=True)
    templates = Jinja2Templates(env=env)
    env.filters.update(
        local=lambda v, year=False: render.local_time(v, cfg.tz, tz_label, year),
        clock=lambda v: render.local_time(v, cfg.tz),
        ago=lambda v: render.ago(v, cfg.tz),
        fromjson=lambda s, d=None: loads(s, d),
        chars=lambda s: len(s or ""),
        num=lambda n: f"{int(n or 0):,}",
        md=render.md,
        wdiff=render.wdiff,
        udiff=render.udiff,
        diffstat=render.diffstat,
        excerpt=lambda s: next((ln.strip() for ln in (s or "").splitlines() if ln.strip()), ""),
    )
    env.globals.update(icon=icon, logo=logo, actions=ACTIONS, tool_kinds=TOOL_KINDS, revisions=REVISION_LABELS,
                       goals=GOALS, cfg=cfg, dashboard_url=DASHBOARD_URL, first_comment_max=FIRST_COMMENT_MAX,
                       status_label=STATUS_LABEL, target=TARGET, slot_pattern=SLOT.pattern, reactions=REACTIONS,
                       mode_title=MODE_TITLE, tz_label=tz_label, asset_v=INSTANCE[:8])

    # ---- response helpers ----------------------------------------------------------
    def page(request: Request, template: str, /, **ctx) -> Response:
        if needs_setup and template != "setup.html":
            return RedirectResponse("/setup", status_code=303)
        ctx.setdefault("nav", template.split(".")[0])
        ctx["flash"] = FLASH.get(request.query_params.get("done", ""))
        return templates.TemplateResponse(request, template, ctx)

    def partial(request: Request, template: str, /, trigger: dict | None = None, **ctx) -> HTMLResponse:
        resp = templates.TemplateResponse(request, template, ctx)
        if trigger:
            resp.headers["HX-Trigger"] = json.dumps(trigger)
        return resp

    def nothing(trigger: dict | None = None, **headers: str) -> Response:
        if trigger:
            headers["HX-Trigger"] = json.dumps(trigger)
        return Response(status_code=204, headers=headers)

    def go(url: str) -> Response:
        return Response(status_code=204, headers={"HX-Redirect": url})

    def fail(text: str, status: int = 422) -> JSONResponse:
        return JSONResponse({"error": text}, status_code=status)

    def toast(text: str, kind: str = "ok") -> dict:
        return {"toast": {"text": text, "kind": kind}}

    def changed(kind: str, job_id: int = 0, status: str = "") -> dict:
        return {"jobs-changed": {"id": job_id, "kind": kind, "status": status}}

    # ---- queries -------------------------------------------------------------------
    def job_row(job_id: int):
        return db.one("SELECT * FROM jobs WHERE id=?", (job_id,))

    def jobs_for(field: str, value: int, kinds: tuple[str, ...]) -> list:
        marks = ",".join("?" * len(kinds))
        return db.all(f"SELECT * FROM jobs WHERE kind IN ({marks}) AND json_extract(params, '$.{field}')=? "
                      "ORDER BY id DESC", (*kinds, value))

    def visible(job) -> bool:
        """A job the page should still show: running, or a problem nobody dismissed yet."""
        return job["status"] in ACTIVE or (job["status"] in PROBLEM and not job["acked"])

    def posts_by_id(ids: list[int]) -> dict[int, Any]:
        ids = [i for i in ids if i]
        if not ids:
            return {}
        rows = db.all(f"SELECT * FROM posts WHERE id IN ({','.join('?' * len(ids))})", tuple(ids))
        return {r["id"]: r for r in rows}

    def doc_status(text: str) -> dict:
        found = dict(re.findall(r"^-\s*(filled|updated|sessions|source):\s*(.*)$", text, flags=re.M))
        # A value still in (parentheses) is the template's own hint, not something a skill wrote.
        status = {k: "" if v.strip().startswith("(") else v.strip() for k, v in found.items()}
        status["is_filled"] = status.get("filled", "").lower().startswith("yes")
        return status

    # ---- health / quit -------------------------------------------------------------
    @app.get("/health")
    def health_check():
        return JSONResponse({"ok": True, "app": "linkedin-studio", "instance": INSTANCE, "pid": os.getpid()})

    @app.post("/quit")
    def quit_app(request: Request):
        if on_quit:
            threading.Timer(0.5, on_quit).start()
        return partial(request, "_quit.html")

    # ---- jobs ------------------------------------------------------------------------
    @app.get("/jobs/active")
    def jobs_active(request: Request):
        return partial(request, "_activity.html", active=jobs.active())

    @app.get("/jobs/{job_id}/tick")
    def job_tick(job_id: int):
        row = job_row(job_id)
        if row is None or row["status"] not in ACTIVE:
            detail = {"id": job_id, "kind": row["kind"] if row else "", "status": row["status"] if row else "gone"}
            return Response("", status_code=286, headers={"HX-Trigger": json.dumps({"jobs-changed": detail})})
        text = "Queued: waiting for the current job" if row["status"] == "queued" else (row["progress"] or "Starting")
        return HTMLResponse(html.escape(text))

    @app.get("/jobs/{job_id}/summary")
    def job_summary(job_id: int):
        row = job_row(job_id)
        if row is None:
            return JSONResponse({"silent": True})
        kind, params = row["kind"], loads(row["params"], {})
        href = {"plan": "/planner", "draft": "/drafts", "audit": "/drafts", "revise": "/drafts",
                "interview": "/interviewer?mode=bank", "voice": "/interviewer?mode=voice"}.get(kind, f"/tools?tool={kind}")
        if params.get("post_id"):
            href = f"/drafts/{params['post_id']}"
        elif kind == "draft" and params.get("plan_item_id") and row["status"] != "done":
            href = "/planner"
        if params.get("conversation_id"):
            href += f"&c={params['conversation_id']}"
        base = {"job": kind, "status": row["status"], "href": href}
        if row["status"] == "done":
            text = {"draft": "Your draft is ready", "plan": "Your week plan is ready", "audit": "Audit finished",
                    "revise": "A revised version is ready", "interview": "The interviewer replied",
                    "voice": "Your voice profile chat has a reply"}.get(kind, f"{ACTIONS[kind].title} is done")
            return JSONResponse({**base, "kind": "ok", "text": text})
        if row["status"] in PROBLEM:
            return JSONResponse({**base, "kind": "error", "text": f"{ACTIONS[kind].title} did not finish"})
        return JSONResponse({**base, "silent": True})

    @app.post("/jobs/{job_id}/cancel")
    def job_cancel(job_id: int):
        jobs.cancel(job_id)
        return nothing(toast("Stopping…", "info"))

    @app.post("/jobs/{job_id}/retry")
    def job_retry(job_id: int):
        row = job_row(job_id)
        if row is None or row["status"] in ACTIVE or ACTIONS[row["kind"]].chat:
            return fail("That job cannot be run again.")
        jobs.dismiss(job_id)
        new_id = jobs.submit(row["kind"], loads(row["params"], {}))
        return nothing(changed(row["kind"], new_id, "queued"))

    @app.post("/jobs/{job_id}/dismiss")
    def job_dismiss(job_id: int):
        row = job_row(job_id)
        if row is None:
            return fail("That job no longer exists.", 404)
        jobs.dismiss(job_id)
        return nothing(changed(row["kind"], job_id, "dismissed"))

    # ---- home ------------------------------------------------------------------------
    def scheduled_ctx() -> dict:
        return {"upcoming": db.all("SELECT * FROM posts WHERE status IN ('scheduling','scheduled') "
                                   "ORDER BY scheduled_at")}

    @app.get("/")
    def home(request: Request):
        now = datetime.now(timezone.utc)
        plan = db.one("SELECT * FROM plans ORDER BY id DESC LIMIT 1")
        items = flows.plan_items(db, plan["id"]) if plan else []
        sched = scheduled_ctx()
        now_iso = now.isoformat(timespec="seconds")
        publora = pub.status()
        bank, voice = doc_status(flows.read_text(cfg.story_bank)), doc_status(flows.read_text(cfg.voice_profile))
        steps = [
            {"done": bank["is_filled"], "title": "Fill your Story Bank", "href": "/interviewer?mode=bank",
             "text": "A 20-40 minute interview. Drafts then draw on real numbers and stories."},
            {"done": voice["is_filled"], "title": "Teach it your voice", "href": "/interviewer?mode=voice",
             "text": "Paste 3-6 of your own posts so drafts sound like you."},
            {"done": publora["key"] and publora["platform_id"], "title": "Connect Publora", "href": "/settings",
             "text": "Add your key to linkedin-skills\\.env to schedule from here."},
            {"done": plan is not None, "title": "Plan your week", "href": "/planner",
             "text": "Three to five posts, each with a formula and an angle."},
        ]
        return page(request, "home.html", plan=plan, items=items,
                    item_posts=posts_by_id([i.get("post_id") for i in items]),
                    next_post=next((p for p in sched["upcoming"] if (p["scheduled_at"] or "") >= now_iso), None),
                    used=pub.quota_used(now), limit=cfg.monthly_post_limit,
                    month=now.astimezone(cfg.tz).strftime("%B"), last_health=health.latest(),
                    active=jobs.active(),
                    last_run=db.one("SELECT r.*, j.kind FROM runs r LEFT JOIN jobs j ON j.id = r.job_id "
                                    "ORDER BY r.id DESC LIMIT 1"),
                    publora=publora, problems=problems(cfg), steps=steps, **sched)

    @app.post("/posts/refresh")
    def refresh_statuses(request: Request):
        due = db.all("SELECT id FROM posts WHERE status='scheduled' AND scheduled_at <= ?",
                     (datetime.now(timezone.utc).isoformat(timespec="seconds"),))
        errors = []
        for row in due:
            try:
                pub.refresh(row["id"])
            except Exception as exc:
                errors.append(str(exc))
        if errors:
            return fail("Could not reach Publora: " + "; ".join(errors)[:300], 502)
        text = "Nothing was due yet." if not due else f"Checked {len(due)} post{'s' if len(due) != 1 else ''}."
        return partial(request, "_scheduled.html", trigger=toast(text, "info"), **scheduled_ctx())

    # ---- tools -----------------------------------------------------------------------
    def tool_job(kind: str):
        # The newest job worth showing: skip cancelled ones and problems the user already dismissed.
        return db.one("SELECT * FROM jobs WHERE kind=? AND json_extract(params,'$.source')='tools' "
                      "AND status != 'cancelled' AND NOT (status IN ('failed','unparsed') AND acked=1) "
                      "ORDER BY id DESC LIMIT 1", (kind,))

    @app.get("/tools")
    def tools(request: Request, tool: str = "humanize"):
        return page(request, "tools.html", tool=tool if tool in TOOL_KINDS else "humanize",
                    latest={k: tool_job(k) for k in TOOL_KINDS}, apify=pub.status()["apify"])

    @app.get("/tools/{kind}/out")
    def tool_out(request: Request, kind: str):
        if kind not in TOOL_KINDS:
            return fail("Unknown tool.", 404)
        return partial(request, "_tool_out.html", kind=kind, job=tool_job(kind))

    @app.post("/tools/{kind}")
    def tool_run(kind: str, text: str = Form(""), url: str = Form(""), mode: str = Form(""),
                 goal: str = Form(""), angle: str = Form("")):
        if kind not in TOOL_KINDS:
            return fail("Unknown tool.", 404)
        text, url = text.strip(), url.strip()
        if not text and not (url and kind in ("hook", "comment")):
            return fail("Paste some text first." if kind not in ("hook", "comment")
                        else "Paste the post text, or give its URL (that needs an Apify token).")
        if mode and mode not in ("default", "forensic", "strict", "aesthetic", "all"):
            return fail("Unknown mode.")
        job_id = jobs.submit(kind, {"source": "tools", "text": text, "url": url, "mode": mode, "goal": goal,
                                    "angle": angle.strip()})
        return nothing(changed(kind, job_id, "queued"))

    @app.post("/tools/repurpose/{job_id}/draft")
    def tool_to_draft(job_id: int):
        row = job_row(job_id)
        data = loads(row["result"], {}) if row and row["kind"] == "repurpose" and row["status"] == "done" else {}
        text = str(data.get("post") or "").strip()
        if not text:
            return fail("There is no post to save.")
        now = utcnow()
        post_id = db.run("INSERT INTO posts (created_at, updated_at, title, text, first_comment, formula, status) "
                         "VALUES (?,?,?,?,?,?, 'draft')",
                         (now, now, flows.short_title(text.splitlines()[0]), text,
                          data.get("first_comment") or None, data.get("formula")))
        return go(f"/drafts/{post_id}?done=created")

    # ---- planner ---------------------------------------------------------------------
    def board_ctx() -> dict:
        plans = db.all("SELECT * FROM plans ORDER BY id DESC LIMIT 6")
        boards = [(p, flows.plan_items(db, p["id"])) for p in plans]
        plan_job = db.one("SELECT * FROM jobs WHERE kind='plan' ORDER BY id DESC LIMIT 1")
        item_jobs: dict[int, Any] = {}
        for r in db.all("SELECT * FROM jobs WHERE kind='draft' AND json_extract(params,'$.plan_item_id') IS NOT NULL "
                        "ORDER BY id"):
            item_jobs[loads(r["params"], {}).get("plan_item_id")] = r  # later rows win: latest per item
        ids = [i.get("post_id") for _p, items in boards for i in items]
        return {"boards": boards, "plan_job": plan_job if plan_job and visible(plan_job) else None,
                "item_jobs": {k: v for k, v in item_jobs.items() if visible(v)}, "item_posts": posts_by_id(ids)}

    @app.get("/planner")
    def planner(request: Request):
        ctx = board_ctx()
        last = loads(ctx["boards"][0][0]["inputs"], {}) if ctx["boards"] else {}
        return page(request, "planner.html", last=last, bank=doc_status(flows.read_text(cfg.story_bank)), **ctx)

    @app.get("/planner/board")
    def planner_board(request: Request):
        return partial(request, "_board.html", **board_ctx())

    @app.post("/planner")
    def planner_run(audience: str = Form(""), goal: str = Form(""), theme: str = Form(""),
                    max_posts: int = Form(4), founder: str = Form("")):
        if not audience.strip() or not goal.strip():
            return fail("Say who you are writing for and what the week should achieve.")
        if db.one("SELECT 1 FROM jobs WHERE kind='plan' AND status IN ('queued','running')"):
            return fail("A plan is already being made.")
        job_id = jobs.submit("plan", {"audience": audience.strip(), "goal": goal.strip(), "theme": theme.strip(),
                                      "max_posts": max(3, min(5, max_posts)), "founder": bool(founder)})
        return nothing(changed("plan", job_id, "queued"))

    @app.post("/planner/items/{item_id}/draft")
    def planner_draft(item_id: int):
        row = db.one("SELECT * FROM plan_items WHERE id=?", (item_id,))
        if row is None:
            return fail("That plan item no longer exists.", 404)
        if row["post_id"]:
            return fail("This item already has a draft.")
        if any(j["status"] in ACTIVE for j in jobs_for("plan_item_id", item_id, ("draft",))):
            return fail("This item is already being drafted.")
        plan = db.one("SELECT inputs FROM plans WHERE id=?", (row["plan_id"],))
        item, inputs = loads(row["data"], {}), loads(plan["inputs"], {}) if plan else {}
        params = {k: item.get(k) for k in ("angle", "formula", "pillar", "goal", "cta", "format", "bank_section")}
        params.update(plan_item_id=item_id, audience=inputs.get("audience"))
        job_id = jobs.submit("draft", params)
        return nothing(changed("draft", job_id, "queued"))

    # ---- drafts: list ----------------------------------------------------------------
    FILTERS = {"all": None, "draft": ("draft",), "approved": ("approved",),
               "scheduled": ("scheduling", "scheduled"), "published": ("published",),
               "other": ("failed", "cancelled")}

    def list_ctx(show: str) -> dict:
        show = show if show in FILTERS else "all"
        posts = db.all("SELECT * FROM posts ORDER BY CASE status WHEN 'draft' THEN 0 WHEN 'approved' THEN 1 "
                       "WHEN 'scheduling' THEN 2 WHEN 'scheduled' THEN 3 WHEN 'failed' THEN 4 ELSE 5 END, "
                       "updated_at DESC")
        counts = {name: sum(1 for p in posts if wanted is None or p["status"] in wanted)
                  for name, wanted in FILTERS.items()}
        wanted = FILTERS[show]
        write_jobs = [j for j in db.all("SELECT * FROM jobs WHERE kind='draft' "
                                        "AND json_extract(params,'$.plan_item_id') IS NULL ORDER BY id DESC LIMIT 10")
                      if visible(j)]
        return {"posts": [p for p in posts if wanted is None or p["status"] in wanted], "counts": counts,
                "show": show, "write_jobs": write_jobs, "total": len(posts)}

    @app.get("/drafts")
    def drafts(request: Request, show: str = "all"):
        return page(request, "drafts.html", **list_ctx(show))

    @app.get("/drafts/list")
    def drafts_list(request: Request, show: str = "all"):
        return partial(request, "_draft_list.html", **list_ctx(show))

    @app.post("/drafts/write")
    def drafts_write(topic: str = Form(""), goal: str = Form(""), audience: str = Form(""),
                     length: str = Form("")):
        if not topic.strip():
            return fail("Say what the post is about.")
        job_id = jobs.submit("draft", {"topic": topic.strip(), "goal": goal if goal in GOALS else "",
                                       "audience": audience.strip(), "length": length.strip()})
        return nothing(changed("draft", job_id, "queued"))

    @app.post("/drafts/blank")
    def drafts_blank(title: str = Form("")):
        now = utcnow()
        post_id = db.run("INSERT INTO posts (created_at, updated_at, title, text, status) VALUES (?,?,?,?, 'draft')",
                         (now, now, title.strip()[:120] or "Untitled draft", ""))
        return go(f"/drafts/{post_id}")

    # ---- drafts: one post ------------------------------------------------------------
    def quick_times(now_local: datetime) -> list[dict]:
        """Posting slots the skills recommend (Tue-Thu mornings), plus tomorrow morning."""
        slots = []
        for weekday, hour, minute in ((1, 8, 0), (2, 9, 30), (3, 8, 0)):
            slot = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
            slot += timedelta(days=(weekday - slot.weekday()) % 7)
            if slot <= now_local + MIN_LEAD + timedelta(minutes=5):
                slot += timedelta(days=7)
            slots.append(slot)
        tomorrow = (now_local + timedelta(days=1)).date()
        if all(s.date() != tomorrow for s in slots):
            slots.append((now_local + timedelta(days=1)).replace(hour=8, minute=30, second=0, microsecond=0))
        picks = []
        for slot in sorted(slots):
            text = render.local_time(slot.astimezone(timezone.utc).isoformat(), cfg.tz)
            day = "Today" if slot.date() == now_local.date() else "Tomorrow" if slot.date() == tomorrow else None
            picks.append({"value": slot.strftime("%Y-%m-%dT%H:%M"),
                          "label": f"{day}, {text.split(', ')[1]}" if day else text})
        return picks

    def draft_ctx(post) -> dict:
        related = jobs_for("post_id", post["id"], ("audit", "revise"))
        audit_job = next((j for j in related if j["kind"] == "audit" and visible(j)), None)
        revise_job = next((j for j in related if j["kind"] == "revise" and visible(j)), None)
        revision = next((j for j in related if j["kind"] == "revise" and j["status"] == "done" and not j["acked"]),
                        None)
        if revise_job is not None and revision is not None and revision["id"] > revise_job["id"]:
            revise_job = None  # an older failure is moot once a newer revision arrived
        now_local = datetime.now(timezone.utc).astimezone(cfg.tz)
        audit = loads(post["audit"])
        return {
            "post": post, "audit": audit, "audit_stale": bool(audit) and audit.get("text") != post["text"],
            "audit_job": audit_job, "revise_job": revise_job, "revision": revision,
            "notes": loads(post["notes"], []), "slots": placeholder_slots(post["text"]),
            "editable": post["status"] == "draft", "publora": pub.status(),
            "used": pub.quota_used(datetime.now(timezone.utc)), "limit": cfg.monthly_post_limit,
            "min_when": (now_local + MIN_LEAD + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M"),
            "max_when": (now_local + MAX_AHEAD).strftime("%Y-%m-%dT%H:%M"),
            "quick": quick_times(now_local),
            "deletable": post["status"] not in ("scheduling", "scheduled", "published"),
        }

    def get_post(post_id: int):
        return db.one("SELECT * FROM posts WHERE id=?", (post_id,))

    @app.get("/drafts/{post_id}")
    def draft_page(request: Request, post_id: int):
        post = get_post(post_id)
        if post is None:
            return page(request, "missing.html", what="draft", nav="drafts")
        return page(request, "draft.html", nav="drafts", **draft_ctx(post))

    @app.get("/drafts/{post_id}/rail")
    def draft_rail(request: Request, post_id: int):
        post = get_post(post_id)
        if post is None:
            return fail("That draft no longer exists.", 404)
        return partial(request, "_rail.html", **draft_ctx(post))

    @app.get("/drafts/{post_id}/revision")
    def draft_revision(request: Request, post_id: int):
        post = get_post(post_id)
        if post is None:
            return fail("That draft no longer exists.", 404)
        return partial(request, "_revision.html", **draft_ctx(post))

    def save_fields(post_id: int, title: str | None, text: str | None, first_comment: str | None):
        """Store the editor's fields if the post is still a draft. Returns the fresh row, or None."""
        post = db.one("SELECT * FROM posts WHERE id=? AND status='draft'", (post_id,))
        if post is None:
            return None
        if text is None:
            return post
        new_text = text.replace("\r\n", "\n").strip()
        new_fc = (first_comment or "").replace("\r\n", "\n").strip() or None
        new_title = (title or "").strip()[:120] or post["title"]
        if (new_text, new_fc, new_title) != (post["text"], post["first_comment"], post["title"]):
            db.run("UPDATE posts SET text=?, first_comment=?, title=?, updated_at=? WHERE id=?",
                   (new_text, new_fc, new_title, utcnow(), post_id))
            post = db.one("SELECT * FROM posts WHERE id=?", (post_id,))
        return post

    @app.post("/drafts/{post_id}/save")
    def draft_save(post_id: int, text: str = Form(""), first_comment: str = Form(""), title: str = Form("")):
        post = save_fields(post_id, title, text, first_comment)
        if post is None:
            return fail("Only a draft can be edited. Move it back to draft first.", 409)
        return nothing({"saved": {"chars": len(post["text"]), "slots": len(placeholder_slots(post["text"])),
                                  "at": render.local_time(post["updated_at"], cfg.tz).split(", ")[1]}})

    @app.post("/drafts/{post_id}/audit")
    def draft_audit(post_id: int, text: str | None = Form(None), first_comment: str | None = Form(None),
                    title: str | None = Form(None)):
        post = save_fields(post_id, title, text, first_comment) or get_post(post_id)
        if post is None or not post["text"].strip():
            return fail("Write something first.")
        if any(j["status"] in ACTIVE for j in jobs_for("post_id", post_id, ("audit",))):
            return fail("An audit is already running.")
        for old in jobs_for("post_id", post_id, ("audit",)):
            jobs.dismiss(old["id"])
        job_id = jobs.submit("audit", {"post_id": post_id, "text": post["text"]})
        return nothing(changed("audit", job_id, "queued"))

    @app.post("/drafts/{post_id}/revise/{how}")
    def draft_revise(post_id: int, how: str, text: str | None = Form(None),
                     first_comment: str | None = Form(None), title: str | None = Form(None)):
        post = save_fields(post_id, title, text, first_comment)
        if post is None or how not in REVISIONS or not post["text"].strip():
            return fail("Only a draft with some text can be revised.")
        if any(j["status"] in ACTIVE for j in jobs_for("post_id", post_id, ("revise",))):
            return fail("A revision is already being written.")
        for old in jobs_for("post_id", post_id, ("revise",)):
            jobs.dismiss(old["id"])
        job_id = jobs.submit("revise", {"post_id": post_id, "how": how, "text": post["text"]})
        return nothing(changed("revise", job_id, "queued"))

    @app.post("/drafts/{post_id}/revision/{job_id}")
    def draft_use_revision(post_id: int, job_id: int, use: int = Form(0)):
        post, job = db.one("SELECT * FROM posts WHERE id=? AND status='draft'", (post_id,)), job_row(job_id)
        if post is None or job is None or job["kind"] != "revise":
            return fail("That revision can no longer be applied.", 409)
        data = loads(job["result"], {})
        jobs.dismiss(job_id)
        if use and str(data.get("text") or "").strip():
            db.run("UPDATE posts SET text=?, first_comment=COALESCE(?, first_comment), audit=NULL, updated_at=? "
                   "WHERE id=?", (data["text"].strip(), data.get("first_comment") or None, utcnow(), post_id))
            return go(f"/drafts/{post_id}?done=revised")
        return go(f"/drafts/{post_id}?done=discarded")

    def transition(post_id: int, done: str, fn: Callable[[], object]) -> Response:
        try:
            result = fn()
        except ScheduleError as exc:
            return fail(str(exc), 409)
        if isinstance(result, dict) and not result.get("ok", True):
            return go(f"/drafts/{post_id}")  # the page shows the stored error and offers Retry
        return go(f"/drafts/{post_id}?done={done}")

    @app.post("/drafts/{post_id}/approve")
    def draft_approve(post_id: int, text: str | None = Form(None), first_comment: str | None = Form(None),
                      title: str | None = Form(None)):
        save_fields(post_id, title, text, first_comment)
        return transition(post_id, "approved", lambda: pub.approve(post_id))

    @app.post("/drafts/{post_id}/unapprove")
    def draft_unapprove(post_id: int):
        return transition(post_id, "draft", lambda: pub.back_to_draft(post_id))

    @app.post("/drafts/{post_id}/schedule")
    def draft_schedule(post_id: int, when: str = Form(""), first_comment: str = Form("")):
        return transition(post_id, "scheduled", lambda: pub.schedule(post_id, when, first_comment))

    @app.post("/drafts/{post_id}/retry")
    def draft_retry(post_id: int):
        return transition(post_id, "scheduled", lambda: pub.retry(post_id))

    @app.post("/drafts/{post_id}/cancel")
    def draft_cancel(post_id: int):
        return transition(post_id, "cancelled", lambda: pub.cancel(post_id))

    @app.post("/drafts/{post_id}/refresh")
    def draft_refresh(post_id: int):
        try:
            pub.refresh(post_id)
        except Exception as exc:
            return fail(f"Could not read the status from Publora: {exc}", 502)
        return go(f"/drafts/{post_id}?done=refreshed")

    @app.post("/drafts/{post_id}/delete")
    def draft_delete(post_id: int):
        post = get_post(post_id)
        if post is None:
            return go("/drafts")
        if post["status"] in ("scheduling", "scheduled", "published"):
            return fail("A scheduled or published post cannot be deleted here. Cancel it on Publora first.", 409)
        db.run("UPDATE plan_items SET post_id=NULL WHERE post_id=?", (post_id,))
        db.run("DELETE FROM posts WHERE id=?", (post_id,))
        return go("/drafts?done=deleted")

    # ---- interviewer -----------------------------------------------------------------
    def thread_ctx(mode: str, conv) -> dict:
        kind = MODES[mode]
        msgs = db.all("SELECT * FROM messages WHERE conversation_id=? ORDER BY id", (conv["id"],)) if conv else []
        related = jobs_for("conversation_id", conv["id"], (kind,)) if conv else []
        active = next((j for j in related if j["status"] in ACTIVE), None)
        last_job = job_row(msgs[-1]["job_id"]) if msgs and msgs[-1]["job_id"] else None
        unanswered = bool(msgs) and msgs[-1]["role"] == "user" and active is None
        return {"mode": mode, "kind": kind, "conv": conv, "msgs": msgs, "active": active,
                "failed": last_job if unanswered and last_job and last_job["status"] != "done" else None,
                "started": bool(conv and conv["session_id"]), "doc_name": mode_file[mode].name}

    def conversation(mode: str, conv_id: int | None):
        if conv_id:
            return db.one("SELECT * FROM conversations WHERE id=? AND mode=?", (conv_id, mode))
        return db.one("SELECT * FROM conversations WHERE mode=? ORDER BY id DESC LIMIT 1", (mode,))

    @app.get("/interviewer")
    def interviewer(request: Request, mode: str = "bank", c: int | None = None):
        mode = mode if mode in MODES else "bank"
        conv = conversation(mode, c)
        history = db.all("SELECT c.id, c.created_at, (SELECT COUNT(*) FROM messages m WHERE m.conversation_id=c.id) "
                         "AS n FROM conversations c WHERE c.mode=? ORDER BY c.id DESC LIMIT 20", (mode,))
        return page(request, "interviewer.html", history=[h for h in history if h["n"]],
                    doc=doc_status(flows.read_text(mode_file[mode])), **thread_ctx(mode, conv))

    @app.get("/interviewer/{mode}/thread")
    def interviewer_thread(request: Request, mode: str, c: int = 0):
        if mode not in MODES:
            return fail("Unknown mode.", 404)
        return partial(request, "_thread.html", **thread_ctx(mode, conversation(mode, c) if c else None))

    @app.post("/interviewer/{mode}/new")
    def interviewer_new(mode: str):
        if mode not in MODES:
            return fail("Unknown mode.", 404)
        conv_id = db.run("INSERT INTO conversations (mode, created_at) VALUES (?,?)", (mode, utcnow()))
        return go(f"/interviewer?mode={mode}&c={conv_id}")

    @app.post("/interviewer/{mode}/send")
    def interviewer_send(request: Request, mode: str, text: str = Form(""), conversation_id: int = Form(0)):
        if mode not in MODES:
            return fail("Unknown mode.", 404)
        text = text.strip()
        conv = conversation(mode, conversation_id) if conversation_id else None
        created = conv is None
        if created:
            conv_id = db.run("INSERT INTO conversations (mode, created_at) VALUES (?,?)", (mode, utcnow()))
            conv = db.one("SELECT * FROM conversations WHERE id=?", (conv_id,))
        first = not conv["session_id"]
        if not text and not first:
            return fail("Type your answer first.")
        if any(j["status"] in ACTIVE for j in jobs_for("conversation_id", conv["id"], (MODES[mode],))):
            return fail("Wait for the reply first.")
        job_id = jobs.submit(MODES[mode], {"conversation_id": conv["id"], "text": text, "first": first})
        db.run("INSERT INTO messages (conversation_id, role, text, job_id, created_at) VALUES (?,?,?,?,?)",
               (conv["id"], "user", text or "Let's start.", job_id, utcnow()))
        resp = partial(request, "_thread.html", **thread_ctx(mode, conv))
        if created:
            resp.headers["HX-Push-Url"] = f"/interviewer?mode={mode}&c={conv['id']}"
        return resp

    # ---- story bank & voice ----------------------------------------------------------
    @app.get("/bank")
    def bank(request: Request, doc: str = "bank"):
        doc = doc if doc in MODES else "bank"
        files = {}
        for mode, path in mode_file.items():
            text = flows.read_text(path)
            sections = render.doc_sections(text)
            files[mode] = {"mode": mode, "title": MODE_TITLE[mode], "path": str(path), "text": text,
                           "status": doc_status(text), "sections": sections,
                           "filled": sum(1 for s in sections if s["filled"])}
        return page(request, "bank.html", files=files, doc=doc, protection=protection)

    # ---- guide -----------------------------------------------------------------------
    @app.get("/guide")
    def guide_page(request: Request):
        # The figures the guide quotes come from the code that enforces them.
        numbers = {"limit": cfg.monthly_post_limit, "post_max": f"{POST_MAX:,}",
                   "min_lead": int(MIN_LEAD.total_seconds() // 60), "max_days": MAX_AHEAD.days,
                   "target_min": f"{TARGET['min']:,}", "target_max": f"{TARGET['max']:,}", "fold": TARGET["fold"]}
        screens = guide.fill(guide.SCREENS, numbers)
        for screen in screens:
            if screen["key"] == "tools":    # one line per tool, from the same descriptions the Tools page shows
                screen["points"] = [f"{ACTIONS[k].title}: {ACTIONS[k].blurb}" for k in TOOL_KINDS] + screen["points"]
        return page(request, "guide.html", lanes=guide.fill(guide.LANES, numbers),
                    states=guide.fill(guide.STATES, numbers), screens=screens,
                    shortcuts=guide.SHORTCUTS, sample=guide.SAMPLE_POST, numbers=numbers, protection=protection)

    # ---- folders: the setup screen ---------------------------------------------------
    def setup_ctx(values: dict | None = None, errors: dict | None = None, saved: bool = False) -> dict:
        places = paths.usual_places()
        found = paths.found(places)
        if values is None:
            # First showing: keep each configured place that works, otherwise offer the first one found.
            wrong = path_problems(cfg)
            values = {f.key: str(getattr(cfg, f.key)) if f.key not in wrong else (found[f.key] or [""])[0]
                      for f in paths.FIELDS}
            _chosen, errors = paths.check(values, cfg, probe=False)
            errors = {key: why for key, why in errors.items() if values[key]}   # an empty box is not a mistake yet
        return {"fields": paths.FIELDS, "values": values, "errors": errors or {}, "found": found,
                "examples": {key: str(where[0]) for key, where in places.items()}, "first_run": needs_setup,
                "saved": saved, "restarts": on_restart is not None}

    @app.get("/setup")
    def setup_page(request: Request):
        return page(request, "setup.html", nav="settings", bare=needs_setup, **setup_ctx())

    @app.post("/setup")
    def setup_save(request: Request, skills_dir: str = Form(""), claude_bin: str = Form(""),
                   claude_config_dir: str = Form("")):
        values = {"skills_dir": skills_dir, "claude_bin": claude_bin, "claude_config_dir": claude_config_dir}
        chosen, errors = paths.check(values, cfg)
        if not errors:
            try:
                paths.save(chosen)
            except ConfigError as exc:
                errors = {"": str(exc)}
        if errors:
            return partial(request, "_paths.html", **setup_ctx(values, errors))
        if on_restart:
            threading.Timer(0.8, on_restart).start()     # after this answer has reached the window
        return partial(request, "_paths.html", **setup_ctx({k: str(v) for k, v in chosen.items()}, {}, saved=True))

    @app.post("/setup/browse")
    def setup_browse(field: str = Form(""), start: str = Form("")):
        spec = next((f for f in paths.FIELDS if f.key == field), None)
        if spec is None:
            return fail("Unknown setting.", 404)
        try:
            return JSONResponse({"path": paths.browse(spec, start)})
        except paths.PickerBusy:
            return fail("A file window is already open. Look for it behind this window.", 409)
        except (OSError, subprocess.SubprocessError) as exc:
            return fail(f"Windows could not open the file window ({exc}). Type or paste the path instead.", 500)

    # ---- settings --------------------------------------------------------------------
    @app.get("/settings")
    def settings(request: Request):
        runs = db.all("SELECT r.*, j.kind FROM runs r LEFT JOIN jobs j ON j.id = r.job_id ORDER BY r.id DESC LIMIT 50")
        return page(request, "settings.html", runs=runs, version=claude_version(cfg),
                    checks={n: health.latest(n) for n in ("check_config", "selftest")},
                    running=dict(health.running), problems=problems(cfg), publora=pub.status(),
                    data_dir=str(DATA_DIR), protection=protection)

    @app.post("/settings/health/{name}")
    def settings_health(request: Request, name: str):
        if not health.start(name):
            return fail("That check is already running.", 409)
        return partial(request, "_health.html", name=name, running=True, row=None)

    @app.get("/settings/health/{name}")
    def settings_health_status(request: Request, name: str):
        return partial(request, "_health.html", name=name, running=health.running.get(name, False),
                       row=health.latest(name))

    return app
