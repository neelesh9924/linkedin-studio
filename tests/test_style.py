"""Post style (style.py): the three sliders and what each step tells the writer, the owner's default in Settings (kept
beside the database), a post's own style from its Restyle, and that every run that writes a post is given it: a post's
Ask Claude, Revise and Restyle, the Planner's drafts and Draft all, and the Repurposer. A stand-in runner, never Claude."""
import json

import pytest
from conftest import TOKEN, add_job, add_post
from fastapi.testclient import TestClient

from app import draft_all, flows, style
from app.db import dumps, loads
from app.main import create_app
from app.skills import build_request

BOLD = {"hook": 5, "tone": 2, "emojis": 2}


@pytest.fixture
def web(cfg, tmp_path, fake_runner):
    app = create_app(cfg, TOKEN, db_path=tmp_path / "style.db", runner=fake_runner)
    with TestClient(app, base_url=f"http://127.0.0.1:{cfg.port}", headers={"Origin": cfg.origin}) as client:
        client.cookies.set("studio_session", TOKEN)
        yield client, app.state.db


def params_of(db, job: int) -> dict:
    return loads(db.one("SELECT params FROM jobs WHERE id=?", (job,))["params"], {})


# ---- the sliders and their words ------------------------------------------------------------
@pytest.mark.parametrize("sent", [None, [], {"hook": 4, "tone": 4}, {"hook": 0, "tone": 4, "emojis": 1},
                                  {"hook": 6, "tone": 4, "emojis": 1}, {"hook": 4, "tone": 4, "emojis": 3},
                                  {"hook": "4", "tone": 4, "emojis": 1}, {"hook": 4.0, "tone": 4, "emojis": 1},
                                  {"hook": True, "tone": 4, "emojis": 1}])
def test_only_three_whole_numbers_each_in_its_range_make_a_style(sent):
    with pytest.raises(style.Refused):
        style.clean(sent)
    assert style.valid(sent) is None


def test_every_step_gives_the_writer_its_own_words_and_the_rule_always_follows():
    for hook in range(1, 6):
        for tone in range(1, 6):
            for emojis in range(3):
                said = style.words({"hook": hook, "tone": tone, "emojis": emojis})
                assert style.HOOK[hook] in said and style.TONE[tone] in said and style.EMOJIS[emojis] in said
                assert said.endswith(style.RULE)
    assert "never a statistic" in style.HOOK[4] and style.EMOJIS[0] == "Use no emojis."
    assert style.summary(style.DEFAULT) == "Hook catchy, tone human, one emoji"
    assert style.summary(BOLD) == "Hook bold, tone plain, two emojis"


# ---- the default, in Settings -----------------------------------------------------------------
def test_the_default_is_the_studios_until_the_owner_saves_one_beside_the_database(web):
    client, db = web
    shown = client.get("/api/style").json()
    assert shown["style"] == style.DEFAULT == shown["studio"]
    assert shown["sliders"] == {"hook": [1, 5], "tone": [1, 5], "emojis": [0, 2]} and shown["labels"]["hook"]["4"] == "Catchy"
    assert client.post("/api/style", json=BOLD).json()["style"] == BOLD
    assert json.loads((db.path.parent / "style.json").read_text(encoding="utf-8")) == BOLD
    refused = client.post("/api/style", json={"hook": 9, "tone": 4, "emojis": 1})
    assert refused.status_code == 422 and refused.json()["error"] == "Hook goes from 1 to 5."
    assert client.get("/api/style").json()["style"] == BOLD                     # a refusal changes nothing


@pytest.mark.parametrize("kept", ["{not json", dumps({"hook": 9, "tone": 1, "emojis": 0}), dumps([4, 4, 1])])
def test_a_saved_default_that_is_not_a_style_counts_as_none(web, kept):
    client, db = web
    (db.path.parent / "style.json").write_text(kept, encoding="utf-8")
    assert client.get("/api/style").json()["style"] == style.DEFAULT


# ---- a post's own style: Restyle ------------------------------------------------------------
def test_restyle_makes_its_sliders_the_posts_own_and_asks_for_the_same_post_in_them(web):
    client, db = web
    post = add_post(db, text="A plain post about deploys.")
    assert client.get(f"/api/post/{post}").json()["style"] == {"value": style.DEFAULT, "own": False}
    job = client.post(f"/api/post/{post}/revise", json={"how": "style", "style": BOLD}).json()["job"]
    params = params_of(db, job)
    assert (params["how"], params["style"]) == ("style", BOLD)
    prompt = build_request("revise", params).prompt
    assert style.RESTYLE in prompt and style.words(BOLD) in prompt and "A plain post about deploys." in prompt
    assert client.get(f"/api/post/{post}").json()["style"] == {"value": BOLD, "own": True}


def test_a_restyle_with_a_slider_out_of_its_range_is_refused_and_changes_nothing(web):
    client, db = web
    post = add_post(db)
    refused = client.post(f"/api/post/{post}/revise", json={"how": "style", "style": {"hook": 4, "tone": 9, "emojis": 1}})
    assert refused.status_code == 422 and refused.json()["error"] == "Tone goes from 1 to 5."
    assert db.one("SELECT style FROM posts WHERE id=?", (post,))["style"] is None
    assert db.one("SELECT COUNT(*) AS n FROM jobs WHERE kind='revise'")["n"] == 0


def test_a_restyle_waiting_beside_the_post_says_what_it_was_asked_for(web):
    client, db = web
    post = add_post(db, text="before")
    add_job(db, "revise", params={"post_id": post, "how": "style", "style": BOLD}, result={"text": "after", "changes": []})
    revision = client.get(f"/api/post/{post}").json()["revision"]
    assert (revision["label"], revision["promise"]) == ("Restyle", "Hook bold, tone plain, two emojis.")


# ---- every run that writes a post is told the style ---------------------------------------------
def test_every_other_revision_is_written_in_the_posts_style_its_own_or_the_default(web):
    client, db = web
    plain, own = add_post(db, text="One."), add_post(db, text="Two.", style=dumps(BOLD))
    for post, expected in ((plain, style.DEFAULT), (own, BOLD)):
        params = params_of(db, client.post(f"/api/post/{post}/revise", json={"how": "shorter"}).json()["job"])
        assert params["style"] == expected and style.words(expected) in build_request("revise", params).prompt


def test_ask_claude_on_a_post_is_told_its_style(web):
    _client, db = web
    post = add_post(db, text="Two.", style=dumps(BOLD))
    shown, history = flows.post_chat_context(db, post, 0, 10**9)
    prompt = build_request("post_chat", {"post": shown, "history": history, "text": "Make it shorter"}).prompt
    assert style.words(BOLD) in prompt and prompt.endswith("The owner's new message:\nMake it shorter")


def test_the_planners_drafts_and_the_repurposer_are_written_in_the_default_and_other_tools_are_not(web):
    client, db = web
    client.post("/api/style", json=BOLD)
    params = draft_all.draft_params(db, {"id": 1, "plan_id": 0, "data": dumps({"angle": "Ship faster"})})
    assert params["style"] == BOLD and style.words(BOLD) in build_request("draft", params).prompt
    params = params_of(db, client.post("/api/tools/repurpose", json={"text": "A thread about deploys."}).json()["job"])
    assert params["style"] == BOLD and style.words(BOLD) in build_request("repurpose", params).prompt
    params = params_of(db, client.post("/api/tools/humanize", json={"text": "Some text."}).json()["job"])
    assert "style" not in params and style.RULE not in build_request("humanize", params).prompt   # it writes no post
