import { Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState } from "react";

import { api } from "../api/client";
import { useActiveLanguage, useContentMutation, useLibrary, usePool } from "../api/hooks";
import type { ContentItem } from "../api/types";
import { SuggestionGrid } from "../components/Suggestions";
import { Button, Chip, Panel, PanelTitle, Skeleton, Tabs, cx } from "../components/ui";
import { formatDay, localDayOf } from "../lib/format";
import { useInfiniteSentinel } from "../lib/useInfiniteSentinel";

type AddMode = "file" | "article" | "text";

const SAMPLES: Record<string, string> = {
  de: "Am Wochenende rufe ich meine Großeltern an. Sie wohnen auf dem Land und freuen sich immer, wenn sich jemand meldet. Meistens erzählen sie mir, was im Garten gerade wächst und welche Nachbarn umgezogen sind.",
  es: "Cuando por fin llegó el sábado, Lucía decidió aprovechar el buen tiempo. Guardó en la mochila un par de bocadillos y el libro que llevaba semanas sin terminar. El tren salía a las ocho, pero ella apareció en el andén con apenas dos minutos de margen.",
  ja: "週末はいつも近くの公園を散歩します。天気がいい日は、ベンチに座って本を読んだり、子どもたちが遊んでいるのを眺めたりします。帰り道にパン屋さんに寄って、焼きたてのパンを買うのが楽しみです。",
};

const TYPE_LABELS: Record<string, string> = { epub: "Book", pdf: "PDF", article: "Article", text: "Text" };

type ReadTab = "for-you" | "shelf";

export function ReadPage() {
  const { code, language } = useActiveLanguage();
  const [tab, setTab] = useState<ReadTab>("for-you");
  const [adding, setAdding] = useState(false);
  const pool = usePool(code).data;
  const shelfCount = useLibrary(code, "read", "mine", "").data?.pages[0]?.total;

  return (
    <div className="flex flex-col gap-5">
      <header className="flex flex-wrap items-end justify-between gap-3 px-1 pt-1">
        <div>
          <h1 className="text-[28px] font-bold tracking-tight">Read</h1>
          <p className="mt-1.5 max-w-2xl text-sm text-ink-2">
            {language?.name} articles from the web and books from your shelf, picked for your reading level. Every word is
            clickable; reading time counts while the page is open and you're active on it.
          </p>
        </div>
        <Button variant={adding ? "secondary" : "primary"} aria-expanded={adding} onClick={() => setAdding((v) => !v)}>
          {adding ? "Close" : "+ Add something to read"}
        </Button>
      </header>

      {adding && <AddPanel lang={code} />}

      <Tabs<ReadTab>
        label="Reading"
        value={tab}
        onChange={setTab}
        items={[
          { value: "for-you", label: "For you", count: pool?.pools.read ?? null },
          { value: "shelf", label: "Your shelf", count: shelfCount ?? null },
        ]}
      />

      {tab === "for-you" ? <SuggestionGrid key={code} lang={code} shelf="read" /> : <ShelfTab lang={code} />}
    </div>
  );
}

function ShelfTab({ lang }: { lang: string }) {
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(query.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [query]);
  const list = useLibrary(lang, "read", "mine", debounced);
  const items = useMemo(() => list.data?.pages.flatMap((p) => p.items) ?? [], [list.data]);
  const sentinel = useInfiniteSentinel(
    () => {
      if (list.hasNextPage && !list.isFetchingNextPage) void list.fetchNextPage();
    },
    Boolean(list.hasNextPage),
    items.length,
  );

  return (
    <section aria-label="Your shelf" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2 px-1">
        <p className="text-sm text-ink-3">What you've added or opened, most recent first.</p>
        <label className="flex min-w-[240px] items-center rounded-xl border border-white/10 bg-black/25 px-3">
          <span className="sr-only">Search the shelf</span>
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search titles, authors…"
            className="min-h-10 w-full bg-transparent text-sm text-ink outline-none placeholder:text-ink-3"
          />
        </label>
      </div>
      {list.isPending ? (
        <Skeleton className="h-48 rounded-[20px]" />
      ) : list.isError ? (
        <Panel role="alert">Could not load your shelf: {list.error.message}</Panel>
      ) : items.length === 0 ? (
        <Panel>
          <p className="text-sm text-ink-2">
            {debounced
              ? "Nothing on your shelf matches that."
              : "Nothing here yet. Open an article from For you, or add a book, a PDF, an article link or a pasted text."}
          </p>
        </Panel>
      ) : (
        <ul className="grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(min(100%,260px),1fr))]">
          {items.map((item) => (
            <ShelfCard key={item.id} item={item} />
          ))}
        </ul>
      )}
      <div ref={sentinel} aria-hidden="true" />
      {list.isFetchingNextPage && <Skeleton className="h-32 rounded-[20px]" />}
    </section>
  );
}

