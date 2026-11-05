"""Hot topics: the latest news in the owner's niche, ranked for them, each one a post it can start from (Draft).

The studio reads the news, never Claude, from the last DAYS days (SOURCES): the teams' own feeds (release notes and
official blogs), every article in the Android and iOS newsletters' issues, the Swift and Django forums, engineering
blogs, dev.to's most liked of the week by tag (DEVTO), and the stories Hacker News readers voted up, those kept to the
niche by the words in their titles (NICHE: the persona's pillars). It asks under its own name (USER_AGENT); a source that
turns that away is left out, never asked in disguise. Checked on 4 Nov 2026: Swift.org, Apple's developer news, Django
News, Postgres and JavaScript Weekly drop the connection, Reddit limits it after one request, Anthropic has no feed.
Only the public web is read: an address on this PC or the home network is refused, on every redirect too.

What was read is kept in the database (table `hot`, one row) and read again in the background (Reader) when the page
opens and it is older than FRESH, or on Refresh. Each new item is then ranked by Claude for the owner (`hot_rank` jobs
of BATCH items, one at a time: rank_next; table `hot_ranks`): how good a post it makes for them, 1 to 10, from how it
fits them (their voice profile) and whether it makes a post (RUBRIC), with why, the post it would become (its angle)
and the item it repeats, if any. A Draft gives Claude the item, its angle and its text as untrusted data
(skills._news): the source's own text when it carries enough (ENOUGH words), else the article page as text, else the
item's summary.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from typing import Callable

from .db import DB, dumps, loads, utcnow

USER_AGENT = "LinkedInStudio/1.0 (a personal news reader; +https://github.com/neelesh9924/linkedin-studio)"
DAYS = 14             # how far back the news goes
HN_POINTS = 100       # a Hacker News story is hot from this many points
FRESH = 3600          # seconds a read stays fresh: the page reads again after that, or on Refresh
REFRESH_GAP = 60      # seconds between two reads, however often Refresh is pressed
TIMEOUT = 15          # seconds a source has to answer
FEED_MAX = 3_000_000  # bytes of a feed (or of Hacker News's answer) read at most
PAGE_MAX = 2_000_000  # bytes of an article page
TEXT_MAX = 12_000     # characters of an item's text kept for a draft
SUMMARY_MAX = 280     # characters of it the page shows
ENOUGH = 150          # words of a source's own text that make reading the article page unnecessary
MOST = 300            # items kept: Hacker News's, the most points first, then the rest, the newest first
BATCH = 50            # items a ranking run takes
DEVTO_GAP = 1.0       # seconds between two of dev.to's tags: it refuses several at once
NEWS_FIELDS = ("id", "title", "url", "source", "pillar", "published", "points", "reactions", "comments", "discussion",
               "summary")
RANK_WORDS = {"post": "Worth a post", "strengthen": "Could make a post", "drop": "Not for you"}   # rank.verdict_of's

# The persona's pillars and the words in a title that put a story in one. Names are matched as written (a title keeps
# "Swift" or "Cursor" capitalised; "swift" or "cursor" is a word); phrases in any case.
NICHE = (
    ("Android", r"\b(Android|Kotlin|Jetpack|Gradle)\b"),
    ("Flutter", r"\b(Flutter|Dart)\b"),
    ("Swift and iOS", r"\b(Swift|SwiftUI|iOS|iPadOS|Xcode)\b"),
    ("Django and Python", r"\b(Django|Python|FastAPI|Celery|PyPI)\b"),
    ("Postgres", r"\b(Postgres|PostgreSQL|SQLite|Redis)\b"),
    ("The web", r"\b(JavaScript|TypeScript|Node\.js|WebAssembly)\b"),
    # Agents that write code, not every AI agent (4 Nov 2026: "AI agents" brought in swarms playing Minecraft)
    ("AI coding agents", r"\b(Claude Code|MCP|Copilot|Cursor|Codex)\b"
                         r"|(?i:\b(coding agents?|AI coding|agentic (coding|development|engineering))\b)"),
)
_NICHE = tuple((pillar, re.compile(words)) for pillar, words in NICHE)


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    pillar: str = ""     # its area; empty: the area its title's words give, else "Engineering"
    kind: str = "feed"   # feed: each item; issues: each article a newsletter's issue lists
    keep: str = ""       # when given, a title must match it
    drop: str = ""       # a title that matches it is left out
    niche: bool = False  # only the titles that name the niche: a source much wider than it


SOURCES = (
    # the teams themselves
    Source("Android Developers Blog", "https://android-developers.googleblog.com/atom.xml", "Android"),
    Source("Android Studio", "https://androidstudio.googleblog.com/feeds/posts/default", "Android",
           drop=r"\b(Canary|RC|Beta)\b"),                                  # its stable releases
    Source("Kotlin blog", "https://blog.jetbrains.com/kotlin/feed/", "Android"),
    Source("Flutter", "https://medium.com/feed/flutter", "Flutter"),
    Source("Dart", "https://medium.com/feed/dartlang", "Flutter"),
    Source("Django", "https://www.djangoproject.com/rss/weblog/", "Django and Python"),
    Source("Python Insider", "https://blog.python.org/feeds/posts/default", "Django and Python"),
    Source("PostgreSQL", "https://www.postgresql.org/news.rss", "Postgres", keep=r"\bPostgreSQL \d"),  # its own releases
    Source("GitHub changelog", "https://github.blog/changelog/feed/", "AI coding agents", keep=r"\b(Copilot|[Aa]gents?|MCP)\b"),
    Source("Firebase blog", "https://firebase.blog/rss.xml"),
    # what the community writes: each article of the newsletters' issues, and the forums
    Source("Android Weekly", "https://androidweekly.net/rss.xml", "Android", kind="issues"),
    Source("iOS Dev Weekly", "https://iosdevweekly.com/issues.rss", "Swift and iOS", kind="issues"),
    Source("Swift Forums", "https://forums.swift.org/latest.rss", "Swift and iOS"),
    Source("Django Forum", "https://forum.djangoproject.com/latest.rss", "Django and Python"),
    # how teams at scale build: the rank, not the words of a title, says what fits
    Source("Cloudflare blog", "https://blog.cloudflare.com/rss/"),
    Source("Netflix tech", "https://netflixtechblog.com/feed"),
    Source("Shopify engineering", "https://shopify.engineering/blog.atom"),
    Source("Meta engineering", "https://engineering.fb.com/feed/"),
    Source("Discord blog", "https://discord.com/blog/rss.xml"),
    Source("InfoQ", "https://feed.infoq.com/"),
    Source("JetBrains blog", "https://blog.jetbrains.com/feed/"),
    Source("Simon Willison", "https://simonwillison.net/atom/everything/", niche=True),
)
HN_SOURCE = "Hacker News"
HN_ITEM = "https://news.ycombinator.com/item?id="
DEVTO_SOURCE = "dev.to"
# dev.to's tags, each with the area it is: the week's most liked articles of each, asked one at a time (DEVTO_GAP)
DEVTO = (("flutter", "Flutter"), ("android", "Android"), ("kotlin", "Android"), ("django", "Django and Python"),
         ("python", "Django and Python"), ("swift", "Swift and iOS"), ("ios", "Swift and iOS"), ("postgres", "Postgres"))
OWN_HOSTS = ("androidweekly.net", "iosdevweekly.com", "twitter.com", "x.com", "mastodon.social", "linkedin.com",
             "youtube.com", "youtu.be")   # an issue's links that are not articles to write from

A = "{http://www.w3.org/2005/Atom}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}encoded"
DC_DATE = "{http://purl.org/dc/elements/1.1/}date"


class Refused(ValueError):
    """Not something the studio reads: off the public web, too large, or not a page."""


# ---- reading from the web --------------------------------------------------------------------------------------------
def public(url: str) -> bool:
    """An http(s) address on the public web, on its usual port: every address its name resolves to is a global one."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        return False
    try:
        if parts.port not in (None, 80, 443):
            return False
        found = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except (OSError, ValueError):
        return False
    return bool(found) and all(ipaddress.ip_address(info[4][0].split("%")[0]).is_global for info in found)


