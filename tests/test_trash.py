"""The Trash, as in the owner's other studios: Move to Trash… and its refusals (by state, by a Publora draft, while Claude
works on the post or waits to); a post in the Trash gone from the list, from every endpoint of a post and from Claude's
tools; the Trash newest first; Put back as it was; Delete forever and Empty trash, each only when confirmed (a picture
file another post uses stays, the plan item is free again); and a database made before the Trash opening as it was."""
import sqlite3
import threading

import pytest
from conftest import TOKEN, add_job, add_post
from fastapi.testclient import TestClient
from support import PNG

from app import attached, images, mcp, versions
from app.db import DB, SCHEMA, dumps, utcnow
from app.jobs import Run
from app.main import create_app


@pytest.fixture
def web(cfg, tmp_path, fake_runner):
    app = create_app(cfg, TOKEN, db_path=tmp_path / "trash.db", runner=fake_runner)
    with TestClient(app, base_url=f"http://127.0.0.1:{cfg.port}", headers={"Origin": cfg.origin}) as client:
        client.cookies.set("studio_session", TOKEN)
        yield client, app.state.db, app


def to_trash(client, post):
    return client.post(f"/api/post/{post}/trash", json={})


def trashed(db, post):
    return bool(db.one("SELECT trashed_at FROM posts WHERE id=?", (post,))["trashed_at"])


def plan_item(db, post=None) -> int:
    plan = db.run("INSERT INTO plans (created_at, inputs, result) VALUES (?,?,?)", (utcnow(), "{}", "{}"))
    return db.run("INSERT INTO plan_items (plan_id, position, data, post_id) VALUES (?,?,?,?)",
                  (plan, 0, dumps({"day": "Tue", "angle": "An angle"}), post))


def test_posts_on_publora_stay_out_of_the_trash_and_the_others_go(web):
    client, db, _ = web
    for status in ("scheduling", "scheduled", "published"):
        post = add_post(db, status=status, scheduled_at="2026-10-09T03:30:00+00:00", publora_post_id="pg1")
        assert client.get(f"/api/post/{post}").json()["deletable"] is False
        assert to_trash(client, post).status_code == 409 and not trashed(db, post), status
    held = add_post(db, status="failed", media=dumps({"postGroupId": "pg2"}), media_step="put", publora_payload="{}")
    refused = to_trash(client, held)
    assert refused.status_code == 409 and "Publora still holds" in refused.json()["error"] and not trashed(db, held)
    for status in ("draft", "approved", "failed", "cancelled"):
        post = add_post(db, status=status)
        assert client.get(f"/api/post/{post}").json()["deletable"] is True
        assert to_trash(client, post).json() == {"ok": True, "id": post} and trashed(db, post), status


@pytest.mark.parametrize("status", ["queued", "running"])
@pytest.mark.parametrize("kind", ["post_chat", "audit", "revise"])
def test_a_post_stays_while_claude_works_on_it_or_waits_to(web, kind, status):
    client, db, _ = web
    post = add_post(db)
    job = add_job(db, kind, status=status, params={"post_id": post, "text": "A finished post."})
    assert client.get(f"/api/post/{post}").json()["deletable"] is False
    refused = to_trash(client, post)
    assert refused.status_code == 409 and "Claude is working" in refused.json()["error"] and not trashed(db, post)
    db.run("UPDATE jobs SET status='done' WHERE id=?", (job,))
    assert to_trash(client, post).json()["ok"] is True


def test_a_post_in_the_trash_is_gone_from_the_list_every_endpoint_and_claudes_tools(web):
    client, db, app = web
    post = add_post(db, text="Kept as it was.")
    other = add_post(db)
    assert to_trash(client, post).json()["ok"] is True
    assert [p["id"] for p in client.get("/api/state").json()["posts"]] == [other]
    shown = client.get(f"/api/post/{post}")
    assert shown.status_code == 404 and shown.json() == {"error": "That post is in the Trash.", "trashed": True}
    assert client.get("/api/post/9999").json() == {"error": "That post no longer exists.", "gone": True}
    body = {"text": "changed", "title": "changed", "how": "hook", "job": 1, "use": 1, "version": 1, "image": None,
            "when": "2026-12-01T09:00", "conversation": 1}
    for action in ("save", "audit", "revise", "revision", "approve", "unapprove", "schedule", "retry", "cancel", "refresh",
                   "picture", "ask", "chat/clear", "chat/back", "versions/back", "title", "checkpoint", "copy", "trash"):
        r = client.post(f"/api/post/{post}/{action}", json=body)
        assert r.status_code == 404 and r.json().get("trashed") is True, action
    for read in ("chat", "versions", "file/notes.txt"):
        assert client.get(f"/api/post/{post}/{read}").json().get("trashed") is True, read
    row = db.one("SELECT text, title, status FROM posts WHERE id=?", (post,))
    assert tuple(row) == ("Kept as it was.", "A post", "draft")
    assert db.one("SELECT COUNT(*) AS n FROM jobs")["n"] == 0 and db.one("SELECT COUNT(*) AS n FROM posts")["n"] == 2
    run = Run(job_id=1, kind="post_chat", params={"post_id": post}, token="t", tools=("set_post_text", "record_audit"),
              cancel=threading.Event(), note=lambda *_a: None)
    for name, arguments in (("set_post_text", {"text": "Claude's text", "note": "New hook"}),
                            ("record_audit", {"verdict": "PASS", "summary": "Fine."})):
        reply = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}},
                           run, app.state.tools)
        assert reply["result"]["isError"] and "Trash" in reply["result"]["content"][0]["text"], name
    assert tuple(db.one("SELECT text, audit FROM posts WHERE id=?", (post,))) == ("Kept as it was.", None)


