"""What the in-app Guide says. Words live here; layout lives in templates/guide.html.

Numbers that the app enforces (limits, targets) are passed in from the code that enforces
them, so the guide cannot drift from the behaviour.
"""
from __future__ import annotations

# The routine as a flowchart: lanes by how often, steps in order. `demo` picks the small
# live example shown beside a step; `claude` says whether pressing the button runs Claude.
LANES = [
    {"label": "Once", "note": "Before your first plan", "steps": [
        {"id": "stories", "title": "Tell it your stories", "icon": "chat", "where": "Interviewer",
         "href": "/interviewer?mode=bank", "claude": "Each message runs Claude, a few seconds", "demo": "chat",
         "do": ["Press Start the interview.", "Answer one question at a time. Enter sends, Shift+Enter adds a line.",
                "Stop whenever you like. Next time it carries on and only asks about thin sections."],
         "gives": "Your Story Bank: roles, real numbers, turning points and opinions, kept on this computer. "
                "Drafts draw on it instead of leaving blanks."},
        {"id": "voice", "title": "Teach it your voice", "icon": "feather", "where": "Interviewer, Voice profile tab",
         "href": "/interviewer?mode=voice", "claude": "Each message runs Claude", "demo": "voice", "optional": True,
         "do": ["Paste three to six of your own posts or comments.", "Read the profile it shows you.",
                "Say yes and it is saved."],
         "gives": "Drafts follow your rhythm, openers and habits. Skip this if you have never posted."},
    ]},
    {"label": "Every week", "note": "Under a minute of waiting", "steps": [
        {"id": "plan", "title": "Plan the week", "icon": "calendar", "where": "Planner", "href": "/planner",
         "claude": "Runs Claude, under a minute", "demo": "plan",
         "do": ["Say who you write for and what the week should achieve.", "Pick 3, 4 or 5 posts.",
                "Press Plan the week. You can leave the page while it runs."],
         "gives": "One card per post with a day, an angle and a hook formula, plus who to comment on each day."},
    ]},
    {"label": "Every post", "note": "Your facts are the real work", "steps": [
        {"id": "draft", "title": "Draft it", "icon": "sparkle", "where": "Planner or Drafts", "href": "/planner",
         "claude": "Runs Claude, about 30 seconds", "demo": "working",
         "do": ["Press Draft this on a plan card.", "Or use Write a post on Drafts for any topic.",
                "A notice with an Open link tells you when it is ready."],
         "gives": "A draft built on the planned formula, waiting in Drafts."},
        {"id": "blanks", "title": "Fill the blanks", "icon": "target", "where": "Draft editor", "href": "/drafts",
         "claude": "", "demo": "blanks",
         "do": ["Open the draft. Where the writer had no real fact it left a blank like [N].",
                "Press Next blank and type the real number, name or date over it.",
                "Typing saves by itself about a second after you stop."],
         "gives": "A post made of your facts. Nothing is invented for you."},
        {"id": "audit", "title": "Audit and revise", "icon": "check-circle", "where": "Draft editor", "href": "/drafts",
         "claude": "Runs Claude, about 40 seconds", "demo": "audit",
         "do": ["Press Run the audit. Red must be fixed, amber is worth a look.",
                "Want a different take? New hook, Shorter or More technical.",
                "A revision shows every change word by word. Nothing is replaced until you choose Use this version."],
         "gives": "Either a pass, or a short list of concrete fixes."},
        {"id": "approve", "title": "Approve", "icon": "check", "where": "Draft editor", "href": "/drafts",
         "claude": "", "demo": "approve",
         "do": ["Press Approve this text.", "It is refused while a blank remains, or past {post_max} characters.",
                "Approved text is locked. Back to draft unlocks it."],
         "gives": "A final text that cannot change by accident."},
        {"id": "schedule", "title": "Schedule", "icon": "send", "where": "Draft editor", "href": "/drafts",
         "claude": "", "demo": "schedule",
         "do": ["Pick a time, or tap one of the recommended slots.",
                "Press Schedule… and check the final text, the time and the first comment.",
                "Confirm. It must be between {min_lead} minutes and {max_days} days ahead."],
         "gives": "The post waits at Publora. If the connection drops, Try again cannot create a second copy."},
        {"id": "published", "title": "Published", "icon": "check-circle", "where": "Home", "href": "/",
         "claude": "", "demo": "published",
         "do": ["After the time has passed, press Check Publora on Home.",
                "The post shows as Published and counts toward your {limit} for the month."],
         "gives": "It is on LinkedIn. A link you put in First comment appears right under it."},
    ]},
    {"label": "Every day", "note": "Alongside your own posts", "steps": [
        {"id": "comment", "title": "Comment on others", "icon": "comment", "where": "Tools, Comment drafter",
         "href": "/tools?tool=comment", "claude": "Runs Claude, usually under half a minute", "demo": "comment",
         "do": ["Paste a post from someone your plan lists under Who to comment on.",
                "Press Draft comments and copy the one you like.",
                "Post it yourself. The app never comments or reacts for you."],
         "gives": "Two or three comments with a suggested reaction each."},
    ]},
]

