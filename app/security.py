"""Keep other websites in the same browser away from the local API.

- Host must be exactly 127.0.0.1:<port> (blocks DNS-rebinding names).
- Every request except /health, /auth, /mcp and /static needs the per-launch session cookie
  (HttpOnly, SameSite=Strict), which /auth sets from the token in the launcher's URL.
- Every state-changing request needs Origin (or, failing that, Referer) on our own origin, and a
  change to /api is JSON, which a page on another site can't send without asking first.
- /mcp is for Claude alone: it takes the running request's own token (checked by the route), never
  the cookie, and answers nothing once that request has ended.
"""
from __future__ import annotations

import hmac
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

COOKIE = "studio_session"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

DENIED_PAGE = """<!doctype html><html lang="en"><meta charset="utf-8"><title>LinkedIn Studio</title>
<meta name="color-scheme" content="light dark"><link rel="icon" type="image/svg+xml" href="/static/icon.svg">
<script src="/static/theme.js"></script><link rel="stylesheet" href="/static/app.css">
<body><main class="stopped"><div class="panel stopped-card">
<h1>Open LinkedIn Studio from its shortcut</h1>
<p>{reason} This page only works in the window the launcher opens. If you closed it,
double-click <b>LinkedIn Studio</b> again.</p></div></main></body></html>"""


def same_token(a: str | None, b: str) -> bool:
    return bool(a) and hmac.compare_digest(a.encode(), b.encode())


def safe_next(value: str | None) -> str:
    if value and value.startswith("/") and not value.startswith("//") and "\\" not in value:
        return value
    return "/"


class LocalOnly(BaseHTTPMiddleware):
    def __init__(self, app, *, token: str, port: int):
        super().__init__(app)
        self.token = token
        self.port = port
        self.origin = f"http://127.0.0.1:{port}"

    def deny(self, request: Request, reason: str, status: int = 403) -> Response:
        if request.url.path.startswith(("/api", "/mcp")):
            return JSONResponse({"error": reason}, status_code=status)
        return HTMLResponse(DENIED_PAGE.format(reason=reason), status_code=status)

    async def dispatch(self, request: Request, call_next):
        if request.headers.get("host") != f"127.0.0.1:{self.port}":
            return self.deny(request, "Wrong host name.", 421)
        path = request.url.path
        if path == "/auth":
            if request.method != "GET" or not same_token(request.query_params.get("token"), self.token):
                return self.deny(request, "This link is not valid for the running app.")
            resp = RedirectResponse(safe_next(request.query_params.get("next")), status_code=303)
            resp.set_cookie(COOKIE, self.token, httponly=True, samesite="strict", path="/")
            return resp
        if path == "/health" or path == "/mcp" or path.startswith("/static/"):
            return await call_next(request)
        if not same_token(request.cookies.get(COOKIE), self.token):
            return self.deny(request, "No valid session for this launch.", 401)
        if request.method not in SAFE_METHODS:
            if not self.origin_ok(request):
                return self.deny(request, "Request from another site was blocked.")
            if path.startswith("/api/") and "application/json" not in request.headers.get("content-type", ""):
                return self.deny(request, "Changes are sent as JSON.", 415)
        return await call_next(request)

    def origin_ok(self, request: Request) -> bool:
        origin = request.headers.get("origin")
        if origin is not None:
            return origin == self.origin
        referer = request.headers.get("referer")
        if not referer:
            return False
        parts = urlsplit(referer)
        return f"{parts.scheme}://{parts.netloc}" == self.origin
