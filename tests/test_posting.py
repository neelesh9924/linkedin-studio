"""The posting queue (app/posting.py): the posting times, the time each queued post takes, and handing the ones inside
the window to Publora, exactly once, through Publisher.schedule. Publora is test_publishing's stand-in throughout."""
from datetime import datetime, timedelta, timezone

import pytest
from conftest import TOKEN, add_post, with_
from fastapi.testclient import TestClient
from test_publishing import FakeClient

from app import posting, skills
from app.db import DB, utcnow
from app.main import create_app
from app.posting import DEFAULT, PostingQueue, Refused
from app.publishing import Publisher, ScheduleError

NOW = datetime(2026, 10, 7, 6, 0, tzinfo=timezone.utc)   # Wednesday 7 October, 11:30 am IST: Wednesday's 9:30 has passed
IST = timedelta(hours=5, minutes=30)


def ist(text: str) -> datetime:
    """"2026-10-08 08:00" in IST, as aware UTC."""
    return (datetime.fromisoformat(text) - IST).replace(tzinfo=timezone.utc)


@pytest.fixture
def line(cfg, tmp_path):
    db = DB(tmp_path / "q.db")
    client = FakeClient()
    pub = Publisher(db, cfg, client_factory=lambda: client, now=lambda: NOW)
    return db, PostingQueue(db, pub), client


def queued(db, queue, n=1, **extra) -> list[int]:
    ids = []
    for _ in range(n):
        pid = add_post(db, "approved", **extra)
        assert queue.add(pid)
        ids.append(pid)
    return ids


def test_the_posting_times_default_to_the_skills_mornings_and_are_checked(line):
    db, queue, _client = line
    assert queue.times() == DEFAULT == {"tue": "08:00", "wed": "09:30", "thu": "08:00"}
    assert posting.words(DEFAULT) == "Tue 8:00 am, Wed 9:30 am and Thu 8:00 am"
    assert posting.save(db, {"fri": "17:15", "mon": "8:30", "sun": ""}) == {"mon": "08:30", "fri": "17:15"}   # week order
    assert queue.times() == {"mon": "08:30", "fri": "17:15"} and posting.words(queue.times()) == "Mon 8:30 am and Fri 5:15 pm"
    for wrong, said in (({}, "at least one"), ({"sun": ""}, "at least one"), ({"someday": "08:00"}, "no day called"),
                        ({"mon": "25:00"}, "Monday: give its time"), ({"mon": "noon"}, "Monday"), ("08:00", "Send")):
        with pytest.raises(Refused, match=said):
            posting.save(db, wrong)
    assert queue.times() == {"mon": "08:30", "fri": "17:15"}             # a refusal keeps what was saved
    posting.path(db).write_text("not json", encoding="utf-8")
    assert queue.times() == DEFAULT                                       # an unreadable file: the studio's own


def test_each_queued_post_takes_the_next_free_posting_day_in_line_order(line):
    db, queue, _client = line
    first, second, third = queued(db, queue, 3)
    taken = add_post(db, "scheduled", scheduled_at=ist("2026-10-13 18:00").isoformat(), publora_post_id="pg-x")
    assert queue.lineup() == [(first, ist("2026-10-08 08:00")),      # Thursday: Wednesday's time has passed today
                              (second, ist("2026-10-14 09:30")),     # Tuesday 13 has a post already: one a day
                              (third, ist("2026-10-15 08:00"))]
    db.run("UPDATE posts SET status='cancelled' WHERE id=?", (taken,))   # a cancelled post frees its day
    assert [at for _pid, at in queue.lineup()] == [ist("2026-10-08 08:00"), ist("2026-10-13 08:00"), ist("2026-10-14 09:30")]
    assert queue.move(third, "first") and [pid for pid, _at in queue.lineup()] == [third, first, second]
    assert queue.move(third, "down") and [pid for pid, _at in queue.lineup()] == [first, third, second]
    assert not queue.move(second, "down") and not queue.move(first, "up") and not queue.move(taken, "up")
    assert queue.take_out(third) and [pid for pid, _at in queue.lineup()] == [first, second]
    assert db.one("SELECT status, queue_pos FROM posts WHERE id=?", (third,))[:] == ("approved", None)
    assert not queue.take_out(third) and not queue.add(add_post(db, "draft"))   # only an approved post joins


