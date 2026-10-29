"""The API of the pages beside the posts: Planner (Coming up from the posting queue, posting.py; Draft all,
draft_all.py), Story Bank & Voice (with its two chats, and Ask me about this, ask_about.py), Tools (with each tool's
earlier results, and Start a post from this), Settings (with ChatGPT, the health checks, You in the preview and the
posting times), the setup screen and the Guide."""
from __future__ import annotations

import dataclasses
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI
from fastapi.responses import FileResponse, Response

from . import (ask_about, attached, attachments, codex, draft_all, flows, guide, paths, posting, profile, render, style,
               versions)
from .api_posts import fail
from .config import ConfigError, path_problems, problems
from .db import dumps, loads, utcnow
from .health import claude_account, claude_version
from .main import ACTIVE, PROBLEM, TARGET, Studio
from .publishing import MAX_AHEAD, MIN_LEAD, POST_MAX
from .skills import ACTIONS, TOOL_KINDS

GOALS = ("comments", "reposts", "likes", "saves")
MODES = {"bank": "interview", "voice": "voice"}
MODE_TITLE = {"bank": "Story Bank", "voice": "Voice profile"}
HUMANIZE_MODES = ("default", "forensic", "strict", "aesthetic", "all")
REACTIONS = {"LIKE": "Like", "PRAISE": "Celebrate", "EMPATHY": "Love", "INTEREST": "Insightful",
             "APPRECIATION": "Support", "ENTERTAINMENT": "Funny"}
VERSION_TTL = 60   # seconds the Claude version and its sign-in are kept between visits
EARLIER = 10       # finished results Tools lists under a tool's result
# Start a post from this: the tools whose result holds a post's text, and its first version's note.
TOOL_POSTS = {"humanize": "From Humanize", "audit": "From Audit", "hook": "From Hook extractor", "repurpose": "Repurposed"}
NOT_A_POST = {"comment": "A comment is not a post: copy the one you like and post it yourself.",
              "profile": "A profile review is not a post: copy the rewrites into LinkedIn yourself."}
GUIDE_SHOTS = Path(__file__).resolve().parent / "static" / "guide"


def doc_status(text: str) -> dict:
    found = dict(re.findall(r"^-\s*(filled|updated|sessions|source):\s*(.*)$", text, flags=re.M))
    # A value still in (parentheses) is the template's own hint, not something a skill wrote.
    status = {k: "" if v.strip().startswith("(") else v.strip() for k, v in found.items()}
    status["is_filled"] = status.get("filled", "").lower().startswith("yes")
    return status


