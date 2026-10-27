import hashlib
import re
import sqlite3
import sys
import threading
import time
import types
from datetime import datetime, timedelta, timezone

import pytest
import requests
from conftest import REAL_SKILLS, TOKEN, with_
from fastapi.testclient import TestClient

from app import publishing
from app.db import DB, SCHEMA, loads, utcnow
from app.main import create_app
from app.publishing import (MEDIA_STEPS, NO_REASON, Publisher, ScheduleError, retry_with_picture, schedule_with_picture,
                            studio_client_class)
from app.status_check import EVERY

NOW = datetime(2026, 10, 7, 6, 0, tzinfo=timezone.utc)  # 11:30 IST


class FakeClient:
    """Counts create-post calls. One instance is shared, like the one Publora account.

    Like Publora, a repeated Idempotency-Key gets the same post group back, and get-upload-url
    attaches its media record before answering. fail_once[step] makes the next call of that step
    raise after it reached the fake (the answer lost on the way back)."""

    def __init__(self, delay=0.0, fail=None):
        self.calls = []
        self.delay = delay
        self.fail = fail
        self.lock = threading.Lock()
        self.groups = {}            # idempotency key -> postGroupId
        self.steps = []             # every request, in order
        self.fail_once = {}
        self.media = []             # media ids attached to the post group
        self.uploads, self.puts, self.updates, self.deleted, self.deleted_groups = [], [], [], [], []

    def _step(self, name):
        self.steps.append(name)
        exc = self.fail_once.pop(name, None)
        if exc:
            raise exc

    def resolve_linkedin_platform_id(self):
        return "linkedin-TEST"

    def create_post_once(self, payload, key):
        with self.lock:
            self.calls.append((payload, key))
            group = self.groups.setdefault(key, f"pg{len(self.groups) + 1}")
        time.sleep(self.delay)
        if self.fail:
            raise self.fail
        self._step("create")
        return {"success": True, "postGroupId": group, "scheduledTime": payload.get("scheduledTime"),
                "warnings": []}

    def get_upload_url_once(self, post_group_id, file_name, content_type):
        self.uploads.append((post_group_id, file_name, content_type))
        media_id = f"m{len(self.uploads)}"
        self.media.append(media_id)
        self._step("upload_url")
        return {"success": True, "uploadUrl": f"https://s3.test/up/{media_id}", "fileUrl": f"https://s3.test/{media_id}",
                "mediaId": media_id}

    def put_upload(self, upload_url, data, content_type):
        self.puts.append((upload_url, data, content_type))
        self._step("put")

    def update_post_once(self, post_group_id, body):
        self.updates.append((post_group_id, body))
        self._step("update")
        effective = body["scheduledTime"].replace("Z", ".000Z")
        return {"success": True, "message": "Post updated successfully", "scheduledTime": effective,
                "postGroup": {"_id": post_group_id, "status": "scheduled", "scheduledTime": effective}}

    def get_post(self, post_group_id):
        self.steps.append("get_post")
        return {"postGroupId": post_group_id, "status": "draft",
                "media": [{"mediaId": m, "status": "uploading"} for m in self.media]}

    def delete_media(self, media_id):
        self.steps.append("delete_media")
        self.media.remove(media_id)
        self.deleted.append(media_id)
        return {"success": True}

    def delete_post(self, post_group_id):
        self.deleted_groups.append(post_group_id)
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


def test_a_post_in_the_trash_never_reaches_publora(setup):
    """Belt and braces under the API's own refusal: neither Schedule nor Retry sends a post that is in the Trash."""
    db, pub, client = setup
    approved, failed = new_post(db), new_post(db, status="failed")
    db.run("UPDATE posts SET publora_payload='{\"content\":\"x\"}', idempotency_key='k' WHERE id=?", (failed,))
    db.run("UPDATE posts SET trashed_at=? WHERE id IN (?,?)", (utcnow(), approved, failed))
    with pytest.raises(ScheduleError, match="Trash"):
        pub.schedule(approved, "2026-10-08T09:00", None)
    with pytest.raises(ScheduleError, match="Trash"):
        pub.retry(failed)
    assert client.calls == []
    assert [r["status"] for r in db.all("SELECT status FROM posts ORDER BY id")] == ["approved", "failed"]


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


