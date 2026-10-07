import threading
import time

from app.claude_runner import RunResult
from app.db import DB
from app.jobs import JobManager, wait_for


class SlowRunner:
    """Records how many runs overlap; each run takes `delay` seconds unless cancelled."""

    def __init__(self, delay=0.6):
        self.delay = delay
        self.running = 0
        self.max_running = 0
        self.lock = threading.Lock()

    def run(self, req, cancel=None, on_progress=None, timeout=None):
        with self.lock:
            self.running += 1
            self.max_running = max(self.max_running, self.running)
        try:
            end = time.monotonic() + self.delay
            while time.monotonic() < end:
                if cancel is not None and cancel.is_set():
                    return RunResult(outcome="cancelled", error="Cancelled.")
                time.sleep(0.02)
            return RunResult(outcome="ok", text="x", data={"rewritten": "y"})
        finally:
            with self.lock:
                self.running -= 1


def test_one_claude_job_at_a_time(tmp_path):
    db, runner = DB(tmp_path / "j.db"), SlowRunner()
    jobs = JobManager(db, runner)
    ids = [jobs.submit("humanize", {"text": f"t{i}"}) for i in range(3)]
    time.sleep(0.2)
    states = [db.one("SELECT status FROM jobs WHERE id=?", (i,))["status"] for i in ids]
    assert states == ["running", "queued", "queued"]
    for i in ids:
        assert wait_for(db, i, 10)["status"] == "done"
    assert runner.max_running == 1
    runs = db.all("SELECT * FROM runs")
    assert len(runs) == 3 and all(r["outcome"] == "ok" for r in runs)
    jobs.shutdown()


def test_cancel_running_and_queued(tmp_path):
    db, runner = DB(tmp_path / "j.db"), SlowRunner(delay=5)
    jobs = JobManager(db, runner)
    first, second = jobs.submit("humanize", {"text": "a"}), jobs.submit("humanize", {"text": "b"})
    time.sleep(0.2)
    jobs.cancel(second)
    jobs.cancel(first)
    assert wait_for(db, first, 5)["status"] == "cancelled"
    assert wait_for(db, second, 5)["status"] == "cancelled"
    jobs.shutdown()


def test_shutdown_cancels_the_running_job(tmp_path):
    db, runner = DB(tmp_path / "j.db"), SlowRunner(delay=30)
    jobs = JobManager(db, runner)
    job = jobs.submit("humanize", {"text": "a"})
    time.sleep(0.2)
    started = time.monotonic()
    jobs.shutdown()
    assert time.monotonic() - started < 5
    assert db.one("SELECT status FROM jobs WHERE id=?", (job,))["status"] == "cancelled"
