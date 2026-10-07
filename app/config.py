"""Load config.local.toml (falling back to config.example.toml) and check it."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
HOST = "127.0.0.1"  # never configurable: the app only listens on loopback


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    skills_dir: Path
    claude_bin: Path
    claude_config_dir: Path
    port: int = 8765
    monthly_post_limit: int = 15
    timezone: str = "Asia/Kolkata"
    browser_path: str = ""
    model: str = "sonnet"
    max_turns: int = 12
    timeout_seconds: int = 180

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def origin(self) -> str:
        return f"http://{HOST}:{self.port}"

    @property
    def env_file(self) -> Path:
        return self.skills_dir / ".env"

    @property
    def story_bank(self) -> Path:
        return self.skills_dir / "references" / "story-bank.md"

    @property
    def voice_profile(self) -> Path:
        return self.skills_dir / "references" / "voice-profile.md"


def config_path() -> Path:
    local = ROOT / "config.local.toml"
    return local if local.is_file() else ROOT / "config.example.toml"


def load_config(path: Path | None = None) -> Config:
    path = path or config_path()
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8-sig"))  # tolerate a BOM from Notepad/PowerShell
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"Cannot read {path.name}: {exc}") from exc
    try:
        cfg = Config(
            skills_dir=Path(raw["skills_dir"]),
            claude_bin=Path(raw["claude_bin"]),
            claude_config_dir=Path(raw.get("claude_config_dir") or ""),
            port=int(raw.get("port", 8765)),
            monthly_post_limit=int(raw.get("monthly_post_limit", 15)),
            timezone=str(raw.get("timezone", "Asia/Kolkata")),
            browser_path=str(raw.get("browser_path", "")),
            model=str(raw.get("model", "sonnet")),
            max_turns=int(raw.get("max_turns", 12)),
            timeout_seconds=int(raw.get("timeout_seconds", 180)),
        )
    except KeyError as exc:
        raise ConfigError(f"{path.name} is missing {exc.args[0]!r}") from exc
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{path.name} has a bad value: {exc}") from exc
    cfg.tz  # raises early on a bad timezone name
    return cfg


def path_problems(cfg: Config) -> dict[str, str]:
    """What is wrong with the three places the setup screen asks for: setting name -> plain words.

    These differ from one PC to the next, so the app opens its setup screen for them instead
    of refusing to start.
    """
    out = {}
    if not cfg.skills_dir.is_absolute() or not (cfg.skills_dir / "skills").is_dir():
        out["skills_dir"] = f"This is not a linkedin-skills folder: {cfg.skills_dir}"
    elif not (cfg.skills_dir / ".claude" / "skills" / "linkedin-humanizer" / "SKILL.md").is_file():
        out["skills_dir"] = ("The skills in this folder are not real links, so Claude cannot find them. "
                             "Clone it again with symlinks on (README > Troubleshooting).")
    if not cfg.claude_bin.is_absolute() or not cfg.claude_bin.is_file():
        out["claude_bin"] = f"The Claude program was not found here: {cfg.claude_bin}"
    if not str(cfg.claude_config_dir) or str(cfg.claude_config_dir) == ".":
        out["claude_config_dir"] = "The Claude login folder is not set."
    elif not cfg.claude_config_dir.is_absolute() or not cfg.claude_config_dir.is_dir():
        out["claude_config_dir"] = f"The Claude login folder does not exist: {cfg.claude_config_dir}"
    return out


def problems(cfg: Config) -> list[str]:
    """Everything that stops the app from working, in plain words. Empty = fine."""
    out = list(path_problems(cfg).values())
    if not 1024 <= cfg.port <= 65535:
        out.append(f"port {cfg.port} is out of range")
    return out
