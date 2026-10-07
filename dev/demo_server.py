"""LinkedIn Studio with scripted jobs, for working on the UI.

    .venv\\Scripts\\python dev\\demo_server.py [--port 8791] [--empty]

Nothing real is touched: no Claude run, no Publora call, and the Story Bank and database are
copies under data\\demo\\ (pass --empty to start with no data at all). Every job "finishes" after
a few seconds with canned output, so each screen and each in-between state can be looked at.
Type FAIL-ME or UNPARSED-ME into a tool to see the two failure cards.

Open the printed link (it carries the demo sign-in token).
"""
from __future__ import annotations

import dataclasses
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402

from app.claude_runner import RunResult  # noqa: E402
from app.config import DATA_DIR, load_config  # noqa: E402
from app.db import DB  # noqa: E402
from app.main import create_app  # noqa: E402
from app.publishing import Publisher  # noqa: E402

STEP_SECONDS = 1.1

POST = """On 14 March I stopped coding my side project after 10 pm on weekdays.

In the [N] weeks after, commits fell from 31 a week to 14. Signups from my launch list slowed too, and I saw it on the dashboard every morning.

For eight months before that, late nights were my whole system. Day job until 7, dinner, then two or three hours with the laptop. I shipped the tax-export feature that way. I also pushed a bug to production at 1 am that took [N] hours to find the next afternoon.

What I got back was seven hours of sleep instead of five, and one rollback in the next quarter against six before. I also started picking the one thing worth building on Saturday morning.

Less time on the project, better decisions inside it.

What did you stop doing that made your work better?"""

