"""Post style (Settings › Post style, and each post's Style): four sliders that say how a post is written, in the same
words for every run that writes one (a post's Ask Claude and its Restyle, Hot topics' drafts).

    Hook    1 plain .. 5 bold        how the first line pulls the reader in
    Tone    1 formal .. 5 warm       how it sounds
    Emojis  0 none .. 3 markers      this many, never the ones that read as AI; markers: one anchoring each list line
    Layout  1 plain .. 2 sections    paragraphs, or a bold first line and bold heads to scan on a phone (bold.py)

Whatever the sliders say, the post stays professional for LinkedIn (RULE). The owner's default is kept beside the
database (`style.json`, as profile.json is); a post restyled with other settings keeps its own (`posts.style`).
"""
from __future__ import annotations

import json
from pathlib import Path

from .db import DB

FILE = "style.json"
SLIDERS_BEFORE = ("hook", "tone", "emojis")   # the sliders of a style kept before Layout came (3 Nov 2026)
SLIDERS = {"hook": (1, 5), "tone": (1, 5), "emojis": (0, 3), "layout": (1, 2)}
DEFAULT = {"hook": 4, "tone": 4, "emojis": 1, "layout": 1}
LABELS = {
    "hook": {1: "Plain", 2: "Clear", 3: "Engaging", 4: "Catchy", 5: "Bold"},
    "tone": {1: "Formal", 2: "Plain", 3: "Peer to peer", 4: "Human", 5: "Warm"},
    "emojis": {0: "None", 1: "One", 2: "Two", 3: "Markers"},
    "layout": {1: "Plain", 2: "Sections"},
}
HOOK = {
    1: "Open with a plain statement or a number from the facts, and let the post build from there.",
    2: "Open with the clearest fact, put so that it says why it matters to the reader.",
    3: "Open with a concrete moment or a surprising true fact that makes the reader want the next line.",
    4: "Open with the sharpest moment of the story or the boldest honest claim, never a statistic: a confession, a "
       "surprise or what was at stake, so the reader needs the second line. The numbers come after, as the proof, and "
       "the payoff within the next two lines.",
    5: "Open as boldly as the facts allow, never with a statistic: the most surprising true line, with its stakes, short "
       "and punchy. It must still be true and paid off at once, never clickbait.",
}
TONE = {
    1: "Write formally and precisely: complete sentences, no contractions, no humour.",
    2: "Write plainly and professionally, with contractions where they come naturally.",
    3: "Write like a professional talking to a peer: first person, contractions, plain words.",
    4: "Write like a person telling a colleague about it over coffee: first person, contractions, plain words, and a "
       "little warmth or dry humour where it fits.",
    5: "Write warmly and personally, with feeling and humour where they fit, as one person talking to another.",
}
AI_TELLS = "such as 🚀 💡 🔑 ✨ 🎯 💪"
EMOJIS = {
    0: "Use no emojis.",
    1: "Use one emoji, where it adds the most meaning: a human one, never one the humanizer lists as an AI tell "
       f"({AI_TELLS}), and never at the start of a bullet.",
    2: "Use two emojis, two different ones, where they add the most meaning: human ones, never ones the humanizer lists "
       f"as AI tells ({AI_TELLS}), never at the start of bullets, and never on both the first line and the last.",
    3: "Use emojis as markers: one at the end of the first line; keycaps (1️⃣ 2️⃣ 3️⃣) to number steps or list items; "
       "and one meaningful emoji at the start of a line only where it says what the line is (⚠️ the trap, ✅ the fix, "
       "🔍 how to check). Never the same emoji twice, never one the humanizer lists as an AI tell "
       f"({AI_TELLS}), and none on the closing question. A post with no list or steps uses two at most.",
}
LAYOUT = {
    1: "Write it as short paragraphs, with no bold and no headings.",
    2: "Lay it out to scan on a phone: the first line in bold, and each part under a short bold head (a few words, on "
       "its own line or leading its line). Write bold as **words**; the studio turns it into LinkedIn's bold. Bold "
       "nothing else, and never code: code stays plain, on its own lines. Paragraphs of one or two sentences.",
}
RULE = ("Whatever the style, keep it professional for a LinkedIn audience: no slang, no clickbait, no hype words, and the "
        "writer's own rules still hold (no question and no capitals as the first line, the hashtag and link rules).")


class Refused(ValueError):
    """A slider value the page cannot have sent; the message says which, in the page's words."""


def clean(data) -> dict:
    """The four sliders from what the page sent, each a whole number in its range; anything else is refused. A style
    from before a slider came (a stored one, a job's params) takes that slider's default."""
    if not isinstance(data, dict):
        raise Refused("Send the four sliders.")
    data = {**{k: v for k, v in DEFAULT.items() if k not in SLIDERS_BEFORE}, **data}
    out = {}
    for name, (low, high) in SLIDERS.items():
        value = data.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise Refused(f"{name.capitalize()} goes from {low} to {high}.")
        out[name] = value
    return out


def valid(data) -> dict | None:
    """The sliders when they are all there and in range (a job's params, a stored style), else None."""
    try:
        return clean(data)
    except Refused:
        return None


def parse(text: str | None) -> dict | None:
    """A stored style (style.json, posts.style), or None when it is missing or no longer valid."""
    try:
        return valid(json.loads(text or ""))
    except (ValueError, TypeError):
        return None


def path(db: DB) -> Path:
    return db.path.parent / FILE


def default(db: DB) -> dict:
    """The owner's default from Settings, or the studio's own when none is saved."""
    try:
        text = path(db).read_text(encoding="utf-8")
    except OSError:
        return dict(DEFAULT)
    return parse(text) or dict(DEFAULT)


def save_default(db: DB, data) -> dict:
    style = clean(data)
    path(db).write_text(json.dumps(style), encoding="utf-8")
    return style


def of_post(db: DB, post) -> dict:
    """The style a post is written in: its own when it was restyled, else the default."""
    return parse(post["style"]) or default(db)


EMOJI_WORDS = {0: "no emojis", 1: "one emoji", 2: "two emojis", 3: "emoji markers"}


def summary(style: dict) -> str:
    """The sliders in a few words, as a Restyle shows them: "Hook catchy, tone human, one emoji, in sections"."""
    return (f"Hook {LABELS['hook'][style['hook']].lower()}, tone {LABELS['tone'][style['tone']].lower()}, "
            f"{EMOJI_WORDS[style['emojis']]}{', in sections' if style['layout'] == 2 else ''}")


def words(style: dict) -> str:
    """The style as a run that writes a post is told it: one line for each slider, then the rule."""
    return ("The owner's post style:\n"
            f"- Hook, {LABELS['hook'][style['hook']]} ({style['hook']} of 5): {HOOK[style['hook']]}\n"
            f"- Tone, {LABELS['tone'][style['tone']]} ({style['tone']} of 5): {TONE[style['tone']]}\n"
            f"- Emojis, {LABELS['emojis'][style['emojis']]}: {EMOJIS[style['emojis']]}\n"
            f"- Layout, {LABELS['layout'][style['layout']]}: {LAYOUT[style['layout']]}\n"
            + RULE)


# What a Restyle asks the writer (skills.REVISIONS["style"]); the style itself follows in the request (words).
RESTYLE = ("Rewrite it in the owner's post style below. Keep every fact, number, date and [blank] as it is, the same topic "
           "and the same point, and add nothing new: change how it opens and how it sounds.")
