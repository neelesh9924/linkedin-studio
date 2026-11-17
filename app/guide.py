"""What the in-app Guide says. Words live here; the page draws them (static/js/guide.js).

Numbers that the app enforces (limits, targets) are passed in from the code that enforces
them, so the guide cannot drift from the behaviour. `href` is where in the studio a step
happens (the page's own addresses), `icon` one of the page's icons, `shot` the picture of that
screen (static/guide/, taken by dev/guide_shots.py on the demo; shown only when present).
"""
from __future__ import annotations

from pathlib import Path

# The routine as a flowchart: lanes by how often, steps in order. `claude` says whether pressing the
# button runs Claude.
LANES = [
    {"label": "Once", "note": "Before your first plan", "steps": [
        {"id": "stories", "shot": "bank", "title": "Tell it your stories", "icon": "chat", "where": "Story Bank & Voice",
         "href": "#~bank", "claude": "Each message runs Claude, a few seconds", "demo": "chat",
         "do": ["Open Story Bank & Voice. The interviewer is on the right.", "Press Start the interview, then answer one "
                "question at a time. Enter sends, Shift+Enter adds a line.",
                "Stop whenever you like. Next time it carries on and only asks about thin sections.",
                "To go deeper on one thing you said, press Ask me about this beside that entry: a short interview "
                "about it alone, in a new conversation."],
         "gives": "Your Story Bank: roles, real numbers, turning points and opinions, kept on this computer. "
                  "Drafts draw on it instead of leaving blanks."},
        {"id": "voice", "shot": "bank", "title": "Teach it your voice", "icon": "feather", "where": "Story Bank & Voice, Voice profile",
         "href": "#~voice", "claude": "Each message runs Claude", "demo": "voice", "optional": True,
         "do": ["Switch to Voice profile.", "Paste three to six of your own posts or comments.",
                "Read the profile it shows you, and say yes to save it."],
         "gives": "Drafts follow your rhythm, openers and habits. Skip this if you have never posted."},
    ]},
    {"label": "Every week", "note": "A few minutes of reading", "steps": [
        {"id": "news", "shot": "hot", "title": "Read what's hot", "icon": "flame", "where": "Hot topics", "href": "#~hot",
         "claude": "Ranking runs Claude in the background", "demo": "news",
         "do": ["Open Hot topics: the last {hot_days} days of news in your niche, each item ranked 1 to 10 for how it "
                "fits you and whether it makes a post.",
                "Read Best for you first: each item says why it ranked so, and the post it would become.",
                "Search the news for one subject; Refresh reads the news again."],
         "gives": "The news worth a post this week, each with the post it would make."},
    ]},
    {"label": "Every post", "note": "Your facts are the real work", "steps": [
        {"id": "draft", "shot": "hot", "title": "Draft it", "icon": "sparkle", "where": "Hot topics, or + New post",
         "href": "#~hot", "claude": "Runs Claude, about 30 seconds", "demo": "working",
         "do": ["Press Draft beside a news item on Hot topics: Claude writes the post its rank saw, from the article, "
                "with its link in the first comment.",
                "Or press + New post and tell Claude, on the right, what the post is about.",
                "You can leave the page while it runs; a notice tells you when it is ready.",
                "The drafts you have wait in the list on the left, the best ranked first."],
         "gives": "A draft in your voice, in the list on the left."},
        {"id": "blanks", "shot": "post", "title": "Fill the blanks", "icon": "target", "where": "The post", "href": "#~posts",
         "claude": "", "demo": "blanks",
         "do": ["Where the writer had no real fact it left a blank like [N], marked in yellow.",
                "Press Next blank, then type the real number, name or date over it.",
                "Typing saves by itself about a second after you stop."],
         "gives": "A post made of your facts. Nothing is invented for you."},
        {"id": "ask", "shot": "chat", "title": "Ask Claude", "icon": "chat", "where": "The post, Ask Claude", "href": "#~posts",
         "claude": "Runs Claude, from seconds to a few minutes", "demo": "ask",
         "do": ["Ask in the panel beside the post: a real number from your Story Bank, a first comment with "
                "the link, an illustration, a closing question.",
                "Claude rewrites the post in place and keeps a version each time; the gear's Versions go back.",
                "An illustration shows under its reply; Add to the post puts it on. A post takes up to {max_pictures} "
                "pictures, in the order you set beside it.",
                "Carousel beside the post (or asking for one) has Claude lay the post out as slides: a PDF LinkedIn "
                "shows as a swipeable document, the words drawn as text. Use this carousel puts it on, alone.",
                "Once a post is approved, scheduled or published its text is locked: Claude can still audit it, "
                "and says what unlocks it."],
         "gives": "Changes in your voice, and pictures from ChatGPT ({per_request} at most a request)."},
        {"id": "audit", "shot": "post", "title": "Audit and revise", "icon": "check-circle", "where": "The post", "href": "#~posts",
         "claude": "Runs Claude, about 40 seconds", "demo": "audit",
         "do": ["Press Audit. The findings appear beside the post: red must be fixed, amber is worth a look.",
                "Want a different take? Revise: New hook, Shorter or More technical.",
                "Style: four sliders (Hook plain to bold, Tone formal to warm, Emojis none to markers, Layout plain or "
                "sections with bold heads). Restyle writes the same post in them, and they become that post's own style.",
                "A revision shows every change word by word. Nothing is replaced until you choose Use this version."],
         "gives": "Either a pass, or a short list of concrete fixes."},
        {"id": "approve", "shot": "post", "title": "Approve and queue", "icon": "check", "where": "The post's top bar",
         "href": "#~posts", "claude": "", "demo": "approve",
         "do": ["Press Approve and queue. It is refused while a blank remains, or past {post_max} characters.",
                "It takes your next free posting time (Settings, Posting times): one post a day at most, within your "
                "Publora plan ({plan_words}). A link in the text, or a picture kept but not on the post, is worth a second "
                "look: it asks first.",
                "Approved text and picture are locked. Back to draft unlocks them, and takes the post out of the queue.",
                "Approve only locks the text with no time: then Add to queue, or Schedule… for a time of its own."],
         "gives": "A final post with its day, and no time to pick."},
        {"id": "queue", "shot": "coming", "title": "The queue", "icon": "calendar", "where": "Schedule, Coming up",
         "href": "#~schedule", "claude": "", "demo": "queue",
         "do": ["Coming up lists what goes out when: the posts at Publora with their times, then your queued posts in "
                "line order, and the posting times still free.",
                "Move up, Move down and First in line change a queued post's place. Take out leaves it approved, "
                "with no time.",
                "A queued post goes to Publora by itself once its time is {max_days} days away and the plan has room, "
                "while the studio is open, so open it every few days. A post already at Publora goes out even with this "
                "PC off.",
                "Cancel on Publora, in a post's gear, frees its day: the next in line takes it."],
         "gives": "Your posts going out on your own rhythm, with nothing to schedule by hand."},
        {"id": "schedule", "shot": "schedule", "title": "Schedule a time of its own", "icon": "send", "where": "The post's top bar",
         "href": "#~posts", "claude": "", "demo": "schedule", "optional": True,
         "do": ["For a post with a day of its own (an event, a launch): Approve only, then Schedule…. Pick a time, or "
                "tap one of your free posting times.",
                "Check the final text, the picture, the time and the first comment, then confirm.",
                "Before you confirm lists what is worth a second look: a blank, a link that reads better as the first "
                "comment, a picture not on the post, a time already gone, the month's last posts. It never "
                "stops you.",
                "It must be between {min_lead} minutes and {max_days} days ahead.",
                "Need it out right away? Post now…, in the post's top bar (or beside a queued post in Coming up), "
                "sends it at once after the same check: Publora takes no post without a time, so it goes for the "
                "soonest the studio schedules, {min_lead} minutes ahead."],
         "gives": "The post waits at Publora with its picture. If the connection drops, Try again carries on and "
                  "cannot create a second copy."},
        {"id": "published", "shot": "post", "title": "Published", "icon": "check-circle", "where": "The post's top bar",
         "href": "#~posts", "claude": "", "demo": "published",
         "do": ["Once its time has passed, the studio asks Publora every few minutes whether it went out; Check now, "
                "in the post's top bar, asks at once.",
                "The post shows as Published, with Open on LinkedIn, and counts toward this month's posts ({limit_words})."],
         "gives": "It is on LinkedIn. A link you put in First comment appears right under it."},
    ]},
    {"label": "Every day", "note": "Alongside your own posts", "steps": [
        {"id": "comment", "shot": "tools", "title": "Comment on others", "icon": "comment", "where": "Tools, Comment drafter",
         "href": "#~tools-comment", "claude": "Runs Claude, usually under half a minute", "demo": "comment",
         "do": ["Paste a post you want to join the conversation on: someone in your niche, or a post that drew you in.",
                "Press Draft comments and copy the one you like.",
                "Post it yourself. The app never comments or reacts for you."],
         "gives": "Two or three comments with a suggested reaction each."},
    ]},
]