def register(app: FastAPI, s: Studio) -> None:
    db, jobs, pub, cfg = s.db, s.jobs, s.pub, s.cfg
    version_cache: dict[str, Any] = {"at": 0.0, "said": ""}

    def visible(job) -> bool:
        return job["status"] in ACTIVE or (job["status"] in PROBLEM and not job["acked"])

    def jobs_for(field: str, value: int, kinds: tuple[str, ...]) -> list:
        marks = ",".join("?" * len(kinds))
        return db.all(f"SELECT * FROM jobs WHERE kind IN ({marks}) AND json_extract(params, '$.{field}')=? "
                      "ORDER BY id DESC", (*kinds, value))

    def posts_by_id(ids: list) -> dict[int, Any]:
        ids = [i for i in ids if i]
        if not ids:
            return {}
        rows = db.all(f"SELECT * FROM posts WHERE id IN ({','.join('?' * len(ids))})", tuple(ids))
        return {r["id"]: r for r in rows}

    def claude_said() -> str:
        if time.monotonic() - version_cache["at"] > VERSION_TTL or not version_cache["said"]:
            version_cache.update(at=time.monotonic(), said=claude_version(cfg))
        return version_cache["said"]

    # Who a login folder is signed in to (health.claude_account), asked with the runs' own command and environment
    # and kept about a minute. Nothing of it is stored.
    accounts: dict[tuple[str, str], tuple[float, dict]] = {}
    asking = threading.Lock()

    def account_of(folder: str, program: str = "", fresh: bool = False) -> dict:
        key = (program or str(cfg.claude_bin), folder)
        with asking:
            kept = accounts.get(key)
        if kept and not fresh and time.monotonic() - kept[0] < VERSION_TTL:
            return kept[1]
        candidate = dataclasses.replace(cfg, claude_config_dir=Path(folder), claude_bin=Path(key[0]))
        said = claude_account(candidate, getattr(jobs.runner, "prefix", None))
        with asking:
            accounts[key] = (time.monotonic(), said)
        return said

    def sign_in(fresh: bool = False) -> dict:
        return account_of(str(cfg.claude_config_dir), fresh=fresh)

    # ---- planner (and this month) ---------------------------------------------------------
    def coming_up(upcoming: list) -> list[dict]:
        """Coming up: what goes out and when, earliest first. The posts at Publora with their time, the queued posts
        with the time the queue gives each (in line order, with their place), and the posting times still free within
        the window."""
        line, free = s.queue.coming()
        spots = dict(line)
        waiting = posts_by_id([pid for pid, _at in line])
        out = [{"kind": "publora", "at": p["scheduled_at"] or "", "when": s.when(p["scheduled_at"]), "post": s.post_summary(p)}
               for p in upcoming]
        for place, (pid, at) in enumerate(line, start=1):
            row = waiting[pid]
            out.append({"kind": "queued", "at": at.isoformat(timespec="seconds") if at else "",
                        "when": posting.time_words(at, cfg.tz, s.tz_label), "place": place, "of": len(line),
                        "error": row["error"] or "", "post": s.post_summary(row, spots)})
        out += [{"kind": "free", "at": at.isoformat(timespec="seconds"), "when": posting.time_words(at, cfg.tz, s.tz_label)}
                for at in free]
        return sorted(out, key=lambda c: (not c["at"], c["at"]))

    @app.get("/api/planner")
    def planner():
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat(timespec="seconds")
        upcoming = db.all("SELECT * FROM posts WHERE status IN ('scheduling','scheduled') AND trashed_at IS NULL "
                          "ORDER BY scheduled_at")
        coming = coming_up(upcoming)
        next_post = next((c["post"] for c in coming if c["kind"] != "free" and c["at"] >= now_iso), None)
        bank, voice = doc_status(flows.read_text(cfg.story_bank)), doc_status(flows.read_text(cfg.voice_profile))
        publora = pub.status()
        plans = db.all("SELECT * FROM plans ORDER BY id DESC LIMIT 6")
        boards = []
        item_jobs: dict[int, Any] = {}
        for r in db.all("SELECT * FROM jobs WHERE kind='draft' AND json_extract(params,'$.plan_item_id') IS NOT NULL ORDER BY id"):
            item_jobs[(loads(r["params"], {}) or {}).get("plan_item_id")] = r   # later rows win: the latest per item
        for plan in plans:
            items = flows.plan_items(db, plan["id"])
            linked = posts_by_id([i.get("post_id") for i in items])
            out_items = []
            for item in items:
                post = linked.get(item.get("post_id"))
                job = item_jobs.get(item["id"])
                out_items.append({**{k: v for k, v in item.items() if isinstance(v, (str, int, float, type(None)))},
                                  "post": s.post_summary(post) if post else None,
                                  "job": s.job_public(job) if job is not None and visible(job) else None})
            result = loads(plan["result"], {}) or {}
            boards.append({"id": plan["id"], "planned": s.ago(plan["created_at"]), "inputs": loads(plan["inputs"], {}) or {},
                           "items": out_items, "comment_targets": result.get("comment_targets") or [],
                           "readiness": result.get("readiness") or [], "notes": result.get("notes") or [],
                           "draft_all": draft_all.board(db, plan["id"])})
        plan_job = db.one("SELECT * FROM jobs WHERE kind='plan' ORDER BY id DESC LIMIT 1")
        last_run = db.one("SELECT r.*, j.kind FROM runs r LEFT JOIN jobs j ON j.id = r.job_id ORDER BY r.id DESC LIMIT 1")
        last_health = s.health.latest()
        active = jobs.active()
        steps = [
            {"done": bank["is_filled"], "title": "Fill your Story Bank", "href": "#~bank",
             "text": "A 20-40 minute interview. Drafts then draw on real numbers and stories."},
            {"done": voice["is_filled"], "title": "Teach it your voice", "href": "#~voice",
             "text": "Paste 3-6 of your own posts so drafts sound like you."},
            # The LinkedIn channel is worked out from the key when a post is scheduled: the key is the whole step.
            {"done": publora["key"], "title": "Connect Publora", "href": "#~settings",
             "text": "Add your key to linkedin-skills\\.env to schedule from here."},
            {"done": bool(plans), "title": "Plan your week", "href": "#~planner",
             "text": "One post for each posting day, each with a formula and an angle."},
        ]
        return {
            "month": now.astimezone(cfg.tz).strftime("%B"), "used": pub.quota_used(now), "limit": cfg.monthly_post_limit,
            "tz": s.tz_label,
            "next": next_post,
            "upcoming": [s.post_summary(p) for p in upcoming],
            "coming": coming, "posting": posting.words(s.queue.times()), "posting_days": len(s.queue.times()),
            "window": MAX_AHEAD.days,
            "claude": {"working": ACTIONS[active[0]["kind"]].doing if active else "",
                       "login": str(cfg.claude_config_dir), "model": cfg.model or "Account default",
                       "sign_in": sign_in(),
                       "last_run": (f"{ACTIONS[last_run['kind']].title if last_run['kind'] in ACTIONS else last_run['skill']}, "
                                    f"{s.ago(last_run['started_at'])}") if last_run else "",
                       "health": ({"ok": last_health["exit_code"] == 0, "when": s.ago(last_health["ran_at"])}
                                  if last_health else None)},
            "steps": steps, "problems": problems(cfg), "bank_filled": bank["is_filled"],
            "last": boards[0]["inputs"] if boards else {},
            "plan_job": s.job_public(plan_job) if plan_job is not None and visible(plan_job) else None,
            "boards": boards, "goals": GOALS,
        }

    @app.post("/api/planner")
    def planner_run(data: dict = Body(default={})):
        audience, goal = str(data.get("audience") or "").strip(), str(data.get("goal") or "").strip()
        if not audience or not goal:
            return fail("Say who you are writing for and what the week should achieve.")
        if db.one("SELECT 1 FROM jobs WHERE kind='plan' AND status IN ('queued','running')"):
            return fail("A plan is already being made.")
        days = s.queue.times()           # one post for each posting day, on that day and at its time
        return {"job": jobs.submit("plan", {"audience": audience, "goal": goal, "theme": str(data.get("theme") or "").strip(),
                                            "max_posts": len(days), "days": days, "founder": bool(data.get("founder"))})}

    @app.post("/api/planner/items/{item_id}/draft")
    def planner_draft(item_id: int):
        row = db.one("SELECT * FROM plan_items WHERE id=?", (item_id,))
        if row is None:
            return fail("That plan item no longer exists.", 404)
        if row["post_id"]:
            return fail("This item already has a draft.")
        if any(j["status"] in ACTIVE for j in jobs_for("plan_item_id", item_id, ("draft",))):
            return fail("This item is already being drafted.")
        return {"job": jobs.submit("draft", draft_all.draft_params(db, row))}

    draft_all.register(app, s)   # Draft all: POST /api/planner/{plan_id}/draft-all and /api/planner/draft-all/stop

    # ---- story bank & voice ------------------------------------------------------------
    @app.get("/api/bank")
    def bank():
        files = {}
        for mode, path in s.mode_file.items():
            text = flows.read_text(path)
            sections = render.doc_sections(text)
            files[mode] = {"mode": mode, "title": MODE_TITLE[mode], "path": str(path), "name": path.name, "text": text,
                           "status": doc_status(text), "sections": sections,
                           "filled": sum(1 for sec in sections if sec["filled"])}
        p = s.protection
        return {"files": files, "protection": {"ok": p.ok, "state": p.state, "detail": p.detail}}

    def conversation(mode: str, conv_id: int | None):
        if conv_id:
            return db.one("SELECT * FROM conversations WHERE id=? AND mode=?", (conv_id, mode))
        return db.one("SELECT * FROM conversations WHERE mode=? ORDER BY id DESC LIMIT 1", (mode,))

    def chat_message(m) -> dict:
        meta = loads(m["meta"], {}) or {}
        out: dict[str, Any] = {"id": m["id"], "role": "claude" if m["role"] == "assistant" else m["role"],
                               "text": m["text"], "at": s.clock(m["created_at"]), "job": m["job_id"]}
        if m["diff"]:
            added, removed = render.diffstat(m["diff"])
            out["diff"] = {"text": m["diff"], "added": added, "removed": removed}
        if meta.get("offer"):
            out["offer"], out["request"] = meta["offer"], meta.get("request")
        if meta.get("files"):
            out["files"] = attached.public(meta["files"], f"/api/chat/{mode_of_conv(m['conversation_id'])}/{m['conversation_id']}/file")
        return out

    def mode_of_conv(conv_id: int) -> str:
        row = db.one("SELECT mode FROM conversations WHERE id=?", (conv_id,))
        return row["mode"] if row else "bank"

    @app.get("/api/chat/{mode}/{conv_id}/file/{name}")
    def chat_file(mode: str, conv_id: int, name: str):
        if mode not in MODES:
            return fail("Unknown mode.", 404)
        found = attached.served(db, f"{mode}-{conv_id}", name)
        if found is None:
            return fail("That file is not here.", 404)
        path, headers = found
        return FileResponse(path, headers=headers)

    @app.get("/api/chat/{mode}")
    def chat(mode: str, c: int = 0):
        if mode not in MODES:
            return fail("Unknown mode.", 404)
        conv = conversation(mode, c or None)
        msgs = db.all("SELECT * FROM messages WHERE conversation_id=? ORDER BY id", (conv["id"],)) if conv else []
        history = db.all("SELECT c.id, c.created_at, (SELECT COUNT(*) FROM messages m WHERE m.conversation_id=c.id) AS n "
                         "FROM conversations c WHERE c.mode=? ORDER BY c.id DESC LIMIT 20", (mode,))
        busy = bool(conv) and any(j["status"] in ACTIVE for j in jobs_for("conversation_id", conv["id"], (MODES[mode],)))
        return {"mode": mode, "conversation": conv["id"] if conv else None, "started": bool(conv and conv["session_id"]),
                "messages": [chat_message(m) for m in msgs], "busy": busy,
                "history": [{"id": h["id"], "when": s.when(h["created_at"]), "count": h["n"]} for h in history if h["n"]],
                "doc": {"name": s.mode_file[mode].name, **doc_status(flows.read_text(s.mode_file[mode]))}}

    @app.post("/api/chat/{mode}/new")
    def chat_new(mode: str):
        if mode not in MODES:
            return fail("Unknown mode.", 404)
        return {"conversation": db.run("INSERT INTO conversations (mode, created_at) VALUES (?,?)", (mode, utcnow()))}

    @app.post("/api/chat/{mode}/send")
    def chat_send(mode: str, data: dict = Body(default={})):
        if mode not in MODES:
            return fail("Unknown mode.", 404)
        focus = ask_about.focus_of(data, mode, cfg.story_bank)   # Ask me about this: a new conversation about one entry
        if isinstance(focus, str):
            return fail(focus)
        text = ask_about.opening(focus) if focus else str(data.get("text") or "").strip()
        conv = conversation(mode, int(data.get("conversation") or 0)) if data.get("conversation") and not focus else None
        if conv is None:
            conv_id = db.run("INSERT INTO conversations (mode, created_at) VALUES (?,?)", (mode, utcnow()))
            conv = db.one("SELECT * FROM conversations WHERE id=?", (conv_id,))
        first = not conv["session_id"]
        if not text and not first:
            return fail("Type your answer first.")
        if any(j["status"] in ACTIVE for j in jobs_for("conversation_id", conv["id"], (MODES[mode],))):
            return fail("Wait for the reply first.", 409)
        try:
            files = attached.save_all(db, f"{mode}-{conv['id']}", data.get("files"))
        except attachments.Refused as exc:
            return fail(str(exc))
        message = flows.add_message(db, conv["id"], "user", text or "Let's start.", meta={"files": files} if files else None)
        job = jobs.submit(MODES[mode], {"conversation_id": conv["id"], "text": text, "first": first, "message_id": message,
                                        "files": [r["path"] for r in files], **({"focus": focus} if focus else {})})
        db.run("UPDATE messages SET job_id=? WHERE id=?", (job, message))
        return {"conversation": conv["id"], "job": job, "message": message}

    # ---- tools -------------------------------------------------------------------------
    def tool_job(kind: str):
        # The newest job worth showing: skip cancelled ones and problems the user already dismissed.
        return db.one("SELECT * FROM jobs WHERE kind=? AND json_extract(params,'$.source')='tools' "
                      "AND status != 'cancelled' AND NOT (status IN ('failed','unparsed') AND acked=1) "
                      "ORDER BY id DESC LIMIT 1", (kind,))

    def tool_done(job) -> dict:
        """A finished tool job as the page shows it: its result, what it was given, and for Humanize the comparison."""
        out = s.job_public(job)
        out["result"] = loads(job["result"], {}) or {}
        out["params"] = {k: v for k, v in (loads(job["params"], {}) or {}).items() if k in ("text", "url", "mode", "goal", "angle")}
        if job["kind"] == "humanize":
            out["compare"] = render.wdiff(out["params"].get("text", ""), str(out["result"].get("rewritten") or ""))
        out["finished_ago"] = s.ago(job["finished_at"])
        return out

    def tool_result(kind: str, job_id: int):
        """One of this tool's finished results from Tools, or None."""
        return db.one("SELECT * FROM jobs WHERE id=? AND kind=? AND status='done' AND json_extract(params,'$.source')='tools'",
                      (job_id, kind)) if kind in TOOL_KINDS else None

    def input_line(params: str | None) -> str:
        """What a result was made from, in a line: the first line of the text, or the link."""
        given = loads(params, {}) or {}
        line = next((x.strip() for x in str(given.get("text") or "").splitlines() if x.strip()), "") or str(given.get("url") or "").strip()
        return line if len(line) <= 120 else line[:119].rstrip() + "…"

    def tool_public(kind: str) -> dict:
        job = tool_job(kind)
        out = s.job_public(job) if job is not None else None
        if out is not None and job["status"] == "done":
            out = tool_done(job)
        finished = db.all("SELECT id, params, finished_at FROM jobs WHERE kind=? AND status='done' "
                          "AND json_extract(params,'$.source')='tools' ORDER BY id DESC LIMIT ?", (kind, EARLIER))
        return {"kind": kind, "title": ACTIONS[kind].title, "blurb": ACTIONS[kind].blurb, "icon": ACTIONS[kind].icon,
                "job": out, "can_post": kind in TOOL_POSTS,
                "earlier": [{"id": r["id"], "when": s.ago(r["finished_at"]), "first": input_line(r["params"])} for r in finished]}

    @app.get("/api/tools")
    def tools():
        return {"tools": [tool_public(k) for k in TOOL_KINDS], "apify": pub.status()["apify"], "goals": GOALS,
                "modes": HUMANIZE_MODES, "reactions": REACTIONS}

    @app.get("/api/tools/{kind}/{job_id}")
    def tool_earlier(kind: str, job_id: int):
        job = tool_result(kind, job_id)
        if job is None:
            return fail("That result is not here any more.", 404)
        return {"job": tool_done(job)}

    @app.post("/api/tools/{kind}/{job_id}/draft")
    def tool_to_post(kind: str, job_id: int):
        """Start a post from this: a draft of the post's text a result holds, with its first version. Humanize gives its
        rewrite (what is worth adding becomes the writer's notes), Audit the draft it audited (its findings beside it),
        Hook extractor its blank template, Repurposer its post and first comment."""
        if kind not in TOOL_KINDS:
            return fail("Unknown tool.", 404)
        if kind not in TOOL_POSTS:
            return fail(NOT_A_POST.get(kind, "This result is not a post."))
        job = tool_result(kind, job_id)
        if job is None:
            return fail("That result is not here any more.", 404)
        data, given = loads(job["result"], {}) or {}, loads(job["params"], {}) or {}
        text = {"humanize": data.get("rewritten"), "audit": given.get("text"), "hook": data.get("template"),
                "repurpose": data.get("post")}[kind]
        text = str(text or "").replace("\r\n", "\n").strip()
        if not text:
            return fail("This result holds no post text.")
        first = str(data.get("first_comment") or "").strip() or None if kind == "repurpose" else None
        formula = str(data.get("formula") or "") or None if kind in ("hook", "repurpose") else None
        notes = [str(n) for n in data.get("missing") or [] if str(n).strip()] if kind == "humanize" else []
        audit = dumps({**data, "job_id": job_id, "text": text}) if kind == "audit" else None
        now = utcnow()
        post_id = db.run("INSERT INTO posts (created_at, updated_at, title, text, first_comment, formula, notes, audit, status) "
                         "VALUES (?,?,?,?,?,?,?,?, 'draft')",
                         (now, now, flows.short_title(text.splitlines()[0]), text, first, formula, dumps(notes), audit))
        versions.record(db, post_id, text, first, "you" if kind == "audit" else "claude", TOOL_POSTS[kind])
        return {"post": post_id}

    @app.post("/api/tools/{kind}")
    def tool_run(kind: str, data: dict = Body(default={})):
        if kind not in TOOL_KINDS:
            return fail("Unknown tool.", 404)
        text, url = str(data.get("text") or "").strip(), str(data.get("url") or "").strip()
        if not text and not (url and kind in ("hook", "comment")):
            return fail("Paste some text first." if kind not in ("hook", "comment")
                        else "Paste the post text, or give its URL (that needs an Apify token).")
        mode = str(data.get("mode") or "")
        if mode and mode not in HUMANIZE_MODES:
            return fail("Unknown mode.")
        return {"job": jobs.submit(kind, {"source": "tools", "text": text, "url": url, "mode": mode,
                                          "goal": str(data.get("goal") or ""), "angle": str(data.get("angle") or "").strip(),
                                          **({"style": style.default(db)} if kind == "repurpose" else {})})}

    # ---- settings ----------------------------------------------------------------------
    @app.get("/api/settings")
    def settings():
        said = claude_said()
        runs = db.all("SELECT r.*, j.kind FROM runs r LEFT JOIN jobs j ON j.id = r.job_id ORDER BY r.id DESC LIMIT 50")
        checks = {}
        for name in ("check_config", "selftest"):
            row = s.health.latest(name)
            checks[name] = {"running": bool(s.health.running.get(name)),
                            "row": {"ok": row["exit_code"] == 0, "when": s.ago(row["ran_at"]), "output": row["output"] or ""}
                            if row else None}
        p = s.protection
        return {
            "claude": {"version": said, "ready": "Claude Code" in said, "login": str(cfg.claude_config_dir),
                       "sign_in": sign_in(),
                       "model": cfg.model or "Account default", "turns": cfg.max_turns, "seconds": cfg.timeout_seconds,
                       "chat_turns": cfg.chat_max_turns, "chat_seconds": cfg.chat_timeout_seconds,
                       "program": str(cfg.claude_bin), "skills": str(cfg.skills_dir)},
            "publora": pub.status(), "limit": cfg.monthly_post_limit, "timezone": cfg.timezone, "tz": s.tz_label,
            "protection": {"ok": p.ok, "state": p.state, "detail": p.detail},
            "problems": problems(cfg), "data_dir": str(s.db.path.parent), "checks": checks,
            "runs": [{"when": s.ago(r["started_at"]), "what": ACTIONS[r["kind"]].title if r["kind"] in ACTIONS else r["skill"],
                      "skill": r["skill"], "outcome": r["outcome"], "error": (r["error"] or "")[:140],
                      "denials": r["denials"] or 0, "seconds": round((r["duration_ms"] or 0) / 1000, 1),
                      "turns": r["num_turns"] or "",
                      "tokens_in": (r["input_tokens"] or 0) + (r["cache_read_tokens"] or 0) + (r["cache_creation_tokens"] or 0),
                      "tokens_out": r["output_tokens"] or 0} for r in runs],
        }

    # Settings › ChatGPT (codex.py): who is signed in (email and plan only, never a token), Sign in, the Codex home.
    @app.get("/api/codex")
    def codex_card():
        return codex.chatgpt_status()

    @app.post("/api/codex/login")
    def codex_login():
        said = codex.chatgpt_sign_in()
        return fail(said, 409) if said else {"ok": True}

    @app.post("/api/codex/stop")
    def codex_stop():
        codex.chatgpt_stop_sign_in()
        return {"ok": True}

    @app.post("/api/codex/home")
    def codex_home(data: dict = Body(default={})):
        text = str(data.get("home") or "").strip().strip('"').strip()
        try:
            codex.set_codex_home(text)
        except codex.CodexError as exc:
            return fail(str(exc))
        return {"ok": True, "home": text}

    @app.post("/api/settings/claude/check")
    def settings_sign_in():
        return {"sign_in": sign_in(fresh=True)}

    # Settings › Post style (style.py): the sliders every new draft is written with, and what each step is called.
    def style_public() -> dict:
        return {"style": style.default(db), "studio": style.DEFAULT, "sliders": style.SLIDERS, "labels": style.LABELS}

    @app.get("/api/style")
    def style_get():
        return style_public()

    @app.post("/api/style")
    def style_save(data: dict = Body(default={})):
        try:
            style.save_default(db, data)
        except style.Refused as exc:
            return fail(str(exc))
        except OSError as exc:
            return fail(f"It could not be saved ({exc.strerror or exc}).", 500)
        return style_public()

    # Settings › Posting times (posting.py): the days and times the queue gives its posts, and the Planner plans for.
    def posting_public() -> dict:
        return {"times": s.queue.times(), "studio": posting.DEFAULT, "days": [[d, posting.NAMES[d]] for d in posting.DAYS],
                "words": posting.words(s.queue.times()), "limit": cfg.monthly_post_limit, "window": MAX_AHEAD.days}

    @app.get("/api/posting")
    def posting_get():
        return posting_public()

    @app.post("/api/posting")
    def posting_save(data: dict = Body(default={})):
        try:
            posting.save(db, data.get("times"))
        except posting.Refused as exc:
            return fail(str(exc))
        except OSError as exc:
            return fail(f"They could not be saved ({exc.strerror or exc}).", 500)
        db.touch()                       # every queued post's time moves with them
        s.queue.send_due()               # and one may now be inside the window
        return posting_public()

    # Settings › You in the preview (profile.py): kept beside the database, read by the preview alone.
    @app.get("/api/profile")
    def profile_get():
        return profile.public(db)

    def profile_change(change, *args):
        try:
            return change(db, *args)
        except profile.Refused as exc:
            return fail(str(exc))
        except OSError as exc:
            return fail(f"It could not be saved ({exc.strerror or exc}).", 500)

    @app.post("/api/profile")
    def profile_save(data: dict = Body(default={})):
        return profile_change(profile.save_words, data.get("name"), data.get("headline"))

    @app.post("/api/profile/photo")
    def profile_photo(data: dict = Body(default={})):
        return profile_change(profile.save_photo, data.get("data"))

    @app.post("/api/profile/photo/remove")
    def profile_photo_remove(_data: dict = Body(default={})):
        return profile_change(profile.remove_photo)

    @app.get("/api/profile/photo")
    def profile_photo_file():
        found = profile.photo(db)
        if found is None:
            return fail("No photo is set.", 404)
        body, mime = found
        return Response(body, media_type=mime, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    @app.post("/api/settings/health/{name}")
    def settings_health(name: str):
        if not s.health.start(name):
            return fail("That check is already running.", 409)
        return {"ok": True}

    # ---- the setup screen: three folders ---------------------------------------------------
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
        # Who each login folder is signed in to: the ones found on this PC and the one in the box, asked side by side.
        folders = list(dict.fromkeys([*found["claude_config_dir"], *([values["claude_config_dir"]] if values.get("claude_config_dir") else [])]))
        folders = [f for f in folders if Path(f).is_absolute() and Path(f).is_dir()]
        program = values.get("claude_bin") or str(cfg.claude_bin)
        program = program if Path(program).is_file() else str(cfg.claude_bin)
        with ThreadPoolExecutor(max_workers=4) as pool:
            signed = dict(zip(folders, pool.map(lambda f: account_of(f, program), folders)))
        return {"fields": [{"key": f.key, "label": f.label, "kind": f.kind, "what": f.what} for f in paths.FIELDS],
                "values": values, "errors": errors or {}, "found": found, "accounts": signed,
                "examples": {key: str(where[0]) for key, where in places.items()}, "first_run": s.needs_setup,
                "saved": saved, "restarts": s.on_restart is not None}

    @app.get("/api/setup")
    def setup_page():
        return setup_ctx()

    @app.post("/api/setup")
    def setup_save(data: dict = Body(default={})):
        values = {f.key: str(data.get(f.key) or "") for f in paths.FIELDS}
        chosen, errors = paths.check(values, cfg, prefix=getattr(jobs.runner, "prefix", None))
        if not errors:
            try:
                paths.save(chosen)
            except ConfigError as exc:
                errors = {"": str(exc)}
        if errors:
            return setup_ctx(values, errors)
        if s.on_restart:
            threading.Timer(0.8, s.on_restart).start()     # after this answer has reached the window
        return setup_ctx({k: str(v) for k, v in chosen.items()}, {}, saved=True)

    @app.post("/api/setup/browse")
    def setup_browse(data: dict = Body(default={})):
        spec = next((f for f in paths.FIELDS if f.key == data.get("field")), None)
        if spec is None:
            return fail("Unknown setting.", 404)
        try:
            return {"path": paths.browse(spec, str(data.get("start") or ""))}
        except paths.PickerBusy:
            return fail("A file window is already open. Look for it behind this window.", 409)
        except (OSError, subprocess.SubprocessError) as exc:
            return fail(f"Windows could not open the file window ({exc}). Type or paste the path instead.", 500)

    # ---- the guide -------------------------------------------------------------------
    @app.get("/api/guide")
    def guide_page():
        # The figures the guide quotes come from the code that enforces them.
        numbers = {"limit": cfg.monthly_post_limit, "post_max": f"{POST_MAX:,}",
                   "min_lead": int(MIN_LEAD.total_seconds() // 60), "max_days": MAX_AHEAD.days,
                   "target_min": f"{TARGET['min']:,}", "target_max": f"{TARGET['max']:,}", "fold": TARGET["fold"],
                   "timeout": cfg.timeout_seconds, "tz": s.tz_label, "per_request": jobs.images_per_request}
        screens = guide.fill(guide.SCREENS, numbers)
        shots = guide.shots(GUIDE_SHOTS)
        for screen in screens:
            if screen["key"] == "tools":    # one line per tool, from the same descriptions the Tools page shows
                screen["points"] = [f"{ACTIONS[k].title}: {ACTIONS[k].blurb}" for k in TOOL_KINDS] + screen["points"]
            screen["shot"] = screen.get("shot", screen["key"]) if screen.get("shot", screen["key"]) in shots else None
        lanes = guide.fill(guide.LANES, numbers)
        for step in (step for lane in lanes for step in lane["steps"]):
            step["shot"] = step.get("shot") if step.get("shot") in shots else None
        return {"lanes": lanes, "states": guide.fill(guide.STATES, numbers),
                "screens": screens, "shortcuts": guide.SHORTCUTS, "sample": guide.SAMPLE_POST, "numbers": numbers,
                "private": s.protection.ok, "target": TARGET, "shots": shots}
