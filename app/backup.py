"""Back up and restore (Settings › Backup and restore): one file holding all of the owner's that a new PC needs, and that
file put back. The file is a zip:

- backup.json, what it holds and when it was made, and README.txt, the same for a person
- story-bank.md and voice-profile.md, from linkedin-skills\\references
- studio.db, the database at that moment (SQLite's own backup, whole while the studio runs): every post with its
  versions, the chats, Hot topics and its ranks, the plans, the runs
- images\\ (the pictures, carousels, cards and ChatGPT's art), attachments\\ (the files attached to chats) and the
  ChatGPT pictures counted (chatgpt.json)
- the settings: those kept beside the database (the posting times, the post style, You in the preview) and those of
  config.local.toml that go with the owner rather than the PC (settings.json: the Publora plan's limits, the time
  zone, the model and its limits); never a folder of this PC

Never a key or a sign-in: linkedin-skills\\.env and Claude's and ChatGPT's sign-ins stay where they are, and a new PC is
set up with them first. A restore reads the whole file before it changes anything (every name and size, the parts, the
database opened and checked), keeps a backup of how the studio is first (data\\backups\\), then puts back the parts the
owner ticked: the Story Bank, the voice profile, the studio (its database, pictures and attachments, replaced whole),
the settings."""
from __future__ import annotations

import io
import json
import re
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from zoneinfo import ZoneInfo

from .attachments import size_words
from .config import Config
from .db import DB, utcnow

MADE_BY, FORMAT = "LinkedIn Studio", 1
PARTS = {"bank": "The Story Bank", "voice": "The voice profile", "studio": "Posts, pictures and chats", "settings": "Settings"}
TEXTS = {"bank": "story-bank.md", "voice": "voice-profile.md"}
FOLDERS = ("images", "attachments")                     # beside the database: a restore replaces them whole
CHATGPT = "chatgpt.json"                                # the ChatGPT pictures counted, the studio's with its database
BESIDE = ("posting.json", "style.json", "profile.json", "profile-photo")   # the settings kept beside the database
SETTINGS = {"monthly_post_limit": int, "publora_at_once": int, "publora_days_ahead": int, "timezone": str, "model": str,
            "max_turns": int, "timeout_seconds": int, "chat_max_turns": int, "chat_timeout_seconds": int,
            "images_per_request": int}                  # config.local.toml's that go with the owner, not with the PC
NAMES = {"backup.json", "README.txt", "studio.db", "settings.json", CHATGPT, *TEXTS.values(), *BESIDE}
MOST_FILES, MOST_FILE, MOST_ALL = 20000, 512 * 1024**2, 4 * 1024**3
PART = re.compile(r'^[^\\/:*?"<>|\x00-\x1f]{1,200}$')  # one step of a path inside images\ or attachments\
MODEL = re.compile(r"^[A-Za-z0-9._\[\]-]{0,60}$")
NOT_ONE = "This is not a LinkedIn Studio backup: choose the .zip that Back up made."
CHANGED = "This backup was changed after it was made ({}), so the studio won't put it back."

README = """This is a backup of LinkedIn Studio: your Story Bank, your voice profile, your posts (with their versions,
pictures, carousels, cards and ChatGPT's art), the chats, Hot topics and its ranks, your posting times, post style,
You in the preview, and the settings that go with you.

It holds no keys and no sign-ins. On a new PC, set LinkedIn Studio up first (the linkedin-skills folder with its .env,
Claude's sign-in), then open Settings > Backup and restore > Restore from a backup, and choose this file.

Keep it somewhere safe: your Story Bank is in it.
"""


class Refused(Exception):
    """A backup that can't be made or put back, in the owner's words."""


