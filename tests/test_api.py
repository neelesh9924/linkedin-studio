"""The JSON API the page draws from: the posts and jobs it polls, the editor's actions with their rules, a post's
picture, every state, the tools, the planner, the interviews and the Guide; and that the page itself can never turn
text into markup or load anything from outside this PC."""
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from conftest import TOKEN, add_job, add_post, with_
from fastapi.testclient import TestClient

from app import guide, images, render
from app.db import DB, dumps, utcnow
from app.main import create_app
from app.publishing import MAX_AHEAD, MIN_LEAD, POST_MAX, Publisher, placeholder_slots
from app.skills import ACTIONS, TOOL_KINDS

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
EVIL = '<img src=x onerror="alert(1)"><script>alert(2)</script>'


@pytest.fixture
def web(cfg, tmp_path, fake_runner):
    (cfg.skills_dir / "references" / "story-bank.md").write_text(
        "# Story Bank\n\n## Status\n\n- filled: yes\n- updated: 2026-10-07\n\n## 1. Timeline\n\n- (role, company)\n\n"
        "## 2. Receipts\n\n- Deploys cut from 22 minutes to 9,\n  team of four\n- " + EVIL + "\n", encoding="utf-8")
    app = create_app(cfg, TOKEN, db_path=tmp_path / "api.db", runner=fake_runner)
    with TestClient(app, base_url=f"http://127.0.0.1:{cfg.port}", headers={"Origin": cfg.origin}) as client:
        client.cookies.set("studio_session", TOKEN)
        yield client, app.state.db


# ---- the page can't be made to run anything -------------------------------------------
def test_the_page_never_turns_text_into_markup():
    """Every piece of text goes in as text (core.h, md.js): no HTML string is ever put into the page."""
    for path in STATIC.rglob("*.js"):
        source = path.read_text(encoding="utf-8")
        assert not re.search(r"\.(innerHTML|outerHTML)\s*=|insertAdjacentHTML|document\.write|\beval\(|new Function\(", source), path.name


def test_the_page_loads_nothing_from_outside_this_pc():
    pattern = re.compile(r"(?:src|href)\s*=\s*[\"']\s*(?:https?:)?//|@import\s+[\"']?(?:https?:)?//|url\(\s*[\"']?(?:https?:)?//"
                         r"|\b(?:from|import)\s*\(?\s*[\"'`]\s*(?:https?:)?//", re.I)
    for path in [*STATIC.rglob("*.js"), *STATIC.rglob("*.css"), *STATIC.rglob("*.html")]:
        assert not pattern.search(path.read_text(encoding="utf-8")), path.name


def test_text_comes_back_as_text(web):
    client, db = web
    post = add_post(db, text=EVIL, title=EVIL, notes=dumps([EVIL]))
    shown = client.get(f"/api/post/{post}").json()
    assert shown["text"] == EVIL and shown["title"] == EVIL and shown["notes"] == [EVIL]   # data, for the page to draw as text
    assert client.get("/").headers["content-type"].startswith("text/html")


# ---- the poll -------------------------------------------------------------------------
def test_state_lists_posts_by_their_first_line_in_a_steady_order(web):
    client, db = web
    published = add_post(db, status="published", text="Shipped it.", scheduled_at="2026-10-01T03:30:00+00:00")
    later = add_post(db, status="scheduled", text="Later one.", scheduled_at="2026-10-20T03:30:00+00:00")
    sooner = add_post(db, status="scheduled", text="Sooner one.", scheduled_at="2026-10-10T03:30:00+00:00")
    draft = add_post(db, text="\n\n  First line here.\nSecond line.")
    empty = add_post(db, text="")
    state = client.get("/api/state").json()
    assert [p["id"] for p in state["posts"]] == [empty, draft, sooner, later, published]
    assert state["posts"][1]["first"] == "First line here." and state["posts"][0]["first"] == "Nothing written yet"
    assert state["posts"][2]["label"] == "Scheduled" and state["posts"][2]["when"] == "Sat 10 Oct, 9:00 am IST"
    assert state["slot"] == placeholder_slots.__globals__["SLOT"].pattern and state["target"]["fold"] == 210


