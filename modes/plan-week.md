# /lingo plan-week [lang]

Plan the coming week from goals and gaps. Read-only: nothing is written.

1. Facts: `uv run --project backend lingo status --json` (goals, hours, recent days) and
   `uv run --project backend lingo evolve-profile --dry-run --json` (last week's metrics per language).
2. Picks: `uv run --project backend lingo recommend --lang <code> --json` for each language you plan.
3. Propose a simple plan: for each day, about how many minutes of what (watch, read, manga, tutor, shadowing),
   naming 3–5 concrete items from the picks. Balance modalities using last week's numbers (for example more
   speaking if `minutes_by_modality.speaking` was near zero). Keep the total at or slightly above the daily goals.
4. One sentence on why. No flashcards or vocabulary drills: saved words return through the chosen content and the tutor.
