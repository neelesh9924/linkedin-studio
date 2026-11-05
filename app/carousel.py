"""A post's carousel or card: slides drawn from a small spec in one of several looks, rendered to the PDF LinkedIn shows
as a swipeable document (a carousel) or to one picture (a card), with a PNG of each slide for the page's preview.

The spec is what Claude writes (or the owner edits): a title, a look (LOOKS: how it is drawn; `tint`, one of its TINTS
colourings), a format (carousel: 3-12 slides; card: one slide, posted as a picture) and slides of these kinds:

    cover    {"title", "sub"?, "kicker"?}                                     the post's hook, big
    point    {"title", "text"?, "code"?, "file"?, "mark"?, "numbered"?}       one idea, numbered unless numbered is false;
                                                                              mark = {"kind": trap|fix|check, "text"}
    compare  {"title", "before", "after", "before_label"?, "after_label"?, "mark"?}   two code panels
    code     {"code", "title"?, "kicker"?, "file"?, "note"?}                   one code block, given the whole slide
    grid     {"title", "kicker"?, "sub"?, "cards": [{"title", "tag"?, "items"}], "legend"?}   a cheat sheet of cards
    versus   {"title", "kicker"?, "left": SIDE, "right": SIDE, "foot"?}        the old way against the new, where
             SIDE = {"label", "items" | "code" | "chat" | "tree", "note"?}
    flow     {"title", "kicker"?, "steps": [{"label", "text"?}], "foot"?}     steps in order
    chat     {"title", "kicker"?, "lines": [{"who", "text"}], "note"?}         a conversation ("you" on the right)
    stat     {"number", "title", "text"?, "kicker"?}                           one figure, big
    sheet    {"title", "items"}                                               the summary worth saving
    end      {"question"?, "cta"?}                                            who wrote it and what to do next

In any text, `code` is inline code, ==words== are marked and ~~words~~ struck through. A cover, a stat, a code slide, a
grid and each side of a versus may carry `art`: what ChatGPT should draw there, a character or an object as a sticker
(art_prompt); the studio has it drawn once (draw_art), keeps it beside the post's pictures as art-<hash>.png, and the
spec then names that file, so Redraw and Try another look (next_look) never spend another picture. Every slide is 1080
x 1350 (LinkedIn's 4:5 portrait); one whose words outgrow it is drawn smaller to fit. The words are drawn as text, never
as an image of text, so what Claude wrote is exactly what shows. The slides name nobody unless the owner switched that
on (Settings › You in the preview, Put them on carousels too): then each carries their name, headline and photo.
Rendering uses the Chrome or Edge already on the PC through Playwright (as dev/guide_shots.py does), with the fonts
Windows has; nothing is downloaded. A carousel is kept as its PDF and a PNG of each slide; a card, as its one PNG, a
picture like any other.
"""
from __future__ import annotations

import base64
import hashlib
import html
import re
import tempfile
from pathlib import Path

from . import images, profile
from .db import DB

WIDTH, HEIGHT = 1080, 1350
# The looks, each with what it suits (Claude picks by it, and the studio keeps a post's look unlike the last few).
LOOKS = {
    "midnight": "deep navy, an amber accent and a soft glow: calm and clear",
    "terminal": "black, monospace labels like // comments, a lime accent: code, tools and the command line",
    "blueprint": "black with a faint grid and crosshair marks, code first: how something is built",
    "paper": "warm paper, serif titles, highlighter and red-pen marks: habits, career, explanations",
    "poster": "one bold colour, huge condensed type: a single strong idea, a number, a rule",
}
TINTS = 3                                   # each look's colourings, 0 to 2
FORMATS = ("carousel", "card")
KINDS = ("cover", "point", "compare", "code", "grid", "versus", "flow", "chat", "stat", "sheet", "end")
MARKS = {"trap": "⚠️", "fix": "✅", "check": "🔍"}
MIN_SLIDES, MAX_SLIDES = 3, 12
MONO_ADVANCE = 0.6                          # a monospace character's width, in ems
MAX_ART = 2                                 # pieces of ChatGPT art in one carousel or card
ART_KINDS = ("cover", "stat", "code", "grid")   # and each side of a versus
ART_FILE = re.compile(r"^art-[0-9a-f]{24}\.png$")
# The order Try another look goes through: every look, then every look in its next colouring.
CYCLE = [(look, tint) for tint in range(3) for look in ("midnight", "terminal", "blueprint", "paper", "poster")]
KEYWORDS = frozenset("""
and as assert async await break case catch class const continue data def defer del do elif else enum except export
extends false final finally fn for from fun func go guard if impl import in init interface internal is lambda let match
mut new nil none not null object of open or override package pass private protected pub public raise return select self
sealed static struct suspend super switch this throw throws true try type typealias val var void when where while with
yield None True False SELECT FROM WHERE UPDATE SET INSERT INTO VALUES JOIN ON AND OR NOT NULL ORDER BY GROUP LIMIT
""".split())


class CarouselError(ValueError):
    pass


# ---- the spec, checked ------------------------------------------------------------------------------------------------
def _s(value) -> str:
    return str(value).replace("\r\n", "\n").strip("\n") if value is not None else ""


def _items(value, least: int, most: int, what: str) -> list[str]:
    items = [_s(x).strip() for x in value or [] if _s(x).strip()] if isinstance(value, list) else []
    if not least <= len(items) <= most:
        raise CarouselError(f"{what} needs {least} to {most} items.")
    return items


def _side(value, where: str) -> dict:
    if not isinstance(value, dict) or not _s(value.get("label")):
        raise CarouselError(f"{where} needs a label, and items, code, chat or tree.")
    side = {"label": _s(value["label"]).strip()}
    given = [k for k in ("items", "code", "chat", "tree") if value.get(k)]
    if len(given) != 1:
        raise CarouselError(f"{where} needs one of items, code, chat or tree.")
    if given[0] == "items":
        side["items"] = _items(value["items"], 1, 6, where)
    elif given[0] == "chat":
        side["chat"] = _lines(value["chat"], 1, 6, where)
    else:
        side[given[0]] = _s(value[given[0]])
    if _s(value.get("note")):
        side["note"] = _s(value["note"]).strip()
    if value.get("art"):
        side["art"] = _art(value["art"], where)
    return side


def _art(value, where: str) -> str | dict:
    """A piece of art: what to draw (a prompt, not drawn yet), or {"prompt", "file"} once drawn."""
    if isinstance(value, str) and len(value.split()) >= 3:
        return " ".join(value.split())[:600]
    if isinstance(value, dict) and ART_FILE.match(str(value.get("file") or "")):
        return {"prompt": " ".join(_s(value.get("prompt")).split())[:600], "file": value["file"]}
    raise CarouselError(f"{where}'s art says what to draw, in a few words (a character or an object).")


