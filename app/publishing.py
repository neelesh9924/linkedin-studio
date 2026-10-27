"""Publishing through linkedin-skills\\lib\\publora_client.py, with exactly-once scheduling.

State machine: draft -> approved -> scheduling -> scheduled -> published | failed | cancelled.
The approved -> scheduling step is one BEGIN IMMEDIATE transaction, so a double-click or
a second tab finds the post already claimed and never reaches Publora. The one HTTP call
carries an Idempotency-Key stored with the post, and a retry after an unclear failure
resends the identical body with the same key, which Publora replays instead of re-posting.

A post with a picture takes Publora's four media steps instead: create-post as a draft (same key
discipline), get-upload-url, PUT the bytes to storage, update-post to scheduled. posts.media_step
records the next step and posts.media what each step returned (the postGroupId first), so Retry
carries on from the step that failed and never creates a second post group. publora_post_id is set
only once the post is scheduled; until then a failure leaves the post failed, with Retry on offer.
"""
from __future__ import annotations

import hashlib
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import requests
from dotenv import dotenv_values

from .config import Config
from .db import DB, dumps, loads, utcnow

MIN_LEAD = timedelta(minutes=2)
MAX_AHEAD = timedelta(days=14)
COUNTED = ("scheduling", "scheduled", "published")
FIRST_COMMENT_MAX = 1250
POST_MAX = 3000
DASHBOARD_URL = "https://app.publora.com"
PICTURE_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")
UPLOAD_URL_TTL = timedelta(minutes=50)   # Publora's upload URLs expire after 1 hour
MEDIA_STEPS = ("create", "upload_url", "put", "update")   # media_step holds the next one, then "done"
STEP_LABEL = {"create": "Creating the post on Publora", "upload_url": "Asking Publora for an upload link",
              "put": "Uploading the picture", "update": "Scheduling the post on Publora"}


class ScheduleError(RuntimeError):
    pass


def sniff_image(head: bytes) -> str | None:
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def picture_record(picture: dict) -> dict:
    """The one picture a post can carry: {"path", "name", "mime", "sha256"}. Checked before anything is
    claimed or sent: a supported type, a readable file whose bytes match the type and the checksum.
    The file must stay at `path` until the post is scheduled; a Retry of the upload reads it again."""
    mime = str(picture.get("mime") or "").strip().lower()
    if mime not in PICTURE_TYPES:
        raise ScheduleError("The picture must be a PNG, JPEG, WebP or GIF file.")
    path = Path(str(picture.get("path") or "")).resolve()
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ScheduleError(f"The picture file cannot be read ({exc.strerror or exc}).") from exc
    if sniff_image(data[:12]) != mime:
        raise ScheduleError(f"The picture file is not the {mime.split('/')[1].upper()} image it is labelled as.")
    digest = hashlib.sha256(data).hexdigest()
    if picture.get("sha256") and str(picture["sha256"]).lower() != digest:
        raise ScheduleError("The picture file is not the one chosen: its contents have changed.")
    name = Path(str(picture.get("name") or "")).name.strip() or path.name
    return {"path": str(path), "name": name, "mime": mime, "sha256": digest}


def unclear_failure(exc: Exception) -> bool:
    return "Timeout" in type(exc).__name__ or "Connection" in type(exc).__name__


# The writer marks facts it does not have as [N], [DD Month YYYY], {slot}. None may reach LinkedIn.
SLOT = re.compile(r"\[[^\[\]\n]{1,60}\]|\{[A-Za-z_ ]{1,40}\}")


def placeholder_slots(text: str) -> list[str]:
    return SLOT.findall(text or "")


def real_value(value: str | None) -> str | None:
    """`.env` copied from `.env.example` holds placeholders like sk_your_key_here: treat as unset."""
    value = (value or "").strip().strip("'\"")
    return value if value and "your_" not in value else None


def read_env(cfg: Config) -> dict[str, str]:
    try:
        raw = dotenv_values(cfg.env_file)
    except OSError:
        return {}
    return {k: v for k, v in ((k, real_value(v)) for k, v in raw.items()) if v}


