"""The web layer the redesign added: safe rendering, region partials, save-then-act, delete rules."""
import json
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import pytest
from conftest import with_
from fastapi.testclient import TestClient
from markupsafe import escape

from app import guide, render
from app.db import dumps, utcnow
from app.icons import ICONS
from app.main import create_app
from app.publishing import MAX_AHEAD, MIN_LEAD, POST_MAX, placeholder_slots
from app.skills import ACTIONS, TOOL_KINDS

TOKEN = "t0ken-for-tests"
EVIL = '<img src=x onerror="alert(1)"><script>alert(2)</script>'


@pytest.fixture
def web(cfg, tmp_path, fake_runner):
    (cfg.skills_dir / "references" / "story-bank.md").write_text(
        "# Story Bank\n\n## Status\n\n- filled: yes\n- updated: 2026-10-07\n\n## 1. Timeline\n\n- (role, company)\n\n"
        "## 2. Receipts\n\n- Deploys cut from 22 minutes to 9,\n  team of four\n- " + EVIL + "\n", encoding="utf-8")
    app = create_app(cfg, TOKEN, db_path=tmp_path / "ui.db", runner=fake_runner)
    with TestClient(app, base_url=f"http://127.0.0.1:{cfg.port}", headers={"Origin": cfg.origin}) as client:
        client.cookies.set("studio_session", TOKEN)
        yield client, app.state.db


def add_post(db, status="draft", text="A finished post.", **extra):
    now = utcnow()
    cols = {"created_at": now, "updated_at": now, "title": "A post", "text": text, "status": status, **extra}
    return db.run(f"INSERT INTO posts ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", tuple(cols.values()))


def add_job(db, kind, status="done", params=None, result=None, **extra):
    cols = {"kind": kind, "status": status, "params": dumps(params or {}), "created_at": utcnow(),
            "result": dumps(result) if result is not None else None, **extra}
    return db.run(f"INSERT INTO jobs ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", tuple(cols.values()))


# ---- rendering is safe ---------------------------------------------------------------
def test_markdown_escapes_html_and_keeps_formatting():
    html = str(render.md(f"**bold** and `code`\n\n{EVIL}\n\n- item {EVIL}\n\n> quote {EVIL}\n\n| a | b |\n|---|---|\n| {EVIL} | x |"))
    assert "<script" not in html and "<img" not in html
    assert "<strong>bold</strong>" in html and "<code>code</code>" in html and "<blockquote>" in html and "<table>" in html


def test_markdown_reflows_hard_wrapped_text_but_chat_keeps_line_breaks():
    doc = str(render.md("one line\nwrapped here\n\n- item starts\n  and continues"))
    assert "<p>one line wrapped here</p>" in doc and "<li>item starts and continues</li>" in doc
    chat = str(render.md("Moment: a\nNumber: b", breaks=True))
    assert "Moment: a<br>Number: b" in chat


def test_diffs_escape_html():
    assert "<script" not in str(render.wdiff("old " + EVIL, "new " + EVIL))
    assert "<script" not in str(render.udiff("+" + EVIL + "\n-gone\n@@ -1 +1 @@"))
    assert "<ins>new</ins>" in str(render.wdiff("old text", "new text"))
    assert render.diffstat("--- a\n+++ b\n+x\n+y\n-z\n same") == (2, 1)


def test_story_bank_sections_count_only_real_material():
    text = ("## Status\n\n- filled: yes\n\n## 1. Timeline\n\n- (role, company)\n\n## 2. Receipts\n\n- 22 minutes to 9\n"
            "- Emoji: (none)\n- Rhythm: short\n\n## How drafts use this\n\n- not a numbered section\n")
    sections = render.doc_sections(text)
    assert [(s["title"], s["filled"]) for s in sections] == [("1. Timeline", 0), ("2. Receipts", 2)]


