"""The Trash: the posts the owner moved there (the gear's Move to Trash…, api_posts.py), until they put one back or
delete it forever, as in the owner's other studios.

A post in the Trash is the same row with `trashed_at` set: its state, versions, chat, pictures and plan link stay as
they were, the list and every endpoint of a post leave it out, and Put back returns all of it. Delete forever (one
post, or Empty trash) needs `confirmed` and takes everything of it from this computer: its versions, chats, picture
rows and its chat's attached files; a picture file another post still uses stays, and its plan item is free again.
Scheduled and published posts never get here (Publora has them), so nothing here touches Publora or the month's count.
"""
from __future__ import annotations

import shutil
from typing import Any

from fastapi import Body, FastAPI

from . import attached, images
from .api_posts import fail
from .db import DB
from .main import STATUS_KIND, STATUS_LABEL, Studio, first_line

MAX_IDS = 1000


def delete_forever(db: DB, post_id: int) -> bool:
    """Delete one post of the Trash and everything of it. False when it is not in the Trash (put back meanwhile)."""
    with db.transaction() as con:
        row = con.execute("SELECT trashed_at FROM posts WHERE id=?", (post_id,)).fetchone()
        if row is None or not row["trashed_at"]:
            return False
        files = [r["file"] for r in con.execute("SELECT file FROM images WHERE post_id=?", (post_id,)).fetchall()]
        con.execute("UPDATE plan_items SET post_id=NULL WHERE post_id=?", (post_id,))
        con.execute("DELETE FROM versions WHERE post_id=?", (post_id,))
        con.execute("DELETE FROM images WHERE post_id=?", (post_id,))
        for conv in con.execute("SELECT id FROM conversations WHERE mode='post' AND post_id=?", (post_id,)).fetchall():
            con.execute("DELETE FROM messages WHERE conversation_id=?", (conv["id"],))
        con.execute("DELETE FROM conversations WHERE mode='post' AND post_id=?", (post_id,))
        # SQLite may give a later post this id again: its old jobs must not show on that one (a problem, a revision).
        con.execute("UPDATE jobs SET acked=1 WHERE json_extract(params, '$.post_id')=?", (post_id,))
        con.execute("DELETE FROM posts WHERE id=? AND trashed_at IS NOT NULL", (post_id,))
    for name in set(files):   # a picture's file goes once no other post's picture is the same file
        if db.one("SELECT 1 FROM images WHERE file=?", (name,)) is None:
            path = images.path_of(db, {"file": name})
            if path:
                path.unlink(missing_ok=True)
    shutil.rmtree(attached.folder(db, f"post-{post_id}"), ignore_errors=True)   # what was attached in its chat
    return True


def register(app: FastAPI, s: Studio) -> None:
    db = s.db

    def entry(row, counts: dict[int, int]) -> dict[str, Any]:
        picture = db.one("SELECT * FROM images WHERE id=? AND post_id=?", (row["picture_id"], row["id"])) \
            if row["picture_id"] else None
        return {"id": row["id"], "title": row["title"], "first": first_line(row["text"]) or "Nothing written yet",
                "status": row["status"], "label": STATUS_LABEL.get(row["status"], row["status"]),
                "kind": STATUS_KIND.get(row["status"], ""), "removed": row["trashed_at"],
                "when": s.when(row["trashed_at"]), "ago": s.ago(row["trashed_at"]),
                "chars": len(row["text"] or ""), "versions": counts.get(row["id"], 0),
                "picture": images.public(picture, row["picture_id"]) if picture else None}

    def in_trash() -> list:
        return db.all("SELECT * FROM posts WHERE trashed_at IS NOT NULL ORDER BY trashed_at DESC, id DESC")

    @app.get("/api/trash")
    def trash_list():
        """What is in the Trash, newest first: each post as it was when it went there."""
        counts = {r["post_id"]: r["n"] for r in db.all(
            "SELECT post_id, COUNT(*) AS n FROM versions WHERE post_id IN (SELECT id FROM posts WHERE trashed_at IS NOT NULL) "
            "GROUP BY post_id")}
        return {"entries": [entry(r, counts) for r in in_trash()]}

    @app.post("/api/trash/back")
    def trash_back(data: dict = Body(default={})):
        """Put back: the post returns to the list as it was (its state, versions, chat, pictures and plan link)."""
        post_id = data.get("id")
        if not isinstance(post_id, int) or isinstance(post_id, bool):
            return fail("Bad request.")
        row = db.one("SELECT * FROM posts WHERE id=?", (post_id,))
        if row is None or not row["trashed_at"]:
            return fail("That is no longer in the Trash.", 404)
        db.run("UPDATE posts SET trashed_at=NULL WHERE id=? AND trashed_at IS NOT NULL", (post_id,))
        return {"ok": True, "id": post_id, "post": s.post_summary(db.one("SELECT * FROM posts WHERE id=?", (post_id,)))}

    @app.post("/api/trash/delete")
    def trash_delete(data: dict = Body(default={})):
        """Delete forever (ids) and Empty trash (all), once the owner confirmed: what the Trash showed them, no more.
        Empty trash with the ids it showed is refused when the Trash has changed since."""
        if data.get("confirmed") is not True:
            return fail("Deleting forever needs your confirmation first: it can't be undone.", 409)
        everything = data.get("all") is True
        ids = data.get("ids")
        there = [r["id"] for r in in_trash()]
        if ids is None and everything:
            chosen = there
        else:
            if (not isinstance(ids, list) or not ids or len(ids) > MAX_IDS
                    or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids)):
                return fail("Bad request.")
            if everything and set(ids) != set(there):
                return fail("The Trash changed since you looked at it. Look at it again, then empty it.", 409)
            chosen = [i for i in dict.fromkeys(ids) if i in set(there)]
        if not chosen:
            return fail("That is no longer in the Trash." if not everything else "The Trash is empty already.", 404)
        done = [post_id for post_id in chosen if delete_forever(db, post_id)]
        return {"ok": True, "count": len(done), "empty": not db.one("SELECT 1 FROM posts WHERE trashed_at IS NOT NULL")}
