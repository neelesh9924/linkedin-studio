"""What the in-app Guide says. Words live here; the page draws them (static/js/guide.js).

Numbers that the app enforces (limits, targets) are passed in from the code that enforces
them, so the guide cannot drift from the behaviour. `href` is where in the studio a step
happens (the page's own addresses), `icon` one of the page's icons, `demo` the small example
drawn beside a step.
"""
from __future__ import annotations

# The routine as a flowchart: lanes by how often, steps in order. `claude` says whether pressing the
# button runs Claude.
LANES = [
    {"label": "Once", "note": "Before your first plan", "steps": [
        {"id": "stories", "title": "Tell it your stories", "icon": "chat", "where": "Story Bank & Voice",
         "href": "#~bank", "claude": "Each message runs Claude, a few seconds", "demo": "chat",
         "do": ["Open Story Bank & Voice. The interviewer is on the right.", "Press Start the interview, then answer one "
                "question at a time. Enter sends, Shift+Enter adds a line.",
                "Stop whenever you like. Next time it carries on and only asks about thin sections."],
         "gives": "Your Story Bank: roles, real numbers, turning points and opinions, kept on this computer. "
                  "Drafts draw on it instead of leaving blanks."},
        {"id": "voice", "title": "Teach it your voice", "icon": "feather", "where": "Story Bank & Voice, Voice profile",
         "href": "#~voice", "claude": "Each message runs Claude", "demo": "voice", "optional": True,
         "do": ["Switch to Voice profile.", "Paste three to six of your own posts or comments.",
                "Read the profile it shows you, and say yes to save it."],
         "gives": "Drafts follow your rhythm, openers and habits. Skip this if you have never posted."},
    ]},
    {"label": "Every week", "note": "Under a minute of waiting", "steps": [
        {"id": "plan", "title": "Plan the week", "icon": "calendar", "where": "Planner", "href": "#~planner",
         "claude": "Runs Claude, under a minute", "demo": "plan",
         "do": ["Say who you write for and what the week should achieve.", "Pick 3, 4 or 5 posts.",
                "Press Plan the week. You can leave the page while it runs."],
         "gives": "One card per post with a day, an angle and a hook formula, plus who to comment on each day."},
    ]},
    {"label": "Every post", "note": "Your facts are the real work", "steps": [
        {"id": "draft", "title": "Draft it", "icon": "sparkle", "where": "Planner", "href": "#~planner",
         "claude": "Runs Claude, about 30 seconds", "demo": "working",
         "do": ["Press Draft this on a plan card: the draft joins the posts in the sidebar.",
                "Or press + New post and tell Claude, on the right, what the post is about.",
                "You can leave the page while it runs; a notice tells you when it is ready."],
         "gives": "A draft built on the planned formula, in the list on the left."},
        {"id": "blanks", "title": "Fill the blanks", "icon": "target", "where": "The post", "href": "#~posts",
         "claude": "", "demo": "blanks",
         "do": ["Where the writer had no real fact it left a blank like [N], marked in yellow.",
                "Press Next blank, then type the real number, name or date over it.",
                "Typing saves by itself about a second after you stop."],
         "gives": "A post made of your facts. Nothing is invented for you."},
        {"id": "ask", "title": "Ask Claude", "icon": "chat", "where": "The post, Ask Claude", "href": "#~posts",
         "claude": "Runs Claude, from seconds to a few minutes", "demo": "ask",
         "do": ["Ask in the panel beside the post: shorter, a new hook, an audit, an illustration.",
                "Claude rewrites the post in place and keeps a version each time; the gear's Versions go back.",
                "An illustration shows under its reply. Use as the picture puts it on the post."],
         "gives": "Changes in your voice, and pictures from ChatGPT ({per_request} at most a request)."},
        {"id": "audit", "title": "Audit and revise", "icon": "check-circle", "where": "The post", "href": "#~posts",
         "claude": "Runs Claude, about 40 seconds", "demo": "audit",
         "do": ["Press Audit. The findings appear beside the post: red must be fixed, amber is worth a look.",
                "Want a different take? Revise: New hook, Shorter or More technical.",
                "A revision shows every change word by word. Nothing is replaced until you choose Use this version."],
         "gives": "Either a pass, or a short list of concrete fixes."},
        {"id": "approve", "title": "Approve", "icon": "check", "where": "The post's top bar", "href": "#~posts",
         "claude": "", "demo": "approve",
         "do": ["Press Approve this text.", "It is refused while a blank remains, or past {post_max} characters.",
                "Approved text and picture are locked. Back to draft unlocks them."],
         "gives": "A final post that cannot change by accident."},
        {"id": "schedule", "title": "Schedule", "icon": "send", "where": "The post's top bar", "href": "#~posts",
         "claude": "", "demo": "schedule",
         "do": ["Press Schedule…, pick a time or tap a recommended slot.",
                "Check the final text, the picture, the time and the first comment, then confirm.",
                "It must be between {min_lead} minutes and {max_days} days ahead."],
         "gives": "The post waits at Publora with its picture. If the connection drops, Try again carries on and "
                  "cannot create a second copy."},
        {"id": "published", "title": "Published", "icon": "check-circle", "where": "Planner", "href": "#~planner",
         "claude": "", "demo": "published",
         "do": ["After the time has passed, press Check Publora on the Planner.",
                "The post shows as Published and counts toward your {limit} for the month."],
         "gives": "It is on LinkedIn. A link you put in First comment appears right under it."},
    ]},
    {"label": "Every day", "note": "Alongside your own posts", "steps": [
        {"id": "comment", "title": "Comment on others", "icon": "comment", "where": "Tools, Comment drafter",
         "href": "#~tools-comment", "claude": "Runs Claude, usually under half a minute", "demo": "comment",
         "do": ["Paste a post from someone your plan lists under Who to comment on.",
                "Press Draft comments and copy the one you like.",
                "Post it yourself. The app never comments or reacts for you."],
         "gives": "Two or three comments with a suggested reaction each."},
    ]},
]

