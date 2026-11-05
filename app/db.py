"""SQLite storage at data/studio.db. One connection per call; WAL so reads never block.

Changes to the schema are additive and made in place when the app starts: a table or a column
that is missing is added, nothing is renamed or dropped, and every row stays as it was. What a
start changed is kept in `DB.started` (and the launcher's log says it).
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,            -- humanize, audit, plan, draft, revise, interview, voice, post_chat, ...
    status TEXT NOT NULL,          -- queued, running, done, unparsed, failed, cancelled
    progress TEXT,
    params TEXT NOT NULL,          -- JSON
    result TEXT,                   -- JSON parsed from the marker block
    raw_text TEXT,                 -- Claude's full reply, kept for retry/debugging
    error TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    acked INTEGER NOT NULL DEFAULT 0,  -- 1 once the user used, dismissed or cancelled it
    activity TEXT,                 -- JSON: the run's numbered steps
    steps INTEGER NOT NULL DEFAULT 0,
    last_step_at TEXT
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    job_id INTEGER,
    skill TEXT NOT NULL,
    started_at TEXT NOT NULL,
    duration_ms INTEGER,
    exit_code INTEGER,
    outcome TEXT,                  -- ok, unparsed, error, timeout, cancelled, refused
    num_turns INTEGER,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cache_read_tokens INTEGER,
    cache_creation_tokens INTEGER,
    cost_usd REAL,                 -- notional list price reported by the CLI
    session_id TEXT,
    skill_invoked INTEGER,
    denials INTEGER,
    error TEXT
);
-- The weekly plan's (plans, plan_items, posts.plan_item_id) went on 4 Nov 2026: a database from before keeps them, unused.
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    first_comment TEXT,
    formula TEXT,
    notes TEXT,                    -- JSON list from the writer
    audit TEXT,                    -- JSON from the last audit
    picture_ids TEXT,              -- JSON list of images.id going out with it, in order: pictures, or one carousel
    status TEXT NOT NULL,          -- draft, approved, scheduling, scheduled, published, failed, cancelled
    trashed_at TEXT,               -- set while the post is in the Trash; it keeps its status and all it has
    scheduled_at TEXT,             -- UTC ISO
    idempotency_key TEXT,
    publora_post_id TEXT,
    publora_payload TEXT,          -- exact JSON body sent, so a retry is byte-identical
    published_url TEXT,            -- the post on LinkedIn, once Publora gives its link (publishing.py)
    style TEXT,                    -- JSON: the post style it was restyled in (style.py); none: the owner's default
    queue_pos INTEGER,             -- its place in the posting queue (posting.py), while it is approved and waiting
    post_now INTEGER,              -- 1 once Post now sent it (publishing.py): Retry sends it after its time too
    rank INTEGER,                  -- how worth posting it is, 1-10 (rank.py); drafts list best first
    rank_note TEXT,                -- JSON: why, the one change that would lift it, and who gave the number
    news TEXT,                     -- JSON: the Hot topics item it was drafted from (hot.py): title, link, source, date
    error TEXT,
    media TEXT,                    -- JSON, with pictures or a carousel: the files, the postGroupId, each mediaId and upload URL
    media_step TEXT                -- with pictures or a carousel: next step (create, upload_url, put, update) or done
);
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY,
    mode TEXT NOT NULL,            -- bank, voice, post
    session_id TEXT,
    created_at TEXT NOT NULL,
    post_id INTEGER,               -- a post's own chat (mode 'post')
    cleared_at TEXT                -- set when the owner starts that chat afresh
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    conversation_id INTEGER NOT NULL,
    role TEXT NOT NULL,            -- user, assistant, info, error
    text TEXT NOT NULL,
    diff TEXT,
    job_id INTEGER,
    created_at TEXT NOT NULL,
    meta TEXT                      -- JSON: what a reply did (versions, pictures, an offer)
);
CREATE TABLE IF NOT EXISTS health (
    id INTEGER PRIMARY KEY,
    ran_at TEXT NOT NULL,
    script TEXT NOT NULL,
    exit_code INTEGER,
    output TEXT
);
CREATE TABLE IF NOT EXISTS versions (
    id INTEGER PRIMARY KEY,
    post_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    first_comment TEXT,
    author TEXT NOT NULL,          -- you, claude, studio
    note TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY,
    post_id INTEGER NOT NULL,
    file TEXT NOT NULL,            -- its name in the images folder beside the database
    source TEXT NOT NULL,          -- chatgpt, attached, or carousel (a PDF, one slide a page)
    prompt TEXT,
    shape TEXT,                    -- landscape (1200 x 627), square (1080 x 1080) or portrait (a carousel, 1080 x 1350)
    width INTEGER,
    height INTEGER,
    mime TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    job_id INTEGER,
    spec TEXT,                     -- a carousel's slides, as JSON (carousel.py), so it can be made again
    pages INTEGER,                 -- a carousel's slide count; each slide's picture is <file stem>-<n>.png
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hot (
    id INTEGER PRIMARY KEY CHECK (id = 1),   -- one row: the latest read of Hot topics (hot.py)
    fetched_at TEXT NOT NULL,
    topics TEXT NOT NULL,          -- JSON list: each item as hot.py keeps it, its text with it
    problems TEXT                  -- JSON list: the sources that gave nothing, and why
);
CREATE TABLE IF NOT EXISTS hot_ranks (
    id TEXT PRIMARY KEY,           -- a Hot topics item (hot.id_of its link)
    rank INTEGER NOT NULL,         -- 1-10: how good a post it makes for the owner (hot.RUBRIC)
    why TEXT,                      -- one line
    angle TEXT,                    -- the post it would become, one line
    same_as TEXT,                  -- the item it repeats (the same story from another source), if any
    ranked_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS spent (
    id INTEGER PRIMARY KEY,
    post_id INTEGER NOT NULL,      -- a published post, deleted forever from the Trash (api_trash.py)
    scheduled_at TEXT NOT NULL,    -- UTC ISO: Publora counted it in that month, so the month's count still does
    deleted_at TEXT NOT NULL
);
"""

