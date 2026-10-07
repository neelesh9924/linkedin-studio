"""The setup screen: finding the usual places, checking a choice, saving it, and being sent there."""
import dataclasses
import shutil
import threading
from pathlib import Path

import pytest
from conftest import make_skills
from fastapi.testclient import TestClient

from app import paths
from app.config import ConfigError, load_config, path_problems
from app.main import create_app

TOKEN = "t0ken-for-tests"
KEYS = [f.key for f in paths.FIELDS]


@pytest.fixture
def pc(tmp_path, monkeypatch):
    """A pretend user folder with everything in its usual place, and nothing else on the PATH."""
    home = tmp_path / "home"
    program = home / ".local" / "bin" / "claude.exe"
    program.parent.mkdir(parents=True)
    program.write_bytes(b"not a real program")
    (home / ".claude").mkdir()
    (home / ".claude-other").mkdir()
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    return {"home": home, "skills_dir": make_skills(home / "linkedin-skills"), "claude_bin": program,
            "claude_config_dir": home / ".claude"}


def chosen_from(pc) -> dict:
    return {key: str(pc[key]) for key in KEYS}


@pytest.fixture
def config_files(tmp_path, monkeypatch):
    """Point the app at a throwaway config.local.toml and a copy of the real example."""
    local, example = tmp_path / "config.local.toml", tmp_path / "config.example.toml"
    shutil.copy(paths.EXAMPLE, example)
    monkeypatch.setattr(paths, "LOCAL", local)
    monkeypatch.setattr(paths, "EXAMPLE", example)
    return local, example


@pytest.fixture
def looks_in_pc(pc, tmp_path, monkeypatch):
    """Make the screen look in the pretend user folder, not in the real one of whoever runs the tests."""
    real = paths.usual_places
    monkeypatch.setattr(paths, "usual_places", lambda: real(home=pc["home"], root=tmp_path / "apps" / "linkedin-studio"))
    return pc


def client_for(cfg, tmp_path, fake_runner, **kw):
    app = create_app(cfg, TOKEN, db_path=tmp_path / "paths.db", runner=fake_runner, **kw)
    client = TestClient(app, base_url=f"http://127.0.0.1:{cfg.port}", headers={"Origin": cfg.origin},
                        follow_redirects=False)
    client.cookies.set("studio_session", TOKEN)
    return client


# ---- finding ---------------------------------------------------------------------------
def test_the_usual_places_are_found_and_lookalikes_left_out(pc, tmp_path, monkeypatch):
    found = paths.found(paths.usual_places(home=pc["home"], root=tmp_path / "apps" / "linkedin-studio"))
    assert found == {"skills_dir": [str(pc["skills_dir"])], "claude_bin": [str(pc["claude_bin"])],
                     "claude_config_dir": [str(pc["home"] / ".claude"), str(pc["home"] / ".claude-other")]}

    shim = pc["home"] / "npm" / "claude.cmd"          # an npm install puts a script on the PATH, not claude.exe
    shim.parent.mkdir()
    shim.write_text("@echo off", encoding="utf-8")
    monkeypatch.setattr(shutil, "which", lambda _name: str(shim))
    (pc["home"] / "Documents" / "linkedin-skills").mkdir(parents=True)     # a folder with the name but not the contents
    found = paths.found(paths.usual_places(home=pc["home"], root=tmp_path / "apps" / "linkedin-studio"))
    assert found["claude_bin"] == [str(pc["claude_bin"])] and found["skills_dir"] == [str(pc["skills_dir"])]


def test_one_file_spelled_two_ways_is_offered_once(pc, tmp_path, monkeypatch):
    shouting = pc["claude_bin"].with_name("claude.EXE")       # how Windows reports a program found on the PATH
    monkeypatch.setattr(shutil, "which", lambda _name: str(shouting))
    found = paths.found(paths.usual_places(home=pc["home"], root=tmp_path / "apps" / "linkedin-studio"))
    assert found["claude_bin"] == [str(pc["claude_bin"])]


def test_a_copy_next_to_the_app_is_offered_first(pc, tmp_path):
    beside = make_skills(tmp_path / "projects" / "linkedin-skills")
    places = paths.usual_places(home=pc["home"], root=tmp_path / "projects" / "linkedin-studio")
    assert paths.found(places)["skills_dir"] == [str(beside), str(pc["skills_dir"])]


# ---- checking --------------------------------------------------------------------------
def test_a_good_choice_passes_and_quotes_from_copy_as_path_are_dropped(cfg, pc):
    values = chosen_from(pc)
    values["skills_dir"] = f'  "{values["skills_dir"]}"  '
    chosen, errors = paths.check(values, cfg, probe=False)
    assert errors == {} and chosen == {key: pc[key] for key in KEYS}
    assert path_problems(dataclasses.replace(cfg, **chosen)) == {}


