"""Backup and restore (backup.py, api_backup.py): Back up downloads one zip of all of the owner's (the Story Bank, the
voice profile, the database, the pictures, the settings that go with them) and never a key; a restore checks the whole
file first, refuses one that is not a backup or was changed, keeps a backup of how the studio was, puts back only the
parts ticked, and waits while Claude is at work. Every word here is made up."""
import base64
import io
import json
import zipfile

import pytest
from conftest import TOKEN, add_job, add_post
from fastapi.testclient import TestClient

from app import backup, images, paths
from app.main import create_app

BANK = "# Story Bank\n\n## 2. Receipts\n\n- Cut a made-up build from 14 minutes to 5\n"
VOICE = "# Voice profile\n\n- Short sentences. No hype.\n"


@pytest.fixture
def web(cfg, tmp_path, fake_runner):
    cfg.story_bank.write_text(BANK, encoding="utf-8")
    cfg.voice_profile.write_text(VOICE, encoding="utf-8")
    app = create_app(cfg, TOKEN, db_path=tmp_path / "data" / "studio.db", runner=fake_runner)
    with TestClient(app, base_url=f"http://127.0.0.1:{cfg.port}", headers={"Origin": cfg.origin}) as client:
        client.cookies.set("studio_session", TOKEN)
        yield client, app.state.db, cfg


def as_file(body: bytes) -> str:
    return "data:application/zip;base64," + base64.b64encode(body).decode("ascii")


def a_studio(db):
    """Two posts, a picture on one, the posting times and the post style beside the database."""
    kept = add_post(db, text="A post worth keeping.")
    add_post(db, text="Another one.")
    folder = images.folder(db)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "a1b2.png").write_bytes(b"\x89PNG made up")
    (db.path.parent / "posting.json").write_text('{"times": ["08:00"]}', encoding="utf-8")
    (db.path.parent / "style.json").write_text('{"length": 2}', encoding="utf-8")
    return kept


def test_back_up_downloads_one_file_of_everything_and_never_a_key(web):
    client, db, cfg = web
    a_studio(db)
    reply = client.get("/api/backup")
    assert reply.status_code == 200 and reply.headers["content-type"] == "application/zip"
    assert 'filename="linkedin-studio-backup-' in reply.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(reply.content)) as z:
        names = set(z.namelist())
        assert {"backup.json", "README.txt", "story-bank.md", "voice-profile.md", "studio.db", "images/a1b2.png",
                "posting.json", "style.json", "settings.json"} <= names
        assert z.read("story-bank.md") == cfg.story_bank.read_bytes()                                 # byte for byte
        about = json.loads(z.read("backup.json"))
        assert (about["parts"], about["posts"], about["pictures"]) == (["bank", "voice", "studio", "settings"], 2, 1)
        assert json.loads(z.read("settings.json"))["timezone"] == cfg.timezone
        assert not any(b"sk_test_secret" in z.read(name) or name.endswith(".env") for name in names)   # never a key


def test_a_restore_puts_back_only_what_is_ticked_after_keeping_how_it_was(web):
    client, db, cfg = web
    kept = a_studio(db)
    body = client.get("/api/backup").content
    cfg.story_bank.write_text("# Story Bank\n\nA bad edit.\n", encoding="utf-8")
    db.run("DELETE FROM posts WHERE id=?", (kept,))
    (images.folder(db) / "a1b2.png").unlink()
    (images.folder(db) / "stray.png").write_bytes(b"made later")
    (db.path.parent / "posting.json").write_text('{"times": ["09:30"]}', encoding="utf-8")
    seen = client.post("/api/backup/look", json={"file": as_file(body)}).json()
    assert [p["key"] for p in seen["parts"]] == ["bank", "voice", "studio", "settings"] and seen["posts"] == 2
    assert seen["parts"][2]["what"] == "2 posts, 1 pictures" and "posting times" in seen["parts"][3]["what"]
    assert client.post("/api/backup/restore", json={"file": as_file(body), "parts": ["bank"]}).status_code == 422   # not asked
    done = client.post("/api/backup/restore", json={"file": as_file(body), "parts": ["bank", "studio"], "confirmed": True}).json()
    assert done["restored"] == ["The Story Bank", "Posts, pictures and chats"] and done["restarts"] is False
    assert cfg.story_bank.read_text(encoding="utf-8") == BANK and kept in [p["id"] for p in client.get("/api/state").json()["posts"]]
    assert (images.folder(db) / "a1b2.png").is_file() and not (images.folder(db) / "stray.png").exists()   # as the backup has it
    assert '"09:30"' in (db.path.parent / "posting.json").read_text(encoding="utf-8")                     # Settings: not ticked
    with zipfile.ZipFile(done["kept"]) as before:                                                          # how it was, kept
        assert b"A bad edit." in before.read("story-bank.md") and "images/stray.png" in before.namelist()


