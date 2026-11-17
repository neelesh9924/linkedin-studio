"""A post's versions: its text (and first comment) as it was at each change, to go back to.

A version is kept when Claude changes the post (a chat request, a revision used, a first draft)
and, just before that, the owner's own edits since the last version, so going back never loses
what they typed. The owner's own edits are kept by themselves too: when they leave the text
(checkpoint), before a save that takes away a third or more of it (big_cut), and when they approve
it. Going back is a change too: it is kept, so it can be undone, and the post's chat says it in one
line (api_posts). The gear lists each earlier version with its words compared with now (render.wdiff).
"""
from __future__ import annotations

from .db import DB, utcnow

AUTHORS = ("you", "claude", "studio")
CUT_SHARE = 3        # a save that takes away 1/CUT_SHARE of the text or more keeps the text before it first
CUT_LEAST = 20       # ... and at least this many characters: a few letters off a short line are not worth a version


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


def checkpoint(db: DB, post_id: int) -> int | None:
    """The owner left the text after typing: keep it as their version when it differs from the latest one."""
    post = db.one("SELECT text, first_comment FROM posts WHERE id=?", (post_id,))
    if post is None:
        return None
    return record(db, post_id, post["text"], post["first_comment"], "you", "Your edits")


def big_cut(before: str, after: str) -> bool:
    """Whether a save takes away a third or more of the text: what lies between the part both keep at the start and
    the part both keep at the end (select-all and one key takes it all)."""
    before, after = before or "", after or ""
    most = min(len(before), len(after))
    start = 0
    while start < most and before[start] == after[start]:
        start += 1
    end = 0
    while end < most - start and before[-1 - end] == after[-1 - end]:
        end += 1
    gone = len(before) - start - end
    return gone >= CUT_LEAST and gone * CUT_SHARE >= len(before)


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
