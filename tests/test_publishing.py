import threading
import time
from datetime import datetime, timezone

import pytest
import requests
from conftest import REAL_SKILLS, with_

from app.db import DB, utcnow
from app.publishing import Publisher, ScheduleError, studio_client_class

NOW = datetime(2026, 10, 7, 6, 0, tzinfo=timezone.utc)  # 11:30 IST


class FakeClient:
    """Counts create-post calls. One instance is shared, like the one Publora account."""

    def __init__(self, delay=0.0, fail=None):
        self.calls = []
        self.delay = delay
        self.fail = fail
        self.lock = threading.Lock()

    def resolve_linkedin_platform_id(self):
        return "linkedin-TEST"

    def create_post_once(self, payload, key):
        with self.lock:
            self.calls.append((payload, key))
        time.sleep(self.delay)
        if self.fail:
            raise self.fail
        return {"success": True, "postGroupId": f"pg{len(self.calls)}", "scheduledTime": payload["scheduledTime"],
                "warnings": []}

    def delete_post(self, post_group_id):
        return {"success": True}


@pytest.fixture
def setup(cfg, tmp_path):
    db = DB(tmp_path / "t.db")
    client = FakeClient()
    pub = Publisher(db, with_(cfg, monthly_post_limit=3), client_factory=lambda: client, now=lambda: NOW)
    return db, pub, client


def new_post(db, status="approved", scheduled_at=None, text="A finished post."):
    now = utcnow()
    return db.run("INSERT INTO posts (created_at, updated_at, title, text, status, scheduled_at) VALUES (?,?,?,?,?,?)",
                  (now, now, "t", text, status, scheduled_at))


# ---- exactly once ---------------------------------------------------------------------
def test_schedule_sends_one_request_with_key_and_first_comment(setup):
    db, pub, client = setup
    pid = new_post(db)
    out = pub.schedule(pid, "2026-10-08T09:00", "Link: https://example.com")
    assert out["ok"] and len(client.calls) == 1
    payload, key = client.calls[0]
    assert payload["scheduledTime"] == "2026-10-08T03:30:00Z"  # 09:00 IST
    assert payload["platforms"] == ["linkedin-TEST"]
    assert payload["firstComment"] == {"text": "Link: https://example.com", "platforms": ["linkedin"]}
    row = db.one("SELECT * FROM posts WHERE id=?", (pid,))
    assert row["status"] == "scheduled" and row["publora_post_id"] == "pg1" and row["idempotency_key"] == key
    assert row["scheduled_at"] == "2026-10-08T03:30:00+00:00"


def test_double_click_reaches_publora_once(setup):
    db, pub, client = setup
    pid = new_post(db)
    pub.schedule(pid, "2026-10-08T09:00", None)
    with pytest.raises(ScheduleError):
        pub.schedule(pid, "2026-10-08T09:00", None)
    assert len(client.calls) == 1