def test_rev_changes_when_something_is_written_and_not_otherwise(web):
    client, db = web
    first = client.get("/api/state").json()["rev"]
    assert client.get("/api/state").json()["rev"] == first
    client.post("/api/posts/new", json={})
    assert client.get("/api/state").json()["rev"] != first


def test_jobs_show_their_numbered_steps_and_end(web):
    client, db = web
    running = add_job(db, "humanize", status="running", params={"source": "tools", "text": "t"}, steps=2,
                      activity=dumps([{"n": 1, "at": "10:00:00", "text": "Loading the skill", "detail": ""},
                                      {"n": 2, "at": "10:00:02", "text": "Reading story-bank.md", "detail": ""}]),
                      progress="Reading story-bank.md", started_at=utcnow(), last_step_at=utcnow())
    job = client.get("/api/state").json()["jobs"][0]
    assert (job["id"], job["steps"], [a["n"] for a in job["activity"]], job["progress"]) == (running, 2, [1, 2], "Reading story-bank.md")
    db.run("UPDATE jobs SET status='done', finished_at=? WHERE id=?", (utcnow(), running))
    ended = client.get("/api/state").json()["ended"][0]
    assert (ended["id"], ended["summary"], ended["href"]) == (running, "Humanize is done", "#~tools-humanize")


# ---- the editor's rules --------------------------------------------------------------------
def test_autosave_stores_the_fields_and_says_what_it_saved(web):
    client, db = web
    post = add_post(db, text="old")
    r = client.post(f"/api/post/{post}/save", json={"text": "Now with [N] blanks\r\nsecond line", "first_comment": " link ", "title": "T"})
    assert r.status_code == 200 and r.json()["chars"] == len("Now with [N] blanks\nsecond line") and r.json()["slots"] == 1
    row = db.one("SELECT * FROM posts WHERE id=?", (post,))
    assert (row["text"], row["first_comment"], row["title"]) == ("Now with [N] blanks\nsecond line", "link", "T")


def test_a_locked_post_is_never_overwritten_by_a_late_save(web):
    client, db = web
    post = add_post(db, status="approved", text="final")
    assert client.post(f"/api/post/{post}/save", json={"text": "sneaky"}).status_code == 409
    assert db.one("SELECT text FROM posts WHERE id=?", (post,))["text"] == "final"


def test_approve_keeps_what_is_on_screen_and_refuses_blanks(web):
    client, db = web
    post = add_post(db, text="old [N]")
    client.post(f"/api/post/{post}/save", json={"text": "Still has [N] in it"})
    r = client.post(f"/api/post/{post}/approve", json={})
    assert r.status_code == 409 and "placeholder" in r.json()["error"]
    assert db.one("SELECT status, text FROM posts WHERE id=?", (post,))[:] == ("draft", "Still has [N] in it")
    client.post(f"/api/post/{post}/save", json={"text": "The text on screen."})
    assert client.post(f"/api/post/{post}/approve", json={}).json() == {"ok": True}
    assert db.one("SELECT status FROM posts WHERE id=?", (post,))["status"] == "approved"


def test_using_a_revision_replaces_the_text_once_and_keeps_both_versions(web):
    client, db = web
    post = add_post(db, text="before", audit=dumps({"verdict": "PASS", "text": "before"}))
    job = add_job(db, "revise", params={"post_id": post, "how": "hook"}, result={"text": "after", "changes": ["x"]})
    revision = client.get(f"/api/post/{post}").json()["revision"]
    assert revision["label"] == "New hook" and revision["segments"] == [["-", "before"], ["+", "after"]]
    assert client.post(f"/api/post/{post}/revision", json={"job": job, "use": 1}).json() == {"used": True}
    shown = client.get(f"/api/post/{post}").json()
    assert shown["text"] == "after" and shown["audit"] is None and shown["revision"] is None
    kept = client.get(f"/api/post/{post}/versions").json()["versions"]
    assert [(v["author"], v["note"]) for v in kept] == [("claude", "New hook"), ("you", "As it was")]


