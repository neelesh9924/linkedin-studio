"""Keep the Story Bank and the voice profile out of git.

Both files are tracked in the linkedin-skills repository as empty templates, and the skills
fill them with career details, names and numbers. A plain `.gitignore` line does nothing for
a file git already tracks, so the app sets git's skip-worktree flag on the two files in this
clone instead: git then treats the local copies as unchanged. They never show in
`git status`, are never picked up by `git add -A` or a commit, and so cannot be pushed by
accident. No file in the repository is edited; the flag lives in this clone's index and is
undone with `git update-index --no-skip-worktree <file>`.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

PERSONAL_FILES = (
    "references/story-bank.md",
    "references/voice-profile.md",
    # The repo's sync script (run by its self-test) copies both into its Codex package.
    # Once the originals are filled, those copies hold the same personal details.
    ".codex-marketplace/linkedin-skills/references/story-bank.md",
    ".codex-marketplace/linkedin-skills/references/voice-profile.md",
)
CREATE_NO_WINDOW = 0x08000000

# Added to the chat skills' rules once the files are protected. The skills are written to warn
# "add this file to .gitignore before pushing"; here that chore is already done for the user.
CHAT_NOTE = (
    "5. Privacy is already handled: on this computer git ignores local changes to the Story Bank "
    "(references/story-bank.md) and the voice profile (references/voice-profile.md), so they cannot be committed or pushed by "
    "accident. Do not ask the user to edit .gitignore and do not warn about pushing. Where the skill wants "
    "you to say where the file lives, say in one short sentence that it stays on this computer, out of git.\n"
)


@dataclass
class Protection:
    state: str                      # protected | no-repo | nested | no-git | partial | error
    detail: str                     # one plain sentence for the UI
    files: dict[str, bool] = field(default_factory=dict)   # path -> kept out of git

    @property
    def ok(self) -> bool:
        return self.state in ("protected", "no-repo")


def _git(git: str, repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([git, "-C", str(repo), *args], capture_output=True, text=True, timeout=20,
                          stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)


def _flags(git: str, repo: Path) -> dict[str, str]:
    """`git ls-files -v`: first letter S means skip-worktree; a file git does not track is absent."""
    out = _git(git, repo, "ls-files", "-v", "--", *PERSONAL_FILES)
    flags = {}
    for line in out.stdout.splitlines():
        tag, _, path = line.partition(" ")
        if path:
            flags[path.strip()] = tag
    return flags


def _exclude_locally(git: str, repo: Path) -> None:
    """List the files in this clone's private ignore file (.git/info/exclude).

    That covers the case skip-worktree cannot: a personal file git does not track (yet).
    """
    where = _git(git, repo, "rev-parse", "--git-path", "info/exclude").stdout.strip()
    if not where:
        return
    path = Path(where) if Path(where).is_absolute() else repo / where
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    missing = [f"/{p}" for p in PERSONAL_FILES if f"/{p}" not in lines]
    if missing:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(("" if not lines or lines[-1] == "" else "\n")
                     + "# LinkedIn Studio: personal files stay out of git\n" + "\n".join(missing) + "\n")


def _inside_another_repo(git: str | None, skills_dir: Path) -> Protection | None:
    """For a skills folder that is not a repository itself but sits inside one.

    That outer repository is not this app's to edit, so nothing is changed here: the app only
    reports whether the outer repository already ignores the files.
    """
    if not git:
        return None
    try:
        if _git(git, skills_dir, "rev-parse", "--is-inside-work-tree").stdout.strip() != "true":
            return None
        ignored = set(_git(git, skills_dir, "check-ignore", "--", *PERSONAL_FILES).stdout.splitlines())
    except (OSError, subprocess.TimeoutExpired):
        return None
    files = {p: p in ignored for p in PERSONAL_FILES}
    if all(files.values()):
        return Protection("protected", "The repository this folder sits in ignores these files, so they cannot be "
                                       "committed or pushed by accident.", files)
    return Protection("nested", "The skills folder sits inside another git repository, which this app leaves alone. "
                                "Keep these files out of that repository yourself.", files)


def protect(skills_dir: Path) -> Protection:
    """Make sure git cannot pick up the personal files. Safe to call on every start."""
    git = shutil.which("git")
    if not (skills_dir / ".git").exists():
        return _inside_another_repo(git, skills_dir) or Protection(
            "no-repo", "The skills folder is not a git repository, so nothing in it can be pushed.")
    if not git:
        return Protection("no-git", "Git was not found, so the app could not check that these files stay out of git.")
    try:
        _exclude_locally(git, skills_dir)
        flags = _flags(git, skills_dir)
        todo = [p for p in PERSONAL_FILES if p in flags and flags[p].upper() != "S"]
        if todo:
            done = _git(git, skills_dir, "update-index", "--skip-worktree", "--", *todo)
            if done.returncode != 0:
                return Protection("error", f"Git refused to protect the files: {done.stderr.strip()[:200]}")
            flags = _flags(git, skills_dir)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return Protection("error", f"Could not run git: {exc}")
    # Tracked files need the skip-worktree flag; untracked ones are covered by the exclude list.
    files = {p: (p not in flags or flags[p].upper() == "S") for p in PERSONAL_FILES}
    if all(files.values()):
        return Protection("protected", "Git ignores your changes to these files, so they cannot be committed or "
                                       "pushed by accident.", files)
    return Protection("partial", "Some of these files are still visible to git.", files)