def test_a_full_month_passes_to_the_next_and_the_trash_and_drafts_leave_the_line(line, cfg):
    db, queue, client = line
    queue.pub.cfg = queue.cfg = with_(cfg, monthly_post_limit=3)
    ids = queued(db, queue, 4)
    assert [at for _pid, at in queue.lineup()] == [ist("2026-10-08 08:00"), ist("2026-10-13 08:00"), ist("2026-10-14 09:30"),
                                                   ist("2026-11-03 08:00")]    # October's three are its limit
    db.run("UPDATE posts SET trashed_at=? WHERE id=?", (utcnow(), ids[0]))
    db.run("UPDATE posts SET status='draft' WHERE id=?", (ids[1],))
    assert [pid for pid, _at in queue.lineup()] == ids[2:]


def test_the_ones_inside_the_window_go_to_publora_once_each_and_leave_the_line(line):
    db, queue, client = line
    ids = queued(db, queue, 8, first_comment="The link: https://example.com")
    sent = queue.send_due()
    assert [r["id"] for r in sent] == ids[:6] and all(r["ok"] and r["sent"] for r in sent)
    times = ["2026-10-08T02:30:00Z", "2026-10-13T02:30:00Z", "2026-10-14T04:00:00Z", "2026-10-15T02:30:00Z",
             "2026-10-20T02:30:00Z", "2026-10-21T04:00:00Z"]           # inside 14 days; Thursday 22 is not
    assert [payload["scheduledTime"] for payload, _key in client.calls] == times
    assert all(payload["firstComment"]["text"] == "The link: https://example.com" for payload, _key in client.calls)
    rows = db.all(f"SELECT id, status, queue_pos FROM posts WHERE id IN ({','.join('?' * 8)}) ORDER BY id", tuple(ids))
    assert [(r["status"], r["queue_pos"]) for r in rows[:6]] == [("scheduled", None)] * 6
    assert [r["status"] for r in rows[6:]] == ["approved"] * 2 and all(r["queue_pos"] for r in rows[6:])
    assert [at for _pid, at in queue.lineup()] == [ist("2026-10-22 08:00"), ist("2026-10-27 08:00")]   # after the sent ones
    assert queue.send_due() == [] and len(client.calls) == 6               # nothing more is due: nothing is sent again


def test_a_refusal_before_anything_is_sent_stays_on_the_post_and_it_keeps_its_place(line):
    db, queue, client = line
    first, second = queued(db, queue, 2)

    def no_key():
        raise ScheduleError("PUBLORA_API_KEY is not set in linkedin-skills\\.env.")

    queue.pub.client_factory = no_key
    said = queue.send_due()
    assert [(r["id"], r["ok"], r["sent"]) for r in said] == [(first, False, False), (second, False, False)]
    row = db.one("SELECT * FROM posts WHERE id=?", (first,))
    assert (row["status"], row["error"]) == ("approved", "Not at Publora yet: PUBLORA_API_KEY is not set in "
                                                         "linkedin-skills\\.env. The studio tries again by itself.")
    rev = db.rev
    queue.send_due()
    assert db.rev == rev                                    # the same refusal again writes nothing
    queue.pub.client_factory = lambda: client
    queue.send_due()
    assert [db.one("SELECT status, error FROM posts WHERE id=?", (p,))[:] for p in (first, second)] == [("scheduled", None)] * 2


def test_a_failure_at_publora_leaves_the_post_failed_with_its_day_kept_for_try_again(line):
    db, queue, client = line
    first, second = queued(db, queue, 2)
    client.fail = RuntimeError("HTTP 503")
    queue.send_due()
    assert db.one("SELECT status FROM posts WHERE id=?", (first,))["status"] == "failed"
    client.fail = None
    assert queue.lineup() == []                                                     # both went: one failed, one sent
    later = queued(db, queue, 1)[0]
    assert queue.lineup() == [(later, ist("2026-10-14 09:30"))]   # Thursday 8 is the failed post's, Tuesday 13 the sent one's


