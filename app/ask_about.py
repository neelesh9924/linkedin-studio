"""Ask me about this, on a saved Story Bank entry: a new Interviewer conversation about that one entry.

The page sends `focus = {section, entry}` exactly as /api/bank listed it (render.doc_sections: each section's filled
entries, by the same rule as its counts). It is checked against the file as it is now, so only an entry the Story
Bank holds can start one, and what the message and the prompt quote of it is capped. The interviewer's first run then
asks linkedin-interviewer (--mode bank) about that entry alone (skills._interview); its tools stay its own.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import render

QUOTED_MAX = 300     # characters of the entry the first message and the prompt quote
GIVEN_MAX = 4000     # a section or entry longer than this is never one the file holds


def _short(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= QUOTED_MAX else text[:QUOTED_MAX].rstrip() + "…"


def focus_of(data: dict, mode: str, story_bank: Path) -> dict | str | None:
    """The focus a chat message asks for, checked: None (none asked), {section, entry} as the file has them, or the
    words that refuse it."""
    given = data.get("focus")
    if not given:
        return None
    if mode != "bank":
        return "Ask me about this works on the Story Bank only."
    if not isinstance(given, dict):
        return "That entry is not in your Story Bank as it is now."
    section, entry = given.get("section"), given.get("entry")
    if not isinstance(section, str) or not isinstance(entry, str) or not section.strip() or not entry.strip() \
            or len(section) > GIVEN_MAX or len(entry) > GIVEN_MAX:
        return "That entry is not in your Story Bank as it is now."
    try:
        text = story_bank.read_text(encoding="utf-8")
    except OSError:
        return "The Story Bank file was not found. Check skills_dir (Settings › Change folders)."
    for found in render.doc_sections(text):
        if found["title"] == section and entry in found["entries"]:
            return {"section": section, "entry": _short(entry)}
    return "That entry is not in your Story Bank as it is now. The page shows it as it is: try again from there."


def opening(focus: dict) -> str:
    """The conversation's first message, as the owner sees it: the entry (without its ** and ` marks: the chat shows
    the owner's words as plain text) and its section (without its number). The prompt quotes the entry as the file has it."""
    section = re.sub(r"^\d+\.\s*", "", focus["section"]).strip() or focus["section"]
    entry = re.sub(r"[*`]", "", focus["entry"]).strip() or focus["entry"]
    return f'Ask me about this: "{entry}" ({section})'