def _lines(value, least: int, most: int, where: str) -> list[dict]:
    lines = [{"who": _s(x.get("who")).strip() or "them", "text": _s(x.get("text")).strip()}
             for x in value or [] if isinstance(x, dict) and _s(x.get("text")).strip()] if isinstance(value, list) else []
    if not least <= len(lines) <= most:
        raise CarouselError(f"{where} needs {least} to {most} lines, each with who and text.")
    return lines


def check(spec: dict) -> dict:
    """The spec, cleaned: a known look and format, known kinds with the fields each needs, strings only. Raises
    CarouselError naming what's wrong."""
    if not isinstance(spec, dict):
        raise CarouselError("A carousel is an object with a title and slides.")
    title = _s(spec.get("title")).strip()
    slides = spec.get("slides")
    if not title:
        raise CarouselError("Give the carousel a title: LinkedIn shows it above the document.")
    look = spec.get("look") or "midnight"
    if look not in LOOKS:
        raise CarouselError(f"The look is one of {', '.join(LOOKS)}.")
    tint = spec.get("tint", 0)
    if isinstance(tint, bool) or not isinstance(tint, int) or not 0 <= tint < TINTS:
        raise CarouselError(f"The tint is a whole number from 0 to {TINTS - 1}.")
    form = spec.get("format") or "carousel"
    if form not in FORMATS:
        raise CarouselError(f"The format is {' or '.join(FORMATS)}.")
    if form == "card" and (not isinstance(slides, list) or len(slides) != 1):
        raise CarouselError("A card is one slide.")
    if form == "carousel" and (not isinstance(slides, list) or not MIN_SLIDES <= len(slides) <= MAX_SLIDES):
        raise CarouselError(f"A carousel has {MIN_SLIDES} to {MAX_SLIDES} slides.")
    clean = []
    for i, slide in enumerate(slides, 1):
        if not isinstance(slide, dict) or slide.get("kind") not in KINDS:
            raise CarouselError(f"Slide {i} needs a kind: one of {', '.join(KINDS)}.")
        kind, where = slide["kind"], f"Slide {i} ({slide['kind']})"
        s = {"kind": kind}
        for key in ("title", "sub", "kicker", "text", "code", "file", "before", "after", "before_label", "after_label",
                    "question", "cta", "note", "foot", "legend", "number"):
            if _s(slide.get(key)):
                s[key] = _s(slide[key])
        if kind in ("cover", "point", "compare", "grid", "versus", "flow", "chat", "stat", "sheet") and not s.get("title"):
            raise CarouselError(f"{where} needs a title.")
        if kind == "compare" and not (s.get("before") and s.get("after")):
            raise CarouselError(f"{where} needs both before and after.")
        if kind == "code" and not s.get("code"):
            raise CarouselError(f"{where} needs its code.")
        if kind == "stat" and not s.get("number"):
            raise CarouselError(f"{where} needs its number.")
        if kind == "sheet":
            s["items"] = _items(slide.get("items"), 2, 6, where)
        if kind == "grid":
            cards = slide.get("cards") if isinstance(slide.get("cards"), list) else []
            if not 2 <= len(cards) <= 6:
                raise CarouselError(f"{where} needs 2 to 6 cards.")
            s["cards"] = []
            for n, card in enumerate(cards, 1):
                if not isinstance(card, dict) or not _s(card.get("title")):
                    raise CarouselError(f"{where}'s card {n} needs a title and items.")
                s["cards"].append({"title": _s(card["title"]).strip(), "tag": _s(card.get("tag")).strip(),
                                   "items": _items(card.get("items"), 1, 5, f"{where}'s card {n}")})
        if kind == "versus":
            s["left"], s["right"] = _side(slide.get("left"), f"{where}'s left"), _side(slide.get("right"), f"{where}'s right")
        if kind == "flow":
            steps = slide.get("steps") if isinstance(slide.get("steps"), list) else []
            s["steps"] = [{"label": _s(x.get("label")).strip(), "text": _s(x.get("text")).strip()}
                          for x in steps if isinstance(x, dict) and _s(x.get("label")).strip()]
            if not 2 <= len(s["steps"]) <= 5:
                raise CarouselError(f"{where} needs 2 to 5 steps, each with a label.")
        if kind == "chat":
            s["lines"] = _lines(slide.get("lines"), 2, 8, where)
        if kind == "point" and slide.get("numbered") is False:
            s["numbered"] = False
        mark = slide.get("mark")
        if mark is not None:
            if not isinstance(mark, dict) or mark.get("kind") not in MARKS or not _s(mark.get("text")).strip():
                raise CarouselError(f"{where}'s mark needs a kind ({', '.join(MARKS)}) and text.")
            s["mark"] = {"kind": mark["kind"], "text": _s(mark["text"]).strip()}
        if form == "card" and kind == "end":
            raise CarouselError("A card is one slide that teaches: not an end slide.")
        if slide.get("art"):
            if kind not in ART_KINDS:
                raise CarouselError(f"{where} can't carry art: a {', '.join(ART_KINDS)} slide or a versus side can.")
            s["art"] = _art(slide["art"], where)
        clean.append(s)
    spec = {"title": title[:200], "look": look, "tint": tint, "format": form, "slides": clean}
    if len(_arts(spec)) > MAX_ART:
        raise CarouselError(f"At most {MAX_ART} pieces of art in one {form}: each is a ChatGPT picture.")
    return spec


def _arts(spec: dict) -> list[tuple[dict, str]]:
    """Where the spec's art is: (the dict holding it, its key), in slide order."""
    found = []
    for s in spec["slides"]:
        if s.get("art"):
            found.append((s, "art"))
        for side in (s.get("left"), s.get("right")):
            if isinstance(side, dict) and side.get("art"):
                found.append((side, "art"))
    return found


def art_files(spec: dict) -> list[str]:
    """The art files a spec names, once drawn."""
    return [holder[key]["file"] for holder, key in _arts(spec) if isinstance(holder[key], dict)]


def art_subjects(spec: dict) -> list[str]:
    """The art not drawn yet: what each piece is to show."""
    return [holder[key] for holder, key in _arts(spec) if isinstance(holder[key], str)]


def drop_art(spec: dict) -> dict:
    """The spec without the art it has not drawn yet (ChatGPT can't draw it here)."""
    for holder, key in _arts(spec):
        if isinstance(holder[key], str):
            del holder[key]
    return spec


WORDLESS = {"look", "tint", "format", "kind", "art", "numbered", "who"}   # a spec's keys whose values are not its words
CODE_KEYS = {"code", "before", "after", "tree"}                         # code keeps its == and ~~: they are code there


def words_of(spec: dict) -> str:
    """A carousel's or card's words, a line a piece, its marks gone (==, ~~): what a search looks in (api_posts:
    /api/search), never its look or what its art was drawn from."""
    out: list[str] = []

    def walk(value, key=""):
        if key in WORDLESS:
            return
        if isinstance(value, str):
            out.append(value if key in CODE_KEYS else value.replace("==", "").replace("~~", ""))
        elif isinstance(value, list):
            for v in value:
                walk(v, key)
        elif isinstance(value, dict):
            for k, v in value.items():
                walk(v, k)

    walk(spec if isinstance(spec, dict) else {})
    return "\n".join(x.strip() for x in out if x.strip())


