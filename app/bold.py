"""LinkedIn's "bold". A post has no markup, so bold is letters from Unicode's Mathematical Sans-Serif Bold block, as
other posts on LinkedIn use it: A-Z, a-z and 0-9 map one to one, everything else stays as it is. The page's Bold button
(js/bold.js) uses the same three starting points, and the writer marks bold as **words**, which from_marks turns into
these letters when Claude's text lands in a post (a chat change, a revision, a first draft).

Bold is for the first line and short heads only: screen readers and LinkedIn's search read these letters as symbols, so
code and anything someone may search for stay plain.
"""
from __future__ import annotations

import re
import unicodedata

UPPER, LOWER, DIGIT = 0x1D5D4, 0x1D5EE, 0x1D7EC
# **words**, not code: no brackets, operators or backticks inside, and no word character or * right outside, so
# Python's **kwargs and f(**a, **b) stay as they are.
MARKED = re.compile(r"(?<![\w*])\*\*(?=\S)([^*\n()\[\]{}<>=`]+?)(?<=\S)\*\*(?![\w*])")


def bold(text: str) -> str:
    out = []
    for ch in text:
        if "A" <= ch <= "Z":
            ch = chr(UPPER + ord(ch) - ord("A"))
        elif "a" <= ch <= "z":
            ch = chr(LOWER + ord(ch) - ord("a"))
        elif "0" <= ch <= "9":
            ch = chr(DIGIT + ord(ch) - ord("0"))
        out.append(ch)
    return "".join(out)


def plain(text: str) -> str:
    """The text with its bold letters as ordinary ones (what LinkedIn's search and the checks read)."""
    return unicodedata.normalize("NFKC", text)


def from_marks(text: str) -> str:
    """Claude's **words** as LinkedIn bold; a stray ** or code stays as it is."""
    return MARKED.sub(lambda m: bold(m.group(1)), text)
