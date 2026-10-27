"""What the page shows, worked out on the server: word-by-word changes, friendly times, a document's sections.

The page draws everything itself from plain text (static/js), never from HTML the server sends, so text
from Claude, from LinkedIn posts or from the Story Bank can never become markup.
"""
from __future__ import annotations

import difflib
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

_BULLET = re.compile(r"^\s*[-*]\s+(.*)$")
_SLUG = re.compile(r"[^a-z0-9]+")


def slug(text: str) -> str:
    return _SLUG.sub("-", text.lower()).strip("-") or "section"


def wdiff(before: str | None, after: str | None) -> list[list[str]]:
    """Word-level comparison as [op, text] pieces: "=" kept, "-" removed, "+" added."""
    a = re.findall(r"\s+|[^\s]+", before or "")
    b = re.findall(r"\s+|[^\s]+", after or "")
    parts: list[list[str]] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            parts.append(["=", "".join(a[i1:i2])])
            continue
        if op in ("delete", "replace"):
            parts.append(["-", "".join(a[i1:i2])])
        if op in ("insert", "replace"):
            parts.append(["+", "".join(b[j1:j2])])
    return parts


def diffstat(diff_text: str | None) -> tuple[int, int]:
    added = removed = 0
    for line in (diff_text or "").splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return added, removed


def parse_utc(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def local_time(value: str | None, tz: ZoneInfo, label: str = "", with_year: bool = False) -> str:
    """`Thu 8 Oct, 8:30 am` in the app's zone."""
    dt = parse_utc(value or "")
    if dt is None:
        return value or ""
    d = dt.astimezone(tz)
    hour = d.hour % 12 or 12
    text = f"{d:%a} {d.day} {d:%b}{f' {d.year}' if with_year else ''}, {hour}:{d:%M} {'am' if d.hour < 12 else 'pm'}"
    return f"{text} {label}".strip()


def clock(value: str | None, tz: ZoneInfo) -> str:
    """`8:30 am` in the app's zone."""
    full = local_time(value, tz)
    return full.split(", ", 1)[1] if ", " in full else full


def ago(value: str | None, tz: ZoneInfo, now: datetime | None = None) -> str:
    dt = parse_utc(value or "")
    if dt is None:
        return ""
    now = now or datetime.now(timezone.utc)
    seconds = (now - dt).total_seconds()
    if seconds < 0:
        return local_time(value, tz)
    if seconds < 45:
        return "just now"
    if seconds < 3600:
        return f"{max(1, round(seconds / 60))} min ago"
    if seconds < 86400:
        return f"{round(seconds / 3600)} h ago"
    days = (now.astimezone(tz).date() - dt.astimezone(tz).date()).days
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    return local_time(value, tz).split(",")[0]


def doc_sections(text: str) -> list[dict]:
    """Numbered `## N. Title` sections of the Story Bank / voice profile, with how much is filled in.

    A list item counts as filled when it holds something other than the template's
    parenthesised hint: `- (role, company, ...)` and `- Emoji: (none / one...)` are empty.
    """
    sections: list[dict] = []
    current: dict | None = None
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        m = re.match(r"^##\s+(\d+\.\s+.*)$", line)
        if m:
            current = {"title": m.group(1).strip(), "anchor": f"doc-{slug(m.group(1))}", "filled": 0, "items": 0, "entries": []}
            sections.append(current)
            continue
        if line.startswith("## "):
            current = None
            continue
        bullet = _BULLET.match(raw)
        if current is not None and bullet:
            item = bullet.group(1).strip()
            label, sep, value = item.partition(":")
            body = value.strip() if sep and len(label) < 48 and not label.startswith("(") else item
            current["items"] += 1
            if body and not body.startswith("("):
                current["filled"] += 1
                current["entries"].append(item)   # the filled ones, as the file has them (Ask me about this)
    return sections
