"""Looks, cards, layouts and ChatGPT art (carousel.py): a spec is checked for its look, format, kinds and art; every
look draws (one real drawing per look with the Chrome or Edge on this PC); a card is one slide kept as a picture; Try
another look goes through every look in turn and never draws the art again; art is drawn once, kept by its hash beside
the post's pictures, goes only when no carousel or card shows it, and is cut to its drawing before the fit. A stand-in
draws instead of ChatGPT."""
import hashlib
import json
import struct
import zlib

import pytest
from support import PNG

from app import carousel, images
from app.db import DB
from launch import find_browser

GRID = {"kind": "grid", "kicker": "Cheat sheet", "title": "Cache rules that ==hold up==",
        "cards": [{"title": "HTTP caching", "tag": "Web", "items": ["Send `Cache-Control` on every reply", "Revalidate with an ETag"]},
                  {"title": "Query caching", "items": ["Key it by every input"]}], "legend": "From two notes"}
VERSUS = {"kind": "versus", "title": "Polling or ==webhooks==?",
          "left": {"label": "Polling", "chat": [{"who": "you", "text": "Any news?"}, {"who": "api", "text": "Not yet"}],
                   "note": "You ask, and ask again.", "art": "a stressed developer at a laptop"},
          "right": {"label": "Webhooks", "items": ["The server calls you"], "art": "a calm robot with a checklist"}}
CODE = {"kind": "code", "title": "A cache with ==no key==", "file": "UserCache.kt",
        "code": 'scope.launch {\n    val user = api.loadUser(userId)  // "never" cached\n}', "note": "Key it by the user."}


def card(slide, **more):
    return {"title": "A card", "format": "card", "slides": [slide], **more}


def carousel_of(*slides, **more):
    return {"title": "A carousel", "slides": [{"kind": "cover", "title": "A hook"}, *slides,
                                              {"kind": "end", "question": "Yours?"}], **more}


# ---- the spec --------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("spec,said", [
    (card(GRID, look="neon"), "The look is one of midnight"),
    (card(GRID, tint=3), "tint is a whole number from 0 to 2"),
    (card(GRID, tint=True), "tint is a whole number"),
    (card(GRID, format="poster"), "format is carousel or card"),
    ({"title": "Two", "format": "card", "slides": [GRID, GRID]}, "A card is one slide"),
    (card({"kind": "end", "question": "Yours?"}), "not an end slide"),
    (card({"kind": "grid", "title": "T", "cards": [{"title": "only one", "items": ["a"]}]}), "2 to 6 cards"),
    (card({"kind": "grid", "title": "T", "cards": [{"title": "a", "items": []}, {"title": "b", "items": ["x"]}]}), "card 1 needs 1 to 5 items"),
    (card({"kind": "versus", "title": "T", "left": {"label": "a", "items": ["x"]}, "right": {"label": "b"}}), "right needs one of items"),
    (card({"kind": "versus", "title": "T", "left": {"label": "a", "items": ["x"], "code": "y"},
           "right": {"label": "b", "items": ["x"]}}), "left needs one of items"),
    (card({"kind": "flow", "title": "T", "steps": [{"label": "only"}]}), "2 to 5 steps"),
    (card({"kind": "chat", "title": "T", "lines": [{"who": "you", "text": "hi"}]}), "2 to 8 lines"),
    (card({"kind": "stat", "title": "T"}), "needs its number"),
    (card({"kind": "code", "title": "T"}), "needs its code"),
    (card({**GRID, "art": "a"}), "art says what to draw"),
    (card({"kind": "chat", "title": "T", "art": "a calm robot here", "lines": [{"who": "a", "text": "b"}, {"who": "c", "text": "d"}]}),
     "can't carry art"),
    (card({**VERSUS, "left": {**VERSUS["left"], "art": {"prompt": "x", "file": "../../secrets.png"}}}), "art says what to draw"),
    (carousel_of({**GRID, "art": "one more robot"}, VERSUS), "At most 2 pieces of art"),
])
def test_a_spec_has_a_known_look_and_format_each_kind_its_fields_and_at_most_two_pieces_of_art(spec, said):
    with pytest.raises(carousel.CarouselError, match=said):
        carousel.check(spec)


