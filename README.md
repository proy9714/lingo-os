# Lingo OS

**Learn a language by watching, reading and listening to things you enjoy, at the right level for you.**

Lingo OS is a free, local-first app for learning **German, Spanish and Japanese** through comprehensible input. It
finds YouTube videos and articles matched to your level, gives every video a clickable transcript and every text
clickable words, tracks your immersion time, and estimates your level from what you actually understand. It runs on
your computer, keeps your data there, and comes with an Android app that syncs over your home Wi-Fi.

No flashcards and no streak pressure: the words you save come back through the videos and articles you're shown.

## What you can do

- **Today**: a daily pick and rows of videos and articles chosen for your level, your goal for the day, and your progress.
- **Watch**: YouTube (or your own video and audio files) next to a synced transcript. Click any word: the video
  pauses and the dictionary opens. Replay a line, slow it down, or pause after each line.
- **Read**: articles from news and learner sites, your own books (EPUB), PDFs and pasted texts, with every word
  clickable and colour-coded by how likely you are to know it.
- **Look up any word**: its dictionary form (*rufe … an* → *anrufen*, 間に合わない → 間に合う), meanings, readings and a
  native voice reading it aloud. Save it with the sentence you met it in.
- **Suggestions that learn**: picks get easier or harder as you rate them, favour the channels and topics you finish,
  never repeat what you've watched, and new ones are found in the background.
- **Level Lab**: short tests (vocabulary, reading, listening, speaking) that give your level as a range.
- **Speak**: an AI tutor that talks at your level (optional, needs a free Gemini key), and shadowing practice.
- **Grammar**, **Manga** (Japanese, with clickable speech bubbles), **weekly reports**, and an **Android app**.

## Install it on your computer

Lingo OS is developed and tested on **Windows**. macOS and Linux should work but are less tested.

### 1. Install the tools (once)

