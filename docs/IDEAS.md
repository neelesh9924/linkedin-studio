# Ideas

Ideas the owner has given in conversation, kept in their words where they carry the intent. Parked until the owner
picks one up; my notes are marked as mine.

## Hot topics (parked 3 Nov 2026, built 4 Nov 2026)

In the owner's words: "a hot topic button, latest in tech news related to our niche, in the create section maybe, or
maybe a dedicated section where we get to see the hot topics, and a draft button along, whichever we like, we make a
post out of it." Parked until the post layout work was done ("first lets do above and then will pick this"), then
picked up with "lets build this" on 4 Nov 2026.

Built as the Hot topics page (app/hot.py, static/js/hot.js), a line of its own in the sidebar under Schedule (then the Planner): the
owner chose that over a section on the Planner or a choice behind New post.

My notes, what was decided:
- The niche is the persona's pillars: Android and Kotlin, Flutter, Swift and iOS, Django and Python, Postgres, the
  web, and AI coding agents (agents that write code, not every AI agent).
- Sources, checked against the live web first: the teams' own feeds, and the Hacker News stories with 100 points or
  more in the last 14 days whose titles name the niche. The studio asks under its own name; Swift.org, Apple's
  developer news and Django News drop that connection, Reddit limits it, Anthropic has no feed, so they are left
  out rather than asked in disguise.
- Draft is the studio's own draft job with the item: Claude gets the article as untrusted text (the feed's own text,
  else the page as text, else the summary), writes a teaching post from it, and the link goes in the first comment.

Then, the same day, in the owner's words: "why only hackernews and teams, it shoul be curated well as per its rank of
postability an relativity to the user too". Built on their yes, after a ranked sample of that day's 241 items:
- More sources, each checked to answer the studio under its own name: every article of the Android Weekly and iOS Dev
  Weekly issues, the Swift and Django forums, engineering blogs, Firebase, and dev.to's most liked of the week.
  Lobsters (it repeats Hacker News), Reddit (it refuses after one request) and Postgres and JavaScript Weekly (they drop
  the connection) are left out.
- One rank per item, 1 to 10, on the scale of a post's own rank: how good a post it makes for the owner, from how it
  fits them (their voice profile; the run is refused the Story Bank, whose stories are private) and
  whether it makes a post. With why, the post it would become (Draft writes that), and the same story merged.