def test_a_post_on_publora_stays_and_any_other_goes_to_the_trash_and_from_there_forever(web):
    client, db = web
    for status in ("scheduling", "scheduled", "published"):
        post = add_post(db, status=status, scheduled_at="2026-10-09T03:30:00+00:00", publora_post_id="pg1")
        assert client.post(f"/api/post/{post}/trash", json={}).status_code == 409
    assert client.post("/api/post/1/delete", json={}).status_code in (404, 405)        # no way round the Trash
    post = add_post(db)
    plan = db.run("INSERT INTO plans (created_at, inputs, result) VALUES (?,?,?)", (utcnow(), "{}", "{}"))
    item = db.run("INSERT INTO plan_items (plan_id, position, data, post_id) VALUES (?,?,?,?)", (plan, 0, "{}", post))
    image = images.save(db, post, b"\x89PNG-one", mime="image/png", source="chatgpt")
    file = images.path_of(db, db.one("SELECT * FROM images WHERE id=?", (image,)))
    client.post(f"/api/post/{post}/ask", json={"text": "hello"})
    assert client.post(f"/api/post/{post}/trash", json={}).status_code in (200, 409)   # 409 while its chat request runs
    from app.jobs import wait_for
    for job in db.all("SELECT id FROM jobs"):
        wait_for(db, job["id"], 15)
    client.post(f"/api/post/{post}/trash", json={})
    assert db.one("SELECT trashed_at FROM posts WHERE id=?", (post,))["trashed_at"] and file.exists()   # all of it kept
    assert client.post("/api/trash/delete", json={"ids": [post], "confirmed": True}).json()["ok"] is True
    assert db.one("SELECT 1 FROM posts WHERE id=?", (post,)) is None and not file.exists()
    assert db.one("SELECT post_id FROM plan_items WHERE id=?", (item,))["post_id"] is None
    assert db.one("SELECT COUNT(*) AS n FROM conversations WHERE post_id=?", (post,))["n"] == 0


# ---- your own edits as versions, the title, New draft from this ---------------------------------
def kept(client, post):
    return [(v["author"], v["note"]) for v in client.get(f"/api/post/{post}/versions").json()["versions"]]


def test_a_big_cut_keeps_the_text_before_it_and_small_edits_do_not(web):
    client, db = web
    hand = "Written by hand, line by line, over an evening.\n\n" * 6
    post = add_post(db, text=hand.strip())
    client.post(f"/api/post/{post}/save", json={"text": hand.strip() + " One more word."})
    assert kept(client, post) == []                                    # typing: no version each second
    client.post(f"/api/post/{post}/save", json={"text": "x"})            # select-all and one key, autosaved
    versions = client.get(f"/api/post/{post}/versions").json()["versions"]
    assert [(v["author"], v["note"]) for v in versions] == [("you", "As it was")]
    assert versions[0]["chars"] == len(hand.strip() + " One more word.")
    back = client.post(f"/api/post/{post}/versions/back", json={"version": versions[0]["id"]}).json()
    assert back == {"changed": True} and db.one("SELECT text FROM posts WHERE id=?", (post,))["text"].startswith("Written by hand")


def test_leaving_the_text_keeps_your_edits_once_and_approve_keeps_the_approved_text(web):
    client, db = web
    post = add_post(db, text="Claude's first draft.")
    from app import versions as kept_versions
    kept_versions.record(db, post, "Claude's first draft.", None, "claude", "First draft")
    client.post(f"/api/post/{post}/save", json={"text": "My own words now."})
    assert client.post(f"/api/post/{post}/checkpoint", json={}).json()["version"]
    assert client.post(f"/api/post/{post}/checkpoint", json={}).json() == {"version": None}   # nothing new since
    assert kept(client, post) == [("you", "Your edits"), ("claude", "First draft")]
    assert client.post(f"/api/post/{post}/approve", json={"text": "My own words, approved."}).json() == {"ok": True}
    assert kept(client, post)[0] == ("you", "Approved")
    assert client.post(f"/api/post/{post}/checkpoint", json={}).json() == {"version": None}   # approved: locked
    refused = add_post(db, text="Still has [N] in it.")
    assert client.post(f"/api/post/{refused}/approve", json={}).status_code == 409 and kept(client, refused) == []


@pytest.mark.parametrize("status", ["draft", "approved", "scheduled", "published", "cancelled"])
def test_the_title_saves_in_any_state_and_alone(web, status):
    client, db = web
    post = add_post(db, status=status, text="The text stays.", scheduled_at="2026-10-09T03:30:00+00:00")
    assert client.post(f"/api/post/{post}/title", json={"title": "  A  better   title "}).json() == {"ok": True, "title": "A better title"}
    assert tuple(db.one("SELECT title, text, status FROM posts WHERE id=?", (post,))) == ("A better title", "The text stays.", status)
    assert client.post(f"/api/post/{post}/title", json={"title": " "}).status_code == 422


