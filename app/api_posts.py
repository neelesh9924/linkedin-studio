"""The API of one post: the editor's actions, its chat, its versions and its picture, sending it to Publora, and
moving it to the Trash (api_trash.py has the Trash itself).

Every endpoint of a post asks `find` for it: one that is gone, or in the Trash, is refused in the same words. A post
in the Trash keeps everything (its state, versions, chat, pictures and plan link) and nothing here can change it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Body, FastAPI
from fastapi.responses import FileResponse, JSONResponse

from . import attached, attachments, images, render, versions
from .db import loads, utcnow
from .flows import add_message
from .main import ACTIVE, PROBLEM, Studio
from .publishing import (DASHBOARD_URL, FIRST_COMMENT_MAX, MAX_AHEAD, MIN_LEAD, NO_REASON, ScheduleError,
                         placeholder_slots, retry_with_picture, schedule_with_picture)
from .skills import REVISION_LABELS, REVISIONS
from .status_check import failure_words

CHAT_BUSY = "Claude is still working on this post. What you wrote stays in the box: send it once Claude is done."
TEXT_BUSY = "Claude is working on this post: its text waits until Claude is done."
GONE = "That post no longer exists."
TRASHED = "That post is in the Trash."


def fail(text: str, status: int = 422, **extra) -> JSONResponse:
    return JSONResponse({"error": text, **extra}, status_code=status)


def trash_refusal(row, working: bool) -> str:
    """Why this post cannot go to the Trash just now, or "" when it can (the gear offers Move to Trash… then)."""
    status = row["status"]
    if status == "scheduling":
        return "This post is being sent to Publora just now, so it stays here."
    if status == "scheduled":
        return "A scheduled post can't go to the Trash. Cancel it on Publora first (the gear's Cancel on Publora…)."
    if status == "published":
        return "A published post stays here: it can't go to the Trash."
    if (loads(row["media"], {}) or {}).get("postGroupId"):
        return ("Publora still holds an unsent draft of this post. Move it back to draft first: that takes the draft off "
                "Publora.")
    if working:
        return "Claude is working on this post. It can go to the Trash once Claude is done, or once you stop it."
    return ""


def due_now(row, now: datetime) -> bool:
    """A scheduled post whose time has passed: Publora should have sent it by now."""
    at = render.parse_utc(row["scheduled_at"] or "") if row["status"] == "scheduled" else None
    return at is not None and at <= now


def register(app: FastAPI, s: Studio) -> None:
    db, jobs, pub, cfg = s.db, s.jobs, s.pub, s.cfg

    def get_post(post_id: int):
        """The row, the Trash's too: only `find` decides what an endpoint may do with it."""
        return db.one("SELECT * FROM posts WHERE id=?", (post_id,))

    def find(post_id: int):
        """(the post, None), or (None, the refusal) for a post that is gone or in the Trash."""
        row = get_post(post_id)
        if row is None:
            return None, fail(GONE, 404, gone=True)
        if row["trashed_at"]:
            return None, fail(TRASHED, 404, trashed=True)
        return row, None

    def jobs_for(post_id: int, kinds: tuple[str, ...]) -> list:
        marks = ",".join("?" * len(kinds))
        return db.all(f"SELECT * FROM jobs WHERE kind IN ({marks}) AND json_extract(params, '$.post_id')=? ORDER BY id DESC",
                      (*kinds, post_id))

    def visible(job) -> bool:
        """A job the page should still show: running, or a problem nobody dismissed yet."""
        return job["status"] in ACTIVE or (job["status"] in PROBLEM and not job["acked"])

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
        if all(slot.date() != tomorrow for slot in slots):
            slots.append((now_local + timedelta(days=1)).replace(hour=8, minute=30, second=0, microsecond=0))
        picks = []
        for slot in sorted(slots):
            text = render.local_time(slot.astimezone(timezone.utc).isoformat(), cfg.tz)
            day = "Today" if slot.date() == now_local.date() else "Tomorrow" if slot.date() == tomorrow else None
            picks.append({"value": slot.strftime("%Y-%m-%dT%H:%M"), "label": f"{day}, {text.split(', ')[1]}" if day else text})
        return picks

    def revision_public(job, post) -> dict:
        data = loads(job["result"], {}) or {}
        how = (loads(job["params"], {}) or {}).get("how")
        label, promise = REVISION_LABELS.get(how, ("Revision", ""))
        text = str(data.get("text") or "")
        return {"job": job["id"], "how": how, "label": label, "promise": promise, "text": text,
                "segments": render.wdiff(post["text"], text), "chars": len(text), "first_comment": data.get("first_comment"),
                "changes": [str(c) for c in data.get("changes") or [] if c]}

    def post_full(row) -> dict:
        pid = row["id"]
        busy = s.post_busy(pid)
        related = jobs_for(pid, ("audit", "revise"))
        audit_job = next((j for j in related if j["kind"] == "audit" and visible(j)), None)
        revise_job = next((j for j in related if j["kind"] == "revise" and visible(j)), None)
        revision = next((j for j in related if j["kind"] == "revise" and j["status"] == "done" and not j["acked"]), None)
        if revise_job is not None and revision is not None and revision["id"] > revise_job["id"]:
            revise_job = None   # an older failure is moot once a newer revision arrived
        audit = loads(row["audit"], None)
        if isinstance(audit, dict):
            audit = {"verdict": str(audit.get("verdict") or "").upper(), "summary": str(audit.get("summary") or ""),
                     "blockers": audit.get("blockers") or [], "warnings": audit.get("warnings") or [],
                     "stale": audit.get("text") != row["text"]}
        else:
            audit = None
        pictures = images.for_post(db, pid)
        chosen = next((p for p in pictures if p["id"] == row["picture_id"]), None)
        now = datetime.now(timezone.utc)
        now_local = now.astimezone(cfg.tz)
        plan = None
        if row["plan_item_id"]:
            item = db.one("SELECT data FROM plan_items WHERE id=?", (row["plan_item_id"],))
            data = loads(item["data"], {}) if item else {}
            plan = {k: data.get(k) for k in ("day", "time", "angle", "formula", "pillar", "goal", "cta") if data.get(k)}
        status = row["status"]
        trash_why = trash_refusal(row, s.post_working(pid))
        due = due_now(row, now)
        return {
            **s.post_summary(row),
            "text": row["text"], "first_comment": row["first_comment"] or "", "formula": row["formula"] or "",
            "notes": [str(n) for n in loads(row["notes"], []) or [] if n],
            "audit": audit, "audit_job": s.job_public(audit_job) if audit_job else None,
            "revise_job": s.job_public(revise_job) if revise_job else None,
            "revision": revision_public(revision, row) if revision is not None and status == "draft" else None,
            "slots": len(placeholder_slots(row["text"])), "chars": len(row["text"]),
            "editable": status == "draft" and not busy,
            "deletable": not trash_why, "trash_why": trash_why,      # Move to Trash… is offered, or why it is not
            "error": row["error"] or "", "saved": s.clock(row["updated_at"]),
            "picture": images.public(chosen, row["picture_id"]) if chosen else None,
            "pictures": [images.public(p, row["picture_id"]) for p in pictures],
            "schedule": {"min": (now_local + MIN_LEAD + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M"),
                         "max": (now_local + MAX_AHEAD).strftime("%Y-%m-%dT%H:%M"),
                         "quick": quick_times(now_local)} if status == "approved" else None,
            "publora": pub.status(), "used": pub.quota_used(now), "limit": cfg.monthly_post_limit,
            "month": now_local.strftime("%B"), "dashboard": DASHBOARD_URL, "first_comment_max": FIRST_COMMENT_MAX,
            "can_retry": status == "failed" and not row["publora_post_id"] and bool(row["publora_payload"]),
            "can_back": status in ("approved", "failed") and not row["publora_post_id"],
            "plan": plan, "versions": db.one("SELECT COUNT(*) AS n FROM versions WHERE post_id=?", (pid,))["n"],
            # A scheduled post whose time has passed: what the light check last heard (status_check.py), for its notice.
            "waiting": s.checker.notice(pid, s.clock) if due else None,
        }

    def save_fields(post_id: int, title: Any, text: Any, first_comment: Any):
        """Store the editor's fields if the post is still a draft Claude is not working on. The fresh row, or None.
        A save that takes away a third or more of the text keeps the text before it as a version first."""
        post = db.one("SELECT * FROM posts WHERE id=? AND status='draft' AND trashed_at IS NULL", (post_id,))
        if post is None or s.post_busy(post_id):
            return None
        if not isinstance(text, str):
            return post
        new_text = text.replace("\r\n", "\n").strip()
        new_fc = (first_comment if isinstance(first_comment, str) else post["first_comment"] or "").replace("\r\n", "\n").strip() or None
        new_title = (title if isinstance(title, str) else "").strip()[:120] or post["title"]
        if (new_text, new_fc, new_title) != (post["text"], post["first_comment"], post["title"]):
            if versions.big_cut(post["text"], new_text):
                versions.catch_up(db, post_id)
            db.run("UPDATE posts SET text=?, first_comment=?, title=?, updated_at=? WHERE id=? AND status='draft' "
                   "AND trashed_at IS NULL", (new_text, new_fc, new_title, utcnow(), post_id))
            post = get_post(post_id)
        return post

    def locked(post_id: int) -> JSONResponse:
        _row, refusal = find(post_id)
        if refusal is not None:
            return refusal
        if s.post_busy(post_id):
            return fail(TEXT_BUSY, 409)
        return fail("Only a draft can be edited. Move it back to draft first.", 409)

    # ---- the list and a new post ----------------------------------------------------
    @app.post("/api/posts/new")
    def post_new(data: dict = Body(default={})):
        now = utcnow()
        title = str(data.get("title") or "").strip()[:120] or "Untitled draft"
        post_id = db.run("INSERT INTO posts (created_at, updated_at, title, text, status) VALUES (?,?,?,?, 'draft')",
                         (now, now, title, ""))
        return {"id": post_id, "post": s.post_summary(get_post(post_id))}   # the page lists it before it opens it

    @app.post("/api/posts/refresh")
    def refresh_due():
        due = db.all("SELECT id FROM posts WHERE status='scheduled' AND trashed_at IS NULL AND scheduled_at <= ?",
                     (datetime.now(timezone.utc).isoformat(timespec="seconds"),))
        errors = []
        for row in due:
            try:
                s.checker.check(row["id"])   # what it heard is kept for the post's notice, as the light check's is
            except Exception as exc:
                errors.append(str(exc))
        if errors:
            return fail("Could not reach Publora: " + "; ".join(errors)[:300], 502)
        return {"checked": len(due), "said": "Nothing was due yet." if not due else
                f"Checked {len(due)} post{'s' if len(due) != 1 else ''}."}

    @app.get("/api/post/{post_id}")
    def post_get(post_id: int):
        row, refusal = find(post_id)
        return refusal if refusal is not None else post_full(row)

    # ---- the editor ----------------------------------------------------------------
    @app.post("/api/post/{post_id}/save")
    def post_save(post_id: int, data: dict = Body(default={})):
        post = save_fields(post_id, data.get("title"), data.get("text"), data.get("first_comment"))
        if post is None:
            return locked(post_id)
        return {"chars": len(post["text"]), "slots": len(placeholder_slots(post["text"])), "saved": s.clock(post["updated_at"])}

    @app.post("/api/post/{post_id}/audit")
    def post_audit(post_id: int, data: dict = Body(default={})):
        post, refusal = find(post_id)
        if refusal is not None:
            return refusal
        post = save_fields(post_id, data.get("title"), data.get("text"), data.get("first_comment")) or post
        if not post["text"].strip():
            return fail("Write something first.")
        if any(j["status"] in ACTIVE for j in jobs_for(post_id, ("audit",))):
            return fail("An audit is already running.")
        for old in jobs_for(post_id, ("audit",)):
            jobs.dismiss(old["id"])
        return {"job": jobs.submit("audit", {"post_id": post_id, "text": post["text"]})}

    @app.post("/api/post/{post_id}/revise")
    def post_revise(post_id: int, data: dict = Body(default={})):
        how = data.get("how")
        _row, refusal = find(post_id)
        if refusal is not None:
            return refusal
        post = save_fields(post_id, data.get("title"), data.get("text"), data.get("first_comment"))
        if post is None or how not in REVISIONS or not post["text"].strip():
            return fail("Only a draft with some text can be revised.")
        if any(j["status"] in ACTIVE for j in jobs_for(post_id, ("revise",))):
            return fail("A revision is already being written.")
        for old in jobs_for(post_id, ("revise",)):
            jobs.dismiss(old["id"])
        return {"job": jobs.submit("revise", {"post_id": post_id, "how": how, "text": post["text"]})}

    @app.post("/api/post/{post_id}/revision")
    def post_use_revision(post_id: int, data: dict = Body(default={})):
        post, refusal = find(post_id)
        if refusal is not None:
            return refusal
        job = db.one("SELECT * FROM jobs WHERE id=? AND kind='revise'", (int(data.get("job") or 0),))
        if post["status"] != "draft" or job is None or (loads(job["params"], {}) or {}).get("post_id") != post_id:
            return fail("That revision can no longer be applied.", 409)
        if s.post_busy(post_id):
            return fail(TEXT_BUSY, 409)
        result = loads(job["result"], {}) or {}
        jobs.dismiss(job["id"])
        text = str(result.get("text") or "").strip()
        if not data.get("use") or not text:
            return {"used": False}
        how = (loads(job["params"], {}) or {}).get("how")
        versions.catch_up(db, post_id)
        first = result.get("first_comment") or post["first_comment"]
        db.run("UPDATE posts SET text=?, first_comment=?, audit=NULL, updated_at=? WHERE id=? AND trashed_at IS NULL",
               (text, first, utcnow(), post_id))
        versions.record(db, post_id, text, first, "claude", REVISION_LABELS.get(how, ("Revision",))[0])
        return {"used": True}

    def transition(post_id: int, fn) -> Any:
        _row, refusal = find(post_id)
        if refusal is not None:
            return refusal
        try:
            result = fn()
        except ScheduleError as exc:
            return fail(str(exc), 409)
        if isinstance(result, dict):
            return {"ok": bool(result.get("ok", True)), "error": result.get("error", "")}
        return {"ok": True}

    def picture_of(row) -> dict | None:
        """The post's chosen picture as publishing.py takes it: {path, name, mime, sha256}; None for none."""
        if not row["picture_id"]:
            return None
        image = db.one("SELECT * FROM images WHERE id=? AND post_id=?", (row["picture_id"], row["id"]))
        path = images.path_of(db, image)
        if path is None:
            raise ScheduleError("The post's picture is missing from the images folder. Take it off the post, or choose another.")
        return {"path": str(path), "name": f"linkedin-studio-{row['id']}-{image['id']}{path.suffix}", "mime": image["mime"],
                "sha256": image["sha256"]}

    @app.post("/api/post/{post_id}/approve")
    def post_approve(post_id: int, data: dict = Body(default={})):
        _row, refusal = find(post_id)
        if refusal is not None:
            return refusal
        if s.post_busy(post_id):
            return fail(TEXT_BUSY, 409)
        save_fields(post_id, data.get("title"), data.get("text"), data.get("first_comment"))
        done = transition(post_id, lambda: pub.approve(post_id))
        row = get_post(post_id)
        if isinstance(done, dict) and row is not None and row["status"] == "approved":   # the text it was approved with
            versions.record(db, post_id, row["text"], row["first_comment"], "you", "Approved")
        return done

    @app.post("/api/post/{post_id}/unapprove")
    def post_unapprove(post_id: int):
        return transition(post_id, lambda: pub.back_to_draft(post_id))

    # A post's picture goes out with it through Publora's own upload (publishing.py); without one it is the single
    # keyed request as before. Either way exactly once, and Retry carries on from where it stopped.
    @app.post("/api/post/{post_id}/schedule")
    def post_schedule(post_id: int, data: dict = Body(default={})):
        row = get_post(post_id)
        when, comment = str(data.get("when") or ""), data.get("first_comment")
        return transition(post_id, lambda: schedule_with_picture(pub, post_id, when, comment, picture_of(row)))

    @app.post("/api/post/{post_id}/retry")
    def post_retry(post_id: int):
        row = get_post(post_id)
        return transition(post_id, lambda: retry_with_picture(pub, post_id, picture_of(row)))

    @app.post("/api/post/{post_id}/cancel")
    def post_cancel(post_id: int):
        return transition(post_id, lambda: pub.cancel(post_id))

    @app.post("/api/post/{post_id}/refresh")
    def post_refresh(post_id: int):
        """Check now: Publora's word on a scheduled post, read at once (get-post only, nothing is sent), in words:
        published, failed in Publora's own words, or still waiting, with the time it was asked."""
        row, refusal = find(post_id)
        if refusal is not None:
            return refusal
        if row["status"] != "scheduled" or not row["publora_post_id"]:
            return {"status": row["status"], "said": "Only a scheduled post is asked about on Publora."}
        try:
            status = s.checker.check(post_id)
        except Exception as exc:
            return fail(f"Could not ask Publora just now ({failure_words(exc)}). Try again in a minute.", 502)
        row = get_post(post_id)
        due = due_now(row, datetime.now(timezone.utc))
        if status == "published":
            said = ("Publora says it is published. Open on LinkedIn shows it." if s.post_summary(row)["link"]
                    else "Publora says it is published. It gave no link to the post.")
        elif status == "failed":
            said = row["error"] or NO_REASON
        elif due:
            said = f"Not out yet: Publora still has it scheduled (checked {s.clock(utcnow())})."
        else:   # its time is in the top bar's chip already
            said = f"All set: Publora has it scheduled (checked {s.clock(utcnow())})."
        # `waiting` as the post now says it: the page keeps these words until the light check hears something newer
        return {"status": status, "said": said, "waiting": s.checker.notice(post_id, s.clock) if due else None}

    # ---- Move to Trash…, the title, your own edits, New draft from this --------------------
    @app.post("/api/post/{post_id}/trash")
    def post_trash(post_id: int):
        """The gear's Move to Trash…: the post leaves the list with everything it has; the Trash puts it back or deletes
        it forever. Never a post on Publora (scheduling, scheduled, published, or a picture post's Publora draft), and
        never while Claude works on it or waits to (its chat, an audit or a revision)."""
        row, refusal = find(post_id)
        if refusal is not None:
            return refusal
        why = trash_refusal(row, s.post_working(post_id))
        if why:
            return fail(why, 409)
        # Checked again in the one statement that moves it, so nothing that started meanwhile is overtaken.
        moved = db.run("UPDATE posts SET trashed_at=? WHERE id=? AND trashed_at IS NULL "
                       "AND status NOT IN ('scheduling','scheduled','published') "
                       "AND (media IS NULL OR NOT json_valid(media) OR json_extract(media, '$.postGroupId') IS NULL) "
                       "AND NOT EXISTS (SELECT 1 FROM jobs WHERE status IN ('queued','running') "
                       "AND json_extract(params, '$.post_id')=?)", (utcnow(), post_id, post_id))
        if moved != 1:
            return fail("The post changed just now, so it stayed. Look at it again.", 409)
        return {"ok": True, "id": post_id}

    @app.post("/api/post/{post_id}/title")
    def post_title(post_id: int, data: dict = Body(default={})):
        """The title only (only the owner sees it), in any state but the Trash: the text is never sent with it."""
        row, refusal = find(post_id)
        if refusal is not None:
            return refusal
        title = " ".join(str(data.get("title") or "").split())[:120]
        if not title:
            return fail("Give the post a title. Only you see it.")
        if title != row["title"]:
            db.run("UPDATE posts SET title=?, updated_at=? WHERE id=? AND trashed_at IS NULL", (title, utcnow(), post_id))
        return {"ok": True, "title": title}

    @app.post("/api/post/{post_id}/checkpoint")
    def post_checkpoint(post_id: int):
        """The owner left the text after typing: their edits are kept as a version when they differ from the latest."""
        row, refusal = find(post_id)
        if refusal is not None:
            return refusal
        if row["status"] != "draft":
            return {"version": None}
        return {"version": versions.checkpoint(db, post_id)}

    @app.post("/api/post/{post_id}/copy")
    def post_copy(post_id: int):
        """New draft from this: the text, first comment, formula, notes and picture (its file is shared, not copied),
        with a first version that says where it came from. Any state but the Trash."""
        row, refusal = find(post_id)
        if refusal is not None:
            return refusal
        now = utcnow()
        with db.transaction() as con:
            new = con.execute("INSERT INTO posts (created_at, updated_at, title, text, first_comment, formula, notes, status) "
                              "VALUES (?,?,?,?,?,?,?, 'draft')",
                              (now, now, row["title"], row["text"], row["first_comment"], row["formula"], row["notes"])).lastrowid
            image = (con.execute("SELECT * FROM images WHERE id=? AND post_id=?", (row["picture_id"], post_id)).fetchone()
                     if row["picture_id"] else None)
            if image is not None:
                copy = con.execute("INSERT INTO images (post_id, file, source, prompt, shape, width, height, mime, sha256, "
                                   "job_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                   (new, image["file"], image["source"], image["prompt"], image["shape"], image["width"],
                                    image["height"], image["mime"], image["sha256"], image["job_id"], now)).lastrowid
                con.execute("UPDATE posts SET picture_id=? WHERE id=?", (copy, new))
        versions.record(db, new, row["text"], row["first_comment"], "studio", f"From {row['title']}")
        return {"id": new, "post": s.post_summary(get_post(new))}

    # ---- versions -------------------------------------------------------------------
    @app.get("/api/post/{post_id}/versions")
    def post_versions(post_id: int):
        post, refusal = find(post_id)
        if refusal is not None:
            return refusal
        listed = []
        for v in versions.listing(db, post_id):
            item = {"id": v["id"], "author": v["author"], "note": v["note"] or "", "when": s.when(v["created_at"]),
                    "chars": len(v["text"]), "first": (v["text"].strip().splitlines() or [""])[0][:140],
                    "current": (v["text"], v["first_comment"]) == (post["text"], post["first_comment"])}
            if not item["current"]:   # Compare with now: that version's words to the post's now, word by word
                item["segments"] = render.wdiff(v["text"], post["text"])
                item["first_comment_differs"] = (v["first_comment"] or None) != (post["first_comment"] or None)
            listed.append(item)
        return {"versions": listed, "editable": post["status"] == "draft" and not s.post_busy(post_id)}

    @app.post("/api/post/{post_id}/versions/back")
    def post_go_back(post_id: int, data: dict = Body(default={})):
        _row, refusal = find(post_id)
        if refusal is not None:
            return refusal
        if s.post_busy(post_id):
            return fail(TEXT_BUSY, 409)
        wanted = int(data.get("version") or 0)
        try:
            changed = versions.go_back(db, post_id, wanted)
        except versions.VersionError as exc:
            return fail(str(exc), 409)
        if changed:   # one line in the post's chat (started if it has none), so the chat and Claude know it
            version = db.one("SELECT created_at, note FROM versions WHERE id=?", (wanted,))
            note = f" ({version['note']})" if version["note"] else ""
            add_message(db, conversation(post_id, create=True)["id"], "info",
                        f"You went back to the version of {render.day_time(version['created_at'], cfg.tz)}{note}.")
        return {"changed": changed}

    # ---- the picture ------------------------------------------------------------------
    @app.post("/api/post/{post_id}/picture")
    def post_picture(post_id: int, data: dict = Body(default={})):
        post, refusal = find(post_id)
        if refusal is not None:
            return refusal
        if post["status"] != "draft":
            return fail("The picture goes with the approved text: move the post back to draft to change it.", 409)
        chosen = data.get("image")
        if chosen is not None:
            image = db.one("SELECT id FROM images WHERE id=? AND post_id=?", (int(chosen or 0), post_id))
            if image is None:
                return fail("That picture is not this post's.", 404)
            chosen = image["id"]
        db.run("UPDATE posts SET picture_id=?, updated_at=? WHERE id=? AND trashed_at IS NULL", (chosen, utcnow(), post_id))
        return {"ok": True, "picture": chosen}

    # ---- the post's chat --------------------------------------------------------------
    def conversation(post_id: int, create: bool = False):
        conv = db.one("SELECT * FROM conversations WHERE mode='post' AND post_id=? AND cleared_at IS NULL "
                      "ORDER BY id DESC LIMIT 1", (post_id,))
        if conv is None and create:
            conv_id = db.run("INSERT INTO conversations (mode, post_id, created_at) VALUES ('post', ?, ?)",
                             (post_id, utcnow()))
            conv = db.one("SELECT * FROM conversations WHERE id=?", (conv_id,))
        return conv

    def message_public(m, chosen: int | None, post_id: int) -> dict:
        meta = loads(m["meta"], {}) or {}
        out: dict[str, Any] = {"id": m["id"], "role": "claude" if m["role"] == "assistant" else m["role"],
                               "text": m["text"], "at": s.clock(m["created_at"]), "job": m["job_id"]}
        if m["diff"]:
            added, removed = render.diffstat(m["diff"])
            out["diff"] = {"text": m["diff"], "added": added, "removed": removed}
        if meta.get("images"):
            marks = ",".join("?" * len(meta["images"]))
            rows = db.all(f"SELECT * FROM images WHERE id IN ({marks}) ORDER BY id", tuple(meta["images"]))
            out["images"] = [images.public(r, chosen) for r in rows]
        if meta.get("files"):
            out["files"] = attached.public(meta["files"], f"/api/post/{post_id}/file")
        if meta.get("versions"):
            out["versions"] = len(meta["versions"])
        if meta.get("offer"):
            out["offer"], out["request"] = meta["offer"], meta.get("request")
        return out

    def thread(conv, chosen: int | None) -> list[dict]:
        if conv is None:
            return []
        return [message_public(m, chosen, conv["post_id"]) for m in
                db.all("SELECT * FROM messages WHERE conversation_id=? ORDER BY id", (conv["id"],))]

    @app.get("/api/post/{post_id}/chat")
    def post_chat(post_id: int):
        post, refusal = find(post_id)
        if refusal is not None:
            return refusal
        conv = conversation(post_id)
        earlier = db.all("SELECT c.id, c.created_at, c.cleared_at, (SELECT COUNT(*) FROM messages m WHERE m.conversation_id=c.id) "
                         "AS n FROM conversations c WHERE c.mode='post' AND c.post_id=? AND c.cleared_at IS NOT NULL "
                         "ORDER BY c.id DESC LIMIT 20", (post_id,))
        return {"conversation": conv["id"] if conv else None, "messages": thread(conv, post["picture_id"]),
                "earlier": [{"id": e["id"], "count": e["n"], "when": s.when(e["cleared_at"])} for e in earlier if e["n"]],
                "busy": s.post_busy(post_id)}

    @app.post("/api/post/{post_id}/ask")
    def post_ask(post_id: int, data: dict = Body(default={})):
        _row, refusal = find(post_id)
        if refusal is not None:
            return refusal
        text = str(data.get("text") or "").strip()
        if not text:
            return fail("Say what you want first.")
        if len(text) > 20000:
            return fail("That message is too long for one request.")
        if s.post_busy(post_id):
            return fail(CHAT_BUSY, 409)
        try:
            files = attached.save_all(db, f"post-{post_id}", data.get("files"))
        except attachments.Refused as exc:
            return fail(str(exc))
        # An attached picture can also go out with the post: it joins the post's pictures (Use as the picture).
        pictures = [images.save(db, post_id, attached.folder(db, f"post-{post_id}").joinpath(r["path"]).read_bytes(),
                                mime=r["mime"], source="attached", prompt=r["name"])
                    for r in files if r["mime"] in images.EXTENSION]
        conv = conversation(post_id, create=True)
        meta = {k: v for k, v in (("files", files), ("images", pictures)) if v}
        message = add_message(db, conv["id"], "user", text, meta=meta or None)
        job = jobs.submit("post_chat", {"post_id": post_id, "conversation_id": conv["id"], "message_id": message,
                                        "text": text, "files": [r["path"] for r in files]})
        db.run("UPDATE messages SET job_id=? WHERE id=?", (job, message))
        return {"job": job, "message": message}

    @app.get("/api/post/{post_id}/file/{name}")
    def post_file(post_id: int, name: str):
        _row, refusal = find(post_id)
        if refusal is not None:
            return refusal
        found = attached.served(db, f"post-{post_id}", name)
        if found is None:
            return fail("That file is not here.", 404)
        path, headers = found
        return FileResponse(path, headers=headers)

    @app.post("/api/post/{post_id}/chat/clear")
    def post_chat_clear(post_id: int):
        _row, refusal = find(post_id)
        if refusal is not None:
            return refusal
        if s.post_busy(post_id):
            return fail(CHAT_BUSY, 409)
        conv = conversation(post_id)
        if conv is not None:
            db.run("UPDATE conversations SET cleared_at=? WHERE id=?", (utcnow(), conv["id"]))
        return {"ok": True}

    @app.post("/api/post/{post_id}/chat/back")
    def post_chat_back(post_id: int, data: dict = Body(default={})):
        _row, refusal = find(post_id)
        if refusal is not None:
            return refusal
        if s.post_busy(post_id):
            return fail(CHAT_BUSY, 409)
        wanted = db.one("SELECT * FROM conversations WHERE id=? AND mode='post' AND post_id=?",
                        (int(data.get("conversation") or 0), post_id))
        if wanted is None:
            return fail("That conversation is not this post's.", 404)
        with db.transaction() as con:
            con.execute("UPDATE conversations SET cleared_at=? WHERE mode='post' AND post_id=? AND cleared_at IS NULL",
                        (utcnow(), post_id))
            con.execute("UPDATE conversations SET cleared_at=NULL WHERE id=?", (wanted["id"],))
        return {"ok": True}
