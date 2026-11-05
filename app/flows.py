"""What happens around each Claude job: input fetched before it, results stored after it."""
from __future__ import annotations

import difflib
import re
from pathlib import Path

from . import attached, bold, carousel, codex, hot, images, style, versions
from .claude_runner import RunResult
from .config import Config
from .db import DB, dumps, loads, utcnow
from .jobs import JobManager
from .publishing import _lib, placeholder_slots, read_env

HISTORY = 16          # the latest messages of a chat that go with a request (chat_history)
HISTORY_CHARS = 1500  # each, at most
RANK_SECONDS = 420    # a Hot topics ranking run's time, at least: hot.BATCH items judged in one run


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


def add_message(db: DB, conversation_id: int, role: str, text: str, *, job_id: int | None = None,
                diff: str | None = None, meta: dict | None = None) -> int:
    return db.run("INSERT INTO messages (conversation_id, role, text, diff, job_id, meta, created_at) VALUES (?,?,?,?,?,?,?)",
                  (conversation_id, role, text, diff or None, job_id, dumps(meta) if meta else None, utcnow()))


def ended_words(result: RunResult) -> tuple[str, str, str]:
    """A run that did not answer, in the chat: (role, words, what the chat offers next)."""
    if result.outcome == "cancelled":
        return "info", "Stopped.", "carry"
    if result.outcome == "timeout":
        return "error", result.error or "It took too long and was stopped.", "carry"
    if "turn limit" in (result.error or ""):
        return "error", result.error, "carry"
    return "error", result.error or result.parse_error or "Claude did not finish.", "again"


def chat_history(db: DB, conversation_id: int, request_id: int) -> list[dict]:
    """A chat's latest messages before this request, oldest first, for the prompt (skills._conversation): a post's
    chat sends them with every request; an interview, only when its saved session could not be resumed."""
    rows = db.all("SELECT role, text FROM messages WHERE conversation_id=? AND id<? ORDER BY id DESC LIMIT ?",
                  (conversation_id, request_id, HISTORY))
    return [{"role": r["role"], "text": (r["text"] or "")[:HISTORY_CHARS]} for r in reversed(rows)]


def post_chat_context(db: DB, post_id: int, conversation_id: int, request_id: int) -> tuple[dict, list]:
    """The post as it stands and the chat so far, for the prompt (skills._post_chat)."""
    post = db.one("SELECT * FROM posts WHERE id=?", (post_id,))
    if post is None:
        raise ValueError("This post is no longer in the studio.")
    going = images.chosen(db, post)
    if going and images.is_carousel(going[0]):
        picture = f"a carousel of {going[0]['pages']} slides goes out with it"
    elif going:
        picture = "1 picture goes out with it" if len(going) == 1 else f"{len(going)} pictures go out with it"
    else:
        picture = "none chosen"
    # The looks of the latest carousels and cards anywhere, so a new one is drawn unlike them (carousel.LOOKS)
    lately = [(loads(r["spec"], {}) or {}).get("look") or "midnight" for r in
              db.all("SELECT spec FROM images WHERE source IN ('carousel','card') AND spec IS NOT NULL ORDER BY id DESC LIMIT 4")]
    if lately:
        picture += f". Looks used lately on carousels and cards: {', '.join(dict.fromkeys(lately))}"
    audit = loads(post["audit"], None)
    audit_line = ""
    if isinstance(audit, dict) and audit.get("verdict"):
        audit_line = f"{audit.get('verdict')}: {audit.get('summary') or ''}".strip()
        if audit.get("text") != post["text"]:
            audit_line += " (the text has changed since)"
    news = loads(post["news"], None)
    news_line = f"{news.get('title')} ({news.get('source')}, {news.get('url')})" if isinstance(news, dict) else ""
    history = chat_history(db, conversation_id, request_id)
    return {"status": post["status"], "text": post["text"], "first_comment": post["first_comment"],
            "chars": len(post["text"]), "blanks": len(placeholder_slots(post["text"])), "picture": picture,
            "audit": audit_line, "news": news_line, "style": style.of_post(db, post)}, history


MODE_OF = {"interview": "bank", "voice": "voice"}