def test_the_trash_lists_its_posts_newest_first_as_they_were(web):
    client, db, _ = web
    first = add_post(db, status="approved", text="Gone first.\nSecond line.")
    second = add_post(db, text="Gone second.")
    add_post(db, text="Still here.")
    image = images.save(db, second, PNG, mime="image/png", source="chatgpt", width=1200, height=627, shape="landscape")
    db.run("UPDATE posts SET picture_id=? WHERE id=?", (image, second))
    versions.record(db, second, "Gone second.", None, "claude", "First draft")
    db.run("UPDATE posts SET trashed_at=? WHERE id=?", ("2026-10-20T03:30:00+00:00", first))
    db.run("UPDATE posts SET trashed_at=? WHERE id=?", ("2026-10-21T03:30:00+00:00", second))
    entries = client.get("/api/trash").json()["entries"]
    assert [e["id"] for e in entries] == [second, first]
    assert (entries[1]["first"], entries[1]["status"], entries[1]["label"], entries[1]["versions"]) == ("Gone first.", "approved", "Approved", 0)
    assert entries[0]["versions"] == 1 and entries[0]["picture"]["id"] == image and entries[1]["picture"] is None
    assert entries[0]["when"] == "Wed 21 Oct, 9:00 am IST"


SAME = ("status", "title", "text", "first_comment", "formula", "notes", "versions", "picture", "pictures", "plan", "audit")


def test_put_back_returns_the_post_as_it_was(web):
    client, db, _ = web
    item = plan_item(db)
    post = add_post(db, status="approved", text="As it was.", first_comment="A link", plan_item_id=item,
                    audit=dumps({"verdict": "PASS", "text": "As it was."}))
    db.run("UPDATE plan_items SET post_id=? WHERE id=?", (post, item))
    versions.record(db, post, "As it was.", "A link", "claude", "First draft")
    image = images.save(db, post, PNG, mime="image/png", source="chatgpt", width=1200, height=627, shape="landscape")
    db.run("UPDATE posts SET picture_id=? WHERE id=?", (image, post))
    conv = db.run("INSERT INTO conversations (mode, post_id, created_at) VALUES ('post', ?, ?)", (post, utcnow()))
    db.run("INSERT INTO messages (conversation_id, role, text, created_at) VALUES (?,?,?,?)", (conv, "user", "Shorter", utcnow()))
    before = client.get(f"/api/post/{post}").json()
    chat = client.get(f"/api/post/{post}/chat").json()
    assert to_trash(client, post).json()["ok"] is True
    card = client.get("/api/planner").json()["boards"][0]["items"][0]["post"]
    assert (card["id"], card["trashed"], card["label"]) == (post, True, "In the Trash")      # the Planner's card says so
    assert client.post(f"/api/planner/items/{item}/draft", json={}).status_code == 422    # and offers no Draft this
    back = client.post("/api/trash/back", json={"id": post}).json()
    assert back["ok"] is True and back["post"]["trashed"] is False and back["post"]["label"] == "Approved"
    after = client.get(f"/api/post/{post}").json()
    assert {k: after[k] for k in SAME} == {k: before[k] for k in SAME}
    assert client.get(f"/api/post/{post}/chat").json()["messages"] == chat["messages"]
    assert client.post("/api/trash/back", json={"id": post}).status_code == 404
    assert client.post("/api/trash/back", json={"id": "1"}).status_code == 422