# ---- a post with one picture -----------------------------------------------------------
PNG = b"\x89PNG\r\n\x1a\n" + bytes(64)


@pytest.fixture
def picture(tmp_path):
    f = tmp_path / "chart.png"
    f.write_bytes(PNG)
    return {"path": str(f), "name": "chart.png", "mime": "image/png",
            "sha256": hashlib.sha256(PNG).hexdigest()}


def post_row(db, pid):
    return db.one("SELECT * FROM posts WHERE id=?", (pid,))


def test_picture_post_takes_publora_four_steps_in_order(setup, picture):
    db, pub, client = setup
    pid = new_post(db)
    out = schedule_with_picture(pub, pid, "2026-10-08T09:00", "Link: https://example.com", picture)
    assert out == {"ok": True, "postGroupId": "pg1", "warnings": []}
    assert client.steps == ["create", "upload_url", "put", "update"]
    (payload, key), = client.calls
    assert "scheduledTime" not in payload                                   # created as a draft
    assert payload["firstComment"] == {"text": "Link: https://example.com", "platforms": ["linkedin"]}
    assert client.uploads == [("pg1", "chart.png", "image/png")]
    assert client.puts == [("https://s3.test/up/m1", PNG, "image/png")]
    assert client.updates == [("pg1", {"status": "scheduled", "scheduledTime": "2026-10-08T03:30:00Z"})]
    row = post_row(db, pid)
    assert (row["status"], row["publora_post_id"], row["media_step"], row["idempotency_key"]) == \
        ("scheduled", "pg1", "done", key)
    assert row["scheduled_at"] == "2026-10-08T03:30:00+00:00"
    media = loads(row["media"])
    assert (media["postGroupId"], media["mediaId"], media["name"]) == ("pg1", "m1", "chart.png")
    assert "uploadUrl" not in media                                         # the spent write link is dropped


@pytest.mark.parametrize("step", MEDIA_STEPS)
def test_each_step_failing_once_then_retry_resumes_from_it(setup, picture, step):
    db, pub, client = setup
    client.fail_once[step] = requests.ConnectionError("connection reset")
    pid = new_post(db)
    out = schedule_with_picture(pub, pid, "2026-10-08T09:00", None, picture)
    assert not out["ok"] and out["step"] == step
    row = post_row(db, pid)
    assert (row["status"], row["media_step"], row["publora_post_id"]) == ("failed", step, None)
    if step != "create":  # the owner is told a Publora draft exists; Retry is on offer (failed, no publora_post_id)
        assert "unscheduled draft" in row["error"] and "Retry" in row["error"]
        assert loads(row["media"])["postGroupId"] == "pg1"
    before = len(client.steps)
    assert retry_with_picture(pub, pid, picture)["ok"]
    resumed = [s for s in client.steps[before:] if s in MEDIA_STEPS]
    assert resumed == list(MEDIA_STEPS[MEDIA_STEPS.index(step):])           # from the failed step, nothing earlier
    assert len(client.groups) == 1                                          # one post group, ever
    if step == "create":
        (p1, k1), (p2, k2) = client.calls
        assert p1 == p2 and k1 == k2                                        # the identical request, replayed
    else:
        assert len(client.calls) == 1                                       # create-post is never sent again
    row = post_row(db, pid)
    assert (row["status"], row["publora_post_id"], row["media_step"]) == ("scheduled", "pg1", "done")
    assert client.media == [loads(row["media"])["mediaId"]]                 # exactly one picture on the post
    if step == "upload_url":
        assert client.deleted == ["m1"]                                     # the record whose answer was lost