@pytest.mark.parametrize("key, value, says", [
    ("skills_dir", "", "still empty"),
    ("skills_dir", "linkedin-skills", "whole path"),
    ("skills_dir", r"C:\nowhere\at\all", "not a linkedin-skills folder"),
    ("claude_config_dir", r"C:\nowhere\.claude", "does not exist"),
    ("claude_bin", r"C:\nowhere\claude.exe", "was not found"),
])
def test_each_mistake_is_named_under_its_own_box(cfg, pc, key, value, says):
    chosen, errors = paths.check({**chosen_from(pc), key: value}, cfg, probe=False)
    assert list(errors) == [key] and says in errors[key]
    assert set(chosen) >= set(KEYS) - {key}


def test_another_program_is_not_accepted_as_claude(cfg, pc, monkeypatch):
    other = pc["home"] / "python.exe"
    other.write_bytes(b"x")
    monkeypatch.setattr(paths, "claude_version", lambda _cfg: pytest.fail("a file with another name must not be run"))
    _chosen, errors = paths.check({**chosen_from(pc), "claude_bin": str(other)}, cfg)
    assert errors == {"claude_bin": "Choose the file named claude.exe."}


def test_the_program_is_asked_who_it_is_only_when_everything_else_is_right(cfg, pc, monkeypatch):
    monkeypatch.setattr(paths, "claude_version", lambda _cfg: "2.1.292 (Claude Code)")
    assert paths.check(chosen_from(pc), cfg)[1] == {}
    monkeypatch.setattr(paths, "claude_version", lambda _cfg: "Claude 1.2.3")        # the desktop app's claude.exe
    assert "did not answer as Claude Code" in paths.check(chosen_from(pc), cfg)[1]["claude_bin"]
    monkeypatch.setattr(paths, "claude_version", lambda _cfg: pytest.fail("nothing is run while a folder is wrong"))
    assert list(paths.check({**chosen_from(pc), "skills_dir": r"C:\nowhere"}, cfg)[1]) == ["skills_dir"]


# ---- saving ----------------------------------------------------------------------------
def test_the_first_save_starts_from_the_example_and_changes_three_lines(pc, config_files):
    local, example = config_files
    chosen = {key: pc[key] for key in KEYS}
    assert paths.save(chosen) == local
    before, after = example.read_text(encoding="utf-8").splitlines(), local.read_text(encoding="utf-8").splitlines()
    changed = [(a, b) for a, b in zip(before, after, strict=True) if a != b]
    assert sorted(b.split(" = ")[0] for _a, b in changed) == sorted(KEYS)
    saved = load_config(local)
    assert (saved.skills_dir, saved.claude_bin, saved.claude_config_dir) == (pc["skills_dir"], pc["claude_bin"], pc["claude_config_dir"])
    assert saved.port == load_config(example).port


def test_a_later_save_keeps_your_other_settings_comments_and_line_endings(pc, config_files):
    local, _example = config_files
    local.write_bytes(b"# mine\r\nport = 9001\r\nskills_dir = 'C:\\old'\r\nclaude_bin = 'C:\\old\\claude.exe'\r\n"
                      b"# claude_config_dir = 'C:\\commented\\out'\r\nmodel = 'opus'\r\n")
    odd = pc["home"] / "O'Brien" / "linkedin-skills"       # an apostrophe needs the other kind of quotes
    paths.save({**{key: pc[key] for key in KEYS}, "skills_dir": odd})
    raw = local.read_bytes()
    assert raw.startswith(b"# mine\r\nport = 9001\r\n") and b"\r\nmodel = 'opus'\r\n" in raw
    assert b"# claude_config_dir = 'C:\\commented\\out'\r\n" in raw and raw.count(b"\n") == raw.count(b"\r\n")
    saved = load_config(local)
    assert (saved.skills_dir, saved.claude_config_dir, saved.port, saved.model) == (odd, pc["claude_config_dir"], 9001, "opus")


def test_a_file_laid_out_another_way_is_left_exactly_as_it_was(pc, config_files):
    local, _example = config_files
    original = "[paths]\nskills_dir = 'C:\\old'\n"
    local.write_text(original, encoding="utf-8")
    with pytest.raises(ConfigError):
        paths.save({key: pc[key] for key in KEYS})
    assert local.read_text(encoding="utf-8") == original and not local.with_name(local.name + ".tmp").exists()


# ---- the screen ------------------------------------------------------------------------
def test_with_wrong_folders_every_page_leads_to_the_setup_screen(cfg, tmp_path, fake_runner, looks_in_pc):
    pc = looks_in_pc
    broken = dataclasses.replace(cfg, skills_dir=tmp_path / "not-there", claude_config_dir=tmp_path / "no-login")
    with client_for(broken, tmp_path, fake_runner) as client:
        for page in ("/", "/settings", "/guide", "/drafts", "/tools", "/planner", "/interviewer", "/bank"):
            answer = client.get(page)
            assert (answer.status_code, answer.headers["location"]) == (303, "/setup"), page
        body = client.get("/setup").text
    assert "Set up LinkedIn Studio" in body and 'class="app bare"' in body
    assert "/jobs/active" not in body and 'href="/guide"' not in body       # nothing that would bounce back here
    for field in paths.FIELDS:
        assert field.label in body and f'name="{field.key}"' in body
    assert body.count("For example") == len(paths.FIELDS) and "Found on this PC" in body
    # A place that works is offered in the box already; what is configured but wrong is not kept.
    assert f'value="{pc["skills_dir"]}"' in body and f'value="{pc["claude_config_dir"]}"' in body
    assert "not-there" not in body and f'data-fill="{pc["claude_bin"]}"' in body


