"""A post's versions: its text (and first comment) as it was at each change, to go back to.

A version is kept when Claude changes the post (a chat request, a revision used, a first draft)
and, just before that, the owner's own edits since the last version, so going back never loses
what they typed. Going back is a change too: it is kept, so it can be undone.
"""
from __future__ import annotations

from .db import DB, utcnow

AUTHORS = ("you", "claude", "studio")


def latest(db: DB, post_id: int):
    return db.one("SELECT * FROM versions WHERE post_id=? ORDER BY id DESC LIMIT 1", (post_id,))


def record(db: DB, post_id: int, text: str, first_comment: str | None, author: str, note: str = "") -> int | None:
    """Keep this text as a version, unless it is what the latest version already holds. Returns its id, or None."""
    if author not in AUTHORS:
        raise ValueError(f"unknown author {author!r}")
    text = text or ""
    first_comment = first_comment or None
    last = latest(db, post_id)
    if last is not None and (last["text"], last["first_comment"]) == (text, first_comment):
        return None
    if last is None and not text.strip() and not first_comment:
        return None   # an empty new draft is not worth a version
    return db.run("INSERT INTO versions (post_id, text, first_comment, author, note, created_at) VALUES (?,?,?,?,?,?)",
                  (post_id, text, first_comment, author, (note or "").strip()[:200] or None, utcnow()))


def catch_up(db: DB, post_id: int) -> int | None:
    """Keep the owner's edits since the last version, before something else changes the post."""
    post = db.one("SELECT text, first_comment FROM posts WHERE id=?", (post_id,))
    if post is None:
        return None
    note = "Your edits" if latest(db, post_id) is not None else "As it was"
    return record(db, post_id, post["text"], post["first_comment"], "you", note)


def listing(db: DB, post_id: int) -> list:
    return db.all("SELECT * FROM versions WHERE post_id=? ORDER BY id DESC", (post_id,))


class VersionError(RuntimeError):
    pass


def go_back(db: DB, post_id: int, version_id: int) -> bool:
    """Put a version's text back on a draft. Returns whether the text changed. The text before is kept first."""
    version = db.one("SELECT * FROM versions WHERE id=? AND post_id=?", (version_id, post_id))
    if version is None:
        raise VersionError("That version is not this post's.")
    post = db.one("SELECT * FROM posts WHERE id=?", (post_id,))
    if post is None or post["status"] != "draft":
        raise VersionError("Only a draft can go back to a version. Move it back to draft first.")
    if (post["text"], post["first_comment"]) == (version["text"], version["first_comment"]):
        return False
    catch_up(db, post_id)
    db.run("UPDATE posts SET text=?, first_comment=?, updated_at=? WHERE id=? AND status='draft'",
           (version["text"], version["first_comment"], utcnow(), post_id))
    record(db, post_id, version["text"], version["first_comment"], "studio", f"Went back to version {version_id}")
    return True
