"""LinkedIn Studio with stand-ins, for working on the page and for the browser checks.

    .venv\\Scripts\\python dev\\demo_server.py [--port 8791] [--folder <dir>] [--empty] [--db <studio.db>]

Nothing real is touched: no Claude run, no Publora call, no ChatGPT. Everything lives in a folder of
its own (a temporary one unless --folder names one): the database, a made-up Story Bank and voice
profile (dev/demo/), a stand-in Claude login folder. Every job "finishes" after a few seconds with
canned output; a post's chat really calls the studio's own tools (set_post_text, record_audit) over
/mcp, as Claude would. Without --empty it starts with demo posts in every state, a week plan and an
interview. --db opens a copy of a real database instead (for checking that it opens as it is).
Type FAIL-ME or UNPARSED-ME into a tool to see the two failure cards.

It prints one JSON line with the sign-in link, then serves until stopped.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402

from app import api_pages, paths, versions  # noqa: E402
from app.claude_runner import RunResult  # noqa: E402
from app.config import Config  # noqa: E402
from app.db import DB, dumps, utcnow  # noqa: E402
from app.main import create_app  # noqa: E402
from app.publishing import Publisher  # noqa: E402

STEP_SECONDS = 0.8
DEMO = ROOT / "dev" / "demo"
# Who the stand-in login folder is "signed in to": made up, as everything here is.
DEMO_ACCOUNT = {"ok": True, "signed_in": True, "account": "you@example.com", "plan": "max", "error": ""}

POST = """On 14 March I stopped coding my side project after 10 pm on weekdays.

In the [N] weeks after, commits fell from 31 a week to 14. Signups from my launch list slowed too, and I saw it on the dashboard every morning.

For eight months before that, late nights were my whole system. Day job until 7, dinner, then two or three hours with the laptop. I shipped the tax-export feature that way. I also pushed a bug to production at 1 am that took [N] hours to find the next afternoon.

What I got back was seven hours of sleep instead of five, and one rollback in the next quarter against six before. I also started picking the one thing worth building on Saturday morning.

Less time on the project, better decisions inside it.

