# LinkedIn Studio — notes for Claude

A local, single-user Windows app over the linkedin-skills Claude Code skills (README.md says what
it does; read it first). Built like the owner's other studios: a launcher, a FastAPI server on
127.0.0.1, one plain HTML/CSS/JS page in an app window (sidebar, centre, Ask Claude), and Claude
Code run headless on the owner's own login. **This repository is public**: nothing personal is
ever committed (no emails, keys, real post text, Story Bank or voice content, no paths with a
username in them).

## Standing rules

- **A post goes out only on the owner's word**: Schedule… or Post now… and its confirmation, or the
  owner's own press of Approve and queue / Add to queue. Nothing Claude does in a chat schedules,
  queues or publishes anything (no tool of `app/mcp.py` does); comments and replies are drafted to
  copy, never posted.
- **The posting queue is one definition.** `app/posting.py` holds the posting times
  (`data\posting.json` beside the database; the default is the skills' Tue 8:00, Wed 9:30, Thu 8:00)
  and the line: an approved post with `posts.queue_pos`. A queued post's time is worked out afresh
  every time (`PostingQueue.lineup`: the next free posting time, one post a day, under the monthly
  limit) and never stored. It goes to Publora only through `Publisher.schedule`, once its time is
  inside the plan's days ahead (`Publisher.max_ahead`) and the plan has room for another scheduled
  post (`publora_at_once`), and leaves the line as it is claimed; Back to draft and the Trash take it out.
- **Never ask Publora for more than the plan allows.** `publishing.PLANS` holds Publora's plans (Starter:
  15 a month, 3 scheduled at a time, 7 days ahead; Pro: none, kept to 14 days here); config.local.toml
  keeps the three numbers (0 = no limit) and Settings › Publishing writes them and restarts the studio.
  `Publisher.schedule` refuses past any of them before anything is sent, so nothing fails at Publora.
  The background pass, like the light check, runs only with `check_publora` and never during setup.
  Schedule…'s recommended times, the Planner's Coming up and the plan's days all come from it.
- **Publora exactly once.** Scheduling is one transaction (approved → scheduling) and one request
  with an `Idempotency-Key`; Retry resends it with the same key. Post now… is the same path for the
  soonest time (`Publisher.post_now`, MIN_LEAD ahead: Publora has no "post at once"); its
  `posts.post_now` lets Retry still send it once that time has passed. A post with a picture records
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
  (`data\profile.json`, `data\profile-photo`). The page's preview reads them; a carousel's slides carry them only while
  the owner has ticked Put them on carousels too (`profile.on_carousels`, off unless set). Never Claude or ChatGPT.
  A photo is kept and served only when its bytes are a PNG, JPEG or WebP (`publishing.sniff_image`), with no-store
  and nosniff. The demo, the tests and the Guide's pictures show You / Your headline.
