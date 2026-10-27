"""A post's Ask Claude chat: what each request carries, the studio's tools Claude changes the post with (over /mcp, on
its run's own token), the versions each change keeps, pictures, and how a run that did not finish is said."""
import base64
import threading
import time

import pytest
from conftest import TOKEN, add_post
from fastapi.testclient import TestClient
from support import PNG

from app import codex, mcp, versions
from app.claude_runner import RunResult, build_command
from app.db import loads
from app.jobs import wait_for
from app.main import create_app
from app.skills import ACTIONS


class StandIn:
    """Stands in for ClaudeRunner in a post's chat: keeps each request, and does what `script` says while it runs
    (calls the studio's tools as Claude would), until the test lets it end."""

    def __init__(self):
        self.requests = []
        self.script = None          # fn(req) -> RunResult, run on the job's thread
        self.hold = threading.Event()
        self.hold.set()

    def run(self, req, cancel=None, on_progress=None, timeout=None):
        self.requests.append(req)
        if on_progress:
            on_progress("Loading the skill")
        while not self.hold.wait(0.05):
            if cancel is not None and cancel.is_set():
                return RunResult(outcome="cancelled", error="Cancelled.")
        if self.script:
            return self.script(req)
        return RunResult(outcome="ok", text="Here is what I think.", clean_text="Here is what I think.")


@pytest.fixture
def studio(cfg, tmp_path):
    runner = StandIn()
    app = create_app(cfg, TOKEN, db_path=tmp_path / "chat.db", runner=runner)
    with TestClient(app, base_url=f"http://127.0.0.1:{cfg.port}", headers={"Origin": cfg.origin}) as client:
        client.cookies.set("studio_session", TOKEN)
        yield client, app, runner


def tool(client, req, name, arguments, token=None):
    """One call of a studio tool over /mcp, with the run's own token (as Claude calls it)."""
    body = {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
    r = client.post("/mcp", json=body, headers={"Authorization": f"Bearer {token or req.mcp['token']}"})
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    return result["content"][0]["text"], result["isError"]


def ask(client, post_id, text):
    r = client.post(f"/api/post/{post_id}/ask", json={"text": text})
    assert r.status_code == 200, r.text
    return r.json()["job"]


# ---- what a request carries ------------------------------------------------------------
def test_a_request_carries_the_post_the_conversation_and_the_new_message(studio):
    client, app, runner = studio
    db = app.state.db
    post = add_post(db, text="Line one of the post.\n\nWe cut deploys to [N] minutes.", first_comment="Link: https://x.example")
    wait_for(db, ask(client, post, "Make the hook sharper"), 10)
    wait_for(db, ask(client, post, "And shorter"), 10)
    req = runner.requests[-1]
    assert "Line one of the post." in req.prompt and "1 blank(s)" in req.prompt and "Link: https://x.example" in req.prompt
    assert "The owner: Make the hook sharper" in req.prompt and "You (Claude): Here is what I think." in req.prompt
    assert req.prompt.rstrip().endswith("The owner's new message:\nAnd shorter")
    assert "<<<UNTRUSTED POST" in req.prompt            # the post's text is data, never instructions
    assert req.system == ACTIONS["post_chat"].rules and "set_post_text" in req.system and "make_image" in req.system


def test_the_run_gets_the_skills_and_its_own_tools_and_nothing_else(studio, cfg):
    client, app, runner = studio
    db = app.state.db
    wait_for(db, ask(client, add_post(db), "Audit it"), 10)
    req = runner.requests[-1]
    assert req.policy.tools == ("Read", "Skill")
    assert req.policy.allow == ("Skill", "mcp__studio__set_post_text", "mcp__studio__record_audit")
    assert req.mcp["url"] == f"{cfg.origin}/mcp" and len(req.mcp["token"]) > 30
    assert (req.max_turns, req.timeout) == (cfg.chat_max_turns, cfg.chat_timeout_seconds)
    cmd = build_command(cfg, req, mcp_config=cfg.skills_dir / "mcp.json")
    assert "Bash" not in " ".join(cmd) and "--no-session-persistence" in cmd and "--strict-mcp-config" in cmd
    assert cmd[cmd.index("--mcp-config") + 1].endswith("mcp.json") and cmd[cmd.index("--max-turns") + 1] == str(cfg.chat_max_turns)


def test_pictures_are_offered_only_once_chatgpt_is_ready(studio, monkeypatch):
    client, app, runner = studio
    db = app.state.db
    monkeypatch.setattr(codex, "chatgpt_ready", lambda: True)
    wait_for(db, ask(client, add_post(db), "Make an illustration"), 10)
    assert "mcp__studio__make_image" in runner.requests[-1].policy.allow


# ---- the tools, on the run's own token ----------------------------------------------------
def test_mcp_lists_the_runs_tools_and_closes_when_the_run_ends(studio):
    client, app, runner = studio
    db = app.state.db
    runner.hold.clear()
    job = ask(client, add_post(db), "Shorter")
    deadline = time.monotonic() + 10
    while not runner.requests and time.monotonic() < deadline:
        time.sleep(0.05)
    req = runner.requests[-1]
    headers = {"Authorization": f"Bearer {req.mcp['token']}"}
    listed = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers=headers).json()
    assert [t["name"] for t in listed["result"]["tools"]] == ["set_post_text", "record_audit"]
    said, failed = tool(client, req, "make_image", {"prompt": "a calm desk at night, flat shapes"})
    assert failed and "not available in this run" in said
    for wrong in ("Bearer not-the-token", f"Bearer {TOKEN}", f"Basic {req.mcp['token']}"):   # only this run's token, as a bearer
        r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 3, "method": "tools/list"}, headers={"Authorization": wrong})
        assert r.status_code == 401, wrong
    runner.hold.set()
    wait_for(db, job, 10)
    after = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers=headers)
    assert after.status_code == 401                     # the token died with its run