def art_prompt(subject: str) -> str:
    """What ChatGPT is asked for one piece of slide art: the subject, as a sticker that sits on any look."""
    return ("A small flat vector sticker illustration, like an emoji-style character: one subject, centered, bold simple "
            "shapes, clean thick outlines, a limited friendly palette, soft flat shading, on a fully transparent "
            f"background with nothing else in the frame and no text. The subject: {subject}")


def draw_art(spec: dict, folder: Path, make_art) -> tuple[dict, list[str]]:
    """Each piece of art not drawn yet, drawn with make_art(subject) -> PNG bytes and kept in `folder` as
    art-<hash>.png (the same picture is kept once). (the spec naming the files, what went wrong): a piece that could not
    be drawn is left out of its slide, and said why."""
    said = []
    for holder, key in _arts(spec):
        subject = holder[key]
        if isinstance(subject, dict):
            continue
        try:
            data = make_art(subject)
        except Exception as exc:  # noqa: BLE001 - the carousel is still drawn, without this piece
            said.append(f"no art for “{subject[:60]}”: {exc}")
            del holder[key]
            continue
        name = f"art-{hashlib.sha256(data).hexdigest()[:24]}.png"
        folder.mkdir(parents=True, exist_ok=True)
        if not (folder / name).is_file():
            (folder / name).write_bytes(data)
        holder[key] = {"prompt": subject, "file": name}
    return spec, said


def next_look(spec: dict) -> dict:
    """The same slides in the next look of CYCLE (Try another look)."""
    at = CYCLE.index((spec["look"], spec["tint"])) if (spec["look"], spec["tint"]) in CYCLE else -1
    look, tint = CYCLE[(at + 1) % len(CYCLE)]
    return {**spec, "look": look, "tint": tint}


# ---- words ---------------------------------------------------------------------------------------------------------------
def _marks(escaped: str) -> str:
    escaped = re.sub(r"==([^=\n]+?)==", r'<mark class="hl">\1</mark>', escaped)
    return re.sub(r"~~([^~\n]+?)~~", r'<s class="strike">\1</s>', escaped)


def _e(text: str) -> str:
    """Escaped, with `code` spans as inline code, ==marked== and ~~struck~~ words (never inside code)."""
    out = []
    for n, part in enumerate(re.split(r"(`[^`\n]+`)", text)):
        if n % 2:
            out.append(f'<code class="inline">{html.escape(part[1:-1], quote=False)}</code>')
        else:
            out.append(_marks(html.escape(part, quote=False)))
    return "".join(out)


_TOKEN = re.compile(r"(?P<c>(?:^|(?<=\s))(?:#|//|--)(?:\s|$)[^\n]*|/\*.*?\*/)"
                    r"|(?P<s>\"(?:\\.|[^\"\\\n])*\"|'(?:\\.|[^'\\\n])*')"
                    r"|(?P<n>\b\d[\d_]*(?:\.\d+)?\b)"
                    r"|(?P<w>[A-Za-z_][A-Za-z0-9_]*)")


def _highlight(line: str) -> str:
    """One line of code with its comments, strings, numbers, keywords, types and calls in spans of their own."""
    out, at = [], 0
    for m in _TOKEN.finditer(line):
        out.append(html.escape(line[at:m.start()], quote=False))
        token = html.escape(m.group(), quote=False)
        if m.lastgroup == "w":
            word = m.group()
            cls = ("k" if word in KEYWORDS else "f" if line[m.end():m.end() + 1] == "(" else
                   "t" if word[:1].isupper() else "")
        else:
            cls = m.lastgroup
        out.append(f'<span class="{cls}">{token}</span>' if cls else token)
        at = m.end()
    out.append(html.escape(line[at:], quote=False))
    return "".join(out)


CODE_PAD = 2 * 36 + 4                       # a code panel's padding and border, left and right together


def _code(code: str, box: int, file: str = "", numbers: bool = False, big: bool = False) -> str:
    """A code panel `box` pixels wide: its font as large as the longest line allows without wrapping, coloured; a
    file's name as a tab over it, and line numbers, when asked."""
    lines = code.split("\n")
    longest = max((len(line) for line in lines), default=1) + (4.4 if numbers else 0)   # the numbers' gutter: 2.6em
    top = 36 if big else 31
    fits = int((box - CODE_PAD) / (MONO_ADVANCE * max(longest, 1)))
    size = max(18, min(top, fits))
    rows = "".join(f'<span class="ln">{n}</span>{_highlight(line)}\n' if numbers else f"{_highlight(line)}\n"
                   for n, line in enumerate(lines, 1))
    tab = (f'<div class="tab"><i></i><i></i><i></i><span>{html.escape(file, quote=False)}</span></div>' if file else "")
    wrap = " wrap" if fits < 18 else ""        # a line too long even at the smallest size wraps; any other never does
    return (f'<div class="codebox{" numbered" if numbers else ""}">{tab}'
            f'<pre class="code{wrap}" style="font-size:{size}px">{rows.rstrip()}</pre></div>')


def _initials(name: str) -> str:
    parts = [p for p in re.split(r"\s+", name.strip()) if p]
    return "".join(p[0] for p in parts[:2]).upper() or "·"


def _head(author: dict, n: int, total: int, card: bool) -> str:
    name = html.escape(author.get("name") or "")
    line = html.escape(author.get("line") or "")
    photo = author.get("photo_uri")
    avatar = (f'<img class="avatar" src="{photo}" alt="">' if photo
              else f'<div class="avatar">{html.escape(_initials(name))}</div>' if name else "")   # no one named: no badge
    who = f'<div class="who"><b>{name}</b><span>{line}</span></div>' if name else ""
    count = "" if card else f'<div class="count">{n:02d}<span>/{total:02d}</span></div>'
    return f'<header>{avatar}{who}{count}</header>' if (avatar or count) else ""


def _mark(mark: dict | None) -> str:
    if not mark:
        return ""
    return f'<div class="mark {mark["kind"]}"><span>{MARKS[mark["kind"]]}</span><p>{_e(mark["text"])}</p></div>'


def _kicker(s: dict) -> str:
    return f'<div class="kicker">{_e(s["kicker"])}</div>' if s.get("kicker") else ""


def _art_html(art, where: Path | None, size: str = "") -> str:
    """A drawn piece of art, from its file beside the post's pictures; nothing while it isn't drawn or isn't there."""
    path = where / art["file"] if isinstance(art, dict) and where is not None else None
    if path is None or not path.is_file():
        return ""
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f'<figure class="art {size}"><img src="data:image/png;base64,{data}" alt=""></figure>'