def test_new_draft_from_this_copies_the_post_and_shares_its_picture(web):
    client, db = web
    post = add_post(db, status="published", text="Shipped it.", first_comment="The link", formula="F4", notes=dumps(["n"]),
                    scheduled_at="2026-10-01T03:30:00+00:00", publora_post_id="pg1", title="Shipped")
    image = images.save(db, post, b"\x89PNG-shared", mime="image/png", source="chatgpt", width=1200, height=627, shape="landscape")
    db.run("UPDATE posts SET picture_id=? WHERE id=?", (image, post))
    reply = client.post(f"/api/post/{post}/copy", json={}).json()
    new = reply["id"]
    assert reply["post"]["status"] == "draft" and reply["post"]["first"] == "Shipped it."
    shown = client.get(f"/api/post/{new}").json()
    assert (shown["text"], shown["first_comment"], shown["formula"], shown["notes"], shown["editable"]) == ("Shipped it.", "The link", "F4", ["n"], True)
    assert shown["picture"]["id"] != image and db.one("SELECT file FROM images WHERE id=?", (shown["picture"]["id"],))["file"] == \
        db.one("SELECT file FROM images WHERE id=?", (image,))["file"]
    assert kept(client, new) == [("studio", "From Shipped")]
    assert client.get(f"/api/post/{post}").json()["status"] == "published"                # the original is as it was


@pytest.mark.parametrize("status,extra,can", [
    ("draft", {}, {"editable": True, "can_retry": False, "can_back": False, "deletable": True}),
    ("approved", {}, {"editable": False, "can_retry": False, "can_back": True, "deletable": True}),
    ("scheduling", {"scheduled_at": "2026-10-09T03:30:00+00:00"}, {"editable": False, "can_back": False, "deletable": False}),
    ("scheduled", {"scheduled_at": "2026-10-09T03:30:00+00:00", "publora_post_id": "pg1"}, {"can_back": False, "deletable": False}),
    ("published", {"scheduled_at": "2026-10-09T03:30:00+00:00", "publora_post_id": "pg1"}, {"deletable": False}),
    ("failed", {"error": "HTTP 500", "scheduled_at": "2026-10-09T03:30:00+00:00", "publora_payload": "{}"}, {"can_retry": True, "can_back": True}),
    ("failed", {"error": "Publora: boom", "publora_post_id": "pg1"}, {"can_retry": False, "can_back": False}),
    ("cancelled", {"publora_post_id": "pg1"}, {"deletable": True, "can_back": False}),
])
def test_every_state_says_what_can_be_done(web, status, extra, can):
    client, db = web
    shown = client.get(f"/api/post/{add_post(db, status=status, **extra)}").json()
    assert {k: shown[k] for k in can} == can
    assert shown["schedule"] is not None if status == "approved" else shown["schedule"] is None


def test_times_are_shown_in_the_app_zone(web):
    client, db = web
    post = add_post(db, status="scheduled", scheduled_at="2026-10-09T03:30:00+00:00", publora_post_id="pg1")
    assert client.get(f"/api/post/{post}").json()["when"] == "Fri 9 Oct, 9:00 am IST"


# ---- the post's picture -----------------------------------------------------------------------
def test_a_picture_is_chosen_and_removed_only_on_a_draft_and_only_one_of_its_own(web):
    client, db = web
    post = add_post(db)
    other = add_post(db)
    mine = images.save(db, post, b"\x89PNG-mine", mime="image/png", source="chatgpt", width=1200, height=627, shape="landscape")
    theirs = images.save(db, other, b"\x89PNG-theirs", mime="image/png", source="chatgpt")
    assert client.post(f"/api/post/{post}/picture", json={"image": theirs}).status_code == 404
    assert client.post(f"/api/post/{post}/picture", json={"image": mine}).json() == {"ok": True, "picture": mine}
    shown = client.get(f"/api/post/{post}").json()
    assert shown["picture"]["id"] == mine and [p["chosen"] for p in shown["pictures"]] == [True]
    assert client.get("/api/state").json()["posts"][0]["picture"] in (True, False)
    db.run("UPDATE posts SET status='approved' WHERE id=?", (post,))
    assert client.post(f"/api/post/{post}/picture", json={"image": None}).status_code == 409
    db.run("UPDATE posts SET status='draft' WHERE id=?", (post,))
    assert client.post(f"/api/post/{post}/picture", json={"image": None}).json()["picture"] is None
    assert client.get("/api/image/999").status_code == 404


