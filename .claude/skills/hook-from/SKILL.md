---
name: hook-from
description: "LinkedIn: break down a viral post's hook into a template (reading the post spends a little Apify). Only when you type /hook-from."
argument-hint: "<a LinkedIn post's link>"
disable-model-invocation: true
---

Break down the hook of this LinkedIn post and give a blank template of it: `/linkedin-skills:linkedin-hook-extractor $ARGUMENTS`.

- Reading a post from its link spends a little of my Apify credit (the `APIFY_TOKEN` key, set in LinkedIn Studio's Settings → Publishing).
- If no link was given, ask for one, or for the post's text.