def test_set_post_text_rewrites_the_post_and_keeps_a_version_each_time(studio):
    client, app, runner = studio
    db = app.state.db
    post = add_post(db, text="First version.")
    client.post(f"/api/post/{post}/save", json={"text": "The owner's own edit."})
    runner.script = lambda req: (tool(client, req, "set_post_text", {"text": "Claude's rewrite.", "note": "New hook",
                                                                      "notes": ["Fill the [N]"]}),
                                 RunResult(outcome="ok", text="Rewrote the hook.", clean_text="Rewrote the hook."))[1]
    wait_for(db, ask(client, post, "New hook please"), 10)
    shown = client.get(f"/api/post/{post}").json()
    assert shown["text"] == "Claude's rewrite." and shown["notes"] == ["Fill the [N]"]
    kept = client.get(f"/api/post/{post}/versions").json()["versions"]
    assert [(v["author"], v["note"]) for v in kept] == [("claude", "New hook"), ("you", "As it was")]
    assert kept[0]["current"] and not kept[1]["current"]
    reply = client.get(f"/api/post/{post}/chat").json()["messages"][-1]
    assert reply["role"] == "claude" and reply["text"] == "Rewrote the hook." and reply["versions"] == 1


def test_set_post_text_leaves_a_locked_or_too_long_post_alone(studio):
    client, app, runner = studio
    db = app.state.db
    approved = add_post(db, status="approved", text="Final text.")
    said = {}
    runner.script = lambda req: (said.update(locked=tool(client, req, "set_post_text", {"text": "Changed!", "note": "x"})),
                                 RunResult(outcome="ok", text="ok", clean_text="ok"))[1]
    wait_for(db, ask(client, approved, "Change it"), 10)
    assert said["locked"][1] and "locked" in said["locked"][0]
    assert db.one("SELECT text FROM posts WHERE id=?", (approved,))["text"] == "Final text."
    draft = add_post(db, text="Short.")
    runner.script = lambda req: (said.update(long=tool(client, req, "set_post_text", {"text": "x" * 3001, "note": "x"})),
                                 RunResult(outcome="ok", text="ok", clean_text="ok"))[1]
    wait_for(db, ask(client, draft, "Make it long"), 10)
    assert said["long"][1] and "3,000" in said["long"][0]
    assert db.one("SELECT text FROM posts WHERE id=?", (draft,))["text"] == "Short."


