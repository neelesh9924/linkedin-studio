# linkedin-skills inventory (Phase 0)

Checked on 7 Oct 2026 against `linkedin-skills` at `2f00424` (v1.1.16), Claude Code 2.1.292
(the native `claude.exe` in `.local\bin`, a real `.exe`, not an npm `.cmd` shim).

## How Claude Code sees the skills

- `.claude\skills\*` are 12 real directory symlinks to `skills\*` (Developer Mode on, system
  `core.symlinks=true`). Verified with `Get-ChildItem` (LinkType `SymbolicLink`) and by a headless run.
- With cwd = `linkedin-skills`, the init event lists the 12 as **plain names** (`linkedin-humanizer`,
  not `linkedin-skills:linkedin-humanizer`). No user plugin duplicates them (`claude plugin list`:
  none installed in the login used).
- 20 built-in Claude Code skills (`design`, `slides`, `debug`, `code-review`, …) are also listed.
  The app always names the skill in the prompt, so these are not selected.
- Invocation is through the `Skill` tool: `{"skill": "linkedin-humanizer"}` → "Launching skill:
  linkedin-humanizer". `--tools` must therefore include `Skill`.
- The repo's own `CLAUDE.md` is maintainer conventions (versioning, commit author). It is loaded
  as project instructions but is irrelevant to drafting; with no Bash it cannot act on it.

## Skills

"App tools" is what the app grants per run. All runs: no Bash, no Write unless listed, no MCP
servers, no Agent. "Network" is what the skill itself would do; in the app the backend does it.

