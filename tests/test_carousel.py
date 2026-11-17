"""Carousels (carousel.py) and LinkedIn's bold (bold.py, js/bold.js): a spec is checked before anything is drawn, its words
are drawn as text and escaped, the slides name the owner from You in the preview, and one real drawing with the Chrome or
Edge on this PC makes a PDF of one page a slide. Bold is one mapping on both sides."""
import re
from pathlib import Path

import pytest

from app import bold, carousel, images, profile
from app.db import DB

SPEC = {"title": "Prefetch, in short", "slides": [
    {"kind": "cover", "title": "A slow API after <prefetch_related>", "kicker": "Django · ORM", "sub": "One query a row."},
    {"kind": "point", "title": "The trap", "code": "order.items.filter(\n    is_open=True)", "mark": {"kind": "trap", "text": "50 rows, 50 queries."}},
    {"kind": "point", "numbered": False, "title": "Why tests miss it", "text": "Wrap it in `assertNumQueries`."},
    {"kind": "compare", "title": "Before and after", "before": "a()", "after": "b()"},
    {"kind": "sheet", "title": "In short", "items": ["One exact query is cached.", "Filter inside it."]},
    {"kind": "end", "question": "Your sneakiest N+1?"}]}


@pytest.mark.parametrize("spec,said", [
    (None, "an object"),
    ({"slides": SPEC["slides"]}, "Give the carousel a title"),
    ({"title": "T", "slides": SPEC["slides"][:2]}, "3 to 12 slides"),
    ({"title": "T", "slides": [{"kind": "poster"}] * 3}, "needs a kind"),
    ({"title": "T", "slides": [{"kind": "point"}] * 3}, r"Slide 1 \(point\) needs a title"),
    ({"title": "T", "slides": [{"kind": "compare", "title": "x", "before": "a"}] * 3}, "both before and after"),
    ({"title": "T", "slides": [{"kind": "sheet", "title": "x", "items": ["one"]}] * 3}, "2 to 6 items"),
    ({"title": "T", "slides": [{"kind": "point", "title": "x", "mark": {"kind": "tip", "text": "t"}}] * 3}, "mark needs a kind"),
])
def test_a_spec_is_checked_before_anything_is_drawn(spec, said):
    with pytest.raises(carousel.CarouselError, match=said):
        carousel.check(spec)


def test_the_page_draws_every_word_as_escaped_text_and_numbers_only_the_numbered_points():
    page = carousel.page(SPEC, {"name": "Ada Lovelace", "line": "Engineer"})
    assert page.count('class="slide ') == 6 and "<title>Prefetch, in short</title>" in page
    assert "&lt;prefetch_related&gt;" in page and "<prefetch_related>" not in page             # never markup from the spec
    assert re.findall(r'class="badge">(\d+)<', page) == ["01"]                                # the unnumbered one has none
    assert '<code class="inline">assertNumQueries</code>' in page and "50 rows, 50 queries." in page
    assert page.count(">AL<") == 6 and "Follow <b>Ada Lovelace</b>" in page                      # initials when no photo
    nobody = carousel.page(SPEC, {})
    assert "Follow" not in nobody and 'class="avatar"' not in nobody                         # no name: no badge, no follow line


def test_the_slides_name_the_owner_only_once_they_put_it_on_carousels(tmp_path):
    db = DB(tmp_path / "c.db")
    assert carousel.author_of(db) == {}
    profile.save_words(db, "Ada Lovelace", "Engineer")
    assert carousel.author_of(db) == {} and profile.public(db)["name"] == "Ada Lovelace"    # the preview has it; slides don't
    assert profile.save_on_carousels(db, True)["on_carousels"] is True
    assert carousel.author_of(db) == {"name": "Ada Lovelace", "line": "Engineer", "photo_uri": None}
    profile.save_words(db, "Ada King", "Engineer")                                           # saving words keeps the switch
    assert profile.on_carousels(db) and carousel.author_of(db)["name"] == "Ada King"
    profile.save_on_carousels(db, False)
    assert carousel.author_of(db) == {} and profile.saved(db)["name"] == "Ada King"
    with pytest.raises(profile.Refused):
        profile.save_on_carousels(db, "yes")


