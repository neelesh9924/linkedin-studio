"""The light check: did a scheduled post whose time has passed go out? Publora is asked in the background.

/api/state kicks it with the posts it read, and never waits for it. One check runs at a time and at most every few
minutes (EVERY), only when a scheduled post's time has passed, never while the studio still needs its setup, and never
for a post in the Trash. It only reads (Publisher.refresh, which sends get-post and nothing else). A check that fails
stays quiet: when and why are kept here, in memory, for the post's notice, and the next check tries again. Check now
(the post's top bar) asks at once through `check`, into the same memory.

It is off unless create_app is given check_publora=True (launch.py, `python -m app` and the demo turn it on): the
tests' studios hold a stand-in key and posts dated in the past, and must never reach the real Publora.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable

from .db import DB
from .publishing import Publisher, parse_utc, unclear_failure

EVERY = timedelta(minutes=3)


def failure_words(exc: Exception) -> str:
    """Why asking Publora failed, short: the post's notice and Check now say it."""
    if unclear_failure(exc):
        return f"no answer ({type(exc).__name__})"
    return " ".join(str(exc).split())[:300] or type(exc).__name__


class StatusCheck:
    def __init__(self, db: DB, pub: Publisher, *, enabled: bool = False, every: timedelta = EVERY,
                 now: Callable[[], datetime] | None = None):
        self.db, self.pub, self.enabled, self.every = db, pub, enabled, every
        self.now = now or (lambda: datetime.now(timezone.utc))
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._last: datetime | None = None                    # when the last light check began
        self._asked: dict[int, datetime] = {}                  # post -> when Publora last answered about it
        self._failed: dict[int, tuple[datetime, str]] = {}     # post -> when, and why, the last ask failed

    @staticmethod
    def due(rows: Iterable[Any], now: datetime) -> list[int]:
        """The scheduled posts whose time has passed, of these rows (never one in the Trash)."""
        out = []
        for r in rows:
            if r["status"] != "scheduled" or not r["publora_post_id"] or r["trashed_at"] or not r["scheduled_at"]:
                continue
            try:
                if parse_utc(r["scheduled_at"]) <= now:
                    out.append(r["id"])
            except ValueError:
                continue
        return out

    def kick(self, rows: Iterable[Any]) -> bool:
        """Start a light check in the background when one is due and allowed. Returns at once: whether it started."""
        if not self.enabled:
            return False
        now = self.now()
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            if self._last is not None and now - self._last < self.every:
                return False
            ids = self.due(rows, now)
            if not ids:
                return False
            self._last = now
            self._thread = threading.Thread(target=self._run, args=(ids,), name="publora-check", daemon=True)
            self._thread.start()
        return True

    def wait(self, timeout: float = 10) -> None:
        """Until the light check under way (if any) is done: for tests."""
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def _run(self, ids: list[int]) -> None:
        for post_id in ids:
            try:
                self.check(post_id)
            except Exception:  # noqa: BLE001  (kept for the post's notice; the next check tries again)
                pass

    def check(self, post_id: int) -> str:
        """Ask Publora about one post now and remember how it went. Raises what Publisher.refresh raised."""
        try:
            status = self.pub.refresh(post_id)
        except Exception as exc:
            with self._lock:
                self._failed[post_id] = (self.now(), failure_words(exc))
            self.db.touch()
            raise
        with self._lock:
            self._failed.pop(post_id, None)
            if status == "scheduled":
                self._asked[post_id] = self.now()
            else:
                self._asked.pop(post_id, None)
        self.db.touch()
        return status

    def last_failure(self, post_id: int) -> str:
        with self._lock:
            failed = self._failed.get(post_id)
        return failed[1] if failed else ""

    def notice(self, post_id: int, clock: Callable[[str], str]) -> dict | None:
        """What a due scheduled post's notice says about the light check: its last ask failed (when, and Publora's or
        the network's words), or when Publora last said it was still waiting, or that it will be asked."""
        with self._lock:
            failed, asked = self._failed.get(post_id), self._asked.get(post_id)
        if failed:
            return {"failed": True, "text": f"The studio could not ask Publora at {clock(failed[0].isoformat())} "
                                            f"({failed[1]}). It tries again every few minutes; Check now asks at once."}
        if asked:
            return {"failed": False, "text": f"Not out yet as of {clock(asked.isoformat())}: Publora still has it "
                                             "scheduled. The studio asks again every few minutes."}
        return {"failed": False, "text": "Its time has passed: the studio asks Publora every few minutes whether it went "
                                         "out. Check now asks at once."}