# What a post can do in each state: (state, what it means, what you can do).
STATES = [
    ("Draft", "You are still writing.", ["Edit the text in place; it saves by itself, and your own edits are kept "
                                         "as versions", "Ask Claude, Audit and Revise",
                                         "Add pictures (up to {max_pictures}) or a carousel, or take them off",
                                         "Approve, once no blank remains", "Move to Trash…"]),
    ("Approved", "The text and pictures are final and locked.", ["Add to queue, for your next free posting time",
                                                                "Schedule… and pick a time", "Back to draft to edit again",
                                                                "Ask Claude to audit it; the text stays as it is",
                                                                "Move to Trash…"]),
    ("Queued", "Approved, and waiting in the queue for its posting time.",
     ["Move it up or down in Schedule's Coming up", "Take out of the queue: it stays approved",
      "Back to draft, which takes it out of the queue",
      "It goes to Publora by itself once its time is {max_days} days away"]),
    ("Scheduled", "It is waiting at Publora.", ["Check now, which asks Publora whether it went out",
                                                "Cancel on Publora (the gear)", "Open the Publora dashboard",
                                                "It stays out of the Trash while it is scheduled"]),
    ("Published", "It is on LinkedIn.", ["Open on LinkedIn, once Publora gave its link",
                                         "New draft from this, for an editable copy",
                                         "It counts toward this month's posts ({limit_words})",
                                         "Move to Trash… takes it out of the studio only: it stays on LinkedIn, and "
                                         "its month still counts it"]),
]

