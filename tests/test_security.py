"""Other websites in the same browser can't use the studio: the cookie, the Origin, JSON for changes, the Host, and
/mcp only on the running request's own token."""
import pytest
from conftest import TOKEN
from fastapi.testclient import TestClient

from app.main import create_app
from app.security import safe_next


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
def test_the_page_and_the_api_need_the_session_cookie(client, cookie):
    if cookie:
        client.cookies.set("studio_session", cookie)
    assert client.get("/").status_code == 401
    for path in ("/api/state", "/api/settings", "/api/post/1", "/api/planner", "/api/bank"):
        r = client.get(path)
        assert r.status_code == 401 and "error" in r.json(), path


def test_auth_rejects_a_bad_token(client):
    assert client.get("/auth?token=nope", follow_redirects=False).status_code == 403


def test_auth_sets_a_strict_httponly_cookie(client):
    r = client.get(f"/auth?token={TOKEN}&next=/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and f"studio_session={TOKEN.lower()}" in cookie


@pytest.mark.parametrize("value,expected", [("/", "/"), ("//evil.example", "/"),
                                            ("https://evil.example", "/"), ("/\\evil", "/"), (None, "/")])
def test_next_stays_on_this_app(value, expected):
    assert safe_next(value) == expected


def test_a_change_without_origin_or_referer_is_rejected(client):
    r = signed_in(client).post("/api/posts/new", json={})
    assert r.status_code == 403
    assert client.get("/api/state").json()["posts"] == []


@pytest.mark.parametrize("origin", ["http://evil.example", "http://localhost:8799", "http://127.0.0.1:8798",
                                    "null", "https://127.0.0.1:8799"])
def test_a_change_from_another_origin_is_rejected(client, origin):
    r = signed_in(client).post("/api/posts/new", json={}, headers={"Origin": origin})
    assert r.status_code == 403


def test_a_change_from_our_origin_is_accepted(client, cfg):
    r = signed_in(client).post("/api/posts/new", json={}, headers={"Origin": cfg.origin})
    assert r.status_code == 200 and r.json() == {"id": 1}


def test_referer_is_the_fallback(client, cfg):
    ok = signed_in(client).post("/api/posts/new", json={}, headers={"Referer": f"{cfg.origin}/"})
    bad = client.post("/api/posts/new", json={}, headers={"Referer": "http://evil.example/x"})
    assert ok.status_code == 200 and bad.status_code == 403


def test_a_change_is_json_never_a_form_another_site_could_send(client, cfg):
    """A plain form post (another site's page can send one without asking) never reaches the API."""
    r = signed_in(client).post("/api/posts/new", data={"title": "x"}, headers={"Origin": cfg.origin})
    assert r.status_code == 415
    r = client.post("/api/quit", content=b"{}", headers={"Origin": cfg.origin, "Content-Type": "text/plain"})
    assert r.status_code == 415
    assert client.get("/api/state").json()["posts"] == []


def test_cookie_alone_is_not_enough_for_changes_and_origin_alone_is_not_enough_for_anything(client, cfg):
    assert client.post("/api/quit", json={}, headers={"Origin": cfg.origin}).status_code == 401
    assert signed_in(client).post("/api/quit", json={}).status_code == 403


def test_wrong_host_header_is_rejected(client):
    r = signed_in(client).get("/api/state", headers={"Host": "attacker.example:8799"})
    assert r.status_code == 421


@pytest.mark.parametrize("auth", [None, "Bearer", "Bearer wrong-token", f"Bearer {TOKEN}", "Basic abc"])
def test_mcp_answers_only_the_running_requests_own_token(client, auth):
    """Not the cookie, not the launch token, not a guess: /mcp is for one running chat request and nothing else."""
    signed_in(client)
    headers = {"Authorization": auth} if auth else {}
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers=headers)
    assert r.status_code == 401 and "tools" not in r.text