@pytest.fixture
def studio(cfg, tmp_path, fake_runner):
    """A studio whose Publora is the stand-in and whose clock is NOW; `check` is passed as check_publora."""
    made = []

    def make(check=None):
        path = tmp_path / f"s{len(made)}.db"
        client = FakeClient()
        pub = Publisher(DB(path), cfg, client_factory=lambda: client, now=lambda: NOW)
        app = create_app(cfg, TOKEN, db_path=path, runner=fake_runner, publisher=pub,
                         **({} if check is None else {"check_publora": check}))
        http = TestClient(app, base_url=f"http://127.0.0.1:{cfg.port}", headers={"Origin": cfg.origin})
        http.__enter__()
        http.cookies.set("studio_session", TOKEN)
        made.append(http)
        return http, app, client

    yield make
    for http in made:
        http.__exit__(None, None, None)


def test_approve_and_queue_refuses_blanks_then_queues_and_hands_it_to_publora(studio):
    http, app, client = studio()
    db = app.state.db
    pid = add_post(db, "draft", text="In [N] weeks I learned a lot.")
    refused = http.post(f"/api/post/{pid}/queue", json={})
    assert refused.status_code == 409 and "placeholder" in refused.json()["error"] and client.calls == []
    said = http.post(f"/api/post/{pid}/queue", json={"text": "In six weeks I learned a lot."}).json()
    assert said == {"ok": True, "status": "scheduled", "said": "Queued, and handed to Publora: it goes out Thu 8 Oct, 8:00 am IST."}
    assert [payload["scheduledTime"] for payload, _key in client.calls] == ["2026-10-08T02:30:00Z"]
    row = db.one("SELECT * FROM posts WHERE id=?", (pid,))
    assert (row["status"], row["queue_pos"], row["text"]) == ("scheduled", None, "In six weeks I learned a lot.")
    assert http.post(f"/api/post/{pid}/queue", json={}).status_code == 409             # at Publora: not again


def test_a_first_comment_with_a_blank_or_too_long_keeps_a_post_out_of_the_queue(studio):
    """No final dialog shows the first comment when a post is queued, so what Schedule… only warns about is refused."""
    http, app, client = studio()
    db = app.state.db
    draft = add_post(db, "draft", first_comment="The slides: [link]")
    said = http.post(f"/api/post/{draft}/queue", json={}).json()["error"]
    assert said == "The first comment still has a blank, such as [link]. Fill it in or cut it first."
    long = add_post(db, "approved", first_comment="x" * 1251)
    said = http.post(f"/api/post/{long}/queue", json={}).json()["error"]
    assert said == "The first comment is 1,251 characters; LinkedIn takes 1,250. Cut it after Back to draft."
    assert db.one("SELECT status, queue_pos FROM posts WHERE id=?", (draft,))[:] == ("draft", None) and client.calls == []


def test_a_post_beyond_the_window_waits_in_line_with_its_time_and_can_be_taken_out(studio):
    http, app, client = studio()
    db = app.state.db
    for _ in range(6):                                       # every posting day inside the window has a post
        http.post(f"/api/post/{add_post(db, 'approved')}/queue", json={})
    pid = add_post(db, "approved")
    said = http.post(f"/api/post/{pid}/queue", json={}).json()
    assert said["status"] == "approved" and said["said"].startswith("Queued: it goes out Thu 22 Oct, 8:00 am IST. It goes "
                                                                   "to Publora by itself 14 days before")
    shown = http.get(f"/api/post/{pid}").json()
    assert (shown["label"], shown["queued"], shown["when"], shown["can_queue"]) == ("Queued", True, "Thu 22 Oct, 8:00 am IST", False)
    assert shown["posting"] == "Tue 8:00 am, Wed 9:30 am and Thu 8:00 am" and shown["window"] == 14
    listed = {p["id"]: p for p in http.get("/api/state").json()["posts"]}
    assert (listed[pid]["label"], listed[pid]["when"], listed[pid]["kind"]) == ("Queued", "Thu 22 Oct, 8:00 am IST", "ok")
    order = [p["id"] for p in http.get("/api/state").json()["posts"]]
    assert order[-1] == pid                                  # what goes out, in time order: the queued one last
    coming = http.get("/api/planner").json()["coming"]
    assert [c["kind"] for c in coming] == ["publora"] * 6 + ["queued"] and coming[-1]["place"] == 1
    assert http.post(f"/api/post/{pid}/unqueue", json={}).json() == {"ok": True}
    assert http.get(f"/api/post/{pid}").json()["label"] == "Approved" and len(client.calls) == 6
    assert http.post(f"/api/post/{pid}/unqueue", json={}).status_code == 409