function AddPanel({ lang }: { lang: string }) {
  const navigate = useNavigate();
  const [mode, setMode] = useState<AddMode>("file");
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const open = (item: ContentItem) => void navigate({ to: "/read/$itemId", params: { itemId: String(item.id) } });
  const upload = useContentMutation((file: File) => api.uploadDocument(lang, file));
  const article = useContentMutation((link: string) => api.addArticle(lang, link));
  const pasted = useContentMutation((v: { title: string; text: string }) => api.addText(lang, v.title, v.text));
  const busy = upload.isPending || article.isPending || pasted.isPending;
  const error = upload.error ?? article.error ?? pasted.error;

  const sendFile = (file: File | undefined) => {
    if (file) upload.mutate(file, { onSuccess: open });
  };

  const tabs: [AddMode, string][] = [
    ["file", "Book or PDF"],
    ["article", "Web article"],
    ["text", "Paste text"],
  ];

  return (
    <Panel aria-labelledby="t-add">
      <PanelTitle id="t-add">Add something to read</PanelTitle>
      <div role="tablist" aria-label="What to add" className="mb-4 flex flex-wrap gap-1.5">
        {tabs.map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={mode === key}
            onClick={() => setMode(key)}
            className={cx(
              "min-h-10 rounded-xl px-3.5 text-sm font-semibold transition",
              mode === key ? "bg-accent/20 text-accent" : "text-ink-2 hover:bg-white/8 hover:text-ink",
            )}
          >
            {label}
          </button>
        ))}
      </div>

      {mode === "file" && (
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            sendFile(e.dataTransfer.files[0]);
          }}
          className={cx(
            "flex flex-col items-center gap-3 rounded-2xl border-2 border-dashed px-4 py-8 text-center transition",
            dragging ? "border-accent bg-accent/10" : "border-white/14",
          )}
        >
          <p className="text-sm text-ink-2">Drop an .epub, .pdf or .txt file here (up to 80 MB), or</p>
          <Button variant="primary" disabled={busy} onClick={() => fileInput.current?.click()}>
            {upload.isPending ? "Importing…" : "Choose a file"}
          </Button>
          <input
            ref={fileInput}
            type="file"
            accept=".epub,.pdf,.txt,application/epub+zip,application/pdf,text/plain"
            className="sr-only"
            tabIndex={-1}
            onChange={(e) => {
              sendFile(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
          <p className="text-xs text-ink-3">
            Scanned PDFs without a text layer can't be read yet. DRM-protected books can't be opened.
          </p>
        </div>
      )}

      {mode === "article" && (
        <form
          className="flex flex-col gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (url.trim()) article.mutate(url.trim(), { onSuccess: (item) => (setUrl(""), open(item)) });
          }}
        >
          <label className="text-xs font-medium text-ink-2" htmlFor="article-url">
            Link to an article or blog post
          </label>
          <div className="flex gap-2">
            <input
              id="article-url"
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://…"
              className="min-h-11 min-w-0 flex-1 rounded-xl border border-white/14 bg-surface px-3 text-sm text-ink placeholder:text-ink-3"
            />
            <Button type="submit" variant="primary" disabled={busy || !url.trim()}>
              {article.isPending ? "Fetching…" : "Add"}
            </Button>
          </div>
          <p className="text-xs text-ink-3">The main text is extracted once and kept on this computer; ads and menus are left out.</p>
        </form>
      )}

      {mode === "text" && (
        <form
          className="flex flex-col gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            const text = body.trim();
            if (!text) return;
            const name = title.trim() || text.slice(0, 40).replace(/\s+/g, " ") + (text.length > 40 ? "…" : "");
            pasted.mutate({ title: name, text }, { onSuccess: (item) => (setTitle(""), setBody(""), open(item)) });
          }}
        >
          <label className="text-xs font-medium text-ink-2" htmlFor="paste-title">
            Title (optional)
          </label>
          <input
            id="paste-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={200}
            className="min-h-11 rounded-xl border border-white/14 bg-surface px-3 text-sm text-ink"
          />
          <label className="mt-1 text-xs font-medium text-ink-2" htmlFor="paste-text">
            Text
          </label>
          <textarea
            id="paste-text"
            lang={lang}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            maxLength={200000}
            placeholder="Paste a chapter, a chat message, a news story…"
            className="min-h-40 w-full rounded-xl border border-white/14 bg-surface p-3 text-base leading-relaxed text-ink placeholder:text-ink-3"
          />
          <div className="flex flex-wrap items-center gap-2">
            <Button type="submit" variant="primary" disabled={busy || !body.trim()}>
              {pasted.isPending ? "Saving…" : "Save and read"}
            </Button>
            <Button variant="ghost" onClick={() => (setBody(SAMPLES[lang] ?? ""), setTitle("Sample"))}>
              Try a sample text
            </Button>
          </div>
        </form>
      )}

      {error && (
        <p role="alert" className="mt-3 text-sm text-red-200">
          {error.message}
        </p>
      )}
    </Panel>
  );
}

