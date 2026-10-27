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
- **The light check only reads.** `app/status_check.py` asks Publora's get-post about scheduled posts whose time has
  passed, in a background thread kicked by `/api/state`: one check at a time, at most every 3 minutes, never during
  setup or for the Trash. It is off unless `create_app(..., check_publora=True)` (`launch.py`, `python -m app`, the
  demo); tests turn it on only with a stand-in Publora. Only a `https://www.linkedin.com/` address is ever kept as a
  post's link (`posts.published_url`).
- **The Story Bank and voice profile are private.** Never print, copy or commit what is in them,
  and never change the owner's skills clone by hand; the app keeps the two files out of git
  there itself (`app/privacy.py`).
- **You in the preview stays on this PC.** `app/profile.py` keeps the name, headline and photo beside the database
  (`data\profile.json`, `data\profile-photo`). Only the page's preview reads them, never Claude, Publora or ChatGPT.
  A photo is kept and served only when its bytes are a PNG, JPEG or WebP (`publishing.sniff_image`), with no-store
  and nosniff. The demo, the tests and the Guide's pictures show You / Your headline.
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
| `app/api_posts.py` | A post: save, audit, revise, approve, schedule, retry, Check now, cancel, versions (compared with now), picture, its chat and attachments, Move to Trash, New draft from this |
| `app/api_trash.py` | The Trash: its list, Put back, Delete forever and Empty trash (confirmed); a post in the Trash is `posts.trashed_at`, and `api_posts.find` refuses it everywhere |
| `app/api_pages.py` | Planner, Story Bank & Voice chats, Tools (each tool's earlier results, Start a post from this), Settings (ChatGPT card, Claude's account, You in the preview), setup, Guide (its pictures) |
| `app/profile.py` | You in the preview: the name, headline and photo kept beside the database |
| `app/jobs.py`, `app/flows.py` | One job at a time with its numbered steps; what each job does when it ends |
| `app/skills.py`, `app/claude_runner.py` | Each action's skill, prompt and tools; the `claude -p` command, its env and MCP config |
| `app/mcp.py`, `app/codex.py` | The post chat's tools (`set_post_text`, `make_image`, `record_audit`, `fetch_post`); ChatGPT's pictures through `codex.exe` |
| `app/publishing.py` | Publora: schedule (with a picture), retry, back to draft, refresh (read-only: published with its LinkedIn link, failed in Publora's words) |
| `app/status_check.py` | The light check: due scheduled posts asked of Publora (get-post only) in the background, every few minutes; what it heard, for the post's notice |
| `app/versions.py`, `app/images.py`, `app/attached.py` | A post's versions, its pictures, a chat's attached files |
| `app/static/` | `index.html`, `app.css`, `app.js` and `js/` (core, sidebar, editor, post, assist, planner, bank, tools, settings, guide, jobs, md, audit, palette, trash, wdiff, precheck) |
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
- Second pass, the same evening, from the first pass's deferred list:
  - Publora's answer by itself: `posts.published_url`; `Publisher.refresh` read-only (published
    with its LinkedIn link, failed in Publora's own words); the light check
    (`app/status_check.py`); Check now in words and Open on LinkedIn in the top bar, which says a
    scheduled post's time once; Compare with now in the gear's Versions, and going back said in
    the post's chat; one word diff (`js/wdiff.js`) for Versions, the revision card and Tools; the
    demo's Claude replies in plain words and its Publora sends a post at its time.
  - The frame: Before you confirm in the Schedule… dialog (`js/precheck.js`: blanks, LinkedIn's
    limits, a link in the text, a picture not on the post, a time gone or far from the plan's,
    the month's last posts; warnings only, said as the dialog opens); the sidebar's Earlier fold
    for published and cancelled posts (no count, closed at first and kept as left, the open post
    always shown); Ask Claude's panel resized from its left edge (drag, ←/→, Home/End,
    double-click resets; kept, never squeezing the centre below its 941 px room); "Claude is
    working · N min" (the minutes shown, not said each minute); Approved's own "ready" colour.
  - Pages: Settings › You in the preview (`app/profile.py`), shown in the post's head and first
    comment and redrawn at once on a save; the Planner shows This week first, and Getting set up
    is done once the Publora key is set; Tools keep each tool's last ten results under Earlier
    results; Start a post from this (a Humanize rewrite, an audited draft with its findings, a
    hook's template, a repurposed post; refused for comments and the profile review) replaced
    Save as a post, and the old Repurpose route went with it.
  - Found on the merged page: a post back in draft with no first comment kept that box hidden
    (`editor.js drawComment`); the sidebar's line now follows Approve and Back to draft at once;
    the top bar's chip follows each poll one way (`post.js chipAfterPoll`); the Guide's pictures
    were retaken, and their guard against the Planner's Claude card reads its "Account" row.
  - Left for the owner's word: Draft all, Story Bank's Ask me about this, a separate local Back
    up, the stage bar's results chip, a rail or drawer layout under 1,180 px. Dropped: Back to
    draft for a cancelled post (New draft from this does that).
