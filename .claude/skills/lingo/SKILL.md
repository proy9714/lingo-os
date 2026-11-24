---
name: lingo
description: Operate Lingo OS (the language-immersion app in this folder) - /lingo status, import, doctor, recommend, update-content, evolve, plan-week, tutor-brief, release. Use when the user types /lingo or asks about their language-immersion data (any language added in the app).
---

# /lingo router

You are operating Lingo OS from its project folder. Follow AGENTS.md.

1. Read `modes/_shared.md` (the router).
2. Pick the mode from the first word of the user's request (no mode given: show the menu from `modes/_shared.md`).
3. Read `modes/<mode>.md` and follow it exactly. Use only the `lingo` CLI for data, never the SQLite files.