PNG = b"\x89PNG\r\n\x1a\n" + b"the post's picture"


@pytest.fixture
def publora(cfg, tmp_path, fake_runner):
    """The studio with a stand-in Publora that takes pictures (tests/test_publishing.py's)."""
    from test_publishing import FakeClient
    path = tmp_path / "pub.db"
    fake = FakeClient()
    app = create_app(cfg, TOKEN, db_path=path, runner=fake_runner, publisher=Publisher(DB(path), cfg, client_factory=lambda: fake))
    with TestClient(app, base_url=f"http://127.0.0.1:{cfg.port}", headers={"Origin": cfg.origin}) as client:
        client.cookies.set("studio_session", TOKEN)
        yield client, app.state.db, fake


def tomorrow_local(cfg) -> str:
    return (datetime.now(timezone.utc).astimezone(cfg.tz) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")


def test_the_chosen_picture_goes_out_with_the_post(publora, cfg):
    client, db, fake = publora
    post = add_post(db, status="draft", text="A finished post.")
    image = images.save(db, post, PNG, mime="image/png", source="chatgpt", width=1200, height=627, shape="landscape")
    client.post(f"/api/post/{post}/picture", json={"image": image})
    db.run("UPDATE posts SET status='approved' WHERE id=?", (post,))
    r = client.post(f"/api/post/{post}/schedule", json={"when": tomorrow_local(cfg)})
    assert r.json() == {"ok": True, "error": ""}
    assert fake.steps == ["create", "upload_url", "put", "update"] and len(fake.calls) == 1
    assert "scheduledTime" not in fake.calls[0][0]                     # created as a draft, scheduled once it has its picture
    assert fake.puts[0][1:] == (PNG, "image/png") and fake.uploads[0][1] == f"linkedin-studio-{post}-{image}.png"
    assert client.get(f"/api/post/{post}").json()["status"] == "scheduled"


def test_a_picture_post_stopped_part_way_keeps_its_picture_and_publora_draft_until_back_to_draft(publora, cfg):
    import requests
    client, db, fake = publora
    post = add_post(db, status="approved", text="A finished post.")
    image = images.save(db, post, PNG, mime="image/png", source="chatgpt")
    db.run("UPDATE posts SET picture_id=? WHERE id=?", (image, post))
    fake.fail_once["put"] = requests.Timeout("lost")
    assert client.post(f"/api/post/{post}/schedule", json={"when": tomorrow_local(cfg)}).json()["ok"] is False
    shown = client.get(f"/api/post/{post}").json()
    assert shown["status"] == "failed" and shown["can_retry"] and not shown["deletable"]
    assert client.post(f"/api/post/{post}/trash", json={}).status_code == 409    # Publora holds its draft
    assert client.post(f"/api/post/{post}/picture", json={"image": None}).status_code == 409
    assert client.post(f"/api/post/{post}/retry", json={}).json()["ok"] is True  # carries on from the upload
    assert len(fake.calls) == 1 and client.get(f"/api/post/{post}").json()["status"] == "scheduled"


# ---- tools, planner, interviews ---------------------------------------------------------------
def test_tool_input_is_checked_before_any_job_exists(web):
    client, db = web
    r = client.post("/api/tools/humanize", json={"text": "  "})
    assert r.status_code == 422 and "Paste some text" in r.json()["error"]
    assert client.post("/api/tools/nope", json={"text": "x"}).status_code == 404
    assert client.post("/api/tools/humanize", json={"text": "x", "mode": "evil"}).status_code == 422
    assert db.one("SELECT COUNT(*) AS n FROM jobs")["n"] == 0


TOOL_RESULTS = {
    "humanize": {"rewritten": "Better.", "changes": ["a"], "reader_read": "reads human", "missing": ["b"]},
    "audit": {"verdict": "PASS", "summary": "Fine.", "blockers": [], "warnings": [{"issue": "w", "fix": "f"}]},
    "hook": {"formula": "F7", "confidence": "high", "hook": "h", "why": "w", "template": "{slot}", "structure": ["s"], "cautions": ["c"]},
    "comment": {"variants": [{"text": "c1", "reaction": "INTEREST", "template": "T1", "why": "w"}]},
    "repurpose": {"post": "A post.", "formula": "F4", "mapping": ["m"], "first_comment": "link"},
    "profile": {"scorecard": [{"section": "About", "verdict": "fail", "note": "n"}], "priority_fixes": ["p"],
                "rewrites": [{"section": "About", "before": "b", "after": "a"}]},
}


def test_each_tool_shows_its_latest_result_and_a_dismissed_problem_goes(web):
    client, db = web
    for kind, result in TOOL_RESULTS.items():
        add_job(db, kind, params={"source": "tools", "text": "t"}, result=result, finished_at=utcnow())
    tools = {t["kind"]: t for t in client.get("/api/tools").json()["tools"]}
    assert list(tools) == list(TOOL_KINDS)
    assert all(tools[k]["job"]["result"] == r for k, r in TOOL_RESULTS.items())
    assert tools["humanize"]["job"]["compare"] == [["-", "t"], ["+", "Better."]]
    failed = add_job(db, "audit", status="failed", params={"source": "tools", "text": "x"}, error="boom")
    assert {t["kind"]: t for t in client.get("/api/tools").json()["tools"]}["audit"]["job"]["id"] == failed
    client.post(f"/api/jobs/{failed}/dismiss", json={})
    assert {t["kind"]: t for t in client.get("/api/tools").json()["tools"]}["audit"]["job"]["id"] != failed


def test_a_repurposed_post_becomes_a_post_with_its_first_version(web):
    client, db = web
    job = add_job(db, "repurpose", params={"source": "tools", "text": "t"}, result=TOOL_RESULTS["repurpose"])
    post = client.post(f"/api/tools/repurpose/{job}/draft", json={}).json()["post"]
    row = db.one("SELECT * FROM posts WHERE id=?", (post,))
    assert (row["text"], row["first_comment"], row["status"]) == ("A post.", "link", "draft")
    assert [v["note"] for v in client.get(f"/api/post/{post}/versions").json()["versions"]] == ["Repurposed"]


def test_earlier_results_come_per_tool_newest_first_and_each_opens_again(web):
    client, db = web
    first = add_job(db, "humanize", params={"source": "tools", "text": "\n  The first draft line\nmore"}, result=TOOL_RESULTS["humanize"], finished_at=utcnow())
    add_job(db, "humanize", status="failed", params={"source": "tools", "text": "failed one"}, error="boom")
    second = add_job(db, "humanize", params={"source": "tools", "text": "The second one"}, result={"rewritten": "Again."}, finished_at=utcnow())
    add_job(db, "audit", params={"post_id": 1, "text": "a post's own audit"}, result=TOOL_RESULTS["audit"], finished_at=utcnow())
    linked = add_job(db, "hook", params={"source": "tools", "text": "", "url": "https://www.linkedin.com/posts/x"}, result=TOOL_RESULTS["hook"], finished_at=utcnow())
    tools = {t["kind"]: t for t in client.get("/api/tools").json()["tools"]}
    assert [(e["id"], e["first"]) for e in tools["humanize"]["earlier"]] == [(second, "The second one"), (first, "The first draft line")]
    assert tools["audit"]["earlier"] == [] and tools["hook"]["earlier"][0]["first"] == "https://www.linkedin.com/posts/x"
    assert [k for k, t in tools.items() if t["can_post"]] == ["humanize", "audit", "hook", "repurpose"]
    shown = client.get(f"/api/tools/humanize/{first}").json()["job"]
    assert shown["result"] == TOOL_RESULTS["humanize"] and shown["compare"][-1] == ["+", "Better."] and shown["finished_ago"]
    assert client.get(f"/api/tools/audit/{first}").status_code == 404 and client.get(f"/api/tools/hook/{linked}").status_code == 200


def test_start_a_post_from_this_makes_a_draft_with_its_first_version(web):
    client, db = web
    humanized = add_job(db, "humanize", params={"source": "tools", "text": "t"}, result=TOOL_RESULTS["humanize"], finished_at=utcnow())
    post = client.post(f"/api/tools/humanize/{humanized}/draft", json={}).json()["post"]
    shown = client.get(f"/api/post/{post}").json()
    assert (shown["text"], shown["status"], shown["notes"], shown["editable"]) == ("Better.", "draft", ["b"], True)
    assert kept(client, post) == [("claude", "From Humanize")]
    audited = add_job(db, "audit", params={"source": "tools", "text": "My draft,\r\nas pasted. "}, result=TOOL_RESULTS["audit"], finished_at=utcnow())
    post = client.post(f"/api/tools/audit/{audited}/draft", json={}).json()["post"]
    shown = client.get(f"/api/post/{post}").json()
    assert shown["text"] == "My draft,\nas pasted." and kept(client, post) == [("you", "From Audit")]
    assert shown["audit"]["verdict"] == "PASS" and shown["audit"]["stale"] is False             # its findings beside it
    hooked = add_job(db, "hook", params={"source": "tools", "text": "t"}, result=TOOL_RESULTS["hook"], finished_at=utcnow())
    post = client.post(f"/api/tools/hook/{hooked}/draft", json={}).json()["post"]
    assert client.get(f"/api/post/{post}").json()["text"] == "{slot}" and kept(client, post) == [("claude", "From Hook extractor")]


def test_start_a_post_is_refused_for_comment_drafts_the_profile_review_and_results_not_here(web):
    client, db = web
    before = db.one("SELECT COUNT(*) AS n FROM posts")["n"]
    for kind in ("comment", "profile"):
        job = add_job(db, kind, params={"source": "tools", "text": "t"}, result=TOOL_RESULTS[kind], finished_at=utcnow())
        refused = client.post(f"/api/tools/{kind}/{job}/draft", json={})
        assert refused.status_code == 422 and "not a post" in refused.json()["error"]
    running = add_job(db, "humanize", status="running", params={"source": "tools", "text": "t"})
    assert client.post(f"/api/tools/humanize/{running}/draft", json={}).status_code == 404
    assert client.post("/api/tools/nope/1/draft", json={}).status_code == 404
    empty = add_job(db, "humanize", params={"source": "tools", "text": "t"}, result={"rewritten": "  "}, finished_at=utcnow())
    assert client.post(f"/api/tools/humanize/{empty}/draft", json={}).status_code == 422
    assert db.one("SELECT COUNT(*) AS n FROM posts")["n"] == before


def test_the_planner_shows_this_month_and_both_plan_shapes(web):
    client, db = web
    old = {"items": [{"day": "Tue", "angle": "old angle"}], "comment_targets": ["Tue: peers"], "readiness": ["Vulnerability post: missing"]}
    new = {"items": [{"day": "Thu", "time": "8:00 AM", "angle": "new angle", "goal": "saves"}],
           "comment_targets": [{"day": "Thu", "who": "peers", "pattern": "data-first"}],
           "readiness": [{"check": "One receipt post", "ok": True}]}
    for result in (old, new):
        plan = db.run("INSERT INTO plans (created_at, inputs, result) VALUES (?,?,?)",
                      (utcnow(), dumps({"audience": "engineers", "max_posts": 3}), dumps(result)))
        for i, item in enumerate(result["items"]):
            db.run("INSERT INTO plan_items (plan_id, position, data) VALUES (?,?,?)", (plan, i, dumps(item)))
    add_post(db, status="scheduled", scheduled_at="2099-10-09T03:30:00+00:00", publora_post_id="pg1", text="Coming up.")
    data = client.get("/api/planner").json()
    assert [b["items"][0]["angle"] for b in data["boards"]] == ["new angle", "old angle"]
    assert data["boards"][1]["comment_targets"] == ["Tue: peers"] and data["next"]["first"] == "Coming up."
    assert (data["used"], data["limit"]) == (0, 15) and len(data["steps"]) == 4
    item = data["boards"][0]["items"][0]["id"]
    assert "job" in client.post(f"/api/planner/items/{item}/draft", json={}).json()
    assert client.post(f"/api/planner/items/{item}/draft", json={}).status_code == 422   # already being drafted
    assert client.post("/api/planner", json={"audience": "", "goal": "x"}).status_code == 422


def test_an_interview_thread_shows_file_changes_and_waits_for_its_reply(web):
    client, db = web
    conv = db.run("INSERT INTO conversations (mode, session_id, created_at) VALUES ('bank', 's1', ?)", (utcnow(),))
    db.run("INSERT INTO messages (conversation_id, role, text, diff, created_at) VALUES (?,?,?,?,?)",
           (conv, "assistant", "Noted.", "--- a\n+++ b\n+new line\n-old line\n", utcnow()))
    add_job(db, "interview", status="running", params={"conversation_id": conv}, progress="Writing")
    chat = client.get(f"/api/chat/bank?c={conv}").json()
    assert chat["busy"] and chat["messages"][0]["diff"] == {"text": "--- a\n+++ b\n+new line\n-old line\n", "added": 1, "removed": 1}
    assert chat["doc"]["name"] == "story-bank.md" and chat["doc"]["is_filled"]
    assert client.post("/api/chat/bank/send", json={"text": "again", "conversation": conv}).status_code == 409
    bank = client.get("/api/bank").json()["files"]["bank"]
    assert bank["filled"] == 1 and [s["title"] for s in bank["sections"]] == ["1. Timeline", "2. Receipts"] and EVIL in bank["text"]


# ---- guide --------------------------------------------------------------------------------------
PAGES = ({"#~planner", "#~bank", "#~voice", "#~tools", "#~settings", "#~guide", "#~trash", "#~posts"}
         | {f"#~tools-{k}" for k in TOOL_KINDS}
         | {f"#~settings-{k}" for k in ("claude", "publishing", "chatgpt", "profile", "appearance", "health", "runs", "app")})


def test_the_guide_covers_every_step_and_screen_with_links_the_page_opens(web):
    client, _db = web
    data = client.get("/api/guide").json()
    steps = [s for lane in data["lanes"] for s in lane["steps"]]
    assert [s["id"] for s in steps] == [s["id"] for lane in guide.LANES for s in lane["steps"]]
    assert {s["href"] for s in steps} | {s["href"] for s in data["screens"]} <= PAGES
    tools = next(s for s in data["screens"] if s["key"] == "tools")
    assert all(f"{ACTIONS[k].title}: {ACTIONS[k].blurb}" in tools["points"] for k in TOOL_KINDS)
    icons = set(re.findall(r'^\s*"?([\w-]+)"?: \[', (STATIC / "js" / "core.js").read_text(encoding="utf-8"), re.M))
    assert {s["icon"] for s in steps} | {s["icon"] for s in data["screens"]} <= icons
    assert [name for name, _meaning, _can in data["states"]] == ["Draft", "Approved", "Scheduled", "Published"]
    assert len(placeholder_slots(data["sample"])) == 2


def test_the_guide_quotes_the_limits_the_app_enforces(cfg, tmp_path, fake_runner):
    app = create_app(with_(cfg, monthly_post_limit=7), TOKEN, db_path=tmp_path / "guide.db", runner=fake_runner)
    with TestClient(app, base_url=f"http://127.0.0.1:{cfg.port}", headers={"Origin": cfg.origin}) as client:
        client.cookies.set("studio_session", TOKEN)
        body = client.get("/api/guide").text
    assert "counts toward your 7 for the month" in body and f"past {POST_MAX:,} characters" in body
    assert f"between {int(MIN_LEAD.total_seconds() // 60)} minutes and {MAX_AHEAD.days} days ahead" in body
    assert not re.search(r"\{[a-z_]+\}", body)


def test_words_and_times_helpers():
    assert render.wdiff("old text", "new text") == [["-", "old"], ["+", "new"], ["=", " text"]]
    assert render.diffstat("--- a\n+++ b\n+x\n+y\n-z\n same") == (2, 1)
    text = "## Status\n\n- filled: yes\n\n## 1. Timeline\n\n- (role, company)\n\n## 2. Receipts\n\n- 22 minutes to 9\n- Emoji: (none)\n"
    assert [(s["title"], s["filled"]) for s in render.doc_sections(text)] == [("1. Timeline", 0), ("2. Receipts", 1)]