def test_record_audit_shows_its_findings_beside_the_post(studio):
    client, app, runner = studio
    db = app.state.db
    post = add_post(db, text="It has a [N] blank.")
    runner.script = lambda req: (tool(client, req, "record_audit", {"verdict": "FAIL", "summary": "One blank left.",
                                                                     "blockers": [{"issue": "Blank [N]", "fix": "Fill it"}]}),
                                 RunResult(outcome="ok", text="Audited.", clean_text="Audited."))[1]
    wait_for(db, ask(client, post, "Audit it"), 10)
    audit = client.get(f"/api/post/{post}").json()["audit"]
    assert audit == {"verdict": "FAIL", "summary": "One blank left.", "blockers": [{"issue": "Blank [N]", "fix": "Fill it"}],
                     "warnings": [], "stale": False}
    client.post(f"/api/post/{post}/save", json={"text": "It has a 4 blank."})
    assert client.get(f"/api/post/{post}").json()["audit"]["stale"] is True


def test_make_image_keeps_the_picture_for_the_post_at_most_a_few_a_request(studio, monkeypatch):
    client, app, runner = studio
    db = app.state.db
    made = []
    monkeypatch.setattr(codex, "chatgpt_ready", lambda: True)
    monkeypatch.setattr(codex, "make_picture", lambda prompt, shape, cancel: (made.append((prompt, shape)) or
                                                                                (b"\x89PNG-" + bytes([len(made)]), 1200, 627, "image/png")))
    post = add_post(db)
    answers = []
    runner.script = lambda req: (answers.extend(tool(client, req, "make_image", {"prompt": "a calm desk at night, flat shapes"})
                                                for _ in range(5)), RunResult(outcome="ok", text="Made one.", clean_text="Made one."))[1]
    wait_for(db, ask(client, post, "An illustration please"), 10)
    cap = app.state.jobs.images_per_request                                    # config's images_per_request: 4
    assert cap == 4 and [failed for _said, failed in answers] == [False] * cap + [True] and "No more pictures" in answers[cap][0]
    assert made == [("a calm desk at night, flat shapes", "landscape")] * cap   # codex.make_picture adds the rules itself
    shown = client.get(f"/api/post/{post}").json()
    assert [p["source"] for p in shown["pictures"]] == ["chatgpt"] * cap and shown["picture"] is None
    reply = client.get(f"/api/post/{post}/chat").json()["messages"][-1]
    assert [p["id"] for p in reply["images"]] == [p["id"] for p in shown["pictures"]]
    picture = client.get(shown["pictures"][0]["url"])
    assert picture.status_code == 200 and picture.content.startswith(b"\x89PNG") and picture.headers["x-content-type-options"] == "nosniff"


def test_make_image_says_why_when_pictures_are_off(studio, monkeypatch):
    client, app, runner = studio
    db = app.state.db
    monkeypatch.setattr(codex, "chatgpt_ready", lambda: True)
    answers = []
    runner.script = lambda req: (answers.append(tool(client, req, "make_image", {"prompt": "a calm desk at night, flat shapes"})),
                                 RunResult(outcome="ok", text="none", clean_text="none"))[1]
    wait_for(db, ask(client, add_post(db), "An illustration"), 10)
    assert answers[0][1] and "no Codex home is set" in answers[0][0]   # this app's config names none


