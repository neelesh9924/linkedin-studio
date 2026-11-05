"""The API of one post: the editor's actions, its chat, its versions and its picture, sending it to Publora or putting
it in the posting queue (posting.py), and moving it to the Trash (api_trash.py has the Trash itself).

Every endpoint of a post asks `find` for it: one that is gone, or in the Trash, is refused in the same words. A post
in the Trash keeps everything (its state, versions, chat and pictures) and nothing here can change it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Body, FastAPI
from fastapi.responses import FileResponse, JSONResponse

from . import attached, attachments, bold, carousel, codex, hot, images, posting, rank, render, style, versions
from .db import dumps, loads, utcnow
from .flows import add_message
from .main import ACTIVE, PROBLEM, Studio
from .publishing import (DASHBOARD_URL, FIRST_COMMENT_MAX, MIN_LEAD, NO_REASON, ScheduleError, placeholder_slots,
                         post_now_with_pictures, retry_with_pictures, schedule_with_pictures)
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
    # A cancelled picture post's postGroupId went with Cancel on Publora; a published one's went out to LinkedIn.
    if status not in ("cancelled", "published") and (loads(row["media"], {}) or {}).get("postGroupId"):
        return ("Publora still holds an unsent draft of this post. Move it back to draft first: that takes the draft off "
                "Publora.")
    if working:
        return "Claude is working on this post. It can go to the Trash once Claude is done, or once you stop it."
    return ""


def due_now(row, now: datetime) -> bool:
    """A scheduled post whose time has passed: Publora should have sent it by now."""
    at = render.parse_utc(row["scheduled_at"] or "") if row["status"] == "scheduled" else None
    return at is not None and at <= now


def news_public(row) -> dict | None:
    """The Hot topics item a post was drafted from, for its card beside it: only a web address is ever a link."""
    news = loads(row["news"], None) if "news" in row.keys() else None
    if not isinstance(news, dict) or not str(news.get("url") or "").startswith(("https://", "http://")):
        return None
    return {**{k: news.get(k) for k in ("title", "url", "source", "pillar", "published", "points", "discussion")},
            "area": hot.area_of(news)}


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
        """Schedule…'s recommended times: the first free posting times (Settings › Posting times) after the queue's,
        within the window. None when every posting day in it has a post."""
        tomorrow = (now_local + timedelta(days=1)).date()
        picks = []
        for slot in s.queue.next_free(4):
            local = slot.astimezone(cfg.tz)
            text = render.local_time(slot.isoformat(), cfg.tz)
            day = "Today" if local.date() == now_local.date() else "Tomorrow" if local.date() == tomorrow else None
            picks.append({"value": local.strftime("%Y-%m-%dT%H:%M"), "label": f"{day}, {text.split(', ')[1]}" if day else text})
        return picks

    def revision_public(job, post) -> dict:
        data = loads(job["result"], {}) or {}
        params = loads(job["params"], {}) or {}
        how = params.get("how")
        label, promise = REVISION_LABELS.get(how, ("Revision", ""))
        chosen = style.valid(params.get("style")) if how == "style" else None
        if chosen:
            promise = f"{style.summary(chosen)}."   # what this Restyle was asked for
        text = bold.from_marks(str(data.get("text") or ""))
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
        chosen = images.chosen_ids(row)
        going = images.chosen(db, row)
        now = datetime.now(timezone.utc)
        now_local = now.astimezone(cfg.tz)
        status = row["status"]
        trash_why = trash_refusal(row, s.post_working(pid))
        due = due_now(row, now)
        summary = s.post_summary(row)
        return {
            **summary,
            "text": row["text"], "first_comment": row["first_comment"] or "", "formula": row["formula"] or "",
            "notes": [str(n) for n in loads(row["notes"], []) or [] if n],
            "audit": audit, "audit_job": s.job_public(audit_job) if audit_job else None,
            "revise_job": s.job_public(revise_job) if revise_job else None,
            "revision": revision_public(revision, row) if revision is not None and status == "draft" else None,
            "slots": len(placeholder_slots(row["text"])), "chars": len(row["text"]),
            "style": {"value": style.of_post(db, row), "own": style.parse(row["style"]) is not None},
            "editable": status == "draft" and not busy,
            "deletable": not trash_why, "trash_why": trash_why,      # Move to Trash… is offered, or why it is not
            "error": row["error"] or "", "saved": s.clock(row["updated_at"]),
            # What goes out with it, in order (up to images.MAX_PICTURES pictures, or one carousel), and all it keeps
            "media": [images.public(p, chosen) for p in going], "max_pictures": images.MAX_PICTURES,
            "pictures": [images.public(p, chosen) for p in pictures], "carousels": carousel.available(),
            "rank": rank.public(row),
            "schedule": {"min": (now_local + MIN_LEAD + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M"),
                         "max": (now_local + pub.max_ahead).strftime("%Y-%m-%dT%H:%M"),
                         "quick": quick_times(now_local)} if status == "approved" else None,
            "publora": pub.status(), "used": pub.quota_used(now), "limit": cfg.monthly_post_limit,
            "month": now_local.strftime("%B"), "dashboard": DASHBOARD_URL, "first_comment_max": FIRST_COMMENT_MAX,
            "can_retry": status == "failed" and not row["publora_post_id"] and bool(row["publora_payload"]),
            "can_back": status in ("approved", "failed") and not row["publora_post_id"],
            "versions": db.one("SELECT COUNT(*) AS n FROM versions WHERE post_id=?", (pid,))["n"],
            "news": news_public(row),
            # The posting queue: Approve and queue on a draft, Add to queue on an approved post, Take out on a queued one
            "can_queue": status in ("draft", "approved") and not summary["queued"],
            "posting": posting.words(s.queue.times()), "window": pub.max_ahead.days, "at_once": cfg.publora_at_once,
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

    # ---- search ---------------------------------------------------------------------
    @app.get("/api/search")
    def search_words():
        """What the search looks in (static/js/search.js matches it as the owner types, in the sidebar and Ctrl+K): each
        post out of the Trash, its words by where they are, in the order a match is shown from: its text, its first
        comment, the words on the carousel or card on it, the news it was drafted from, its title. `rev`: the state it
        was read at, so the page asks again only after a change."""
        specs = {r["id"]: loads(r["spec"], {}) for r in db.all("SELECT id, spec FROM images WHERE spec IS NOT NULL")}
        found = []
        for row in db.all("SELECT * FROM posts WHERE trashed_at IS NULL ORDER BY id"):
            news = loads(row["news"], None)
            on = [specs[i] for i in images.chosen_ids(row) if specs.get(i)]
            pieces = [("text", row["text"]), ("comment", row["first_comment"] or ""),
                      *((spec.get("format") or "carousel", carousel.words_of(spec)) for spec in on),
                      ("news", " · ".join(str(news.get(k) or "") for k in ("title", "source")) if isinstance(news, dict) else ""),
                      ("title", row["title"] or "")]
            found.append({"id": row["id"], "words": [[where, words] for where, words in pieces if words.strip()]})
        return {"rev": db.rev, "posts": found}

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
        try:   # Restyle: the sliders it was given are this post's style from now on; any other revision keeps its style
            chosen = style.clean(data.get("style")) if how == "style" else None
        except style.Refused as exc:
            return fail(str(exc))
        post = save_fields(post_id, data.get("title"), data.get("text"), data.get("first_comment"))
        if post is None or how not in REVISIONS or not post["text"].strip():
            return fail("Only a draft with some text can be revised.")
        if any(j["status"] in ACTIVE for j in jobs_for(post_id, ("revise",))):
            return fail("A revision is already being written.")
        for old in jobs_for(post_id, ("revise",)):
            jobs.dismiss(old["id"])
        if chosen:
            db.run("UPDATE posts SET style=? WHERE id=?", (dumps(chosen), post_id))
        return {"job": jobs.submit("revise", {"post_id": post_id, "how": how, "text": post["text"],
                                              "style": chosen or style.of_post(db, post)})}

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
        text = bold.from_marks(str(result.get("text") or "").strip())
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

    def pictures_of(row) -> list[dict]:
        return posting.pictures_of(db, row)

    def first_comment(row, data) -> tuple[str, JSONResponse | None]:
        """The first comment going out (the page's, else the post's) and its refusal, or None. What Schedule… only
        warns about is refused where no final dialog shows it (the queue) and where it is out at once (Post now): a
        blank left in it, or more than LinkedIn takes."""
        comment = str((data["first_comment"] if isinstance(data.get("first_comment"), str) else row["first_comment"]) or "").strip()
        fix = "first" if row["status"] == "draft" else "after Back to draft"
        if placeholder_slots(comment):
            return comment, fail(f"The first comment still has a blank, such as {placeholder_slots(comment)[0]}. "
                                 f"Fill it in or cut it {fix}.", 409)
        if len(comment) > FIRST_COMMENT_MAX:
            return comment, fail(f"The first comment is {len(comment):,} characters; LinkedIn takes "
                                 f"{FIRST_COMMENT_MAX:,}. Cut it {fix}.", 409)
        return comment, None

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
        return transition(post_id, lambda: pub.back_to_draft(post_id))   # a queued post leaves the queue with it

    # ---- the posting queue (posting.py) ------------------------------------------------
    @app.post("/api/post/{post_id}/queue")
    def post_queue(post_id: int, data: dict = Body(default={})):
        """Approve and queue (a draft: saved and approved as Approve does it, then queued) or Add to queue (an approved
        post): at the end of the line, where it takes the next free posting time. A post whose time is inside the
        window goes to Publora at once; the answer says when it goes out, in words."""
        row, refusal = find(post_id)
        if refusal is not None:
            return refusal
        _comment, refusal = first_comment(row, data)   # no final dialog shows the first comment here
        if refusal is not None:
            return refusal
        if row["status"] == "draft":
            done = post_approve(post_id, data)
            if not isinstance(done, dict):
                return done                    # refused as Approve is: a blank left, too long, Claude at work on it
        elif row["status"] != "approved" or row["queue_pos"] is not None:
            return fail("It is in the queue already." if row["queue_pos"] is not None
                        else "Only a draft or an approved post can join the queue.", 409)
        if not s.queue.add(post_id):
            return fail("The post changed just now, so it did not join the queue. Look at it again.", 409)
        s.queue.send_due()
        row = get_post(post_id)
        summary = s.post_summary(row)
        if row["status"] in ("scheduling", "scheduled"):
            return {"ok": True, "status": row["status"], "said": f"Queued, and handed to Publora: it goes out {summary['when']}."}
        if row["status"] == "failed":
            return {"ok": False, "status": "failed", "error": row["error"] or "Publora did not take it."}
        if not summary["when"]:
            return {"ok": True, "status": "approved",
                    "said": "Queued, but no posting time is free within a year. Settings › Posting times adds days."}
        room = f" and your Publora plan has room (it holds {cfg.publora_at_once} at a time)" if cfg.publora_at_once else ""
        later = (f" It goes to Publora by itself once its time is {pub.max_ahead.days} days away{room}, while the studio is "
                 "open." if not row["error"] else f" {row['error']}")
        return {"ok": True, "status": "approved", "said": f"Queued: it goes out {summary['when']}.{later}"}

    @app.post("/api/post/{post_id}/unqueue")
    def post_unqueue(post_id: int):
        """Take out of the queue: it stays approved, with no time."""
        _row, refusal = find(post_id)
        if refusal is not None:
            return refusal
        if not s.queue.take_out(post_id):
            return fail("This post is not waiting in the queue.", 409)
        return {"ok": True}

    @app.post("/api/queue/move")
    def queue_move(data: dict = Body(default={})):
        """A queued post one place up or down the line, or to its front; the others keep their order."""
        how = str(data.get("how") or "")
        if how not in ("up", "down", "first"):
            return fail("Move it up, down or to the front.")
        try:
            post_id = int(data.get("id") or 0)
        except (TypeError, ValueError):
            return fail("Say which post.")
        _row, refusal = find(post_id)
        if refusal is not None:
            return refusal
        if not s.queue.move(post_id, how):
            return fail("It cannot move that way: it is not waiting in the queue, or it is at that end already.", 409)
        s.queue.send_due()                     # one moved to the front may now be inside the window
        return {"ok": True}

    # A post's pictures or carousel go out with it through Publora's own upload (publishing.py); without any it is the
    # single keyed request as before. Either way exactly once, and Retry carries on from where it stopped.
    @app.post("/api/post/{post_id}/schedule")
    def post_schedule(post_id: int, data: dict = Body(default={})):
        row = get_post(post_id)
        when, comment = str(data.get("when") or ""), data.get("first_comment")
        return transition(post_id, lambda: schedule_with_pictures(pub, post_id, when, comment, pictures_of(row)))

    @app.post("/api/post/{post_id}/now")
    def post_now(post_id: int, data: dict = Body(default={})):
        """Post now…: a draft (approved as Approve does it), an approved post or a queued one goes to Publora at once,
        for the soonest time (Publisher.post_now), with its pictures or carousel and first comment as Schedule… sends
        them. It is public at once, so the page asks first and sends `confirmed`. The plan's refusals (its monthly
        limit, the posts Publora holds at a time) and a picture gone are asked before a draft is approved, so a draft
        refused stays a draft. A queued post leaves the line as it goes, and the posts behind it move up."""
        row, refusal = find(post_id)
        if refusal is not None:
            return refusal
        if row["status"] not in ("draft", "approved"):
            return fail("Only a draft or an approved post can be posted now.", 409)
        if data.get("confirmed") is not True:
            return fail("Post now puts it on LinkedIn at once: confirm it first.")
        comment, refusal = first_comment(row, data)   # out at once: a blank would be there for everyone to see
        if refusal is not None:
            return refusal
        try:
            pictures = pictures_of(row)
            pub.room(pub.soonest(), post_now=True)
        except ScheduleError as exc:
            return fail(str(exc), 409)
        if row["status"] == "draft":
            done = post_approve(post_id, data)
            if not isinstance(done, dict):
                return done                    # refused as Approve is: a blank left, too long, Claude at work on it
        done = transition(post_id, lambda: post_now_with_pictures(pub, post_id, comment, pictures))
        if not isinstance(done, dict) or not done["ok"]:
            return done
        s.queue.send_due()                     # its day is taken now, and a queued one's place is free
        sent = get_post(post_id)
        return {**done, "said": f"Handed to Publora: it goes out at {s.clock(sent['scheduled_at'])}, about "
                                f"{int(MIN_LEAD.total_seconds() // 60)} minutes from now."}

    @app.post("/api/post/{post_id}/retry")
    def post_retry(post_id: int):
        row = get_post(post_id)
        return transition(post_id, lambda: retry_with_pictures(pub, post_id, pictures_of(row)))

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
        it forever. Never a post waiting on Publora (scheduling, scheduled, or a picture post's Publora draft), and
        never while Claude works on it or waits to (its chat, an audit or a revision). A published post stays on
        LinkedIn: only the studio's copy goes."""
        row, refusal = find(post_id)
        if refusal is not None:
            return refusal
        why = trash_refusal(row, s.post_working(post_id))
        if why:
            return fail(why, 409)
        # Checked again in the one statement that moves it, so nothing that started meanwhile is overtaken.
        moved = db.run("UPDATE posts SET trashed_at=?, queue_pos=NULL WHERE id=? AND trashed_at IS NULL "
                       "AND status NOT IN ('scheduling','scheduled') "
                       "AND (status IN ('cancelled','published') OR media IS NULL OR NOT json_valid(media) "
                       "OR json_extract(media, '$.postGroupId') IS NULL) "
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
        """New draft from this: the text, first comment, formula, notes and pictures (their files shared, not copied),
        with a first version that says where it came from. Any state but the Trash."""
        row, refusal = find(post_id)
        if refusal is not None:
            return refusal
        now = utcnow()
        with db.transaction() as con:
            new = con.execute("INSERT INTO posts (created_at, updated_at, title, text, first_comment, formula, notes, status) "
                              "VALUES (?,?,?,?,?,?,?, 'draft')",
                              (now, now, row["title"], row["text"], row["first_comment"], row["formula"], row["notes"])).lastrowid
            copies = []
            for image in images.chosen(db, row):
                copies.append(con.execute(
                    "INSERT INTO images (post_id, file, source, prompt, shape, width, height, mime, sha256, job_id, spec, "
                    "pages, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (new, image["file"], image["source"], image["prompt"], image["shape"], image["width"], image["height"],
                     image["mime"], image["sha256"], image["job_id"], image["spec"], image["pages"], now)).lastrowid)
            if copies:
                con.execute("UPDATE posts SET picture_ids=? WHERE id=?", (dumps(copies), new))
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

    # ---- its rank ---------------------------------------------------------------------------
    @app.post("/api/post/{post_id}/rank")
    def post_rank(post_id: int, data: dict = Body(default={})):
        """The owner's own number for the post (1-10), or null to take the rank off; the reason Claude gave stays beside
        it, said as Claude's. With `by: "claude"`, Claude's rank given from outside a chat (as an audit of the drafts
        does), with its own `why` and `fix`."""
        row, refusal = find(post_id)
        if refusal is not None:
            return refusal
        if data.get("rank") is None:
            db.run("UPDATE posts SET rank=NULL, rank_note=NULL, updated_at=? WHERE id=?", (utcnow(), post_id))
            return {"ok": True, "rank": None}
        try:
            given = rank.number(data.get("rank"))
        except rank.Refused as exc:
            return fail(str(exc))
        by = data.get("by", "you")
        if by not in ("you", "claude"):
            return fail("A rank is yours or Claude's.")
        kept = loads(row["rank_note"], {}) or {}
        why, fix = (data.get("why"), data.get("fix")) if by == "claude" else (kept.get("why", ""), kept.get("fix", ""))
        db.run("UPDATE posts SET rank=?, rank_note=?, updated_at=? WHERE id=?",
               (given, rank.note(given, why or "", fix or "", by=by), utcnow(), post_id))
        return {"ok": True, "rank": rank.public(get_post(post_id))}

    # ---- the pictures and carousels -----------------------------------------------------
    @app.post("/api/post/{post_id}/pictures")
    def post_pictures(post_id: int, data: dict = Body(default={})):
        """What goes out with the post, in order: `ids` of its own pictures (up to images.MAX_PICTURES), or one carousel
        alone; an empty list sends it with none."""
        post, refusal = find(post_id)
        if refusal is not None:
            return refusal
        if post["status"] != "draft":
            return fail("The pictures go with the approved text: move the post back to draft to change them.", 409)
        ids = data.get("ids")
        if not isinstance(ids, list) or any(isinstance(i, bool) or not isinstance(i, int) for i in ids):
            return fail("Send the pictures as a list of their ids.")
        rows = {r["id"]: r for r in images.for_post(db, post_id)}
        if any(i not in rows for i in ids):
            return fail("That picture is not this post's.", 404)
        why = images.refusal([rows[i] for i in ids])
        if why:
            return fail(why)
        db.run("UPDATE posts SET picture_ids=?, updated_at=? WHERE id=? AND trashed_at IS NULL",
               (dumps(ids) if ids else None, utcnow(), post_id))
        return {"ok": True, "ids": ids}

    @app.post("/api/post/{post_id}/carousel")
    def post_carousel(post_id: int, data: dict = Body(default={})):
        """Draws a carousel or card from `spec` (carousel.py) and keeps it with the post's pictures; `use` puts it on the
        post (alone: it takes the place of any pictures). `again`: the id of one of its carousels or cards to draw afresh
        in its place (Redraw), with You in the preview as it is now: on the post still if it was, and no copy left beside
        it; with `look`, in another look as it is drawn afresh: "next" (Try another look: carousel.next_look) or a look's
        name, with `tint`. Its art is never drawn again."""
        post, refusal = find(post_id)
        if refusal is not None:
            return refusal
        if post["status"] != "draft":
            return fail("Only a draft's pictures can change: move it back to draft first.", 409)
        spec, use, into = data.get("spec"), bool(data.get("use")), None
        if data.get("again") is not None:
            old = db.one("SELECT * FROM images WHERE id=? AND post_id=?", (int(data.get("again") or 0), post_id))
            if old is None or not loads(old["spec"], None):
                return fail("That carousel is not this post's.", 404)
            spec, into = loads(old["spec"], None), old["id"]
            try:
                spec = carousel.check(spec)
            except carousel.CarouselError as exc:
                return fail(str(exc))
            look = data.get("look")
            if look == "next":
                spec = carousel.next_look(spec)
            elif look is not None:
                spec = {**spec, "look": look, "tint": data.get("tint", 0)}
        said: list[str] = []
        try:
            spec = carousel.check(spec)
            if carousel.art_subjects(spec):   # a new spec's art: ChatGPT draws it now, each piece one of its pictures
                if codex.chatgpt_ready():
                    spec, said = carousel.draw_art(spec, images.folder(db), lambda subject: codex.make_picture(
                        carousel.art_prompt(subject), "square")[0])
                else:
                    spec, said = carousel.drop_art(spec), ["Its art was left out: ChatGPT isn't set up for pictures."]
            made = carousel.make(db, post_id, spec, into=into)
        except carousel.CarouselError as exc:
            return fail(str(exc))
        if use:
            db.run("UPDATE posts SET picture_ids=?, updated_at=? WHERE id=? AND trashed_at IS NULL",
                   (dumps([made]), utcnow(), post_id))
        return {"ok": True, "id": made, "image": images.public(images_row(made), images.chosen_ids(get_post(post_id))),
                "said": said}

    @app.post("/api/post/{post_id}/picture/{image_id}/delete")
    def post_picture_delete(post_id: int, image_id: int, data: dict = Body(default={})):
        """Deletes a picture or carousel kept with the post but not on it, and its files once nothing else keeps them.
        Needs `confirmed`: it can't be undone."""
        post, refusal = find(post_id)
        if refusal is not None:
            return refusal
        row = db.one("SELECT * FROM images WHERE id=? AND post_id=?", (image_id, post_id))
        if row is None:
            return fail("That picture is not this post's.", 404)
        if image_id in images.chosen_ids(post):
            return fail("It's on the post: remove it from the post first.", 409)
        if data.get("confirmed") is not True:
            return fail("Deleting a picture can't be undone: confirm it first.")
        db.run("DELETE FROM images WHERE id=? AND post_id=?", (image_id, post_id))
        images.unlink_unused(db, [row])
        return {"ok": True}

    def images_row(image_id: int):
        return db.one("SELECT * FROM images WHERE id=?", (image_id,))

    # ---- the post's chat --------------------------------------------------------------
    def conversation(post_id: int, create: bool = False):
        conv = db.one("SELECT * FROM conversations WHERE mode='post' AND post_id=? AND cleared_at IS NULL "
                      "ORDER BY id DESC LIMIT 1", (post_id,))
        if conv is None and create:
            conv_id = db.run("INSERT INTO conversations (mode, post_id, created_at) VALUES ('post', ?, ?)",
                             (post_id, utcnow()))
            conv = db.one("SELECT * FROM conversations WHERE id=?", (conv_id,))
        return conv

    def message_public(m, chosen: list[int], post_id: int) -> dict:
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

    def thread(conv, chosen: list[int]) -> list[dict]:
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
        return {"conversation": conv["id"] if conv else None, "messages": thread(conv, images.chosen_ids(post)),
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
        # An attached picture can also go out with the post: it joins the post's pictures (Add to the post).
        pictures = [images.save(db, post_id, attached.folder(db, f"post-{post_id}").joinpath(r["path"]).read_bytes(),
                                mime=r["mime"], source="attached", prompt=r["name"])
                    for r in files if r["mime"] in images.PICTURE]
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
