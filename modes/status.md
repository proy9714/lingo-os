# /lingo status [lang]

1. Run `uv run --project backend lingo status --json` (add `--lang <code>` if the user named a language).
2. For each language in the result, report in a compact table:
   - total hours, split into "before tracking" (`baseline_hours`) and `tracked_hours`
   - today's minutes vs the daily goal (`today.today_minutes` / `today.goal_minutes`)
   - last session date
   - starting level: `estimate.level` of `estimate.max_level`, `estimate.words_prior` words, labelled
     "hours only, low confidence"
3. Add at most two observations from `monthly` and `today.last7`, e.g. a drop or rise between months, or a gap
   since the last session. State them neutrally; no guilt-tripping.
4. If a language has no tracked sessions (only baseline hours), say that its estimate rests on hours alone and that the
   Level Lab (Phase 1) will measure it properly.