def _lib(cfg: Config):
    if str(cfg.skills_dir) not in sys.path:
        sys.path.insert(0, str(cfg.skills_dir))
    import lib.publora_client as publora  # noqa: PLC0415  (lives in the skills repo)
    return publora


_CLIENT_CLASS = None


def studio_client_class(cfg: Config):
    """PubloraClient from the skills repo plus single-request methods: no retry loops, the app's Retry decides."""
    global _CLIENT_CLASS
    if _CLIENT_CLASS is None:
        publora = _lib(cfg)

        class StudioPublora(publora.PubloraClient):
            def create_post_once(self, payload: dict, idempotency_key: str) -> dict:
                # One request, no retry loop (the client's own _post retries without a key).
                r = self._session.post(self.BASE_URL + "/create-post", json=payload,
                                       headers={"Idempotency-Key": idempotency_key}, timeout=self.timeout)
                return self._handle(r)

            def get_upload_url_once(self, post_group_id: str, file_name: str, content_type: str) -> dict:
                r = self._session.post(self.BASE_URL + "/get-upload-url", timeout=self.timeout, json={
                    "postGroupId": post_group_id, "fileName": file_name, "contentType": content_type})
                return self._handle(r)

            def put_upload(self, upload_url: str, data: bytes, content_type: str) -> None:
                # Straight to storage, not through the session: the Publora key must not travel with it.
                r = requests.put(upload_url, data=data, headers={"Content-Type": content_type},
                                 timeout=max(self.timeout, 120))
                if r.status_code >= 400:
                    raise publora.PubloraError(f"storage answered HTTP {r.status_code}")

            def update_post_once(self, post_group_id: str, body: dict) -> dict:
                # No Idempotency-Key: a status and time body is safe to resend, and a replayed
                # error (say a 503 while the upload settles) must not stick for 24 hours.
                r = self._session.put(f"{self.BASE_URL}/update-post/{post_group_id}", json=body,
                                      timeout=self.timeout)
                return self._handle(r)

            def delete_media(self, media_id: str) -> dict:
                r = self._session.delete(f"{self.BASE_URL}/media/{media_id}", timeout=self.timeout)
                return self._handle(r)

        _CLIENT_CLASS = StudioPublora
    return _CLIENT_CLASS


def make_client(cfg: Config):
    """Keyed from linkedin-skills\\.env, read by explicit path."""
    key = read_env(cfg).get("PUBLORA_API_KEY")
    if not key:
        raise ScheduleError("PUBLORA_API_KEY is not set in linkedin-skills\\.env.")
    return studio_client_class(cfg)(api_key=key)


def utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


