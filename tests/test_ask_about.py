"""Ask me about this, on a saved Story Bank entry: the filled entries the studio lists (render.doc_sections), the new
Interviewer conversation one click starts, its first prompt, and the entries it refuses. The tests' own made-up Story
Bank in a temporary skills folder; a stand-in runner, never real Claude."""
import pytest
from conftest import TOKEN
from fastapi.testclient import TestClient

from app.claude_runner import RunResult
from app.jobs import wait_for
from app.main import create_app
from app.skills import ACTIONS

BANK = """# Story Bank

## Status

- filled: yes
- sessions: 1

## 1. Timeline

- (role, company, years, one line on what you did)
- Lead engineer at a made-up payments startup, 2021-2024

## 2. Receipts

- **Deploy time:** cut from 22 minutes to 9, team of four, Q2 2025
- Emoji: (none / one)
- (number, what it measures, when, who or what it belongs to)
"""
DEPLOY = "**Deploy time:** cut from 22 minutes to 9, team of four, Q2 2025"


class StandIn:
    def __init__(self):
        self.requests = []

    def run(self, req, cancel=None, on_progress=None, timeout=None):
        self.requests.append(req)
        return RunResult(outcome="ok", text="What did the 9 minutes change?", clean_text="What did the 9 minutes change?",
                         session_id=f"s-{len(self.requests)}")


@pytest.fixture
def studio(cfg, tmp_path):
    cfg.story_bank.write_text(BANK, encoding="utf-8")
    runner = StandIn()
    app = create_app(cfg, TOKEN, db_path=tmp_path / "ask.db", runner=runner)
    with TestClient(app, base_url=f"http://127.0.0.1:{cfg.port}", headers={"Origin": cfg.origin}) as client:
        client.cookies.set("studio_session", TOKEN)
        yield client, app, runner


def test_the_bank_lists_each_sections_filled_entries_by_the_rule_its_counts_use(studio):
    client, _app, _runner = studio
    sections = client.get("/api/bank").json()["files"]["bank"]["sections"]
    assert [(s["title"], s["entries"]) for s in sections] == [("1. Timeline", ["Lead engineer at a made-up payments startup, 2021-2024"]),
                                                              ("2. Receipts", [DEPLOY])]
    assert all(s["filled"] == len(s["entries"]) for s in sections)


def test_ask_me_about_this_starts_a_new_interview_about_that_one_entry(studio):
    client, app, runner = studio
    db = app.state.db
    earlier = client.post("/api/chat/bank/send", json={"text": "Let's start."}).json()
    wait_for(db, earlier["job"], 10)
    sent = client.post("/api/chat/bank/send", json={"focus": {"section": "2. Receipts", "entry": DEPLOY},
                                                    "conversation": earlier["conversation"], "text": "ignored"})
    assert sent.status_code == 200, sent.text
    sent = sent.json()
    assert sent["conversation"] != earlier["conversation"]            # a new conversation, never the one it was on
    wait_for(db, sent["job"], 10)
    req = runner.requests[-1]
    assert "linkedin-interviewer skill in --mode bank" in req.prompt
    assert f'Entry: "{DEPLOY}"' in req.prompt and "Section: 2. Receipts" in req.prompt and "one question at a time" in req.prompt
    assert req.resume_session is None and req.policy == ACTIONS["interview"].policy   # its tools stay the interviewer's own
    chat = client.get(f"/api/chat/bank?c={sent['conversation']}").json()
    assert chat["messages"][0]["text"] == 'Ask me about this: "Deploy time: cut from 22 minutes to 9, team of four, Q2 2025" (Receipts)'
    assert [h["id"] for h in chat["history"]] == [sent["conversation"], earlier["conversation"]]   # the earlier one is kept
    answer = client.post("/api/chat/bank/send", json={"text": "It cut our rollbacks too", "conversation": sent["conversation"]})
    wait_for(db, answer.json()["job"], 10)
    assert runner.requests[-1].resume_session == "s-2" and runner.requests[-1].prompt == "It cut our rollbacks too"   # after the first run, the answer goes as it is


@pytest.mark.parametrize("focus", [
    {"section": "2. Receipts", "entry": "Deploy time: cut from 22 minutes to 3"},         # not what the file says
    {"section": "2. Receipts", "entry": "(number, what it measures, when, who or what it belongs to)"},   # a template hint
    {"section": "2. Receipts", "entry": "Emoji: (none / one)"},
    {"section": "1. Timeline", "entry": DEPLOY},                                           # another section's entry
    {"section": "Status", "entry": "filled: yes"},
    {"section": "2. Receipts", "entry": DEPLOY + "x" * 5000},
    {"section": "2. Receipts"},
    "Deploy time",
])
def test_an_entry_that_is_not_in_the_file_is_refused(studio, focus):
    client, app, runner = studio
    r = client.post("/api/chat/bank/send", json={"focus": focus})
    assert r.status_code == 422 and "not in your Story Bank" in r.json()["error"]
    assert app.state.db.one("SELECT COUNT(*) AS n FROM conversations")["n"] == 0 and not runner.requests


def test_ask_me_about_this_is_for_the_story_bank_only_and_quotes_a_long_entry_capped(studio, cfg):
    client, app, runner = studio
    r = client.post("/api/chat/voice/send", json={"focus": {"section": "2. Receipts", "entry": DEPLOY}})
    assert r.status_code == 422 and "Story Bank only" in r.json()["error"]
    long_entry = "A very long receipt " + "with many words " * 60
    cfg.story_bank.write_text(BANK.replace("- Emoji: (none / one)", f"- {long_entry.strip()}"), encoding="utf-8")
    sent = client.post("/api/chat/bank/send", json={"focus": {"section": "2. Receipts", "entry": long_entry.strip()}}).json()
    wait_for(app.state.db, sent["job"], 10)
    first = client.get(f"/api/chat/bank?c={sent['conversation']}").json()["messages"][0]["text"]
    assert first.endswith('…" (Receipts)') and len(first) < 360 and len(runner.requests[-1].prompt) < 1600