def test_pages_escape_text_from_files_and_from_claude(web):
    client, db = web
    conv = db.run("INSERT INTO conversations (mode, created_at) VALUES ('bank', ?)", (utcnow(),))
    db.run("INSERT INTO messages (conversation_id, role, text, diff, created_at) VALUES (?,?,?,?,?)",
           (conv, "assistant", f"**Hi** {EVIL}", f"+{EVIL}", utcnow()))
    post = add_post(db, text=EVIL, title=EVIL, notes=dumps([EVIL]), audit=dumps({"verdict": "FAIL", "summary": EVIL,
                    "blockers": [{"issue": EVIL, "fix": EVIL}], "text": EVIL}))
    add_job(db, "humanize", params={"source": "tools", "text": EVIL}, result={"rewritten": EVIL, "changes": [EVIL]})
    for path in ("/bank", "/interviewer", f"/drafts/{post}", "/drafts", "/tools", "/"):
        body = client.get(path).text
        assert "<script>alert(2)</script>" not in body and "<img src=x" not in body, path


# ---- jobs ----------------------------------------------------------------------------
def test_tick_escapes_progress_and_announces_the_end(web):
    client, db = web
    running = add_job(db, "humanize", status="running", progress='Reading <b onmouseover="x">evil</b>.md')
    r = client.get(f"/jobs/{running}/tick")
    assert r.status_code == 200 and "<b" not in r.text and "&lt;b" in r.text
    done = add_job(db, "humanize", status="done")
    r = client.get(f"/jobs/{done}/tick")
    assert r.status_code == 286
    assert json.loads(r.headers["hx-trigger"]) == {"jobs-changed": {"id": done, "kind": "humanize", "status": "done"}}


def test_summary_links_to_where_the_result_lives(web):
    client, db = web
    post = add_post(db)
    draft = add_job(db, "draft", params={"post_id": post})
    failed = add_job(db, "plan", status="failed")
    chat = add_job(db, "interview", params={"conversation_id": 7})
    assert client.get(f"/jobs/{draft}/summary").json() == {
        "job": "draft", "status": "done", "href": f"/drafts/{post}", "kind": "ok", "text": "Your draft is ready"}
    assert client.get(f"/jobs/{failed}/summary").json()["kind"] == "error"
    assert client.get(f"/jobs/{chat}/summary").json()["href"] == "/interviewer?mode=bank&c=7"


def test_dismiss_hides_a_problem_and_cancel_needs_no_card(web):
    client, db = web
    failed = add_job(db, "humanize", status="failed", params={"source": "tools", "text": "x"}, error="boom")
    assert "did not finish" in client.get("/tools/humanize/out").text
    assert client.post(f"/jobs/{failed}/dismiss").status_code == 204
    assert "did not finish" not in client.get("/tools/humanize/out").text
    cancelled = add_job(db, "humanize", status="cancelled", params={"source": "tools", "text": "x"})
    assert f'data-job="{cancelled}"' not in client.get("/tools/humanize/out").text


def test_tool_input_is_validated_before_any_job_exists(web):
    client, db = web
    r = client.post("/tools/humanize", data={"text": "  "})
    assert r.status_code == 422 and "Paste some text" in r.json()["error"]
    assert client.post("/tools/nope", data={"text": "x"}).status_code == 404
    assert db.one("SELECT COUNT(*) AS n FROM jobs")["n"] == 0


# ---- the draft editor ----------------------------------------------------------------
def test_autosave_stores_fields_and_reports_what_it_saved(web):
    client, db = web
    post = add_post(db, text="old")
    r = client.post(f"/drafts/{post}/save", data={"text": "Now with [N] blanks\r\nsecond line", "first_comment": " link ", "title": "T"})
    assert r.status_code == 204
    saved = json.loads(r.headers["hx-trigger"])["saved"]
    assert saved["chars"] == len("Now with [N] blanks\nsecond line") and saved["slots"] == 1
    row = db.one("SELECT * FROM posts WHERE id=?", (post,))
    assert (row["text"], row["first_comment"], row["title"]) == ("Now with [N] blanks\nsecond line", "link", "T")


def test_locked_posts_cannot_be_overwritten_by_a_late_save(web):
    client, db = web
    post = add_post(db, status="approved", text="final")
    assert client.post(f"/drafts/{post}/save", data={"text": "sneaky"}).status_code == 409
    assert db.one("SELECT text FROM posts WHERE id=?", (post,))["text"] == "final"