def test_a_spec_from_before_the_looks_is_drawn_in_midnight_as_a_carousel():
    old = carousel.check(carousel_of({"kind": "point", "title": "One idea"}))
    assert (old["look"], old["tint"], old["format"]) == ("midnight", 0, "carousel")


# ---- the page ---------------------------------------------------------------------------------------------------------
def test_marked_and_struck_words_are_drawn_but_never_inside_code():
    page = carousel.page(card({"kind": "stat", "number": "~50%", "title": "Stop ~~slicing~~ ==streaming==",
                               "text": "Read `a == b ==` as code"}))
    assert '<s class="strike">slicing</s>' in page and '<mark class="hl">streaming</mark>' in page
    assert '<code class="inline">a == b ==</code>' in page


def test_code_is_coloured_and_a_slide_of_kind_code_is_never_a_code_block():
    page = carousel.page(card(CODE, look="blueprint"))
    assert '<section class="slide k-code">' in page and 'class="slide code"' not in page   # the whole slide went monospace
    assert '<span class="f">launch</span>' not in page          # launch is not followed by (
    assert '<span class="f">loadUser</span>' in page and '<span class="k">val</span>' in page
    assert '<span class="c">// &quot;never&quot; cached</span>' in page or '<span class="c">// "never" cached</span>' in page
    assert '<div class="tab"><i></i><i></i><i></i><span>UserCache.kt</span></div>' in page and 'class="ln"' in page


def test_every_layout_draws_its_parts():
    page = carousel.page(carousel_of(GRID, VERSUS, {"kind": "flow", "title": "Before you run it",
                                                    "steps": [{"label": "Count", "text": "rows"}, {"label": "Run"}]},
                                     {"kind": "chat", "title": "T", "lines": [{"who": "you", "text": "a"}, {"who": "app", "text": "b"}]}))
    assert page.count('<div class="card">') == 2 and "<em>Web</em>" in page and '<p class="legend">From two notes</p>' in page
    assert '<div class="panels split">' in page and '<p class="bubble mine">Any news?</p>' in page   # no code: side by side
    assert page.count('<span class="step">') == 2 and '<div class="say mine">' in page
    stacked = carousel.page(card({**VERSUS, "left": {"label": "Looped", "code": "for x in rows[a:b]:\n    send(x)"}}))
    assert '<div class="panels stack">' in stacked                            # code needs the width


def test_each_look_and_tint_is_the_pages_own_and_try_another_look_goes_through_all_fifteen():
    spec = carousel.check(card(GRID))
    page = carousel.page({**spec, "look": "paper", "tint": 2})
    assert '<body class="look-paper tint-2 single">' in page
    seen, now = [], spec
    for _ in range(len(carousel.CYCLE)):
        now = carousel.next_look(now)
        seen.append((now["look"], now["tint"]))
    assert len(set(seen)) == 15 and seen[-1] == ("midnight", 0) and now["slides"] == spec["slides"]   # around, same slides


# ---- ChatGPT's art ----------------------------------------------------------------------------------------------------
def test_art_is_drawn_once_kept_by_its_hash_and_a_piece_that_fails_is_left_out(tmp_path):
    asked = []

    def make_art(subject):
        asked.append(subject)
        if "robot" in subject:
            raise RuntimeError("ChatGPT made no picture")
        return PNG

    spec = carousel.check(card(VERSUS))
    assert carousel.art_subjects(spec) == ["a stressed developer at a laptop", "a calm robot with a checklist"]
    spec, said = carousel.draw_art(spec, tmp_path, make_art)
    name = f"art-{hashlib.sha256(PNG).hexdigest()[:24]}.png"
    assert spec["slides"][0]["left"]["art"] == {"prompt": "a stressed developer at a laptop", "file": name}
    assert "art" not in spec["slides"][0]["right"] and said == ["no art for “a calm robot with a checklist”: ChatGPT made no picture"]
    assert (tmp_path / name).read_bytes() == PNG and carousel.art_files(spec) == [name]
    again, said = carousel.draw_art(carousel.check(spec), tmp_path, make_art)   # drawn already: never asked again
    assert len(asked) == 2 and said == [] and carousel.art_files(again) == [name]
    assert "fully transparent background" in carousel.art_prompt("a robot") and "no text" in carousel.art_prompt("a robot")
    page = carousel.page(again, art_dir=tmp_path)
    assert page.count('<figure class="art small"><img src="data:image/png;base64,') == 1
    assert '<figure class="art' not in carousel.page(again, art_dir=tmp_path / "elsewhere")   # its file isn't there: none
    dropped = carousel.drop_art(carousel.check(card(VERSUS)))
    assert carousel.art_subjects(dropped) == [] and carousel.check(dropped)


