"""Draft all, on the Planner's week plan: every planned post without a draft, written one at a time as ordinary draft jobs
on the one worker (app/draft_all.py), with the owner's own requests in between; Stop, a failure and a second start.
A stand-in runner only: no real Claude run."""
import json
import re
import threading
import time

import pytest
from conftest import TOKEN, add_post
from fastapi.testclient import TestClient

from app.claude_runner import RunResult
from app.db import dumps, utcnow
from app.jobs import wait_for
from app.main import create_app

DAYS = ("Tue", "Thu", "Fri", "Sat")


class Gate:
    """Stands in for ClaudeRunner. Each run waits for a permit (`let_go`) while `held`, and notes what it was, when it
    started and ended, and how many ran at once. A draft whose angle is in `fail` fails; `during` runs inside a run."""

    def __init__(self):
        self.held = True
        self.permits = threading.Semaphore(0)
        self.lock = threading.Lock()
        self.runs = []                 # [kind, angle or None, started, ended]
        self.now = 0
        self.most = 0
        self.fail = set()
        self.during = None             # fn(req), once, inside the first draft's run; that run then ends ok regardless

    def run(self, req, cancel=None, on_progress=None, timeout=None):
        found = re.search(r"^Angle: (.*)$", req.prompt, flags=re.M)
        angle = found.group(1) if found else None
        with self.lock:
            self.now += 1
            self.most = max(self.most, self.now)
            entry = [req.kind, angle, time.monotonic(), None]
            self.runs.append(entry)
        try:
            if self.during and req.kind == "draft":
                during, self.during = self.during, None
                during(req)
                return self._answer(req, angle)
            while self.held and not self.permits.acquire(timeout=0.02):
                if cancel is not None and cancel.is_set():
                    return RunResult(outcome="cancelled", error="Cancelled.")
            return self._answer(req, angle)
        finally:
            with self.lock:
                self.now -= 1
                entry[3] = time.monotonic()

    def _answer(self, req, angle):
        if req.kind != "draft":
            return RunResult(outcome="ok", text="A question.", clean_text="A question.", session_id="s-1")
        if angle in self.fail:
            return RunResult(outcome="error", error="Claude reported an error (stand-in).")
        return RunResult(outcome="ok", text="done", data={"text": f"A post: {angle}.", "formula": "F4", "first_comment": None,
                                                          "notes": []})

    def let_go(self, n=1):
        self.permits.release(n)

    def started(self, kind="draft"):
        with self.lock:
            return sum(1 for r in self.runs if r[0] == kind)


@pytest.fixture
def studio(cfg, tmp_path):
    runner = Gate()
    app = create_app(cfg, TOKEN, db_path=tmp_path / "draft-all.db", runner=runner)
    with TestClient(app, base_url=f"http://127.0.0.1:{cfg.port}", headers={"Origin": cfg.origin}) as client:
        client.cookies.set("studio_session", TOKEN)
        yield client, app, runner
        runner.held = False


def until(test, timeout=10):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if test():
            return
        time.sleep(0.02)
    raise AssertionError("waited too long")


def make_plan(db, angles, drafted=()):
    plan = db.run("INSERT INTO plans (created_at, inputs, result) VALUES (?,?,?)",
                  (utcnow(), dumps({"audience": "engineers who build side projects"}), dumps({"items": []})))
    items = [db.run("INSERT INTO plan_items (plan_id, position, data) VALUES (?,?,?)",
                    (plan, i, dumps({"day": DAYS[i], "angle": angle, "formula": "F4 Time-Anchor Confession"})))
             for i, angle in enumerate(angles)]
    for i in drafted:
        post = add_post(db, plan_item_id=items[i])
        db.run("UPDATE plan_items SET post_id=? WHERE id=?", (post, items[i]))
    return plan, items


def drafts(db):
    return db.all("SELECT * FROM jobs WHERE kind='draft' ORDER BY id")