What did you stop doing that made your work better?"""

CANNED = {
    "humanize": {"rewritten": "Our team changed how we handle deployments. Releases are easier to ship now, and people work "
                              "together on them more than they used to.",
                 "changes": ["Cut the stock opener.", "Replaced \"embarked on a transformative journey\" with what happened."],
                 "reader_read": "reads human", "missing": ["The name of the tool you adopted.", "A before/after number with a date."]},
    "audit": {"verdict": "FAIL", "summary": "Two unfilled blanks and a reveal bridge; the structure is otherwise clean.",
              "blockers": [{"issue": "Draft contains unfilled blanks ([N]).", "fix": "Replace each with your real figure, or cut the sentence."}],
              "warnings": [{"issue": "Paragraph 4 uses a setup-then-reveal bridge.", "fix": "State the result directly."}], "chars": 1017},
    "hook": {"formula": "F7 Odd-Precision Money Ledger", "confidence": "high", "runner_up": "F3 Year-over-Year Pivot",
             "hook": "I spent $4,730 on Vercel last March. Here is every line.", "structure": ["Hook: one odd-precision number"],
             "why": "The exact figure signals a real invoice.", "template": "I spent {amount} on {thing} in {month}.",
             "cautions": ["Do not copy its second paragraph's opener."]},
    "comment": {"variants": [{"text": "The caching argument misses one piece: half the teams I see cache at the edge and still pay for cold starts.",
                              "reaction": "INTEREST", "template": "T1 Missing-Piece", "why": "Adds the one thing the post leaves out."}]},
    "repurpose": {"post": POST.replace("[N] weeks", "six weeks").replace("[N] hours", "four hours"), "formula": "F4 Time-Anchor Confession",
                  "mapping": ["Tweet 1 became the hook"], "first_comment": "Full thread: https://example.com/thread", "chars": 1011},
    "profile": {"scorecard": [{"section": "Headline", "verdict": "needs work", "note": "Uses 42 of 220 characters."}],
                "priority_fixes": ["Rewrite the headline to say who you help."],
                "rewrites": [{"section": "Headline", "before": "Software engineer.", "after": "Backend engineer | payment systems that do not double-charge"}]},
    "plan": {"items": [
        {"day": "Tue", "time": "8:00 AM", "pillar": "Authority", "format": "Text", "formula": "F7 Odd-Precision Money Ledger",
         "angle": "What your side project costs to run each month, line by line.", "cta": "Question close", "goal": "saves", "bank_section": "Receipts"},
        {"day": "Thu", "time": "8:00 AM", "pillar": "Narrative", "format": "Text", "formula": "F4 Time-Anchor Confession",
         "angle": "A dated thing you stopped doing on your side project, and what it gave back.", "cta": "Mirror question", "goal": "comments"},
        {"day": "Fri", "time": "9:00 AM", "pillar": "Narrative", "format": "Text", "formula": "F11 Emotional Cold-Open",
         "angle": "The night the first deploy failed, told from inside the scene.", "cta": "Soft close", "goal": "likes"}],
        "comment_targets": [{"day": "Tue", "who": "Peer founders at 5-20k followers", "pattern": "Data-first: add one number"}],
        "readiness": [{"check": "At least one receipt or data post", "ok": True}, {"check": "A soft offer", "ok": False, "note": "none planned"}],
        "notes": ["Monday is a commenting day."]},
    "draft": {"formula": "F4 Time-Anchor Confession", "text": POST, "first_comment": None, "posting_window": "Tue-Thu 7:30-9:00 AM",
              "notes": ["Two figures are left as [N] because they are not in your Story Bank."]},
    "revise": {"text": POST.replace("On 14 March I stopped coding my side project after 10 pm on weekdays.",
                                    "14 March: the last night I opened my side project after 10 pm."),
               "first_comment": None, "changes": ["New first line leads with the date."]},
}
INTERVIEW = ["What have you been working on lately that you **can't stop thinking about**?",
             "You said deploys got faster: by how much, measured how, and over what period?",
             "Got it: 22 minutes down to 9, team of four, Q2 2025. I've written that to **Receipts**.\n\nWhat did you believe a year ago that you no longer believe?"]


def call_tool(mcp: dict, name: str, arguments: dict) -> str:
    """One call of the studio's own tools, over /mcp with this run's token, as Claude makes it."""
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}).encode()
    request = urllib.request.Request(mcp["url"], data=body, method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {mcp['token']}"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=30) as answer:
        result = json.loads(answer.read())["result"]
    return result["content"][0]["text"]


def post_in(prompt: str) -> str:
    found = re.search(r"<<<UNTRUSTED POST:[^\n]*\n(.*?)\n<<<END UNTRUSTED POST>>>", prompt, flags=re.S)
    text = found.group(1) if found else ""
    return "" if text.startswith("(empty") else text


class ScriptedRunner:
    """Stands in for ClaudeRunner: the same call, canned results after a few steps."""

    def __init__(self, story_bank: Path):
        self.story_bank = story_bank
        self.turns = 0

    def _steps(self, say, cancel, steps) -> bool:
        for step in steps:
            say(step)
            end = time.monotonic() + STEP_SECONDS
            while time.monotonic() < end:
                if cancel is not None and cancel.is_set():
                    return False
                time.sleep(0.05)
        return True

    def run(self, req, cancel=None, on_progress=None, timeout=None):
        say = on_progress or (lambda _text: None)
        usage = {"input_tokens": 12, "output_tokens": 1400, "cache_read_input_tokens": 52000}
        if req.kind == "post_chat":
            return self._chat(req, say, cancel, usage)
        chat = req.kind in ("interview", "voice")
        if not self._steps(say, cancel, ["Getting ready", "Loading the skill", "Loaded the skill, now writing",
                                         "Reading story-bank.md", "Read story-bank.md, now writing"]):
            return RunResult(outcome="cancelled", error="Cancelled.")
        if "FAIL-ME" in req.prompt:
            return RunResult(outcome="error", error="Claude reported an error (demo).", exit_code=1)
        if "UNPARSED-ME" in req.prompt:
            return RunResult(outcome="unparsed", text="Here is my answer but I forgot the block.", parse_error="The reply has no result block.")
        if chat:
            if not req.resume_session:
                self.turns = 0
            text = INTERVIEW[min(self.turns, len(INTERVIEW) - 1)]
            self.turns += 1
            if self.turns == 3 and req.kind == "interview":
                body = self.story_bank.read_text(encoding="utf-8").replace("- filled: no", "- filled: yes")
                body = body.replace("- (number, what it measures, when, who or what it belongs to)",
                                    "- Deploy time cut from 22 minutes to 9, team of four, Q2 2025")
                self.story_bank.write_text(body, encoding="utf-8")
            return RunResult(outcome="ok", text=text, clean_text=text, session_id="demo-session", num_turns=3, usage=usage, skill_invoked=True)
        data = CANNED[req.kind]
        if req.kind == "audit" and "[" not in req.prompt.split("Draft:")[-1]:
            data = {"verdict": "PASS", "summary": "No blockers. The hook lands in 142 characters.", "blockers": [],
                    "warnings": [{"issue": "No named entity beyond your own project.", "fix": "Name the tool."}], "chars": 1011}
        return RunResult(outcome="ok", text="done", data=data, num_turns=5, usage=usage, skill_invoked=True, cost_usd=0.2)

    def _chat(self, req, say, cancel, usage):
        """A post's chat: reads what was asked, and changes the post through the studio's tools."""
        asked = req.prompt.rsplit("The owner's new message:\n", 1)[-1].strip()
        text = post_in(req.prompt)
        if not self._steps(say, cancel, ["Getting ready", "Loading the skill", "Loaded the skill, now writing"]):
            return RunResult(outcome="cancelled", error="Stopped.")
        lower = asked.lower()
        if any(w in lower for w in ("picture", "illustration", "image")):
            if "mcp__studio__set_post_text" not in req.policy.allow:
                reply = "This post is locked, so it cannot take a new picture. New draft from this makes an editable copy."
            elif "mcp__studio__make_image" not in req.policy.allow:
                reply = "ChatGPT's pictures are not set up in this studio yet (Settings › ChatGPT), so I made none."
            else:
                say("Asking ChatGPT for a picture")
                said = call_tool(req.mcp, "make_image", {"prompt": "A calm desk at night, a closed laptop and a cup of tea, in soft flat shapes", "shape": "landscape"})
                reply = f"I asked ChatGPT for an illustration: a calm desk at night, a closed laptop and a tea. {said.split('.')[0]}."
            return RunResult(outcome="ok", text=reply, clean_text=reply, num_turns=4, usage=usage, skill_invoked=True)
        if "audit" in lower:
            say("Saving the audit")
            call_tool(req.mcp, "record_audit", {"verdict": "FAIL" if "[" in text else "PASS",
                                                "summary": "Blanks left to fill; the hook is strong." if "[" in text else "Ready to post.",
                                                "blockers": [{"issue": "Unfilled blanks ([N]).", "fix": "Put in your real figures."}] if "[" in text else []})
            reply = "Audited: the findings are beside the post."
            return RunResult(outcome="ok", text=reply, clean_text=reply, num_turns=4, usage=usage, skill_invoked=True)
        if "mcp__studio__set_post_text" not in req.policy.allow:     # a post that is not a draft: its text is locked
            reply = ("This post's text is locked, so I changed nothing. I can audit it, or say what would make the next "
                     "one stronger.")
            return RunResult(outcome="ok", text=reply, clean_text=reply, num_turns=2, usage=usage, skill_invoked=True)
        if not text or (("write" in lower or "draft" in lower) and "hook" not in lower):
            new, note = POST, "First draft"
        elif "short" in lower:
            parts = text.split("\n\n")
            new, note = "\n\n".join(parts[:2] + parts[-2:]) if len(parts) > 4 else text[: max(200, len(text) // 2)], "Shorter"
        else:
            lines = text.split("\n")
            new, note = "\n".join(["14 March: the last night I opened my side project after 10 pm."] + lines[1:]), "New hook"
        say("Rewriting the post")
        said = call_tool(req.mcp, "set_post_text", {"text": new, "note": note})
        reply = f"{note}: done. {said}"
        if not self._steps(say, cancel, ["Rewrote the post, now writing"]):
            return RunResult(outcome="cancelled", error="Stopped.")
        return RunResult(outcome="ok", text=reply, clean_text=reply, num_turns=5, usage=usage, skill_invoked=True)


class ScriptedPublora:
    """Publora as the studio's client sees it, kept in memory: a post, and a picture going up with it."""

    def __init__(self):
        self.media = {}

    def resolve_linkedin_platform_id(self):
        return "linkedin-demo"

    def create_post_once(self, payload, key):
        time.sleep(0.4)
        return {"success": True, "postGroupId": "demo" + key[-6:], "scheduledTime": payload.get("scheduledTime"), "warnings": []}

    def get_upload_url_once(self, post_group_id, file_name, content_type):
        media_id = f"m{len(self.media) + 1}"
        self.media[media_id] = post_group_id
        return {"success": True, "uploadUrl": f"https://upload.demo/{media_id}", "fileUrl": f"https://files.demo/{media_id}",
                "mediaId": media_id}

    def put_upload(self, upload_url, data, content_type):
        time.sleep(0.3)

    def update_post_once(self, post_group_id, body):
        return {"success": True, "scheduledTime": body.get("scheduledTime"), "postGroup": {"_id": post_group_id, "status": body.get("status")}}

    def delete_media(self, media_id):
        self.media.pop(media_id, None)
        return {"success": True}

    def delete_post(self, post_group_id):
        return {"success": True}

    def get_post(self, post_group_id):
        return {"status": "scheduled", "posts": [], "media": [{"mediaId": m, "status": "ready"} for m, g in self.media.items() if g == post_group_id]}