# Columns added after the first release: (table, column, definition).
MIGRATIONS = [
    ("jobs", "acked", "INTEGER NOT NULL DEFAULT 0"),
    ("jobs", "activity", "TEXT"),                       # JSON: the run's numbered steps
    ("jobs", "steps", "INTEGER NOT NULL DEFAULT 0"),
    ("jobs", "last_step_at", "TEXT"),
    ("conversations", "post_id", "INTEGER"),            # a post's own chat (mode 'post')
    ("conversations", "cleared_at", "TEXT"),            # set when the owner starts that chat afresh
    ("messages", "meta", "TEXT"),                       # JSON: what a reply did (versions, pictures, an offer)
    ("posts", "media", "TEXT"),                         # JSON: a picture post's Publora steps (publishing.py)
    ("posts", "media_step", "TEXT"),                    # the step it reaches next
    ("posts", "trashed_at", "TEXT"),                    # in the Trash since then (api_trash.py)
    ("posts", "published_url", "TEXT"),                 # the post on LinkedIn, once Publora gives its link
    ("posts", "style", "TEXT"),                         # JSON: the post style it was restyled in (style.py)
    ("posts", "queue_pos", "INTEGER"),                  # its place in the posting queue (posting.py)
    ("posts", "picture_ids", "TEXT"),                   # JSON: what goes out with it, in order (images.py)
    ("images", "spec", "TEXT"),                         # JSON: a carousel's slides (carousel.py)
    ("images", "pages", "INTEGER"),                     # a carousel's slide count
    ("posts", "rank", "INTEGER"),                       # how worth posting it is, 1-10 (rank.py)
    ("posts", "rank_note", "TEXT"),                     # JSON: why, what would lift it, who gave it
    ("posts", "news", "TEXT"),                          # JSON: the Hot topics item it was drafted from (hot.py)
    ("posts", "post_now", "INTEGER"),                   # 1 once Post now sent it (publishing.py)
]


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DB:
    def __init__(self, path: Path):
        self.path = path
        self._rev = 0
        self._rev_lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        changed: dict[str, Any] = {"tables": [], "columns": [], "jobs_stopped": 0, "posts_interrupted": 0}
        with self.connect() as con:
            con.execute("PRAGMA journal_mode=WAL")
            before = {r["name"] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            con.executescript(SCHEMA)
            after = {r["name"] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            changed["tables"] = sorted(after - before)
            for table, column, definition in MIGRATIONS:
                if column not in {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
                    changed["columns"].append(f"{table}.{column}")
            # Before 3 Nov 2026 a post had one picture, posts.picture_id: it becomes the first (and only) of picture_ids.
            if "picture_id" in {r["name"] for r in con.execute("PRAGMA table_info(posts)")}:
                con.execute("UPDATE posts SET picture_ids=json_array(picture_id), picture_id=NULL WHERE picture_id IS NOT NULL")
            # Anything left in flight by a previous run can never finish now.
            changed["jobs_stopped"] = con.execute(
                "UPDATE jobs SET status='failed', error='The app stopped before this finished.', finished_at=? "
                "WHERE status IN ('queued','running')", (utcnow(),)).rowcount
            # A picture post takes several Publora steps; stopped between them, it may sit on Publora as a draft.
            # Failed, it shows the owner what happened and offers Retry from the step it reached.
            changed["posts_interrupted"] = con.execute(
                "UPDATE posts SET status='failed', error='The app stopped while scheduling this post and its picture. "
                "Publora may hold it as an unscheduled draft: Retry finishes it.', updated_at=? "
                "WHERE status='scheduling' AND media_step IS NOT NULL", (utcnow(),)).rowcount
        self.started = changed

    @property
    def rev(self) -> int:
        """A number that changes whenever something the page shows was written."""
        return self._rev

    def _bump(self) -> None:
        with self._rev_lock:
            self._rev += 1

    def touch(self) -> None:
        """Something the page shows changed outside the database (the light check's words): the page asks again."""
        self._bump()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        con.row_factory = sqlite3.Row
        try:
            yield con
        finally:
            con.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """BEGIN IMMEDIATE: takes the write lock up front, so check-then-update is atomic."""
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                yield con
            except BaseException:
                con.execute("ROLLBACK")
                raise
            con.execute("COMMIT")
        self._bump()

    def one(self, sql: str, args: tuple = ()) -> sqlite3.Row | None:
        with self.connect() as con:
            return con.execute(sql, args).fetchone()

    def all(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self.connect() as con:
            return con.execute(sql, args).fetchall()

    def run(self, sql: str, args: tuple = (), *, quiet: bool = False) -> int:
        """One write. `quiet`: a job's progress, which the page reads from the jobs it polls anyway."""
        with self.connect() as con:
            cur = con.execute(sql, args)
            result = cur.lastrowid if sql.lstrip().upper().startswith("INSERT") else cur.rowcount
        if not quiet:
            self._bump()
        return result


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def loads(text: str | None, default: Any = None) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default
