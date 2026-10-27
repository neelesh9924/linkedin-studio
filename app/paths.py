"""The three places the app has to be told about, and what the setup screen does with them.

Where the skills live, where the Claude program is and where Claude keeps its sign-in differ
from one PC to the next. This module looks in the usual places, checks what the user chose,
opens a Windows file window for Browse, and writes the choice into config.local.toml while
leaving everything else in that file as it was.
"""
from __future__ import annotations

import dataclasses
import os
import re
import shutil
import subprocess
import threading
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .claude_runner import CREATE_NO_WINDOW
from .config import ROOT, Config, ConfigError, path_problems
from .health import claude_account, claude_version, venv_python

LOCAL = ROOT / "config.local.toml"
EXAMPLE = ROOT / "config.example.toml"


@dataclass(frozen=True)
class Field:
    key: str        # its name in config.local.toml
    label: str
    kind: str       # "folder" or "file": which window Browse opens
    what: str       # one sentence under the box


FIELDS = (
    Field("skills_dir", "Skills folder", "folder",
          "Your copy of linkedin-skills. Claude works inside this folder."),
    Field("claude_bin", "Claude program", "file",
          "The file claude.exe: Claude Code's command-line program, not the desktop app."),
    Field("claude_config_dir", "Claude login folder", "folder",
          "Where Claude Code keeps your sign-in. Every run uses the login in this folder."),
)
LOOKS_RIGHT = {
    "skills_dir": lambda p: (p / "skills").is_dir(),
    "claude_bin": lambda p: p.is_file() and p.name.lower() == "claude.exe",
    "claude_config_dir": lambda p: p.is_dir(),
}


class PickerBusy(RuntimeError):
    """A file window is already open; Windows shows one at a time for this app."""


def usual_places(home: Path | None = None, root: Path = ROOT) -> dict[str, list[Path]]:
    """Where each thing normally is on a PC. The first one is shown as the example under its box."""
    home = home or Path.home()
    on_path = shutil.which("claude")
    named = os.environ.get("CLAUDE_CONFIG_DIR")
    return {
        "skills_dir": [root.parent / "linkedin-skills", home / "linkedin-skills", home / "Documents" / "linkedin-skills"],
        "claude_bin": [home / ".local" / "bin" / "claude.exe"] + ([Path(on_path)] if on_path else []),
        "claude_config_dir": [home / ".claude"] + ([Path(named)] if named else []) + sorted(home.glob(".claude-*")),
    }


def found(places: dict[str, list[Path]]) -> dict[str, list[str]]:
    """The usual places that exist on this PC and look right, for the user to pick from."""
    out: dict[str, list[str]] = {}
    for key, candidates in places.items():
        out[key], seen = [], set()
        for place in candidates:
            same = os.path.normcase(os.path.normpath(str(place)))   # Windows may spell one file claude.exe and claude.EXE
            try:
                good = same not in seen and LOOKS_RIGHT[key](place)
            except OSError:
                good = False
            if good:
                seen.add(same)
                out[key].append(str(place))
        del out[key][4:]
    return out


def check(values: dict[str, str], cfg: Config, probe: bool = True,
          prefix: list[str] | None = None) -> tuple[dict[str, Path], dict[str, str]]:
    """Turn what was typed into paths and say what is wrong with each. No errors = usable.

    With `probe`, a program that passes every other check is also asked for its version, so a
    different claude.exe (the desktop app has one too) is caught here and not on the first job;
    then who the login folder is signed in to. A folder that says it is signed in to nobody is
    refused; an answer that cannot be read is no reason to refuse (the screen shows it).
    """
    chosen: dict[str, Path] = {}
    errors: dict[str, str] = {}
    for field in FIELDS:
        text = (values.get(field.key) or "").strip().strip('"').strip()   # Explorer's "Copy as path" adds quotes
        if not text:
            errors[field.key] = "This one is still empty."
        elif any(ord(ch) < 32 for ch in text) or not Path(text).is_absolute():
            errors[field.key] = "Give the whole path, starting with the drive letter."
        else:
            chosen[field.key] = Path(text)
    candidate = dataclasses.replace(cfg, **chosen)
    for key, why in path_problems(candidate).items():
        if key in chosen:
            errors[key] = why
    program = chosen.get("claude_bin")
    if program is not None and "claude_bin" not in errors:
        if program.name.lower() != "claude.exe":
            errors["claude_bin"] = "Choose the file named claude.exe."
        elif probe and not errors:
            said = claude_version(candidate)
            if "Claude Code" not in said:
                errors["claude_bin"] = f"That file did not answer as Claude Code. It said: {said[:120]}"
            elif claude_account(candidate, prefix)["signed_in"] is False:
                errors["claude_config_dir"] = ("Claude Code is not signed in with this login folder. Run claude once "
                                               "in a terminal and sign in, or choose the folder you signed in with.")
    return chosen, errors


