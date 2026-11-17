"""Settings › Backup and restore (backup.py): the backup as a download, what a backup the owner chose holds, and the
restore. A backup comes back as the page read it, a data: URL in JSON, as an attached file does (attached.py)."""
from __future__ import annotations

import base64
import re
import shutil
import sqlite3
import tempfile
import threading
from datetime import datetime
from pathlib import Path

from fastapi import Body, FastAPI
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask

from . import backup, paths
from .config import ConfigError
from .main import Studio

DATA_URL = re.compile(r"^data:[^,]*?;base64,", re.S)


def fail(text: str, status: int = 422) -> JSONResponse:
    return JSONResponse({"error": text}, status_code=status)


def body_of(data: dict) -> bytes:
    text = str(data.get("file") or "")
    found = DATA_URL.match(text)
    if not found:
        raise backup.Refused(backup.NOT_ONE)
    try:
        return base64.b64decode(text[found.end():], validate=True)
    except ValueError:
        raise backup.Refused("The file did not arrive whole: choose it again.") from None


def register(app: FastAPI, s: Studio) -> None:
    db, cfg = s.db, s.cfg

    @app.get("/api/backup")
    def backup_download():
        """The studio as it is now, in one file to keep: linkedin-studio-backup-<its date>.zip, as a download."""
        folder = Path(tempfile.mkdtemp(prefix="linkedin-studio-backup-"))
        name = f"linkedin-studio-backup-{datetime.now(cfg.tz):%Y-%m-%d}.zip"
        try:
            backup.make(cfg, db, folder / name)
        except (OSError, sqlite3.Error) as exc:
            shutil.rmtree(folder, ignore_errors=True)
            return fail(f"The backup could not be made: {exc}", 500)
        return FileResponse(folder / name, media_type="application/zip", filename=name,
                            background=BackgroundTask(shutil.rmtree, folder, ignore_errors=True))

    @app.post("/api/backup/look")
    def backup_look(data: dict = Body(default={})):
        """What a backup the owner chose holds, the whole file checked; nothing changes."""
        try:
            held = backup.look(body_of(data))
        except backup.Refused as exc:
            return fail(str(exc))
        return {"ok": True, "made_at": s.when(held["made_at"], year=True), "posts": held["posts"], "pictures": held["pictures"],
                "parts": [{"key": part, "label": backup.PARTS[part], "what": held["what"][part]} for part in held["parts"]]}

    @app.post("/api/backup/restore")
    def backup_restore(data: dict = Body(default={})):
        """Puts back the parts ticked (`parts`) from the backup sent, once the owner was asked (`confirmed`); never while
        Claude is at work or a post is on its way to Publora. A backup of how the studio is now is kept first, in
        data\\backups. Settings of config.local.toml that change are written there, and the studio starts again to use
        them."""
        if data.get("confirmed") is not True:
            return fail("Restoring replaces what is here: confirm it first.")
        if db.one("SELECT 1 FROM jobs WHERE status IN ('queued','running')") or db.one("SELECT 1 FROM posts WHERE status='scheduling'"):
            return fail("Claude is at work, or a post is on its way to Publora: restore once that is done.", 409)
        before = db.path.parent / "backups" / f"before-restore-{datetime.now(cfg.tz):%Y-%m-%d-%H%M%S}.zip"
        try:
            done = backup.restore(cfg, db, body_of(data), data.get("parts"), before)
        except backup.Refused as exc:
            return fail(str(exc))
        except (OSError, sqlite3.Error) as exc:
            return fail(f"The restore stopped part of the way: {exc}. How the studio was before is in {before}.", 500)
        restarts = False
        if done["settings"]:
            try:
                paths.save_values(done["settings"])
            except ConfigError as exc:
                return fail(f"Restored all but the settings of config.local.toml: {exc}", 500)
            if s.on_restart:
                threading.Timer(1.0, s.on_restart).start()     # after this answer has reached the window
                restarts = True
        return {"ok": True, "restored": done["restored"], "kept": str(before), "restarts": restarts}