def seed(db: DB) -> None:
    """Demo posts in every state, a week plan and an interview: the page as it is after a few weeks of use."""
    now = datetime.now(timezone.utc)
    stamp = utcnow()

    def add(status, text, title, **extra):
        cols = {"created_at": stamp, "updated_at": stamp, "title": title, "text": text, "status": status, **extra}
        post_id = db.run(f"INSERT INTO posts ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", tuple(cols.values()))
        versions.record(db, post_id, text, extra.get("first_comment"), "claude", "First draft")
        return post_id

    plan = db.run("INSERT INTO plans (created_at, inputs, result) VALUES (?,?,?)",
                  (stamp, dumps({"audience": "engineers who build side projects", "goal": "conversations about building alongside a day job",
                                 "max_posts": 3}), dumps(CANNED["plan"])))
    items = [db.run("INSERT INTO plan_items (plan_id, position, data) VALUES (?,?,?)", (plan, i, dumps(item)))
             for i, item in enumerate(CANNED["plan"]["items"])]
    when = (now + timedelta(days=3)).replace(hour=2, minute=30, second=0, microsecond=0)
    add("published", "Three years ago I wrote my first line of Rust.\n\nToday it runs the billing for 40,000 people.", "Three years of Rust",
        scheduled_at=(now - timedelta(days=4)).isoformat(timespec="seconds"), publora_post_id="demo-published")
    add("scheduled", "Our deploys used to take 22 minutes. Now they take 9.\n\nHere is what we cut, in order.", "Deploy time",
        scheduled_at=when.isoformat(timespec="seconds"), publora_post_id="demo-scheduled")
    add("approved", "The best code review I ever got was one sentence long.\n\n\"Delete this file.\"", "One-sentence review")
    draft = add("draft", POST, "A dated thing you stopped doing", plan_item_id=items[1], formula="F4 Time-Anchor Confession",
                notes=dumps(CANNED["draft"]["notes"]))
    db.run("UPDATE plan_items SET post_id=? WHERE id=?", (draft, items[1]))
    conv = db.run("INSERT INTO conversations (mode, session_id, created_at) VALUES ('bank', 'demo-session', ?)", (stamp,))
    db.run("INSERT INTO messages (conversation_id, role, text, created_at) VALUES (?,?,?,?)", (conv, "user", "Let's start.", stamp))
    db.run("INSERT INTO messages (conversation_id, role, text, created_at) VALUES (?,?,?,?)", (conv, "assistant", INTERVIEW[0], stamp))