def test_a_carousel_is_kept_as_its_pdf_and_a_picture_of_each_slide(tmp_path, monkeypatch):
    db = DB(tmp_path / "c.db")
    post = db.run("INSERT INTO posts (created_at, updated_at, title, text, status) VALUES ('x','x','t','t','draft')")

    def stand_in(spec, out_dir, author=None, stem="carousel", art_dir=None):
        (out_dir / "c.pdf").write_bytes(b"%PDF-1.7 made")
        pages = []
        for n in range(len(spec["slides"])):
            pages.append(out_dir / f"c-{n}.png")
            pages[-1].write_bytes(b"\x89PNG" + bytes([n]))
        return {"pdf": out_dir / "c.pdf", "pages": pages}
    monkeypatch.setattr(carousel, "render", stand_in)
    made = carousel.make(db, post, SPEC)
    row = db.one("SELECT * FROM images WHERE id=?", (made,))
    assert (row["mime"], row["source"], row["pages"], row["shape"]) == ("application/pdf", "carousel", 6, "portrait")
    assert images.page_path(db, row, 6).read_bytes() == b"\x89PNG\x05" and images.page_path(db, row, 7) is None
    assert len(images.files_of(row)) == 7 and images.public(row)["page_urls"][0] == f"/api/image/{made}/page/1?v={row['sha256'][:12]}"


def test_redraw_puts_new_slides_in_the_old_ones_place_and_drops_the_old_files(tmp_path, monkeypatch):
    db = DB(tmp_path / "c.db")
    post = db.run("INSERT INTO posts (created_at, updated_at, title, text, status) VALUES ('x','x','t','t','draft')")
    drawn = iter([b"first", b"second"])

    def stand_in(spec, out_dir, author=None, stem="carousel", art_dir=None):
        mark = next(drawn)
        (out_dir / "c.pdf").write_bytes(b"%PDF-1.7 " + mark)
        pages = [out_dir / f"c-{n}.png" for n in range(len(spec["slides"]))]
        for n, page in enumerate(pages):
            page.write_bytes(b"\x89PNG" + mark + bytes([n]))
        return {"pdf": out_dir / "c.pdf", "pages": pages}
    monkeypatch.setattr(carousel, "render", stand_in)
    made = carousel.make(db, post, SPEC)
    before = db.one("SELECT * FROM images WHERE id=?", (made,))
    old_files = [images.folder(db) / name for name in images.files_of(before)]
    assert carousel.make(db, post, SPEC, into=made) == made                  # the same row: all that names it still does
    after = db.one("SELECT * FROM images WHERE id=?", (made,))
    assert len(db.all("SELECT id FROM images")) == 1 and after["file"] != before["file"]
    assert not any(path.exists() for path in old_files)                     # no copy left beside it
    assert images.page_path(db, after, 1).read_bytes() == b"\x89PNGsecond\x00"
    assert images.public(after)["url"] != images.public(before)["url"]      # a new address, so no slides from the cache


@pytest.mark.skipif(not carousel.available(), reason="Playwright is not installed here")
def test_a_real_drawing_makes_a_pdf_of_one_page_a_slide(tmp_path):
    try:
        out = carousel.render(SPEC, tmp_path, {"name": "Ada Lovelace", "line": "Engineer"}, stem="real")
    except carousel.CarouselError as exc:
        pytest.skip(str(exc))                                               # no Chrome or Edge on this PC
    data = out["pdf"].read_bytes()
    assert data.startswith(b"%PDF-") and len(re.findall(rb"/Type\s*/Page[^s]", data)) == 6
    assert [p.read_bytes()[:8] for p in out["pages"]] == [b"\x89PNG\r\n\x1a\n"] * 6


# ---- bold ------------------------------------------------------------------------------------
def test_bold_maps_letters_and_digits_and_reads_back_plain():
    assert bold.bold("Fix 2 bugs!") == "𝗙𝗶𝘅 𝟮 𝗯𝘂𝗴𝘀!" and bold.plain("𝗙𝗶𝘅 𝟮 𝗯𝘂𝗴𝘀!") == "Fix 2 bugs!"


@pytest.mark.parametrize("text,want", [
    ("**The fix** works", "𝗧𝗵𝗲 𝗳𝗶𝘅 works"),
    ("1️⃣ **Root cause**\nWhat broke.", "1️⃣ 𝗥𝗼𝗼𝘁 𝗰𝗮𝘂𝘀𝗲\nWhat broke."),
    ("def f(**kwargs):", "def f(**kwargs):"),
    ("f(**a, **b)", "f(**a, **b)"),
    ("** spaced **", "** spaced **"),
    ("**call(x)** stays", "**call(x)** stays"),
])
def test_claudes_bold_marks_become_linkedin_bold_and_code_stays(text, want):
    assert bold.from_marks(text) == want


def test_the_page_maps_bold_from_the_same_three_starting_points():
    js = (Path(__file__).parent.parent / "app" / "static" / "js" / "bold.js").read_text(encoding="utf-8")
    found = {name: int(value, 16) for name, value in re.findall(r"const (UPPER|LOWER|DIGIT) = (0x[0-9a-f]+);", js)}
    assert found == {"UPPER": bold.UPPER, "LOWER": bold.LOWER, "DIGIT": bold.DIGIT}
