"""The Apify key, which fetches a LinkedIn post from its link (`flows.fetch_post_text`).

It is the Windows user variable APIFY_TOKEN: the one place the owner's studios keep it, set from Settings › Publishing
(the owner's word, 17 Nov 2026: "Apify key in Settings, in all places where its used"). It is read there first, so a key
set in another studio reaches this one while it runs; then this process's environment; then the skills folder's .env,
where linkedin-skills' own setup puts it. Only a value shaped like a key is sent, and only to Apify, which is asked
whether it takes it before it is kept. Never shown, logged, written to a file by the studio, or given to Claude
(`claude_runner.BLOCKED_ENV`).
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

from .config import Config

API = "https://api.apify.com/v2"   # tests point it at a stand-in
VARIABLE = "APIFY_TOKEN"           # tests name one of their own
REGISTRY = True                    # the Windows user variable; tests and the demo keep the key to their own process
SHAPE = re.compile(r"apify_api_[A-Za-z0-9]{20,80}")
WHERE = "Apify Console › Settings › API & Integrations"
FRESH = 60                         # seconds the month's figure is kept before Apify is asked again

_month = {"read": 0.0, "for": None, "value": None}
_month_lock = threading.Lock()


def month(cfg: Config) -> dict | None:
    """The key's account's month as Apify says it (/users/me/limits): {"used", "of", "renews", "when"}, dollars used and the
    month's limit, the day the next month starts, when it was read (17 Nov, 6:41 pm); None with no key or no answer yet.
    Asked again after FRESH seconds; a failed ask keeps the last figure. Each person's own account: nothing is assumed."""
    secret = token(cfg)
    if not secret:
        return None
    asked = (API, secret)
    with _month_lock:
        if _month["for"] == asked and time.monotonic() - _month["read"] < FRESH:
            return _month["value"]
        if _month["for"] != asked:
            _month["value"] = None
        try:
            request = urllib.request.Request(f"{API}/users/me/limits", headers={"Authorization": f"Bearer {secret}", "User-Agent": "LinkedIn Studio"})
            with urllib.request.urlopen(request, timeout=8) as reply:
                data = (json.loads(reply.read().decode("utf-8") or "null") or {}).get("data") or {}
            used, of = float((data.get("current") or {}).get("monthlyUsageUsd") or 0), (data.get("limits") or {}).get("maxMonthlyUsageUsd")
            ends = str((data.get("monthlyUsageCycle") or {}).get("endAt") or "")[:10]
            now = datetime.now()
            _month["value"] = {"used": round(used, 3), "of": float(of) if of is not None else None,
                               "renews": (date.fromisoformat(ends) + timedelta(days=1)).isoformat() if ends else "",
                               "when": f"{now.day} {now:%b}, {now.hour % 12 or 12}:{now:%M} {'am' if now.hour < 12 else 'pm'}"}
        except (OSError, ValueError, TypeError, AttributeError):   # urllib's errors are OSErrors
            pass
        _month["read"], _month["for"] = time.monotonic(), asked
        return _month["value"]


def token(cfg: Config) -> str:
    """The key, or "" when there is none."""
    if REGISTRY and sys.platform == "win32":
        try:
            import winreg  # noqa: PLC0415  (Windows only)
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as found:
                value = str(winreg.QueryValueEx(found, VARIABLE)[0]).strip()
            if value:
                return value
        except OSError:
            pass
    from .publishing import read_env  # noqa: PLC0415  (publishing reads the key through here)
    return os.environ.get(VARIABLE, "").strip() or read_env(cfg).get("APIFY_TOKEN", "")


def set_token(value) -> str | None:
    """Keep a new key once Apify takes it. What went wrong, in the owner's words, or None."""
    value = str(value or "").strip()
    if not value:
        return f"Paste your Apify API token: {WHERE}."
    if not SHAPE.fullmatch(value):
        return f"That isn't an Apify API token: one starts apify_api_ ({WHERE})."
    asked = urllib.request.Request(f"{API}/users/me", headers={"Authorization": f"Bearer {value}", "User-Agent": "LinkedIn Studio"})
    try:
        with urllib.request.urlopen(asked, timeout=30):
            pass
    except urllib.error.HTTPError as exc:
        return f"Apify didn't take that key: copy it again from {WHERE}." if exc.code == 401 else f"Apify answered {exc.code}. Try again in a while."
    except (urllib.error.URLError, OSError) as exc:
        return f"Apify could not be reached: {getattr(exc, 'reason', exc)}"
    if REGISTRY and sys.platform == "win32":
        try:
            import winreg  # noqa: PLC0415  (Windows only)
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as kept:
                winreg.SetValueEx(kept, VARIABLE, 0, winreg.REG_SZ, value)
        except OSError as exc:
            return f"Windows didn't keep the key: {exc.strerror or exc}"
        try:   # programs started from now on see it, as after setting it by hand
            import ctypes  # noqa: PLC0415
            ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 0x0002, 3000, None)
        except (OSError, AttributeError):
            pass
    os.environ[VARIABLE] = value
    return None