class Publisher:
    def __init__(self, db: DB, cfg: Config, client_factory: Callable[[], Any] | None = None,
                 now: Callable[[], datetime] | None = None):
        self.db = db
        self.cfg = cfg
        self.client_factory = client_factory or (lambda: make_client(cfg))
        self.now = now or (lambda: datetime.now(timezone.utc))
        self._platform_id: str | None = None

    # ---- configuration -------------------------------------------------------
    def status(self) -> dict:
        env = read_env(self.cfg)
        return {"key": bool(env.get("PUBLORA_API_KEY")), "platform_id": bool(env.get("LINKEDIN_PLATFORM_ID")),
                "apify": bool(env.get("APIFY_TOKEN"))}

    def platform_id(self, client: Any) -> str:
        if self._platform_id:
            return self._platform_id
        pid = read_env(self.cfg).get("LINKEDIN_PLATFORM_ID")
        if not pid:
            pid = client.resolve_linkedin_platform_id()
        if not pid:
            raise ScheduleError("LINKEDIN_PLATFORM_ID is not set in linkedin-skills\\.env and the key has no "
                                "single LinkedIn channel to pick. Copy the linkedin-... id from Publora > Channels.")
        self._platform_id = pid
        return pid

    # ---- validation ----------------------------------------------------------
    def parse_local(self, local_value: str) -> datetime:
        """`2026-10-08T09:00` from <input type=datetime-local>, in the configured zone -> aware UTC."""
        try:
            naive = datetime.fromisoformat(local_value.strip())
        except ValueError as exc:
            raise ScheduleError("Pick a date and time.") from exc
        if naive.tzinfo is not None:
            raise ScheduleError("Send local time without a zone.")
        when = naive.replace(tzinfo=self.cfg.tz).astimezone(timezone.utc)
        now = self.now()
        if when < now + MIN_LEAD:
            raise ScheduleError("That time is in the past (or under 2 minutes away). Pick a later time.")
        if when > now + MAX_AHEAD:
            raise ScheduleError("Publora scheduling here is limited to 14 days ahead. Pick an earlier time.")
        return when

    def month_bounds(self, when: datetime) -> tuple[str, str]:
        local = when.astimezone(self.cfg.tz)
        start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = (start + timedelta(days=32)).replace(day=1)
        return utc_iso(start), utc_iso(end)

    def quota_used(self, when: datetime, con=None) -> int:
        start, end = self.month_bounds(when)
        sql = (f"SELECT COUNT(*) FROM posts WHERE status IN ({','.join('?' * len(COUNTED))}) "
               "AND scheduled_at >= ? AND scheduled_at < ?")
        args = (*COUNTED, start, end)
        row = (con.execute(sql, args).fetchone() if con is not None else self.db.one(sql, args))
        return int(row[0])

    # ---- transitions ---------------------------------------------------------
    def approve(self, post_id: int) -> None:
        row = self.db.one("SELECT text FROM posts WHERE id=? AND status='draft'", (post_id,))
        if row is None:
            raise ScheduleError("Only a draft can be approved.")
        text = row["text"].strip()
        if not text:
            raise ScheduleError("The draft is empty.")
        if len(text) > POST_MAX:
            raise ScheduleError(f"LinkedIn caps posts at {POST_MAX} characters; this one has {len(text)}.")
        slots = placeholder_slots(text)
        if slots:
            raise ScheduleError(f"The draft still has {len(slots)} placeholder slot(s), such as {slots[0]}. The writer "
                                "leaves these where it has no real fact. Fill them in (or remove the brackets), "
                                "save, then approve.")
        self.db.run("UPDATE posts SET status='approved', updated_at=? WHERE id=? AND status='draft'",
                    (utcnow(), post_id))

    def back_to_draft(self, post_id: int) -> None:
        row = self.db.one("SELECT status, media FROM posts WHERE id=?", (post_id,))
        group = (loads(row["media"], {}) or {}).get("postGroupId") if row and row["status"] == "failed" else None
        if group:  # a picture post stopped part-way: its Publora draft goes first, so nothing lingers there
            try:
                self.client_factory().delete_post(post_group_id=group)
            except Exception as exc:
                if "HTTP 404" not in str(exc):  # 404: already gone, e.g. deleted in the dashboard
                    raise ScheduleError(f"Publora would not delete its draft of this post: {exc}. Delete it in "
                                        f"the Publora dashboard ({DASHBOARD_URL}), then try again.") from exc
        n = self.db.run("UPDATE posts SET status='draft', idempotency_key=NULL, publora_payload=NULL, "
                        "scheduled_at=NULL, error=NULL, media=NULL, media_step=NULL, updated_at=? WHERE id=? "
                        "AND publora_post_id IS NULL AND status IN ('approved','failed')", (utcnow(), post_id))
        if n != 1:
            raise ScheduleError("Only an approved post, or one whose scheduling failed, can go back to draft.")

    def schedule(self, post_id: int, local_when: str, first_comment: str | None,
                 picture: dict | None = None) -> dict:
        when = self.parse_local(local_when)
        comment = (first_comment or "").strip() or None
        if comment and len(comment) > FIRST_COMMENT_MAX:
            raise ScheduleError(f"The first comment is {len(comment)} characters; LinkedIn allows {FIRST_COMMENT_MAX}.")
        media = picture_record(picture) if picture else None
        client = self.client_factory()
        platform_id = self.platform_id(client)
        with self.db.transaction() as con:
            row = con.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
            if row is None:
                raise ScheduleError("No such post.")
            if row["trashed_at"]:   # the API refuses it first; this keeps the Trash out of Publora whoever calls
                raise ScheduleError("That post is in the Trash. Put it back first.")
            if row["publora_post_id"]:
                raise ScheduleError("This post already exists on Publora; it will not be sent again.")
            if row["status"] != "approved":
                raise ScheduleError(f"Only an approved post can be scheduled; this one is {row['status']}.")
            used = self.quota_used(when, con)
            if used >= self.cfg.monthly_post_limit:
                raise ScheduleError(f"Monthly limit reached: {used}/{self.cfg.monthly_post_limit} posts are already "
                                    f"scheduled or published in {when.astimezone(self.cfg.tz):%B %Y}.")
            payload: dict[str, Any] = {"content": row["text"], "platforms": [platform_id]}
            if media is None:  # with a picture it is created as a draft and scheduled by update-post
                payload["scheduledTime"] = when.strftime("%Y-%m-%dT%H:%M:%SZ")
            if comment:
                payload["firstComment"] = {"text": comment, "platforms": ["linkedin"]}
            key = f"linkedin-studio-{post_id}-{uuid.uuid4().hex}"
            con.execute("UPDATE posts SET status='scheduling', scheduled_at=?, idempotency_key=?, publora_payload=?, "
                        "first_comment=?, error=NULL, media=?, media_step=?, updated_at=? WHERE id=? "
                        "AND status='approved' AND publora_post_id IS NULL",
                        (utc_iso(when), key, dumps(payload), comment, dumps(media) if media else None,
                         "create" if media else None, utcnow(), post_id))
        if media:
            return self._run_media(post_id, client)
        return self._send(post_id, client, payload, key)

    def retry(self, post_id: int, picture: dict | None = None) -> dict:
        """Resend the identical body with the same key after a failed schedule call; a picture post
        carries on from the step that failed, with the picture it started with (`picture` may give
        that same file's new path)."""
        with self.db.transaction() as con:
            row = con.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
            if row is None or row["status"] != "failed" or row["publora_post_id"] or not row["publora_payload"]:
                raise ScheduleError("Only a post whose schedule call failed can be retried.")
            if row["trashed_at"]:
                raise ScheduleError("That post is in the Trash. Put it back first.")
            if picture:
                if row["media_step"] not in MEDIA_STEPS:
                    raise ScheduleError("This post was sent without a picture. Move it back to draft to add one.")
                media = loads(row["media"], {})
                if str(picture.get("sha256") or "").lower() not in ("", media.get("sha256")):
                    raise ScheduleError("This post is part-way through scheduling with another picture. Move it "
                                        "back to draft to change the picture.")
                if picture.get("path"):
                    media["path"] = str(Path(str(picture["path"])).resolve())
                    con.execute("UPDATE posts SET media=? WHERE id=?", (dumps(media), post_id))
            when = parse_utc(row["scheduled_at"])
            if when < self.now() + MIN_LEAD:
                raise ScheduleError("The scheduled time has passed. Move it back to draft and pick a new time.")
            used = self.quota_used(when, con)
            if used >= self.cfg.monthly_post_limit:
                raise ScheduleError("Monthly limit reached.")
            con.execute("UPDATE posts SET status='scheduling', error=NULL, updated_at=? WHERE id=? AND status='failed'",
                        (utcnow(), post_id))
            payload, key = loads(row["publora_payload"]), row["idempotency_key"]
        if row["media_step"] in MEDIA_STEPS:
            return self._run_media(post_id, self.client_factory())
        return self._send(post_id, self.client_factory(), payload, key)

    @staticmethod
    def _failure_text(exc: Exception) -> str:
        if unclear_failure(exc):
            return (f"No answer from Publora ({type(exc).__name__}). It may or may not have created the post: "
                    "check the Publora dashboard, then use Retry (it cannot create a second copy).")
        return str(exc)

    def _send(self, post_id: int, client: Any, payload: dict, key: str) -> dict:
        try:
            resp = client.create_post_once(payload, key)
        except Exception as exc:  # PubloraError, timeouts, connection errors
            msg = self._failure_text(exc)
            self.db.run("UPDATE posts SET status='failed', error=?, updated_at=? WHERE id=?",
                        (msg[:1000], utcnow(), post_id))
            return {"ok": False, "error": msg}
        group = resp.get("postGroupId") if isinstance(resp, dict) else None
        if not group:
            msg = f"Publora answered without a postGroupId: {str(resp)[:300]}"
            self.db.run("UPDATE posts SET status='failed', error=?, updated_at=? WHERE id=?",
                        (msg, utcnow(), post_id))
            return {"ok": False, "error": msg}
        scheduled = resp.get("scheduledTime")
        warnings = resp.get("warnings") or []
        self.db.run("UPDATE posts SET status='scheduled', publora_post_id=?, scheduled_at=COALESCE(?, scheduled_at), "
                    "error=?, updated_at=? WHERE id=?",
                    (group, utc_iso(parse_utc(scheduled)) if scheduled else None,
                     ("Publora warnings: " + "; ".join(map(str, warnings))) if warnings else None, utcnow(), post_id))
        return {"ok": True, "postGroupId": group, "warnings": warnings}

    def _run_media(self, post_id: int, client: Any) -> dict:
        """A picture post's steps, from the one recorded; each result is saved before the next step runs."""
        row = self.db.one("SELECT * FROM posts WHERE id=?", (post_id,))
        media, step = loads(row["media"], {}), row["media_step"]

        def advance(next_step: str) -> str:
            self.db.run("UPDATE posts SET media=?, media_step=?, updated_at=? WHERE id=?",
                        (dumps(media), next_step, utcnow(), post_id))
            return next_step

        try:
            if step == "create":
                resp = client.create_post_once(loads(row["publora_payload"]), row["idempotency_key"])
                group = resp.get("postGroupId") if isinstance(resp, dict) else None
                if not group:
                    raise RuntimeError(f"Publora answered without a postGroupId: {str(resp)[:300]}")
                media["postGroupId"] = group
                step = advance("upload_url")
            if step == "put" and self.now() - parse_utc(media["urlAt"]) > UPLOAD_URL_TTL:
                step = "upload_url"  # the upload link has expired: ask for a new one
            if step == "upload_url":
                if media.get("urlAsked"):
                    # An earlier request may have attached a file that never arrived (no answer, or an
                    # expired link). Publora refuses to schedule a post holding one, so remove it first.
                    for item in client.get_post(post_group_id=media["postGroupId"]).get("media") or []:
                        client.delete_media(item["mediaId"])
                media["urlAsked"] = True
                advance("upload_url")
                resp = client.get_upload_url_once(media["postGroupId"], media["name"], media["mime"])
                if not (isinstance(resp, dict) and resp.get("uploadUrl") and resp.get("mediaId")):
                    raise RuntimeError(f"Publora answered without an upload link: {str(resp)[:300]}")
                media.update(mediaId=resp["mediaId"], uploadUrl=resp["uploadUrl"], fileUrl=resp.get("fileUrl"),
                             urlAt=utc_iso(self.now()))
                step = advance("put")
            if step == "put":
                try:
                    data = Path(media["path"]).read_bytes()
                except OSError as exc:
                    raise RuntimeError(f"the picture file cannot be read ({exc.strerror or exc})") from exc
                if hashlib.sha256(data).hexdigest() != media["sha256"]:
                    raise RuntimeError("the picture file has changed since it was chosen")
                client.put_upload(media["uploadUrl"], data, media["mime"])
                step = advance("update")
            # step == "update"
            resp = client.update_post_once(media["postGroupId"], {
                "status": "scheduled", "scheduledTime": parse_utc(row["scheduled_at"]).strftime("%Y-%m-%dT%H:%M:%SZ")})
            state = (resp.get("postGroup") or {}) if isinstance(resp, dict) else None
            if state is None or state.get("status", "scheduled") != "scheduled":
                raise RuntimeError(f"Publora did not confirm the schedule: {str(resp)[:300]}")
        except Exception as exc:  # PubloraError, timeouts, connection errors, a missing file
            if step == "create":
                msg = self._failure_text(exc)
            else:
                detail = f"no answer ({type(exc).__name__})" if unclear_failure(exc) else str(exc)
                msg = (f"{STEP_LABEL[step]} failed: {detail}. Publora holds this post as an unscheduled draft, so "
                       "it will not go out yet. Retry carries on from this step and never makes a second post; "
                       "Back to draft deletes the Publora draft.")
            self.db.run("UPDATE posts SET status='failed', error=?, media=?, media_step=?, updated_at=? WHERE id=?",
                        (msg[:1000], dumps(media), step, utcnow(), post_id))
            return {"ok": False, "error": msg, "step": step}
        scheduled = resp.get("scheduledTime") or state.get("scheduledTime")
        warnings = resp.get("warnings") or []
        media.pop("uploadUrl", None)  # spent; it was a one-hour write link to storage
        self.db.run("UPDATE posts SET status='scheduled', publora_post_id=?, media=?, media_step='done', "
                    "scheduled_at=COALESCE(?, scheduled_at), error=?, updated_at=? WHERE id=?",
                    (media["postGroupId"], dumps(media), utc_iso(parse_utc(scheduled)) if scheduled else None,
                     ("Publora warnings: " + "; ".join(map(str, warnings))) if warnings else None, utcnow(), post_id))
        return {"ok": True, "postGroupId": media["postGroupId"], "warnings": warnings}

    def cancel(self, post_id: int) -> None:
        row = self.db.one("SELECT * FROM posts WHERE id=?", (post_id,))
        if row is None or row["status"] != "scheduled" or not row["publora_post_id"]:
            raise ScheduleError("Only a scheduled post can be cancelled.")
        try:
            self.client_factory().delete_post(post_group_id=row["publora_post_id"])
        except Exception as exc:
            raise ScheduleError(f"Publora would not cancel it: {exc}. Use the Publora dashboard "
                                f"({DASHBOARD_URL}).") from exc
        self.db.run("UPDATE posts SET status='cancelled', error=NULL, updated_at=? WHERE id=? AND status='scheduled'",
                    (utcnow(), post_id))

    def refresh(self, post_id: int) -> str:
        row = self.db.one("SELECT * FROM posts WHERE id=?", (post_id,))
        if row is None or row["status"] != "scheduled" or not row["publora_post_id"]:
            return row["status"] if row else "missing"
        body = self.client_factory().get_post(post_group_id=row["publora_post_id"])
        remote = (body.get("postGroup") or body).get("status")
        new = {"published": "published", "partially_published": "published", "failed": "failed"}.get(remote)
        if new:
            errors = [p.get("error") for p in body.get("posts") or [] if p.get("error")]
            self.db.run("UPDATE posts SET status=?, error=?, updated_at=? WHERE id=? AND status='scheduled'",
                        (new, ("Publora: " + "; ".join(map(str, errors))) if errors else None, utcnow(), post_id))
        return new or "scheduled"


# The UI's entry points for a post with a picture. `picture` is {"path", "name", "mime", "sha256"};
# empty or None means no picture, which is today's single-request flow. Results are shaped like
# Publisher.schedule's: {"ok": True, "postGroupId", "warnings"} or {"ok": False, "error", "step"};
# a refusal before anything is sent raises ScheduleError.
def schedule_with_picture(publisher: Publisher, post_id: int, local_when: str, first_comment: str | None,
                          picture: dict | None) -> dict:
    return publisher.schedule(post_id, local_when, first_comment, picture or None)


def retry_with_picture(publisher: Publisher, post_id: int, picture: dict | None) -> dict:
    return publisher.retry(post_id, picture or None)
