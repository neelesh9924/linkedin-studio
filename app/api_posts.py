"""The API of one post: the editor's actions, its chat, its versions and its picture, and sending it to Publora."""
from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Body, FastAPI
from fastapi.responses import FileResponse, JSONResponse

from . import attached, attachments, images, render, versions
from .db import dumps, loads, utcnow
from .flows import add_message, short_title
from .main import ACTIVE, PROBLEM, Studio
from .publishing import (DASHBOARD_URL, FIRST_COMMENT_MAX, MAX_AHEAD, MIN_LEAD, ScheduleError, placeholder_slots,
                         retry_with_picture, schedule_with_picture)
from .skills import REVISION_LABELS, REVISIONS

CHAT_BUSY = "Claude is still working on this post. What you wrote stays in the box: send it once Claude is done."
TEXT_BUSY = "Claude is working on this post: its text waits until Claude is done."


def fail(text: str, status: int = 422) -> JSONResponse:
    return JSONResponse({"error": text}, status_code=status)


def register(app: FastAPI, s: Studio) -> None:
    db, jobs, pub, cfg = s.db, s.jobs, s.pub, s.cfg

    def get_post(post_id: int):
        return db.one("SELECT * FROM posts WHERE id=?", (post_id,))

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
        return {
            **s.post_summary(row),
            "text": row["text"], "first_comment": row["first_comment"] or "", "formula": row["formula"] or "",
            "notes": [str(n) for n in loads(row["notes"], []) or [] if n],
            "audit": audit, "audit_job": s.job_public(audit_job) if audit_job else None,
            "revise_job": s.job_public(revise_job) if revise_job else None,
            "revision": revision_public(revision, row) if revision is not None and status == "draft" else None,
            "slots": len(placeholder_slots(row["text"])), "chars": len(row["text"]),
            "editable": status == "draft" and not busy,
            "deletable": status not in ("scheduling", "scheduled", "published") and not busy
                         and not (loads(row["media"], {}) or {}).get("postGroupId"),
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
        }

    def save_fields(post_id: int, title: Any, text: Any, first_comment: Any):
        """Store the editor's fields if the post is still a draft Claude is not working on. The fresh row, or None."""
        post = db.one("SELECT * FROM posts WHERE id=? AND status='draft'", (post_id,))
        if post is None or s.post_busy(post_id):
            return None
        if not isinstance(text, str):
            return post
        new_text = text.replace("\r\n", "\n").strip()
        new_fc = (first_comment if isinstance(first_comment, str) else post["first_comment"] or "").replace("\r\n", "\n").strip() or None
        new_title = (title if isinstance(title, str) else "").strip()[:120] or post["title"]
        if (new_text, new_fc, new_title) != (post["text"], post["first_comment"], post["title"]):
            db.run("UPDATE posts SET text=?, first_comment=?, title=?, updated_at=? WHERE id=? AND status='draft'",
                   (new_text, new_fc, new_title, utcnow(), post_id))
            post = get_post(post_id)
        return post

    def locked(post_id: int) -> JSONResponse:
        if get_post(post_id) is None:
            return fail("That post no longer exists.", 404)
        if s.post_busy(post_id):
            return fail(TEXT_BUSY, 409)
        return fail("Only a draft can be edited. Move it back to draft first.", 409)

    # ---- the list and a new post ----------------------------------------------------
    @app.post("/api/posts/new")
    def post_new(data: dict = Body(default={})):
        now = utcnow()
        title = str(data.get("title") or "").strip()[:120] or "Untitled draft"
        return {"id": db.run("INSERT INTO posts (created_at, updated_at, title, text, status) VALUES (?,?,?,?, 'draft')",
                             (now, now, title, ""))}

    @app.post("/api/posts/refresh")
    def refresh_due():
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
        return {"checked": len(due), "said": "Nothing was due yet." if not due else
                f"Checked {len(due)} post{'s' if len(due) != 1 else ''}."}

    @app.get("/api/post/{post_id}")
    def post_get(post_id: int):
        row = get_post(post_id)
        if row is None:
            return fail("That post no longer exists.", 404)
        return post_full(row)

    # ---- the editor ----------------------------------------------------------------
    @app.post("/api/post/{post_id}/save")
    def post_save(post_id: int, data: dict = Body(default={})):
        post = save_fields(post_id, data.get("title"), data.get("text"), data.get("first_comment"))
        if post is None:
            return locked(post_id)
        return {"chars": len(post["text"]), "slots": len(placeholder_slots(post["text"])), "saved": s.clock(post["updated_at"])}

    @app.post("/api/post/{post_id}/audit")
    def post_audit(post_id: int, data: dict = Body(default={})):
        post = save_fields(post_id, data.get("title"), data.get("text"), data.get("first_comment")) or get_post(post_id)
        if post is None or not post["text"].strip():
            return fail("Write something first.")
        if any(j["status"] in ACTIVE for j in jobs_for(post_id, ("audit",))):
            return fail("An audit is already running.")
        for old in jobs_for(post_id, ("audit",)):
            jobs.dismiss(old["id"])
        return {"job": jobs.submit("audit", {"post_id": post_id, "text": post["text"]})}

    @app.post("/api/post/{post_id}/revise")
    def post_revise(post_id: int, data: dict = Body(default={})):
        how = data.get("how")
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
        job = db.one("SELECT * FROM jobs WHERE id=? AND kind='revise'", (int(data.get("job") or 0),))
        post = db.one("SELECT * FROM posts WHERE id=? AND status='draft'", (post_id,))
        if post is None or job is None or (loads(job["params"], {}) or {}).get("post_id") != post_id:
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
        db.run("UPDATE posts SET text=?, first_comment=?, audit=NULL, updated_at=? WHERE id=?",
               (text, first, utcnow(), post_id))
        versions.record(db, post_id, text, first, "claude", REVISION_LABELS.get(how, ("Revision",))[0])
        return {"used": True}

    def transition(post_id: int, fn) -> Any:
        if get_post(post_id) is None:
            return fail("That post no longer exists.", 404)
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
        if s.post_busy(post_id):
            return fail(TEXT_BUSY, 409)
        save_fields(post_id, data.get("title"), data.get("text"), data.get("first_comment"))
        return transition(post_id, lambda: pub.approve(post_id))

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
        if get_post(post_id) is None:
            return fail("That post no longer exists.", 404)
        try:
            return {"status": pub.refresh(post_id)}
        except Exception as exc:
            return fail(f"Could not read the status from Publora: {exc}", 502)

    @app.post("/api/post/{post_id}/delete")
    def post_delete(post_id: int):
        post = get_post(post_id)
        if post is None:
            return {"ok": True}
        if post["status"] in ("scheduling", "scheduled", "published"):
            return fail("A scheduled or published post cannot be deleted here. Cancel it on Publora first.", 409)
        if (loads(post["media"], {}) or {}).get("postGroupId"):
            return fail("Publora still holds an unsent draft of this post. Move it back to draft first: that takes the "
                        "draft off Publora.", 409)
        if s.post_busy(post_id):
            return fail(TEXT_BUSY, 409)
        files = [r["file"] for r in images.for_post(db, post_id)]
        with db.transaction() as con:
            con.execute("UPDATE plan_items SET post_id=NULL WHERE post_id=?", (post_id,))
            con.execute("DELETE FROM versions WHERE post_id=?", (post_id,))
            con.execute("DELETE FROM images WHERE post_id=?", (post_id,))
            for conv in con.execute("SELECT id FROM conversations WHERE mode='post' AND post_id=?", (post_id,)).fetchall():
                con.execute("DELETE FROM messages WHERE conversation_id=?", (conv["id"],))
            con.execute("DELETE FROM conversations WHERE mode='post' AND post_id=?", (post_id,))
            con.execute("DELETE FROM posts WHERE id=?", (post_id,))
        for name in files:   # a picture's file goes once no other post's picture is the same file
            if db.one("SELECT 1 FROM images WHERE file=?", (name,)) is None:
                path = images.path_of(db, {"file": name})
                if path:
                    path.unlink(missing_ok=True)
        shutil.rmtree(attached.folder(db, f"post-{post_id}"), ignore_errors=True)   # what was attached in its chat
        return {"ok": True}

    # ---- versions -------------------------------------------------------------------
    @app.get("/api/post/{post_id}/versions")
    def post_versions(post_id: int):
        post = get_post(post_id)
        if post is None:
            return fail("That post no longer exists.", 404)
        rows = versions.listing(db, post_id)
        return {"versions": [{"id": v["id"], "author": v["author"], "note": v["note"] or "", "when": s.when(v["created_at"]),
                              "chars": len(v["text"]), "first": (v["text"].strip().splitlines() or [""])[0][:140],
                              "current": (v["text"], v["first_comment"]) == (post["text"], post["first_comment"])}
                             for v in rows],
                "editable": post["status"] == "draft" and not s.post_busy(post_id)}

    @app.post("/api/post/{post_id}/versions/back")
    def post_go_back(post_id: int, data: dict = Body(default={})):
        if s.post_busy(post_id):
            return fail(TEXT_BUSY, 409)
        try:
            changed = versions.go_back(db, post_id, int(data.get("version") or 0))
        except versions.VersionError as exc:
            return fail(str(exc), 409)
        return {"changed": changed}

    # ---- the picture ------------------------------------------------------------------
    @app.post("/api/post/{post_id}/picture")
    def post_picture(post_id: int, data: dict = Body(default={})):
        post = get_post(post_id)
        if post is None:
            return fail("That post no longer exists.", 404)
        if post["status"] != "draft":
            return fail("The picture goes with the approved text: move the post back to draft to change it.", 409)
        chosen = data.get("image")
        if chosen is not None:
            image = db.one("SELECT id FROM images WHERE id=? AND post_id=?", (int(chosen or 0), post_id))
            if image is None:
                return fail("That picture is not this post's.", 404)
            chosen = image["id"]
        db.run("UPDATE posts SET picture_id=?, updated_at=? WHERE id=?", (chosen, utcnow(), post_id))
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
        post = get_post(post_id)
        if post is None:
            return fail("That post no longer exists.", 404)
        conv = conversation(post_id)
        earlier = db.all("SELECT c.id, c.created_at, c.cleared_at, (SELECT COUNT(*) FROM messages m WHERE m.conversation_id=c.id) "
                         "AS n FROM conversations c WHERE c.mode='post' AND c.post_id=? AND c.cleared_at IS NOT NULL "
                         "ORDER BY c.id DESC LIMIT 20", (post_id,))
        return {"conversation": conv["id"] if conv else None, "messages": thread(conv, post["picture_id"]),
                "earlier": [{"id": e["id"], "count": e["n"], "when": s.when(e["cleared_at"])} for e in earlier if e["n"]],
                "busy": s.post_busy(post_id)}

    @app.post("/api/post/{post_id}/ask")
    def post_ask(post_id: int, data: dict = Body(default={})):
        if get_post(post_id) is None:
            return fail("That post no longer exists.", 404)
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
        found = attached.served(db, f"post-{post_id}", name)
        if found is None:
            return fail("That file is not here.", 404)
        path, headers = found
        return FileResponse(path, headers=headers)

    @app.post("/api/post/{post_id}/chat/clear")
    def post_chat_clear(post_id: int):
        if s.post_busy(post_id):
            return fail(CHAT_BUSY, 409)
        conv = conversation(post_id)
        if conv is not None:
            db.run("UPDATE conversations SET cleared_at=? WHERE id=?", (utcnow(), conv["id"]))
        return {"ok": True}

    @app.post("/api/post/{post_id}/chat/back")
    def post_chat_back(post_id: int, data: dict = Body(default={})):
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

    # ---- a repurposed post becomes a draft ---------------------------------------------
    @app.post("/api/tools/repurpose/{job_id}/draft")
    def tool_to_draft(job_id: int):
        row = db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
        data = loads(row["result"], {}) if row and row["kind"] == "repurpose" and row["status"] == "done" else {}
        text = str((data or {}).get("post") or "").strip()
        if not text:
            return fail("There is no post to save.")
        now = utcnow()
        first = (data or {}).get("first_comment") or None
        post_id = db.run("INSERT INTO posts (created_at, updated_at, title, text, first_comment, formula, notes, status) "
                         "VALUES (?,?,?,?,?,?,?, 'draft')",
                         (now, now, short_title(text.splitlines()[0]), text, first, (data or {}).get("formula"), dumps([])))
        versions.record(db, post_id, text, first, "claude", "Repurposed")
        return {"post": post_id}
