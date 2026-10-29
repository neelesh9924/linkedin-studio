"""The posting queue: the owner's posting times (Settings › Posting times) and the approved posts waiting for them.

A queued post is an approved one with a place in line (posts.queue_pos). In line order, each takes the next free
posting time: a time on one of the posting days, at least LEAD away, on a day no other post goes out (one post a day
at most), in a month that still has room under the monthly limit. A queued post's time is never stored: it is worked
out again each time it is asked for (`lineup`), so the line moves up by itself when a post leaves it, and a day that
passed with nobody in line is simply gone.

A queued post goes to Publora by itself once its time is within the window the studio schedules in (MAX_AHEAD), through
the same Publisher.schedule as Schedule… (one transaction, one keyed request), and leaves the line as it is claimed.
That happens when the owner queues a post or changes the posting times, and in the background while the studio runs:
/api/state kicks a pass at most every minute, one pass at a time, only with check_publora (as the light check), and
never during setup. A post already at Publora keeps its time; Cancel on Publora frees its day for the next in line.

The posting times are kept beside the database (posting.json, as style.json is).
"""
from __future__ import annotations

import json
import logging
import re
import threading
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from . import images
from .db import DB, utcnow
from .publishing import COUNTED, MAX_AHEAD, MIN_LEAD, Publisher, ScheduleError
from .render import local_time

log = logging.getLogger("studio.posting")

FILE = "posting.json"
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
NAMES = {"mon": "Monday", "tue": "Tuesday", "wed": "Wednesday", "thu": "Thursday", "fri": "Friday", "sat": "Saturday",
         "sun": "Sunday"}
DEFAULT = {"tue": "08:00", "wed": "09:30", "thu": "08:00"}   # the mornings the skills recommend
LEAD = MIN_LEAD + timedelta(minutes=5)       # a time closer than this is passed over
SEND_MARGIN = timedelta(minutes=10)          # sent once its time is this much inside MAX_AHEAD
HORIZON = 400                                # days ahead a queued post looks for a free time
EVERY = timedelta(minutes=1)                 # the background pass, at most this often
TAKES_ITS_DAY = (*COUNTED, "failed")         # a post with a time keeps that day from the queue (failed: Try again)
_TIME = re.compile(r"([01]?\d|2[0-3]):([0-5]\d)")


class Refused(ValueError):
    """Posting times the page cannot have sent; the message says what, in the page's words."""


# ---- the posting times --------------------------------------------------------------------------------------------
def clean(data) -> dict[str, str]:
    """{"tue": "08:00", ...} from what the page sent: days by their first three letters, times as HH:MM, a day left
    out or empty is not a posting day. At least one day."""
    if not isinstance(data, dict):
        raise Refused("Send the posting times.")
    out = {}
    for day, value in data.items():
        if day not in DAYS:
            raise Refused(f"There is no day called {day}.")
        if value in (None, "", False):
            continue
        found = _TIME.fullmatch(str(value).strip())
        if not found:
            raise Refused(f"{NAMES[day]}: give its time as hours and minutes, such as 08:30.")
        out[day] = f"{int(found[1]):02d}:{found[2]}"
    if not out:
        raise Refused("Pick at least one posting day.")
    return {d: out[d] for d in DAYS if d in out}


def path(db: DB) -> Path:
    return db.path.parent / FILE


