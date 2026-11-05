"""A post's rank: how worth posting it is, 1 to 10, so the owner can pick a strong one over a basic one.

Claude ranks a post when asked (the post chat's set_rank, judged by RUBRIC); the owner can put their own number on it.
posts.rank is the number the list sorts drafts by (best first, unranked ones on top); posts.rank_note keeps the reason
and the one change that would lift it, and who gave the number. A rank only informs: nothing is refused for it.
"""
from __future__ import annotations

import json

from .db import loads

MOST_WHY = 300
VERDICTS = {"post": "Worth posting", "strengthen": "Strengthen it first", "drop": "Not worth a post"}
RUBRIC = ("Rank it 1 to 10 for its readers: developers coming up (students, juniors and mid-level), read by seniors too. "
          "Weigh depth most: what a mid-level developer already knows from the docs' first page, a beginner tutorial or "
          "common sense is basic, and generic career or habit advice is basic unless it carries something specific and "
          "earned; a non-obvious mechanism, a production trap or a tradeoff experienced developers still get wrong is "
          "strong. Then correctness (a real error caps it at 4), usefulness (a situation they will meet, something to do "
          "or check, worth saving), credibility (does it make the author look senior) and conversation (would developers "
          "answer its closing question from experience). Use the whole range. 7 to 10: worth posting; 5 or 6: strengthen "
          "it first (say the one change that would lift it); 1 to 4: not worth a post (say why).")


class Refused(ValueError):
    """What was sent is not a rank; the message says why, in the page's words."""


def verdict_of(rank: int) -> str:
    return "post" if rank >= 7 else "strengthen" if rank >= 5 else "drop"


def number(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 10:
        raise Refused("A rank is a whole number from 1 to 10.")
    return value


def note(rank: int, why: str = "", fix: str = "", by: str = "claude") -> str:
    """posts.rank_note for this rank."""
    return json.dumps({"why": " ".join(str(why or "").split())[:MOST_WHY], "fix": " ".join(str(fix or "").split())[:MOST_WHY],
                       "by": by, "verdict": verdict_of(rank)}, ensure_ascii=False)


def public(row) -> dict | None:
    """The rank as the page shows it beside the post, or None when it has none."""
    if row["rank"] is None:
        return None
    kept = loads(row["rank_note"], {}) or {}
    verdict = verdict_of(row["rank"])
    return {"rank": row["rank"], "verdict": verdict, "label": VERDICTS[verdict], "why": kept.get("why") or "",
            "fix": kept.get("fix") or "", "by": kept.get("by") or "you"}