SCREENS = [
    {"key": "post", "title": "A post", "href": "#~posts", "icon": "file", "shot": "post",
     "purpose": "The post as LinkedIn shows it, and the place you finish it.",
     "points": ["The middle shows it as a reader sees it, at Desktop or Phone width, with \"…more\" after about {fold} "
                "characters and its pictures as LinkedIn lays them out (or its carousel, paged with the arrows), under "
                "your name, headline and photo (Settings, You in the preview).",
                "Click the text to edit it there. Bold (Ctrl+B) makes the selected words LinkedIn's bold, and again makes "
                "them plain: keep it for the first line and short heads. The meter shows your length against the "
                "{target_min}-{target_max} sweet spot.",
                "Pictures beside it: the ones marked On the post are posted with it. Add to the post, their order, "
                "Remove from post (it stays in Pictures); a carousel goes out alone, a card as a picture. Try another "
                "look draws a carousel or a card in the next of five looks (midnight, terminal, blueprint, paper, "
                "poster, three colourings each), its art kept and no ChatGPT picture spent; Redraw draws it again in "
                "its place, with your name on it only if you put it on carousels (Settings, You in the preview).",
                "Edit text opens the editor from the keyboard. Copy and Copy first comment copy the words as they "
                "will go out.",
                "The top bar says where it stands and holds the next step: Approve and queue (or Approve only, then "
                "Add to queue or Schedule…), then Check now once it is at Publora; once it is out, Open on LinkedIn.",
                "The gear holds the title, Versions to compare with now and go back to (your own edits are kept too), "
                "New draft from this and Move to Trash…; a scheduled post stays out of the Trash.",
                "Rank, beside it: how worth posting it is, 1 to 10, with why and the one change that would lift it. "
                "Ask Claude to rank it, or give it your own number.",
                "The sidebar lists your posts as they are today, drafts best first by rank (any not ranked yet on top), "
                "each draft with its rank; published and cancelled ones fold away under "
                "Earlier, which stays as you leave it. The post you have open always shows."]},
    {"key": "chat", "title": "Ask Claude", "href": "#~posts", "icon": "sparkle", "shot": "chat",
     "purpose": "A conversation beside each post, kept with it.",
     "points": ["Ask for any change; Claude rewrites the post and keeps a version.",
                "It runs your skills: the post writer, the humanizer, the audit and the hook extractor.",
                "Ask for an illustration and ChatGPT makes one, or for a carousel or a card: Claude lays the post out "
                "as slides (a cheat sheet, a before and after, a code card, steps, a figure…) in a look unlike your "
                "last ones, with ChatGPT art where a character or an object helps; Add to the post (Use this carousel) "
                "puts it on.",
                "Each step shows while it works, and Stop ends it. A request that got no answer offers Try again.",
                "On a locked post (approved, scheduled or published) it changes nothing: it can audit it, and says "
                "what unlocks the text.",
                "Drag the panel's left edge to make it wider or narrower, or focus the edge and use ← and →; a "
                "double-click puts it back."]},
    {"key": "schedule", "title": "Schedule", "href": "#~schedule", "icon": "calendar", "shot": "coming",   # "schedule": Schedule…'s
     "purpose": "What goes out when, and this month at a glance.",
     "points": ["Coming up comes first: the posts at Publora with their times, then the queue in line order with Move "
                "up, Move down, First in line and Take out, then the posting times still free. Check Publora asks "
                "about the posts whose time has passed.",
                "Getting set up stays until each of its steps is done.",
                "Then this month: posts used, the next post out and Claude's status."]},
    {"key": "hot", "title": "Hot topics", "href": "#~hot", "icon": "flame",
     "purpose": "The latest news in your niche, ranked for you, each item one press from a draft.",
     "points": ["The last {hot_days} days from the teams behind your tools (Android, Android Studio, Kotlin, Flutter, "
                "Dart, Django, Python, PostgreSQL, GitHub, Firebase), every article of the Android Weekly and iOS Dev "
                "Weekly issues, the Swift and Django forums, engineering blogs (Cloudflare, Netflix, Shopify, Meta, "
                "Discord, InfoQ, JetBrains), dev.to's most liked of the week, and the Hacker News stories with "
                "{hot_points} points or more that name your areas.",
                "Claude ranks each new item 1 to 10: how good a post it makes for you, from how it fits you (your "
                "voice profile; never your Story Bank) and whether there is something to teach in it. Each item shows "
                "its rank, why, and the post it would become.",
                "Best for you comes first; items not ranked yet follow; those ranked 1 to 4 fold away under Not for "
                "you. The same story from several sources is one item, naming the others.",
                "The studio reads the news under its own name when the page opens and its copy is over an hour old; "
                "Refresh reads it again. Then Claude ranks what is new, a batch at a time, so a Draft you press goes "
                "next. A source that gives nothing is named under the heading.",
                "Draft has Claude write the post its rank saw, from the article as the studio read it. The link goes "
                "in the first comment, and the news sits beside the post as From Hot topics. The item then shows the "
                "draft at work, then Open the post. A title opens the article in your browser.",
                "Search the news keeps the items with every word you type somewhere in them, the words marked; Not "
                "for you opens while it holds one."]},
    {"key": "bank", "title": "Story Bank & Voice", "href": "#~bank", "icon": "book",
     "purpose": "What the skills know about you, and the interviews that fill it.",
     "points": ["Read-only, so the format stays what the skills expect.",
                "The list beside it shows which sections have material.",
                "On the right, the interviewer (Story Bank) or the voice-profile chat (Voice profile).",
                "Ask me about this, beside each filled Story Bank entry, starts a short interview about that entry; "
                "the conversation before it stays under Earlier conversations.",
                "Both files stay on this computer. The lock chip confirms git leaves them alone."]},
    {"key": "tools", "title": "Tools", "href": "#~tools", "icon": "tool",
     "purpose": "One-off jobs. Nothing here is posted; you copy what you want.",
     # The page adds one line per tool in front of these, in the words the Tools screen uses.
     "points": ["Under a Humanize result, Compare with the original shows every change.",
                "Start a post from this makes a new post of a Humanize rewrite, an audited draft (its findings beside "
                "it), a repurposed post with its first comment, or a hook's blank template, and opens it.",
                "Earlier results, under a tool's result, lists its last ten: pick one to see it again with its copy "
                "buttons."]},
    {"key": "settings", "title": "Settings", "href": "#~settings", "icon": "settings", "shot": None,
     "purpose": "Checking that everything is connected.",
     "points": ["Claude: its version, the account its login folder is signed in to (Check the sign-in asks again), and "
                "the Model every run uses, picked from a list: the account's default, Sonnet, Opus or Haiku.",
                "Change folders: where the skills, the Claude program and its sign-in are on this PC. It names the "
                "account beside each login folder, and refuses one that is not signed in.",
                "ChatGPT: who is signed in for pictures, and how many were made today.",
                "You in the preview: your name, headline and photo for every post's preview. They stay on this PC; "
                "Put them on carousels too (off at first) puts them on carousel slides drawn from then on.",
                "Posting times: the days, and a time for each, that the queue gives its posts. One post a day at "
                "most.",
                "Publishing: your Publora plan, which sets how many posts go out a month, how many wait at Publora at "
                "a time and how far ahead. Starter is free with 15 a month; Pro has no limits.",
                "Post style: the hook, tone, emojis and layout every new draft is written with. It always stays "
                "professional.",
                "Backup and restore: Back up downloads one file of everything of yours (the Story Bank, the voice "
                "profile, the posts with their pictures and chats, the settings), never a key or a sign-in. Restore "
                "from a backup… puts back the parts you tick, here or on a new PC, after keeping how the studio was.",
                "Connections confirms your Publora key works. Run it after changing .env.",
                "Recent runs lists every Claude run and how long it took."]},
    {"key": "trash", "title": "Trash", "href": "#~trash", "icon": "trash",
     "purpose": "The posts you moved out of the way, kept until you say otherwise.",
     "points": ["Move to Trash… in a post's gear sends a draft, approved, failed, cancelled or published post here, "
                "with its versions, chat and pictures. A published one stays on LinkedIn.",
                "Put back returns it to your posts as it was.",
                "Delete forever… and Empty trash ask first and name what goes. Scheduled posts never come here: "
                "cancel one on Publora first."]},
]