def times(db: DB) -> dict[str, str]:
    """The owner's posting times from Settings, or the studio's own when none are saved."""
    try:
        return clean(json.loads(path(db).read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return dict(DEFAULT)


def save(db: DB, data) -> dict[str, str]:
    chosen = clean(data)
    path(db).write_text(json.dumps(chosen), encoding="utf-8")
    return chosen


def clock_words(hhmm: str) -> str:
    """"08:00" as "8:00 am"."""
    hour, minute = map(int, hhmm.split(":"))
    return f"{hour % 12 or 12}:{minute:02d} {'am' if hour < 12 else 'pm'}"


def words(chosen: dict[str, str]) -> str:
    """The posting times in a line: "Tue 8:00 am, Wed 9:30 am and Thu 8:00 am"."""
    each = [f"{NAMES[d][:3]} {clock_words(t)}" for d, t in chosen.items()]
    return each[0] if len(each) == 1 else f"{', '.join(each[:-1])} and {each[-1]}"


def picture_of(db: DB, row) -> dict | None:
    """The post's chosen picture as publishing.py takes it: {path, name, mime, sha256}; None for none."""
    if not row["picture_id"]:
        return None
    image = db.one("SELECT * FROM images WHERE id=? AND post_id=?", (row["picture_id"], row["id"]))
    found = images.path_of(db, image)
    if found is None:
        raise ScheduleError("The post's picture is missing from the images folder. Take it off the post, or choose another.")
    return {"path": str(found), "name": f"linkedin-studio-{row['id']}-{image['id']}{found.suffix}", "mime": image["mime"],
            "sha256": image["sha256"]}


# ---- the line -----------------------------------------------------------------------------------------------------
WAITING = "status='approved' AND queue_pos IS NOT NULL AND trashed_at IS NULL"


class PostingQueue:
    def __init__(self, db: DB, pub: Publisher, *, enabled: bool = False, every: timedelta = EVERY,
                 now: Callable[[], datetime] | None = None):
        self.db, self.pub, self.cfg, self.enabled, self.every = db, pub, pub.cfg, enabled, every
        self.now = now or pub.now
        self.lock = threading.Lock()        # one pass at a time: the line is worked out and sent under it
        self._kick = threading.Lock()
        self._thread: threading.Thread | None = None
        self._last: datetime | None = None

    def times(self) -> dict[str, str]:
        return times(self.db)

    def _free_times(self, now: datetime):
        """The free posting times from now on, earliest first (aware UTC), each kept from the next as it is given."""
        tz, chosen, limit = self.cfg.tz, self.times(), self.cfg.monthly_post_limit
        taken: set[date] = set()
        months: Counter = Counter()
        for row in self.db.all(f"SELECT status, scheduled_at FROM posts WHERE trashed_at IS NULL AND scheduled_at IS NOT NULL "
                               f"AND status IN ({','.join('?' * len(TAKES_ITS_DAY))})", TAKES_ITS_DAY):
            try:
                local = datetime.fromisoformat(row["scheduled_at"].replace("Z", "+00:00")).astimezone(tz)
            except ValueError:
                continue
            taken.add(local.date())
            if row["status"] in COUNTED:
                months[(local.year, local.month)] += 1
        first = now.astimezone(tz).date()
        for ahead in range(HORIZON):
            day = first + timedelta(days=ahead)
            at_time = chosen.get(DAYS[day.weekday()])
            if at_time is None or day in taken or months[(day.year, day.month)] >= limit:
                continue
            hour, minute = map(int, at_time.split(":"))
            at = datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz).astimezone(timezone.utc)
            if at < now + LEAD:
                continue
            taken.add(day)
            months[(day.year, day.month)] += 1
            yield at

    def _line(self, free) -> list[tuple[int, datetime | None]]:
        return [(r["id"], next(free, None)) for r in self.db.all(f"SELECT id FROM posts WHERE {WAITING} ORDER BY queue_pos, id")]

    def lineup(self, now: datetime | None = None) -> list[tuple[int, datetime | None]]:
        """The queued posts in line order, each with the time it takes (None: no free time within HORIZON days)."""
        return self._line(self._free_times(now or self.now()))

    def coming(self, now: datetime | None = None) -> tuple[list[tuple[int, datetime | None]], list[datetime]]:
        """The line, and the free posting times left within MAX_AHEAD after it: the Planner's Coming up."""
        now = now or self.now()
        free = self._free_times(now)
        line = self._line(free)
        left = []
        for at in free:
            if at > now + MAX_AHEAD:
                break
            left.append(at)
        return line, left

    def next_free(self, count: int = 4, now: datetime | None = None) -> list[datetime]:
        """The first free posting times after the line, within MAX_AHEAD: Schedule…'s recommended times."""
        return self.coming(now)[1][:count]

    # ---- the owner's changes ----
    def add(self, post_id: int) -> bool:
        """At the end of the line. False when the post is not an approved one out of the line."""
        return self.db.run("UPDATE posts SET queue_pos=(SELECT COALESCE(MAX(queue_pos), 0) + 1 FROM posts), updated_at=? "
                           "WHERE id=? AND status='approved' AND queue_pos IS NULL AND trashed_at IS NULL",
                           (utcnow(), post_id)) == 1

    def take_out(self, post_id: int) -> bool:
        """Out of the line, still approved. False when it was not in it."""
        return self.db.run(f"UPDATE posts SET queue_pos=NULL, error=NULL, updated_at=? WHERE id=? AND {WAITING}",
                           (utcnow(), post_id)) == 1

    def move(self, post_id: int, how: str) -> bool:
        """One place up or down, or to the front of the line. False when it cannot move that way."""
        with self.db.transaction() as con:
            line = [r["id"] for r in con.execute(f"SELECT id FROM posts WHERE {WAITING} ORDER BY queue_pos, id")]
            if post_id not in line:
                return False
            at = line.index(post_id)
            to = {"up": at - 1, "down": at + 1, "first": 0}.get(how, at)
            if to == at or not 0 <= to < len(line):
                return False
            line.insert(to, line.pop(at))
            for place, pid in enumerate(line, start=1):
                con.execute("UPDATE posts SET queue_pos=? WHERE id=?", (place, pid))
        return True

    # ---- going to Publora ----
    def send_due(self) -> list[dict]:
        """Hand each queued post whose time is within the window to Publora, in line order. What happened to each one
        sent or refused: {"id", "ok", "error"}. A refusal before anything was sent (no key, a missing picture) stays on
        the post as its error, and the post stays in line."""
        out = []
        with self.lock:
            now = self.now()
            for post_id, at in self.lineup(now):
                if at is None or at > now + MAX_AHEAD - SEND_MARGIN:
                    break
                out.append(self._send(post_id, at))
        return out

    def _send(self, post_id: int, at: datetime) -> dict:
        row = self.db.one("SELECT * FROM posts WHERE id=?", (post_id,))
        try:
            result = self.pub.schedule(post_id, at.astimezone(self.cfg.tz).strftime("%Y-%m-%dT%H:%M"), row["first_comment"],
                                       picture_of(self.db, row))
        except ScheduleError as exc:
            said = f"Not at Publora yet: {exc} The studio tries again by itself."
            if row["error"] != said:              # the same refusal again writes nothing, so the page is not redrawn
                self.db.run("UPDATE posts SET error=? WHERE id=? AND status='approved'", (said, post_id))
            return {"id": post_id, "ok": False, "error": str(exc), "sent": False}
        return {"id": post_id, "ok": bool(result.get("ok")), "error": result.get("error", ""), "sent": True}

    def kick(self) -> bool:
        """A background pass, when one is allowed and due: returns at once, whether it started."""
        if not self.enabled:
            return False
        now = self.now()
        with self._kick:
            if self._thread is not None and self._thread.is_alive():
                return False
            if self._last is not None and now - self._last < self.every:
                return False
            if self.db.one(f"SELECT 1 FROM posts WHERE {WAITING}") is None:
                return False
            self._last = now
            self._thread = threading.Thread(target=self._pass, name="posting-queue", daemon=True)
            self._thread.start()
        return True

    def _pass(self) -> None:
        try:
            self.send_due()
        except Exception:  # noqa: BLE001  (the next pass tries again)
            log.exception("The posting queue could not finish a pass")

    def wait(self, timeout: float = 10) -> None:
        """Until the background pass under way (if any) is done: for tests."""
        thread = self._thread
        if thread is not None:
            thread.join(timeout)


def time_words(at: datetime | None, tz: Any, label: str = "") -> str:
    """A queued post's time as the page shows times (render.local_time), or "" for none."""
    return local_time(at.isoformat(timespec="seconds"), tz, label) if at else ""
