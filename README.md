# LinkedIn Studio

A local, single-user Windows app that runs the
[linkedin-skills](https://github.com/sergebulaev/linkedin-skills) Claude Code skills from a UI.
You double-click a shortcut and an app window opens. Closing the window stops everything.

- **Claude:** the Claude Code CLI in headless mode (`claude -p`) on your own login. There is no
  API key and no cloud hosting.
- **Publishing:** goes through Publora (free tier: 15 posts a month), and only after you approve
  the text and confirm the time.
- **Pictures (optional):** Claude can ask ChatGPT for an illustration for a post, through
  OpenAI's Codex CLI signed in as your own ChatGPT account.
- **Comments and replies:** drafted for you to copy. The app never posts them.
- **Storage:** everything stays on this machine (`data\`, plus two files in the skills repo).

## The studio

One window in three columns. **New to it? Open Guide in the sidebar**: it shows the routine as
steps you can click through, each with a picture of where it happens, what happens while Claude
works, a post's four states, and an editor to practise in.

- **The sidebar** lists your posts, each with its first line and its state: drafts first, then
  approved, scheduled (soonest first) and published. **New post** starts one. Below the list:
  Planner, Story Bank & Voice, Tools, Guide, Settings, Trash, and the light/dark switch.
- **The centre** is the post you picked, as LinkedIn shows it (Desktop or Phone, with the
  "…more" fold at about 210 characters and its picture). The top bar has its title, its state
  and the next step: **Approve this text**, then **Schedule…**, then the time it goes out. The
  gear holds its versions (your own edits are kept as versions too), earlier chats, **New draft
  from this** (an editable copy of any post) and **Move to Trash…**.
- **Ask Claude**, on the right, is a chat kept with each post. Ask for a draft, a sharper hook,
  a shorter take, an audit or a picture: Claude works through the skills and changes the post
  itself, and each change is kept as a version you can go back to. You can attach files (notes,
  a PDF, a chart) for Claude to read; an attached picture can be put on the post. On a post that
  is not a draft the text is locked: the panel says what unlocks it (Back to draft, cancelling on
  Publora, or New draft from this), and Claude can still audit it, but its run gets no tool that
  rewrites the post or makes a picture, so none is spent on it. A request that never got an
  answer (the app closed meanwhile) offers **Try again**.

**Editing a post**

- **Autosave.** Click the text and type: it saves about a second after you stop (Ctrl+S saves
  at once).
- **Character meter.** Where the post sits against the 900-1,300 sweet spot and LinkedIn's 3,000
  limit.
- **Blanks.** The writer marks facts it does not have as `[N]` or `[DD Month YYYY]`. The editor
  counts them, **Next blank** jumps to each one, and Approve refuses while any remain.
- **Audit and Revise.** Audit findings appear beside the text. New hook, Shorter or More
  technical shows the changes word by word; nothing is replaced until you choose **Use this
  version**.
- **Publish.** Draft → Approved → Scheduled → Published. Approved text is locked. Scheduling asks
  for a time (the skills' recommended slots one click away), then confirms the final text, time,
  first comment and picture.
- **Trash.** **Move to Trash…** (the gear) sends a draft, approved, failed or cancelled post to the
  Trash, after Settings in the sidebar. There **Put back** returns it as it was, with its versions,
  chat and pictures; **Delete forever…** and **Empty trash** ask first and name what goes.
  Scheduled and published posts stay protected: cancel one on Publora first.

**The pages**

| Page | What it does |
|---|---|
| Planner | Posts used this month (x of 15) and the next scheduled post; audience + goal (+ theme, 3-5 posts) → a board of post cards → **Draft this** on any card; comment targets and the inbound-readiness checklist |
| Story Bank & Voice | Both files, formatted, with the sections that have material; the Interviewer (`linkedin-interviewer`) and the voice-profile builder (`linkedin-humanizer --mode profile`) as chats beside them |
| Tools | Humanize, Audit, Hook extractor, Comment drafter, Repurposer, Profile optimizer. Input, result, copy buttons. A repurposed post can be saved as a draft |
| Guide | The routine step by step with a picture of each screen (light or dark, as the app is), what each button does, the four post states, shortcuts and limits |
| Settings | Claude's version, **the account its login folder is signed in to** (**Check the sign-in** asks again) and **Change folders**; publishing keys (set or missing, never shown), ChatGPT, light/dark/auto, the two health checks, recent runs, Quit. Jump links at the top; each section has its own address (`#~settings-claude`, `-publishing`, `-chatgpt`, `-appearance`, `-health`, `-runs`, `-app`) |
| Trash | Posts moved there: Put back, Delete forever…, Empty trash |

**Keys.** Ctrl+K searches posts, pages and actions; Alt+N starts a new post; Ctrl+/ goes to Ask
Claude; Alt+↑ / Alt+↓ open the previous or next post; ? lists the shortcuts. In Ask Claude, Enter
sends, Shift+Enter adds a line and ↑ in an empty box brings back your last message. The Guide's
Keys and limits lists them all.

**Jobs.** Claude runs one job at a time; others wait in line. A running job shows its steps,
numbered, a timer and Cancel (Stop, in a chat), and its result appears in place. You can leave the page: when the
job ends, a note in the corner links to it.

## First run

You need:

1. Windows 11 and Python 3.11 or newer (`py -3 --version`).
2. [Claude Code](https://code.claude.com/docs/en/setup), installed and signed in: run `claude`
   once in a terminal and log in. The app needs the real `claude.exe`. If yours came from npm,
   run `claude install` to get it.
3. A copy of the skills, cloned with real links. Turn on Developer Mode in Windows Settings
   first, then run:
   `git -c core.symlinks=true clone https://github.com/sergebulaev/linkedin-skills`
4. This repository, in any folder.

Then:

1. **Launch.** Double-click `Launch LinkedIn Studio.vbs`, or make a desktop shortcut with the
   snippet in [docs/SHORTCUT.md](docs/SHORTCUT.md). The first time, a console window builds
   `.venv` and installs the pinned packages (about a minute); it does so again when
   `requirements.txt` changes. Otherwise there is no console.
2. **Set the three folders.** On a new PC the app opens its setup screen first. See below.
3. **Keys.** In your skills folder, copy `.env.example` to `.env` and set:
   - `PUBLORA_API_KEY=sk_…` (Publora → Settings → API)
   - `LINKEDIN_PLATFORM_ID=linkedin-…` (Publora → Channels → your LinkedIn account)
   - optional: `APIFY_TOKEN=apify_api_…`, so post URLs can be fetched instead of pasted
   - **Delete the lines you don't use.** The placeholders from `.env.example` are ignored by this
     app but count as "set" for the skills' own scripts.
4. **Pictures (optional).** Install the Codex CLI (`npm install -g @openai/codex`). In
   **Settings → ChatGPT**, name a folder of its own for Codex's sign-in (its Codex home), save,
   and press **Sign in**. There is no default: the PC's own `.codex` folder may be signed in to
   another account, so it is never used. Empty means pictures are off.

### Setting the three folders

The app has to know where three things are on your PC. On a new PC it opens a setup screen
for this before anything else. Later the same screen is under **Settings → Change folders**.

| Folder | What it is | Usually |
|---|---|---|
| Skills folder | Your clone of linkedin-skills. Claude works inside it | next to this folder, or `C:\Users\you\linkedin-skills` |
| Claude program | `claude.exe`, the Claude Code command-line program (not the desktop app) | `C:\Users\you\.local\bin\claude.exe` |
| Claude login folder | Where Claude Code keeps your sign-in | `C:\Users\you\.claude` |

For each one you can click a place the app **found on this PC**, press **Browse…** and choose
it in a Windows file window, or paste the path (Explorer's "Copy as path" works, quotes
included). **Save** checks all three, writes them to `config.local.toml` and restarts the app.
As part of the check it asks the program for its version, so a different `claude.exe` is caught
there and not on your first job, and asks Claude Code (`claude auth status`, which sends Claude no
request) who each login folder is signed in to. The screen shows the account beside every login
folder it found, so a work sign-in on the same PC is easy to tell apart, and Save refuses a folder
signed in to nobody. An answer it cannot read (an older Claude Code) is shown, never a reason to
refuse.

By hand instead: copy `config.example.toml` to `config.local.toml` and set `skills_dir`,
`claude_bin` and `claude_config_dir`. The other settings in that file (port, time zone, model,
limits, `codex_home`) are explained there.

## How it stays safe

- **Claude's account.** Each Claude run gets `CLAUDE_CONFIG_DIR` from the config, never from the
  environment, so the app always uses the login you chose. If the folder is missing, the app
  refuses to run Claude. `ANTHROPIC_API_KEY` is stripped, so a run can't fall back to paid API
  billing.
- **What Claude can do.** The backend picks the tools for each run:
  - Skills get `Skill` and `Read` only. Reads work inside `linkedin-skills` only; `.env` and
    anything outside are denied.
  - The Interviewer and voice-profile chats may also edit their one file: `story-bank.md` or
    `voice-profile.md`.
  - A post's chat also gets the studio's own tools, and nothing else: rewrite this post, keep an
    audit on it, make a picture for it (when ChatGPT is set up), fetch a LinkedIn post (when an
    Apify token is set). They are served by the app on `127.0.0.1`, behind a token made for that
    one run.
  - A chat's attached files sit in a folder of that chat, the one extra folder its run may read.
  - No run gets Bash, web access or any other MCP server. Prompts go in on stdin; the command
    is a list, with no shell.
  - Apify fetching and Publora publishing are done by the app, not by Claude.
- **Limits.** 12 turns and 180 s per skill run; 30 turns and 600 s per Ask Claude request. A
  timeout, Cancel or Stop kills the whole process tree (Windows Job Object).
- **ChatGPT's pictures.** Codex runs with the Codex home you named and nothing else
  (`OPENAI_API_KEY` and the like are stripped). At most 4 pictures per request, counted per day
  on the Settings page. The rules: LinkedIn's sizes (1200 x 627 or 1080 x 1080), an
  illustration and never something passed off as a photo, a word or two at most, no real
  people's faces. A picture goes out only if you put it on the post.
- **Approving.** Approve refuses text that still contains placeholder slots like `[N]` or
  `[DD Month YYYY]`. The writer leaves these where it has no real fact.
- **Scheduling happens exactly once:**
  - Scheduling is one database transaction from approved to scheduling, so double-clicks can't
    send twice.
  - It is a single Publora request carrying an `Idempotency-Key`.
  - After a failed or timed-out call, Retry resends the identical request with the same key,
    which Publora replays instead of re-posting.
  - A post with a picture takes Publora's four media steps: create it as a draft (same key), get an
    upload link, upload the file, schedule it. Each step is recorded, so Retry carries on from the
    one that failed and never makes a second post; Back to draft deletes the Publora draft.
  - Times must be between 2 minutes and 14 days ahead.
  - The monthly limit is checked on the server. It counts scheduling, scheduled and published
    posts in the IST calendar month; Publora keeps its own count too.
- **The web server.** It listens on `127.0.0.1` only, with a random token per launch. The token
  becomes an HttpOnly, SameSite=Strict cookie, and any request that changes something must come
  from `http://127.0.0.1:<port>` and carry JSON. Other websites open in your browser can't use it.

## Your Story Bank stays out of git

The Story Bank and the voice profile hold career detail, real numbers and named people. Both
are files the skills repository tracks as empty templates, so a filled copy would travel with
any commit and push of that folder. A `.gitignore` line does not help for a file git already
tracks, so the app does this instead, every time it starts:

- It sets git's skip-worktree flag on both files in your clone. Git then treats your filled
  copies as unchanged: they never show in `git status`, `git add -A` skips them, and they cannot
  reach a commit or a push.
- It covers the two copies the skills' self-test writes under `.codex-marketplace\` as well.
- It lists all four paths in the clone's private ignore file (`.git\info\exclude`).

Nothing in the skills repository is edited; the flag lives in your clone only. The Story Bank &
Voice page shows the result (**Private: kept out of git**) and Settings repeats it. If the
skills folder is not its own repository, the app changes nothing, and says so when the folder
sits inside another repository that does not ignore these files.

This repository has its own guard: `.gitignore` refuses `.env` files, databases and any
`story-bank*.md` or `voice-profile*.md`, so a backup copied in here cannot be committed, and a
test fails if a tracked file ever looks like one of those or like a real Publora key.

## Where data lives

| What | Where |
|---|---|
| Plans, posts, their versions, chats, job log | `data\studio.db` (SQLite) |
| Post pictures (made or attached) | `data\images\` |
| Files attached in a chat | `data\attachments\<chat>\` |
| Pictures made per day, Codex's sign-in log | `data\chatgpt.json`, `data\chatgpt.log` |
| Launcher log, the app window's browser profile | `data\studio.log`, `data\browser-profile\` |
| Story Bank, voice profile | `linkedin-skills\references\story-bank.md`, `voice-profile.md` |
| API keys | `linkedin-skills\.env` (never shown by the app) |

`data\` and `config.local.toml` are gitignored here. The ChatGPT sign-in itself stays in the
Codex home you named; the app reads only who is signed in.

## Backups

Close the app first, so SQLite isn't mid-write. Then:

```powershell
$studio = "C:\path\to\linkedin-studio"    # this folder
$skills = "C:\path\to\linkedin-skills"    # your skills folder
$dest = "$env:USERPROFILE\Documents\linkedin-studio-backup\$(Get-Date -Format yyyy-MM-dd)"
New-Item -ItemType Directory -Force $dest | Out-Null
Copy-Item $studio\data\studio.db $dest
Copy-Item -Recurse $studio\data\images, $studio\data\attachments $dest -ErrorAction SilentlyContinue
Copy-Item $skills\references\story-bank.md, $skills\references\voice-profile.md $dest
```

To restore, copy the files back with the app closed.

## Updating the skills

```powershell
git -C C:\path\to\linkedin-skills pull
```

That is all it takes while upstream leaves the two templates alone: your filled Story Bank and
voice profile stay as they are.

If upstream changed a template too, the pull refuses ("your local changes would be
overwritten"), and `git stash` cannot help because git does not look at these files. Close the
app, then:

```powershell
cd C:\path\to\linkedin-skills
$files = "references/story-bank.md", "references/voice-profile.md",
         ".codex-marketplace/linkedin-skills/references/story-bank.md",
         ".codex-marketplace/linkedin-skills/references/voice-profile.md"
$keep = "$env:USERPROFILE\Documents\linkedin-studio-backup\before-pull"
New-Item -ItemType Directory -Force $keep | Out-Null
Copy-Item references\story-bank.md, references\voice-profile.md $keep    # your filled copies
git update-index --no-skip-worktree -- $files                             # let git see the files again
git checkout -- $files                                                    # back to the templates
git pull
Copy-Item $keep\story-bank.md, $keep\voice-profile.md references\        # put your copies back
```

Then open LinkedIn Studio before you do anything else with git: it protects the files again as
it starts. Afterwards, run **Settings → Health checks → Connections** and one Tools run to
confirm the skills still load.

## Troubleshooting

| Symptom | Fix |
|---|---|
| The setup screen opens instead of the app | One of the three folders is missing or wrong, for example after a folder was moved. Choose it again on that screen. |
| **Browse…** seems to do nothing | The Windows file window opened behind another window. Look for it on the taskbar, or paste the path instead. |
| Jobs fail with "Please run /login" or "Invalid API key" | The login in the Claude login folder has expired. In PowerShell run `claude`, type `/login`, sign in, then `/exit`, and retry the job. If the app uses a login folder other than the default, name it first: `$env:CLAUDE_CONFIG_DIR = "C:\Users\you\.claude-other"`. |
| "Claude did not find the skill …", or the setup screen says the skills are not real links | `linkedin-skills\.claude\skills\*` were checked out as text files. With Developer Mode on, re-clone: `git -c core.symlinks=true clone https://github.com/sergebulaev/linkedin-skills`. Check with `Get-ChildItem linkedin-skills\.claude\skills`: LinkType must be `SymbolicLink`. |
| Error page: port in use | Another program has the port. Set another `port` in `config.local.toml`. If it is an old LinkedIn Studio, close its window or end `pythonw.exe` in Task Manager. |
| Publora 401 | Wrong or revoked `PUBLORA_API_KEY`. Create a new key in Publora → Settings → API. |
| Publora 400 (`Invalid platform ID`, missing platformId) | `LINKEDIN_PLATFORM_ID` is wrong: copy the whole `linkedin-…` id from Publora → Channels. `SCHEDULED_TIME_IN_PAST`: pick a later time. |
| Publora 404 | Wrong platform id, or the post was already deleted on Publora. |
| Publora 403 `POST_LIMIT_REACHED` | Publora's own monthly limit. It can differ from the app's count, which only sees posts scheduled from here. |
| "No answer from Publora … may or may not have created the post" | Check the Publora dashboard, then use **Retry**. It reuses the same idempotency key (and, for a post with a picture, carries on from the step that failed), so it can't create a second copy. |
| Settings → ChatGPT says the Codex CLI was not found | Install it (`npm install -g @openai/codex`), or set `codex_bin` in `config.local.toml` to its `codex.exe`. |
| Settings → ChatGPT says Codex is not signed in | Press **Sign in** there and finish ChatGPT's sign-in in the browser window Codex opens. |
| Error page: browser not found | Set `browser_path` in `config.local.toml` to `chrome.exe` or `msedge.exe`. |
| A job says "Claude answered, but not in the shape the app reads" | Claude answered without the result block. Its full reply is shown; press **Try again**. |
| Approve says there are placeholder slots | Use **Next blank** to fill in every `[…]` with a real detail (or delete the sentence), then approve. |
| A job timed out | Raise `timeout_seconds` (skills) or `chat_timeout_seconds` (Ask Claude) in `config.local.toml` and restart the app. |
| "This window belongs to an earlier session" | The app was restarted while this window stayed open. Close it and open LinkedIn Studio from the shortcut. |
| The Story Bank & Voice page says **Not protected from git** | Git is missing or refused. Install Git for Windows and restart the app. If the skills folder sits inside another repository of yours, add the two files to that repository's `.gitignore`. Until it says Private, do not commit or push that folder. |
| Pages look broken or show errors right after the app's code changed | The running app still has the old code. Close its window (that stops it) and open it again. |

## Development

```powershell
cd C:\path\to\linkedin-studio
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest            # API, security, jobs, scheduling, chats, pictures, and the page in Chrome
.venv\Scripts\python -m app               # dev server; prints the sign-in URL
.venv\Scripts\python dev\demo_server.py   # the page with stand-ins: no Claude, no Publora, no ChatGPT, made-up data
```

The demo server is the way to work on the page: every job finishes in a few seconds with canned
output, and a post's chat calls the studio's own tools as Claude would, so each screen and each
in-between state can be looked at without spending anything (`--empty` starts it bare).

- The back end is a JSON API on FastAPI: `app\main.py` (the app, its state and jobs),
  `app\api_posts.py` (posts, their chats, versions, pictures, scheduling) and `app\api_pages.py`
  (the other pages). `app\mcp.py` serves the studio's tools to a post's chat; `app\codex.py`
  makes ChatGPT's pictures.
- The front end is plain HTML, CSS and JavaScript modules with nothing external and no build
  step: `app\static\index.html`, `app.css` (design tokens at the top, light and dark), `app.js`
  and `js\`. The Guide's words live in `app\guide.py`.
- `app\attachments.py`, `app\static\attach.js` and `attach.css` (and `tests\test_attachments.py`)
  are shared byte for byte with other studios built like this one: change them there, never here
  alone.
- `tests\test_browser.py` and `tests\test_browser_pages.py` drive the page in Chrome or Edge
  through Playwright, on the demo server; they are skipped when neither is installed.
- **The Guide's pictures** (`app\static\guide\`) are taken on the demo, never on your own data:
  `.venv\Scripts\python dev\guide_shots.py` starts the demo in a folder that names no one, uses
  the page as a person would and saves each screen in light and dark, small, as WebP. It never
  pictures Settings, the setup screen or the Planner's Claude card, and refuses a picture whose
  text shows your user name or home folder. Retake them when a screen changes.

`docs/skill-inventory.md` covers what each skill takes and produces, the Publora client surface,
and the gaps found when this was built. One test uses the real skills code and is skipped unless
a linkedin-skills clone sits next to this folder.

## Licence

MIT. See [LICENSE](LICENSE). The licences of the projects this app includes are in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