def test_picture_post_never_sends_create_post_twice(setup, picture):
    db, pub, client = setup
    client.fail_once["put"] = requests.Timeout("slow")
    pid = new_post(db)
    schedule_with_picture(pub, pid, "2026-10-08T09:00", None, picture)
    client.fail_once["update"] = requests.Timeout("slow")
    assert not retry_with_picture(pub, pid, picture)["ok"]
    with pytest.raises(ScheduleError):
        schedule_with_picture(pub, pid, "2026-10-08T09:00", None, picture)                # a second click finds it taken
    assert retry_with_picture(pub, pid, picture)["ok"]
    assert len(client.calls) == 1 and client.steps.count("create") == 1
    with pytest.raises(ScheduleError):
        retry_with_picture(pub, pid, picture)                                                      # scheduled: nothing left to retry
    assert len(client.calls) == 1


def test_expired_upload_link_is_replaced_not_reused(setup, picture):
    db, pub, client = setup
    client.fail_once["put"] = requests.Timeout("slow")
    pid = new_post(db)
    schedule_with_picture(pub, pid, "2026-10-08T09:00", None, picture)
    pub.now = lambda: NOW + timedelta(hours=2)                              # Publora's links last 1 hour
    assert retry_with_picture(pub, pid, picture)["ok"]
    assert client.deleted == ["m1"] and client.media == ["m2"] and len(client.calls) == 1
    assert client.puts[-1][0] == "https://s3.test/up/m2"


def test_picture_post_keeps_the_time_window_and_the_quota(setup, picture):
    db, pub, client = setup
    pid = new_post(db)
    with pytest.raises(ScheduleError, match="past"):
        schedule_with_picture(pub, pid, "2026-10-07T11:00", None, picture)
    with pytest.raises(ScheduleError, match="14 days"):
        schedule_with_picture(pub, pid, "2026-10-21T12:00", None, picture)
    for _ in range(3):
        new_post(db, status="scheduled", scheduled_at="2026-10-03T03:30:00+00:00")
    with pytest.raises(ScheduleError, match="Monthly limit reached: 3/3"):
        schedule_with_picture(pub, pid, "2026-10-08T09:00", None, picture)
    assert client.steps == [] and post_row(db, pid)["status"] == "approved"


def test_retry_of_a_picture_post_rechecks_the_quota_and_the_time(setup, picture):
    db, pub, client = setup
    client.fail_once["update"] = requests.Timeout("slow")
    pid = new_post(db)
    schedule_with_picture(pub, pid, "2026-10-08T09:00", None, picture)
    sent = list(client.steps)
    others = [new_post(db, status="scheduled", scheduled_at="2026-10-03T03:30:00+00:00") for _ in range(3)]
    with pytest.raises(ScheduleError, match="Monthly limit"):
        retry_with_picture(pub, pid, picture)
    db.run("DELETE FROM posts WHERE id IN (?,?,?)", tuple(others))
    pub.now = lambda: datetime(2026, 10, 8, 3, 29, tzinfo=timezone.utc)    # 1 minute before it was due
    with pytest.raises(ScheduleError, match="passed"):
        retry_with_picture(pub, pid, picture)
    assert client.steps == sent and post_row(db, pid)["status"] == "failed"


def test_back_to_draft_deletes_the_publora_draft_first(setup, picture):
    db, pub, client = setup
    client.fail_once["put"] = requests.ConnectionError("reset")
    pid = new_post(db)
    schedule_with_picture(pub, pid, "2026-10-08T09:00", None, picture)
    pub.back_to_draft(pid)
    assert client.deleted_groups == ["pg1"]
    row = post_row(db, pid)
    assert (row["status"], row["media"], row["media_step"], row["idempotency_key"]) == ("draft", None, None, None)


