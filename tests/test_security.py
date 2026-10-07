import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.security import safe_next

TOKEN = "t0ken-for-tests"


@pytest.fixture
def client(cfg, tmp_path, fake_runner):
    app = create_app(cfg, TOKEN, db_path=tmp_path / "s.db", runner=fake_runner)
    with TestClient(app, base_url=f"http://127.0.0.1:{cfg.port}") as c:
        yield c


def signed_in(c):
    c.cookies.set("studio_session", TOKEN)
    return c


def test_health_is_open(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["app"] == "linkedin-studio"


@pytest.mark.parametrize("cookie", [None, "wrong"])
def test_pages_need_the_session_cookie(client, cookie):
    if cookie:
        client.cookies.set("studio_session", cookie)
    assert client.get("/").status_code == 401
    assert client.get("/settings").status_code == 401


def test_auth_rejects_a_bad_token(client):
    assert client.get("/auth?token=nope", follow_redirects=False).status_code == 403


def test_auth_sets_a_strict_httponly_cookie(client):
    r = client.get(f"/auth?token={TOKEN}&next=/drafts", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/drafts"
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and f"studio_session={TOKEN.lower()}" in cookie


@pytest.mark.parametrize("value,expected", [("/drafts", "/drafts"), ("//evil.example", "/"),
                                            ("https://evil.example", "/"), ("/\\evil", "/"), (None, "/")])
def test_next_stays_on_this_app(value, expected):
    assert safe_next(value) == expected


def test_post_without_origin_or_referer_is_rejected(client):
    r = signed_in(client).post("/drafts/blank", data={"title": "x"})
    assert r.status_code == 403


@pytest.mark.parametrize("origin", ["http://evil.example", "http://localhost:8799", "http://127.0.0.1:8798",
                                    "null", "https://127.0.0.1:8799"])
def test_post_from_another_origin_is_rejected(client, origin):
    r = signed_in(client).post("/drafts/blank", data={"title": "x"}, headers={"Origin": origin})
    assert r.status_code == 403


def test_post_from_our_origin_is_accepted(client, cfg):
    r = signed_in(client).post("/drafts/blank", data={"title": "x"}, headers={"Origin": cfg.origin})
    assert r.status_code == 204 and r.headers["hx-redirect"] == "/drafts/1"


def test_referer_is_the_fallback(client, cfg):
    ok = signed_in(client).post("/drafts/blank", data={"title": "x"}, headers={"Referer": f"{cfg.origin}/drafts"})
    bad = client.post("/drafts/blank", data={"title": "x"}, headers={"Referer": "http://evil.example/x"})
    assert ok.status_code == 204 and bad.status_code == 403


def test_cookie_alone_is_not_enough_for_writes_and_origin_alone_is_not_enough_for_reads(client, cfg):
    assert client.post("/quit", headers={"Origin": cfg.origin}).status_code == 401


def test_wrong_host_header_is_rejected(client):
    r = signed_in(client).get("/", headers={"Host": "attacker.example:8799"})
    assert r.status_code == 421