CANNED = {
    "humanize": {
        "rewritten": "Our team changed how we handle deployments. Releases are easier to ship now, and people work "
                     "together on them more than they used to.",
        "changes": ["Cut the stock opener \"In today's fast-paced digital landscape\".",
                    "Replaced \"embarked on a transformative journey\" with what actually happened.",
                    "Removed the \"and the result?\" reveal bridge."],
        "reader_read": "reads human",
        "missing": ["The name of the tool you adopted.", "A before/after number with a date."]},
    "audit": {
        "verdict": "FAIL", "summary": "Two unfilled blanks and a reveal bridge; the structure is otherwise clean.",
        "blockers": [{"issue": "Draft contains unfilled blanks ([N]).",
                      "fix": "Replace each with your real figure, or cut the sentence."}],
        "warnings": [{"issue": "Paragraph 4 uses a setup-then-reveal bridge.", "fix": "State the result directly."},
                     {"issue": "Closing line restates the paragraph as a slogan.",
                      "fix": "Cut it, or replace it with one concrete result."}],
        "chars": 1017},
    "hook": {
        "formula": "F7 Odd-Precision Money Ledger", "confidence": "high", "runner_up": "F3 Year-over-Year Pivot",
        "hook": "I spent $4,730 on Vercel last March. Here is every line.",
        "structure": ["Hook: one odd-precision number with a referent", "Ledger: five dated line items",
                      "Turn: the line that surprised me", "Close: a question about the reader's own bill"],
        "why": "The exact figure signals a real invoice, and the ledger keeps the promise the hook made.",
        "template": "I spent {amount} on {thing} in {month}.\n\n{line item 1}\n{line item 2}\n{line item 3}\n\n"
                    "The one that surprised me: {surprise}.\n\n{question about the reader's own numbers}",
        "cautions": ["The original opens its second paragraph with \"Here's what\": do not copy that."]},
    "comment": {"variants": [
        {"text": "Priya the caching argument misses one piece.. half the teams I see now cache at the edge and still "
                 "pay for cold starts. the bill moved, it did not shrink.",
         "reaction": "INTEREST", "template": "T1 Missing-Piece", "why": "Adds the one thing the post leaves out."},
        {"text": "To your closing question: yes, we saw it in March. Moving two endpoints off serverless cut the "
                 "invoice by 38% and nobody noticed a latency change.",
         "reaction": "PRAISE", "template": "T2 Answer-the-Closing-Question", "why": "The author asked a direct question."}]},
    "repurpose": {
        "post": POST.replace("[N] weeks", "six weeks").replace("[N] hours", "four hours"),
        "formula": "F4 Time-Anchor Confession",
        "mapping": ["Tweet 1 became the hook", "Tweets 2-4 became the ledger paragraph",
                    "The link moved to the first comment"],
        "first_comment": "Full thread: https://example.com/thread", "chars": 1011},
    "profile": {
        "scorecard": [{"section": "Headline", "verdict": "needs work", "note": "Uses 42 of 220 characters."},
                      {"section": "About", "verdict": "fail", "note": "Third person, no hook in the first 265 characters."},
                      {"section": "Experience", "verdict": "pass", "note": "Bullets carry metrics."},
                      {"section": "Photo", "verdict": "not shown", "note": "Paste a description to score it."}],
        "priority_fixes": ["Rewrite the headline to say who you help and with what.",
                           "Open About with one concrete result."],
        "rewrites": [{"section": "Headline", "before": "Software engineer.",
                      "after": "Backend engineer | I help fintech teams ship payment systems that do not double-charge"},
                     {"section": "About", "before": "I build things.",
                      "after": "I build the parts of payment systems nobody sees until they break.\n\n"
                               "In 2025 I cut failed settlements at my company from 2.1% to 0.3%."}]},
    "plan": {
        "items": [
            {"day": "Tue", "time": "8:00 AM", "pillar": "Authority", "format": "Text", "formula": "F7 Odd-Precision Money Ledger",
             "angle": "What your side project costs to run each month, line by line and nothing rounded.",
             "cta": "Question close", "goal": "saves", "bank_section": "Receipts"},
            {"day": "Wed", "time": "9:30 AM", "pillar": "Community", "format": "Text", "formula": "F14 Named Gratitude",
             "angle": "Thank the real people who made building alongside a day job possible, one specific act each.",
             "cta": "Tag and thanks", "goal": "reposts", "bank_section": None},
            {"day": "Thu", "time": "8:00 AM", "pillar": "Narrative", "format": "Text", "formula": "F4 Time-Anchor Confession",
             "angle": "A dated, specific thing you stopped doing on your side project, and what it cost and gave back.",
             "cta": "Mirror question", "goal": "comments", "bank_section": "Turning points"},
            {"day": "Fri", "time": "9:00 AM", "pillar": "Narrative", "format": "Text", "formula": "F11 Emotional Cold-Open",
             "angle": "The night the first deploy failed, told from inside the scene.",
             "cta": "Soft close", "goal": "likes", "bank_section": "Scars"}],
        "comment_targets": [
            {"day": "Tue", "who": "Peer founders at 5-20k followers", "pattern": "Data-first: add one number they did not have"},
            {"day": "Wed", "who": "Engineering leaders you have worked with", "pattern": "Answer their closing question"},
            {"day": "Thu", "who": "Indie builders shipping in public", "pattern": "First commenter within 10 minutes"}],
        "readiness": [{"check": "At least one vulnerability post", "ok": True},
                      {"check": "At least one receipt or data post", "ok": True},
                      {"check": "A soft offer or CTA-driving post", "ok": False, "note": "none planned"},
                      {"check": "No formula used twice", "ok": True}],
        "notes": ["Monday is a commenting day.", "Fill the two [N] figures before the Thursday post."]},
    "draft": {"formula": "F4 Time-Anchor Confession", "text": POST, "first_comment": None,
              "posting_window": "Tue-Thu 7:30-9:00 AM",
              "notes": ["Two figures are left as [N] because they are not in your Story Bank.",
                        "No external link, so there is no first comment."]},
    "revise": {
        "text": POST.replace("On 14 March I stopped coding my side project after 10 pm on weekdays.",
                             "14 March: the last night I opened my side project after 10 pm.")
                    .replace("Less time on the project, better decisions inside it.\n\n", ""),
        "first_comment": None, "changes": ["New first line leads with the date.", "Cut the slogan line near the end."]},
}
CHAT = [
    "The Story Bank is empty (`filled: no`), so every section is thin and I'll start wide.\n\n"
    "What have you been working on lately that you **can't stop thinking about**?",
    "That's a real one. You said deploys got faster: by how much, measured how, and over what period?",
    "Got it: 22 minutes down to 9, team of four, Q2 2025. I've written that to **Receipts**.\n\n"
    "What did you believe a year ago that you no longer believe?",
]


