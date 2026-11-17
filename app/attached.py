"""This studio's use of the shared attachments module (app/attachments.py, never edited here): the files the owner
attaches to a chat message, kept in a folder of that one chat under data\\attachments\\ (post-<id>, bank-<id>,
voice-<id>), which is the only extra folder that chat's Claude run may Read (--add-dir, its hidden .text/ included).
"""
from __future__ import annotations

import base64
import re
from pathlib import Path

from . import attachments
from .attachments import Refused
from .db import DB

DATA_URL = re.compile(r"^data:[^,]*?(;base64)?,", re.S)


def folder(db: DB, key: str) -> Path:
    return db.path.parent / "attachments" / key


def _decode(item) -> tuple[str, bytes]:
    if not isinstance(item, dict):
        raise Refused("A file did not arrive whole: attach it again.")
    name = str(item.get("name") or "file")
    data = str(item.get("data") or "")
    found = DATA_URL.match(data)
    if not found or not found.group(1):
        raise Refused(f"{attachments.safe_name(name)} did not arrive whole: attach it again.")
    try:
        return name, base64.b64decode(data[found.end():], validate=True)
    except ValueError:
        raise Refused(f"{attachments.safe_name(name)} did not arrive whole: attach it again.") from None


def save_all(db: DB, key: str, files) -> list[dict]:
    """Keep a message's files, all of them or none: the count and the total are checked before any is kept.
    Returns their records; raises Refused in the owner's words."""
    if not files:
        return []
    limits = attachments.LIMITS
    if not isinstance(files, list) or len(files) > limits["count"]:
        raise Refused(f"Attach up to {limits['count']} files at a time.")
    decoded = [_decode(item) for item in files]
    total = sum(len(body) for _name, body in decoded)
    if total > limits["message"]:
        raise Refused(f"These files come to {attachments.size_words(total)}: a message can carry up to "
                      f"{attachments.size_words(limits['message'])}.")
    target = folder(db, key)
    return [attachments.save(target, name, body, limits) for name, body in decoded]


def for_run(db: DB, key: str, names: list[str]) -> tuple[str, list[str]]:
    """(the folder the run may Read, the lines its prompt gets for these files)."""
    target = folder(db, key)
    records = [attachments.describe(target, name) for name in names]
    return str(target), attachments.for_claude([r for r in records if r], target.as_posix())


def public(records: list[dict], base: str) -> list[dict]:
    """A message's files for the page: each one's name, kind and size, and where the page opens it."""
    return [{"name": r["name"], "kind": r["kind"], "size": r["size"], "mime": r["mime"],
             "url": f"{base}/{r['name']}", "view": r["mime"] in attachments.VIEWABLE} for r in records]


def served(db: DB, key: str, name: str):
    """(the file, its headers) to serve a kept file back to the page, or None. The name is checked as text first (one
    plain file name the module would itself keep: no folder, no drive, nothing hidden), then resolved inside the folder."""
    if not name or name != attachments.safe_name(name) or name.startswith(".") or "/" in name or "\\" in name:
        return None
    target = folder(db, key).resolve()
    path = (target / name).resolve()
    if path.parent != target or not path.is_file():
        return None
    record = attachments.describe(target, name)
    return (path, attachments.headers(record)) if record else None