# What a post can do in each state: (state, what it means, what you can do).
STATES = [
    ("Draft", "You are still writing.", ["Edit the text in place; it saves by itself", "Ask Claude, Audit and Revise",
                                         "Choose or remove its picture", "Approve, once no blank remains", "Delete"]),
    ("Approved", "The text and picture are final and locked.", ["Schedule… and pick a time", "Back to draft to edit again",
                                                                "Delete"]),
    ("Scheduled", "It is waiting at Publora.", ["Check status", "Cancel on Publora (the gear)", "Open the Publora dashboard"]),
    ("Published", "It is on LinkedIn.", ["Nothing more to do here", "It counts toward this month's {limit}"]),
]

SCREENS = [
    {"key": "post", "title": "A post", "href": "#~posts", "icon": "file",
     "purpose": "The post as LinkedIn shows it, and the place you finish it.",
     "points": ["The middle shows it as a reader sees it, at Desktop or Phone width, with \"…more\" after about {fold} "
                "characters and its picture.",
                "Click the text to edit it there. The meter shows your length against the {target_min}-{target_max} "
                "sweet spot.",
                "The top bar says where it stands and holds the next step: Approve, then Schedule…",
                "The gear holds the title, Versions to go back to, and Delete."]},
    {"key": "chat", "title": "Ask Claude", "href": "#~posts", "icon": "sparkle",
     "purpose": "A conversation beside each post, kept with it.",
     "points": ["Ask for any change; Claude rewrites the post and keeps a version.",
                "It runs your skills: the post writer, the humanizer, the audit and the hook extractor.",
                "Ask for an illustration and ChatGPT makes one; Use as the picture puts it on the post.",
                "Each step shows while it works, and Stop ends it."]},
    {"key": "planner", "title": "Planner", "href": "#~planner", "icon": "calendar",
     "purpose": "This month at a glance, and the week in one go.",
     "points": ["Posts used this month, the next scheduled post and Claude's status at the top.",
                "Plan the next 7 days: each card is one post; Draft this writes it.",
                "Below: who to comment on, and the inbound-readiness checklist.",
                "Older plans move to Earlier plans."]},
    {"key": "bank", "title": "Story Bank & Voice", "href": "#~bank", "icon": "book",
     "purpose": "What the skills know about you, and the interviews that fill it.",
     "points": ["Read-only, so the format stays what the skills expect.",
                "The list beside it shows which sections have material.",
                "On the right, the interviewer (Story Bank) or the voice-profile chat (Voice profile).",
                "Both files stay on this computer. The lock chip confirms git leaves them alone."]},
    {"key": "tools", "title": "Tools", "href": "#~tools", "icon": "tool",
     "purpose": "One-off jobs. Nothing here is posted; you copy what you want.",
     # The page adds one line per tool in front of these, in the words the Tools screen uses.
     "points": ["Under a Humanize result, Compare with the original shows every change.",
                "A repurposed post has Save as a post, which adds it to your posts."]},
    {"key": "settings", "title": "Settings", "href": "#~settings", "icon": "settings",
     "purpose": "Checking that everything is connected.",
     "points": ["Change folders: where the skills, the Claude program and its sign-in are on this PC.",
                "ChatGPT: who is signed in for pictures, and how many were made today.",
                "Connections confirms your Publora key works. Run it after changing .env.",
                "Recent runs lists every Claude run and how long it took."]},
]

# The text in the "Try the editor" box. Two blanks, so Next blank has something to find.
SAMPLE_POST = """On 14 March I stopped coding my side project after 10 pm.

In the [N] weeks after, commits fell from 31 a week to 14. I expected the project to stall.

What I got back was seven hours of sleep instead of five, and [N] rollbacks in the next quarter against six before.

What did you stop doing that made your work better?"""

SHORTCUTS = [
    ("Enter", "Send in Ask Claude and the interviews"),
    ("Shift + Enter", "A new line in a chat"),
    ("Ctrl + Enter", "Run the tool or dialog you are typing in"),
    ("Ctrl + S", "Save the post now (it also saves by itself)"),
    ("Esc", "Close a dialog, or leave the text for the preview"),
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
