"""Publishing through linkedin-skills\\lib\\publora_client.py, with exactly-once scheduling.

State machine: draft -> approved -> scheduling -> scheduled -> published | failed | cancelled.
The approved -> scheduling step is one BEGIN IMMEDIATE transaction, so a double-click or
a second tab finds the post already claimed and never reaches Publora. The one HTTP call
carries an Idempotency-Key stored with the post, and a retry after an unclear failure
resends the identical body with the same key, which Publora replays instead of re-posting.
"""
from __future__ import annotations

import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from dotenv import dotenv_values

from .config import Config
from .db import DB, dumps, loads, utcnow

MIN_LEAD = timedelta(minutes=2)
MAX_AHEAD = timedelta(days=14)
COUNTED = ("scheduling", "scheduled", "published")
FIRST_COMMENT_MAX = 1250
POST_MAX = 3000
DASHBOARD_URL = "https://app.publora.com"


class ScheduleError(RuntimeError):
    pass


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
    """PubloraClient from the skills repo plus one method: a single create-post with an Idempotency-Key."""
    global _CLIENT_CLASS
    if _CLIENT_CLASS is None:
        publora = _lib(cfg)

        class StudioPublora(publora.PubloraClient):
            def create_post_once(self, payload: dict, idempotency_key: str) -> dict:
                # One request, no retry loop (the client's own _post retries without a key).
                r = self._session.post(self.BASE_URL + "/create-post", json=payload,
                                       headers={"Idempotency-Key": idempotency_key}, timeout=self.timeout)
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
        n = self.db.run("UPDATE posts SET status='draft', idempotency_key=NULL, publora_payload=NULL, "
                        "scheduled_at=NULL, error=NULL, updated_at=? WHERE id=? AND publora_post_id IS NULL "
                        "AND status IN ('approved','failed')", (utcnow(), post_id))
        if n != 1:
            raise ScheduleError("Only an approved post, or one whose scheduling failed, can go back to draft.")

    def schedule(self, post_id: int, local_when: str, first_comment: str | None) -> dict:
        when = self.parse_local(local_when)
        comment = (first_comment or "").strip() or None
        if comment and len(comment) > FIRST_COMMENT_MAX:
            raise ScheduleError(f"The first comment is {len(comment)} characters; LinkedIn allows {FIRST_COMMENT_MAX}.")
        client = self.client_factory()
        platform_id = self.platform_id(client)
        with self.db.transaction() as con:
            row = con.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
            if row is None:
                raise ScheduleError("No such post.")
            if row["publora_post_id"]:
                raise ScheduleError("This post already exists on Publora; it will not be sent again.")
            if row["status"] != "approved":
                raise ScheduleError(f"Only an approved post can be scheduled; this one is {row['status']}.")
            used = self.quota_used(when, con)
            if used >= self.cfg.monthly_post_limit:
                raise ScheduleError(f"Monthly limit reached: {used}/{self.cfg.monthly_post_limit} posts are already "
                                    f"scheduled or published in {when.astimezone(self.cfg.tz):%B %Y}.")
            payload: dict[str, Any] = {"content": row["text"], "platforms": [platform_id],
                                       "scheduledTime": when.strftime("%Y-%m-%dT%H:%M:%SZ")}
            if comment:
                payload["firstComment"] = {"text": comment, "platforms": ["linkedin"]}
            key = f"linkedin-studio-{post_id}-{uuid.uuid4().hex}"
            con.execute("UPDATE posts SET status='scheduling', scheduled_at=?, idempotency_key=?, publora_payload=?, "
                        "first_comment=?, error=NULL, updated_at=? WHERE id=? AND status='approved' "
                        "AND publora_post_id IS NULL",
                        (utc_iso(when), key, dumps(payload), comment, utcnow(), post_id))
        return self._send(post_id, client, payload, key)

    def retry(self, post_id: int) -> dict:
        """Resend the identical body with the same key after a failed schedule call."""
        with self.db.transaction() as con:
            row = con.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
            if row is None or row["status"] != "failed" or row["publora_post_id"] or not row["publora_payload"]:
                raise ScheduleError("Only a post whose schedule call failed can be retried.")
            when = parse_utc(row["scheduled_at"])
            if when < self.now() + MIN_LEAD:
                raise ScheduleError("The scheduled time has passed. Move it back to draft and pick a new time.")
            used = self.quota_used(when, con)
            if used >= self.cfg.monthly_post_limit:
                raise ScheduleError("Monthly limit reached.")
            con.execute("UPDATE posts SET status='scheduling', error=NULL, updated_at=? WHERE id=? AND status='failed'",
                        (utcnow(), post_id))
            payload, key = loads(row["publora_payload"]), row["idempotency_key"]
        return self._send(post_id, self.client_factory(), payload, key)

    def _send(self, post_id: int, client: Any, payload: dict, key: str) -> dict:
        try:
            resp = client.create_post_once(payload, key)
        except Exception as exc:  # PubloraError, timeouts, connection errors
            msg = str(exc)
            if "Timeout" in type(exc).__name__ or "Connection" in type(exc).__name__:
                msg = (f"No answer from Publora ({type(exc).__name__}). It may or may not have created the post: "
                       "check the Publora dashboard, then use Retry (it cannot create a second copy).")
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