def test_delete_forever_and_empty_trash_need_confirmed_and_take_everything_of_the_post(web):
    client, db, _ = web
    item = plan_item(db)
    gone = add_post(db, plan_item_id=item)
    db.run("UPDATE plan_items SET post_id=? WHERE id=?", (gone, item))
    image = images.save(db, gone, PNG, mime="image/png", source="chatgpt", width=1200, height=627)
    db.run("UPDATE posts SET picture_id=? WHERE id=?", (image, gone))
    file = images.path_of(db, db.one("SELECT * FROM images WHERE id=?", (image,)))
    copy = client.post(f"/api/post/{gone}/copy", json={}).json()["id"]          # shares the picture's file
    versions.record(db, gone, "Edited.", None, "you", "Your edits")
    folder = attached.folder(db, f"post-{gone}")
    folder.mkdir(parents=True)
    (folder / "notes.txt").write_text("notes", encoding="utf-8")
    conv = db.run("INSERT INTO conversations (mode, post_id, created_at) VALUES ('post', ?, ?)", (gone, utcnow()))
    db.run("INSERT INTO messages (conversation_id, role, text, created_at) VALUES (?,?,?,?)", (conv, "user", "Hi", utcnow()))
    job = add_job(db, "audit", status="failed", params={"post_id": gone, "text": "x"}, error="boom")
    other = add_post(db)
    stays = add_post(db)
    for post in (gone, other):
        assert to_trash(client, post).json()["ok"] is True
    for body in ({"ids": [gone]}, {"ids": [gone], "confirmed": "yes"}, {"all": True}):
        r = client.post("/api/trash/delete", json=body)
        assert r.status_code == 409 and "confirmation" in r.json()["error"]
    assert client.post("/api/trash/delete", json={"ids": [stays], "confirmed": True}).status_code == 404   # never one outside it
    assert client.post("/api/trash/delete", json={"ids": ["x"], "confirmed": True}).status_code == 422
    changed = client.post("/api/trash/delete", json={"ids": [gone], "all": True, "confirmed": True})
    assert changed.status_code == 409 and "changed" in changed.json()["error"]                          # it holds two
    assert trashed(db, gone) and trashed(db, other)
    assert client.post("/api/trash/delete", json={"ids": [gone], "confirmed": True}).json() == {"ok": True, "count": 1, "empty": False}
    assert db.one("SELECT 1 FROM posts WHERE id=?", (gone,)) is None
    assert [db.one(f"SELECT COUNT(*) AS n FROM {t} WHERE post_id=?", (gone,))["n"] for t in ("versions", "images", "conversations")] == [0, 0, 0]
    assert db.one("SELECT COUNT(*) AS n FROM messages WHERE conversation_id=?", (conv,))["n"] == 0
    assert db.one("SELECT post_id FROM plan_items WHERE id=?", (item,))["post_id"] is None                # Draft this again
    assert db.one("SELECT acked FROM jobs WHERE id=?", (job,))["acked"] == 1
    assert not folder.exists() and file.exists()                                                         # the copy has it
    assert client.post("/api/trash/delete", json={"ids": [other], "all": True, "confirmed": True}).json()["empty"] is True
    assert client.get("/api/trash").json()["entries"] == [] and db.one("SELECT 1 FROM posts WHERE id=?", (stays,))
    assert to_trash(client, copy).json()["ok"] is True
    assert client.post("/api/trash/delete", json={"all": True, "confirmed": True}).json() == {"ok": True, "count": 1, "empty": True}
    assert not file.exists()                                                                             # nothing uses it now
    assert client.post("/api/trash/delete", json={"all": True, "confirmed": True}).status_code == 404


def test_a_database_made_before_the_trash_opens_with_every_row_as_it_was(tmp_path):
    path = tmp_path / "before.db"
    schema = "\n".join(line for line in SCHEMA.splitlines() if not line.strip().startswith("trashed_at"))
    con = sqlite3.connect(path)
    con.executescript(schema)                                       # the posts table as it was before the Trash
    assert "trashed_at" not in {r[1] for r in con.execute("PRAGMA table_info(posts)")}
    for status in ("draft", "approved", "scheduled", "published"):
        con.execute("INSERT INTO posts (created_at, updated_at, title, text, status) VALUES (?,?,?,?,?)",
                    (utcnow(), utcnow(), "A post", f"A {status} post.", status))
    con.commit()
    before = con.execute("SELECT * FROM posts ORDER BY id").fetchall()
    con.close()
    again = DB(path)
    assert again.started["columns"] == ["posts.trashed_at"] and again.started["tables"] == []
    con = sqlite3.connect(path)
    after = con.execute("SELECT * FROM posts ORDER BY id").fetchall()
    con.close()
    assert [row[:-1] for row in after] == before and all(row[-1] is None for row in after)
