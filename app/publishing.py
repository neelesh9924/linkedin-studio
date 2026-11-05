"""Publishing through linkedin-skills\\lib\\publora_client.py, with exactly-once scheduling.

State machine: draft -> approved -> scheduling -> scheduled -> published | failed | cancelled. An approved post may wait
in the posting queue (posting.py, posts.queue_pos) for its time; it leaves the queue as it is claimed, or goes back.
The approved -> scheduling step is one BEGIN IMMEDIATE transaction, so a double-click or
a second tab finds the post already claimed and never reaches Publora. The one HTTP call
carries an Idempotency-Key stored with the post, and a retry after an unclear failure
resends the identical body with the same key, which Publora replays instead of re-posting.

A post with pictures or a carousel takes Publora's media steps instead: create-post as a draft (same key
discipline), then for each file get-upload-url and a PUT of its bytes to storage, then update-post to scheduled.
posts.media_step records the next step and posts.media what each step returned (the postGroupId first, then each
file's mediaId and whether it arrived), so Retry carries on from the file and step that failed and never creates a
second post group or uploads a file twice. publora_post_id is set only once the post is scheduled; until then a
failure leaves the post failed, with Retry on offer.

Post now (Publisher.post_now) is the same path for the soonest time, MIN_LEAD from now: Publora has no "post at once" (a
post sent with no time is kept there as a draft). posts.post_now marks it, so Retry still sends it once that time has
passed, where a post scheduled for a time of its own is refused.
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
from .images import DOCUMENT, EXTENSION, MAX_PICTURES

MIN_LEAD = timedelta(minutes=2)
COUNTED = ("scheduling", "scheduled", "published")
WAITING_THERE = ("scheduling", "scheduled")     # held by Publora until they go out: its "scheduled posts at a time"
# Publora's plans as its pricing page gives them (Oct 2026). Settings › Publishing picks one, and config.local.toml keeps
# its three numbers. 0: no limit. Pro has none at Publora; the studio still schedules at most 14 days ahead, so the
# queue keeps what lies further out in its own order.
PLANS = {
    "starter": {"label": "Starter (free)", "monthly_post_limit": 15, "publora_at_once": 3, "publora_days_ahead": 7},
    "pro": {"label": "Pro", "monthly_post_limit": 0, "publora_at_once": 0, "publora_days_ahead": 14},
}


def plan_of(cfg: Config) -> str:
    """The plan whose limits the config holds: "starter", "pro", or "custom" for numbers set by hand."""
    for key, plan in PLANS.items():
        if all(getattr(cfg, name) == value for name, value in plan.items() if name != "label"):
            return key
    return "custom"


def limit_words(cfg: Config) -> str:
    """The plan's limits in a line: "15 posts a month, 3 scheduled at a time, 7 days ahead", or "no limits"."""
    parts = [f"{cfg.monthly_post_limit} posts a month" if cfg.monthly_post_limit else "",
             f"{cfg.publora_at_once} scheduled at a time" if cfg.publora_at_once else "",
             f"{cfg.publora_days_ahead} days ahead" if cfg.publora_days_ahead < PLANS["pro"]["publora_days_ahead"] else ""]
    said = [p for p in parts if p]
    return ", ".join(said) if said else "no limits"
FIRST_COMMENT_MAX = 1250
POST_MAX = 3000
DASHBOARD_URL = "https://app.publora.com"
UPLOAD_URL_TTL = timedelta(minutes=50)   # Publora's upload URLs expire after 1 hour
MEDIA_STEPS = ("create", "upload_url", "put", "update")   # media_step holds the next one, then "done"
STEP_LABEL = {"create": "Creating the post on Publora", "upload_url": "Asking Publora for an upload link for {what}",
              "put": "Uploading {what}", "update": "Scheduling the post on Publora"}


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
    if head.startswith(b"%PDF-"):
        return DOCUMENT
    return None


def picture_record(picture: dict) -> dict:
    """One file going out with a post, a picture or a carousel's PDF: {"path", "name", "mime", "sha256"}. Checked
    before anything is claimed or sent: a supported type, a readable file whose bytes match the type and the checksum.
    The file must stay at `path` until the post is scheduled; a Retry of the upload reads it again."""
    mime = str(picture.get("mime") or "").strip().lower()
    what = "carousel" if mime == DOCUMENT else "picture"
    if mime not in EXTENSION:
        raise ScheduleError("The picture must be a PNG, JPEG, WebP or GIF file, or a carousel's PDF.")
    path = Path(str(picture.get("path") or "")).resolve()
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ScheduleError(f"The {what} file cannot be read ({exc.strerror or exc}).") from exc
    if sniff_image(data[:12]) != mime:
        raise ScheduleError(f"The {what} file is not the {EXTENSION[mime].upper()} it is labelled as.")
    digest = hashlib.sha256(data).hexdigest()
    if picture.get("sha256") and str(picture["sha256"]).lower() != digest:
        raise ScheduleError(f"The {what} file is not the one chosen: its contents have changed.")
    name = Path(str(picture.get("name") or "")).name.strip() or path.name
    return {"path": str(path), "name": name, "mime": mime, "sha256": digest}