class ScriptedRunner:
    """Stands in for ClaudeRunner: same call, canned result after a few progress steps."""

    def __init__(self, story_bank: Path):
        self.story_bank = story_bank
        self.chat_turns = 0

    def run(self, req, cancel=None, on_progress=None, timeout=None):
        say = on_progress or (lambda _text: None)
        chat = req.kind in ("interview", "voice")
        steps = ["Getting ready", "Loading the skill", "Loaded the skill, now writing", "Reading story-bank.md",
                 "Read story-bank.md, now writing"]
        if not chat:
            steps += ["Reading hook-formulas.md", "Read hook-formulas.md, now writing"]
        started = time.monotonic()
        for step in steps:
            say(step)
            end = time.monotonic() + STEP_SECONDS
            while time.monotonic() < end:
                if cancel is not None and cancel.is_set():
                    return RunResult(outcome="cancelled", error="Cancelled.")
                time.sleep(0.05)
        ms = int((time.monotonic() - started) * 1000)
        usage = {"input_tokens": 12, "output_tokens": 1400, "cache_read_input_tokens": 52000}
        if "FAIL-ME" in req.prompt:
            return RunResult(outcome="error", error="Claude reported an error (demo).", duration_ms=ms, exit_code=1)
        if "UNPARSED-ME" in req.prompt:
            return RunResult(outcome="unparsed", text="Here is my answer but I forgot the block.",
                             parse_error="The reply has no result block.", duration_ms=ms)
        if chat:
            if not req.resume_session:
                self.chat_turns = 0  # a new conversation starts the script again
            text = CHAT[min(self.chat_turns, len(CHAT) - 1)]
            self.chat_turns += 1
            if self.chat_turns == 3:
                body = self.story_bank.read_text(encoding="utf-8").replace("- filled: no", "- filled: yes")
                fact = "- Deploy time cut from 22 minutes to 9, team of four, Q2 2025"
                hint = "- (number, what it measures, when, who or what it belongs to)"
                body = body.replace(hint, fact) if hint in body else body.replace(fact, fact + "\n" + fact + " (again)", 1)
                self.story_bank.write_text(body, encoding="utf-8")
            return RunResult(outcome="ok", text=text, clean_text=text, session_id="demo-session", duration_ms=ms,
                             num_turns=3, usage=usage, skill_invoked=True)
        data = CANNED[req.kind]
        if req.kind == "audit" and "[" not in req.prompt.split("Draft:")[-1]:
            data = {"verdict": "PASS", "summary": "No blockers. The hook lands in 142 characters and the length is in range.",
                    "blockers": [], "warnings": [{"issue": "No named entity beyond your own project.",
                                                  "fix": "Name the tool or the company type."}], "chars": 1011}
        return RunResult(outcome="ok", text="done", data=data, session_id="demo", duration_ms=ms, num_turns=5,
                         usage=usage, skill_invoked=True, cost_usd=0.2)


class ScriptedPublora:
    def resolve_linkedin_platform_id(self):
        return "linkedin-demo"

    def create_post_once(self, payload, key):
        time.sleep(0.6)
        return {"success": True, "postGroupId": "demo" + key[-6:], "scheduledTime": payload["scheduledTime"], "warnings": []}

    def delete_post(self, post_group_id):
        return {"success": True}

    def get_post(self, post_group_id):
        return {"status": "scheduled", "posts": []}


def main() -> None:
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8791
    real = load_config()
    home = DATA_DIR / "demo"
    shutil.rmtree(home, ignore_errors=True)
    skills = home / "skills"
    (skills / "references").mkdir(parents=True)
    (skills / "skills").mkdir()
    link = skills / ".claude" / "skills" / "linkedin-humanizer"
    link.mkdir(parents=True)
    (link / "SKILL.md").write_text("demo", encoding="utf-8")
    for name in ("story-bank.md", "voice-profile.md"):
        shutil.copy(real.skills_dir / "references" / name, skills / "references" / name)
    (skills / ".env").write_text("PUBLORA_API_KEY=sk_demo\nLINKEDIN_PLATFORM_ID=linkedin-demo\n", encoding="utf-8")
    db_path = home / "studio.db"
    if "--empty" not in sys.argv and (DATA_DIR / "studio.db").is_file():
        shutil.copy(DATA_DIR / "studio.db", db_path)

    cfg = dataclasses.replace(real, skills_dir=skills, port=port)
    db = DB(db_path)
    app = create_app(cfg, "demo", db_path=db_path, runner=ScriptedRunner(cfg.story_bank),
                     publisher=Publisher(db, cfg, client_factory=ScriptedPublora))
    print(f"Demo (no Claude, no Publora): http://127.0.0.1:{port}/auth?token=demo", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_config=None, access_log=False)


if __name__ == "__main__":
    main()