# ---- the slides -------------------------------------------------------------------------------------------------------
INNER = WIDTH - 2 * 88                      # a slide's width inside its margins
PANEL_PAD = 2 * 30 + 4                      # a versus panel's padding and border, left and right together


def _side_html(side: dict, good: bool, width: int, where: Path | None) -> str:
    if side.get("items"):
        body = "<ul>" + "".join(f"<li>{_e(x)}</li>" for x in side["items"]) + "</ul>"
    elif side.get("chat"):
        body = '<div class="bubbles">' + "".join(
            f'<p class="bubble{" mine" if line["who"].lower() in ("you", "me") else ""}">{_e(line["text"])}</p>'
            for line in side["chat"]) + "</div>"
    elif side.get("tree"):
        body = f'<pre class="tree">{html.escape(side["tree"], quote=False)}</pre>'
    else:
        body = _code(side["code"], width - PANEL_PAD)
    note = f'<p class="note">{_e(side["note"])}</p>' if side.get("note") else ""
    return (f'<div class="panel {"good" if good else "bad"}"><div class="label">{MARKS["fix" if good else "trap"]} '
            f'{_e(side["label"])}</div>{body}{note}{_art_html(side.get("art"), where, "small")}</div>')


def _card(c: dict) -> str:
    tag = f'<em>{_e(c["tag"])}</em>' if c["tag"] else ""
    items = "".join(f"<li>{_e(x)}</li>" for x in c["items"])
    return f'<div class="card"><div class="card-head"><b>{_e(c["title"])}</b>{tag}</div><ul>{items}</ul></div>'


def _step(i: int, x: dict) -> str:
    text = f'<p>{_e(x["text"])}</p>' if x["text"] else ""
    return f'<li><span class="step">{i}</span><div><b>{_e(x["label"])}</b>{text}</div></li>'


def _slide(s: dict, n: int, total: int, author: dict, number: int, card: bool, where: Path | None) -> str:
    kind = s["kind"]
    if kind == "cover":
        sub = f'<p class="sub">{_e(s["sub"])}</p>' if s.get("sub") else ""
        size = 92 if len(s["title"]) <= 60 else 80 if len(s["title"]) <= 90 else 70
        swipe = "" if card else '<div class="swipe">Swipe <span>→</span></div>'
        art = _art_html(s.get("art"), where, "cover-art")
        body = f'<div class="main cover">{_kicker(s)}<h1 style="--size:{size}px">{_e(s["title"])}</h1>{sub}{art}</div>{swipe}'
    elif kind == "point":
        text = f'<p class="text">{_e(s["text"])}</p>' if s.get("text") else ""
        code = _code(s["code"], INNER, s.get("file", "")) if s.get("code") else ""
        badge = f'<div class="badge">{number:02d}</div>' if s.get("numbered", True) else ""
        body = f'<div class="main">{badge}<h2>{_e(s["title"])}</h2>{text}{code}{_mark(s.get("mark"))}</div>'
    elif kind == "compare":
        before, after = s.get("before_label") or "Before", s.get("after_label") or "After"
        body = (f'<div class="main"><h2>{_e(s["title"])}</h2>'
                f'<div class="side trap"><div class="label">{MARKS["trap"]} {_e(before)}</div>{_code(s["before"], INNER)}</div>'
                f'<div class="side fix"><div class="label">{MARKS["fix"]} {_e(after)}</div>{_code(s["after"], INNER)}</div>'
                f'{_mark(s.get("mark"))}</div>')
    elif kind == "code":
        title = f'<h2>{_e(s["title"])}</h2>' if s.get("title") else ""
        note = f'<p class="code-note">{_e(s["note"])}</p>' if s.get("note") else ""
        body = (f'<div class="main code-slide">{_kicker(s)}{title}{_code(s["code"], INNER, s.get("file", ""), True, True)}'
                f'{note}{_art_html(s.get("art"), where)}</div>')
    elif kind == "grid":
        cards = "".join(_card(c) for c in s["cards"])
        sub = f'<p class="sub">{_e(s["sub"])}</p>' if s.get("sub") else ""
        legend = f'<p class="legend">{_e(s["legend"])}</p>' if s.get("legend") else ""
        body = (f'<div class="main grid-slide">{_kicker(s)}<h2>{_e(s["title"])}</h2>{sub}'
                f'<div class="cards n{len(s["cards"])}">{cards}</div>{legend}{_art_html(s.get("art"), where, "small")}</div>')
    elif kind == "versus":
        split = not any(side.get("code") or side.get("tree") for side in (s["left"], s["right"]))
        width = (INNER - 28) // 2 if split else INNER
        foot = f'<p class="foot">{_e(s["foot"])}</p>' if s.get("foot") else ""
        body = (f'<div class="main versus">{_kicker(s)}<h2>{_e(s["title"])}</h2>'
                f'<div class="panels {"split" if split else "stack"}">{_side_html(s["left"], False, width, where)}'
                f'{_side_html(s["right"], True, width, where)}</div>{foot}</div>')
    elif kind == "flow":
        steps = "".join(_step(i, x) for i, x in enumerate(s["steps"], 1))
        foot = f'<p class="foot">{_e(s["foot"])}</p>' if s.get("foot") else ""
        body = f'<div class="main flow">{_kicker(s)}<h2>{_e(s["title"])}</h2><ol class="steps">{steps}</ol>{foot}</div>'
    elif kind == "chat":
        bubbles = "".join(f'<div class="say{" mine" if x["who"].lower() in ("you", "me") else ""}"><small>{_e(x["who"])}'
                          f'</small><p class="bubble">{_e(x["text"])}</p></div>' for x in s["lines"])
        note = f'<p class="foot">{_e(s["note"])}</p>' if s.get("note") else ""
        body = f'<div class="main chat">{_kicker(s)}<h2>{_e(s["title"])}</h2><div class="talk">{bubbles}</div>{note}</div>'
    elif kind == "stat":
        text = f'<p class="text">{_e(s["text"])}</p>' if s.get("text") else ""
        body = (f'<div class="main stat">{_kicker(s)}<div class="number">{_e(s["number"])}</div>'
                f'<h2>{_e(s["title"])}</h2>{text}{_art_html(s.get("art"), where)}</div>')
    elif kind == "sheet":
        items = "".join(f'<li><span class="tick">{i}</span><span>{_e(x)}</span></li>' for i, x in enumerate(s["items"], 1))
        body = (f'<div class="main sheet"><div class="kicker">{_e(s.get("kicker") or "Save this")}</div>'
                f'<h2>{_e(s["title"])}</h2><ol>{items}</ol></div>')
    else:   # end
        name = html.escape(author.get("name") or "")
        q = f'<h2 class="question">{_e(s["question"])}</h2>' if s.get("question") else ""
        cta = _e(s.get("cta") or "Found it useful? Save it for later 🔖")
        follow = f'<p class="follow">Follow <b>{name}</b> for more notes like this</p>' if name else ""
        body = f'<div class="main end">{q}<p class="cta">{cta}</p>{follow}</div>'
    bar = "" if card else f'<div class="bar"><i style="width:{n / total * 100:.1f}%"></i></div>'
    # k-<kind>, not <kind>: a slide of kind "code" is not a .code block (4 Nov 2026: the whole slide went monospace)
    return f'<section class="slide k-{kind}">{_head(author, n, total, card)}{body}{bar}</section>'