# ---- while it works, and when it ends ---------------------------------------------------------
def test_while_claude_works_on_a_post_its_text_and_chat_wait(studio):
    client, app, runner = studio
    db = app.state.db
    post = add_post(db, text="Draft.")
    runner.hold.clear()
    job = ask(client, post, "Shorter")
    assert client.post(f"/api/post/{post}/ask", json={"text": "Again"}).status_code == 409
    assert client.post(f"/api/post/{post}/save", json={"text": "typed meanwhile"}).status_code == 409
    assert client.post(f"/api/post/{post}/approve", json={}).status_code == 409
    assert client.get(f"/api/post/{post}").json()["editable"] is False
    assert [p["busy"] for p in client.get("/api/state").json()["posts"]] == [True]
    runner.hold.set()
    wait_for(db, job, 10)
    assert client.get(f"/api/post/{post}").json()["editable"] is True


@pytest.mark.parametrize("outcome,offer,role", [("error", "again", "error"), ("timeout", "carry", "error"),
                                                 ("cancelled", "carry", "info")])
def test_a_run_that_did_not_finish_says_so_and_offers_the_next_step(studio, outcome, offer, role):
    client, app, runner = studio
    db = app.state.db
    post = add_post(db)
    runner.script = lambda req: RunResult(outcome=outcome, error="It broke." if outcome == "error" else "")
    wait_for(db, ask(client, post, "Shorter"), 10)
    messages = client.get(f"/api/post/{post}/chat").json()["messages"]
    assert [m["role"] for m in messages] == ["user", role]
    assert messages[-1]["offer"] == offer and messages[-1]["request"] == messages[0]["id"]


def test_starting_the_chat_afresh_keeps_the_old_one_to_bring_back(studio):
    client, app, runner = studio
    db = app.state.db
    post = add_post(db)
    wait_for(db, ask(client, post, "First question"), 10)
    assert client.post(f"/api/post/{post}/chat/clear", json={}).status_code == 200
    chat = client.get(f"/api/post/{post}/chat").json()
    assert chat["messages"] == [] and chat["earlier"][0]["count"] == 2
    wait_for(db, ask(client, post, "A new start"), 10)
    assert "First question" not in runner.requests[-1].prompt     # a fresh chat carries nothing of the old one
    client.post(f"/api/post/{post}/chat/back", json={"conversation": chat["earlier"][0]["id"]})
    assert [m["text"] for m in client.get(f"/api/post/{post}/chat").json()["messages"]][0] == "First question"


# ---- versions ------------------------------------------------------------------------------------
def test_going_back_to_a_version_keeps_the_text_before_so_it_can_be_undone(studio):
    client, app, _runner = studio
    db = app.state.db
    post = add_post(db, text="One.")
    versions.record(db, post, "One.", None, "claude", "First draft")
    client.post(f"/api/post/{post}/save", json={"text": "Two."})
    first = client.get(f"/api/post/{post}/versions").json()["versions"][-1]
    assert client.post(f"/api/post/{post}/versions/back", json={"version": first["id"]}).json() == {"changed": True}
    assert client.get(f"/api/post/{post}").json()["text"] == "One."
    kept = client.get(f"/api/post/{post}/versions").json()["versions"]
    assert [(v["author"], v["note"]) for v in kept] == [("studio", f"Went back to version {first['id']}"),
                                                          ("you", "Your edits"), ("claude", "First draft")]
    other = add_post(db, status="approved", text="Locked.")
    versions.record(db, other, "Locked.", None, "claude", "x")
    v = client.get(f"/api/post/{other}/versions").json()["versions"][0]
    assert client.post(f"/api/post/{other}/versions/back", json={"version": v["id"]}).status_code == 409
    assert client.post(f"/api/post/{post}/versions/back", json={"version": v["id"]}).status_code == 409  # not its own


# ---- attachments --------------------------------------------------------------------------------
def data_url(mime, body):
    return f"data:{mime};base64," + base64.b64encode(body).decode()


