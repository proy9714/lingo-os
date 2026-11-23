# Lingo OS

A local-first, single-window system for learning **German, Spanish and Japanese** through comprehensible input.
Watch, read, look words up, track immersion and practise speaking without leaving the app. Your data stays on your
laptop in `data/`.

The design, schema and roadmap are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Status

**Phases 0–7 are done.**

Phases 6–7, speaking:

- **Tutor** (Speak → Tutor; needs an AI provider): chat by typing or with the microphone, replies read aloud. It writes at your level, reuses words you're learning, and simplifies any reply with too many unknown words. Modes: conversation, role-play cards, talk about something you watched or read, grammar practice. **End and review** adds corrections to your turns and a summary, and records grammar slips, which feed the next conversation.
- **Shadowing** (Speak → Shadowing): press **Shadow this line** in the video player, or type any sentence. Listen once or loop with a pause for your turn, at 0.5–1× speed, record yourself, and see which words were recognised. Recordings stay in `data\recordings\`.
- **Level Lab → Speaking**: hear a sentence, say it back; ten sentences from A1 to C1.
- Voice input uses the browser's speech recognition (Chrome and Edge send the audio to their speech service); spoken replies use the browser's voices.

Phase 5, manga:

- Drop volumes into `data\inbox\manga\` (Japanese; use a `de` or `es` subfolder for other languages): a `.mokuro` file with its image folder, a folder of page images, or a `.zip`/`.cbz`. They're imported when you open Manga (or run `npm run lingo -- manga scan`). Nothing is deleted: volumes move into the library, zips into `_imported`.
- The viewer fits pages to the screen, one or two at a time, right to left for Japanese. Hover a speech bubble to see its text, click a word to look it up. **Fix OCR text** corrects a bubble; **Volume words** lists the likely-new words with the page they first appear on.
- **Mokuro Bunko**: the Manga screen links to catalog.mokuro.moe. Lingo OS never crawls it.
- Volumes without mokuro text can be read as images. Running OCR here needs mokuro, which isn't installed (a large download, like Whisper).

Phase 4, AI explanations (optional; everything else works without them):

- Click a word and the lookup panel says what it means **in that sentence**, marks the dictionary sense that fits, and adds a usage note. Translation and a grammar breakdown are one click away; the sentence can be played aloud.
- Gemini by default: put `GEMINI_API_KEY=…` in `.env` (copy `.env.example`), restart, then press **Test connection** in Settings or run `npm run lingo -- ai test`.
- Any OpenAI-compatible server works too (Ollama on this laptop, OpenRouter, LM Studio); see `config/llm.yaml`. `local_only: true` keeps every request on this computer.
- Answers are cached, and every call is logged with its token count (Settings shows the totals). Only the sentence you ask about is sent.

Phase 3, read and Up Next:

- **Read**:
  - Your shelf of books (.epub), PDFs with a text layer, web articles (the main text is extracted once and kept locally) and pasted texts.
  - Each shows how much you'd know and the expected new words.
- **Reader**:
  - Pages on a paper background, every word clickable. A saved word keeps just its sentence as context.
  - Arrow keys turn pages, text size is adjustable, and it reopens where you left off.
  - Reading time is tracked while the page is open and you've been active in the last 3 minutes.
- **Up Next** on Today: 12 picks matched to your level. They favour items that bring back your saved words and things you've started, and mix channels and formats. Dismiss any pick with ×.
- `npm run lingo -- content rescore` refreshes the starting estimate and every item's score.

Phase 2, watch and listen:

- **Watch**:
  - Your library: the videos from your tracker history plus any YouTube link you add, and local media found by scanning `data\library\media\<lang>\` (same-named `.srt`/`.vtt` files become transcripts).
  - Each video shows how much you'd know, the expected new words and its speaking speed.
- **Player**:
  - YouTube or local file next to a synced transcript. Click a word: the video pauses, the lookup opens, and it resumes when you close it.
  - Previous, next and replay line; speed control; pause after each line.
  - Watching time is tracked only while it plays, with a live timer in the top bar.
- **History analysis**: fetches the captions of every video you watched (`npm run lingo -- content fetch-history`, or the button on Watch). It counts how often you've heard each word, which feeds word colouring and your starting level.
- **Level Lab listening**: dictation of graded sentences read by your browser's voice.

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
| `npm run lingo -- content fetch-history` | Fetch and analyse captions of the videos you've watched (resumes where it stopped) |
| `npm run lingo -- content rescore` | Refresh the starting estimate and re-score the library |
| `npm run lingo -- recommend` | Up Next picks with reasons (`--lang es`, `--json`) |
| `npm run lingo -- manga scan` | Import volumes from `data\inbox\manga\` |
| `npm run lingo -- ai status` / `ai test` / `ai models` | Which model each task uses; check the key; list the Gemini models your key can use |

`npm run dev` starts the API through `backend/app/devserver.py`. On Windows, uvicorn's auto-reload sends Ctrl+C to the
whole console, which would also stop Vite. The launcher keeps the API on its own hidden console.

## In an AI terminal

Open Gemini CLI (or Claude Code) in this folder and type `/lingo`, `/lingo status de`, `/lingo import` or
`/lingo doctor`. Instructions live in `AGENTS.md`, and each mode's playbook in `modes/`. The AI reads and changes data
only through the `lingo` CLI, never by touching the database files.

## Configuration

- `config/app.yaml`: data folder, languages, default goal, Immersion Tracker path
- `config/baselines.yaml`: hours → level roadmap and per-language difficulty divisors
- `config/llm.yaml`: AI providers and task routing (Gemini by default)
- `.env`: API keys only (copy `.env.example`)

## Layout

```
backend/   FastAPI + SQLite (Python, uv)     frontend/  React + Vite + Tailwind
config/    YAML settings                     docs/      architecture + schema
modes/     /lingo playbooks for AI terminals data/      your personal data (git-ignored)
```
