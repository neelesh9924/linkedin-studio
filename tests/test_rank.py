"""A post's rank (rank.py): the owner's own number or Claude's (set_rank over /mcp), kept on the post with why; drafts
listed best first, any not ranked yet on top; a rank only informs."""
import threading

import pytest
from conftest import TOKEN, add_post
from fastapi.testclient import TestClient

from app import rank
from app.jobs import Run
from app.main import create_app
from app.mcp import Studio, handle


@pytest.fixture
def web(cfg, tmp_path, fake_runner):
    app = create_app(cfg, TOKEN, db_path=tmp_path / "rank.db", runner=fake_runner)
    with TestClient(app, base_url=f"http://127.0.0.1:{cfg.port}", headers={"Origin": cfg.origin}) as client:
        client.cookies.set("studio_session", TOKEN)
        yield client, app.state.db


def test_the_verdicts_follow_the_number():
    assert [rank.verdict_of(n) for n in (10, 7, 6, 5, 4, 1)] == ["post", "post", "strengthen", "strengthen", "drop", "drop"]
    for bad in (0, 11, 7.5, "8", True, None):
        with pytest.raises(rank.Refused):
            rank.number(bad)


def test_the_owners_number_is_kept_with_claudes_reason_and_can_come_off(web):
    client, db = web
    post = add_post(db)
    assert client.get(f"/api/post/{post}").json()["rank"] is None
    db.run("UPDATE posts SET rank=?, rank_note=? WHERE id=?", (5, rank.note(5, "Common knowledge.", "Add the trap."), post))
    shown = client.get(f"/api/post/{post}").json()["rank"]
    assert (shown["rank"], shown["verdict"], shown["label"], shown["by"]) == (5, "strengthen", "Strengthen it first", "claude")
    assert client.post(f"/api/post/{post}/rank", json={"rank": 11}).status_code == 422
    mine = client.post(f"/api/post/{post}/rank", json={"rank": 8}).json()["rank"]
    assert (mine["rank"], mine["by"], mine["why"], mine["verdict"]) == (8, "you", "Common knowledge.", "post")
    assert client.post(f"/api/post/{post}/rank", json={"rank": None}).json() == {"ok": True, "rank": None}
    assert client.get(f"/api/post/{post}").json()["rank"] is None
    assert client.post(f"/api/post/{post}/rank", json={"rank": 6, "by": "someone"}).status_code == 422
    audit = client.post(f"/api/post/{post}/rank", json={"rank": 4, "by": "claude", "why": "Generic.", "fix": "Drop it."}).json()["rank"]
    assert (audit["rank"], audit["by"], audit["why"], audit["fix"], audit["label"]) == (4, "claude", "Generic.", "Drop it.", "Not worth a post")


def test_drafts_list_unranked_first_then_best_first(web):
    client, db = web
    low, high, mid, new = add_post(db), add_post(db), add_post(db), add_post(db)
    for post, n in ((low, 3), (high, 9), (mid, 6)):
        client.post(f"/api/post/{post}/rank", json={"rank": n})
    approved = add_post(db, status="approved")
    order = [p["id"] for p in client.get("/api/state").json()["posts"]]
    assert order[:5] == [new, high, mid, low, approved]
    assert [p["rank"] for p in client.get("/api/state").json()["posts"]][:4] == [None, 9, 6, 3]


def test_set_rank_from_a_posts_chat_keeps_the_number_and_why(web, cfg):
    client, db = web
    post = add_post(db, status="scheduled", scheduled_at="2026-10-09T03:30:00+00:00", publora_post_id="pg1")
    run = Run(job_id=1, kind="post_chat", params={"post_id": post}, token="t", tools=("record_audit", "set_rank"),
              cancel=threading.Event(), note=lambda *_a: None)
    studio = Studio(db=db, cfg=cfg)

    def call(args):
        reply = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "set_rank", "arguments": args}},
                       run, studio)["result"]
        return reply["content"][0]["text"], reply["isError"]
    assert call({"rank": 12, "why": "x"})[1] and call({"rank": 6, "why": " "})[1]
    said, failed = call({"rank": 4, "why": "Every tutorial covers it.", "fix": "Fold it into the pagination post."})
    assert not failed and "4/10" in said and "not worth a post" in said
    shown = client.get(f"/api/post/{post}").json()["rank"]                   # any post can be ranked, scheduled too
    assert (shown["rank"], shown["by"], shown["fix"]) == (4, "claude", "Fold it into the pagination post.")
