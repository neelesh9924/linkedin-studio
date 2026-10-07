"""Developer entry: `python -m app` serves on the configured port and prints the sign-in URL."""
from __future__ import annotations

import secrets

import uvicorn

from .config import HOST, load_config
from .main import create_app


def main() -> None:
    cfg = load_config()
    token = secrets.token_urlsafe(32)
    holder: dict = {}
    app = create_app(cfg, token, on_quit=lambda: setattr(holder["server"], "should_exit", True))
    print(f"Open: http://{HOST}:{cfg.port}/auth?token={token}", flush=True)
    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=cfg.port, log_config=None, access_log=False,
                                           timeout_graceful_shutdown=5))
    holder["server"] = server
    server.run()


if __name__ == "__main__":
    main()
