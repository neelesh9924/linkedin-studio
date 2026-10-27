# LinkedIn Studio — notes for Claude

A local, single-user Windows app over the linkedin-skills Claude Code skills (README.md says what
it does; read it first). Built like the owner's other studios: a launcher, a FastAPI server on
127.0.0.1, one plain HTML/CSS/JS page in an app window (sidebar, centre, Ask Claude), and Claude
Code run headless on the owner's own login. **This repository is public**: nothing personal is
ever committed (no emails, keys, real post text, Story Bank or voice content, no paths with a
username in them).

## Standing rules

- **A post goes out only on the owner's word**: Schedule… and its confirmation. Nothing Claude
  does in a chat schedules or publishes anything; comments and replies are drafted to copy, never
  posted.
- **Publora exactly once.** Scheduling is one transaction (approved → scheduling) and one request
  with an `Idempotency-Key`; Retry resends it with the same key. A post with a picture records
  each of Publora's four media steps (`posts.media`, `posts.media_step`), and Retry carries on
  from the one that failed. Keep a picture's file while its post is scheduling. Never call the
  real Publora from tests or checks; never read or print the keys (the skills folder's `.env`).
- **The Story Bank and voice profile are private.** Never print, copy or commit what is in them,
  and never change the owner's skills clone by hand; the app keeps the two files out of git
  there itself (`app/privacy.py`).
- **ChatGPT's pictures use only the Codex home in `config.local.toml` (`codex_home`).** It has no
  default: never the PC's own `~/.codex`, which may be signed in to another account; never sign
  it in, read it or change it. Tests give Codex a home of their own and never call the real one:
  each picture spends the owner's ChatGPT allowance.
- **Claude's tools are the backend's choice** (`claude_runner.py`, `skills.py`): Skill and Read in
  the skills folder; Edit of their one file for the two interview chats; for a post's chat also
  the studio's own MCP tools (`app/mcp.py`) behind a per-run token, and Read of that chat's
  attachments folder. No Bash, no web, no other MCP server.
- **The owner's database opens as it is.** Schema changes are additive (`db.py` MIGRATIONS).
  Check one on a copy of a real database (`dev/demo_server.py --db <copy>`); never write to the
  real `data\` from tests or checks.
- **The safety model stays**: 127.0.0.1 only; the per-launch token becomes an HttpOnly,
  SameSite=Strict cookie; every change needs the studio's Origin and a JSON body
  (`security.py`); a timeout or Cancel kills the whole process tree (`winjob.py`).
- **Shared files are never edited here alone**: `app/attachments.py`, `app/static/attach.js`,
  `app/static/attach.css` and `tests/test_attachments.py` are copies shared byte for byte with
  the other studios built alike.
- Never run `chrome.exe --version`.

## How it fits together

| Where | What |
|---|---|
| `app/main.py` | `create_app`: the middleware, `/api/state` (posts, jobs, what changed), jobs, images, `/mcp` |
| `app/api_posts.py` | A post: save, audit, revise, approve, schedule, retry, cancel, versions, picture, its chat and attachments |
| `app/api_pages.py` | Planner, Story Bank & Voice chats, Tools, Settings (ChatGPT card), setup, Guide |
| `app/jobs.py`, `app/flows.py` | One job at a time with its numbered steps; what each job does when it ends |
| `app/skills.py`, `app/claude_runner.py` | Each action's skill, prompt and tools; the `claude -p` command, its env and MCP config |
| `app/mcp.py`, `app/codex.py` | The post chat's tools (`set_post_text`, `make_image`, `record_audit`, `fetch_post`); ChatGPT's pictures through `codex.exe` |
| `app/publishing.py` | Publora: schedule (with a picture), retry, back to draft, check |
| `app/versions.py`, `app/images.py`, `app/attached.py` | A post's versions, its pictures, a chat's attached files |
| `app/static/` | `index.html`, `app.css`, `app.js` and `js/` (core, sidebar, editor, post, assist, planner, bank, tools, settings, guide, jobs, md) |
| `dev/demo_server.py` | The page on made-up data with stand-ins for Claude, Publora and ChatGPT |

## Working here

- Windows. `.venv\Scripts\python -m pytest`; run the files you touched, the whole suite once at
  the end. `tests/test_browser.py` needs `requirements-dev.txt` (Playwright) and Chrome or Edge.
- Look at the page through `dev/demo_server.py`: nothing real is touched.
- The Guide is words only (`app/guide.py`, `app/static/js/guide.js`); keep its figures in step
  with the code.

## Done on 27 Oct 2026

- The page rebuilt like the owner's other studios: a sidebar of posts with Planner, Story Bank &
  Voice, Tools, Guide and Settings; the post as LinkedIn shows it, edited in place; Ask Claude, a
  chat kept with each post, which changes the post through the studio's own tools and keeps each
  change as a version. Jinja and htmx are gone: a JSON API and plain ES modules.
- ChatGPT's pictures for a post (`app/codex.py`), a post's picture going out through Publora's
  media upload exactly once, and files attached to any chat (the shared attachments module).
- The Guide's pictures were dropped with the old screens; its words describe the new ones.