class _Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not public(newurl):
            raise Refused("It sent the studio off the public web.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_Redirects)


def http_get(url: str, limit: int) -> tuple[str, bytes]:
    """(its content type, its bytes), asked under the studio's own name."""
    if not public(url):
        raise Refused("That address is not on the public web.")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with _opener.open(request, timeout=TIMEOUT) as answer:
        data = answer.read(limit + 1)
        if len(data) > limit:
            raise Refused("It is larger than the studio reads.")
        return answer.headers.get("Content-Type", ""), data


def words_for(exc: BaseException) -> str:
    """Why a source gave nothing, in a few words for the page."""
    if isinstance(exc, urllib.error.HTTPError):
        return f"it answered {exc.code}"
    if isinstance(exc, (urllib.error.URLError, TimeoutError, OSError)):
        return "it did not answer"
    if isinstance(exc, Refused):
        return str(exc)
    return "its answer could not be read"


# ---- text out of HTML ---------------------------------------------------------------------------------------------------
class _Text(HTMLParser):
    """A page's words: what is in its longest <article>, else its <main>, else all of it, without scripts, menus and
    the like; block elements end lines, and a <pre> keeps its lines between ``` fences."""
    SKIP = {"script", "style", "noscript", "svg", "template", "iframe", "form", "button", "nav", "header", "footer",
            "aside", "figure", "select"}
    BLOCK = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "blockquote", "tr", "table",
             "section", "article", "main", "dd", "dt", "hr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.pre = 0
        self.everything: list[str] = []
        self.articles: list[list[str]] = []
        self.article = 0
        self.main: list[str] = []
        self.in_main = 0

    def _put(self, piece: str) -> None:
        self.everything.append(piece)
        if self.article:
            self.articles[-1].append(piece)
        if self.in_main:
            self.main.append(piece)

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
            return
        if tag == "article":
            if not self.article:
                self.articles.append([])
            self.article += 1
        elif tag == "main":
            self.in_main += 1
        if tag in self.BLOCK and not self.skip:
            self._put("\n")
        if tag == "pre" and not self.skip:
            if not self.pre:
                self._put("```\n")
            self.pre += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if tag == "pre" and self.pre and not self.skip:
            self.pre -= 1
            if not self.pre:
                self._put("\n```")
        if tag in self.BLOCK and not self.skip:
            self._put("\n")
        if tag == "article":
            self.article = max(0, self.article - 1)
        elif tag == "main":
            self.in_main = max(0, self.in_main - 1)

    def handle_data(self, data):
        if not self.skip:
            self._put(data if self.pre else re.sub(r"\s+", " ", data))

    def text(self) -> str:
        longest = max(("".join(a) for a in self.articles), key=len, default="")
        for region in (longest, "".join(self.main), "".join(self.everything)):
            if len(region.split()) >= 120:
                return tidy(region)
        return tidy("".join(self.everything))


def tidy(text: str) -> str:
    """Lines trimmed, but a fenced block's kept as they are; no more than one empty line in a row."""
    out, fenced = [], False
    for line in text.replace("\r", "").split("\n"):
        if line.strip() == "```":
            fenced = not fenced
            out.append("```")
        else:
            out.append(line.rstrip() if fenced else line.strip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def as_text(html: str) -> str:
    parser = _Text()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001  (a broken page still gives what was read of it)
        pass
    return parser.text()


def plain(value: str | None) -> str:
    """A title or a summary as one line of text: no tags, no entities, single spaces."""
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", value or "")).split())


# ---- feeds and Hacker News ------------------------------------------------------------------------------------------
def niche_of(title: str) -> str:
    return next((pillar for pillar, words in _NICHE if words.search(title)), "")


def area_of(item: dict) -> str:
    """The item's pillar as the page names it beside its source, or "" when the source says it already ("Flutter ·
    Flutter", "Django · Django and Python")."""
    area, source = str(item.get("pillar") or ""), str(item.get("source") or "")
    return "" if not area or area.lower().startswith(source.lower()) or source.lower().startswith(area.lower()) else area


def key_of(url: str) -> str:
    """One address however it is written: no scheme, www, trailing slash, fragment or utm_ and ref tags."""
    parts = urllib.parse.urlsplit(url.strip())
    host = (parts.hostname or "").lower().removeprefix("www.")
    query = urllib.parse.urlencode([(k, v) for k, v in urllib.parse.parse_qsl(parts.query)
                                    if not k.lower().startswith(("utm_", "ref", "source"))])
    return f"{host}{parts.path.rstrip('/') or '/'}{'?' + query if query else ''}"


def id_of(url: str) -> str:
    return hashlib.sha1(key_of(url).encode("utf-8")).hexdigest()[:16]


def _when(value: str | None) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        found = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        try:
            found = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return (found if found.tzinfo else found.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _item(source: str, pillar: str, title: str, url: str, at: datetime, text: str, **more) -> dict:
    text = text[:TEXT_MAX]
    summary = " ".join(text.split())
    if len(summary) > SUMMARY_MAX:
        summary = summary[:SUMMARY_MAX].rsplit(" ", 1)[0].rstrip(" ,;:.") + "…"
    return {"id": id_of(url), "title": title, "url": url, "source": source, "pillar": pillar,
            "published": at.isoformat(timespec="seconds"), "points": None, "reactions": None, "comments": None,
            "discussion": None, "summary": summary, "text": text, **more}


def _area(source: Source, title: str) -> str:
    """An item's area: its source's, else the one its title's words give, else Engineering; "" when the source keeps
    only titles in the niche and this one is not."""
    found = niche_of(title)
    if source.niche and not found:
        return ""
    return source.pillar or found or "Engineering"


def _root(data: bytes):
    if re.search(rb"<!ENTITY", data[:65536], flags=re.I):
        raise Refused("its feed declares entities, which the studio does not read")
    return ET.fromstring(data)


def parse_feed(data: bytes, source: Source, since: datetime) -> list[dict]:
    """An RSS or Atom feed's items since `since`, newest first (a niche source's: those in the niche)."""
    root = _root(data)
    found = []
    for node in root.iter("item"):
        link = (node.findtext("link") or "").strip()
        guid = node.find("guid")
        if not link and guid is not None and guid.get("isPermaLink", "true") != "false":
            link = (guid.text or "").strip()
        found.append((node.findtext("title"), link, node.findtext("pubDate") or node.findtext(DC_DATE),
                      node.findtext(CONTENT) or node.findtext("description")))
    for node in root.iter(f"{A}entry"):
        links = [l for l in node.iter(f"{A}link") if l.get("rel") in (None, "alternate") and l.get("href")]
        link = next((l.get("href") for l in links if l.get("type") in (None, "text/html")), links[0].get("href") if links else "")
        body = next((b for b in (node.find(f"{A}content"), node.find(f"{A}summary")) if b is not None and _inner(b).strip()), None)
        found.append((node.findtext(f"{A}title"), link, node.findtext(f"{A}published") or node.findtext(f"{A}updated"),
                      _inner(body) if body is not None else ""))
    out = []
    for title, link, date, body in found:
        title, at = plain(title), _when(date)
        if not title or not link or at is None or at < since or not public_form(link):
            continue
        if (source.keep and not re.search(source.keep, title)) or (source.drop and re.search(source.drop, title)):
            continue
        pillar = _area(source, title)
        if pillar:
            out.append(_item(source.name, pillar, title, link.strip(), at, as_text(body or "")))
    return sorted(out, key=lambda i: i["published"], reverse=True)


class _Links(HTMLParser):
    """A newsletter issue's articles: each link whose words make a title (four or more, starting with a capital or a
    digit, so a link inside a sentence is not one), with the words after it as its summary."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found: list[list[str]] = []
        self.href: str | None = None
        self.words: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.href, self.words = dict(attrs).get("href"), []

    def handle_endtag(self, tag):
        if tag == "a" and self.href is not None:
            title = " ".join("".join(self.words).split())
            first = title.lstrip("\"'‘“([")[:1]
            if len(title.split()) >= 4 and (first.isupper() or first.isdigit()):
                self.found.append([title, self.href, ""])
            self.href = None

    def handle_data(self, data):
        if self.href is not None:
            self.words.append(data)
        elif self.found and len(self.found[-1][2]) < 600:
            self.found[-1][2] += data


def parse_issues(data: bytes, source: Source, since: datetime) -> list[dict]:
    """A newsletter's issues since `since`, each article they list an item of its own (dated with its issue)."""
    out = []
    for node in _root(data).iter("item"):
        at = _when(node.findtext("pubDate") or node.findtext(DC_DATE))
        if at is None or at < since:
            continue
        links = _Links()
        try:
            links.feed(node.findtext(CONTENT) or node.findtext("description") or "")
        except Exception:  # noqa: BLE001  (an issue that breaks off still gives what was read of it)
            pass
        for title, href, after in links.found:
            host = (urllib.parse.urlsplit(href).hostname or "").lower().removeprefix("www.")
            if public_form(href) and not any(host == own or host.endswith("." + own) for own in OWN_HOSTS):
                out.append(_item(source.name, source.pillar, title, href.strip(), at, " ".join(after.split())))
    return out


def devto_address(tag: str) -> str:
    """dev.to's most liked articles of the week under a tag, through its public API."""
    return "https://dev.to/api/articles?" + urllib.parse.urlencode({"tag": tag, "top": 7, "per_page": 8})


def parse_devto(data: bytes, pillar: str, since: datetime) -> list[dict]:
    out = []
    for art in json.loads(data) or []:
        at, url, title = _when(str(art.get("published_at") or "")), str(art.get("url") or ""), plain(art.get("title"))
        if title and at is not None and at >= since and public_form(url):
            out.append(_item(DEVTO_SOURCE, pillar, title, url, at, plain(art.get("description")),
                             reactions=int(art.get("public_reactions_count") or 0),
                             comments=int(art.get("comments_count") or 0)))
    return out


def _inner(node) -> str:
    """An Atom text's HTML: escaped HTML as its text (type="html"), or its own elements (type="xhtml")."""
    return (node.text or "") + "".join(ET.tostring(child, encoding="unicode") for child in node)


def public_form(url: str) -> bool:
    """Looks like a web address (the network is asked only when it is read: public())."""
    parts = urllib.parse.urlsplit(url.strip())
    return parts.scheme in ("http", "https") and bool(parts.hostname)


def hn_address(now: datetime) -> str:
    """Hacker News's stories of the last DAYS days with HN_POINTS points or more, through its public search (Algolia)."""
    since = int((now - timedelta(days=DAYS)).timestamp())
    return "https://hn.algolia.com/api/v1/search?" + urllib.parse.urlencode({
        "query": "", "tags": "story", "numericFilters": f"points>={HN_POINTS},created_at_i>{since}", "hitsPerPage": 1000,
        "attributesToRetrieve": "title,url,points,num_comments,created_at_i,story_text", "attributesToHighlight": ""})


def parse_hn(data: bytes) -> list[dict]:
    """The stories whose titles belong to the niche, hottest first. One without a link (Ask HN) is its own discussion."""
    out = []
    for hit in json.loads(data).get("hits") or []:
        title = plain(hit.get("title"))
        pillar = niche_of(title)
        story = str(hit.get("objectID") or "")
        if not title or not pillar or not story.isdigit():
            continue
        discussion = HN_ITEM + story
        url = str(hit.get("url") or "") if public_form(str(hit.get("url") or "")) else discussion
        at = datetime.fromtimestamp(int(hit.get("created_at_i") or 0), timezone.utc)
        out.append(_item(HN_SOURCE, pillar, title, url, at, as_text(hit.get("story_text") or ""),
                         points=int(hit.get("points") or 0), comments=int(hit.get("num_comments") or 0),
                         discussion=discussion))
    return sorted(out, key=lambda i: i["points"], reverse=True)


def read_all(get: Callable[[str, int], tuple[str, bytes]] | None = None, now: datetime | None = None) -> dict:
    """Every source at once: {"topics": [...], "problems": [{"source", "error"}]}. A story Hacker News voted up that a
    team's feed also has is one item: the feed's, with its points. `get` defaults to http_get, looked up when called
    (the tests' studios replace it, so they never reach the network)."""
    get = get or http_get
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=DAYS)

    def feed(source: Source) -> tuple[list[dict], str]:
        try:
            parse = parse_issues if source.kind == "issues" else parse_feed
            return parse(get(source.url, FEED_MAX)[1], source, since), ""
        except Exception as exc:  # noqa: BLE001  (one source failing never takes the others with it)
            return [], words_for(exc)

    def stories() -> tuple[list[dict], str]:
        try:
            return parse_hn(get(hn_address(now), FEED_MAX)[1]), ""
        except Exception as exc:  # noqa: BLE001
            return [], words_for(exc)

    def week() -> tuple[list[dict], str]:
        """dev.to's tags one after another, DEVTO_GAP apart; a tag that gives nothing leaves the others."""
        found, errors = [], []
        for n, (tag, pillar) in enumerate(DEVTO):
            if n:
                time.sleep(DEVTO_GAP)
            try:
                found += parse_devto(get(devto_address(tag), FEED_MAX)[1], pillar, since)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"#{tag}: {words_for(exc)}")
        return found, "; ".join(errors)

    with ThreadPoolExecutor(max_workers=6) as pool:
        hot = pool.submit(stories)
        liked = pool.submit(week)
        feeds = list(pool.map(feed, SOURCES))
        voted, hn_error = hot.result()
        community, devto_error = liked.result()
    items: dict[str, dict] = {}
    for found in [f for f, _error in feeds] + [community]:
        for item in found:
            items.setdefault(item["id"], item)
    for story in voted:
        if story["id"] in items:
            items[story["id"]].update(points=story["points"], comments=story["comments"], discussion=story["discussion"])
        else:
            items[story["id"]] = story
    problems = [{"source": s.name, "error": e} for s, (_found, e) in zip(SOURCES, feeds) if e]
    problems += [{"source": name, "error": e} for name, e in ((HN_SOURCE, hn_error), (DEVTO_SOURCE, devto_error)) if e]
    hottest = sorted((i for i in items.values() if i["points"] is not None), key=lambda i: i["points"], reverse=True)
    newest = sorted((i for i in items.values() if i["points"] is None), key=lambda i: i["published"], reverse=True)
    return {"topics": (hottest + newest)[:MOST], "problems": problems}


def article(url: str, get: Callable[[str, int], tuple[str, bytes]] | None = None) -> str:
    """An article page as text, for a draft."""
    kind, data = (get or http_get)(url, PAGE_MAX)
    if "html" not in kind.lower():
        raise Refused("It is not a page the studio reads.")
    charset = re.search(r"charset=([\w.-]+)", kind, flags=re.I)
    try:
        html = data.decode(charset.group(1) if charset else "utf-8", errors="replace")
    except LookupError:
        html = data.decode("utf-8", errors="replace")
    return as_text(html)[:TEXT_MAX]


# ---- kept in the studio -----------------------------------------------------------------------------------------------
def kept(db: DB) -> dict | None:
    row = db.one("SELECT * FROM hot WHERE id=1")
    if row is None:
        return None
    return {"fetched_at": row["fetched_at"], "topics": loads(row["topics"], []) or [], "problems": loads(row["problems"], []) or []}


def topic(db: DB, topic_id: str) -> dict | None:
    return next((t for t in (kept(db) or {}).get("topics", []) if t.get("id") == topic_id), None)


def text_for(db: DB, news: dict) -> tuple[str, str]:
    """What a draft writes from: (text, how it was read) — "source", "page" or "summary"."""
    own = (topic(db, news.get("id", "")) or {}).get("text") or ""
    if len(own.split()) >= ENOUGH:
        return own, "source"
    try:
        page = article(news["url"])        # the module's, when called: the demo and the tests stand in for it
    except Exception:  # noqa: BLE001  (an article that can't be read leaves the summary)
        page = ""
    if len(page.split()) >= 80:
        return page, "page"
    return (own if len(own) > len(news.get("summary") or "") else news.get("summary") or own or news.get("title", "")), "summary"


# ---- ranked for the owner -----------------------------------------------------------------------------------------------
# What a ranking run judges by (skills._hot_rank), on the scale of a post's own rank (rank.RUBRIC, rank.verdict_of).
RUBRIC = ("Rank each item 1 to 10: how good a LinkedIn post it makes for this owner. Two things make the rank. Fits them: "
          "their stack, the way they work and their pillars, as their voice profile says; an item outside them ranks low "
          "however hot. Makes a post: something specific a senior developer can teach developers coming up from it (a "
          "production trap, a mechanism, a tradeoff, a habit, a change they must act on), timely, with its facts in the "
          "item, worth saving. Rank low: news with nothing to teach (business, legal, launches, survey figures alone), "
          "promotions and sponsor blurbs, community notices, help requests and beginner basics. Rank 1 anything the voice "
          "profile's Never lines keep out of posts, however strong, and never name what it is in why or angle. Use the "
          "whole range: 7 to 10 worth a post, 5 or 6 could make one with the right angle, 1 to 4 not for them.")
MOST_WHY = 300        # characters of why and of angle kept
_ranking = threading.Lock()   # the Reader's thread and a run's end never start two runs at once


def ranks(db: DB) -> dict[str, dict]:
    """Every rank kept, by item id."""
    return {r["id"]: {"rank": r["rank"], "why": r["why"] or "", "angle": r["angle"] or "", "same_as": r["same_as"]}
            for r in db.all("SELECT * FROM hot_ranks")}


def heat_words(item: dict) -> str:
    if item.get("points"):
        return f"{item['points']} points on Hacker News"
    if item.get("reactions"):
        return f"{item['reactions']} reactions on dev.to"
    return ""


def _on_its_way(db: DB, but: int | None) -> list:
    """The ranking runs queued or running, but the one with id `but` (a run whose end is being kept: the job runner
    marks it done only after)."""
    return [r for r in db.all("SELECT id, params FROM jobs WHERE kind='hot_rank' AND status IN ('queued','running')")
            if r["id"] != but]


def unranked(db: DB, but: int | None = None) -> list[dict]:
    """The kept items with no rank and none on its way, in the order they are ranked: Hacker News's first, by points,
    then the newest (read_all keeps them so)."""
    done = {r["id"] for r in db.all("SELECT id FROM hot_ranks")}
    busy: set[str] = set()
    for r in _on_its_way(db, but):
        busy.update((loads(r["params"], {}) or {}).get("ids") or [])
    return [t for t in (kept(db) or {}).get("topics", []) if t["id"] not in done and t["id"] not in busy]


def batch_params(items: list[dict]) -> dict:
    """What a ranking run is given (skills._hot_rank): each item's id and what it says, briefly."""
    return {"ids": [t["id"] for t in items],
            "items": [{"id": t["id"], "title": t["title"], "source": t["source"], "area": t["pillar"],
                       "published": str(t.get("published") or "")[:10], "heat": heat_words(t),
                       "summary": str(t.get("summary") or "")[:240]} for t in items]}


def rank_next(jobs, db: DB, but: int | None = None) -> int | None:
    """The next ranking run, of up to BATCH items without a rank, when none is on its way: its job id, else None.
    `but`: the run handing on (flows.hot_rank_done), which still shows as running (4 Nov 2026: the first ranking of 248
    items stopped after one batch, as that run saw itself on its way)."""
    with _ranking:
        if _on_its_way(db, but):
            return None
        todo = unranked(db, but)[:BATCH]
        return jobs.submit("hot_rank", batch_params(todo)) if todo else None


def keep_ranks(db: DB, params: dict, data) -> int:
    """A ranking run's answer, checked: a whole rank 1-10 for an item the run was given, why and angle cut short, and
    same_as only another kept item. How many it kept."""
    given = set(params.get("ids") or [])
    known = {t["id"] for t in (kept(db) or {}).get("topics", [])}
    entries = data.get("items") if isinstance(data, dict) else None
    n = 0
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        item_id, value = entry.get("id"), entry.get("rank")
        if item_id not in given or isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 10:
            continue
        same = entry.get("same_as")
        same = same if isinstance(same, str) and same in known and same != item_id else None
        db.run("INSERT INTO hot_ranks (id, rank, why, angle, same_as, ranked_at) VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO "
               "UPDATE SET rank=excluded.rank, why=excluded.why, angle=excluded.angle, same_as=excluded.same_as, "
               "ranked_at=excluded.ranked_at", (item_id, value, _line(entry.get("why")), _line(entry.get("angle")), same,
                                                utcnow()))
        n += 1
    return n


def _line(value) -> str:
    return " ".join(str(value or "").split())[:MOST_WHY]


class Reader:
    """Reads the news in the background and keeps it: one read at a time, at most one each REFRESH_GAP. The read
    itself is the module's read_all, looked up when it runs (the demo and the tests stand in for it). `on_read` runs
    once a read is kept (the studio ranks what is new then: rank_next); the ranks of items no longer kept go."""

    def __init__(self, db: DB, on_read: Callable[[], object] | None = None):
        self.db = db
        self.on_read = on_read
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._last = float("-inf")

    @property
    def reading(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def stale(self) -> bool:
        now = kept(self.db)
        if now is None:
            return True
        at = datetime.fromisoformat(now["fetched_at"])
        return (datetime.now(timezone.utc) - at).total_seconds() > FRESH

    def kick(self, force: bool = False) -> bool:
        """Starts a read when it is due (`force`: Refresh) and none runs. Whether one started."""
        with self._lock:
            if self.reading or time.monotonic() - self._last < REFRESH_GAP or not (force or self.stale()):
                return False
            self._last = time.monotonic()
            self._thread = threading.Thread(target=self._read, name="hot-topics", daemon=True)
            self._thread.start()
            return True

    def _read(self) -> None:
        try:
            got = read_all()
        except Exception as exc:  # noqa: BLE001
            got = {"topics": None, "problems": [{"source": "Hot topics", "error": words_for(exc)}]}
        before = kept(self.db)
        topics = got["topics"] if got.get("topics") is not None else (before or {}).get("topics", [])
        self.db.run("INSERT INTO hot (id, fetched_at, topics, problems) VALUES (1,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                    "fetched_at=excluded.fetched_at, topics=excluded.topics, problems=excluded.problems",
                    (utcnow(), dumps(topics), dumps(got.get("problems") or [])))
        self.db.run("DELETE FROM hot_ranks WHERE id NOT IN (SELECT value FROM json_each(?))", (dumps([t["id"] for t in topics]),))
        if self.on_read is not None:
            try:
                self.on_read()
            except Exception:  # noqa: BLE001  (ranking never takes the read with it: the page shows the items unranked)
                pass

    def wait(self, timeout: float = 30) -> None:
        if self._thread is not None:
            self._thread.join(timeout)