# ---- a backup -----------------------------------------------------------------------------------------------------
def make(cfg: Config, db: DB, target: Path) -> dict:
    """Writes a backup of the studio as it is now to `target` (a zip). Returns what it holds (its backup.json)."""
    data = db.path.parent
    target.parent.mkdir(parents=True, exist_ok=True)
    held = []
    with tempfile.TemporaryDirectory() as temp, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for part, name in TEXTS.items():
            path = cfg.story_bank if part == "bank" else cfg.voice_profile
            if path.is_file():
                z.write(path, name)
                held.append(part)
        snapshot = Path(temp) / "studio.db"
        _copy_db(db.path, snapshot)
        z.write(snapshot, "studio.db")
        posts = _posts(snapshot)
        pictures = 0
        for folder in FOLDERS:
            root = data / folder
            for path in sorted(root.rglob("*")) if root.is_dir() else []:
                if path.is_file():
                    z.write(path, f"{folder}/{path.relative_to(root).as_posix()}")
                    pictures += folder == "images"
        if (data / CHATGPT).is_file():
            z.write(data / CHATGPT, CHATGPT)
        held.append("studio")
        for name in BESIDE:
            if (data / name).is_file():
                z.write(data / name, name)
        z.writestr("settings.json", json.dumps({key: getattr(cfg, key) for key in SETTINGS}, indent=2))
        held.append("settings")
        about = {"made_by": MADE_BY, "format": FORMAT, "made_at": utcnow(), "parts": held, "posts": posts, "pictures": pictures}
        z.writestr("backup.json", json.dumps(about, indent=2))
        z.writestr("README.txt", README)
    return about


def _copy_db(source: Path, target: Path) -> None:
    """SQLite's own backup, page by page: whole and consistent while other connections read and write."""
    src, dst = sqlite3.connect(source, timeout=30), sqlite3.connect(target, timeout=30)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def _posts(path: Path) -> int:
    con = sqlite3.connect(path)
    try:
        return con.execute("SELECT COUNT(*) FROM posts WHERE trashed_at IS NULL").fetchone()[0]
    finally:
        con.close()


# ---- what a backup holds ------------------------------------------------------------------------------------------
def _open(body: bytes) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(io.BytesIO(body))
    except zipfile.BadZipFile:
        raise Refused(NOT_ONE) from None


def _about(z: zipfile.ZipFile) -> dict:
    try:
        about = json.loads(z.read("backup.json"))
    except (KeyError, ValueError):
        raise Refused(NOT_ONE) from None
    if not isinstance(about, dict) or about.get("made_by") != MADE_BY or not isinstance(about.get("format"), int):
        raise Refused(NOT_ONE)
    if about["format"] > FORMAT:
        raise Refused("This backup was made by a newer LinkedIn Studio: update this one, then restore.")
    return about


def _names(z: zipfile.ZipFile) -> set[str]:
    """Every file's name, each one checked: a name a backup never holds, a path out of its folder or a size no backup
    has is refused, before anything is read."""
    infos = [info for info in z.infolist() if not info.is_dir()]
    if len(infos) > MOST_FILES or sum(info.file_size for info in infos) > MOST_ALL:
        raise Refused("This backup is larger than any the studio makes, so it won't put it back.")
    names = set()
    for info in infos:
        name = info.filename
        top, _, rest = name.partition("/")
        steps = rest.split("/") if top in FOLDERS else []
        inside = 0 < len(steps) <= 3 and all(PART.match(step) and step not in (".", "..") and not step.endswith((" ", "."))
                                             for step in steps)
        if info.file_size > MOST_FILE or not (name in NAMES or inside):
            raise Refused(CHANGED.format(name[:80]))
        names.add(name)
    return names


def _text(z: zipfile.ZipFile, name: str) -> bytes:
    body = z.read(name)
    try:
        body.decode("utf-8")
    except UnicodeDecodeError:
        raise Refused(CHANGED.format(name)) from None
    return body


def _check_db(z: zipfile.ZipFile) -> None:
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "studio.db"
        path.write_bytes(z.read("studio.db"))
        try:
            con = sqlite3.connect(path)
            try:
                ok = con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            finally:
                con.close()
        except sqlite3.Error:
            ok, tables = False, set()
    if not ok or not {"posts", "images"} <= tables:
        raise Refused("This backup's posts are damaged, so the studio won't put them back.")


def _settings(z: zipfile.ZipFile) -> dict:
    """settings.json's values, each of a setting that goes with the owner and of its kind."""
    try:
        values = json.loads(z.read("settings.json"))
    except ValueError:
        values = None
    if not isinstance(values, dict) or any(k not in SETTINGS or type(v) is not SETTINGS[k] for k, v in values.items()):
        raise Refused(CHANGED.format("settings.json"))
    try:
        if "timezone" in values:
            ZoneInfo(values["timezone"])
    except (ValueError, OSError, KeyError):     # a name no zone has: ZoneInfoNotFoundError, a KeyError
        raise Refused(CHANGED.format("settings.json")) from None
    if not MODEL.match(values.get("model", "")) or any(v < 0 for v in values.values() if isinstance(v, int)):
        raise Refused(CHANGED.format("settings.json"))
    return values