def test_concurrent_clicks_reach_publora_once(setup):
    db, pub, client = setup
    client.delay = 0.5
    pid = new_post(db)
    results, errors = [], []

    def click():
        try:
            results.append(pub.schedule(pid, "2026-10-08T09:00", None))
        except ScheduleError as exc:
            errors.append(str(exc))

    threads = [threading.Thread(target=click) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(client.calls) == 1 and len(results) == 1 and len(errors) == 4


def test_refuses_when_a_publora_id_exists(setup):
    db, pub, client = setup
    pid = new_post(db)
    db.run("UPDATE posts SET publora_post_id='pg-old' WHERE id=?", (pid,))
    with pytest.raises(ScheduleError, match="already exists on Publora"):
        pub.schedule(pid, "2026-10-08T09:00", None)
    assert client.calls == []


@pytest.mark.parametrize("text", ["[DD Month YYYY], I stopped coding.", "Commits fell from [X] to [Y].",
                                  "Template: {hook line} then more."])
def test_approve_refuses_unfilled_slots(setup, text):
    db, pub, _c = setup
    pid = new_post(db, status="draft", text=text)
    with pytest.raises(ScheduleError, match="placeholder"):
        pub.approve(pid)
    assert db.one("SELECT status FROM posts WHERE id=?", (pid,))["status"] == "draft"


def test_approve_accepts_finished_text(setup):
    db, pub, _c = setup
    pid = new_post(db, status="draft", text="On 14 March our deploys fell from 22 minutes to 9.")
    pub.approve(pid)
    assert db.one("SELECT status FROM posts WHERE id=?", (pid,))["status"] == "approved"


def test_only_approved_posts_can_be_scheduled(setup):
    db, pub, client = setup
    pid = new_post(db, status="draft")
    with pytest.raises(ScheduleError, match="approved"):
        pub.schedule(pid, "2026-10-08T09:00", None)
    assert client.calls == []


def test_timeout_then_retry_resends_identical_body_and_key(setup):
    db, pub, client = setup
    client.fail = requests.Timeout("read timed out")
    pid = new_post(db)
    out = pub.schedule(pid, "2026-10-08T09:00", None)
    assert not out["ok"] and "may or may not" in out["error"]
    assert db.one("SELECT status FROM posts WHERE id=?", (pid,))["status"] == "failed"
    client.fail = None
    assert pub.retry(pid)["ok"]
    (p1, k1), (p2, k2) = client.calls
    assert p1 == p2 and k1 == k2
    assert db.one("SELECT status FROM posts WHERE id=?", (pid,))["status"] == "scheduled"


@pytest.mark.skipif(not (REAL_SKILLS / "lib" / "publora_client.py").is_file(),
                    reason="needs the linkedin-skills clone next to this folder")
def test_studio_client_makes_exactly_one_http_request_even_on_timeout():
    """The real subclass of lib/publora_client.py: no retry loop, Idempotency-Key header present."""
    from conftest import Config
    cls = studio_client_class(Config(skills_dir=REAL_SKILLS, claude_bin=REAL_SKILLS, claude_config_dir=REAL_SKILLS))
    client = cls(api_key="sk_test")

    class Session:
        def __init__(self):
            self.posts = []

        def post(self, url, json=None, headers=None, timeout=None):
            self.posts.append((url, json, headers))
            raise requests.Timeout("slow")

    client._session = Session()
    with pytest.raises(requests.Timeout):
        client.create_post_once({"content": "x", "platforms": ["linkedin-1"]}, "key-1")
    assert len(client._session.posts) == 1
    url, body, headers = client._session.posts[0]
    assert url.endswith("/create-post") and headers == {"Idempotency-Key": "key-1"}


# ---- date validation -------------------------------------------------------------------
@pytest.mark.parametrize("value,needle", [
    ("2026-10-07T11:00", "past"),        # 30 min ago IST
    ("2026-10-07T11:31", "past"),        # 1 minute ahead: under the 2-minute lead
    ("2026-10-21T12:00", "14 days"),     # 14 days + 30 min
    ("", "Pick a date"),
    ("2026-10-08T09:00+05:30", "without a zone"),
])
def test_bad_times_are_rejected(setup, value, needle):
    db, pub, client = setup
    with pytest.raises(ScheduleError, match=needle):
        pub.parse_local(value)


def test_ist_is_converted_to_utc(setup):
    _db, pub, _c = setup
    assert pub.parse_local("2026-10-20T23:45") == datetime(2026, 10, 20, 18, 15, tzinfo=timezone.utc)


# ---- quota -------------------------------------------------------------------------------
def test_quota_counts_the_ist_month_and_blocks_at_the_limit(setup):
    db, pub, client = setup
    for status in ("scheduling", "scheduled", "published"):
        new_post(db, status=status, scheduled_at="2026-10-03T03:30:00+00:00")
    new_post(db, status="cancelled", scheduled_at="2026-10-04T03:30:00+00:00")   # not counted
    new_post(db, status="failed", scheduled_at="2026-10-04T03:30:00+00:00")      # not counted
    pid = new_post(db)
    with pytest.raises(ScheduleError, match="Monthly limit reached: 3/3"):
        pub.schedule(pid, "2026-10-08T09:00", None)
    assert client.calls == []


def test_quota_month_boundary_is_ist_not_utc(setup):
    db, pub, _c = setup
    # 31 Oct 23:30 IST is 18:00 UTC: October. 1 Nov 00:30 IST is 31 Oct 19:00 UTC: November.
    new_post(db, status="scheduled", scheduled_at="2026-10-31T18:00:00+00:00")
    new_post(db, status="scheduled", scheduled_at="2026-10-31T19:00:00+00:00")
    assert pub.quota_used(datetime(2026, 10, 15, tzinfo=timezone.utc)) == 1
    assert pub.quota_used(datetime(2026, 11, 2, tzinfo=timezone.utc)) == 1


def test_other_month_is_not_blocked(setup):
    db, pub, client = setup
    for _ in range(3):
        new_post(db, status="scheduled", scheduled_at="2026-09-20T03:30:00+00:00")
    pid = new_post(db)
    assert pub.schedule(pid, "2026-10-08T09:00", None)["ok"]
