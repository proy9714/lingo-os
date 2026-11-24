import { Link, useLocation } from "@tanstack/react-router";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { BANDS } from "../components/cards";
import { cx } from "../components/ui";

/** One help topic. `keywords` widen what the search box finds. */
interface Topic {
  id: string;
  title: string;
  summary: string;
  keywords: string;
  body: ReactNode;
}

export function HelpPage() {
  const [query, setQuery] = useState("");
  const hash = useLocation({ select: (l) => l.hash });
  const q = query.trim().toLowerCase();
  const shown = useMemo(
    () => (q ? TOPICS.filter((t) => `${t.title} ${t.summary} ${t.keywords}`.toLowerCase().includes(q)) : TOPICS),
    [q],
  );

  // Links like /help#phone open at that topic.
  useEffect(() => {
    if (!hash) return;
    const timer = window.setTimeout(() => document.getElementById(hash)?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
    return () => window.clearTimeout(timer);
  }, [hash]);

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-4 px-1 pt-1">
        <div>
          <h1 className="text-[28px] font-bold tracking-tight md:text-[34px]">Help</h1>
          <p className="mt-1.5 max-w-3xl text-sm leading-relaxed text-ink-2">
            Lingo OS helps you learn German, Spanish and Japanese by watching and reading things you enjoy, at the right level.
            It picks what to watch and read next, makes every word clickable, tracks your time, and adapts as you improve.
            Everything stays on this computer.
          </p>
        </div>
        <label className="flex max-w-xl items-center gap-2 rounded-2xl border border-white/12 bg-black/25 px-4">
          <span aria-hidden="true" className="text-ink-3">
            ⌕
          </span>
          <span className="sr-only">Search help</span>
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search help: phone, suggestions, shortcuts, level…"
            className="min-h-12 w-full bg-transparent text-sm text-ink outline-none placeholder:text-ink-3"
          />
        </label>
      </header>

      <div className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[230px_minmax(0,1fr)]">
        <nav aria-label="Help topics" className="lg:sticky lg:top-4 lg:self-start">
          <ul className="flex gap-1.5 overflow-x-auto pb-1 lg:flex-col lg:overflow-visible lg:pb-0">
            {TOPICS.map((t) => (
              <li key={t.id} className="shrink-0">
                <a
                  href={`#${t.id}`}
                  className={cx(
                    "block rounded-xl px-3 py-2 text-sm transition hover:bg-white/8 hover:text-ink",
                    hash === t.id ? "bg-white/10 font-semibold text-ink" : "text-ink-2",
                    !shown.includes(t) && "opacity-40",
                  )}
                >
                  {t.title}
                </a>
              </li>
            ))}
          </ul>
        </nav>

        <div className="flex min-w-0 flex-col gap-4">
          {shown.length === 0 && (
            <p className="rounded-2xl border border-white/10 bg-white/[0.04] p-5 text-sm text-ink-2">
              Nothing in the help matches “{query}”. Try a shorter word, such as “phone”, “level” or “time”.
            </p>
          )}
          {shown.map((t) => (
            <section
              key={t.id}
              id={t.id}
              aria-labelledby={`h-${t.id}`}
              className="scroll-mt-4 rounded-[20px] border border-white/10 bg-white/[0.04] p-5 md:p-7"
            >
              <h2 id={`h-${t.id}`} className="text-xl font-bold tracking-tight md:text-2xl">
                {t.title}
              </h2>
              <p className="mt-1 text-sm text-ink-3">{t.summary}</p>
              <div className="help-body mt-4 flex flex-col gap-3 text-[15px] leading-relaxed text-ink-2">{t.body}</div>
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- building blocks

function Steps({ children }: { children: ReactNode[] }) {
  return (
    <ol className="flex flex-col gap-2.5">
      {children.map((step, n) => (
        <li key={n} className="flex gap-3">
          <span
            aria-hidden="true"
            className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full bg-accent/20 text-xs font-bold text-accent"
          >
            {n + 1}
          </span>
          <div className="min-w-0 flex-1">{step}</div>
        </li>
      ))}
    </ol>
  );
}

function Tip({ children, tone = "accent" }: { children: ReactNode; tone?: "accent" | "warn" }) {
  return (
    <div
      className={cx(
        "rounded-xl border px-4 py-3 text-sm",
        tone === "accent" ? "border-accent/25 bg-accent/[0.07] text-ink" : "border-orange-300/25 bg-orange-400/[0.08] text-ink",
      )}
    >
      {children}
    </div>
  );
}

function H3({ children }: { children: ReactNode }) {
  return <h3 className="mt-3 text-base font-semibold text-ink">{children}</h3>;
}

function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="rounded-md border border-white/20 bg-white/8 px-1.5 py-0.5 font-sans text-xs font-semibold text-ink">{children}</kbd>;
}

function Code({ children }: { children: ReactNode }) {
  return <code className="rounded bg-black/40 px-1.5 py-0.5 text-[13px] text-ink">{children}</code>;
}

function Go({ to, hash, children }: { to: "/" | "/watch" | "/read" | "/manga" | "/speak" | "/words" | "/grammar" | "/level" | "/settings" | "/reports" | "/connect"; hash?: string; children: ReactNode }) {
  return (
    <Link to={to} hash={hash} className="font-semibold text-accent hover:underline">
      {children}
    </Link>
  );
}

function Faq({ q, children }: { q: string; children: ReactNode }) {
  return (
    <details className="group rounded-xl border border-white/10 bg-black/20 px-4 py-3 open:bg-black/30">
      <summary className="cursor-pointer list-none font-semibold text-ink marker:hidden">
        <span className="mr-2 inline-block text-accent transition group-open:rotate-90">›</span>
        {q}
      </summary>
      <div className="mt-2 flex flex-col gap-2 pl-5 text-sm">{children}</div>
    </details>
  );
}

function Bullets({ children }: { children: ReactNode[] }) {
  return (
    <ul className="flex list-disc flex-col gap-1.5 pl-5 marker:text-ink-3">
      {children.map((c, n) => (
        <li key={n}>{c}</li>
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------- topics

const TOPICS: Topic[] = [
  {
    id: "start",
    title: "Getting started",
    summary: "Five minutes to a useful setup.",
    keywords: "begin first setup import tracker csv quick start",
    body: (
      <>
        <Steps>
          {[
            <>
              <strong className="text-ink">Pick a language</strong> with the DE / ES / JA buttons at the top. Everything (suggestions,
              words, time, level) is kept separately per language, and the colours change with it.
            </>,
            <>
              <strong className="text-ink">Bring in your history</strong> (optional): <Go to="/settings">Settings</Go> → Immersion
              Tracker → Import. Your past hours count toward your level, and videos you've already watched are never suggested.
            </>,
            <>
              <strong className="text-ink">Measure your level</strong> (optional, about 5 minutes): <Go to="/level">Level</Go> → vocabulary
              test. Without it, your level is estimated from your hours, which is rougher.
            </>,
            <>
              <strong className="text-ink">Open Today</strong> and press the big card: that's the best thing to watch or read next. New
              suggestions keep arriving in the background.
            </>,
            <>
              <strong className="text-ink">Click any word you don't know</strong> while watching or reading. Mark it as{" "}
              <em>Learning</em> or <em>Known</em>; that's how the app learns what you know.
            </>,
          ]}
        </Steps>
        <Tip>
          The app runs on this computer. Start it with <Code>npm run dev</Code> (or <Code>npm run start</Code>) in the project folder
          and keep that window open while you use it.
        </Tip>
      </>
    ),
  },
  {
    id: "today",
    title: "The Today page",
    summary: "Your home page: what to do next, and how you're doing.",
    keywords: "home dashboard up next featured goal streak hours progress",
    body: (
      <>
        <Bullets>
          {[
            <>
              <strong className="text-ink">The big card</strong> is the single best pick for you right now: a video or something to
              read. <em>Watch now</em> / <em>Read now</em> opens it; <em>Not interested</em> hides it for good.
            </>,
            <>
              <strong className="text-ink">Also up next</strong> lists four more picks, mixing videos and reading, and never more than
              two from one channel.
            </>,
            <>
              <strong className="text-ink">Videos for you</strong> and <strong className="text-ink">Articles &amp; books for you</strong>{" "}
              are rows you can scroll sideways. <em>See all</em> opens the full, endless list on Watch or Read.
            </>,
            <>
              <strong className="text-ink">The pills at the top</strong> show today's minutes against your daily goal, your total
              hours, and your level.
            </>,
            <>
              <strong className="text-ink">Your progress</strong> (further down): the last 7 days, your level, the weekly report, recent
              sessions, all languages and monthly hours.
            </>,
          ]}
        </Bullets>
      </>
    ),
  },
  {
    id: "suggestions",
    title: "How suggestions work",
    summary: "Why you see what you see, and where new content comes from.",
    keywords: "recommend recommendation i+1 level band known percent coverage background search find new content sources feeds youtube watched dismiss not interested taste learn preferences rating difficulty very easy hard estimated catalogue channels",
    body: (
      <>
        <p>
          Every video and text is analysed word by word against what you know. The <strong className="text-ink">% known</strong> on a
          card is how much of it you should understand. The best picks are mostly known, with a handful of new words to learn from
          (often called <em>i+1</em>). Each card has a label:
        </p>
        <ul className="grid gap-2 sm:grid-cols-2">
          {Object.entries(BANDS).map(([key, band]) => (
            <li key={key} className="flex items-start gap-2.5 rounded-xl bg-black/20 px-3 py-2.5 text-sm">
              <span className={cx("mt-0.5 shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold", band.tone)}>{band.label}</span>
              <span>{band.hint}</span>
            </li>
          ))}
        </ul>
        <H3>What is never suggested</H3>
        <Bullets>
          {[
            "Videos you've watched: tracked in the app, or listed in your Immersion Tracker history (matched by link or title, so re-uploads are caught too).",
            "Anything you've finished, and anything you marked Not interested (the × on a card).",
          ]}
        </Bullets>
        <H3>What comes first</H3>
        <p>
          Picks that fit your level best come first. Things that bring back words you're learning get a boost, and so do books you've
          started. One channel never fills the screen: others are mixed in.
        </p>
        <H3>Your taste: learned from what you do</H3>
        <p>
          Like a video site's feed, suggestions learn what you enjoy, with no likes needed. Videos you finish or come back to, and
          articles you read most of, count for their channel or site, their topic and their length. Things you leave after a few
          seconds, or mark <em>Not interested</em>, count against. Recent behaviour counts most. Channels you've never tried still
          turn up now and then, so the list doesn't narrow to the same few. The card <em>What your suggestions learned</em> on Today
          shows what it has picked up, and the reasons on each card say why it was suggested ("you often watch …", "similar to
          things you enjoyed").
        </p>
        <H3>Rate how hard things are</H3>
        <p>
          Under every video and at the end of every page you read: <strong>Very easy · Easy · Comfortable · Hard · Very hard</strong>.
          Each rating moves your "just right" level right away, separately for videos and for reading, and every suggestion is
          re-ranked. Rating a few videos you've already watched (Watch → Watched) is the quickest way to tune it. Click a rating
          again to remove it.
        </p>
        <H3>Already watched it?</H3>
        <p>
          Hover a suggestion (or tap it on a phone) and press <strong>✓</strong>, or <strong>Already watched</strong> on Today's
          top pick: it leaves your suggestions and moves to Watch → Watched. On a video's own page, <strong>Mark as
          completed</strong> does the same. Both have an <strong>Undo</strong>, and <strong>Not watched yet</strong> on the
          Watched tab brings a video back.
        </p>
        <H3>A big catalogue, found in the background</H3>
        <p>
          The app lists whole YouTube channels: those from the Comprehensible Input Wiki, the ones you watch, and new ones whose
          videos turn out to be at your level. A little more of each channel's back catalogue is listed on each search, so there
          are hundreds of videos to choose from. Until a video has been measured word by word, its level is{" "}
          <strong>estimated</strong> from the channel's other videos and marked <strong>≈ … estimated</strong>. The best ones are
          measured in the background, and any video is measured the moment you open it. Videos about another language
          (a channel that teaches German and Japanese, say) are left out.
        </p>
        <p>
          Searches start on their own as soon as you open the app (when a list is low), when a list runs low, or when you scroll
          to its end, and run while you keep using the app. New finds join Today, Watch and Read as each channel or site is
          read, without waiting for the whole search to finish. A badge{" "}
          <span className="rounded-lg bg-accent/14 px-2 py-0.5 text-xs font-semibold text-accent">Finding new content</span> shows in
          the top bar while one runs. Articles come from news and learner sites (RSS feeds); sites whose articles suit you get
          most of the reading, including their older articles, and sites that keep turning out too hard are read less. YouTube is
          asked for videos at most every 45 minutes, and left alone for 12 hours if it asks to slow down.
        </p>
        <Tip>
          Want more right now? Scroll to the end of the list on Watch or Read and press <strong>Find more now</strong>. To turn the
          automatic search off, or to choose channels: <Go to="/settings">Settings</Go> → New content. Article sites are listed in{" "}
          <Code>config/sources.yaml</Code>.
        </Tip>
      </>
    ),
  },
  {
    id: "watch",
    title: "Watch & listen",
    summary: "Videos with a clickable transcript.",
    keywords: "video youtube player transcript subtitles captions add video local files media history watched shadow",
    body: (
      <>
        <p>
          <Go to="/watch">Watch</Go> opens on <strong className="text-ink">For you</strong>: videos at your level, best first. Scroll
          down and more load on their own. <strong className="text-ink">Watched</strong> lists everything you've seen (including
          your tracker history) and is never mixed into suggestions.
        </p>
        <H3>In the player</H3>
        <Bullets>
          {[
            "The transcript scrolls with the video. Click a word: the video pauses and the word's meaning opens on the right.",
            "Click a line's time to play from there. Pause after each line (a button under the video) gives you time to read along.",
            <>
              <strong className="text-ink">Shadow this line</strong> sends the current line to Speak → Shadowing, so you can repeat it
              aloud.
            </>,
            "Watching time counts only while the video actually plays.",
          ]}
        </Bullets>
        <H3>Adding videos</H3>
        <p>
          <strong className="text-ink">+ Add a video</strong> takes a YouTube link. For your own files, put them in{" "}
          <Code>data\library\media\&lt;language&gt;\</Code> with a same-named <Code>.srt</Code> or <Code>.vtt</Code> subtitle file,
          then press <em>Scan the media folder</em>.
        </p>
      </>
    ),
  },
  {
    id: "read",
    title: "Read",
    summary: "Articles from the web, books, PDFs and your own texts.",
    keywords: "reading articles books epub pdf text paste web shelf reader pages",
    body: (
      <>
        <p>
          <Go to="/read">Read</Go> opens on <strong className="text-ink">For you</strong>: web articles found for your level, plus
          books on your shelf, best first, with an endless scroll. <strong className="text-ink">Your shelf</strong> holds what you've
          added or opened.
        </p>
        <Bullets>
          {[
            <>
              <strong className="text-ink">+ Add something to read</strong>: an <Code>.epub</Code>, <Code>.pdf</Code> or{" "}
              <Code>.txt</Code> file (up to 80 MB), a link to a web article (its text is kept on this computer), or a pasted text.
            </>,
            "The reader shows one page at a time. Every word is clickable, and your place is remembered.",
            "Reading time counts while the page is open and you're active on it (it stops after a while without scrolling or clicking).",
            "Scanned PDFs without a text layer, and books with DRM, can't be opened.",
          ]}
        </Bullets>
      </>
    ),
  },
  {
    id: "words",
    title: "Looking up words",
    summary: "Click a word, see what it means, and tell the app how well you know it.",
    keywords: "lookup dictionary meaning word status learning known ignore new colours colors highlight flashcards words page",
    body: (
      <>
        <p>Click any word in a transcript, text or manga bubble. The panel on the right shows its dictionary entry and lets you set a status:</p>
        <ul className="grid gap-2 sm:grid-cols-2">
          {[
            ["New", "bg-amber-300/20 text-amber-100 shadow-[inset_0_-2px_0_#f5b443]", "Highlighted in amber: you haven't marked it yet."],
            ["Learning", "bg-sky-400/25 text-sky-100", "Highlighted in blue: it will come back in suggestions and in tutor chats."],
            ["Familiar", "shadow-[inset_0_-1px_0_rgb(255_255_255/0.5)]", "Thinly underlined: you've met it often and probably know it."],
            ["Known", "", "Plain text. Ignore works the same for names and words you don't care about."],
          ].map(([name, style, text]) => (
            <li key={name} className="flex items-start gap-2.5 rounded-xl bg-black/20 px-3 py-2.5 text-sm">
              <span className={cx("shrink-0 rounded px-1 font-semibold text-ink", style)}>{name}</span>
              <span>{text}</span>
            </li>
          ))}
        </ul>
        <p>
          There are no flashcards. Words you're learning come back naturally: suggestions favour content that contains them, and the
          tutor uses them in conversation. <Go to="/words">Words</Go> lists every word you've met, with its status.
        </p>
        <p>
          With an AI key (see <a href="#ai" className="font-semibold text-accent hover:underline">AI explanations</a>), the panel also
          explains what the word means <em>in that sentence</em>, and can translate or break down the whole sentence.
        </p>
      </>
    ),
  },
  {
    id: "grammar",
    title: "Grammar",
    summary: "A reference for each language, with sentences you can hear and look up.",
    keywords: "grammar reference cases verbs conjugation tables tutor weak spots",
    body: (
      <>
        <p>
          <Go to="/grammar">Grammar</Go> has a reference for German, Spanish and Japanese, from beginner to intermediate: numbered
          sections with tables, a short explanation and real example sentences with translations. Colours show the kind of topic:{" "}
          <span className="font-semibold text-sky-300">structure</span>, <span className="font-semibold text-amber-300">verb forms</span>{" "}
          and <span className="font-semibold text-rose-300">watch-out contrasts</span>, and each ends with a one-page summary.
        </p>
        <Bullets>
          {[
            "It opens on the language you're learning; the tabs show the others.",
            "Search (dative, ser, て form …) or filter by kind.",
            "The speaker button reads an example aloud; Aa makes its words clickable for lookups.",
            "Japanese examples show the reading in kana underneath.",
            "If the tutor noticed slips (for example 'dative after mit'), they're listed at the top with links to the sections that explain them.",
          ]}
        </Bullets>
      </>
    ),
  },
  {
    id: "manga",
    title: "Manga",
    summary: "Read manga with clickable speech bubbles.",
    keywords: "manga mokuro comics japanese ocr bubbles volume",
    body: (
      <>
        <Steps>
          {[
            <>
              Put a volume processed with <strong className="text-ink">mokuro</strong> (images plus its <Code>.mokuro</Code> file) in{" "}
              <Code>data\inbox\manga\</Code>.
            </>,
            <>
              Open <Go to="/manga">Manga</Go> and press <em>Scan</em>. The volume appears with the words you're likely to meet.
            </>,
            "In the viewer, hover a speech bubble to see its text; click a word to look it up. ← and → turn pages (right to left for Japanese).",
            "If the text recognition misread a bubble, fix it in place; your fix is kept.",
          ]}
        </Steps>
        <p className="text-sm text-ink-3">The app only links to Mokuro Bunko; it never downloads from it.</p>
      </>
    ),
  },
  {
    id: "speak",
    title: "Speak: tutor and shadowing",
    summary: "Practise speaking at your level.",
    keywords: "tutor conversation chat roleplay role-play grammar shadowing speaking microphone pronunciation topic",
    body: (
      <>
        <H3>Tutor</H3>
        <Bullets>
          {[
            "Just chat: a relaxed conversation that stays at your level and reuses words you're learning. Replies with too many unknown words are simplified automatically.",
            "Role-play: everyday scenes (ordering food, at the doctor's, and more).",
            "Talk about something you watched or read: choose from your last 10 videos and texts, most recent first.",
            "Grammar practice: works on the mistakes the tutor noticed in earlier conversations.",
            "Speak with the microphone button or type. After a conversation ends, a short review records what went well and what to work on.",
          ]}
        </Bullets>
        <H3>Shadowing</H3>
        <p>
          Pick a line (or use <em>Shadow this line</em> in the video player), listen, then record yourself saying it. The app compares
          what it heard with the line and shows the differences. Speaking time counts toward your day.
        </p>
        <p className="text-sm text-ink-3">The tutor needs an AI key; shadowing works without one.</p>
      </>
    ),
  },
  {
    id: "level",
    title: "Your level",
    summary: "Always shown as a range, because no test is exact.",
    keywords: "level lab vocabulary test reading listening speaking estimate range cefr jlpt hours",
    body: (
      <>
        <p>
          Before you take a test, your level is estimated from your hours, which is a rough guide. <Go to="/level">Level</Go> (the Level
          Lab) has short tests you take yourself:
        </p>
        <Bullets>
          {[
            "Vocabulary (about 5 minutes): do you know these words? Some answers are checked with a meaning question.",
            "Reading: fill in the missing parts of words in short texts.",
            "Listening: type what you hear.",
            "Speaking: repeat sentences after hearing them.",
          ]}
        </Bullets>
        <p>
          Results are ranges, for example “90% likely 3,800–4,900 words”. They set how hard your suggestions are. The weekly review then
          nudges this a little at a time, based on what you actually did.
        </p>
      </>
    ),
  },
  {
    id: "time",
    title: "Time tracking",
    summary: "Your hours are counted automatically, and you can add offline time.",
    keywords: "time tracking hours minutes goal log offline manual immersion tracker import ctrl+l",
    body: (
      <>
        <Bullets>
          {[
            "Watching, reading, manga, the tutor and shadowing are counted automatically, only while you're actually doing them.",
            <>
              Did something away from the app (a podcast, a book, a conversation)? Press <strong className="text-ink">Log time</strong> in
              the top bar, or <Kbd>Ctrl</Kbd> + <Kbd>L</Kbd>.
            </>,
            <>
              Daily goals per language: <Go to="/settings">Settings</Go> → Daily goals.
            </>,
            <>
              Immersion Tracker CSVs: <Go to="/settings">Settings</Go> → Immersion Tracker → Import. It's safe to run again whenever the
              tracker has new entries; nothing is counted twice.
            </>,
          ]}
        </Bullets>
      </>
    ),
  },
  {
    id: "weekly",
    title: "Weekly review",
    summary: "Once a week the app looks back and adjusts.",
    keywords: "weekly review report evolve calibration adjust difficulty",
    body: (
      <>
        <p>
          The review measures your week (time, what you finished, words you learned) and adjusts your suggestions a little: harder if
          things were too easy, easier if you kept stopping. It moves at most 2 points a week, so nothing changes suddenly. It also
          updates the tutor's brief for the next week and writes a report.
        </p>
        <p>
          Run it from <Go to="/reports">Reports</Go>, or let it run every Sunday (see <Code>scripts\schedule-windows.ps1</Code>).
        </p>
      </>
    ),
  },
  {
    id: "ai",
    title: "AI explanations",
    summary: "Optional: meanings in context, sentence help and the tutor.",
    keywords: "ai gemini api key llm explanation translation grammar tutor ollama openrouter",
    body: (
      <>
        <Steps>
          {[
            <>
              Create a free API key at <strong className="text-ink">aistudio.google.com</strong>.
            </>,
            <>
              In the project folder, copy <Code>.env.example</Code> to <Code>.env</Code> and paste the key after{" "}
              <Code>GEMINI_API_KEY=</Code>.
            </>,
            "Restart the app.",
            <>
              <Go to="/settings">Settings</Go> → AI → <em>Test connection</em>.
            </>,
          ]}
        </Steps>
        <p>
          Other providers work too (Ollama on this computer, OpenRouter and any OpenAI-compatible service): see{" "}
          <Code>config/llm.yaml</Code>. Without a key, lookups use the dictionaries only. Only what a request needs is sent (the sentence
          you ask about, or the tutor conversation), never your history or your files.
        </p>
      </>
    ),
  },
  {
    id: "voices",
    title: "Voices: native pronunciation",
    summary: "Every word and sentence read by a native voice of the language.",
    keywords: "voice voices speech speak pronunciation audio tts text to speech accent read aloud listen",
    body: (
      <>
        <p>
          The speaker buttons (lookup panel, sentences, tutor replies, shadowing, grammar examples, the Level Lab listening check) use a
          neural voice of the language itself, so German sounds German even when your computer only has English voices. The laptop makes
          each clip with Microsoft's speech service (no account) and keeps it, so a sentence is sent once and replays offline.
        </p>
        <p>
          <Go to="/settings">Settings</Go> → Voices: choose a voice per language (female or male, and other regions such as Mexican
          Spanish), and press <em>Test</em>. Or choose <em>This device's voices only</em> to stay fully offline: a language your device
          has no voice for then stays silent, with a message, instead of being read with an English accent.
        </p>
        <p>On the phone the same voices come from the laptop; away from it, Android's own voices are used.</p>
      </>
    ),
  },
  {
    id: "phone",
    title: "Phone sync (Android)",
    summary: "Use Lingo OS on your phone over your home Wi-Fi, and offline away from home.",
    keywords: "phone mobile android app sync wifi wi-fi pair pairing qr code offline save apk android studio usb firewall connect",
    body: (
      <>
        <p>
          The phone runs the same app. At home it works through the laptop over your Wi-Fi. Away from home it keeps working with texts
          you saved for offline. What you do there (lookups, word statuses, reading time, progress) syncs when the phone is back in
          reach.
        </p>
        <Tip>
          <strong>What you need:</strong> an Android phone and the laptop running Lingo OS, both on the <strong>same Wi-Fi</strong>.
        </Tip>

        <H3>Step 1 · Turn on syncing on the laptop</H3>
        <Steps>
          {[
            <>
              Open <Go to="/settings">Settings</Go> → <strong className="text-ink">Phone</strong> and tick{" "}
              <em>Let a phone sync over this Wi-Fi</em>.
            </>,
            <>
              Windows may ask whether Python may use the network. Allow it on <strong className="text-ink">private networks only</strong>{" "}
              (your home), not public ones.
            </>,
            <>
              The Phone panel now shows <em>listening on Wi-Fi</em> and the laptop's address. Only port 8788 is opened, it only answers
              paired phones, and everything sent is encrypted. The rest of the app stays private to the laptop.
            </>,
          ]}
        </Steps>

        <H3>Step 2 · Install the app</H3>
        <Steps>
          {[
            <>
              Install <strong className="text-ink">Obtainium</strong> on the phone (from github.com/ImranR98/Obtainium or F-Droid). It
              installs apps from GitHub and keeps them up to date.
            </>,
            <>
              In Obtainium: <em>Add app</em> → paste <Code>https://github.com/proy9714/lingo-os</Code> → <em>Add</em> →{" "}
              <em>Install</em>. Allow installs from Obtainium when Android asks.
            </>,
            <>New versions then appear in Obtainium: tap <em>Update</em>. Your pairing and offline texts are kept.</>,
          ]}
        </Steps>
        <p className="text-sm text-ink-3">
          Without Obtainium: open github.com/proy9714/lingo-os/releases/latest on the phone, download the <Code>.apk</Code> and open it.
          Developers can also build it themselves with <Code>npm run phone</Code> (needs Android Studio; see docs/PHONE.md).
        </p>

        <H3>Step 3 · Pair the phone</H3>
        <Steps>
          {[
            <>
              On the laptop: Settings → Phone → <strong className="text-ink">Pair a phone</strong>. A QR code appears. It works once and
              expires after 10 minutes.
            </>,
            <>
              On the phone: open Lingo OS. It starts on <strong className="text-ink">Connect to your laptop</strong>. Name the phone, tap{" "}
              <em>Scan the code</em> and point the camera at the QR code. If scanning isn't available, copy the code's text and paste
              it instead.
            </>,
            <>The phone connects and shows the full app. The laptop's Phone panel lists it with “last seen”.</>,
          ]}
        </Steps>

        <H3>Step 4 · Everyday use</H3>
        <Bullets>
          {[
            <>
              <strong className="text-ink">At home</strong> the whole app works on the phone, through the laptop: suggestions, videos,
              reading, lookups, your level.
            </>,
            <>
              <strong className="text-ink">Before you leave</strong>, save texts for offline: tap the sync badge in the top bar (or open{" "}
              <Code>/connect</Code>) and press <em>Save offline</em> next to books, articles or texts. A saved text brings its words,
              your word statuses and the dictionary entries it needs.
            </>,
            <>
              <strong className="text-ink">Away from home</strong> the Read shelf shows what you saved. Reading, lookups, word statuses,
              the timer and logging time all work. Changes wait on the phone.
            </>,
            <>
              <strong className="text-ink">Back home</strong> they sync on their own: when the app opens or the phone is back on the
              Wi-Fi, and every 2 minutes. Or press <em>Sync now</em>.
              Each change is applied exactly once; if a word was changed on both devices, the later change wins.
            </>,
          ]}
        </Bullets>

        <H3>Not on the phone yet</H3>
        <Bullets>
          {[
            "Videos can't be saved for offline (they stream from YouTube or the laptop). Manga reads at home only.",
            "Android's in-app browser has no speech recognition: for the tutor and speaking checks, type instead (recording yourself in shadowing works).",
            "AI explanations work at home only (the laptop asks the AI service).",
            "Over mobile data the phone can't reach the laptop; it syncs when you're back on the home Wi-Fi.",
          ]}
        </Bullets>

        <H3>Troubleshooting</H3>
        <div className="flex flex-col gap-2">
          <Faq q="The phone says it can't reach the laptop">
            <Bullets>
              {[
                "Are both on the same Wi-Fi? Guest networks often keep devices apart.",
                "Is Lingo OS running on the laptop, with “Let a phone sync over this Wi-Fi” ticked? The Phone panel should say “listening on Wi-Fi”.",
                "Did Windows block it? Windows Security → Firewall & network protection → Allow an app through firewall → make sure Python is allowed on Private networks, and that your home Wi-Fi is set to Private.",
                "Is the laptop asleep? Sync needs it awake.",
              ]}
            </Bullets>
          </Faq>
          <Faq q="It worked before, but stopped after a router restart">
            <p>
              The laptop's address on the Wi-Fi may have changed. On the phone, open the sync screen → <em>Disconnect</em>, then pair
              again (Step 3). To avoid it, reserve a fixed address for the laptop in your router's settings (often called “DHCP
              reservation”).
            </p>
          </Faq>
          <Faq q="The QR code doesn't scan">
            <p>
              Codes expire after 10 minutes and work once: press <em>Pair a phone</em> again for a fresh one. Allow camera access when
              Android asks. You can also paste the code's text instead of scanning.
            </p>
          </Faq>
          <Faq q="Android Studio can't see my phone">
            <p>
              Check USB debugging is on, use a data cable (not a charge-only one), unlock the phone and accept the “Allow USB
              debugging?” prompt. Or install the released app with Obtainium instead (see Step 2).
            </p>
          </Faq>
          <Faq q="I lost my phone, or want to stop syncing">
            <p>
              On the laptop: Settings → Phone → <strong>Remove</strong> next to it. It can't connect again until it's paired again. To
              stop all phone syncing, untick “Let a phone sync over this Wi-Fi”; the network port closes.
            </p>
          </Faq>
        </div>
      </>
    ),
  },
  {
    id: "privacy",
    title: "Privacy: what stays here, what goes online",
    summary: "Your data never leaves this computer, except as listed here.",
    keywords: "privacy data local online network internet offline security",
    body: (
      <>
        <p>
          Your words, history, levels, notes and recordings stay in the <Code>data</Code> folder on this computer. The app goes online
          only to:
        </p>
        <Bullets>
          {[
            "Play YouTube videos and fetch their captions, and search YouTube when looking for new videos.",
            "Read the news and learner sites listed in config/sources.yaml, and the Comprehensible Input Wiki page for your language (at most once a week).",
            "Ask the AI service you set up, only when you request an explanation or use the tutor.",
            "Send a sentence to Microsoft's speech service the first time it's read aloud (Settings → Voices can switch this off).",
            "Talk to your own paired phone over your home Wi-Fi, encrypted, if you turned phone sync on.",
          ]}
        </Bullets>
      </>
    ),
  },
  {
    id: "shortcuts",
    title: "Keyboard shortcuts",
    summary: "Faster with a keyboard.",
    keywords: "keyboard shortcuts keys hotkeys space arrow escape",
    body: (
      <div className="overflow-x-auto">
        <table className="w-full min-w-[420px] text-left text-sm">
          <tbody className="divide-y divide-white/8">
            {(
              [
                ["Anywhere", <><Kbd>Ctrl</Kbd> + <Kbd>L</Kbd></>, "Log offline time"],
                ["Anywhere", <Kbd key="esc">Esc</Kbd>, "Close the word panel or a dialog"],
                ["Video player", <Kbd key="sp">Space</Kbd>, "Play / pause"],
                ["Video player", <><Kbd>←</Kbd> <Kbd>→</Kbd></>, "Previous / next line"],
                ["Video player", <Kbd key="r">R</Kbd>, "Repeat the current line"],
                ["Reader, manga", <><Kbd>←</Kbd> <Kbd>→</Kbd></>, "Previous / next page"],
                ["Vocabulary test", <><Kbd>Y</Kbd> / <Kbd>N</Kbd></>, "I know it / I don't"],
                ["Tutor", <Kbd key="en">Enter</Kbd>, "Send (Shift + Enter for a new line)"],
              ] as [string, ReactNode, string][]
            ).map(([where, keys, what], n) => (
              <tr key={n}>
                <td className="py-2.5 pr-4 text-ink-3">{where}</td>
                <td className="py-2.5 pr-4 whitespace-nowrap">{keys}</td>
                <td className="py-2.5 text-ink">{what}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    ),
  },
  {
    id: "faq",
    title: "Questions and problems",
    summary: "Quick answers to common issues.",
    keywords: "faq troubleshooting problem error not working empty missing slow",
    body: (
      <div className="flex flex-col gap-2">
        <Faq q="I see no suggestions">
          <p>
            Suggestions skip everything you've watched. If none are left, a background search starts on its own (watch for{" "}
            <em>Finding new content</em> in the top bar). It takes a minute or two. You can also press <em>Find more now</em> at the
            end of the list on Watch or Read.
          </p>
        </Faq>
        <Faq q="Suggestions are too easy or too hard">
          <p>
            Take the vocabulary test in <Go to="/level">Level</Go>: it is much more precise than the estimate from hours. Marking
            words as Known or Learning while you watch also helps, and the weekly review adjusts difficulty a little each week.
          </p>
        </Faq>
        <Faq q="A video has no transcript">
          <p>
            Some videos have no captions in the language. Suggested videos always have them; for videos you add yourself, the player
            offers to fetch captions if they exist.
          </p>
        </Faq>
        <Faq q="“Can't reach the Lingo OS server”">
          <p>
            The app's server isn't running. In the project folder run <Code>npm run dev</Code>, then reload the page.
          </p>
        </Faq>
        <Faq q="Searching stopped early / YouTube asked to sign in">
          <p>
            YouTube sometimes asks automated requests to slow down. The app stops right away and waits 12 hours before searching
            YouTube again on its own. Articles keep coming meanwhile.
          </p>
        </Faq>
      </div>
    ),
  },
  {
    id: "terminal",
    title: "For AI terminals",
    summary: "Operate Lingo OS from Claude Code, Gemini CLI or Codex.",
    keywords: "terminal cli lingo command claude gemini codex agent",
    body: (
      <>
        <p>
          In an AI terminal opened in the project folder, type <Code>/lingo</Code> followed by a mode, for example{" "}
          <Code>/lingo status de</Code>, <Code>/lingo recommend</Code>, <Code>/lingo update-content</Code>,{" "}
          <Code>/lingo plan-week</Code> or <Code>/lingo doctor</Code> to check the setup. The modes are described in{" "}
          <Code>AGENTS.md</Code>.
        </p>
      </>
    ),
  },
];