def test_app_stopped_between_steps_offers_retry_on_the_next_start(setup, picture):
    db, pub, client = setup
    client.fail_once["put"] = requests.ConnectionError("reset")
    pid = new_post(db)
    text_only = new_post(db, status="scheduling", scheduled_at="2026-10-08T03:30:00+00:00")
    schedule_with_picture(pub, pid, "2026-10-08T09:00", None, picture)
    db.run("UPDATE posts SET status='scheduling' WHERE id=?", (pid,))      # as if the app died mid-upload
    DB(db.path)                                                             # the next start
    row = post_row(db, pid)
    assert row["status"] == "failed" and "Retry" in row["error"]
    assert post_row(db, text_only)["status"] == "scheduling"               # a text post: as before
    assert pub.retry(pid)["ok"] and len(client.calls) == 1                  # none passed: the recorded picture


def test_an_older_database_gains_the_two_columns_and_keeps_its_rows(tmp_path):
    old_schema, n = re.subn(r"error TEXT,\n\s*media TEXT,[^\n]*\n\s*media_step TEXT[^\n]*", "error TEXT", SCHEMA)
    assert n == 1
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript(old_schema)
    con.execute("INSERT INTO posts (created_at, updated_at, title, text, status, scheduled_at, publora_post_id) "
                "VALUES ('t','t','t','A post.','scheduling','2026-10-08T03:30:00+00:00',NULL)")
    con.commit()
    before = dict(zip(*[[c[0] for c in con.execute("SELECT * FROM posts").description],
                        con.execute("SELECT * FROM posts").fetchone()]))
    con.close()
    db = DB(path)
    after = dict(post_row(db, 1))
    assert (after.pop("media"), after.pop("media_step")) == (None, None) and after == before


@pytest.mark.parametrize("mime,content,needle", [
    ("image/bmp", PNG, "PNG, JPEG, WebP or GIF"),
    ("image/jpeg", PNG, "not the JPEG"),
    ("image/png", None, "cannot be read"),
])
def test_a_bad_picture_is_refused_before_anything_is_sent(setup, tmp_path, mime, content, needle):
    db, pub, client = setup
    f = tmp_path / "pic.png"
    if content is not None:
        f.write_bytes(content)
    pid = new_post(db)
    with pytest.raises(ScheduleError, match=needle):
        schedule_with_picture(pub, pid, "2026-10-08T09:00", None, {"path": str(f), "name": "pic.png", "mime": mime})
    assert client.steps == [] and post_row(db, pid)["status"] == "approved"


def test_studio_client_media_requests_match_the_docs(monkeypatch, cfg):
    """The new single requests, on a stand-in base class: the real lib loads .env when imported."""
    sent = []

    class Resp:
        def __init__(self, status_code=200):
            self.status_code = status_code

        def json(self):
            return {"success": True}

    class Session:
        def __getattr__(self, method):
            return lambda url, json=None, headers=None, timeout=None: sent.append((method, url, json, headers)) or Resp()

    class PubloraClient:
        BASE_URL = "https://api.publora.com/api/v1"

        def __init__(self, api_key):
            self.timeout, self._session = 30.0, Session()

        @staticmethod
        def _handle(r):
            return r.json()

    lib, mod = types.ModuleType("lib"), types.ModuleType("lib.publora_client")
    mod.PubloraClient, mod.PubloraError, lib.publora_client = PubloraClient, RuntimeError, mod
    monkeypatch.setitem(sys.modules, "lib", lib)
    monkeypatch.setitem(sys.modules, "lib.publora_client", mod)
    monkeypatch.setattr(publishing, "_CLIENT_CLASS", None)
    storage = {"code": 200}
    monkeypatch.setattr(requests, "put", lambda url, data=None, headers=None, timeout=None:
                        sent.append(("storage", url, data, headers)) or Resp(storage["code"]))
    client = studio_client_class(cfg)(api_key="sk_test")
    client.get_upload_url_once("pg1", "chart.png", "image/png")
    client.put_upload("https://s3.test/up/m1", PNG, "image/png")
    client.update_post_once("pg1", {"status": "scheduled", "scheduledTime": "2026-10-08T03:30:00Z"})
    client.delete_media("m1")
    base = PubloraClient.BASE_URL
    assert sent == [
        ("post", base + "/get-upload-url", {"postGroupId": "pg1", "fileName": "chart.png", "contentType": "image/png"},
         None),
        ("storage", "https://s3.test/up/m1", PNG, {"Content-Type": "image/png"}),   # no Publora key to storage
        ("put", base + "/update-post/pg1", {"status": "scheduled", "scheduledTime": "2026-10-08T03:30:00Z"}, None),
        ("delete", base + "/media/m1", None, None),
    ]
    storage["code"] = 403
    with pytest.raises(RuntimeError, match="HTTP 403"):
        client.put_upload("https://s3.test/up/m1", PNG, "image/png")


