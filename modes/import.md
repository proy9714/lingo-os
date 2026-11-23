# /lingo import

1. Run `uv run --project backend lingo import-tracker --json`.
2. Report per language: status (`imported`, `unchanged` or `missing`), new rows and rows already present.
3. If `goals_imported` is set, mention that the daily goals were copied from the tracker.
4. For each item in `pending_flags`: say it was **not counted** as a probable double-log, with the title, date and
   reason, and tell the user they can count it in the app under Settings → Immersion Tracker if it was a real rewatch.
   Do not count it yourself.
5. Finish with the updated totals from `uv run --project backend lingo status --json` (one line per language).