# What a post can do in each state: (state, what it means, what you can do).
STATES = [
    ("Draft", "You are still writing.", ["Edit freely; it saves by itself", "Audit and Revise", "Approve, once no blank remains",
                                         "Delete"]),
    ("Approved", "The text is final and locked.", ["Pick a time and Schedule…", "Back to draft to edit again", "Delete"]),
    ("Scheduled", "It is waiting at Publora.", ["Check status", "Cancel on Publora", "Open the Publora dashboard"]),
    ("Published", "It is on LinkedIn.", ["Nothing more to do here", "It counts toward this month's {limit}"]),
]

SCREENS = [
    {"key": "home", "title": "Home", "href": "/", "icon": "home",
     "purpose": "Where things stand and what to do next.",
     "points": ["Getting set up: four steps, gone once all are done.",
                "Posts this month, counted toward your {limit}.",
                "This week's plan, with Draft it or Open on each post.",
                "Scheduled posts. Check Publora marks the ones whose time has passed."]},
    {"key": "interviewer", "title": "Interviewer", "href": "/interviewer", "icon": "chat",
     "purpose": "Filling your Story Bank and voice profile by talking.",
     "points": ["Two tabs: Story Bank and Voice profile.",
                "Enter sends. Stop ends a reply early.",
                "When it writes to your file, the reply shows Saved to story-bank.md; click to see the lines.",
                "New conversation starts fresh. Earlier ones stay in the list at the top."]},
    {"key": "bank", "title": "Story Bank & Voice", "href": "/bank", "icon": "book",
     "purpose": "Reading what the skills know about you.",
     "points": ["Read-only, so the format stays what the skills expect.",
                "The list on the right shows which sections have material.",
                "Change either file through the Interviewer.",
                "Both files stay on this computer. The lock chip confirms git leaves them alone."]},
    {"key": "planner", "title": "Planner", "href": "/planner", "icon": "calendar",
     "purpose": "Deciding the week in one go.",
     "points": ["The form remembers what you entered last time.",
                "Each card is one post. Draft this writes it.",
                "Below: who to comment on, and a readiness checklist.",
                "Older plans move to Earlier plans."]},
    {"key": "drafts", "title": "Drafts", "href": "/drafts", "icon": "pen",
     "purpose": "Every post, whatever its state.",
     "points": ["Write a post drafts from any topic. Blank draft is for your own text.",
                "Tabs filter by state.", "Click a row to open the editor."]},
    {"key": "editor", "title": "Draft editor", "href": "/drafts", "icon": "file",
     "purpose": "Finishing one post.",
     "points": ["The meter shows your length against the {target_min}-{target_max} sweet spot.",
                "The preview shows what readers see before \"more\", about {fold} characters.",
                "First comment is where links go; Publora posts it right after the post.",
                "On the right, top to bottom: preview, approve and schedule, audit, revise."]},
    {"key": "tools", "title": "Tools", "href": "/tools", "icon": "tool",
     "purpose": "One-off jobs. Nothing here is posted; you copy what you want.",
     # The page adds one line per tool in front of these, in the words the Tools screen uses.
     "points": ["Under a Humanize result, Compare with the original shows every change.",
                "A repurposed post has Save as draft, which sends it to Drafts."]},
    {"key": "settings", "title": "Settings", "href": "/settings", "icon": "settings",
     "purpose": "Checking that everything is connected.",
     "points": ["Change folders: where the skills, the Claude program and its sign-in are on this PC.",
                "Connections confirms your Publora key works. Run it after changing .env.",
                "Theme: Auto, Light or Dark.",
                "Recent runs lists every Claude run and how long it took."]},
]

# The text in the "Try the editor" box. Two blanks, so Next blank has something to find.
SAMPLE_POST = """On 14 March I stopped coding my side project after 10 pm.

In the [N] weeks after, commits fell from 31 a week to 14. I expected the project to stall.

What I got back was seven hours of sleep instead of five, and [N] rollbacks in the next quarter against six before.

What did you stop doing that made your work better?"""

SHORTCUTS = [
    ("Enter", "Send your answer in the Interviewer"),
    ("Shift + Enter", "A new line in the Interviewer"),
    ("Ctrl + Enter", "Run the tool or dialog you are typing in"),
    ("Ctrl + S", "Save the draft now (it also saves by itself)"),
    ("Esc", "Close a dialog"),
]


def fill(value, numbers: dict):
    """Put the live numbers into the text: strings, and lists/dicts of them."""
    if isinstance(value, str):
        return value.format(**numbers) if "{" in value else value
    if isinstance(value, (list, tuple)):
        return type(value)(fill(v, numbers) for v in value)
    if isinstance(value, dict):
        return {k: fill(v, numbers) for k, v in value.items()}
    return value