# ---- how each look draws them ---------------------------------------------------------------------------------------------
CSS = """
@page { size: 1080px 1350px; margin: 0 }
* { box-sizing: border-box; margin: 0; padding: 0 }
html, body { background: var(--bg) }
body { font-family: var(--text-font); color: var(--ink); -webkit-print-color-adjust: exact; print-color-adjust: exact;
       --text-font: "Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif, "Segoe UI Emoji";
       --display: "Segoe UI Variable Display", "Segoe UI", sans-serif, "Segoe UI Emoji";
       --mono: "Cascadia Mono", "Cascadia Code", Consolas, monospace;
       --label-font: var(--text-font) }
.slide { width: 1080px; height: 1350px; position: relative; overflow: hidden; padding: 84px 88px 96px;
         display: flex; flex-direction: column; break-after: page; page-break-after: always; background: var(--slide-bg) }
.slide:last-child { break-after: auto; page-break-after: auto }
header { display: flex; align-items: center; gap: 22px; height: 72px; flex: none }
.avatar { width: 72px; height: 72px; border-radius: 50%; background: var(--accent); color: var(--accent-ink); display: grid;
          place-items: center; font: 700 28px var(--display); object-fit: cover }
.who { display: flex; flex-direction: column; line-height: 1.25 }
.who b { font-size: 29px; font-weight: 600 }
.who span { font-size: 23px; color: var(--muted) }
.count { margin-left: auto; font: 600 30px var(--label-font); color: var(--ink); letter-spacing: 1px }
.count span { color: var(--faint) }
.main { flex: 1; display: flex; flex-direction: column; justify-content: center; gap: 30px; min-height: 0 }
h1, h2 { font-family: var(--display); font-weight: 700; letter-spacing: -0.5px; color: var(--ink) }
h1 { font-size: var(--size); line-height: 1.06 }
h2 { font-size: 60px; line-height: 1.12 }
.kicker { font: 700 26px var(--label-font); letter-spacing: 3px; text-transform: uppercase; color: var(--accent) }
.sub { font-size: 38px; line-height: 1.35; color: var(--soft) }
.text { font-size: 40px; line-height: 1.4; color: var(--soft) }
mark.hl { background: none; color: var(--accent) }
s.strike { color: var(--faint); text-decoration: line-through; text-decoration-color: var(--bad); text-decoration-thickness: 5px }
.badge { width: 92px; height: 92px; border-radius: 26px; background: var(--accent); color: var(--accent-ink); display: grid;
         place-items: center; font: 800 40px var(--display) }
/* never squeezed: a slide too full for its size is drawn smaller (FIT), its code whole (4 Nov 2026: cut to a line) */
.codebox { border-radius: 24px; background: var(--panel); border: 2px solid var(--line); overflow: hidden; flex-shrink: 0 }
.tab { display: flex; align-items: center; gap: 10px; padding: 16px 24px; border-bottom: 2px solid var(--line);
       font: 500 24px var(--mono); color: var(--muted) }
.tab i { width: 14px; height: 14px; border-radius: 50%; background: var(--line) }
.tab span { margin-left: 10px }
.code { font-family: var(--mono); font-variant-ligatures: none; line-height: 1.5; color: var(--code-ink, var(--ink));
        padding: 30px 36px; white-space: pre; overflow: hidden }
.code.wrap { white-space: pre-wrap; word-break: break-word }
.code .ln { display: inline-block; width: 2.6em; color: var(--faint); user-select: none }
.code .k { color: var(--sk) } .code .s { color: var(--ss) } .code .c { color: var(--sc); font-style: italic }
.code .n { color: var(--sn) } .code .f { color: var(--sf) } .code .t { color: var(--st) }
code.inline { font-family: var(--mono); font-variant-ligatures: none; font-size: .86em; color: var(--inline-ink);
              background: var(--panel); border-radius: 10px; padding: 2px 12px }
.mark { display: flex; gap: 22px; align-items: flex-start; border-left: 8px solid; border-radius: 6px;
        padding: 18px 0 18px 26px; background: var(--mark-bg) }
.mark span { font-size: 40px; line-height: 1.3 }
.mark p { font-size: 36px; line-height: 1.38 }
.mark.trap { border-color: var(--bad) } .mark.fix { border-color: var(--good) } .mark.check { border-color: var(--info) }
.side { display: flex; flex-direction: column; gap: 14px }
.label { font: 700 30px var(--label-font) }
.side.trap .label, .panel.bad .label { color: var(--bad) } .side.fix .label, .panel.good .label { color: var(--good) }
.sheet ol { list-style: none; display: flex; flex-direction: column; gap: 26px }
.sheet li { display: flex; gap: 26px; align-items: flex-start; font-size: 38px; line-height: 1.35;
            background: var(--panel); border: 2px solid var(--line); border-radius: 22px; padding: 22px 28px }
.tick { flex: none; width: 54px; height: 54px; border-radius: 50%; background: var(--good); color: var(--accent-ink);
        display: grid; place-items: center; font: 800 28px var(--label-font); margin-top: 1px }
.end { gap: 40px }
.question { font-size: 64px }
.cta { font-size: 42px; color: var(--accent); line-height: 1.35 }
.follow { font-size: 34px; color: var(--muted) }
.follow b { color: var(--ink) }
.swipe { align-self: flex-start; font: 600 32px var(--label-font); color: var(--accent-ink); background: var(--accent);
         border-radius: 999px; padding: 16px 34px; flex: none }
.swipe span { margin-left: 8px }
.bar { position: absolute; left: 88px; right: 88px; bottom: 48px; height: 8px; border-radius: 8px; background: var(--line) }
.bar i { display: block; height: 100%; border-radius: 8px; background: var(--accent) }
/* a cheat sheet of cards */
.grid-slide { gap: 26px; justify-content: flex-start; padding-top: 10px }
.cards { display: grid; grid-template-columns: 1fr 1fr; gap: 22px }
.cards.n3 .card:last-child, .cards.n5 .card:last-child { grid-column: 1 / -1 }
.card { background: var(--panel); border: 2px solid var(--line); border-radius: 22px; padding: 24px 26px;
        display: flex; flex-direction: column; gap: 14px }
.card-head { display: flex; align-items: center; gap: 12px }
.card-head b { font: 700 34px var(--display); line-height: 1.15; flex: 1 }
.card-head em { font: 700 18px var(--label-font); font-style: normal; letter-spacing: 1.5px; text-transform: uppercase;
                color: var(--accent); border: 2px solid var(--accent); border-radius: 999px; padding: 4px 12px }
.card ul, .panel ul { list-style: none; display: flex; flex-direction: column; gap: 10px }
.card li, .panel li { font-size: 27px; line-height: 1.32; color: var(--soft); padding-left: 26px; position: relative }
.card li::before, .panel li::before { content: ""; position: absolute; left: 0; top: .5em; width: 11px; height: 11px;
                                       border-radius: 3px; background: var(--accent) }
.legend { font-size: 24px; color: var(--muted) }
/* the old way against the new */
.versus { gap: 28px }
.panels { display: grid; gap: 28px }
.panels.split { grid-template-columns: 1fr 1fr }
.panel { background: var(--panel); border: 2px solid var(--line); border-radius: 26px; padding: 28px 30px;
         display: flex; flex-direction: column; gap: 18px }
.panel.good { border-color: var(--good) }
.panel .codebox { border-radius: 16px }
.panel .note { font-size: 28px; line-height: 1.35; color: var(--soft) }
.panel.bad .note { color: var(--bad) } .panel.good .note { color: var(--good) }
.bubbles { display: flex; flex-direction: column; gap: 12px }
.bubble { font-size: 28px; line-height: 1.3; background: var(--bubble); border-radius: 20px; padding: 14px 20px;
          align-self: flex-start; max-width: 92% }
.bubble.mine, .say.mine .bubble { align-self: flex-end; background: var(--accent); color: var(--accent-ink) }
.tree { font: 28px/1.55 var(--mono); color: var(--ink); white-space: pre }
.foot { font: 600 28px var(--label-font); color: var(--muted) }
/* steps */
.steps { list-style: none; display: flex; flex-direction: column; gap: 22px; position: relative }
.steps li { display: flex; gap: 26px; align-items: flex-start }
.step { flex: none; width: 76px; height: 76px; border-radius: 50%; display: grid; place-items: center;
        background: var(--accent); color: var(--accent-ink); font: 800 34px var(--display) }
.steps b { display: block; font: 700 40px var(--display); line-height: 1.2 }
.steps p { font-size: 30px; line-height: 1.38; color: var(--soft); margin-top: 6px }
/* a conversation */
.talk { display: flex; flex-direction: column; gap: 18px }
.say { display: flex; flex-direction: column; gap: 6px; align-items: flex-start }
.say.mine { align-items: flex-end }
.say small { font: 600 22px var(--label-font); color: var(--muted); text-transform: uppercase; letter-spacing: 2px }
.say .bubble { font-size: 32px; max-width: 86% }
/* one figure */
.stat .number { font: 800 220px/1 var(--display); color: var(--accent); letter-spacing: -6px; white-space: nowrap }
/* one code block */
.code-slide { gap: 26px }
.code-note { font-size: 34px; line-height: 1.38; color: var(--soft) }
/* ChatGPT's art: a sticker, at the foot of what it belongs to; cut to its drawing first (CROP), which fills its box */
.art { display: flex; justify-content: flex-end; align-items: flex-end; flex: none }
.art img { width: 300px; height: 300px; object-fit: contain; object-position: right bottom; border-radius: 30px;
           filter: drop-shadow(0 18px 28px rgba(0,0,0,.35)) }
.art.cover-art img { width: 380px; height: 380px }
.art.small img { width: 240px; height: 240px; border-radius: 22px }
.art.cut img { border-radius: 0 }   /* cut to its drawing, rounded corners would cut into it */
.panel .art { margin-top: auto }
.look-paper .art { padding: 10px 22px }   /* its tilt stays inside the slide, so the fit never takes it for words */
.look-paper .art img { transform: rotate(-3deg); filter: drop-shadow(0 12px 18px rgba(80,60,20,.22)) }
.look-poster .art img { filter: none }

/* ---- midnight: deep navy, amber, a soft glow ---- */
body.look-midnight { --bg: #0d1321; --slide-bg: radial-gradient(1200px 700px at 100% 0%, #1a2540 0%, #0d1321 60%);
  --ink: #eef2f8; --soft: #c3cede; --muted: #9aa8bf; --faint: #66748f; --accent: #ffb547; --accent-ink: #0d1321;
  --panel: #111a2e; --line: #24304a; --bubble: #1b2640; --mark-bg: rgba(255,255,255,.03); --inline-ink: #ffd38a;
  --good: #4ade9b; --bad: #ff7b7b; --info: #6cb6ff;
  --sk: #ff9bb5; --ss: #a6e3a1; --sc: #6c7a96; --sn: #ffcf70; --sf: #8ec5ff; --st: #f5c2e7 }
body.look-midnight.tint-1 { --accent: #ff7a6b; --inline-ink: #ffb0a6; --slide-bg: radial-gradient(1200px 700px at 0% 0%, #2a1d33 0%, #0d1321 62%) }
body.look-midnight.tint-2 { --accent: #5eead4; --inline-ink: #99f6e4; --slide-bg: radial-gradient(1200px 800px at 50% 110%, #12313a 0%, #0d1321 60%) }

/* ---- terminal: black, monospace labels, lime ---- */
body.look-terminal { --bg: #0a0a0b; --slide-bg: #0a0a0b; --ink: #ececea; --soft: #c2c2bd; --muted: #8c8c86; --faint: #5a5a55;
  --accent: #c6f432; --accent-ink: #0a0a0b; --panel: #131315; --line: #29292c; --bubble: #1c1c1f;
  --mark-bg: #121214; --inline-ink: #c6f432; --good: #c6f432; --bad: #ff6b6b; --info: #7cc4ff;
  --label-font: var(--mono); --sk: #ff7eb6; --ss: #c6f432; --sc: #5f5f5a; --sn: #ffb86b; --sf: #7cc4ff; --st: #f2f2a0 }
body.look-terminal.tint-1 { --accent: #4fd6ff; --good: #4fd6ff; --inline-ink: #4fd6ff; --ss: #9ef0ff }
body.look-terminal.tint-2 { --accent: #ff7eb6; --good: #7ee787; --inline-ink: #ff9fcb; --sk: #c6f432 }
.look-terminal .kicker { letter-spacing: 1px; font-weight: 600 }
.look-terminal .kicker::before { content: "// " }
.look-terminal .cover h1::after { content: "▍"; color: var(--accent); margin-left: 6px; font-weight: 400 }
.look-terminal .swipe, .look-terminal .badge, .look-terminal .step { border-radius: 10px }
.look-terminal .sheet li::before { content: "$"; color: var(--accent); font-family: var(--mono) }
.look-terminal .tick { display: none }
.look-terminal .mark { border-left-width: 4px; border-radius: 0 }
.look-terminal .card, .look-terminal .panel, .look-terminal .sheet li, .look-terminal .codebox { border-radius: 14px }

/* ---- blueprint: black, a faint grid and crosshairs, code first ---- */
body.look-blueprint { --bg: #050506; --ink: #f3f4f6; --soft: #c9ccd3; --muted: #8b909b; --faint: #565b66;
  --slide-bg: linear-gradient(rgba(255,255,255,.055) 1px, transparent 1px) 0 0 / 54px 54px,
              linear-gradient(90deg, rgba(255,255,255,.055) 1px, transparent 1px) 0 0 / 54px 54px, #050506;
  --accent: #7dd3fc; --accent-ink: #050506; --panel: rgba(12,13,16,.92); --line: #2a2d35; --bubble: #15171c;
  --mark-bg: rgba(255,255,255,.02); --inline-ink: #7dd3fc; --good: #6ee7b7; --bad: #fb7185; --info: #7dd3fc;
  --label-font: var(--mono); --sk: #ff6b8a; --ss: #9be37a; --sc: #5d6370; --sn: #fbbf6a; --sf: #7dd3fc; --st: #e9d5ff }
body.look-blueprint.tint-1 { --accent: #fbbf24; --inline-ink: #fcd34d; --sf: #fbbf24 }
body.look-blueprint.tint-2 { --accent: #f472b6; --inline-ink: #f9a8d4 }
.look-blueprint .slide::before, .look-blueprint .slide::after { content: "+"; position: absolute; font: 300 64px/1 var(--mono);
  color: rgba(255,255,255,.28) }
.look-blueprint .slide::before { left: 40px; top: 30px }
.look-blueprint .slide::after { right: 40px; bottom: 74px }
.look-blueprint .kicker { letter-spacing: 2px }
.look-blueprint .codebox { background: #000; border-color: #23262d }
.look-blueprint .swipe { background: transparent; color: var(--accent); border: 2px solid var(--accent) }

/* ---- paper: warm paper, serif, highlighter and red pen ---- */
body.look-paper { --bg: #f5efe2; --slide-bg: radial-gradient(1400px 900px at 30% 0%, #fbf7ee 0%, #f5efe2 55%, #efe6d3 100%);
  --ink: #1f1b16; --soft: #3f3a33; --muted: #6c6457; --faint: #a39a8a; --accent: #d9480f; --accent-ink: #fffdf7;
  --panel: #fffdf6; --line: #e4dac5; --bubble: #fffdf6; --mark-bg: #fffdf6; --inline-ink: #b03a0b; --hl: #ffe066;
  --good: #2b8a3e; --bad: #e03131; --info: #1c7ed6; --code-ink: #2b2620;
  --display: "Sitka Heading", "Sitka Text", Georgia, serif; --label-font: "Segoe UI Variable Text", "Segoe UI", sans-serif;
  --sk: #c2255c; --ss: #2b8a3e; --sc: #9a8f7c; --sn: #e8590c; --sf: #1864ab; --st: #6741d9 }
body.look-paper.tint-1 { --hl: #b2f2bb; --accent: #1864ab; --inline-ink: #1864ab }
body.look-paper.tint-2 { --hl: #ffc9de; --accent: #862e9c; --inline-ink: #862e9c }
.look-paper h1, .look-paper h2 { letter-spacing: -0.2px }
.look-paper mark.hl { color: inherit; background: linear-gradient(transparent 52%, var(--hl) 52%, var(--hl) 92%, transparent 92%) }
.look-paper s.strike { color: var(--muted); text-decoration-color: #e03131 }
.look-paper .sub, .look-paper .code-note, .look-paper .mark p, .look-paper .foot, .look-paper .legend, .look-paper .panel .note {
  font-family: "Ink Free", "Segoe Print", cursive }
.look-paper .sub { font-size: 42px } .look-paper .mark p { font-size: 39px } .look-paper .code-note { font-size: 37px }
.look-paper .foot, .look-paper .legend, .look-paper .panel .note { font-size: 31px }
.look-paper .kicker { color: var(--accent); letter-spacing: 2px }
.look-paper .swipe { background: var(--ink); color: #fffdf7; transform: rotate(-2deg) }
.look-paper .badge, .look-paper .step { background: transparent; color: var(--accent); border: 4px solid var(--accent);
  border-radius: 50%; font-family: "Ink Free", "Segoe Print", cursive }
.look-paper .card, .look-paper .panel, .look-paper .codebox, .look-paper .sheet li { box-shadow: 0 10px 0 -2px rgba(80,60,20,.08) }
.look-paper .tick { background: transparent; color: var(--good); border: 3px solid var(--good) }
.look-paper .sheet .kicker { align-self: flex-start; background: var(--hl); color: var(--ink); padding: 6px 16px; transform: rotate(-2deg) }

/* ---- poster: one bold colour, huge condensed type ---- */
body.look-poster { --bg: #2448ff; --slide-bg: #2448ff; --ink: #ffffff; --soft: #e8ecff; --muted: #c5ceff; --faint: #8ea0ff;
  --accent: #ffe14d; --accent-ink: #101010; --panel: rgba(0,0,30,.22); --line: rgba(255,255,255,.28); --bubble: rgba(0,0,0,.22);
  --mark-bg: rgba(0,0,0,.18); --inline-ink: #ffe14d; --good: #ffe14d; --bad: #ff9c9c; --info: #ffffff;
  --display: "Bahnschrift", "Segoe UI", sans-serif; --label-font: "Bahnschrift", "Segoe UI", sans-serif;
  --sk: #ffe14d; --ss: #b9ffcf; --sc: #a9b6ff; --sn: #ffd0a8; --sf: #ffffff; --st: #ffe14d }
body.look-poster.tint-1 { --bg: #ff5a1f; --slide-bg: #ff5a1f; --accent: #111111; --accent-ink: #ffffff; --muted: #ffe0d2;
  --faint: #ffc2a8; --good: #111111; --inline-ink: #111111; --panel: rgba(0,0,0,.14) }
body.look-poster.tint-2 { --bg: #0e8a5f; --slide-bg: #0e8a5f; --accent: #fff3a3; --muted: #c8f0de; --faint: #8fd6b6 }
.look-poster h1, .look-poster h2 { font-stretch: condensed; font-weight: 700; text-transform: uppercase; letter-spacing: 0 }
.look-poster h1 { font-size: calc(var(--size) * 1.32); line-height: .95 }
.look-poster h2 { font-size: 76px; line-height: 1 }
.look-poster .kicker { font-stretch: condensed; letter-spacing: 4px }
.look-poster .badge { width: auto; height: auto; background: none; color: var(--accent); font: 700 150px/0.9 var(--display);
  font-stretch: condensed; justify-content: start }
.look-poster .stat .number { font-stretch: condensed; font-size: 300px }
.look-poster .swipe { border-radius: 0; text-transform: uppercase; letter-spacing: 2px }
.look-poster .card, .look-poster .panel, .look-poster .sheet li, .look-poster .codebox { border-radius: 0; border-width: 3px }
.look-poster .code { color: #ffffff }
"""

