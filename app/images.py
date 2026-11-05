"""A post's pictures and carousels: kept as files in the images folder beside the database, listed in the `images` table.

What goes out with a post is posts.picture_ids, in order: up to MAX_PICTURES pictures, or one carousel alone (a PDF
LinkedIn shows as a swipeable document, as Publora takes it: it never mixes a document with pictures). Files are named
by their contents, so the same one is kept once; a carousel keeps a PNG of each slide beside its PDF for the page.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .db import DB, loads, utcnow

PICTURE = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}   # what Publora takes
DOCUMENT = "application/pdf"
EXTENSION = {**PICTURE, DOCUMENT: "pdf"}
NAME = re.compile(r"^[0-9a-f]{24}\.(png|jpg|webp|gif|pdf)$")
MAX_PICTURES = 10        # Publora's limit for a LinkedIn post


class ImageError(RuntimeError):
    pass


def folder(db: DB) -> Path:
    return db.path.parent / "images"


def _keep(where: Path, name: str, data: bytes) -> None:
    path = where / name
    if not path.is_file():
        temp = path.with_name(name + ".tmp")
        temp.write_bytes(data)
        temp.replace(path)


def save(db: DB, post_id: int, data: bytes, *, mime: str, source: str, prompt: str = "", shape: str = "",
         width: int = 0, height: int = 0, job_id: int | None = None, spec: dict | None = None,
         pages: list[bytes] | tuple = (), into: int | None = None) -> int:
    """Keeps a picture, or a carousel (its PDF, with `spec` and a PNG of each slide in `pages`). Returns its id.
    `into`: the id of the post's row it takes the place of (Redraw), so the post and its chat go on naming it; the old
    files go once nothing else keeps them."""
    if mime not in EXTENSION:
        raise ImageError(f"A picture is PNG, JPEG, WebP or GIF, not {mime}.")
    if (mime == DOCUMENT) != bool(pages):
        raise ImageError("A carousel is a PDF with a picture of each slide.")
    digest = hashlib.sha256(data).hexdigest()
    name = f"{digest[:24]}.{EXTENSION[mime]}"
    where = folder(db)
    where.mkdir(parents=True, exist_ok=True)
    _keep(where, name, data)
    for n, page in enumerate(pages, 1):
        _keep(where, f"{digest[:24]}-{n}.png", page)
    values = (name, source, prompt[:2000] or None, shape or None, width or None, height or None, mime, digest, job_id,
              json.dumps(spec, ensure_ascii=False) if spec else None, len(pages) or None, utcnow())
    old = db.one("SELECT * FROM images WHERE id=? AND post_id=?", (into, post_id)) if into is not None else None
    if old is not None and db.run("UPDATE images SET file=?, source=?, prompt=?, shape=?, width=?, height=?, mime=?, "
                                  "sha256=?, job_id=?, spec=?, pages=?, created_at=? WHERE id=? AND post_id=?",
                                  (*values, into, post_id)) == 1:
        unlink_unused(db, [old])
        return into
    return db.run("INSERT INTO images (post_id, file, source, prompt, shape, width, height, mime, sha256, job_id, spec, "
                  "pages, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (post_id, *values))


def path_of(db: DB, row) -> Path | None:
    """The file of an image row, only when its name is one the studio made."""
    if row is None or not NAME.match(str(row["file"] or "")):
        return None
    path = folder(db) / row["file"]
    return path if path.is_file() else None


def files_of(row) -> list[str]:
    """Every file a row keeps in the images folder: the picture, or a carousel's PDF and its slides (not its art:
    art_of)."""
    name = str(row["file"] or "")
    if not NAME.match(name):
        return []
    stem = name.rsplit(".", 1)[0]
    return [name, *(f"{stem}-{n}.png" for n in range(1, (row["pages"] or 0) + 1))]


def art_of(row) -> list[str]:
    """The ChatGPT art a carousel's or card's slides show (carousel.py keeps it as art-<hash>.png beside them)."""
    from .carousel import ART_FILE   # noqa: PLC0415  (carousel imports this module)

    spec = loads(row["spec"], {}) if "spec" in row.keys() else {}
    found = re.findall(r'"file":\s*"(art-[0-9a-f]{24}\.png)"', json.dumps(spec or {}))
    return [name for name in dict.fromkeys(found) if ART_FILE.match(name)]


def unlink_unused(db: DB, rows) -> None:
    """After these rows are deleted, or drawn afresh: their files that no other row still keeps go (a picture, or a
    carousel's PDF and its slides; art while no row's slides show it). The same file can be another post's (New draft
    from this shares it)."""
    for row in rows:
        if db.one("SELECT 1 FROM images WHERE file=?", (row["file"],)) is None:
            for name in files_of(row):
                (folder(db) / name).unlink(missing_ok=True)
        for name in art_of(row):
            if db.one("SELECT 1 FROM images WHERE spec LIKE ?", (f"%{name}%",)) is None:
                (folder(db) / name).unlink(missing_ok=True)


def page_path(db: DB, row, n: int) -> Path | None:
    """A carousel's slide n (from 1) as a picture, when it is there."""
    if row is None or row["mime"] != DOCUMENT or not 1 <= n <= (row["pages"] or 0):
        return None
    path = folder(db) / files_of(row)[n]
    return path if path.is_file() else None


