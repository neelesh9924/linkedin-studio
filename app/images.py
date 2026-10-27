"""A post's pictures: kept as files in the images folder beside the database, listed in the `images` table.

One of a post's pictures can be chosen as the picture that goes out with it (posts.picture_id). Files
are named by their contents, so the same picture is kept once.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .db import DB, utcnow

EXTENSION = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}   # what Publora takes
NAME = re.compile(r"^[0-9a-f]{24}\.(png|jpg|webp|gif)$")


class ImageError(RuntimeError):
    pass


def folder(db: DB) -> Path:
    return db.path.parent / "images"


def save(db: DB, post_id: int, data: bytes, *, mime: str, source: str, prompt: str = "", shape: str = "",
         width: int = 0, height: int = 0, job_id: int | None = None) -> int:
    if mime not in EXTENSION:
        raise ImageError(f"A picture is PNG, JPEG, WebP or GIF, not {mime}.")
    digest = hashlib.sha256(data).hexdigest()
    name = f"{digest[:24]}.{EXTENSION[mime]}"
    where = folder(db)
    where.mkdir(parents=True, exist_ok=True)
    path = where / name
    if not path.is_file():
        temp = path.with_name(name + ".tmp")
        temp.write_bytes(data)
        temp.replace(path)
    return db.run("INSERT INTO images (post_id, file, source, prompt, shape, width, height, mime, sha256, job_id, created_at) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (post_id, name, source, prompt[:2000] or None, shape or None, width or None, height or None, mime, digest,
                   job_id, utcnow()))


def path_of(db: DB, row) -> Path | None:
    """The file of an image row, only when its name is one the studio made."""
    if row is None or not NAME.match(str(row["file"] or "")):
        return None
    path = folder(db) / row["file"]
    return path if path.is_file() else None


def for_post(db: DB, post_id: int) -> list:
    return db.all("SELECT * FROM images WHERE post_id=? ORDER BY id", (post_id,))


def public(row, chosen_id: int | None = None) -> dict:
    return {"id": row["id"], "url": f"/api/image/{row['id']}", "source": row["source"], "shape": row["shape"],
            "width": row["width"], "height": row["height"], "prompt": row["prompt"] or "",
            "chosen": row["id"] == chosen_id, "made": row["created_at"]}