# The text in the "Try the editor" box. Two blanks, so Next blank has something to find.
SAMPLE_POST = """On 14 March I stopped coding my side project after 10 pm.

In the [N] weeks after, commits fell from 31 a week to 14. I expected the project to stall.

What I got back was seven hours of sleep instead of five, and [N] rollbacks in the next quarter against six before.

What did you stop doing that made your work better?"""

SHORTCUTS = [
    ("/", "Search your posts (on Hot topics: the news)"),
    ("Ctrl + K", "Search posts, pages and actions"),
    ("Alt + N", "A new post"),
    ("Ctrl + /", "Ask Claude"),
    ("Alt + ↑ / Alt + ↓", "The previous or next post"),
    ("?", "These shortcuts"),
    ("Enter", "Send in Ask Claude and the interviews"),
    ("Shift + Enter", "A new line in a chat"),
    ("↑", "In an empty Ask box: brings back your last message"),
    ("← / →", "On Ask Claude's edge: the panel wider or narrower (with Shift, in bigger steps)"),
    ("Ctrl + Enter", "Run the tool you are typing in"),
    ("Ctrl + S", "Save the post now (it also saves by itself)"),
    ("Ctrl + B", "In the post's text: the selection in LinkedIn's bold (again: plain)"),
    ("Esc", "Close a dialog, or leave the text for the preview"),
]

