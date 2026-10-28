"""Draft all, on the Planner's week plan: Claude writes every planned post that has no draft yet, one at a time.

There is no batch table. Each step is an ordinary 'draft' job on the one worker, with the params the card's own Draft
this sends (`draft_params`, one definition for both) and `batch` = {id, plan_id, at, of}. Only one step is ever
waiting: the next is queued when the one before it is saved (flows.draft_done calls `chain`), so whatever the owner
asks for meanwhile is already in line ahead of it. Each step takes the first item still without a draft, so one drafted
by hand meanwhile is skipped.

A failed, unparsed or stopped step ends the batch: nothing chains from it. Stop cancels the batch's job through
jobs.cancel, which sets the job's acked flag; `chain` reads that flag under the lock Stop takes, so a Stop that lands
just as a draft finishes still ends the rest. Try again on a failed step's card runs that one draft again (its params
still carry the batch, so the end line counts it) and chains nothing.
"""
from __future__ import annotations

import logging
import secrets
import threading
from typing import Any

from . import style
from .db import loads

log = logging.getLogger("studio.draft_all")

ACTIVE = ("queued", "running")
FAILED = ("failed", "unparsed")
ENDED = ("failed", "unparsed", "cancelled")
ITEM_FIELDS = ("angle", "formula", "pillar", "goal", "cta", "format", "bank_section")
_handoff = threading.Lock()     # a step handing over to the next, a start and a Stop never interleave


def draft_params(db, row) -> dict:
    """What a plan item's draft asks the post writer (a plan_items row): Draft this on a card, and each Draft all step."""
    plan = db.one("SELECT inputs FROM plans WHERE id=?", (row["plan_id"],))
    item = loads(row["data"], {}) or {}
    inputs = (loads(plan["inputs"], {}) or {}) if plan else {}
    params = {k: item.get(k) for k in ITEM_FIELDS}
    params.update(plan_item_id=row["id"], audience=inputs.get("audience"), style=style.default(db))
    return params


def left(db, plan_id: int) -> list[dict]:
    """The plan's items in the board's order that have no draft and none on its way."""
    from .flows import plan_items  # noqa: PLC0415  (flows imports this module)

    being = {(loads(r["params"], {}) or {}).get("plan_item_id")
             for r in db.all("SELECT params FROM jobs WHERE kind='draft' AND status IN ('queued','running')")}
    return [i for i in plan_items(db, plan_id) if not i.get("post_id") and i["id"] not in being]


def _batch_of(row) -> dict:
    return (loads(row["params"], {}) or {}).get("batch") or {}


def _steps(db, batch_id: str) -> list:
    return db.all("SELECT * FROM jobs WHERE kind='draft' AND json_extract(params,'$.batch.id')=? ORDER BY id", (batch_id,))


def _ended(steps: list, but: int | None = None) -> bool:
    """A step failed, came back unreadable or was stopped (cancelled, or acked while it still runs: Stop on its way)."""
    return any(j["id"] != but and (j["status"] in ENDED or (j["status"] in ACTIVE and j["acked"])) for j in steps)


def running(db) -> dict | None:
    """The batch under way, if any: its newest step's batch params, that step's job id, and its active steps' ids."""
    for row in db.all("SELECT * FROM jobs WHERE kind='draft' AND status IN ('queued','running') "
                      "AND json_extract(params,'$.batch.id') IS NOT NULL ORDER BY id DESC"):
        steps = _steps(db, _batch_of(row).get("id"))
        if not _ended(steps):
            active = [j for j in steps if j["status"] in ACTIVE]
            return {**_batch_of(active[-1]), "job": active[-1]["id"], "active": [j["id"] for j in active]}
    return None


def start(jobs, db, plan_id: int) -> tuple[int | None, str]:
    """The first step of a Draft all on this plan: (its job id, "") or (None, why it is refused)."""
    with _handoff:
        if running(db):
            return None, "Draft all is already writing your planned posts. Stop it first, or wait for it to finish."
        todo = left(db, plan_id)
        if not todo:
            return None, "Every planned post already has a draft, or is being written."
        row = db.one("SELECT * FROM plan_items WHERE id=?", (todo[0]["id"],))
        batch = {"id": secrets.token_hex(6), "plan_id": plan_id, "at": 1, "of": len(todo)}
        return jobs.submit("draft", {**draft_params(db, row), "batch": batch}), ""