def test_approve_saves_what_is_on_screen_first(web):
    client, db = web
    post = add_post(db, text="old text")
    r = client.post(f"/drafts/{post}/approve", data={"text": "The text on screen.", "title": "T", "first_comment": ""})
    assert r.status_code == 204 and r.headers["hx-redirect"] == f"/drafts/{post}?done=approved"
    row = db.one("SELECT * FROM posts WHERE id=?", (post,))
    assert (row["status"], row["text"]) == ("approved", "The text on screen.")


def test_approve_with_blanks_is_refused_but_keeps_the_typing(web):
    client, db = web
    post = add_post(db, text="old")
    r = client.post(f"/drafts/{post}/approve", data={"text": "Still has [N] in it", "title": "T", "first_comment": ""})
    assert r.status_code == 409 and "placeholder" in r.json()["error"]
    row = db.one("SELECT * FROM posts WHERE id=?", (post,))
    assert (row["status"], row["text"]) == ("draft", "Still has [N] in it")


def test_using_a_revision_replaces_the_text_once(web):
    client, db = web
    post = add_post(db, text="before", audit=dumps({"verdict": "PASS", "text": "before"}))
    job = add_job(db, "revise", params={"post_id": post, "how": "hook"}, result={"text": "after", "changes": ["x"]})
    assert "Revised version" in client.get(f"/drafts/{post}/revision").text
    r = client.post(f"/drafts/{post}/revision/{job}", data={"use": 1})
    assert r.headers["hx-redirect"] == f"/drafts/{post}?done=revised"
    row = db.one("SELECT * FROM posts WHERE id=?", (post,))
    assert row["text"] == "after" and row["audit"] is None
    assert "Revised version" not in client.get(f"/drafts/{post}/revision").text


def test_delete_is_refused_once_a_post_is_on_publora(web):
    client, db = web
    for status in ("scheduling", "scheduled", "published"):
        post = add_post(db, status=status, scheduled_at="2026-10-09T03:30:00+00:00", publora_post_id="pg1")
        assert client.post(f"/drafts/{post}/delete").status_code == 409
        assert db.one("SELECT 1 FROM posts WHERE id=?", (post,)) is not None


def test_deleting_a_draft_frees_its_plan_item(web):
    client, db = web
    post = add_post(db)
    plan = db.run("INSERT INTO plans (created_at, inputs, result) VALUES (?,?,?)", (utcnow(), "{}", "{}"))
    item = db.run("INSERT INTO plan_items (plan_id, position, data, post_id) VALUES (?,?,?,?)", (plan, 0, "{}", post))
    r = client.post(f"/drafts/{post}/delete")
    assert r.headers["hx-redirect"] == "/drafts?done=deleted"
    assert db.one("SELECT 1 FROM posts WHERE id=?", (post,)) is None
    assert db.one("SELECT post_id FROM plan_items WHERE id=?", (item,))["post_id"] is None


def test_only_known_flash_messages_are_shown(web):
    client, _db = web
    assert 'data-flash-text="Draft deleted."' in client.get("/drafts?done=deleted").text
    assert "data-flash-text" not in client.get("/drafts?done=<script>alert(1)</script>").text


# ---- every state renders ---------------------------------------------------------------
@pytest.mark.parametrize("status,extra,expect", [
    ("draft", {}, "Approve this text"),
    ("approved", {}, "Schedule…"),
    ("scheduling", {"scheduled_at": "2026-10-09T03:30:00+00:00"}, "Sending to Publora"),
    ("scheduled", {"scheduled_at": "2026-10-09T03:30:00+00:00", "publora_post_id": "pg1"}, "Cancel on Publora"),
    ("published", {"scheduled_at": "2026-10-09T03:30:00+00:00", "publora_post_id": "pg1"}, "Published"),
    ("failed", {"error": "HTTP 500", "scheduled_at": "2026-10-09T03:30:00+00:00", "publora_payload": "{}"}, "Try again"),
    ("failed", {"error": "Publora: boom", "publora_post_id": "pg1"}, "could not publish"),
    ("cancelled", {"publora_post_id": "pg1"}, "It was never published"),
])
def test_draft_page_renders_in_every_status(web, status, extra, expect):
    client, db = web
    post = add_post(db, status=status, **extra)
    page = client.get(f"/drafts/{post}")
    assert page.status_code == 200 and expect in page.text
    assert client.get(f"/drafts/{post}/rail").status_code == 200
    assert client.get("/").status_code == 200 and client.get("/drafts").status_code == 200


