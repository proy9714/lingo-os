# Lingo OS

A local-first, single-window system for learning **German, Spanish and Japanese** through comprehensible input.
Watch, read, look words up, track immersion and practise speaking without leaving the app. Your data stays on your
laptop in `data/`.

The design, schema and roadmap are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Status

**Phases 0 and 1 are done.**

Phase 1, the word engine and Level Lab:

- **Read** (paste mode): paste any German, Spanish or Japanese text. Words are coloured as likely new or learning, and every word is clickable. Shows how much of the text you probably know.
- **Lookup panel**: dictionary form (*rufe … an* → *anrufen*, *muss* → *müssen*, *dámelo* → *dar*, 間に合わない → 間に合う), readings, glosses, German gender/plural/conjugation notes, frequency rank and browser pronunciation. Set a word to new, learning, known or ignored, or save it with its sentence.
- **Words**: everything you saved or looked up, with sentences and notes. A browser, not flashcards.
- **Level Lab**:
  - Adaptive vocabulary test, about 5 minutes. Meanings are verified and made-up words catch guessing. The result is a vocabulary range and approximate CEFR (and JLPT) band.
  - C-test reading check for German and Spanish.
  - Results recolour your texts.
- **Dictionaries**: Jitendex (ja) and Wiktionary-derived de/es dictionaries, imported with `npm run lingo -- dict import`.

Phase 0, the foundation:

- Glass app shell for desktop and phone widths, with a DE / ES / JA switcher that re-themes the app
- Today dashboard on your real history: daily goal, last 7 days, tracked hours by month, all languages, recent sessions
- A starting level range per language (hours only, low confidence) on your tracker's 7-level roadmap
- Import and re-sync of your Immersion Tracker CSVs (`D:\Language-Immersion\data`). It is idempotent, and a probable
  double-log is held back until you confirm it.
- Manual time logging (`+ Log` or Ctrl+L)
- Settings: daily goals, tracker sync, system checks, this laptop's device id
- `/lingo status`, `/lingo import` and `/lingo doctor` from Gemini CLI or Claude Code opened in this folder

Pages for Watch, Read, Manga, Speak, Words and Level describe what each phase will add.

## Requirements

Windows with Node 18+ and [uv](https://docs.astral.sh/uv/). uv installs Python 3.12 for the backend if needed.

## Commands

| Command | What it does |
|---|---|
| `npm run setup` | Install backend and frontend dependencies and create the databases |
| `npm run dev` | API on http://127.0.0.1:8787 and the app on **http://localhost:5173**, both reloading on changes |
| `npm run start` | Build the app and serve everything on **http://127.0.0.1:8787** |
| `npm test` | Backend tests plus the frontend typecheck |
| `npm run status` | Hours, today vs goal and starting level per language (add `-- --json` for JSON) |
| `npm run import-tracker` | Import or re-sync the Immersion Tracker CSVs |
| `npm run doctor` | Check Python, data folder, databases, build, ffmpeg and API keys |
| `npm run lingo -- dict import` | Import every Yomitan dictionary zip in `data/dictionaries` (re-importing replaces) |
| `npm run lingo -- dict list` | Show installed dictionaries |

`npm run dev` starts the API through `backend/app/devserver.py`. On Windows, uvicorn's auto-reload sends Ctrl+C to the
whole console, which would also stop Vite. The launcher keeps the API on its own hidden console.

## In an AI terminal

Open Gemini CLI (or Claude Code) in this folder and type `/lingo`, `/lingo status de`, `/lingo import` or
`/lingo doctor`. Instructions live in `AGENTS.md`, and each mode's playbook in `modes/`. The AI reads and changes data
only through the `lingo` CLI, never by touching the database files.

## Configuration

- `config/app.yaml`: data folder, languages, default goal, Immersion Tracker path
- `config/baselines.yaml`: hours → level roadmap and per-language difficulty divisors
- `config/llm.yaml`: AI task routing (Gemini by default; used from Phase 4)
- `.env`: API keys only (copy `.env.example`)

## Layout

```
backend/   FastAPI + SQLite (Python, uv)     frontend/  React + Vite + Tailwind
config/    YAML settings                     docs/      architecture + schema
modes/     /lingo playbooks for AI terminals data/      your personal data (git-ignored)
```
