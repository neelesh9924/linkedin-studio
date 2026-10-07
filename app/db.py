"""SQLite storage at data/studio.db. One connection per call; WAL so reads never block."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,            -- humanize, audit, plan, draft, revise, interview, ...
    status TEXT NOT NULL,          -- queued, running, done, unparsed, failed, cancelled
    progress TEXT,
    params TEXT NOT NULL,          -- JSON
    result TEXT,                   -- JSON parsed from the marker block
    raw_text TEXT,                 -- Claude's full reply, kept for retry/debugging
    error TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    acked INTEGER NOT NULL DEFAULT 0   -- 1 once the user used, dismissed or cancelled it
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
CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    inputs TEXT NOT NULL,          -- JSON
    result TEXT NOT NULL           -- JSON from the planner
);
CREATE TABLE IF NOT EXISTS plan_items (
    id INTEGER PRIMARY KEY,
    plan_id INTEGER NOT NULL,
    position INTEGER NOT NULL,
    data TEXT NOT NULL,            -- JSON: day, time, pillar, format, formula, angle, cta, goal
    post_id INTEGER
);
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    plan_item_id INTEGER,
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    first_comment TEXT,
    formula TEXT,
    notes TEXT,                    -- JSON list from the writer
    audit TEXT,                    -- JSON from the last audit
    status TEXT NOT NULL,          -- draft, approved, scheduling, scheduled, published, failed, cancelled
    scheduled_at TEXT,             -- UTC ISO
    idempotency_key TEXT,
    publora_post_id TEXT,
    publora_payload TEXT,          -- exact JSON body sent, so a retry is byte-identical
    error TEXT
);
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY,
    mode TEXT NOT NULL,            -- bank, voice
    session_id TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    conversation_id INTEGER NOT NULL,
    role TEXT NOT NULL,            -- user, assistant
    text TEXT NOT NULL,
    diff TEXT,
    job_id INTEGER,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS health (
    id INTEGER PRIMARY KEY,
    ran_at TEXT NOT NULL,
    script TEXT NOT NULL,
    exit_code INTEGER,
    output TEXT
);
"""


# Columns added after the first release: (table, column, definition).
MIGRATIONS = [("jobs", "acked", "INTEGER NOT NULL DEFAULT 0")]


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DB:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript(SCHEMA)
            for table, column, definition in MIGRATIONS:
                if column not in {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            # Anything left in flight by a previous run can never finish now.
            con.execute("UPDATE jobs SET status='failed', error='The app stopped before this finished.', "
                        "finished_at=? WHERE status IN ('queued','running')", (utcnow(),))

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

    def one(self, sql: str, args: tuple = ()) -> sqlite3.Row | None:
        with self.connect() as con:
            return con.execute(sql, args).fetchone()

    def all(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self.connect() as con:
            return con.execute(sql, args).fetchall()

    def run(self, sql: str, args: tuple = ()) -> int:
        with self.connect() as con:
            cur = con.execute(sql, args)
            return cur.lastrowid if sql.lstrip().upper().startswith("INSERT") else cur.rowcount


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def loads(text: str | None, default: Any = None) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default