def test_restored_settings_go_into_config_local_toml_and_only_those_that_change(web, monkeypatch):
    client, db, cfg = web
    written = []
    monkeypatch.setattr(paths, "save_values", written.append)
    body = client.get("/api/backup").content
    changed = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(body)) as z, zipfile.ZipFile(changed, "w") as out:
        for name in z.namelist():
            values = {**json.loads(z.read(name)), "model": "opus"} if name == "settings.json" else None
            out.writestr(name, json.dumps(values) if values else z.read(name))
    done = client.post("/api/backup/restore", json={"file": as_file(changed.getvalue()), "parts": ["settings"], "confirmed": True}).json()
    assert done["restored"] == ["Settings"] and written == [{"model": "opus"}]


def zipped(**files) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, body in files.items():
            z.writestr(name.replace("__", "/").replace("_dot_", "."), body)
    return out.getvalue()


ABOUT = json.dumps({"made_by": "LinkedIn Studio", "format": 1, "made_at": "2026-11-04T10:00:00+00:00"})


@pytest.mark.parametrize("body,said", [
    (b"plain words, not a zip", "not a LinkedIn Studio backup"),
    (zipped(**{"story-bank_dot_md": BANK}), "not a LinkedIn Studio backup"),                         # no backup.json
    (zipped(**{"backup_dot_json": ABOUT.replace('"format": 1', '"format": 2')}), "made by a newer LinkedIn Studio"),
    (zipped(**{"backup_dot_json": ABOUT, "notes_dot_txt": "x"}), "changed after it was made (notes.txt)"),
    (zipped(**{"backup_dot_json": ABOUT, "images__.._dot_.__.._dot_.__evil_dot_png": "x"}), "changed after it was made"),
    (zipped(**{"backup_dot_json": ABOUT, "studio_dot_db": "not a database"}), "posts are damaged"),
    (zipped(**{"backup_dot_json": ABOUT, "settings_dot_json": '{"skills_dir": "C:/elsewhere"}'}), "changed after it was made"),
    (zipped(**{"backup_dot_json": ABOUT, "settings_dot_json": '{"timezone": "Nowhere/Atall"}'}), "changed after it was made"),
])
def test_a_restore_refuses_what_is_not_a_backup_or_was_changed_and_changes_nothing(web, body, said):
    client, db, cfg = web
    reply = client.post("/api/backup/restore", json={"file": as_file(body), "parts": list(backup.PARTS), "confirmed": True})
    assert reply.status_code == 422 and said in reply.json()["error"]
    assert cfg.story_bank.read_text(encoding="utf-8") == BANK and not (db.path.parent / "backups").exists()


def test_a_restore_waits_while_claude_is_at_work(web):
    client, db, _cfg = web
    body = client.get("/api/backup").content
    add_job(db, "post_chat", status="running")
    reply = client.post("/api/backup/restore", json={"file": as_file(body), "parts": ["bank"], "confirmed": True})
    assert reply.status_code == 409 and "Claude is at work" in reply.json()["error"]