def test_times_are_shown_in_the_app_zone(web):
    client, db = web
    post = add_post(db, status="scheduled", scheduled_at="2026-10-09T03:30:00+00:00", publora_post_id="pg1")
    assert "Fri 9 Oct, 9:00 am IST" in client.get(f"/drafts/{post}").text


TOOL_RESULTS = {
    "humanize": {"rewritten": "Better.", "changes": ["a"], "reader_read": "reads human", "missing": ["b"]},
    "audit": {"verdict": "PASS", "summary": "Fine.", "blockers": [], "warnings": [{"issue": "w", "fix": "f"}]},
    "hook": {"formula": "F7", "confidence": "high", "hook": "h", "why": "w", "template": "{slot}", "structure": ["s"], "cautions": ["c"]},
    "comment": {"variants": [{"text": "c1", "reaction": "INTEREST", "template": "T1", "why": "w"}]},
    "repurpose": {"post": "A post.", "formula": "F4", "mapping": ["m"], "first_comment": "link"},
    "profile": {"scorecard": [{"section": "About", "verdict": "fail", "note": "n"}], "priority_fixes": ["p"],
                "rewrites": [{"section": "About", "before": "b", "after": "a"}]},
}


@pytest.mark.parametrize("kind", sorted(TOOL_RESULTS))
def test_every_tool_result_and_state_renders(web, kind):
    client, db = web
    assert "Nothing here yet" in client.get(f"/tools/{kind}/out").text
    queued = add_job(db, kind, status="queued", params={"source": "tools", "text": "t"})
    assert f"/jobs/{queued}/tick" in client.get(f"/tools/{kind}/out").text
    db.run("UPDATE jobs SET status='done', result=? WHERE id=?", (dumps(TOOL_RESULTS[kind]), queued))
    out = client.get(f"/tools/{kind}/out")
    assert out.status_code == 200 and "Finished" in out.text
    assert client.get(f"/tools?tool={kind}").status_code == 200


def test_repurposed_post_becomes_a_draft(web):
    client, db = web
    job = add_job(db, "repurpose", params={"source": "tools", "text": "t"}, result=TOOL_RESULTS["repurpose"])
    r = client.post(f"/tools/repurpose/{job}/draft")
    assert r.status_code == 204 and r.headers["hx-redirect"].endswith("?done=created")
    row = db.one("SELECT * FROM posts ORDER BY id DESC LIMIT 1")
    assert (row["text"], row["first_comment"], row["status"]) == ("A post.", "link", "draft")


def test_planner_board_renders_new_and_old_plan_shapes(web):
    client, db = web
    old = {"items": [{"day": "Tue", "angle": "old angle"}], "comment_targets": ["Tue: peers"], "readiness": ["Vulnerability post: missing"]}
    new = {"items": [{"day": "Thu", "time": "8:00 AM", "angle": "new angle", "goal": "saves"}],
           "comment_targets": [{"day": "Thu", "who": "peers", "pattern": "data-first"}],
           "readiness": [{"check": "One receipt post", "ok": True}, {"check": "A soft offer", "ok": False}]}
    for result in (old, new):
        plan = db.run("INSERT INTO plans (created_at, inputs, result) VALUES (?,?,?)",
                      (utcnow(), dumps({"audience": "engineers", "max_posts": 3}), dumps(result)))
        for i, item in enumerate(result["items"]):
            db.run("INSERT INTO plan_items (plan_id, position, data) VALUES (?,?,?)", (plan, i, dumps(item)))
    board = client.get("/planner/board").text
    assert "new angle" in board and "old angle" in board and "Earlier plans" in board
    assert 'class="yes"' in board and 'class="no"' in board
    assert client.get("/planner").status_code == 200 and client.get("/").status_code == 200