def test_the_checksum_keeps_the_upload_to_the_chosen_picture(setup, picture, tmp_path):
    db, pub, client = setup
    pid = new_post(db)
    with pytest.raises(ScheduleError, match="not the one chosen"):
        schedule_with_picture(pub, pid, "2026-10-08T09:00", None, {**picture, "sha256": "0" * 64})
    client.fail_once["put"] = requests.ConnectionError("reset")
    schedule_with_picture(pub, pid, "2026-10-08T09:00", None, picture)
    with open(picture["path"], "ab") as f:
        f.write(b"edited")                                                  # the file changes before Retry
    out = retry_with_picture(pub, pid, picture)
    assert not out["ok"] and out["step"] == "put" and "changed since it was chosen" in out["error"]
    assert len(client.puts) == 1                                            # the changed bytes never went up
    other = tmp_path / "other.png"
    other.write_bytes(PNG + b"other")
    with pytest.raises(ScheduleError, match="another picture"):
        retry_with_picture(pub, pid, {"path": str(other), "name": "other.png", "mime": "image/png",
                                      "sha256": hashlib.sha256(PNG + b"other").hexdigest()})


def test_retry_follows_the_same_picture_to_its_new_path(setup, picture, tmp_path):
    db, pub, client = setup
    client.fail_once["put"] = requests.ConnectionError("reset")
    pid = new_post(db)
    schedule_with_picture(pub, pid, "2026-10-08T09:00", None, picture)
    moved = tmp_path / "moved.png"
    moved.write_bytes(PNG)
    assert retry_with_picture(pub, pid, {**picture, "path": str(moved)})["ok"]
    assert loads(post_row(db, pid)["media"])["path"] == str(moved.resolve()) and len(client.calls) == 1


def test_no_picture_is_todays_single_request(setup):
    db, pub, client = setup
    pid = new_post(db)
    assert schedule_with_picture(pub, pid, "2026-10-08T09:00", None, None)["ok"]
    (payload, _key), = client.calls
    assert client.steps == ["create"] and payload["scheduledTime"] == "2026-10-08T03:30:00Z"
    row = post_row(db, pid)
    assert (row["status"], row["media"], row["media_step"]) == ("scheduled", None, None)


# ---- Publora's answer, by itself: Check now and the light check (app/status_check.py) ------------------------
class Recorder:
    """Publora that answers get-post with `answer` (or raises it) and records every request by name. Reading a post's
    status may only ask get-post: any other request (create, update, delete...) is recorded, and fails the test."""

    def __init__(self, answer=None):
        self.answer = {"status": "scheduled", "posts": []} if answer is None else answer
        self.asked = []

    def get_post(self, post_group_id):
        self.asked.append(("get_post", post_group_id))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)

        def sent(*args, **kwargs):
            self.asked.append((name, args))
            raise AssertionError(f"reading the status sent {name}")
        return sent

    def only_read(self):
        return all(name == "get_post" for name, _ in self.asked)


DUE = "2026-10-07T03:30:00+00:00"       # 9:00 IST, before NOW


@pytest.fixture
def reader(cfg, tmp_path):
    def make(answer):
        db = DB(tmp_path / "r.db")
        recorder = Recorder(answer)
        pub = Publisher(db, cfg, client_factory=lambda: recorder, now=lambda: NOW)
        pid = new_post(db, status="scheduled", scheduled_at=DUE)
        db.run("UPDATE posts SET publora_post_id='pg7' WHERE id=?", (pid,))
        return db, pub, recorder, pid
    return make