def toml_string(text: str) -> str:
    """A TOML string holding exactly `text`. Single quotes keep Windows backslashes readable."""
    if "'" not in text:
        return f"'{text}'"
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def save(chosen: dict[str, Path], local: Path | None = None, example: Path | None = None) -> Path:
    """Write the chosen paths into config.local.toml, starting it from the example the first time."""
    return save_values({key: str(path) for key, path in chosen.items()}, local, example)


def save_values(values: dict[str, str], local: Path | None = None, example: Path | None = None) -> Path:
    """Write these settings into config.local.toml, starting it from the example the first time.

    Only the lines for these settings change; comments and every other setting stay.
    """
    local, example = local or LOCAL, example or EXAMPLE
    source = local if local.is_file() else example
    try:
        lines = source.read_bytes().decode("utf-8-sig").splitlines(keepends=True)
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"Cannot read {source.name}: {exc}") from exc
    eol = "\r\n" if lines and lines[0].endswith("\r\n") else "\n"
    for key, value in values.items():
        entry = f"{key} = {toml_string(value)}"
        for i, line in enumerate(lines):
            if re.match(rf"{key}\s*=", line):
                lines[i] = entry + (line[len(line.rstrip("\r\n")):] or eol)
                break
        else:
            if lines and not lines[-1].endswith("\n"):
                lines[-1] += eol
            lines.append(entry + eol)
    text = "".join(lines)
    try:
        written = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{source.name} could not be updated safely: {exc}") from exc
    if any(written.get(key) != value for key, value in values.items()):
        raise ConfigError(f"{local.name} has a layout the app cannot update safely. Set "
                          f"{', '.join(values)} in it by hand.")
    try:
        temp = local.with_name(local.name + ".tmp")
        temp.write_bytes(text.encode("utf-8"))
        os.replace(temp, local)
    except OSError as exc:
        raise ConfigError(f"Cannot write {local.name}: {exc}") from exc
    return local


# Runs in its own Python, because a window toolkit and a web server do not share a process well.
# The hidden parent window is kept on top so the file window opens above the app, not behind it.
PICKER = r"""
import sys, tkinter
from tkinter import filedialog
kind, start, title = sys.argv[1:4]
root = tkinter.Tk()
root.withdraw()
root.attributes("-topmost", True)
root.update()
if kind == "folder":
    chosen = filedialog.askdirectory(parent=root, initialdir=start, title=title, mustexist=True)
else:
    chosen = filedialog.askopenfilename(parent=root, initialdir=start, title=title,
                                        filetypes=[("Claude Code", "claude.exe"), ("Programs", "*.exe")])
root.destroy()
sys.stdout.buffer.write((chosen or "").encode("utf-8"))
"""
_picker = threading.Lock()


def browse_title(field: Field) -> str:
    return f"LinkedIn Studio: choose the {field.label.lower()}"


def browse(field: Field, start: str = "", timeout: float = 900) -> str:
    """Open a Windows file or folder window and return what was chosen ("" = closed without choosing)."""
    text = start.strip().strip('"').strip()
    where = Path(text) if text and Path(text).is_absolute() else Path.home()
    while not where.is_dir() and where != where.parent:
        where = where.parent
    if not _picker.acquire(blocking=False):
        raise PickerBusy
    try:
        done = subprocess.run([venv_python(), "-c", PICKER, field.kind, str(where), browse_title(field)],
                              capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL,
                              creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
    except subprocess.TimeoutExpired:
        return ""
    finally:
        _picker.release()
    if done.returncode != 0:
        tail = done.stderr.decode("utf-8", "replace").strip().splitlines()
        raise OSError(tail[-1] if tail else "the window could not be opened")
    chosen = done.stdout.decode("utf-8", "replace").strip()
    return str(Path(chosen)) if chosen else ""
