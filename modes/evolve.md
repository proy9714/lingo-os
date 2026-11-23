# /lingo evolve

The weekly review, reasoned by you instead of the app's own model. Scripts measure; you propose; the app validates.

1. Get the facts (writes nothing): `uv run --project backend lingo evolve-profile --dry-run --json`.
   For each language you get `metrics` (minutes by activity and modality, words saved and marked known, lookups,
   items opened/finished/dropped, lookups per 1,000 words by difficulty band, tutor and shadowing numbers, Level Lab
   results) and `context` (words being learned, grammar slips, recent corrections, the tutor's current style).
2. Write `data/proposals/evolve-<YYYY-MM-DD>.json` with this shape (one entry per language you have something to say about):
   ```json
   {"languages": {"de": {
     "narrative_md": "4–8 sentences for the report, based only on the numbers.",
     "focus_words": ["only words from context.learning_words"],
     "focus_grammar": ["up to 3 grammar points, from context.grammar when possible"],
     "tutor_instructions_md": "A short brief for the tutor: topics, what to recast, what to avoid.",
     "style": {"speech_rate": null, "max_sentence_words": null},
     "suggested_goal_minutes": null
   }}}
   ```
3. Apply it: `uv run --project backend lingo evolve-profile --apply data/proposals/evolve-<date>.json --json`.
   The app clamps style changes, drops focus words that aren't on the learning list, shifts the difficulty band by at
   most two points from the numbers alone, and writes `data/reports/<year>-W<week>.md`.
4. Summarise for the learner: minutes, what changed (`adjustments` with reasons), guardrail `notes`, and where the
   report is. Level estimates are ranges; say so.

Rules: never suggest flashcards, spaced repetition or word drills. Don't invent numbers. Don't edit the database.