@pytest.mark.parametrize("answer,link", [
    ({"status": "published", "posts": [{"status": "published", "postedId": "urn:li:share:7101",
                                        "permalink": "https://www.linkedin.com/posts/demo-author_activity-7101-AbCd"}]},
     "https://www.linkedin.com/posts/demo-author_activity-7101-AbCd"),                      # its permalink
    ({"postGroup": {"status": "published", "posts": [{"status": "published", "postedId": "urn:li:activity:7102"}]}},
     "https://www.linkedin.com/feed/update/urn:li:activity:7102"),                          # no permalink: its urn
    ({"status": "partially_published", "posts": [{"postedId": "urn:li:ugcPost:7103", "permalink": ""}]},
     "https://www.linkedin.com/feed/update/urn:li:ugcPost:7103"),
    ({"status": "published", "posts": [{"status": "published"}]}, None),                     # no link given
])
def test_refresh_marks_it_published_with_its_linkedin_link(reader, answer, link):
    db, pub, recorder, pid = reader(answer)
    assert pub.refresh(pid) == "published"
    row = post_row(db, pid)
    assert (row["status"], row["published_url"], row["error"]) == ("published", link, None)
    assert recorder.asked == [("get_post", "pg7")] and recorder.only_read()


@pytest.mark.parametrize("permalink,posted", [
    ("javascript:alert(1)", None),
    ("https://example.com/www.linkedin.com/feed/update/urn:li:share:1", None),
    ("https://www.linkedin.com.example.com/feed/update/urn:li:share:1", None),
    ("http://www.linkedin.com/feed/update/urn:li:share:1", None),
    ('https://www.linkedin.com/feed/update/urn:li:share:1" onmouseover="alert(1)', None),
    ("https://www.linkedin.com/feed/update/urn:li:share:1" + chr(10) + "javascript:alert(1)", None),
    (None, "javascript:alert(1)"),
    (None, "urn:li:share:1/../../logout"),
    (None, "7104"),
])
def test_a_link_that_is_not_linkedins_is_never_stored(reader, permalink, posted):
    db, pub, recorder, pid = reader({"status": "published", "posts": [{"permalink": permalink, "postedId": posted}]})
    assert pub.refresh(pid) == "published"
    assert post_row(db, pid)["published_url"] is None and recorder.only_read()


@pytest.mark.parametrize("answer,error", [
    ({"status": "failed", "error": "The group failed", "posts": [{"status": "failed", "error": "LinkedIn refused the token"}]},
     "Publora says it failed: LinkedIn refused the token; The group failed"),
    ({"postGroup": {"status": "failed", "error": {"code": "RATE", "message": "Too many posts today"}}},
     "Publora says it failed: Too many posts today"),
    ({"status": "failed", "posts": [{"status": "failed", "error": None}]}, NO_REASON),
])
def test_failed_keeps_publoras_own_words(reader, answer, error):
    db, pub, recorder, pid = reader(answer)
    assert pub.refresh(pid) == "failed"
    row = post_row(db, pid)
    assert (row["status"], row["error"], row["published_url"]) == ("failed", error, None) and recorder.only_read()
    assert "no reason" in NO_REASON


@pytest.mark.parametrize("answer", [{"status": "scheduled"}, {"status": "processing"}, {"status": "draft"}, {},
                                    {"postGroup": {"status": "something new"}}, "not an object"])
def test_any_other_answer_leaves_it_scheduled(reader, answer):
    db, pub, recorder, pid = reader(answer)
    before = dict(post_row(db, pid))
    assert pub.refresh(pid) == "scheduled"
    assert dict(post_row(db, pid)) == before and recorder.only_read()


