"""You in the preview (Settings): the name, headline and photo a post's preview shows above its text.

They are kept beside the database the app opened (`db.path.parent`: data\\ for the real app, the demo's and the tests'
own folders for theirs): `profile.json` for the words (and the carousels switch), `profile-photo` for the picture. The
page's preview reads them; a carousel's slides carry them to LinkedIn only while the owner has switched that on
(`on_carousels`, off unless set). They are never sent to Claude or ChatGPT, and never in config or a tracked file. Unset,
the preview says You / Your headline.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
from pathlib import Path

from .db import DB
from .publishing import sniff_image

NAME_MAX = 80             # characters
HEADLINE_MAX = 220        # LinkedIn's own limit for a headline
PHOTO_TYPES = ("image/png", "image/jpeg", "image/webp")
PHOTO_MAX = 512 * 1024    # bytes: the page sends a 256 px square, usually a few tens of KB
YOU = {"name": "You", "headline": "Your headline"}   # what the preview says when nothing is set
WORDS, PHOTO = "profile.json", "profile-photo"
DATA_URL = re.compile(r"data:[\w.+-]+/[\w.+-]+(?:;[\w.+-]+=[\w.+-]+)*;base64,", re.I)


class Refused(ValueError):
    """What was sent cannot be kept; the message says why, in the page's words."""


def words_path(db: DB) -> Path:
    return db.path.parent / WORDS


def photo_path(db: DB) -> Path:
    return db.path.parent / PHOTO


def one_line(value, most: int, what: str) -> str:
    """Trimmed to one line with single spaces; refused when longer than `most` characters."""
    text = " ".join("".join(ch if ch.isprintable() else " " for ch in str(value or "")).split())
    if len(text) > most:
        raise Refused(f"{what} has {len(text)} characters: keep it to {most}.")
    return text


def _kept(db: DB) -> dict:
    try:
        data = json.loads(words_path(db).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return data if isinstance(data, dict) else {}


def saved(db: DB) -> dict:
    """The name and headline as saved ("" when not set)."""
    data = _kept(db)
    return {"name": str(data.get("name") or "")[:NAME_MAX], "headline": str(data.get("headline") or "")[:HEADLINE_MAX]}


def on_carousels(db: DB) -> bool:
    """Whether carousels carry the name, headline and photo: only once the owner switched it on."""
    return _kept(db).get("on_carousels") is True


def photo(db: DB) -> tuple[bytes, str] | None:
    """The photo's bytes and their type, sniffed from the bytes themselves; None when there is none, or when what is in
    the file is not a PNG, JPEG or WebP picture."""
    try:
        body = photo_path(db).read_bytes()
    except OSError:
        return None
    mime = sniff_image(body[:16])
    return (body, mime) if mime in PHOTO_TYPES and len(body) <= PHOTO_MAX else None


def public(db: DB) -> dict:
    """What GET /api/profile answers: the name and headline the preview shows, the photo's address or None, the words as
    saved and how long each may be (for Settings' boxes)."""
    words = saved(db)
    url = None
    if photo(db) is not None:
        url = f"/api/profile/photo?v={photo_path(db).stat().st_mtime_ns}"   # a new address for each new photo
    return {"name": words["name"] or YOU["name"], "headline": words["headline"] or YOU["headline"], "photo": url,
            "saved": words, "most": {"name": NAME_MAX, "headline": HEADLINE_MAX}, "on_carousels": on_carousels(db)}


def _write(path: Path, data: bytes) -> None:
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(data)
    temp.replace(path)


def _store(db: DB, data: dict) -> None:
    """The words, with on_carousels only while it is on; nothing at all when all of it is empty."""
    on = data.pop("on_carousels")
    if data["name"] or data["headline"] or on:
        _write(words_path(db), json.dumps({**data, **({"on_carousels": True} if on else {})}, ensure_ascii=False).encode("utf-8"))
    else:
        words_path(db).unlink(missing_ok=True)


def save_words(db: DB, name, headline) -> dict:
    words = {"name": one_line(name, NAME_MAX, "The name"), "headline": one_line(headline, HEADLINE_MAX, "The headline")}
    _store(db, {**words, "on_carousels": on_carousels(db)})
    return public(db)


def save_on_carousels(db: DB, on) -> dict:
    """Carousels drawn from now on carry the name, headline and photo (on) or nothing (off)."""
    if not isinstance(on, bool):
        raise Refused("Say on or off.")
    _store(db, {**saved(db), "on_carousels": on})
    return public(db)


def save_photo(db: DB, data_url) -> dict:
    """A photo sent as a data: URL. Only a PNG, JPEG or WebP picture is kept, judged by its bytes, never by its label."""
    text = str(data_url or "").strip()
    if len(text) > PHOTO_MAX * 4 // 3 + 256:
        raise Refused(f"That photo is over {PHOTO_MAX // 1024} KB. Choose it again: the page makes it small first.")
    head = DATA_URL.match(text)
    if head is None:
        raise Refused("Send the photo as a picture.")
    try:
        body = base64.b64decode(text[head.end():], validate=True)
    except (binascii.Error, ValueError):
        raise Refused("The photo did not arrive whole. Choose it again.") from None
    if len(body) > PHOTO_MAX:
        raise Refused(f"That photo is over {PHOTO_MAX // 1024} KB. Choose it again: the page makes it small first.")
    if sniff_image(body[:16]) not in PHOTO_TYPES:
        raise Refused("A photo is a PNG, JPEG or WebP picture.")
    _write(photo_path(db), body)
    return public(db)


def remove_photo(db: DB) -> dict:
    photo_path(db).unlink(missing_ok=True)
    return public(db)