function ShelfCard({ item }: { item: ContentItem }) {
  const analysing = item.analysis_status === "queued" || item.analysis_status === "running";
  return (
    <li>
      <Link
        to="/read/$itemId"
        params={{ itemId: String(item.id) }}
        className="flex h-full flex-col gap-3 rounded-2xl border border-white/10 bg-white/[0.045] p-4 transition hover:border-white/20 hover:bg-white/[0.08]"
      >
        <div className="flex items-start gap-3">
          <div
            aria-hidden="true"
            className="flex h-16 w-12 shrink-0 items-center justify-center rounded-md bg-[#f6f2ea] text-[10px] font-bold tracking-wider text-[#1f1d1a] uppercase shadow-md"
          >
            {TYPE_LABELS[item.type] ?? item.type}
          </div>
          <div className="min-w-0">
            <div className="line-clamp-2 text-sm leading-snug font-semibold">{item.title}</div>
            <div className="mt-1 truncate text-xs text-ink-3">
              {item.creator ?? (item.url ? new URL(item.url).hostname : TYPE_LABELS[item.type])}
              {item.word_count ? ` · ${item.word_count.toLocaleString("en")} words` : ""}
              {item.last_opened_at && ` · ${formatDay(localDayOf(item.last_opened_at))}`}
            </div>
          </div>
        </div>
        <div className="mt-auto flex flex-wrap gap-1.5">
          {analysing ? (
            <Chip className="px-2 py-0.5 text-[11px]">analysing…</Chip>
          ) : item.coverage !== null ? (
            <Chip tone="accent" className="px-2 py-0.5 text-[11px]">
              ≈ {Math.round(item.coverage * 100)}% known
            </Chip>
          ) : null}
          {item.expected_unknown !== null && !analysing && (
            <Chip className="px-2 py-0.5 text-[11px]">≈ {Math.round(item.expected_unknown)} new words</Chip>
          )}
          {item.status === "finished" && (
            <Chip tone="good" className="px-2 py-0.5 text-[11px]">
              finished
            </Chip>
          )}
        </div>
        {item.progress > 0.01 && item.status !== "finished" && (
          <div className="h-1 overflow-hidden rounded-full bg-white/10" aria-label={`${Math.round(item.progress * 100)}% read`}>
            <div className="h-full bg-accent" style={{ width: `${item.progress * 100}%` }} />
          </div>
        )}
      </Link>
    </li>
  );
}