def is_carousel(row) -> bool:
    return row["mime"] == DOCUMENT


def for_post(db: DB, post_id: int) -> list:
    return db.all("SELECT * FROM images WHERE post_id=? ORDER BY id", (post_id,))


def chosen_ids(post) -> list[int]:
    """posts.picture_ids as a list of ids, in order."""
    ids = loads(post["picture_ids"], []) if post is not None else []
    return [int(i) for i in ids if isinstance(i, int) and not isinstance(i, bool)] if isinstance(ids, list) else []


def chosen(db: DB, post) -> list:
    """The rows that go out with the post, in its order (any no longer there are left out)."""
    ids = chosen_ids(post)
    if not ids:
        return []
    rows = {r["id"]: r for r in db.all(f"SELECT * FROM images WHERE post_id=? AND id IN ({','.join('?' * len(ids))})",
                                        (post["id"], *ids))}
    return [rows[i] for i in ids if i in rows]


def refusal(rows: list) -> str:
    """Why these can't go out together on one post, in the owner's words; empty when they can."""
    ids = [r["id"] for r in rows]
    if len(set(ids)) != len(ids):
        return "A picture can go on the post once."
    if any(is_carousel(r) for r in rows) and len(rows) > 1:
        return "A carousel goes out alone: LinkedIn doesn't mix a document with pictures."
    if len(rows) > MAX_PICTURES:
        return f"A post takes up to {MAX_PICTURES} pictures."
    return ""


def public(row, chosen: list[int] | tuple = ()) -> dict:
    """The page's view of a row. Its addresses name the file too: the browser keeps an image for good, and Redraw
    gives the same row new slides."""
    v = f"?v={str(row['sha256'] or '')[:12]}"
    out = {"id": row["id"], "url": f"/api/image/{row['id']}{v}", "source": row["source"], "shape": row["shape"],
           "width": row["width"], "height": row["height"], "prompt": row["prompt"] or "",
           "chosen": row["id"] in chosen, "order": chosen.index(row["id"]) + 1 if row["id"] in chosen else None,
           "made": row["created_at"], "kind": "carousel" if is_carousel(row) else "picture"}
    spec = loads(row["spec"], {}) or {}
    if spec:     # drawn from slides: a carousel, or a card (one slide, a picture): Redraw and Try another look work on it
        out.update(title=str(spec.get("title") or ""), look=str(spec.get("look") or "midnight"), card=not is_carousel(row))
    if is_carousel(row):
        out.update(pages=row["pages"] or 0,
                   page_urls=[f"/api/image/{row['id']}/page/{n}{v}" for n in range(1, (row["pages"] or 0) + 1)])
    return out
