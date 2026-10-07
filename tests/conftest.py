import dataclasses
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.claude_runner import ClaudeRunner  # noqa: E402
from app.config import Config  # noqa: E402

FAKE = Path(__file__).with_name("fake_claude.py")
REAL_SKILLS = ROOT.parent / "linkedin-skills"    # the real clone, next to this folder; tests that need it skip without it


def make_skills(folder: Path) -> Path:
    """The parts of a linkedin-skills clone the app looks for before it will start."""
    (folder / "references").mkdir(parents=True)
    (folder / "skills").mkdir()
    link = folder / ".claude" / "skills" / "linkedin-humanizer"
    link.mkdir(parents=True)
    (link / "SKILL.md").write_text("test", encoding="utf-8")
    return folder


@pytest.fixture
def cfg(tmp_path) -> Config:
    skills = make_skills(tmp_path / "skills")
    (skills / ".env").write_text("PUBLORA_API_KEY=sk_test_secret\nAPIFY_TOKEN=apify_api_your_token_here\n",
                                 encoding="utf-8")
    confdir = tmp_path / "claude-config"
    confdir.mkdir()
    return Config(skills_dir=skills, claude_bin=Path(sys.executable), claude_config_dir=confdir, port=8799,
                  monthly_post_limit=15, timezone="Asia/Kolkata", model="sonnet", max_turns=12, timeout_seconds=30)


@pytest.fixture
def fake_runner(cfg):
    return ClaudeRunner(cfg, prefix=[sys.executable, str(FAKE)])


def with_(cfg: Config, **kw) -> Config:
    return dataclasses.replace(cfg, **kw)