def board(client):
    return client.get("/api/planner").json()["boards"][0]


def test_draft_all_writes_each_planned_post_without_a_draft_one_after_the_other(studio):
    client, app, runner = studio
    db = app.state.db
    plan, items = make_plan(db, ["Angle one", "Angle two", "Angle three"], drafted=[0])
    assert board(client)["draft_all"] == {"left": 2, "running": None, "last": None}
    first = client.post(f"/api/planner/{plan}/draft-all", json={}).json()["job"]
    until(lambda: runner.started() == 1)
    shown = board(client)
    assert shown["draft_all"] == {"left": 1, "running": {"at": 1, "of": 2, "job": first}, "last": None}
    assert [i["job"]["id"] if i["job"] else None for i in shown["items"]] == [None, first, None]   # on its card, as Draft this
    assert len(drafts(db)) == 1                                       # one step at a time: the next is not queued yet
    runner.let_go()
    until(lambda: runner.started() == 2)
    second = drafts(db)[-1]["id"]
    assert board(client)["draft_all"]["running"] == {"at": 2, "of": 2, "job": second}
    runner.let_go()
    assert wait_for(db, second, 10)["status"] == "done"
    assert [r[1] for r in runner.runs] == ["Angle two", "Angle three"] and runner.most == 1
    assert runner.runs[0][3] <= runner.runs[1][2]                     # the second began after the first had ended
    for item, angle in zip(items[1:], ["Angle two", "Angle three"]):
        row = db.one("SELECT * FROM plan_items WHERE id=?", (item,))
        post = db.one("SELECT * FROM posts WHERE id=?", (row["post_id"],))
        assert post["plan_item_id"] == item and post["text"] == f"A post: {angle}." and post["title"] == angle
    time.sleep(0.3)
    assert len(drafts(db)) == 2                                       # nothing left, so nothing more queued
    assert board(client)["draft_all"] == {"left": 0, "running": None,
                                          "last": {"job": second, "written": 2, "of": 2, "failed": []}}
    assert len([p for p in client.get("/api/state").json()["posts"] if p["title"].startswith("Angle")]) == 2   # in the list
    refused = client.post(f"/api/planner/{plan}/draft-all", json={})
    assert refused.status_code == 409 and "already has a draft" in refused.json()["error"]
    assert client.post(f"/api/jobs/{second}/dismiss", json={}).status_code == 200
    assert board(client)["draft_all"]["last"] is None                 # the end line, dismissed


def test_a_second_draft_all_while_one_runs_is_refused(studio):
    client, app, runner = studio
    db = app.state.db
    plan, _items = make_plan(db, ["Angle one", "Angle two"])
    other, _ = make_plan(db, ["Another plan's angle"])
    assert client.post(f"/api/planner/{plan}/draft-all", json={}).status_code == 200
    until(lambda: runner.started() == 1)
    for which in (plan, other):
        r = client.post(f"/api/planner/{which}/draft-all", json={})
        assert r.status_code == 409 and "already writing" in r.json()["error"]
    assert client.post("/api/planner/999/draft-all", json={}).status_code == 404
    assert len(drafts(db)) == 1
    runner.held = False


def test_a_request_sent_mid_batch_runs_before_the_next_draft(studio):
    client, app, runner = studio
    db = app.state.db
    plan, _items = make_plan(db, ["Angle one", "Angle two"])
    client.post(f"/api/planner/{plan}/draft-all", json={})
    until(lambda: runner.started() == 1)
    chat = client.post("/api/chat/bank/send", json={"text": "Let's go"}).json()["job"]
    runner.let_go(3)
    until(lambda: runner.started() == 2)
    assert wait_for(db, drafts(db)[-1]["id"], 10)["status"] == "done" and wait_for(db, chat, 10)["status"] == "done"
    assert [(r[0], r[1]) for r in runner.runs] == [("draft", "Angle one"), ("interview", None), ("draft", "Angle two")]
    assert runner.most == 1


