"""Settings › You in the preview (app/profile.py): the name, headline and photo a post's preview shows, kept beside the
database the app opened and nowhere else; only a PNG, JPEG or WebP photo, judged by its bytes; the studio's usual
rules for a change. Made-up words only."""
import base64
import json

import pytest
from conftest import TOKEN
from fastapi.testclient import TestClient
from support import PNG

from app import profile
from app.main import create_app

WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 24


def data_url(body: bytes, mime: str = "image/png") -> str:
    return f"data:{mime};base64,{base64.b64encode(body).decode()}"


@pytest.fixture
def web(cfg, tmp_path, fake_runner):
    app = create_app(cfg, TOKEN, db_path=tmp_path / "data" / "studio.db", runner=fake_runner)
    with TestClient(app, base_url=f"http://127.0.0.1:{cfg.port}", headers={"Origin": cfg.origin}) as client:
        client.cookies.set("studio_session", TOKEN)
        yield client, tmp_path / "data"


def files_under(folder):
    return {p for p in folder.rglob("*") if p.is_file() and not p.name.startswith("studio.db")}


def test_with_nothing_set_the_preview_says_you_and_your_headline(web):
    client, _data = web
    shown = client.get("/api/profile").json()
    assert (shown["name"], shown["headline"], shown["photo"]) == ("You", "Your headline", None)
    assert shown["saved"] == {"name": "", "headline": ""} and shown["most"] == {"name": 80, "headline": 220}
    assert client.get("/api/profile/photo").status_code == 404


def test_the_name_and_headline_are_kept_beside_the_database_and_nowhere_else(web, tmp_path):
    client, data = web
    before = files_under(tmp_path)
    reply = client.post("/api/profile", json={"name": "  Asha \t Rao ", "headline": "Builds tiny\ntools for writers"}).json()
    assert (reply["name"], reply["headline"]) == ("Asha Rao", "Builds tiny tools for writers")   # one line, single spaces
    assert files_under(tmp_path) - before == {data / "profile.json"}
    assert json.loads((data / "profile.json").read_text(encoding="utf-8")) == {"name": "Asha Rao", "headline": "Builds tiny tools for writers"}
    assert client.get("/api/profile").json()["saved"] == {"name": "Asha Rao", "headline": "Builds tiny tools for writers"}
    too_long = client.post("/api/profile", json={"name": "A" * 81, "headline": ""})
    assert too_long.status_code == 422 and "keep it to 80" in too_long.json()["error"]
    assert client.post("/api/profile", json={"name": "", "headline": "H" * 221}).status_code == 422
    assert client.get("/api/profile").json()["name"] == "Asha Rao"                     # a refusal changes nothing
    cleared = client.post("/api/profile", json={"name": " ", "headline": ""}).json()
    assert (cleared["name"], cleared["headline"]) == ("You", "Your headline") and not (data / "profile.json").exists()


@pytest.mark.parametrize("body,mime", [(PNG, "image/png"), (b"\xff\xd8\xff\xe0" + b"\x00" * 40, "image/jpeg"), (WEBP, "image/webp")])
def test_a_photo_is_kept_served_with_no_store_and_nosniff_and_remove_deletes_it(web, body, mime):
    client, data = web
    reply = client.post("/api/profile/photo", json={"data": data_url(body, "image/png")}).json()   # its bytes decide, not its label
    assert reply["photo"].startswith("/api/profile/photo?v=") and (data / "profile-photo").read_bytes() == body
    served = client.get(reply["photo"])
    assert served.status_code == 200 and served.content == body and served.headers["content-type"] == mime
    assert served.headers["cache-control"] == "no-store" and served.headers["x-content-type-options"] == "nosniff"
    gone = client.post("/api/profile/photo/remove", json={}).json()
    assert gone["photo"] is None and not (data / "profile-photo").exists()
    assert client.get("/api/profile/photo").status_code == 404


SVG = b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><rect width="9" height="9"/></svg>'
HTML = b"<!doctype html><script>alert(1)</script>"


REFUSED = {
    "svg": lambda: data_url(SVG, "image/svg+xml"),                      # a picture that can run script
    "html-as-png": lambda: data_url(HTML, "image/png"),                 # a page labelled as a PNG
    "gif": lambda: data_url(b"GIF89a" + b"\x00" * 20, "image/gif"),     # a GIF: not a profile photo here
    "too-big": lambda: data_url(b"\x89PNG\r\n\x1a\n" + b"\x00" * (profile.PHOTO_MAX + 1)),
    "a-link": lambda: "https://example.com/me.png",                     # not a picture at all
    "not-whole": lambda: "data:image/png;base64,iVBORw0KGgo***",
}


@pytest.mark.parametrize("case", list(REFUSED))
def test_svg_html_and_oversize_data_are_refused_and_nothing_is_kept(web, case):
    client, data = web
    refused = client.post("/api/profile/photo", json={"data": REFUSED[case]()})
    assert refused.status_code == 422 and refused.json()["error"]
    assert not (data / "profile-photo").exists() and client.get("/api/profile").json()["photo"] is None


def test_a_file_that_is_not_a_picture_is_never_served(web):
    client, data = web
    (data / "profile-photo").write_bytes(HTML)            # swapped on disk behind the studio's back
    assert client.get("/api/profile").json()["photo"] is None
    assert client.get("/api/profile/photo").status_code == 404


def test_a_change_from_another_site_or_as_a_form_is_refused(web, tmp_path):
    client, data = web
    before = files_under(tmp_path)
    evil = {"Origin": "http://evil.example"}
    assert client.post("/api/profile", json={"name": "Someone Else"}, headers=evil).status_code == 403
    assert client.post("/api/profile/photo", json={"data": data_url(PNG)}, headers=evil).status_code == 403
    assert client.post("/api/profile/photo/remove", json={}, headers=evil).status_code == 403
    assert client.post("/api/profile", data={"name": "Someone Else"}).status_code == 415
    assert client.post("/api/profile/photo", data={"data": data_url(PNG)}).status_code == 415
    assert files_under(tmp_path) == before