| Skill (as Claude sees it) | In app? | Inputs | Outputs | App tools | Files read | Network (skill's own) |
|---|---|---|---|---|---|---|
| `linkedin-humanizer` (default/forensic/strict/aesthetic/all) | Tools: humanize | any text | rewrite, diff, per-paragraph tell density, "reads human/mixed/AI", tier | Skill, Read | `references/scrub-rules.md` etc. (optional), voice-profile | none |
| `linkedin-humanizer --mode audit` (sub-skill `post-audit.md`) | Tools: audit; Drafts: audit findings | draft text, optional audience/time/format | PASS/FAIL, blockers, warnings, per-paragraph density, fixes, timing | Skill, Read | `sub-skills/post-audit.md`, `references/audit-*.md` | none |
| `linkedin-humanizer --mode profile` (sub-skill `voice-profile.md`) | **not in spec yet** (see decisions) | 3-6 pasted posts (or Apify) | fills `references/voice-profile.md`, asks approval first | Skill, Read, Write/Edit on voice-profile.md only | voice-profile template | Apify optional |
| `linkedin-hook-extractor` | Tools | post URL → text (Apify or paste) | formula F1-F20 + confidence, structure, why it worked, blank template, cautions | Skill, Read | `references/hook-formulas.md`, `references/classification-rules.md` | Apify `fetch_post` |
| `linkedin-comment-drafter` | Tools (copy only) | post URL → text, optional top comments | 1-3 comments (200-350 chars), reaction, template label | Skill, Read | `references/comment-templates.md`, voice-profile, story-bank | Apify `fetch_post`, `fetch_post_comments`; Publora comment/reaction/reshare on approval (never in app) |
| `linkedin-repurposer` | Tools | source text (tweet/thread/blog/transcript), goal | LinkedIn post 900-1300 chars, source→LinkedIn mapping, formula, first-comment link note | Skill, Read | `references/hook-formulas.md`, `algorithm-heuristics.md`, voice-profile, story-bank | Publora post on approval (never in app) |
| `linkedin-profile-optimizer` | Tools | **pasted** profile text + goal (clients/job/authority). A URL cannot be fetched: no Apify profile actor | 9-section scorecard, priority fixes, before→after rewrites | Skill, Read | `skills/linkedin-profile-optimizer/references/*` | none |
| `linkedin-content-planner` | Planner | theme (opt), audience, pillar mix (opt), posting days (opt, default Tue-Fri) | 7-day table (day, time, pillar, format, formula, angle, CTA, goal), comment targets, readiness check, optional JSON | Skill, Read | story-bank, voice-profile, `references/founder-topics.md`, `hook-formulas.md` | none |
| `linkedin-post-writer` | Drafts | topic, angle, goal, length, audience; or a 5-line spine from the interviewer | formula, draft, char count, posting window | Skill, Read | voice-profile, story-bank, `hook-formulas.md`, `founder-topics.md`, `algorithm-heuristics.md` | Pixfaro images (optional); Publora on approval (never in app) |
| `linkedin-interviewer` (`--mode bank` default, `--mode post`) | Interviewer | the user's answers, one question per turn | writes `references/story-bank.md`; post mode ends in a 5-line spine | Skill, Read, Edit/Write on story-bank.md only | story-bank, `references/question-bank.md`, voice-profile | none |
| `linkedin-reply-handler` | no (not in your tool list) | comment URL or post URL | 1-2 replies per comment, parentComment URN | — | — | Apify comments; Publora |
| `linkedin-thread-monitor` | no | your handle | hot/warm/cool/dormant table | — | — | Apify |
| `linkedin-engager-analytics` | no | post URL(s), ICP | engager roster by tier | — | — | Apify |
| `linkedin-employee-advocacy` | no | team size, goal | 14-day team playbook | — | — | Publora reshare |

Interactive skills in a one-shot run: post-writer normally asks for the goal and offers 2-3
formulas; the planner may ask "founder plan or general plan?". The app supplies those as form
fields and tells the skill (via `--append-system-prompt`) not to ask questions.

## Story Bank and voice profile

| File | Filled by | Read by | Status line |
|---|---|---|---|
| `linkedin-skills\references\story-bank.md` | `linkedin-interviewer` | planner, post-writer, comment-drafter, repurposer, reply-handler | `## Status` → `- filled: no/yes`, `- updated:`, `- sessions:` |
| `linkedin-skills\references\voice-profile.md` | `linkedin-humanizer --mode profile` | post-writer, comment-drafter, reply-handler, repurposer, planner | `## Status` → `- filled:`, `- source:`, `- updated:` |

Both are **tracked files** in the skills repo, shipped as empty templates. Consequences:
- Once filled, `git pull` in `linkedin-skills` refuses to run if upstream also changed the template
  ("local changes would be overwritten"). README will give the stash → pull → pop steps.
- Skills load them only when `filled: yes`.
- Backups must include both files, alongside `data\studio.db`.

## Publora client surface (`lib\publora_client.py`)

Construction: `PubloraClient(api_key=None, timeout=30.0)`. It calls `load_env()` (python-dotenv
`find_dotenv(usecwd=True)` upward from the process cwd, then `linkedin-skills\.env`), reads
`PUBLORA_API_KEY`, raises `PubloraError` if missing. Auth header `x-publora-key`. Base
`https://api.publora.com/api/v1`. Errors raise `PubloraError("HTTP <code>: <body>")`.

| Method | Endpoint | Params | Returns |
|---|---|---|---|
| `create_post` | `POST /create-post` | `content`, `platforms` (list of `"linkedin-…"` ids), `scheduled_time` (ISO 8601 UTC; omitted = draft), `media_urls` | per docs: `{"success": true, "postGroupId", "scheduledTime", "warnings": [], "media": {}}` |
| `get_post` | `GET /get-post/<id>` | `post_group_id` | `{"success", "postGroupId", "status", "scheduledTime", "platforms", "posts": [{"status", "postedId", "error", "permalink"}], "media": [...]}` (repo fixture) |
| `delete_post` | `GET /get-post` guard, then `DELETE /delete-post/<id>` | `post_group_id`, `allow_live=False` | `{"success": true}`; refuses `published`/`partially_published` locally; API 409 `POST_IS_PUBLISHED` / `POST_HAS_LIVE_CONTENT` / `POST_IS_PROCESSING`, 404 if gone |
| `list_platform_connections`, `resolve_linkedin_platform_id` | `GET /platform-connections` | — | list of connections; the single `linkedin-…` id or None |
| `create_comment`, `delete_comment`, `create_reaction`, `create_reshare` | `/linkedin-comments`, `/linkedin-reactions`, `/linkedin-reshare` | — | not used: the app never posts comments |

- **Cancel:** yes, `delete_post`.
- **List:** no `list_posts` in the client. The API has `GET /list-posts` (status filter
  draft/scheduled/published/failed/partially_published). Also `PUT /update-post/<id>`, not in the client.
- **First comment:** not in the client. The API supports `firstComment: {"text": "...",
  "platforms": ["linkedin"]}` on `create-post` (≤1,250 chars, plain text; 400 `FIRST_COMMENT_TOO_LONG`).
- **Retries:** every POST goes through `_retry` → up to 3 attempts on 408/429/5xx **and on
  timeouts/connection errors**. Publora's docs: "A timeout does not tell you whether the post was
  created. Without a key, the retry double-posts."
- **Idempotency:** the API supports an `Idempotency-Key` header on `create-post` (same key + same
  body replays the original response for 24 h; 409 `IDEMPOTENCY_IN_FLIGHT`, 422
  `IDEMPOTENCY_KEY_CONFLICT`). The client never sends it.
- **Scheduling limits (docs):** past times ≥5 min → 400 `SCHEDULED_TIME_IN_PAST`, <5 min clamped
  with a warning; horizon is plan-dependent → 403 `SCHEDULE_HORIZON_REACHED`.
- **Quota (docs):** Starter = 15 posts/month account-wide; 403 `POST_LIMIT_REACHED`. The docs do
  **not** say whether drafts or deleted posts count, or when the month resets. The app's IST
  calendar-month counter is a local guard and may differ from Publora's own count.

## Apify client (`lib\apify_client.py`)

`ApifyClient(token=None, timeout=180.0)`; `fetch_post(post_url, force_refresh=False)` → `text`,
`authorName`, `urn`, `shareUrn`, `canShare`, `url`, counts, `postedAtISO`;
`fetch_post_comments(post_id, max_items=20, sort_order="most relevant", scrape_replies=False)`;
`fetch_user_recent_comments(username, result_limit=30)`;
`fetch_post_engagers(post_url, max_items=50, types=("likers","commenters"))`. 3 retries,
6-hour in-memory LRU cache.

## Repo scripts

- `scripts\check_config.py [--offline]`: credential wiring for Apify / Publora / Pixfaro. Prints
  key prefix + length, never the key. Live mode hits free endpoints only. Exit 0 = nothing
  misconfigured, 1 = a configured layer is broken.
- `scripts\selftest.py [--offline] [--live --yes] [--fresh]`: exit code = failed phases.
  Without `--live` it spends nothing, but:
  - its install phase runs `scripts\sync_codex_marketplace.py`, which rewrites `.codex-marketplace\`
    inside `linkedin-skills` (normally to identical content), and needs `git` on PATH;
  - its tests phase runs the full `unittest` suite (up to 15 min timeout) and
    `check_frontmatter.py` (imports PyYAML, which is only in `requirements-dev.txt`);
  - `--live` creates and deletes a real Publora draft and pays for a Pixfaro render. The app never
    passes `--live`.

## Tool policies, verified against the real CLI (2.1.292)

Run in a scratch folder with dummy files, flags exactly as `app/claude_runner.py` builds them
(`--tools`, `--allowedTools`, `--disallowedTools Read(./.env)`, `--permission-mode dontAsk`):

| Policy | Attempt | Result |
|---|---|---|
| Stateless (`--tools Read,Skill`, allow `Skill`) | Read `./notes.txt` | ok (reads inside the working dir need no allow rule) |
| | Read `./.env` | denied: "File is in a directory that is denied by your permission settings" |
| | Read a file outside the working dir | denied: "running in don't ask mode" |
| Story Bank (`--tools Read,Skill,Edit,Write`, allow `Edit(./references/story-bank.md)`) | Edit `references/story-bank.md` | ok |
| | Write (overwrite) `references/story-bank.md` | ok (an `Edit(path)` rule covers Write too) |
| | Write `references/new.md` | denied, file not created |
| | Edit `notes.txt` | denied, file unchanged |

Interviewer resume was checked end to end through the app: turn 2 reused turn 1's session id via
`--resume`, and `story-bank.md` was byte-identical afterwards.

## Gaps and risks found

1. `create_post` can double-post on a timeout (retry without idempotency key).
2. No first-comment support in the client (API has it).
3. Quota counting rules are undocumented; the local counter is a guard, not the source of truth.
4. `.env` was created from `.env.example`, so it holds **placeholder values** (`sk_your_key_here`,
   `apify_api_your_token_here`, …). `lib` treats any non-empty value as configured, so placeholders
   look "set". The app will treat `*your_*` placeholders as unset; the user should fill or delete them.
5. Story Bank / voice profile are tracked files (pull conflicts, backups).
6. `--max-turns` works on 2.1.292 (verified: accepted under `-p`, while an unknown flag errors)
   but is **not listed in `claude --help`**.
7. The account default model is `claude-opus-5-5`. One humanizer call took about 16 s, 3 turns,
   ~35k input tokens (mostly cache) and 1.2k output tokens. The run's rate-limit event showed the
   5-hour window at 20% (shared with any other Claude Code use on this login).