def media_record(pictures: list[dict]) -> dict:
    """What a post sends to Publora besides its text: up to MAX_PICTURES pictures, or one carousel alone."""
    files = [picture_record(p) for p in pictures]
    if any(f["mime"] == DOCUMENT for f in files) and len(files) > 1:
        raise ScheduleError("A carousel goes out alone: LinkedIn doesn't mix a document with pictures.")
    if len(files) > MAX_PICTURES:
        raise ScheduleError(f"A post takes up to {MAX_PICTURES} pictures.")
    return {"files": files}


def media_files(media: dict, step: str | None) -> list[dict]:
    """The files of posts.media. One kept before 3 Nov 2026 had its single picture's fields at the top."""
    if "files" not in media and media.get("path"):
        one = {k: media.pop(k) for k in ("path", "name", "mime", "sha256", "mediaId", "uploadUrl", "fileUrl", "urlAt",
                                         "urlAsked") if k in media}
        one["done"] = step in ("update", "done")
        media["files"] = [one]
    return media.setdefault("files", [])


def what_of(files: list[dict], item: dict | None) -> str:
    """A file in the owner's words: "the carousel", "the picture", "picture 2 of 3"."""
    if item is None:
        return "the pictures"
    if item["mime"] == DOCUMENT:
        return "the carousel"
    return "the picture" if len(files) == 1 else f"picture {files.index(item) + 1} of {len(files)}"


def unclear_failure(exc: Exception) -> bool:
    return "Timeout" in type(exc).__name__ or "Connection" in type(exc).__name__


# What get-post says about a post, read without sending anything. Only a LinkedIn address is ever kept as the post's
# link (the page offers it as Open on LinkedIn): its permalink, or the feed address of its urn:li: id.
LINKEDIN = "https://www.linkedin.com/"
_LINKEDIN_LINK = re.compile(r"https://www\.linkedin\.com/[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]{0,1900}")
_URN = re.compile(r"urn:li:[A-Za-z]{2,40}:[A-Za-z0-9_-]{1,100}")
NO_REASON = "Publora says it failed, and gave no reason. Its dashboard may say more."


def linkedin_link(value: Any) -> str | None:
    """`value` when it is a https://www.linkedin.com/ address, else None: no other link is ever kept or offered."""
    link = value.strip() if isinstance(value, str) else ""
    return link if _LINKEDIN_LINK.fullmatch(link) else None