def register(jobs: JobManager, db: DB, cfg: Config) -> None:
    def with_attachments(params: dict, key: str) -> dict:
        """A chat message's files: the folder its run may Read, and the lines its prompt gets for them."""
        if not params.get("files"):
            return params
        where, lines = attached.for_run(db, key, params["files"])
        return {**params, "attach_dir": where, "attached": lines}

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

    # ---- drafts --------------------------------------------------------------
    def draft_prepare(job_id: int, params: dict, progress) -> dict:
        """A Hot topics draft: the item's text, read once (hot.text_for) and kept with the job, so Try again reads the
        same text."""
        news = params.get("news")
        if not isinstance(news, dict) or news.get("read"):
            return {"params": params}
        progress("Reading the article")
        text, how = hot.text_for(db, news)
        params = {**params, "news": {**news, "text": text, "read": how}}
        db.run("UPDATE jobs SET params=? WHERE id=?", (dumps(params), job_id))
        return {"params": params}

    jobs.prepare["draft"] = draft_prepare

    def draft_done(job_id: int, params: dict, result: RunResult, ctx: dict) -> None:
        data = result.data
        if not isinstance(data, dict) or not str(data.get("text") or "").strip():
            return
        title = short_title(params.get("angle") or params.get("topic") or "")
        now = utcnow()
        text = bold.from_marks(data["text"].strip())
        first = data.get("first_comment") or None
        notes = [str(n) for n in data.get("notes") or [] if n]
        news = params.get("news") if isinstance(params.get("news"), dict) else None
        if news:
            # The article's link always goes with the post, in its first comment (where LinkedIn does not cut its reach).
            if news.get("url") and news["url"] not in (first or ""):
                first = f"{first.rstrip()}\n\n{news['url']}" if first else news["url"]
            if news.get("read") == "summary":
                notes.insert(0, "Written from the news item's summary alone: its page could not be read. "
                                "Check the post against the link.")
        post_id = db.run(
            "INSERT INTO posts (created_at, updated_at, title, text, first_comment, formula, notes, news, status) "
            "VALUES (?,?,?,?,?,?,?,?, 'draft')",
            (now, now, title, text, first, data.get("formula"), dumps(notes),
             dumps({k: news.get(k) for k in hot.NEWS_FIELDS if k != "summary"}) if news else None))
        versions.record(db, post_id, text, first, "claude", "First draft")
        db.run("UPDATE jobs SET params=? WHERE id=?", (dumps({**params, "post_id": post_id}), job_id))

    jobs.finish["draft"] = draft_done

    # ---- Hot topics, ranked for the owner -----------------------------------------
    def hot_rank_done(job_id: int, params: dict, result: RunResult, ctx: dict) -> None:
        """A batch's ranks kept, then the next batch (one run at a time, so a Draft pressed meanwhile is next in line).
        A run that came back with nothing usable chains nothing: the page offers Try again."""
        if hot.keep_ranks(db, params, result.data):
            hot.rank_next(jobs, db, but=job_id)     # this run is still marked running while its end is kept

    jobs.finish["hot_rank"] = hot_rank_done
    jobs.limits["hot_rank"] = (cfg.max_turns, max(cfg.timeout_seconds, RANK_SECONDS))

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
            return {"before": read_text(path), "params": with_attachments(params, f"{MODE_OF[kind]}-{params['conversation_id']}")}

        def done(job_id: int, params: dict, result: RunResult, ctx: dict) -> None:
            conv = params["conversation_id"]
            if result.outcome not in ("ok", "unparsed"):
                role, words, offer = ended_words(result)
                add_message(db, conv, role, words, job_id=job_id, meta={"offer": offer, "request": params.get("message_id")})
                return
            after = read_text(path)
            diff = unified_diff(ctx.get("before", ""), after, path.name) if after != ctx.get("before") else ""
            if result.session_id:
                db.run("UPDATE conversations SET session_id=? WHERE id=?", (result.session_id, conv))
            add_message(db, conv, "assistant", result.clean_text or result.text, job_id=job_id, diff=diff or None)

        def carry(params: dict) -> dict:
            # its saved session is gone (jobs.carry): the new one is told what was said so far
            return {**params, "history": chat_history(db, params["conversation_id"], params["message_id"])}

        jobs.session_for[kind] = session
        jobs.prepare[kind] = before
        jobs.finish[kind] = done
        jobs.carry[kind] = carry

    chat_hooks("interview", cfg.story_bank)
    chat_hooks("voice", cfg.voice_profile)

    # ---- a post's own chat ----------------------------------------------------
    def post_chat_prepare(job_id: int, params: dict, progress) -> dict:
        post, history = post_chat_context(db, params["post_id"], params["conversation_id"], params["message_id"])
        versions.catch_up(db, params["post_id"])    # the owner's edits so far are kept before Claude changes anything
        params = with_attachments(params, f"post-{params['post_id']}")
        return {"params": {**params, "post": post, "history": history}}

    def post_chat_tools(params: dict) -> tuple:
        # Only a draft's text and pictures can change: a locked post's run is offered none of those tools, so it spends no
        # ChatGPT picture and no rewrite on a post it could not change. Auditing and reading a post still work.
        draft = (params.get("post") or {}).get("status") == "draft"
        tools = ["set_post_text", "record_audit", "set_rank"] if draft else ["record_audit", "set_rank"]
        if draft and codex.chatgpt_ready():
            tools.append("make_image")
        if draft and carousel.available():
            tools.append("make_carousel")
        if read_env(cfg).get("APIFY_TOKEN"):
            tools.append("fetch_post")
        return tuple(tools)

    def post_chat_done(job_id: int, params: dict, result: RunResult, ctx: dict) -> None:
        run = ctx.get("run")
        made = {"versions": list(run.versions), "images": list(run.images)} if run else {"versions": [], "images": []}
        conv = params["conversation_id"]
        if result.outcome in ("ok", "unparsed"):
            add_message(db, conv, "assistant", (result.clean_text or result.text or "Done.").strip(), job_id=job_id,
                        meta={**made, "request": params["message_id"]})
            return
        role, words, offer = ended_words(result)
        add_message(db, conv, role, words, job_id=job_id,
                    meta={**made, "offer": offer, "request": params["message_id"]})

    jobs.prepare["post_chat"] = post_chat_prepare
    jobs.tools_for["post_chat"] = post_chat_tools
    jobs.finish["post_chat"] = post_chat_done
    jobs.limits["post_chat"] = (cfg.chat_max_turns, cfg.chat_timeout_seconds)
    jobs.images_per_request = max(0, cfg.images_per_request)