# A card's page is body.single, never .card: that is a grid's card (4 Nov 2026: its bullets went on every list).
# A slide whose words outgrow it, down or across (a code line, a big figure), is drawn smaller until they fit (never
# below FIT_MIN of its size). A card, one slide on its own, is drawn as large as fits first (up to FIT_MAX): it fills its
# frame as a picture in the feed.
FIT_MIN, FIT_MAX = 0.62, 1.4
FIT = """() => {
  const card = document.body.classList.contains('single');
  for (const main of document.querySelectorAll('.slide .main')) {
    const wide = (el) => el.scrollWidth > el.clientWidth + 1;
    const over = () => main.scrollHeight > main.clientHeight + 1 || wide(main)
      || [...main.querySelectorAll('.code:not(.wrap)')].some(wide);
    let zoom = card ? %s : 1;
    main.style.zoom = zoom;
    while (over() && zoom > %s) { zoom -= 0.03; main.style.zoom = zoom; }
  }
}""" % (FIT_MAX, FIT_MIN)

# ChatGPT draws a sticker in the middle of its square with a wide margin of nothing round it: drawn whole, the drawing
# showed at half its box (4 Nov 2026: too small to find). Before the fit, each piece is cut to the part that is drawn on; a
# picture with no margin to speak of stays whole, rounded corners and all.
CROP = """async () => {
  for (const img of document.querySelectorAll('.art img')) {
    const w = img.naturalWidth, h = img.naturalHeight, whole = document.createElement('canvas');
    if (!w || !h) continue;
    whole.width = w; whole.height = h;
    const pen = whole.getContext('2d', {willReadFrequently: true});
    pen.drawImage(img, 0, 0);
    const px = pen.getImageData(0, 0, w, h).data;
    let left = w, top = h, right = -1, bottom = -1;
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      if (px[(y * w + x) * 4 + 3] < 24) continue;
      if (x < left) left = x; if (x > right) right = x; if (y < top) top = y; if (y > bottom) bottom = y;
    }
    if (right < 0 || (right - left + 1) * (bottom - top + 1) > 0.9 * w * h) continue;
    const cut = document.createElement('canvas');
    cut.width = right - left + 1; cut.height = bottom - top + 1;
    cut.getContext('2d').drawImage(whole, left, top, cut.width, cut.height, 0, 0, cut.width, cut.height);
    img.src = cut.toDataURL('image/png');
    await img.decode();
    img.closest('.art').classList.add('cut');
  }
}"""