def main() -> None:
    args = sys.argv[1:]
    port = int(args[args.index("--port") + 1]) if "--port" in args else 8791
    folder = Path(args[args.index("--folder") + 1]) if "--folder" in args else Path(tempfile.mkdtemp(prefix="linkedin-studio-demo-"))
    skills = folder / "skills"
    (skills / "references").mkdir(parents=True, exist_ok=True)
    (skills / "skills").mkdir(exist_ok=True)
    link = skills / ".claude" / "skills" / "linkedin-humanizer"
    link.mkdir(parents=True, exist_ok=True)
    (link / "SKILL.md").write_text("demo", encoding="utf-8")
    for template, name in (("bank-template.md", "story-bank.md"), ("voice-template.md", "voice-profile.md")):
        if not (skills / "references" / name).is_file():
            shutil.copy(DEMO / template, skills / "references" / name)
    (skills / ".env").write_text("PUBLORA_API_KEY=sk_demo\nLINKEDIN_PLATFORM_ID=linkedin-demo\n", encoding="utf-8")
    login = folder / "claude-login"
    login.mkdir(exist_ok=True)
    db_path = Path(args[args.index("--db") + 1]) if "--db" in args else folder / "studio.db"
    fresh = not db_path.is_file()
    cfg = Config(skills_dir=skills, claude_bin=Path(sys.executable), claude_config_dir=login, port=port)
    # The stand-in "claude program" is this Python: Settings shows it as Claude Code, as on a PC that has it.
    api_pages.claude_version = paths.claude_version = lambda _cfg: "2.1.292 (Claude Code), the demo's stand-in"
    api_pages.claude_account = paths.claude_account = lambda _cfg, _prefix=None: DEMO_ACCOUNT
    db = DB(db_path)
    if fresh and "--empty" not in args and "--db" not in args:
        seed(db)
    app = create_app(cfg, "demo", db_path=db_path, runner=ScriptedRunner(cfg.story_bank),
                     publisher=Publisher(db, cfg, client_factory=lambda publora=ScriptedPublora(): publora))
    print(json.dumps({"url": f"http://127.0.0.1:{port}/auth?token=demo", "folder": str(folder), "started": db.started}), flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_config=None, access_log=False)


if __name__ == "__main__":
    main()