def test_a_messages_files_stay_in_the_posts_own_folder_its_run_reads_and_the_page_opens(studio, cfg):
    client, app, runner = studio
    db = app.state.db
    post = add_post(db)
    files = [{"name": "chart.png", "data": data_url("image/png", PNG)},
             {"name": "notes.txt", "data": data_url("text/plain", b"Our deploys went from 22 minutes to 9.")}]
    wait_for(db, client.post(f"/api/post/{post}/ask", json={"text": "Use these", "files": files}).json()["job"], 10)
    req = runner.requests[-1]
    folder = db.path.parent / "attachments" / f"post-{post}"
    assert req.add_dirs == (str(folder),)                                  # that one folder, and nothing wider
    cmd = build_command(cfg, req)
    assert cmd.count("--add-dir") == 1 and cmd[cmd.index("--add-dir") + 1] == str(folder)
    assert f"- {folder.as_posix()}/chart.png (" in req.prompt and f"- {folder.as_posix()}/notes.txt (text" in req.prompt
    sent = client.get(f"/api/post/{post}/chat").json()["messages"][0]
    assert [(f["name"], f["view"]) for f in sent["files"]] == [("chart.png", True), ("notes.txt", False)]
    served = client.get(sent["files"][0]["url"])
    assert served.status_code == 200 and served.content == PNG
    assert served.headers["content-security-policy"].startswith("sandbox") and served.headers["x-content-type-options"] == "nosniff"
    picture = sent["images"][0]                                            # an attached picture can go out with the post
    assert client.post(f"/api/post/{post}/picture", json={"image": picture["id"]}).json()["picture"] == picture["id"]
    for name in ("..%5C..%5Cchat.db", "%2E%2E", ".text", "..%5Cpost-1%5Cchart.png"):   # out of the folder, however written
        assert client.get(f"/api/post/{post}/file/{name}").status_code == 404, name
    assert client.get(f"/api/post/{add_post(db)}/file/chart.png").status_code == 404   # another post's folder is its own
    signed_out = TestClient(app, base_url=f"http://127.0.0.1:{cfg.port}")
    assert signed_out.get(sent["files"][0]["url"]).status_code == 401      # the session cookie, as for everything


def test_files_a_message_cannot_carry_are_refused_in_words_and_nothing_is_kept(studio):
    client, app, _runner = studio
    db = app.state.db
    post = add_post(db)
    too_many = [{"name": f"n{i}.txt", "data": data_url("text/plain", b"x")} for i in range(13)]
    r = client.post(f"/api/post/{post}/ask", json={"text": "x", "files": too_many})
    assert r.status_code == 422 and "up to 12 files" in r.json()["error"]
    r = client.post(f"/api/post/{post}/ask", json={"text": "x", "files": [{"name": "a.png", "data": "not a data url"}]})
    assert r.status_code == 422 and "attach it again" in r.json()["error"]
    assert not (db.path.parent / "attachments" / f"post-{post}").exists() and db.one("SELECT COUNT(*) AS n FROM jobs")["n"] == 0


def test_the_interviewer_reads_what_is_attached_from_its_own_folder(studio):
    client, app, runner = studio
    db = app.state.db
    sent = client.post("/api/chat/bank/send", json={"text": "My CV", "files": [{"name": "cv.txt", "data": data_url("text/plain", b"Role: lead")}]}).json()
    wait_for(db, sent["job"], 10)
    folder = db.path.parent / "attachments" / f"bank-{sent['conversation']}"
    assert runner.requests[-1].add_dirs == (str(folder),) and f"{folder.as_posix()}/cv.txt" in runner.requests[-1].prompt
    message = client.get(f"/api/chat/bank?c={sent['conversation']}").json()["messages"][0]
    assert client.get(message["files"][0]["url"]).content == b"Role: lead"


def test_mcp_handle_answers_the_protocol(studio):
    _client, app, _runner = studio
    from app.jobs import Run
    run = Run(job_id=1, kind="post_chat", params={"post_id": 1}, token="t", tools=("set_post_text",),
              cancel=threading.Event(), note=lambda *_: None)
    init = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                      run, app.state.tools)
    assert init["result"]["capabilities"] == {"tools": {"listChanged": False}}
    assert mcp.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}, run, app.state.tools) is None
    assert mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "nope"}, run, app.state.tools)["error"]["code"] == -32601
    assert loads('{"a": 1}') == {"a": 1}