def stand_in_render(spec, out_dir, author=None, stem="carousel", art_dir=None):
    """carousel.render without a browser: a card's one PNG, or a carousel's PDF and a PNG a slide."""
    out_dir.mkdir(parents=True, exist_ok=True)
    pages = []
    for n, _slide in enumerate(spec["slides"], 1):
        page = out_dir / f"{stem}-{n}.png"
        page.write_bytes(PNG + json.dumps([spec["look"], spec["tint"], n]).encode())
        pages.append(page)
    if spec.get("format") == "card":
        return {"pdf": None, "pages": pages}
    (out_dir / f"{stem}.pdf").write_bytes(b"%PDF-1.7 " + spec["look"].encode())
    return {"pdf": out_dir / f"{stem}.pdf", "pages": pages}


def test_a_card_is_kept_as_its_one_picture_and_another_look_keeps_its_art_till_nothing_shows_it(tmp_path, monkeypatch):
    db = DB(tmp_path / "looks.db")
    post = db.run("INSERT INTO posts (created_at, updated_at, title, text, status) VALUES ('x','x','t','t','draft')")
    monkeypatch.setattr(carousel, "render", stand_in_render)
    spec, _said = carousel.draw_art(carousel.check(card(VERSUS, look="terminal")), images.folder(db), lambda subject: PNG)
    made = carousel.make(db, post, spec)
    row = db.one("SELECT * FROM images WHERE id=?", (made,))
    assert (row["mime"], row["source"], row["pages"]) == ("image/png", "card", None)          # a picture: it posts as one
    shown = images.public(row)
    assert (shown["kind"], shown["card"], shown["look"]) == ("picture", True, "terminal") and "page_urls" not in shown
    art = carousel.art_files(spec)[0]
    assert images.art_of(row) == [art] and images.files_of(row) == [row["file"]]
    other = carousel.next_look(carousel.check(json.loads(row["spec"])))
    assert carousel.make(db, post, other, into=made) == made                                    # in its place, its art kept
    row = db.one("SELECT * FROM images WHERE id=?", (made,))
    assert json.loads(row["spec"])["look"] == "blueprint" and (images.folder(db) / art).is_file()
    copy = db.run("INSERT INTO images (post_id, file, source, mime, sha256, spec, created_at) VALUES (?,?,?,?,?,?,'x')",
                  (post, row["file"], "card", "image/png", row["sha256"], row["spec"]))          # New draft from this shares it
    db.run("DELETE FROM images WHERE id=?", (made,))
    images.unlink_unused(db, [row])
    assert (images.folder(db) / art).is_file()                                                  # the copy still shows it
    db.run("DELETE FROM images WHERE id=?", (copy,))
    images.unlink_unused(db, [row])
    assert not (images.folder(db) / art).exists() and not (images.folder(db) / row["file"]).exists()