def test_stop_during_the_first_draft_starts_nothing_more(studio):
    client, app, runner = studio
    db = app.state.db
    plan, _items = make_plan(db, ["Angle one", "Angle two", "Angle three"])
    first = client.post(f"/api/planner/{plan}/draft-all", json={}).json()["job"]
    until(lambda: runner.started() == 1)
    r = client.post("/api/planner/draft-all/stop", json={})
    assert r.status_code == 200 and r.json()["said"].startswith("Stopped.")
    assert wait_for(db, first, 10)["status"] == "cancelled"
    time.sleep(0.4)
    assert len(drafts(db)) == 1 and runner.started() == 1
    assert board(client)["draft_all"] == {"left": 3, "running": None, "last": None}
    assert client.post("/api/planner/draft-all/stop", json={}).status_code == 409    # nothing running now


def test_a_stop_that_lands_as_a_draft_finishes_still_ends_the_rest(studio):
    client, app, runner = studio
    db = app.state.db
    plan, items = make_plan(db, ["Angle one", "Angle two"])
    # The stop comes while the run is ending: the run still answers with its draft, which is kept, and nothing follows.
    runner.during = lambda req: client.post("/api/planner/draft-all/stop", json={})
    first = client.post(f"/api/planner/{plan}/draft-all", json={}).json()["job"]
    assert wait_for(db, first, 10)["status"] == "done"
    time.sleep(0.4)
    assert len(drafts(db)) == 1
    assert db.one("SELECT post_id FROM plan_items WHERE id=?", (items[0],))["post_id"]
    assert board(client)["draft_all"] == {"left": 1, "running": None, "last": None}


def test_a_failed_draft_ends_the_rest_and_try_again_redrafts_that_one(studio):
    client, app, runner = studio
    db = app.state.db
    plan, items = make_plan(db, ["Angle one", "Angle two", "Angle three"])
    runner.held = False
    runner.fail = {"Angle two"}
    client.post(f"/api/planner/{plan}/draft-all", json={})
    until(lambda: runner.started() == 2)
    failed = drafts(db)[-1]["id"]
    assert wait_for(db, failed, 10)["status"] == "failed"
    time.sleep(0.4)
    assert len(drafts(db)) == 2                                       # the third was never queued
    shown = board(client)
    assert shown["draft_all"] == {"left": 2, "running": None,
                                  "last": {"job": failed, "written": 1, "of": 3, "failed": [{"item": items[1], "angle": "Angle two"}]}}
    assert shown["items"][1]["job"]["status"] == "failed"             # its card offers Try again
    runner.fail = set()
    again = client.post(f"/api/jobs/{failed}/retry", json={}).json()["job"]
    assert wait_for(db, again, 10)["status"] == "done"
    time.sleep(0.4)
    assert len(drafts(db)) == 3                                       # that one draft only: the batch stays ended
    assert board(client)["draft_all"] == {"left": 1, "running": None,
                                          "last": {"job": again, "written": 2, "of": 3, "failed": []}}


def test_draft_this_and_each_step_send_the_same_params(studio):
    client, app, runner = studio
    db = app.state.db
    runner.held = False
    plan, items = make_plan(db, ["Angle one", "Angle two"])
    one = client.post(f"/api/planner/items/{items[0]}/draft", json={}).json()["job"]
    wait_for(db, one, 10)
    step = client.post(f"/api/planner/{plan}/draft-all", json={}).json()["job"]
    wait_for(db, step, 10)
    params = [json.loads(r["params"]) for r in drafts(db)]
    keys = {"angle", "formula", "pillar", "goal", "cta", "format", "bank_section", "plan_item_id", "audience"}
    assert keys <= set(params[0]) and keys <= set(params[1]) and "batch" not in params[0]
    assert params[1]["batch"]["plan_id"] == plan and params[0]["audience"] == params[1]["audience"]
