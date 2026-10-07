"""Turn text into safe HTML for the UI: light Markdown, diffs, friendly times.

Everything here escapes its input first and only then adds its own fixed tags, so text from
Claude, from LinkedIn posts or from the Story Bank can never inject markup.
"""
from __future__ import annotations

import difflib
import html
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from markupsafe import Markup

_CODE = re.compile(r"`([^`\n]+)`")
_BOLD = re.compile(r"\*\*([^*\n]+)\*\*")
_ITALIC = re.compile(r"(?<![*\w])\*([^*\n]+)\*(?![*\w])")
_HEADING = re.compile(r"^(#{1,4})\s+(.*)$")
_BULLET = re.compile(r"^\s*[-*]\s+(.*)$")
_NUMBER = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_TABLE_RULE = re.compile(r"^\|?[\s:|-]+\|[\s:|-]*$")
_SLUG = re.compile(r"[^a-z0-9]+")


def _esc(text: str) -> str:
    return html.escape(text, quote=False)


def _inline(escaped: str) -> str:
    escaped = _CODE.sub(r"<code>\1</code>", escaped)
    escaped = _BOLD.sub(r"<strong>\1</strong>", escaped)
    return _ITALIC.sub(r"<em>\1</em>", escaped)


def slug(text: str) -> str:
    return _SLUG.sub("-", text.lower()).strip("-") or "section"


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def md(text: str | None, anchors: bool = False, breaks: bool = False) -> Markup:
    """Headings, lists, quotes, rules, fenced code, pipe tables, **bold**, *italic*, `code`.

    `breaks=True` keeps single line breaks (chat replies); the default reflows them, which is
    what hard-wrapped files like the Story Bank need.
    """
    lines = (text or "").replace("\r\n", "\n").split("\n")
    out: list[str] = []
    para: list[str] = []
    list_tag: str | None = None
    items: list[str] = []
    quote: list[str] = []
    i = 0

    def joined(parts: list[str]) -> str:
        if breaks:
            return "<br>".join(_inline(_esc(p)) for p in parts)
        return _inline(_esc(" ".join(parts)))

    def flush_para() -> None:
        if para:
            out.append("<p>" + joined(para) + "</p>")
            para.clear()

    def close_list() -> None:
        nonlocal list_tag
        if list_tag:
            out.append(f"<{list_tag}>" + "".join(f"<li>{_inline(_esc(item))}</li>" for item in items)
                       + f"</{list_tag}>")
            list_tag = None
            items.clear()

    def flush_quote() -> None:
        if quote:
            out.append("<blockquote>" + joined(quote) + "</blockquote>")
            quote.clear()

    def close_all() -> None:
        flush_para()
        close_list()
        flush_quote()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```"):
            close_all()
            block: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            out.append("<pre><code>" + _esc("\n".join(block)) + "</code></pre>")
            i += 1
            continue
        if not stripped:
            close_all()
            i += 1
            continue
        heading = _HEADING.match(stripped)
        if heading:
            close_all()
            level = min(len(heading.group(1)) + 2, 6)  # '#' is the document title inside a page: h3
            title = heading.group(2).strip()
            attr = f' id="{slug(title)}"' if anchors else ""
            out.append(f"<h{level}{attr}>{_inline(_esc(title))}</h{level}>")
            i += 1
            continue
        if re.fullmatch(r"[-*_]{3,}", stripped):
            close_all()
            out.append("<hr>")
            i += 1
            continue
        if stripped.startswith("|") and i + 1 < len(lines) and _TABLE_RULE.match(lines[i + 1].strip()):
            close_all()
            head = _cells(stripped)
            rows = []
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(_cells(lines[i]))
                i += 1
            out.append("<div class=\"table-wrap\"><table><thead><tr>"
                       + "".join(f"<th>{_inline(_esc(c))}</th>" for c in head) + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f"<td>{_inline(_esc(c))}</td>" for c in r) + "</tr>" for r in rows)
                       + "</tbody></table></div>")
            continue
        if stripped.startswith(">"):
            flush_para()
            close_list()
            quote.append(stripped.lstrip(">").strip())
            i += 1
            continue
        bullet, number = _BULLET.match(line), _NUMBER.match(line)
        if bullet or number:
            flush_para()
            flush_quote()
            want = "ul" if bullet else "ol"
            if list_tag != want:
                close_list()
                list_tag = want
            items.append((bullet or number).group(1).strip())
            i += 1
            continue
        if list_tag and items and line[:1] in (" ", "\t"):
            items[-1] += " " + stripped  # an indented line continues the item above it
            i += 1
            continue
        close_list()
        flush_quote()
        para.append(stripped)
        i += 1
    close_all()
    return Markup("".join(out))


def wdiff(before: str | None, after: str | None) -> Markup:
    """Word-level comparison: removed words struck through, added words highlighted."""
    a = re.findall(r"\s+|[^\s]+", before or "")
    b = re.findall(r"\s+|[^\s]+", after or "")
    parts: list[str] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            parts.append(_esc("".join(a[i1:i2])))
            continue
        if op in ("delete", "replace"):
            parts.append("<del>" + _esc("".join(a[i1:i2])) + "</del>")
        if op in ("insert", "replace"):
            parts.append("<ins>" + _esc("".join(b[j1:j2])) + "</ins>")
    return Markup("".join(parts))


def udiff(diff_text: str | None) -> Markup:
    """A unified diff with added/removed lines coloured."""
    rows = []
    for line in (diff_text or "").splitlines():
        if line.startswith(("+++", "---")):
            continue
        cls = "hunk" if line.startswith("@@") else "add" if line.startswith("+") else "del" if line.startswith("-") else ""
        rows.append(f'<span class="{cls}">{_esc(line) or " "}</span>')
    return Markup("\n".join(rows))


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
            current = {"title": m.group(1).strip(), "anchor": slug(m.group(1)), "filled": 0, "items": 0}
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
    return sections