@pytest.mark.skipif(not carousel.available(), reason="Playwright is not installed here")
@pytest.mark.parametrize("look", list(carousel.LOOKS))
def test_every_look_draws_a_card_and_a_carousel(tmp_path, look):
    try:
        out = carousel.render(card(GRID, look=look, tint=1), tmp_path / "card", stem="card")
        many = carousel.render(carousel_of(VERSUS | {"left": {"label": "Looped", "code": "for x in rows[a:b]:\n    send(x)"}},
                                           look=look), tmp_path / "carousel", stem="carousel")
    except carousel.CarouselError as exc:
        pytest.skip(str(exc))                                           # no Chrome or Edge on this PC
    assert out["pdf"] is None and len(out["pages"]) == 1 and out["pages"][0].read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert many["pdf"].read_bytes().startswith(b"%PDF-") and len(many["pages"]) == 3


def sticker(width, height, drawn):
    """A PNG clear but for one opaque box, drawn = (left, top, right, bottom): ChatGPT's sticker and its margin."""
    left, top, right, bottom = drawn
    rows = b"".join(b"\0" + b"".join(b"\xff\x80\0\xff" if left <= x < right and top <= y < bottom else bytes(4)
                                     for x in range(width)) for y in range(height))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


@pytest.mark.skipif(not carousel.available() or not find_browser(""), reason="needs Playwright and Chrome or Edge")
def test_art_is_cut_to_its_drawing_before_the_fit_and_a_picture_with_no_margin_stays_whole(tmp_path):
    from playwright.sync_api import sync_playwright  # noqa: PLC0415
    names = []
    for png in (sticker(200, 200, (50, 40, 150, 180)), sticker(60, 60, (0, 0, 60, 60))):
        names.append(f"art-{hashlib.sha256(png).hexdigest()[:24]}.png")
        (tmp_path / names[-1]).write_bytes(png)
    spec = card({**VERSUS, "left": {**VERSUS["left"], "art": {"prompt": "a stressed developer", "file": names[0]}},
                 "right": {**VERSUS["right"], "art": {"prompt": "a calm robot", "file": names[1]}}})
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome" if "chrome" in find_browser("").lower() else "msedge", headless=True)
        tab = browser.new_page()
        tab.set_content(carousel.page(spec, art_dir=tmp_path), wait_until="load")
        tab.evaluate(carousel.CROP)
        art = tab.evaluate("[...document.querySelectorAll('.art')].map(f => [f.className, f.firstChild.naturalWidth,"
                           " f.firstChild.naturalHeight, f.firstChild.offsetWidth])")
        browser.close()
    assert art == [["art small cut", 100, 140, 240], ["art small", 60, 60, 240]]   # the sticker cut, the tile whole


@pytest.mark.skipif(not carousel.available() or not find_browser(""), reason="needs Playwright and Chrome or Edge")
def test_a_card_too_full_for_its_largest_size_is_drawn_smaller_and_its_code_box_shows_all_its_code(tmp_path):
    from playwright.sync_api import sync_playwright  # noqa: PLC0415
    png = sticker(200, 200, (50, 40, 150, 180))
    name = f"art-{hashlib.sha256(png).hexdigest()[:24]}.png"
    (tmp_path / name).write_bytes(png)
    full = card({**CODE, "kicker": "Caching", "title": "With ==no key==, every read goes to the network",
                 "code": "\n".join(f'"user{n}": null,' for n in range(1, 7)),     # short lines: too tall, never too wide
                 "note": "Every read goes to the network: with no key, the cache can never answer for a user it has seen.",
                 "art": {"prompt": "a robot", "file": name}})
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome" if "chrome" in find_browser("").lower() else "msedge", headless=True)
        tab = browser.new_page(viewport={"width": carousel.WIDTH, "height": carousel.HEIGHT})
        tab.set_content(carousel.page(full, art_dir=tmp_path), wait_until="load")
        tab.evaluate(carousel.CROP)
        tab.evaluate(carousel.FIT)
        zoom, box, code = tab.evaluate("[+document.querySelector('.main').style.zoom, document.querySelector('.codebox')"
                                       ".clientHeight, document.querySelector('.codebox').scrollHeight]")
        browser.close()
    assert zoom < carousel.FIT_MAX and box >= code   # 4 Nov 2026: the box was squeezed to a line and the card stayed large
