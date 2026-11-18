---
name: post-audit
description: "LinkedIn: audit a draft before posting (AI tells, hook, voice). Only when you type /post-audit."
argument-hint: "<the draft's text>"
disable-model-invocation: true
---

Audit this LinkedIn draft before it is posted: run `/linkedin-skills:linkedin-humanizer --mode audit` on it.

$ARGUMENTS

- Judge the voice against my voice profile, the one LinkedIn Studio keeps on its Story Bank & Voice page: `references/voice-profile.md` in my linkedin-skills folder (`skills_dir` in LinkedIn Studio's `config.local.toml`; ask me if you can't find it), not the plugin's own copy, which is an empty template. If mine is empty too, say so and go on without it.
- Never post, schedule or queue anything.