def chain(jobs, db, job_id: int, params: dict) -> None:
    """A Draft all step's draft is saved: queue the next item still without one, unless the batch has ended."""
    batch = params.get("batch")
    if not isinstance(batch, dict) or not batch.get("id"):
        return
    try:
        with _handoff:
            row = db.one("SELECT acked FROM jobs WHERE id=?", (job_id,))
            if row is None or row["acked"]:
                return                      # Stop came as this draft finished: the rest is not written
            if _ended(_steps(db, batch["id"]), but=job_id):
                return                      # Try again on a step that failed: that one draft only
            todo = left(db, batch["plan_id"])
            if not todo:
                return
            item = db.one("SELECT * FROM plan_items WHERE id=?", (todo[0]["id"],))
            at = int(batch.get("at") or 1)
            jobs.submit("draft", {**draft_params(db, item), "batch": {**batch, "at": at + 1, "of": at + len(todo)}})
    except Exception:  # the draft itself is saved; a batch that cannot go on just ends
        log.exception("Draft all could not queue the step after job %s", job_id)


def stop(jobs, db) -> str:
    """Stop: cancel the batch's job (and a next one queued that same moment). Returns what it did, in words, or ""."""
    with _handoff:
        found = running(db)
        if not found:
            return ""
        for job_id in found["active"]:
            jobs.cancel(job_id)
    written = sum(1 for j in _steps(db, found["id"]) if j["status"] == "done")
    return (f"Stopped. Draft all wrote {written} of {found.get('of')}; the rest still have no draft."
            if written else "Stopped. Nothing more is written; the planned posts still have no draft.")


def ended_line(db, plan_id: int) -> dict | None:
    """How the plan's newest batch ended, until dismissed: {job, written, of, failed: [{item, angle}]}.

    None while it runs, once it is dismissed (the newest step's acked flag: Dismiss on the line, or on a failed step's
    card), and for a stopped batch (Stop says so itself)."""
    newest = db.one("SELECT * FROM jobs WHERE kind='draft' AND json_extract(params,'$.batch.plan_id')=? ORDER BY id DESC LIMIT 1",
                    (plan_id,))
    if newest is None:
        return None
    steps = _steps(db, _batch_of(newest).get("id"))
    last = steps[-1] if steps else None
    if last is None or last["acked"] or any(j["status"] in ACTIVE for j in steps) or last["status"] == "cancelled":
        return None
    latest: dict[Any, Any] = {}
    for j in steps:                         # the newest step of each item: Try again replaces the one that failed
        latest[(loads(j["params"], {}) or {}).get("plan_item_id")] = j
    failed = [{"item": item, "angle": (loads(j["params"], {}) or {}).get("angle") or "A planned post"}
              for item, j in latest.items() if j["status"] in FAILED]
    return {"job": last["id"], "written": sum(1 for j in latest.values() if j["status"] == "done"),
            "of": _batch_of(last).get("of") or len(latest), "failed": failed}


def board(db, plan_id: int) -> dict:
    """What a board of the Planner shows of Draft all: how many are left, the batch under way on it, how one ended."""
    found = running(db)
    on_it = found if found and found.get("plan_id") == plan_id else None
    return {"left": len(left(db, plan_id)),
            "running": {"at": on_it.get("at"), "of": on_it.get("of"), "job": on_it["job"]} if on_it else None,
            "last": None if on_it else ended_line(db, plan_id)}


def register(app, s) -> None:
    """POST /api/planner/{plan_id}/draft-all and POST /api/planner/draft-all/stop."""
    from .api_posts import fail  # noqa: PLC0415  (api_posts needs main, which loads flows, which loads this)

    @app.post("/api/planner/{plan_id}/draft-all")
    def draft_all_start(plan_id: int):
        if s.db.one("SELECT 1 FROM plans WHERE id=?", (plan_id,)) is None:
            return fail("That plan no longer exists.", 404)
        job, refused = start(s.jobs, s.db, plan_id)
        return fail(refused, 409) if refused else {"job": job}

    @app.post("/api/planner/draft-all/stop")
    def draft_all_stop():
        said = stop(s.jobs, s.db)
        return {"ok": True, "said": said} if said else fail("Draft all is not running.", 409)
