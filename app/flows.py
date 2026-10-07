"""What happens around each Claude job: input fetched before it, results stored after it."""
from __future__ import annotations

import difflib
import re
from pathlib import Path

from .claude_runner import RunResult
from .config import Config
from .db import DB, dumps, loads, utcnow
from .jobs import JobManager
from .publishing import _lib, read_env


def fetch_post_text(cfg: Config, url: str) -> str:
    """Backend-side Apify read (lib/apify_client.py). Claude never gets the token or the network."""
    _lib(cfg)
    from lib.url_parser import parse_linkedin_url  # noqa: PLC0415
    from lib.apify_client import ApifyClient  # noqa: PLC0415

    if not parse_linkedin_url(url).get("post_urn"):
        raise ValueError("That is not a LinkedIn post URL. Paste the post text instead.")
    token = read_env(cfg).get("APIFY_TOKEN")
    if not token:
        raise ValueError("No Apify token in linkedin-skills\\.env, so the post cannot be fetched. Paste its text.")
    post = ApifyClient(token=token).fetch_post(url)
    text = (post.get("text") or "").strip()
    if not text:
        raise ValueError("Apify returned no text for that post. Paste it instead.")
    author = post.get("authorName")
    return f"Author: {author}\n\n{text}" if author else text


def short_title(text: str, limit: int = 80) -> str:
    """A list-friendly title: no parentheticals, cut at a word boundary."""
    text = re.sub(r"\s*\([^)]*\)?", "", " ".join((text or "").split())).strip(" ,;:-")
    if len(text) <= limit:
        return text or "Untitled draft"
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-") + "…"


def unified_diff(before: str, after: str, name: str) -> str:
    return "".join(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
                                        fromfile=f"{name} (before)", tofile=f"{name} (after)", n=1))


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def register(jobs: JobManager, db: DB, cfg: Config) -> None:
    def needs_post_text(job_id: int, params: dict, progress) -> dict:
        if params.get("text", "").strip():
            return {"params": params}
        if not params.get("url"):
            raise ValueError("Paste the post text, or give a post URL with an Apify token configured.")
        progress("Fetching the post through Apify")
        params = {**params, "text": fetch_post_text(cfg, params["url"])}
        db.run("UPDATE jobs SET params=? WHERE id=?", (dumps(params), job_id))
        return {"params": params}

    jobs.prepare["hook"] = needs_post_text
    jobs.prepare["comment"] = needs_post_text

    # ---- planner -------------------------------------------------------------
    def plan_done(job_id: int, params: dict, result: RunResult, ctx: dict) -> None:
        data = result.data
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            return  # unparsed: the job keeps the raw text and offers Retry
        plan_id = db.run("INSERT INTO plans (created_at, inputs, result) VALUES (?,?,?)",
                         (utcnow(), dumps(params), dumps(data)))
        for i, item in enumerate(data["items"]):
            if isinstance(item, dict):
                db.run("INSERT INTO plan_items (plan_id, position, data) VALUES (?,?,?)", (plan_id, i, dumps(item)))
        db.run("UPDATE jobs SET params=? WHERE id=?", (dumps({**params, "plan_id": plan_id}), job_id))

    jobs.finish["plan"] = plan_done

    # ---- drafts --------------------------------------------------------------
    def draft_done(job_id: int, params: dict, result: RunResult, ctx: dict) -> None:
        data = result.data
        if not isinstance(data, dict) or not str(data.get("text") or "").strip():
            return
        title = short_title(params.get("angle") or params.get("topic") or "")
        now = utcnow()
        post_id = db.run(
            "INSERT INTO posts (created_at, updated_at, plan_item_id, title, text, first_comment, formula, notes, status) "
            "VALUES (?,?,?,?,?,?,?,?, 'draft')",
            (now, now, params.get("plan_item_id"), title, data["text"].strip(), data.get("first_comment") or None,
             data.get("formula"), dumps(data.get("notes") or [])))
        if params.get("plan_item_id"):
            db.run("UPDATE plan_items SET post_id=? WHERE id=?", (post_id, params["plan_item_id"]))
        db.run("UPDATE jobs SET params=? WHERE id=?", (dumps({**params, "post_id": post_id}), job_id))

    jobs.finish["draft"] = draft_done

    def audit_done(job_id: int, params: dict, result: RunResult, ctx: dict) -> None:
        if params.get("post_id") and isinstance(result.data, dict):
            db.run("UPDATE posts SET audit=?, updated_at=? WHERE id=?",
                   (dumps({**result.data, "job_id": job_id, "text": params["text"]}), utcnow(), params["post_id"]))

    jobs.finish["audit"] = audit_done

    # ---- chat skills that own one file ---------------------------------------
    def chat_hooks(kind: str, path: Path):
        def session(params: dict) -> str | None:
            row = db.one("SELECT session_id FROM conversations WHERE id=?", (params["conversation_id"],))
            return row["session_id"] if row else None

        def before(job_id: int, params: dict, progress) -> dict:
            return {"before": read_text(path)}

        def done(job_id: int, params: dict, result: RunResult, ctx: dict) -> None:
            after = read_text(path)
            diff = unified_diff(ctx.get("before", ""), after, path.name) if after != ctx.get("before") else ""
            if result.session_id:
                db.run("UPDATE conversations SET session_id=? WHERE id=?", (result.session_id, params["conversation_id"]))
            db.run("INSERT INTO messages (conversation_id, role, text, diff, job_id, created_at) VALUES (?,?,?,?,?,?)",
                   (params["conversation_id"], "assistant", result.clean_text or result.text, diff or None,
                    job_id, utcnow()))

        jobs.session_for[kind] = session
        jobs.prepare[kind] = before
        jobs.finish[kind] = done

    chat_hooks("interview", cfg.story_bank)
    chat_hooks("voice", cfg.voice_profile)


DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def plan_items(db: DB, plan_id: int) -> list[dict]:
    rows = db.all("SELECT * FROM plan_items WHERE plan_id=? ORDER BY position", (plan_id,))
    items = [{"id": r["id"], "post_id": r["post_id"], **loads(r["data"], {})} for r in rows]
    day = lambda i: next((n for n, d in enumerate(DAYS) if str(i.get("day", "")).lower().startswith(d)), 7)  # noqa: E731
    return sorted(items, key=day)