def page(spec: dict, author: dict | None = None, art_dir: Path | None = None) -> str:
    """The carousel (or card) as one HTML page, a slide per printed page; its drawn art read from art_dir."""
    spec = check(spec)
    author = author or {}
    card = spec["format"] == "card"
    total = len(spec["slides"])
    number, parts = 0, []
    for n, s in enumerate(spec["slides"], 1):
        if s["kind"] == "point" and s.get("numbered", True):
            number += 1
        parts.append(_slide(s, n, total, author, number, card, art_dir))
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{html.escape(spec["title"])}</title>'
            f'<style>{CSS}</style></head><body class="look-{spec["look"]} tint-{spec["tint"]}{" single" if card else ""}">'
            f'{"".join(parts)}</body></html>')


def available() -> bool:
    """Whether carousels can be drawn here: Playwright is installed (requirements.txt has it)."""
    try:
        import playwright.sync_api  # noqa: F401, PLC0415
    except ImportError:
        return False
    return True


def render(spec: dict, out_dir: Path, author: dict | None = None, stem: str = "carousel",
           art_dir: Path | None = None) -> dict:
    """Writes <stem>.pdf (a carousel's; a card has none) and <stem>-1.png … into out_dir. Returns {"pdf": Path or None,
    "pages": [Path, ...]}."""
    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415 - only when a carousel is made
    except ImportError:
        raise CarouselError("Carousels need Playwright: close the studio and open it again, and it installs it.") from None
    doc = page(spec, author, art_dir)
    card = check(spec)["format"] == "card"
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf, pages = out_dir / f"{stem}.pdf", []
    with sync_playwright() as p:
        browser = None
        for channel in ("chrome", "msedge"):   # Edge is on every Windows PC
            try:
                browser = p.chromium.launch(channel=channel, headless=True)
                break
            except Exception:  # noqa: BLE001 - that browser isn't installed: try the next
                continue
        if browser is None:
            raise CarouselError("A carousel is drawn with Chrome or Edge, and neither would start here.")
        try:
            tab = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})
            tab.set_content(doc, wait_until="load")
            tab.evaluate("document.fonts.ready")
            tab.evaluate(CROP)
            tab.evaluate(FIT)
            slides = tab.locator("section.slide")
            for i in range(slides.count()):
                target = out_dir / f"{stem}-{i + 1}.png"
                slides.nth(i).screenshot(path=str(target))
                pages.append(target)
            if not card:
                tab.emulate_media(media="print")
                tab.pdf(path=str(pdf), width=f"{WIDTH}px", height=f"{HEIGHT}px", print_background=True,
                        margin={"top": "0", "right": "0", "bottom": "0", "left": "0"})
        finally:
            browser.close()
    return {"pdf": None if card else pdf, "pages": pages}