def test_refresh_asks_nothing_about_a_post_that_is_not_scheduled_or_is_in_the_trash(reader):
    db, pub, recorder, pid = reader({"status": "published"})
    db.run("UPDATE posts SET trashed_at=? WHERE id=?", (utcnow(), pid))
    assert pub.refresh(pid) == "scheduled" and post_row(db, pid)["status"] == "scheduled"
    for status in ("draft", "approved", "published", "failed", "cancelled"):
        assert pub.refresh(new_post(db, status=status, scheduled_at=DUE)) == status
    assert recorder.asked == []


def test_an_older_database_gains_published_url_and_keeps_its_rows(tmp_path):
    old_schema = "\n".join(line for line in SCHEMA.splitlines() if not line.strip().startswith("published_url"))
    assert old_schema != SCHEMA
    path = tmp_path / "before.db"
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(old_schema)
    for status in ("scheduled", "published", "draft"):
        con.execute("INSERT INTO posts (created_at, updated_at, title, text, status, scheduled_at, publora_post_id) "
                    "VALUES ('t','t','t',?,?,?,?)", (f"A {status} post.", status, DUE, "pg1" if status != "draft" else None))
    con.commit()
    before = [dict(r) for r in con.execute("SELECT * FROM posts ORDER BY id")]
    con.close()
    db = DB(path)
    assert db.started["columns"] == ["posts.published_url"] and db.started["tables"] == []
    after = [dict(r) for r in db.all("SELECT * FROM posts ORDER BY id")]
    assert [a.pop("published_url") for a in after] == [None, None, None] and after == before


@pytest.fixture
def checked(cfg, tmp_path, fake_runner):
    """A studio whose Publora is a Recorder, with posts the light check must and must not ask about. `check` is passed
    as check_publora; None passes nothing, as every other test makes its studio."""
    made = []

    def make(check, answer=None):
        path = tmp_path / f"check{len(made)}.db"
        recorder = Recorder(answer)
        flag = {} if check is None else {"check_publora": check}
        app = create_app(cfg, TOKEN, db_path=path, runner=fake_runner, publisher=Publisher(DB(path), cfg, client_factory=lambda: recorder),
                         **flag)
        client = TestClient(app, base_url=f"http://127.0.0.1:{cfg.port}", headers={"Origin": cfg.origin})
        client.__enter__()
        made.append(client)
        client.cookies.set("studio_session", TOKEN)
        db = app.state.db
        ids = {}
        for name, at, group in (("due", "2026-10-01T03:30:00+00:00", "pg-due"), ("later", "2099-10-01T03:30:00+00:00", "pg-later"),
                                ("trashed", "2026-10-01T03:30:00+00:00", "pg-trashed")):
            ids[name] = new_post(db, status="scheduled", scheduled_at=at)
            db.run("UPDATE posts SET publora_post_id=? WHERE id=?", (group, ids[name]))
        db.run("UPDATE posts SET trashed_at=? WHERE id=?", (utcnow(), ids["trashed"]))
        return client, app, recorder, ids

    yield make
    for client in made:
        client.__exit__(None, None, None)


def test_the_light_check_is_off_unless_asked_for_and_then_asks_at_most_every_few_minutes(checked):
    """The guard: a studio made without check_publora (every test's) never asks Publora, however often it is polled
    with a due post. With it, two polls within 3 minutes make one check, of the due post only: never one not yet due,
    and never one in the Trash. And it only reads."""
    client, app, recorder, _ids = checked(check=None)
    for _ in range(20):
        assert client.get("/api/state").status_code == 200
    app.state.checker.wait()
    assert recorder.asked == [] and app.state.checker._thread is None

    client, app, recorder, ids = checked(check=True)
    checker = app.state.checker
    client.get("/api/state")
    checker.wait()
    assert recorder.asked == [("get_post", "pg-due")]
    client.get("/api/state")
    checker.wait()
    assert recorder.asked == [("get_post", "pg-due")]                          # within 3 minutes: no second check
    real = checker.now
    checker.now = lambda: real() + EVERY + timedelta(seconds=1)
    client.get("/api/state")
    checker.wait()
    assert recorder.asked == [("get_post", "pg-due")] * 2 and recorder.only_read()
    assert EVERY == timedelta(minutes=3)


