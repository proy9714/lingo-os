# /lingo router (shared by every mode)

## How to call the app

Run commands from the project root:

```
uv run --project backend lingo <command> [options] --json
```

`--json` output is UTF-8 JSON on stdout. Treat it as the source of truth; do not guess numbers.

## Menu (show this when no mode is given)

| Mode | Ready? | Use it to |
|---|---|---|
| `/lingo status [de\|es\|ja]` | yes | See hours, today vs goal, recent trend and starting level range |
| `/lingo import` | yes | Re-sync the Immersion Tracker CSVs |
| `/lingo doctor` | yes | Check the setup and fix problems |
| `/lingo recommend [lang]` | yes | Get i+1 picks with reasons |
| `/lingo update-content [lang]` | yes | Find new content at your level |
| `/lingo evolve` | yes | Weekly recalibration and report |
| `/lingo plan-week`, `/lingo tutor-brief` | yes | Plan the week, edit the tutor brief |

## Rules for every mode

- Never open or edit `data/*.db` directly. Never run SQL.
- No flashcards, spaced repetition or Anki suggestions.
- Level estimates are ranges with a confidence value; say "hours-only, low confidence" when no Level Lab test was taken.
- Keep answers short: the numbers, one or two observations, and at most one suggestion.
- A mode marked "Phase N": say it is not built yet, which phase delivers it, and offer `status` instead.