def test_back_to_draft_and_the_trash_take_a_post_out_of_the_line(studio):
    http, app, _client = studio()
    db = app.state.db
    queue = app.state.queue
    for _ in range(6):
        http.post(f"/api/post/{add_post(db, 'approved')}/queue", json={})
    a, b = add_post(db, "approved"), add_post(db, "approved")
    for pid in (a, b):
        http.post(f"/api/post/{pid}/queue", json={})
    assert [pid for pid, _at in queue.lineup()] == [a, b]
    assert http.post("/api/queue/move", json={"id": b, "how": "up"}).json() == {"ok": True}
    assert [pid for pid, _at in queue.lineup()] == [b, a]
    assert http.post("/api/queue/move", json={"id": b, "how": "up"}).status_code == 409
    assert http.post("/api/queue/move", json={"id": b, "how": "sideways"}).status_code == 422
    assert http.post(f"/api/post/{b}/unapprove", json={}).json() == {"ok": True}
    assert db.one("SELECT status, queue_pos FROM posts WHERE id=?", (b,))[:] == ("draft", None)
    assert http.post(f"/api/post/{a}/trash", json={}).json()["ok"]
    assert queue.lineup() == [] and db.one("SELECT queue_pos FROM posts WHERE id=?", (a,))["queue_pos"] is None


def test_the_queue_goes_to_publora_by_itself_only_with_check_publora(studio):
    """The guard, as the light check's: a studio made without check_publora (every test's) never sends a queued post by
    itself, however often it is polled. With it, a poll starts one pass, which sends the ones inside the window."""
    http, app, client = studio()
    db = app.state.db
    pid = add_post(db, "approved")
    db.run("UPDATE posts SET queue_pos=1 WHERE id=?", (pid,))
    for _ in range(10):
        http.get("/api/state")
    app.state.queue.wait()
    assert client.calls == [] and app.state.queue._thread is None

    http, app, client = studio(check=True)
    db = app.state.db
    pid = add_post(db, "approved")
    db.run("UPDATE posts SET queue_pos=1 WHERE id=?", (pid,))
    http.get("/api/state")
    app.state.queue.wait()
    assert len(client.calls) == 1 and db.one("SELECT status FROM posts WHERE id=?", (pid,))["status"] == "scheduled"


def test_the_posting_times_settings_and_the_plan_that_follows_them(studio):
    http, app, _client = studio()
    shown = http.get("/api/posting").json()
    assert shown["times"] == DEFAULT and shown["days"][0] == ["mon", "Monday"] and shown["words"].startswith("Tue 8:00 am")
    refused = http.post("/api/posting", json={"times": {}})
    assert refused.status_code == 422 and "at least one" in refused.json()["error"]
    saved = http.post("/api/posting", json={"times": {"mon": "08:30", "wed": "08:30", "fri": "08:30"}}).json()
    assert saved["words"] == "Mon 8:30 am, Wed 8:30 am and Fri 8:30 am"
    job = http.post("/api/planner", json={"audience": "Android developers", "goal": "conversations"}).json()["job"]
    params = app.state.db.one("SELECT params FROM jobs WHERE id=?", (job,))["params"]
    assert '"max_posts": 3' in params and '"days": {"mon": "08:30"' in params
    words = skills._plan({"audience": "a", "goal": "g", "max_posts": 3, "days": {"mon": "08:30", "fri": "17:00"}})
    assert ("Number of posts: 2, one for each of the owner's posting days, on that day and at that time: Mon 8:30 AM, "
            "Fri 5:00 PM") in words
    assert "Number of posts: 4 (the skill's 3-5 per week rule)" in skills._plan({"audience": "a", "goal": "g", "max_posts": 4})


def test_schedules_recommended_times_are_the_free_posting_times(studio):
    http, app, _client = studio()
    pid = add_post(app.state.db, "approved")
    quick = http.get(f"/api/post/{pid}").json()["schedule"]["quick"]
    assert [q["value"] for q in quick] == ["2026-10-08T08:00", "2026-10-13T08:00", "2026-10-14T09:30", "2026-10-15T08:00"]