def test_interviewer_thread_shows_file_changes_and_waiting_state(web):
    client, db = web
    conv = db.run("INSERT INTO conversations (mode, session_id, created_at) VALUES ('bank', 's1', ?)", (utcnow(),))
    db.run("INSERT INTO messages (conversation_id, role, text, diff, created_at) VALUES (?,?,?,?,?)",
           (conv, "assistant", "Noted.", "--- a\n+++ b\n+new line\n-old line\n", utcnow()))
    job = add_job(db, "interview", status="running", params={"conversation_id": conv}, progress="Writing")
    db.run("INSERT INTO messages (conversation_id, role, text, job_id, created_at) VALUES (?,?,?,?,?)",
           (conv, "user", "My answer", job, utcnow()))
    thread = client.get(f"/interviewer/bank/thread?c={conv}").text
    assert 'data-busy="1"' in thread and "Saved to story-bank.md" in thread and f"/jobs/{job}/tick" in thread
    assert client.get(f"/interviewer?mode=bank&c={conv}").status_code == 200
    assert client.post("/interviewer/bank/send", data={"text": "again", "conversation_id": conv}).status_code == 422


# ---- guide ---------------------------------------------------------------------------
GUIDE_STEPS = [step for lane in guide.LANES for step in lane["steps"]]


def test_guide_shows_every_step_and_screen_and_is_one_click_from_any_page(web):
    client, _db = web
    body = client.get("/guide").text
    for step in GUIDE_STEPS:
        assert f'data-step="{step["id"]}"' in body and f'data-step-panel="{step["id"]}"' in body, step["id"]
    for screen in guide.SCREENS:
        assert f'data-tab="{screen["key"]}"' in body and f'data-tab-panel="{screen["key"]}"' in body, screen["key"]
    assert "built-in method" not in body                       # a content key that collides with a dict method
    for kind in TOOL_KINDS:                                    # each tool is described, in the Tools page's own words
        assert str(escape(f"{ACTIONS[kind].title}: {ACTIONS[kind].blurb}")) in body, kind
    assert 'href="/guide"' in client.get("/settings").text     # the ? button in the top bar


def test_guide_quotes_the_limits_the_app_enforces(cfg, tmp_path, fake_runner):
    app = create_app(with_(cfg, monthly_post_limit=7), TOKEN, db_path=tmp_path / "guide.db", runner=fake_runner)
    with TestClient(app, base_url=f"http://127.0.0.1:{cfg.port}", headers={"Origin": cfg.origin}) as client:
        client.cookies.set("studio_session", TOKEN)
        body = client.get("/guide").text
    assert "counts toward your 7 for the month" in body
    assert f"past {POST_MAX:,} characters" in body
    assert f"between {int(MIN_LEAD.total_seconds() // 60)} minutes and {MAX_AHEAD.days} days ahead" in body
    assert not re.search(r"\{[a-z_]+\}", body)                 # no number was left as a {placeholder}


def test_every_guide_link_opens_the_page_it_names(web):
    client, _db = web
    for href in sorted({s["href"] for s in GUIDE_STEPS} | {s["href"] for s in guide.SCREENS}):
        assert client.get(href).status_code == 200, href
        query = dict(parse_qsl(urlsplit(href).query))           # an unknown tool or mode would fall back silently
        assert query.get("tool", "humanize") in TOOL_KINDS and query.get("mode", "bank") in ("bank", "voice"), href


def test_every_guide_picture_is_there_in_both_themes(web):
    client, _db = web
    for screen in guide.SCREENS:
        for theme in ("light", "dark"):
            assert client.get(f"/static/guide/{screen['key']}-{theme}.png").status_code == 200, (screen["key"], theme)


def test_guide_content_only_names_things_the_page_can_draw():
    template = (Path(guide.__file__).parent / "templates" / "guide.html").read_text(encoding="utf-8")
    assert {s["demo"] for s in GUIDE_STEPS} <= set(re.findall(r"kind == '(\w+)'", template))
    assert {s["icon"] for s in GUIDE_STEPS} | {s["icon"] for s in guide.SCREENS} <= set(ICONS)
    assert [name for name, _meaning, _can in guide.STATES] == ["Draft", "Approved", "Scheduled", "Published"]
    assert len(placeholder_slots(guide.SAMPLE_POST)) == 2       # "Next blank" needs something to find