def look(body: bytes) -> dict:
    """What a backup holds, the whole file checked first (Refused when it can't be put back): when it was made, its
    parts (of PARTS) with a few words on each, its posts and pictures."""
    with _open(body) as z:
        about = _about(z)
        names = _names(z)
        what = {}
        for part, name in TEXTS.items():
            if name in names:
                what[part] = size_words(len(_text(z, name)))
        if "studio.db" in names:
            _check_db(z)
            what["studio"] = f"{about.get('posts', 0)} posts, {about.get('pictures', 0)} pictures"
        beside = [name for name in BESIDE if name in names]
        for name in beside:
            if name != "profile-photo":
                try:
                    json.loads(z.read(name))
                except ValueError:
                    raise Refused(CHANGED.format(name)) from None
        if "settings.json" in names:
            _settings(z)
        if beside or "settings.json" in names:
            what["settings"] = ", ".join(word for word, there in (
                ("posting times", "posting.json" in names), ("post style", "style.json" in names),
                ("You in the preview", "profile.json" in names or "profile-photo" in names),
                ("the plan, time zone and model", "settings.json" in names)) if there)
    return {"made_at": about.get("made_at", ""), "posts": about.get("posts", 0), "pictures": about.get("pictures", 0),
            "parts": [part for part in PARTS if part in what], "what": what}


# ---- a restore ----------------------------------------------------------------------------------------------------
def restore(cfg: Config, db: DB, body: bytes, chosen, before: Path) -> dict:
    """Puts back the parts chosen (of those the backup holds), the whole file checked first and a backup of how the
    studio is now kept at `before`. Returns what was put back (its words) and the settings of config.local.toml that
    change (the caller writes them, and the studio starts again to use them)."""
    held = look(body)
    parts = [part for part in PARTS if part in set(chosen or []) and part in held["parts"]]
    if not parts:
        raise Refused("Tick what to put back.")
    make(cfg, db, before)
    data = db.path.parent
    changes: dict = {}
    with _open(body) as z:
        names = set(z.namelist())
        for part, name in TEXTS.items():
            if part in parts:
                _write(cfg.story_bank if part == "bank" else cfg.voice_profile, z.read(name))
        if "studio" in parts:
            _put_db(z, db)
            for folder in FOLDERS:
                _put_folder(z, data / folder, folder)
            if CHATGPT in names:
                _write(data / CHATGPT, z.read(CHATGPT))
        if "settings" in parts:
            for name in BESIDE:
                if name in names:
                    _write(data / name, z.read(name))
            if "settings.json" in names:
                changes = {k: v for k, v in _settings(z).items() if getattr(cfg, k) != v}
    return {"restored": [PARTS[part] for part in parts], "settings": changes}


def _write(path: Path, body: bytes) -> None:
    """In one step: written beside it first, then put in its place."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fresh = path.with_name(path.name + ".restoring")
    fresh.write_bytes(body)
    fresh.replace(path)


def _put_db(z: zipfile.ZipFile, db: DB) -> None:
    """The backup's database in place of this one, through SQLite's own backup (the studio's other connections wait for
    it), then brought up to this studio's tables and columns with anything it had in flight stopped, as at a start."""
    with tempfile.TemporaryDirectory() as temp:
        incoming = Path(temp) / "studio.db"
        incoming.write_bytes(z.read("studio.db"))
        _copy_db(incoming, db.path)
    DB(db.path)
    db.touch()


def _put_folder(z: zipfile.ZipFile, root: Path, prefix: str) -> None:
    """The folder as the backup has it: what was in it goes (a file in use at that moment stays, unused), then the
    backup's files go in."""
    if root.is_dir():
        for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            try:
                path.unlink() if path.is_file() else path.rmdir()
            except OSError:
                pass
    for info in z.infolist():
        if not info.is_dir() and info.filename.startswith(prefix + "/"):
            target = root.joinpath(*info.filename[len(prefix) + 1:].split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(info))