def test_with_working_folders_the_screen_is_reached_from_settings(cfg, tmp_path, fake_runner):
    with client_for(cfg, tmp_path, fake_runner) as client:
        assert 'href="/setup"' in client.get("/settings").text
        body = client.get("/setup").text
    assert "Set up LinkedIn Studio" not in body and 'class="app"' in body
    assert f'value="{cfg.skills_dir}"' in body and "Save and restart" not in body     # no launcher here, so no restart


def test_a_wrong_choice_is_shown_and_nothing_is_written(cfg, pc, tmp_path, fake_runner, config_files):
    local, _example = config_files
    with client_for(cfg, tmp_path, fake_runner) as client:
        answer = client.post("/setup", data={**chosen_from(pc), "claude_config_dir": r"C:\nowhere\.claude"})
    assert answer.status_code == 200 and "does not exist" in answer.text and 'id="paths-form"' in answer.text
    assert r'value="C:\nowhere\.claude"' in answer.text and not local.exists()


def test_a_good_choice_is_saved_and_the_app_restarts(cfg, pc, tmp_path, fake_runner, config_files, monkeypatch):
    local, _example = config_files
    monkeypatch.setattr(paths, "claude_version", lambda _cfg: "2.1.292 (Claude Code)")
    restarted = threading.Event()
    with client_for(cfg, tmp_path, fake_runner, on_restart=restarted.set) as client:
        answer = client.post("/setup", data=chosen_from(pc))
        assert answer.status_code == 200 and "is restarting" in answer.text
        assert restarted.wait(5), "the launcher was not asked to restart"
    assert load_config(local).claude_config_dir == pc["claude_config_dir"]


def test_without_a_launcher_it_says_to_reopen_the_app(cfg, pc, tmp_path, fake_runner, config_files, monkeypatch):
    monkeypatch.setattr(paths, "claude_version", lambda _cfg: "2.1.292 (Claude Code)")
    with client_for(cfg, tmp_path, fake_runner) as client:
        answer = client.post("/setup", data=chosen_from(pc))
    assert "Close LinkedIn Studio and open it again" in answer.text and config_files[0].is_file()


def test_another_site_cannot_change_the_folders(cfg, pc, tmp_path, fake_runner, config_files):
    with client_for(cfg, tmp_path, fake_runner) as client:
        answer = client.post("/setup", data=chosen_from(pc), headers={"Origin": "http://evil.example"})
        assert answer.status_code == 403 and not config_files[0].exists()
        assert client.post("/setup/browse", data={"field": "skills_dir"}, headers={"Origin": "http://evil.example"}).status_code == 403


# ---- browse ----------------------------------------------------------------------------
def test_browse_returns_what_the_file_window_chose(cfg, tmp_path, fake_runner, monkeypatch):
    # Stand-in for the window: it "chooses" a path that records which kind of window was asked for and where it opened.
    monkeypatch.setattr(paths, "PICKER", "import sys; sys.stdout.write('C:/picked/' + sys.argv[1] + '/' + sys.argv[2][-6:])")
    start = tmp_path / "start-here" / "claude.exe"
    start.parent.mkdir()
    with client_for(cfg, tmp_path, fake_runner) as client:
        folder = client.post("/setup/browse", data={"field": "skills_dir", "start": str(tmp_path / "start-here")})
        program = client.post("/setup/browse", data={"field": "claude_bin", "start": f'"{start}"'})
        assert client.post("/setup/browse", data={"field": "port"}).status_code == 404
        with paths._picker:                                    # one is already open
            assert client.post("/setup/browse", data={"field": "skills_dir"}).status_code == 409
    assert folder.json() == {"path": r"C:\picked\folder\t-here"}
    assert program.json() == {"path": r"C:\picked\file\t-here"}       # a file's folder is where the window opens


def test_closing_the_file_window_chooses_nothing_and_a_failure_is_explained(cfg, tmp_path, fake_runner, monkeypatch):
    with client_for(cfg, tmp_path, fake_runner) as client:
        monkeypatch.setattr(paths, "PICKER", "pass")
        assert client.post("/setup/browse", data={"field": "skills_dir"}).json() == {"path": ""}
        monkeypatch.setattr(paths, "PICKER", "raise SystemExit('no display')")
        failed = client.post("/setup/browse", data={"field": "skills_dir"})
    assert failed.status_code == 500 and "Type or paste the path instead" in failed.json()["error"]