You need [Git](https://git-scm.com/), [Node.js](https://nodejs.org/) 18 or newer, and
[uv](https://docs.astral.sh/uv/) (it installs the right Python for you). On Windows, in PowerShell:

```powershell
winget install Git.Git OpenJS.NodeJS.LTS astral-sh.uv
```

On macOS: `brew install git node uv`. On Linux: Git and Node.js from your package manager, then
`curl -LsSf https://astral.sh/uv/install.sh | sh`. Close and reopen the terminal afterwards.

Optional: [ffmpeg](https://ffmpeg.org/) (`winget install Gyan.FFmpeg`), only needed for your own video and audio files.

### 2. Download Lingo OS and set it up

```powershell
git clone https://github.com/proy9714/lingo-os.git
cd lingo-os
npm run setup
```

`setup` installs everything and creates your (empty) database in the `data` folder. It takes a few minutes the first
time.

### 3. Add dictionaries

Download the dictionary for each language you're learning and put the `.zip` files, unopened, in `data\dictionaries\`:

- **German / Spanish**: `wty-de-en.zip` / `wty-es-en.zip` from the
  [Wiktionary-to-Yomitan downloads page](https://yomidevs.github.io/wiktionary-to-yomitan/download/)
  (the "target language → English" dictionaries).
- **Japanese**: `jitendex-yomitan.zip` from [jitendex.org](https://jitendex.org/).

Then import them (takes a minute or two):

```powershell
npm run lingo -- dict import
```

### 4. Start it

```powershell
npm run start
```

Open **http://127.0.0.1:8787** in your browser. Keep the terminal open while you use the app; press Ctrl+C there to
stop it. Next time, `npm run start` is all you need.

### 5. First steps in the app

1. Pick your language with the **DE / ES / JA** buttons at the top, and set your daily goal in **Settings**.
2. Take the 5-minute vocabulary test in **Level**. It measures where you are, so suggestions fit you from day one
   (especially if you've been learning for a while). Entering the hours you studied before using the app is planned
   for a coming release.
3. Go to **Today** or **Watch**. Suggestions are found in the background in your first minutes; they appear as they're
   found.
4. Time you spend away from the app (a podcast, a class) can be added with **Log time** (or Ctrl+L).

Stuck? Run `npm run doctor`: it checks your setup and says what to fix. The **Help** page in the app explains every screen.

## The Android app

Install [Obtainium](https://github.com/ImranR98/Obtainium) on your phone, tap **Add app**, paste
`https://github.com/proy9714/lingo-os`, then **Install**. Obtainium tells you when there's an update. (Or download the
`.apk` from the [latest release](https://github.com/proy9714/lingo-os/releases/latest).)

The phone works through your computer: turn on Settings → **Phone** on the computer, then scan the pairing code with
the app. Both must be on the same Wi-Fi. Away from home, texts you saved for offline still work, and everything you
do syncs when you're back. Details in [docs/PHONE.md](docs/PHONE.md).

## Optional extras

- **AI explanations and the tutor**: create a free API key at [aistudio.google.com](https://aistudio.google.com/),
  copy `.env.example` to `.env`, put the key after `GEMINI_API_KEY=`, restart, and press **Test connection** in
  Settings. Other providers (a local Ollama, OpenRouter, any OpenAI-compatible server) are set in `config/llm.yaml`.
  Everything else works without AI.
- **Voices**: words and sentences are read by native neural voices, whatever voices your computer has. Choose a voice
  per language in Settings → **Voices**, or switch to your device's own voices to stay fully offline.
- **Your own videos and audio**: put them in `data\library\media\<language>\` with a same-named `.srt` or `.vtt`
  subtitle file, then **Watch → Add a video → Scan**.
- **Manga** (Japanese): drop volumes processed with mokuro into `data\inbox\manga\`.
- **Immersion Tracker users**: put its data folder in `config/app.local.yaml` (`immersion_tracker: { path: ... }`) and
  press **Sync now** in Settings to bring in your history.
- **AI terminals**: open Claude Code, Gemini CLI or Codex in this folder and type `/lingo` for status, recommendations,
  weekly reviews and more.
- **Scheduled runs** (Windows): `powershell -ExecutionPolicy Bypass -File scripts\schedule-windows.ps1` runs a daily
  content search and the Sunday review.

## Updating

```powershell
git pull
npm run setup
npm run start
```

Your data in `data\` is kept, and the database is upgraded automatically. The phone updates through Obtainium.

## Your data and privacy

Everything you do (words, history, levels, notes, recordings) stays in the `data` folder on your computer. Back that
folder up to keep it safe. The app goes online only to play and search YouTube, read the article sites in
`config/sources.yaml`, read a sentence aloud the first time (Microsoft's speech service; can be turned off), ask the AI
provider you set up when you ask for an explanation, and talk to your own phone over your Wi-Fi, encrypted.

## For developers

| Command | What it does |
|---|---|
| `npm run dev` | API on http://127.0.0.1:8787 and the app on **http://localhost:5173**, both reloading on changes |
| `npm test` | Backend tests plus the frontend typecheck |
| `npm run status` | Hours, today vs goal and starting level per language (`-- --json`) |
| `npm run doctor` | Check Python, data folder, databases, build, ffmpeg and API keys |
| `npm run import-tracker` | Import or re-sync Immersion Tracker CSVs |
| `npm run update-content` | Find new videos and articles near your level (`-- --lang es --dry-run`) |
| `npm run evolve-profile` | Weekly review and report (`-- --no-llm`, `-- --dry-run --json`) |
| `npm run lingo -- dict list` | Show installed dictionaries |
| `npm run lingo -- content fetch-history` | Fetch and analyse captions of the videos you've watched |
| `npm run lingo -- content rescore` | Refresh the starting estimate and re-score the library |
| `npm run lingo -- recommend` | Up Next picks with reasons (`--lang es`, `--json`) |
| `npm run lingo -- manga scan` | Import volumes from `data\inbox\manga\` |
| `npm run lingo -- ai status` / `ai test` | Which model each task uses; check the key |
| `npm run phone` | Build the app into the Android project and open it in Android Studio |
| `npm run lingo -- release check` | Maintainers: what changed since the last release (see [docs/RELEASING.md](docs/RELEASING.md)) |

Configuration lives in `config/`: `app.yaml` (data folder, languages, default goal), `app.local.yaml` (optional,
git-ignored, this computer's overrides), `baselines.yaml` (hours → level roadmap), `llm.yaml` (AI providers),
`sources.yaml` (content searches and feeds). API keys go in `.env` only.

```
backend/   FastAPI + SQLite (Python, uv)     frontend/  React + Vite + Tailwind, Capacitor for Android
config/    YAML settings                     docs/      architecture, schema, phone, releasing
modes/     /lingo playbooks for AI terminals data/      your personal data (git-ignored)
```

The design and data model are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/schema.sql](docs/schema.sql).
AI terminals follow [AGENTS.md](AGENTS.md) and read and change data only through the `lingo` command line.
On Windows, `npm run dev` starts the API through `backend/app/devserver.py`, which keeps uvicorn's auto-reload from
stopping Vite.

## License

Lingo OS is free software under the [GNU Affero General Public License v3.0](LICENSE) or later. You may use, study,
change and share it; if you distribute a changed version, or run one as a service others use over a network, you must
share its source under the same license.