def _said(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("message") or value.get("error") or value.get("code") or ""
    return " ".join(str(value or "").split())[:300]


def remote_state(body: Any) -> tuple[str, str | None, list[str]]:
    """get-post's answer as (published | failed | scheduled, the post's LinkedIn link or None, Publora's own words).
    The status is read at the top level or under postGroup; published and partially_published are published, failed
    is failed, and anything else is still scheduled. The words are the posts' errors and the group's."""
    body = body if isinstance(body, dict) else {}
    group = body.get("postGroup") if isinstance(body.get("postGroup"), dict) else {}
    remote = str(body.get("status") or group.get("status") or "").strip().lower()
    posts = [p for p in [*(body.get("posts") if isinstance(body.get("posts"), list) else []),
                         *(group.get("posts") if isinstance(group.get("posts"), list) else [])] if isinstance(p, dict)]
    words: list[str] = []
    for value in [*(p.get("error") for p in posts), group.get("error"), body.get("error")]:
        said = _said(value)
        if said and said not in words:
            words.append(said)
    status = "published" if remote in ("published", "partially_published") else "failed" if remote == "failed" else "scheduled"
    link = None
    if status == "published":
        link = next(filter(None, (linkedin_link(p.get("permalink")) for p in posts)), None)
        posted = next((u for u in (str(p.get("postedId") or "").strip() for p in posts) if _URN.fullmatch(u)), None)
        if link is None and posted:
            link = linkedin_link(f"{LINKEDIN}feed/update/{posted}")
    return status, link, words


# The writer marks facts it does not have as [N], [DD Month YYYY], [what you would tell yourself], {slot}. None may reach
# LinkedIn. Code in a post is not a blank: brackets holding quotes, parentheses, backslashes or operators, a list of
# numbers, or an index straight after a name (items[0]). An apostrophe inside a word (you'd) is still words. The page
# compiles the same pattern (/api/state's slot), so it must stay valid as a JavaScript RegExp too.
SLOT = re.compile(r"(?<![\w)\]])\[(?![\d\s.,]+\])(?:[^\[\]\n\"'`(){}\\^=;<>]|(?<=[A-Za-z])'(?=[A-Za-z])){1,120}\]"
                  r"|\{[A-Za-z_ ]{1,40}\}")


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

    @property
    def max_ahead(self) -> timedelta:
        """How far ahead a post can be scheduled: the Publora plan's limit (config publora_days_ahead)."""
        return timedelta(days=self.cfg.publora_days_ahead)

    def waiting_there(self, con=None) -> int:
        """Posts Publora holds until they go out: sending or scheduled, and not yet heard back as published."""
        sql = f"SELECT COUNT(*) FROM posts WHERE status IN ({','.join('?' * len(WAITING_THERE))})"
        row = con.execute(sql, WAITING_THERE).fetchone() if con is not None else self.db.one(sql, WAITING_THERE)
        return int(row[0])

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
        if when > now + self.max_ahead:
            raise ScheduleError(f"Your Publora plan schedules up to {self.cfg.publora_days_ahead} days ahead. Pick an "
                                "earlier time.")
        return when

    def soonest(self) -> datetime:
        """Post now's time: MIN_LEAD from now, the least Schedule… takes (to the second, rounded up)."""
        at = self.now() + MIN_LEAD
        return at.replace(microsecond=0) + timedelta(seconds=1) if at.microsecond else at

    def room(self, when: datetime, con=None, post_now: bool = False) -> None:
        """Refuses (ScheduleError) a post at `when` the plan has no room for: the month's posts are all used, or Publora
        holds all the scheduled posts it takes at a time. `post_now`: said for Post now."""
        used = self.quota_used(when, con)
        if self.cfg.monthly_post_limit and used >= self.cfg.monthly_post_limit:
            raise ScheduleError(f"Monthly limit reached: {used}/{self.cfg.monthly_post_limit} posts are already "
                                f"scheduled or published in {when.astimezone(self.cfg.tz):%B %Y}.")
        held = self.waiting_there(con)
        if self.cfg.publora_at_once and held >= self.cfg.publora_at_once:
            then = ("Post it now once one of them has gone out, or make room with Cancel on Publora, in its gear."
                    if post_now else "Schedule this one once one has gone out, or queue it: the queue sends it then.")
            raise ScheduleError(f"Your Publora plan holds {self.cfg.publora_at_once} scheduled posts at a time, and "
                                f"{held} are waiting there now. {then}")

    def month_bounds(self, when: datetime) -> tuple[str, str]:
        local = when.astimezone(self.cfg.tz)
        start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = (start + timedelta(days=32)).replace(day=1)
        return utc_iso(start), utc_iso(end)

    def quota_used(self, when: datetime, con=None) -> int:
        """The month's posts: those at Publora or sent (in the Trash too), and the sent ones deleted forever since."""
        start, end = self.month_bounds(when)
        sql = (f"SELECT (SELECT COUNT(*) FROM posts WHERE status IN ({','.join('?' * len(COUNTED))}) "
               "AND scheduled_at >= ? AND scheduled_at < ?) "
               "+ (SELECT COUNT(*) FROM spent WHERE scheduled_at >= ? AND scheduled_at < ?)")
        args = (*COUNTED, start, end, start, end)
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
                        "scheduled_at=NULL, error=NULL, media=NULL, media_step=NULL, queue_pos=NULL, post_now=NULL, "
                        "updated_at=? WHERE id=? AND publora_post_id IS NULL AND status IN ('approved','failed')",
                        (utcnow(), post_id))
        if n != 1:
            raise ScheduleError("Only an approved post, or one whose scheduling failed, can go back to draft.")

    def schedule(self, post_id: int, local_when: str, first_comment: str | None,
                 pictures: list[dict] | None = None) -> dict:
        return self._schedule(post_id, self.parse_local(local_when), first_comment, pictures)

    def post_now(self, post_id: int, first_comment: str | None, pictures: list[dict] | None = None) -> dict:
        """Post now: an approved post (queued or not) to Publora for the soonest time, as Schedule… sends it."""
        return self._schedule(post_id, self.soonest(), first_comment, pictures, post_now=True)

    def _schedule(self, post_id: int, when: datetime, first_comment: str | None, pictures: list[dict] | None,
                  post_now: bool = False) -> dict:
        comment = (first_comment or "").strip() or None
        if comment and len(comment) > FIRST_COMMENT_MAX:
            raise ScheduleError(f"The first comment is {len(comment)} characters; LinkedIn allows {FIRST_COMMENT_MAX}.")
        media = media_record(pictures) if pictures else None
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
            self.room(when, con, post_now)
            payload: dict[str, Any] = {"content": row["text"], "platforms": [platform_id]}
            if media is None:  # with pictures it is created as a draft and scheduled by update-post
                payload["scheduledTime"] = when.strftime("%Y-%m-%dT%H:%M:%SZ")
            if comment:
                payload["firstComment"] = {"text": comment, "platforms": ["linkedin"]}
            key = f"linkedin-studio-{post_id}-{uuid.uuid4().hex}"
            con.execute("UPDATE posts SET status='scheduling', scheduled_at=?, idempotency_key=?, publora_payload=?, "
                        "first_comment=?, error=NULL, media=?, media_step=?, queue_pos=NULL, post_now=?, updated_at=? "
                        "WHERE id=? AND status='approved' AND publora_post_id IS NULL",
                        (utc_iso(when), key, dumps(payload), comment, dumps(media) if media else None,
                         "create" if media else None, 1 if post_now else None, utcnow(), post_id))
        if media:
            return self._run_media(post_id, client)
        return self._send(post_id, client, payload, key)

    def retry(self, post_id: int, pictures: list[dict] | None = None) -> dict:
        """Resend the identical body with the same key after a failed schedule call; a post with pictures
        carries on from the file and step that failed, with the files it started with (`pictures` may give
        those same files' new paths)."""
        with self.db.transaction() as con:
            row = con.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
            if row is None or row["status"] != "failed" or row["publora_post_id"] or not row["publora_payload"]:
                raise ScheduleError("Only a post whose schedule call failed can be retried.")
            if row["trashed_at"]:
                raise ScheduleError("That post is in the Trash. Put it back first.")
            if pictures:
                if row["media_step"] not in MEDIA_STEPS:
                    raise ScheduleError("This post was sent without a picture. Move it back to draft to add one.")
                media = loads(row["media"], {})
                files = media_files(media, row["media_step"])
                given = [str(p.get("sha256") or "").lower() for p in pictures]
                if any(given) and given != [f.get("sha256") for f in files]:
                    raise ScheduleError("This post is part-way through scheduling with other pictures. Move it "
                                        "back to draft to change them.")
                for file, picture in zip(files, pictures):
                    if picture.get("path"):
                        file["path"] = str(Path(str(picture["path"])).resolve())
                con.execute("UPDATE posts SET media=? WHERE id=?", (dumps(media), post_id))
            when = parse_utc(row["scheduled_at"])
            if when < self.now() + MIN_LEAD:
                if not row["post_now"]:
                    raise ScheduleError("The scheduled time has passed. Move it back to draft and pick a new time.")
                # Posted now, it still goes now. With pictures, the schedule step (update-post, safe to resend) takes
                # the soonest time. Without, its one request goes again as it was, key and all: Publora replays it if
                # it made the post, sends it at once if its time has only just gone, and refuses it once 5 minutes
                # have. Either way there is never a second post.
                if row["media_step"] in MEDIA_STEPS:
                    when = self.soonest()
                    con.execute("UPDATE posts SET scheduled_at=? WHERE id=?", (utc_iso(when), post_id))
            used = self.quota_used(when, con)
            if self.cfg.monthly_post_limit and used >= self.cfg.monthly_post_limit:
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
        """A post's media steps, from the one recorded: the post group, then each file in turn (an upload link, then
        its bytes), then the schedule. Each result is saved before the next step runs."""
        row = self.db.one("SELECT * FROM posts WHERE id=?", (post_id,))
        media, step = loads(row["media"], {}), row["media_step"]
        files = media_files(media, step)
        item = None

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
            while step in ("upload_url", "put"):
                item = next((f for f in files if not f.get("done")), None)
                if item is None:
                    step = advance("update")
                    break
                if step == "put" and self.now() - parse_utc(item["urlAt"]) > UPLOAD_URL_TTL:
                    step = "upload_url"  # the upload link has expired: ask for a new one
                if step == "upload_url":
                    if item.get("urlAsked"):
                        # An earlier request may have attached a file that never arrived (no answer, or an expired
                        # link). Publora refuses to schedule a post holding one, so remove all but the files that did.
                        arrived = {f.get("mediaId") for f in files if f.get("done")}
                        for held in client.get_post(post_group_id=media["postGroupId"]).get("media") or []:
                            if held.get("mediaId") not in arrived:
                                client.delete_media(held["mediaId"])
                    item["urlAsked"] = True
                    advance("upload_url")
                    resp = client.get_upload_url_once(media["postGroupId"], item["name"], item["mime"])
                    if not (isinstance(resp, dict) and resp.get("uploadUrl") and resp.get("mediaId")):
                        raise RuntimeError(f"Publora answered without an upload link: {str(resp)[:300]}")
                    item.update(mediaId=resp["mediaId"], uploadUrl=resp["uploadUrl"], fileUrl=resp.get("fileUrl"),
                                urlAt=utc_iso(self.now()))
                    step = advance("put")
                what = "carousel" if item["mime"] == DOCUMENT else "picture"
                try:
                    data = Path(item["path"]).read_bytes()
                except OSError as exc:
                    raise RuntimeError(f"the {what} file cannot be read ({exc.strerror or exc})") from exc
                if hashlib.sha256(data).hexdigest() != item["sha256"]:
                    raise RuntimeError(f"the {what} file has changed since it was chosen")
                client.put_upload(item["uploadUrl"], data, item["mime"])
                item["done"] = True
                item.pop("uploadUrl", None)  # spent; it was a one-hour write link to storage
                step = advance("upload_url")  # the next file, or the schedule when none is left
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
                msg = (f"{STEP_LABEL[step].format(what=what_of(files, item))} failed: {detail}. Publora holds this post "
                       "as an unscheduled draft, so it will not go out yet. Retry carries on from this step and never "
                       "makes a second post; Back to draft deletes the Publora draft.")
            self.db.run("UPDATE posts SET status='failed', error=?, media=?, media_step=?, updated_at=? WHERE id=?",
                        (msg[:1000], dumps(media), step, utcnow(), post_id))
            return {"ok": False, "error": msg, "step": step}
        scheduled = resp.get("scheduledTime") or state.get("scheduledTime")
        warnings = resp.get("warnings") or []
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
        """Read a scheduled post's status from Publora: get-post only, so nothing is sent, changed or deleted there.
        Published (or partially) becomes published, with the post's LinkedIn link when Publora gives one; failed
        becomes failed, in Publora's own words; anything else stays scheduled. A post in the Trash is never asked
        about. Returns the post's status."""
        row = self.db.one("SELECT * FROM posts WHERE id=?", (post_id,))
        if row is None:
            return "missing"
        if row["trashed_at"] or row["status"] != "scheduled" or not row["publora_post_id"]:
            return row["status"]
        status, link, words = remote_state(self.client_factory().get_post(post_group_id=row["publora_post_id"]))
        if status == "published":
            self.db.run("UPDATE posts SET status='published', published_url=?, error=?, updated_at=? WHERE id=? "
                        "AND status='scheduled' AND trashed_at IS NULL",
                        (link, ("Publora says: " + "; ".join(words))[:1000] if words else None, utcnow(), post_id))
        elif status == "failed":
            self.db.run("UPDATE posts SET status='failed', error=?, updated_at=? WHERE id=? AND status='scheduled' "
                        "AND trashed_at IS NULL",
                        (("Publora says it failed: " + "; ".join(words))[:1000] if words else NO_REASON, utcnow(), post_id))
        return status


# The UI's entry points for a post with pictures or a carousel. Each of `pictures` is {"path", "name", "mime",
# "sha256"}; empty or None means none, which is the single-request flow. Results are shaped like Publisher.schedule's:
# {"ok": True, "postGroupId", "warnings"} or {"ok": False, "error", "step"}; a refusal before anything is sent raises
# ScheduleError.
def schedule_with_pictures(publisher: Publisher, post_id: int, local_when: str, first_comment: str | None,
                           pictures: list[dict] | None) -> dict:
    return publisher.schedule(post_id, local_when, first_comment, pictures or None)


def post_now_with_pictures(publisher: Publisher, post_id: int, first_comment: str | None,
                           pictures: list[dict] | None) -> dict:
    return publisher.post_now(post_id, first_comment, pictures or None)


def retry_with_pictures(publisher: Publisher, post_id: int, pictures: list[dict] | None) -> dict:
    return publisher.retry(post_id, pictures or None)