def author_of(db: DB) -> dict:
    """Who the slides name: Settings › You in the preview, the photo as a data address, once the owner put them on
    carousels; nobody until then, or when nothing is set."""
    if not profile.on_carousels(db):
        return {}
    words = profile.saved(db)
    found = profile.photo(db)
    photo = f"data:{found[1]};base64,{base64.b64encode(found[0]).decode()}" if found else None
    return {"name": words["name"], "line": words["headline"], "photo_uri": photo}


def make(db: DB, post_id: int, spec: dict, *, job_id: int | None = None, prompt: str = "", into: int | None = None) -> int:
    """Draws the carousel or card and keeps it with the post's pictures (images.save), its art read from beside them
    (draw_art has drawn it); `into`, one of the post's it is drawn afresh in place of. Returns its id."""
    spec = check(spec)
    with tempfile.TemporaryDirectory(prefix="carousel-") as temp:
        out = render(spec, Path(temp), author_of(db), art_dir=images.folder(db))
        shots = [path.read_bytes() for path in out["pages"]]
        data = out["pdf"].read_bytes() if out["pdf"] else None
    if spec["format"] == "card":     # one picture, posted as a picture
        return images.save(db, post_id, shots[0], mime="image/png", source="card", prompt=prompt or spec["title"],
                           shape="portrait", width=WIDTH, height=HEIGHT, job_id=job_id, spec=spec, into=into)
    return images.save(db, post_id, data, mime=images.DOCUMENT, source="carousel", prompt=prompt or spec["title"],
                       shape="portrait", width=WIDTH, height=HEIGHT, job_id=job_id, spec=spec, pages=shots, into=into)
