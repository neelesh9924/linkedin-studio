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
- **Which Claude account.** `health.claude_account` runs `claude auth status --json` with
  `build_env` (the configured login folder, no API key); it sends Claude no request and nothing of
  it is stored. Settings, the Planner (`claude.sign_in`) and the setup screen show it; Save refuses
  a login folder signed in to nobody, and an unreadable answer never blocks. Tests answer it with
  `tests/fake_claude.py` only.
- **The Trash keeps posts, never sends them.** A post in it is `posts.trashed_at`, refused by every post endpoint
  (`api_posts.find`), by the studio's tools (`mcp.py`) and by `Publisher.schedule`/`retry`. Scheduled, sending and
  published posts, a post Publora holds a draft of, and a post Claude is working on are never moved there. Delete
  forever and Empty trash need `confirmed: true`, touch only posts in the Trash, and the page names what goes first.
- **A locked post's chat** (anything but a draft) is offered no `set_post_text` and no
  `make_image` (`flows.post_chat_tools`): no rewrite and no ChatGPT picture is spent on a post
  that cannot change.
- **The Guide's pictures** come from `dev/guide_shots.py` on the demo only: made-up data, a folder
  with no user name, no Settings, setup screen or Planner Claude card; it refuses a picture whose
  text holds the PC's user name or home folder. Retake them when a screen changes; together they
  stay under about 1.5 MB.
- Never run `chrome.exe --version`.

## How it fits together

| Where | What |
|---|---|
| `app/main.py` | `create_app`: the middleware, `/api/state` (posts, jobs, what changed), jobs, images, `/mcp` |
| `app/api_posts.py` | A post: save, audit, revise, approve, schedule, retry, cancel, versions, picture, its chat and attachments, Move to Trash, New draft from this |
| `app/api_trash.py` | The Trash: its list, Put back, Delete forever and Empty trash (confirmed); a post in the Trash is `posts.trashed_at`, and `api_posts.find` refuses it everywhere |
| `app/api_pages.py` | Planner, Story Bank & Voice chats, Tools, Settings (ChatGPT card, Claude's account), setup, Guide (its pictures) |
| `app/jobs.py`, `app/flows.py` | One job at a time with its numbered steps; what each job does when it ends |
| `app/skills.py`, `app/claude_runner.py` | Each action's skill, prompt and tools; the `claude -p` command, its env and MCP config |
| `app/mcp.py`, `app/codex.py` | The post chat's tools (`set_post_text`, `make_image`, `record_audit`, `fetch_post`); ChatGPT's pictures through `codex.exe` |
| `app/publishing.py` | Publora: schedule (with a picture), retry, back to draft, check |
| `app/versions.py`, `app/images.py`, `app/attached.py` | A post's versions, its pictures, a chat's attached files |
| `app/static/` | `index.html`, `app.css`, `app.js` and `js/` (core, sidebar, editor, post, assist, planner, bank, tools, settings, guide, jobs, md, audit, palette, trash) |
| `dev/demo_server.py` | The page on made-up data with stand-ins for Claude (and its sign-in), Publora and ChatGPT |
| `dev/guide_shots.py` | The Guide's pictures, taken on the demo into `app/static/guide/` |

## Working here

- Windows. `.venv\Scripts\python -m pytest`; run the files you touched, the whole suite once at
  the end. The browser checks (`tests/test_browser*.py`) need `requirements-dev.txt` (Playwright)
  and Chrome or Edge; without Playwright they are skipped, silently.
- Look at the page through `dev/demo_server.py`: nothing real is touched.
- The Guide's words live in `app/guide.py` (figures passed in from the code that enforces them;
  `SHORTCUTS` is the one list of keys, which the page's ? dialog reads too) and its pictures in
  `app/static/guide/` (`guide.SHOT_WORDS`). Story Bank headings take `doc-` ids (`md.js`
  `anchorOf`, `render.doc_sections`) so they never clash with the page's own.

## Done on 27 Oct 2026

- The page rebuilt like the owner's other studios: a sidebar of posts with Planner, Story Bank &
  Voice, Tools, Guide and Settings; the post as LinkedIn shows it, edited in place; Ask Claude, a
  chat kept with each post, which changes the post through the studio's own tools and keeps each
  change as a version. Jinja and htmx are gone: a JSON API and plain ES modules.
- ChatGPT's pictures for a post (`app/codex.py`), a post's picture going out through Publora's
  media upload exactly once, and files attached to any chat (the shared attachments module).
- The Guide's pictures were dropped with the old screens, then retaken on the new ones
  (`dev/guide_shots.py`).
- Ask Claude on a locked post, the Claude account in Settings and setup, Settings' sections with
  addresses, and the Trash (Put back, Delete forever…, Empty trash).
- Later the same day, the owner's other studios' tweaks: the Trash (`app/api_trash.py`,
  `js/trash.js`; the API, the studio's tools and `publishing.py` all refuse a post in it), New
  draft from this, your own edits kept as versions (a big cut, leaving the text, Approve), the
  title saved alone; the command palette (Ctrl+K, `js/palette.js`), Alt+N, Ctrl+/, Alt+↑/↓, ?,
  skip links; the post read aloud as text with an Edit text button, the focus kept through polls
  and redraws, a real menu for Revise and real tabs in Tools, one audit view (`js/audit.js`),
  Copy and Copy first comment, toasts clear of Send; three columns from 941 to 1,180 px and a
  maximized window; a request for a post already on its way asks once more after it
  (`post.js loadPost`), so no change waits for the next poll. The Guide's pictures were retaken on
  the merged page, the Trash's among them.
- Two fixes found on the merged page: a post opened again after another page lost its top bar's
  next step (`route()` now forgets the drawn buttons), and the demo's Publora stand-in wrote
  through a second database object, so Approve and Back to draft never moved the demo page's poll
  (`dev/demo_server.py` hands it the app's own).