def test_check_now_answers_in_words_and_a_failed_ask_stays_for_the_notice(checked):
    client, app, recorder, ids = checked(check=True)
    assert client.get(f"/api/post/{ids['due']}").json()["waiting"]["text"].startswith("Its time has passed: the studio asks")
    waiting = client.post(f"/api/post/{ids['due']}/refresh", json={}).json()
    assert waiting["status"] == "scheduled" and re.fullmatch(
        r"Not out yet: Publora still has it scheduled \(checked \d{1,2}:\d{2} [ap]m\)\.", waiting["said"])
    assert waiting["waiting"] == client.get(f"/api/post/{ids['due']}").json()["waiting"]   # the notice as the post says it
    later = client.post(f"/api/post/{ids['later']}/refresh", json={}).json()["said"]
    assert re.fullmatch(r"All set: Publora has it scheduled \(checked \d{1,2}:\d{2} [ap]m\)\.", later)
    assert client.get(f"/api/post/{ids['due']}").json()["waiting"]["text"].startswith("Not out yet as of ")
    assert client.get(f"/api/post/{ids['later']}").json()["waiting"] is None    # not due: nothing to say yet
    recorder.answer = requests.ConnectionError("reset")
    refused = client.post(f"/api/post/{ids['due']}/refresh", json={})
    assert refused.status_code == 502 and "no answer (ConnectionError)" in refused.json()["error"]
    notice = client.get(f"/api/post/{ids['due']}").json()["waiting"]
    assert notice["failed"] and "could not ask Publora" in notice["text"] and "every few minutes" in notice["text"]
    recorder.answer = {"status": "published", "posts": [{"permalink": "https://www.linkedin.com/feed/update/urn:li:share:7105"}]}
    said = client.post(f"/api/post/{ids['due']}/refresh", json={}).json()
    assert said == {"status": "published", "said": "Publora says it is published. Open on LinkedIn shows it.", "waiting": None}
    shown = client.get(f"/api/post/{ids['due']}").json()
    assert (shown["status"], shown["link"], shown["waiting"]) == ("published", "https://www.linkedin.com/feed/update/urn:li:share:7105", None)
    assert [p["link"] for p in client.get("/api/state").json()["posts"] if p["id"] == ids["due"]] == [shown["link"]]
    app.state.db.run("UPDATE posts SET published_url='javascript:alert(1)' WHERE id=?", (ids["due"],))
    assert client.get(f"/api/post/{ids['due']}").json()["link"] is None        # a stored address is checked again
    assert client.post(f"/api/post/{ids['trashed']}/refresh", json={}).status_code == 404
    assert recorder.only_read() and ("get_post", "pg-trashed") not in recorder.asked


def test_the_demos_publora_sends_a_post_at_its_time(cfg, tmp_path):
    """dev/demo_server.py's stand-in: scheduled until the time it was given, then published with a made-up link."""
    from dev.demo_server import ScriptedPublora
    stand_in = ScriptedPublora()
    stand_in.update_post_once("demo-due", {"status": "scheduled", "scheduledTime": "2026-10-01T03:30:00Z"})
    stand_in.update_post_once("demo-later", {"status": "scheduled", "scheduledTime": "2099-10-01T03:30:00Z"})
    db = DB(tmp_path / "demo.db")
    pub = Publisher(db, cfg, client_factory=lambda: stand_in)
    due, later, unknown = (new_post(db, status="scheduled", scheduled_at=DUE) for _ in range(3))
    for pid, group in ((due, "demo-due"), (later, "demo-later"), (unknown, "demo-unknown")):
        db.run("UPDATE posts SET publora_post_id=? WHERE id=?", (group, pid))
    assert [pub.refresh(pid) for pid in (due, later, unknown)] == ["published", "scheduled", "scheduled"]
    assert post_row(db, due)["published_url"] == "https://www.linkedin.com/feed/update/urn:li:share:demo-due"
