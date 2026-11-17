"""The Story Bank and voice profile must never be picked up by git, however they get filled."""
import dataclasses
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.privacy import PERSONAL_FILES, protect

ROOT = Path(__file__).resolve().parents[1]
GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(GIT is None, reason="git is not installed")
BANK, VOICE, BANK_COPY, VOICE_COPY = PERSONAL_FILES


def git(repo, *args):
    return subprocess.run([GIT, "-C", str(repo), "-c", "commit.gpgsign=false", *args],
                          capture_output=True, text=True, check=True).stdout


def make_repo(path, tracked=PERSONAL_FILES):
    path.mkdir(parents=True)
    (path / "README.md").write_text("readme\n", encoding="utf-8")
    for name in tracked:
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_text("- filled: no\n", encoding="utf-8")
    git(path, "init", "-q")
    git(path, "config", "user.email", "test@example.com")
    git(path, "config", "user.name", "Test")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "templates")
    return path


@pytest.fixture
def repo(tmp_path):
    return make_repo(tmp_path / "skills")


def test_this_repository_tracks_no_personal_material():
    """The app's own repository may be published one day: no key, database or personal file in it."""
    if not (ROOT / ".git").exists():
        pytest.skip("not running from a git checkout")
    tracked = git(ROOT, "ls-files").splitlines()
    personal = re.compile(r"(^|/)(\.env(\..*)?|[^/]*\.db|story-bank[^/]*\.md|voice-profile[^/]*\.md|config\.local\.toml)$")
    assert [name for name in tracked if personal.search(name)] == []
    # A real Publora key is sk_<id>_<hex>.<long hex>. The made-up keys in tests are not that shape.
    found = subprocess.run([GIT, "-C", str(ROOT), "grep", "-I", "-l", "-E", r"sk_[a-z0-9]{6,}_[0-9a-f]{6,}\.[0-9a-f]{16,}"],
                           capture_output=True, text=True)
    assert found.stdout == "" and found.returncode == 1            # 1 is git grep's "nothing found"
    for name in ("story-bank.md", "voice-profile-backup.md", ".env", "copy-of-studio.db"):
        ignored = subprocess.run([GIT, "-C", str(ROOT), "check-ignore", "-q", name])
        assert ignored.returncode == 0, f"{name} would not be ignored if it were dropped into this folder"


def test_a_filled_story_bank_never_reaches_a_commit(repo):
    result = protect(repo)
    assert result.state == "protected" and result.ok and all(result.files.values())
    (repo / BANK).write_text("- filled: yes\n- Salary: 42 lakh, do not share\n", encoding="utf-8")
    (repo / VOICE).write_text("- filled: yes\n- I never say synergy\n", encoding="utf-8")
    (repo / "README.md").write_text("an ordinary change\n", encoding="utf-8")

    assert git(repo, "status", "--porcelain").split() == ["M", "README.md"]
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "everything I changed")

    assert git(repo, "show", f"HEAD:{BANK}") == "- filled: no\n"       # what a push would carry
    assert git(repo, "show", f"HEAD:{VOICE}") == "- filled: no\n"
    assert "42 lakh" in (repo / BANK).read_text(encoding="utf-8")       # the local file is untouched


def test_the_copies_the_sync_script_makes_are_covered_too(repo):
    """selftest.py runs sync_codex_marketplace.py, which copies the filled files into the Codex package."""
    protect(repo)
    for original, copy in ((BANK, BANK_COPY), (VOICE, VOICE_COPY)):
        (repo / original).write_text("- filled: yes\n- private detail\n", encoding="utf-8")
        shutil.copy(repo / original, repo / copy)
    assert git(repo, "status", "--porcelain") == ""
    git(repo, "add", "-A")
    assert git(repo, "diff", "--cached", "--name-only") == ""


def test_protecting_twice_changes_nothing_more(repo):
    assert protect(repo).state == "protected"
    exclude = repo / ".git" / "info" / "exclude"
    first = exclude.read_text(encoding="utf-8")
    assert protect(repo).state == "protected"
    assert exclude.read_text(encoding="utf-8") == first
    assert all(first.splitlines().count(f"/{name}") == 1 for name in PERSONAL_FILES)
    assert git(repo, "status", "--porcelain") == ""                    # no repository file was edited


def test_a_personal_file_git_does_not_track_is_ignored_too(tmp_path):
    repo = make_repo(tmp_path / "skills", tracked=())
    assert protect(repo).state == "protected"
    (repo / "references").mkdir()
    (repo / BANK).write_text("- filled: yes\n- private\n", encoding="utf-8")
    assert git(repo, "status", "--porcelain") == ""
    git(repo, "add", "-A")
    assert git(repo, "diff", "--cached", "--name-only") == ""


def test_a_folder_that_is_not_a_repository_needs_nothing(tmp_path):
    result = protect(tmp_path)
    assert result.state == "no-repo" and result.ok


def test_a_folder_inside_someone_elses_repository_is_reported_and_left_alone(tmp_path):
    outer = make_repo(tmp_path / "outer", tracked=())
    inner = outer / "vendor" / "skills"
    (inner / "references").mkdir(parents=True)
    (inner / BANK).write_text("- filled: yes\n- private\n", encoding="utf-8")
    exclude = outer / ".git" / "info" / "exclude"
    before = exclude.read_text(encoding="utf-8") if exclude.is_file() else ""

    result = protect(inner)
    assert result.state == "nested" and not result.ok          # the outer repository would pick the file up

    (outer / ".gitignore").write_text("vendor/skills/\n", encoding="utf-8")
    result = protect(inner)
    assert result.state == "protected" and result.ok            # unless it already ignores the folder
    assert (exclude.read_text(encoding="utf-8") if exclude.is_file() else "") == before   # nothing of theirs was edited


def test_the_app_protects_the_files_when_it_starts_and_the_bank_page_says_so(cfg, tmp_path, fake_runner):
    repo = make_repo(tmp_path / "clone")
    (repo / "skills").mkdir()                                   # what the app checks for before it shows any page
    link = repo / ".claude" / "skills" / "linkedin-humanizer" / "SKILL.md"
    link.parent.mkdir(parents=True)
    link.write_text("test", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "skills")
    (repo / BANK).write_text("# Story Bank\n\n> Add `references/story-bank.md` to your `.gitignore` before you fill it.\n\n"
                             "## Status\n\n- filled: yes\n- updated: (date)\n\n## 1. Receipts\n\n- Salary: 42 lakh\n",
                             encoding="utf-8")
    app = create_app(dataclasses.replace(cfg, skills_dir=repo), "tok", db_path=tmp_path / "p.db", runner=fake_runner)
    with TestClient(app, base_url=f"http://127.0.0.1:{cfg.port}", headers={"Origin": cfg.origin}) as client:
        client.cookies.set("studio_session", "tok")
        body = client.get("/api/bank").json()
    assert git(repo, "status", "--porcelain") == ""             # the filled file is invisible to git
    assert body["protection"]["ok"] is True and body["protection"]["state"] == "protected"
    assert body["files"]["bank"]["status"]["updated"] == ""     # a template hint is not a date
