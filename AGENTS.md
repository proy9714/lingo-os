# Lingo OS: instructions for AI terminals

This folder is **Lingo OS**, a local-first language-immersion app for German (`de`), Spanish (`es`) and Japanese (`ja`).
You (Gemini CLI, Claude Code, Codex, …) can operate it through `/lingo <mode>`.

## Ground rules

1. **Never edit the SQLite files directly** (`data/lingo.db`, `data/dictionaries.db`). Read and change data only through
   the CLI: `uv run --project backend lingo <command> --json`. Later modes write a proposal file and apply it with
   `--apply`, which validates it first.
2. **No flashcards, ever.** Do not suggest review decks, spaced repetition, Anki or "due" words. Saved words come back
   through content and the tutor.
3. **Level estimates are ranges with a confidence value.** Never present them as exact.
4. Personal data stays local. Do not paste database contents, CSVs or reports into web searches or external tools.
5. Design and roadmap: `docs/ARCHITECTURE.md`. Schema: `docs/schema.sql`.

## Modes

The router is `modes/_shared.md`; each mode's playbook is `modes/<mode>.md`.

| Mode | Status | What it does |
|---|---|---|
| `status [de\|es\|ja]` | ready | Hours, today vs goal, recent trend, starting level range |
| `import` | ready | Re-sync the Immersion Tracker CSVs |
| `doctor` | ready | Check the environment and explain any problem |
| `recommend [de\|es\|ja]` | ready | Top i+1 picks with reasons |
| `update-content [de\|es\|ja]` | ready | Discover new videos and articles at your level |
| `evolve` | ready | Weekly recalibration and progress report (you propose, the app validates) |
| `plan-week`, `tutor-brief` | ready | Plan the week; edit next week's tutor brief |
| `release` | ready | Maintainers: publish a GitHub release with the signed APK, only if the app changed, after a yes |

If asked for a mode that is not ready, say which phase delivers it and offer what is available now.

Useful read-only commands for any mode: `uv run --project backend lingo dict list --json` (installed dictionaries).
Never start a Level Lab test on the user's behalf. Tests are answered by the user in the app.

## Running the app

- `npm run dev`: API on http://127.0.0.1:8787 plus the web app on http://localhost:5173
- `npm run start`: build and serve everything on http://127.0.0.1:8787
- `npm test`: backend tests plus the frontend typecheck