# The Guide's pictures (static/guide/<name>-light|dark.webp or .jpg), each with the words a screen reader hears.
SHOT_WORDS = {
    "post": "A post as LinkedIn shows it, with Ask Claude beside it",
    "chat": "Ask Claude at work: each step numbered while it runs",
    "schedule": "Schedule…: the time, the recommended slots and the final check",
    "coming": "Schedule: Coming up, with the queue in line order and the posting times still free",
    "hot": "Hot topics: the news ranked for you, each item with why, its post and Draft",
    "bank": "Story Bank & Voice, with the interviewer beside it",
    "tools": "Tools, with a result to copy",
    "trash": "The Trash, with Put back and Delete forever…",
}


def shots(folder: Path) -> dict[str, dict]:
    """The pictures present: {name: {light, dark, alt}}. A name with one theme only shows it in both."""
    found: dict[str, dict] = {}
    for name, words in SHOT_WORDS.items():
        urls = {}
        for theme in ("light", "dark"):
            for ext in ("webp", "jpg"):
                path = folder / f"{name}-{theme}.{ext}"
                if path.is_file():
                    urls[theme] = f"/static/guide/{path.name}?v={int(path.stat().st_mtime)}"
                    break
        if urls:
            found[name] = {"light": urls.get("light") or urls["dark"], "dark": urls.get("dark") or urls["light"],
                           "alt": words}
    return found


def fill(value, numbers: dict):
    """Put the live numbers into the text: strings, and lists/dicts of them."""
    if isinstance(value, str):
        return value.format(**numbers) if "{" in value else value
    if isinstance(value, (list, tuple)):
        return type(value)(fill(v, numbers) for v in value)
    if isinstance(value, dict):
        return {k: fill(v, numbers) for k, v in value.items()}
    return value