- **Post style is one definition.** `app/style.py` holds the four sliders (Hook 1-5, Tone 1-5, Emojis 0-3, Layout 1-2),
  the words each step gives the writer and the rule that it stays professional. Every run that writes a post gets `style.words`
  (Ask Claude, Revise and Restyle, Hot topics' drafts, the Repurposer); the page takes the steps'
  names from `/api/style`, never its own copy. The default is `data\style.json` beside the database; a Restyle makes
  its sliders the post's own (`posts.style`). Restyle is a revision (`how: "style"`), so it waits beside the post
  like New hook does.
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
  it is stored. Settings, Schedule (`claude.sign_in`) and the setup screen show it; Save refuses
  a login folder signed in to nobody, and an unreadable answer never blocks. Tests answer it with
  `tests/fake_claude.py` only.
- **The Trash keeps posts, never sends them.** A post in it is `posts.trashed_at`, refused by every post endpoint
  (`api_posts.find`), by the studio's tools (`mcp.py`) and by `Publisher.schedule`/`retry`. Scheduled and sending
  posts, a post Publora holds a draft of, and a post Claude is working on are never moved there. A published post
  can be (it stays on LinkedIn); deleted forever, it leaves its time in `spent`, which `quota_used` and the queue
  still count. Delete forever and Empty trash need `confirmed: true`, touch only posts in the Trash, and the page
  names what goes first.
- **A locked post's chat** (anything but a draft) is offered no `set_post_text` and no
  `make_image` (`flows.post_chat_tools`): no rewrite and no ChatGPT picture is spent on a post
  that cannot change.
- **The Guide's pictures** come from `dev/guide_shots.py` on the demo only: made-up data, a folder
  with no user name, no Settings, setup screen or Schedule's Claude card; it refuses a picture whose
  text holds the PC's user name or home folder. Retake them when a screen changes; together they
  stay under about 1.5 MB.
- **What goes out with a post is one list.** `posts.picture_ids` (images.py): up to `images.MAX_PICTURES` (10, Publora's
  limit for LinkedIn) pictures in order, or one carousel alone. A carousel is an `images` row with the PDF, its `spec`
  and a PNG of each slide (`<stem>-<n>.png`), drawn by `app/carousel.py` from a spec Claude writes (`make_carousel`) or
  drawn again from its own. Its words are drawn as text, never as a picture of text. `bold.py` and `js/bold.js` are one
  mapping for LinkedIn's bold; the writer's `**words**` become it wherever Claude's text lands in a post.
- Never run `chrome.exe --version`.

## How it fits together

| Where | What |
|---|---|
| `app/main.py` | `create_app`: the middleware, `/api/state` (posts, jobs, what changed), jobs, images, `/mcp`; the page's files at `/static/v-<build>/` (`build_of`: their hash, so an update changes their address and an app window never runs an old copy; `<meta name="studio-static">` says it, for the browser checks) and `/static/`, both no-cache |
| `app/api_posts.py` | A post: save, audit, revise, approve, schedule, Post now, retry, Check now, cancel, versions (compared with now), picture, its chat and attachments, Move to Trash, New draft from this |
| `app/api_trash.py` | The Trash: its list, Put back, Delete forever and Empty trash (confirmed); a post in the Trash is `posts.trashed_at`, and `api_posts.find` refuses it everywhere |
| `app/api_pages.py` | Schedule (Coming up, this month), Hot topics (its list, Refresh, Draft), Story Bank & Voice chats, Tools (each tool's earlier results, Start a post from this), Settings (ChatGPT card, Claude's account, You in the preview, Posting times), setup, Guide (its pictures) |
| `app/posting.py` | The posting queue: the posting times, each queued post's time (worked out, never stored), handing the ones inside the window to Publora through `Publisher.schedule`, the background pass |
| `app/hot.py`, `app/static/js/hot.js` | Hot topics: `SOURCES` (the teams' feeds, newsletter issues read article by article (`parse_issues`), forums, engineering blogs, Simon Willison on the niche's words), dev.to's week (`DEVTO`, one tag at a time) and Hacker News's stories (Algolia, `HN_POINTS`+, title words `NICHE`), `DAYS` back, one item per article (`key_of`); read under `USER_AGENT`, public web only (`public`, on each redirect too), in the background (`Reader`, table `hot`). Each read is ranked for the owner: `hot_rank` jobs of `BATCH` items one at a time (`rank_next`, chained by `flows.hot_rank_done`; `skills._hot_rank` with `RUBRIC`, `RANK_POLICY` refuses the Story Bank), checked into `hot_ranks` (`keep_ranks`: rank, why, angle, same_as). Draft is an ordinary `draft` job with `news` and the rank's `angle` (`flows.draft_prepare` reads its text once, `skills._news` hands it over untrusted, `draft_done` keeps the link in the first comment and `posts.news`) |
| `app/ask_about.py` | Ask me about this on a Story Bank entry: the `focus` checked against the file's own entries (`render.doc_sections`), capped; the new conversation's opening message |
| `app/profile.py` | You in the preview: the name, headline and photo kept beside the database |
| `app/style.py`, `app/static/js/style.js` | Post style: the three sliders, each step's words for the writer, the default beside the database; the sliders the page draws in Settings and a post's Style panel |
| `app/jobs.py`, `app/flows.py` | One job at a time with its numbered steps; what each job does when it ends |
| `app/skills.py`, `app/claude_runner.py` | Each action's skill, prompt and tools; the `claude -p` command, its env and MCP config |
| `app/mcp.py`, `app/codex.py` | The post chat's tools (`set_post_text`, `make_image`, `record_audit`, `fetch_post`); ChatGPT's pictures through `codex.exe` |
| `app/publishing.py` | Publora: schedule (with a picture), Post now (the soonest time), retry, back to draft, refresh (read-only: published with its LinkedIn link, failed in Publora's words) |
| `app/status_check.py` | The light check: due scheduled posts asked of Publora (get-post only) in the background, every few minutes; what it heard, for the post's notice |
| `app/versions.py`, `app/images.py`, `app/attached.py` | A post's versions, its pictures and carousels (what goes out, in order), a chat's attached files |
| `app/rank.py` | A post's rank: 1-10 with why and what would lift it (Claude's `set_rank`, judged by `rank.RUBRIC`, or the owner's own number); drafts list best first |
| `app/carousel.py`, `app/bold.py`, `app/static/js/bold.js` | Carousels and cards: the spec checked (`LOOKS` × `TINTS`, `FORMATS`, `KINDS`, at most `MAX_ART` art), its slides drawn as HTML (each look a CSS block; `FIT` shrinks what outgrows a slide, grows a card), then a PDF and a PNG a slide with Playwright (a card: its one PNG, kept as a picture, source `card`); ChatGPT art drawn once (`draw_art`, `art_prompt`) and kept as `art-<hash>.png` beside the pictures (`images.art_of`, gone when no spec shows it); Try another look is `next_look` through `CYCLE`; LinkedIn's bold, the same mapping on both sides |
| `app/static/` | `index.html`, `app.css`, `app.js` and `js/` (core, sidebar, editor, post, assist, schedule, hot, bank, tools, settings, guide, jobs, md, audit, palette, trash, wdiff, precheck, search) |
| `dev/demo_server.py` | The page on made-up data with stand-ins for Claude (and its sign-in), Publora, ChatGPT and Hot topics' news (example.com) |
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
