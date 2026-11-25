import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useEffect, useId, useRef, useState } from "react";

import { api } from "../api/client";
import type { SearchResult, SearchState } from "../api/types";
import { displayTitle } from "../lib/nav";
import { LevelChip, readingMinutes, videoThumb } from "./cards";
import { GRID, Spinner } from "./Suggestions";
import { Button, Skeleton, cx } from "./ui";

const NOUN = { video: "videos", article: "articles" } as const;
const RECENT_MAX = 6;

const recentKey = (lang: string, kind: string) => `lingo.search.recent.${kind}.${lang}`;

function readRecent(lang: string, kind: string): string[] {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(recentKey(lang, kind)) ?? "[]");
    return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string").slice(0, RECENT_MAX) : [];
  } catch {
    return [];
  }
}

function writeRecent(lang: string, kind: string, list: string[]): void {
  try {
    localStorage.setItem(recentKey(lang, kind), JSON.stringify(list.slice(0, RECENT_MAX)));
  } catch {
    // private mode: recent searches just aren't kept
  }
}

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), ms);
    return () => window.clearTimeout(timer);
  }, [value, ms]);
  return debounced;
}

/**
 * Search YouTube (Watch) or the news (Read) in the language you're learning. Suggestions appear as you type; results
 * are checked one by one in the search's own order, and only those really in your language are shown, each with its
 * level.
 */
export function ContentSearch({
  lang,
  languageName,
  kind,
  onActive,
}: {
  lang: string;
  languageName: string;
  kind: "video" | "article";
  onActive: (active: boolean) => void;
}) {
  const qc = useQueryClient();
  const [query, setQuery] = useState("");
  const [searchId, setSearchId] = useState<string | null>(null);
  const [recent, setRecent] = useState(() => readRecent(lang, kind));
  const start = useMutation({
    mutationFn: (q: string) => api.search(lang, kind, q),
    onSuccess: (state) => {
      qc.setQueryData(["search", state.id], state);
      setSearchId(state.id);
      onActive(true);
    },
  });
  const results = useQuery({
    queryKey: ["search", searchId],
    queryFn: () => api.searchResults(searchId as string),
    enabled: Boolean(searchId),
    refetchInterval: (q) => ((q.state.data?.pending ?? 0) > 0 ? 1500 : false),
  });
  const run = (q: string) => {
    const clean = q.trim().replace(/\s+/g, " ");
    if (!clean) return;
    setQuery(clean);
    const next = [clean, ...recent.filter((r) => r.toLowerCase() !== clean.toLowerCase())].slice(0, RECENT_MAX);
    setRecent(next);
    writeRecent(lang, kind, next);
    start.mutate(clean);
  };
  const forget = (q: string) => {
    const next = recent.filter((r) => r !== q);
    setRecent(next);
    writeRecent(lang, kind, next);
  };
  const clear = () => {
    setSearchId(null);
    setQuery("");
    onActive(false);
    void qc.invalidateQueries({ queryKey: ["feed"] });
  };
  return (
    <div className="flex flex-col gap-4">
      <SearchBox
        lang={lang}
        kind={kind}
        languageName={languageName}
        query={query}
        onQuery={setQuery}
        onSearch={run}
        onClear={() => (searchId ? clear() : setQuery(""))}
        recent={recent}
        onForget={forget}
        busy={start.isPending}
      />
      {start.isError && (
        <p role="alert" className="text-sm text-red-200">
          {start.error.message}
        </p>
      )}
      {start.isPending && <SkeletonGrid count={6} label="Searching" />}
      {results.data && !start.isPending && <Results state={results.data} languageName={languageName} onClear={clear} />}
    </div>
  );
}

type Option = { text: string; recent: boolean };

/** The search field: suggestions as you type (like YouTube's), your recent searches when it's empty, full keyboard use. */
function SearchBox({
  lang,
  kind,
  languageName,
  query,
  onQuery,
  onSearch,
  onClear,
  recent,
  onForget,
  busy,
}: {
  lang: string;
  kind: "video" | "article";
  languageName: string;
  query: string;
  onQuery: (q: string) => void;
  onSearch: (q: string) => void;
  onClear: () => void;
  recent: string[];
  onForget: (q: string) => void;
  busy: boolean;
}) {
  const listId = useId();
  const input = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const typed = query.trim();
  const debounced = useDebounced(typed, 180);
  const suggestions = useQuery({
    queryKey: ["search-suggest", lang, kind, debounced.toLowerCase()],
    queryFn: () => api.searchSuggest(lang, kind, debounced),
    enabled: open && debounced.length >= 2,
    staleTime: 10 * 60_000,
    placeholderData: (previous) => previous,
  });
  const lower = typed.toLowerCase();
  const options: Option[] = typed
    ? [
        ...recent
          .filter((r) => r.toLowerCase().startsWith(lower) && r.toLowerCase() !== lower)
          .slice(0, 2)
          .map((text) => ({ text, recent: true })),
        ...(suggestions.data?.suggestions ?? [])
          .filter((s) => s.toLowerCase() !== lower && !recent.includes(s))
          .slice(0, 7)
          .map((text) => ({ text, recent: false })),
      ]
    : recent.map((text) => ({ text, recent: true }));
  const showList = open && options.length > 0;
  useEffect(() => setActive(-1), [typed, open]);

  const pick = (text: string) => {
    setOpen(false);
    input.current?.blur();
    onSearch(text);
  };
  const where = kind === "video" ? "YouTube" : "the news";

  return (
    <form
      role="search"
      onSubmit={(e) => {
        e.preventDefault();
        pick(active >= 0 && options[active] ? options[active].text : query);
      }}
      className="relative z-20 flex gap-2"
    >
      <div
        className={cx(
          "relative flex min-h-12 flex-1 items-center gap-2.5 rounded-2xl border bg-black/30 px-4 transition-[border-color,box-shadow,background-color] duration-200",
          open
            ? "border-accent/60 bg-black/45 shadow-[0_0_0_4px_color-mix(in_oklab,var(--accent)_16%,transparent)]"
            : "border-white/12 hover:border-white/22",
          showList && "rounded-b-none",
        )}
      >
        {busy ? (
          <Spinner className="shrink-0" />
        ) : (
          <svg
            aria-hidden="true"
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            className={cx("shrink-0 transition-colors", open ? "text-accent" : "text-ink-3")}
          >
            <circle cx="11" cy="11" r="7" />
            <path d="m20 20-3.5-3.5" />
          </svg>
        )}
        <input
          ref={input}
          type="text"
          role="combobox"
          aria-label={`Search ${where} in ${languageName}`}
          aria-expanded={showList}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={active >= 0 ? `${listId}-${active}` : undefined}
          value={query}
          lang={lang}
          autoComplete="off"
          spellCheck={false}
          onChange={(e) => {
            onQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => window.setTimeout(() => setOpen(false), 120)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown" && options.length) {
              e.preventDefault();
              setOpen(true);
              setActive((a) => (a + 1) % options.length);
            } else if (e.key === "ArrowUp" && options.length) {
              e.preventDefault();
              setActive((a) => (a <= 0 ? options.length - 1 : a - 1));
            } else if (e.key === "Escape") {
              if (showList) setOpen(false);
              else onClear();
            }
          }}
          placeholder={kind === "video" ? `Search YouTube in ${languageName}…` : `Search the news in ${languageName}…`}
          className="focus-in-frame min-w-0 flex-1 bg-transparent text-[15px] text-ink outline-none placeholder:text-ink-3"
          enterKeyHint="search"
        />
        {query && (
          <button
            type="button"
            aria-label="Clear the search"
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => {
              onClear();
              input.current?.focus();
            }}
            className="grid size-7 shrink-0 place-items-center rounded-full text-ink-3 transition hover:bg-white/10 hover:text-ink"
          >
            <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <path d="M6 6l12 12M18 6 6 18" />
            </svg>
          </button>
        )}
        {showList && (
          <ul
            id={listId}
            role="listbox"
            aria-label={typed ? "Suggestions" : "Recent searches"}
            className="anim-fade absolute inset-x-[-1px] top-full max-h-80 overflow-y-auto rounded-b-2xl border border-t-white/8 border-accent/60 bg-surface py-1.5 shadow-2xl"
          >
            {options.map((option, n) => (
              <li
                key={`${option.recent}-${option.text}`}
                id={`${listId}-${n}`}
                role="option"
                aria-selected={n === active}
                onMouseDown={(e) => e.preventDefault()}
                onMouseEnter={() => setActive(n)}
                onClick={() => pick(option.text)}
                className={cx("group flex cursor-pointer items-center gap-3 px-4 py-2 text-[15px]", n === active && "bg-white/[0.08]")}
              >
                <span aria-hidden="true" className="shrink-0 text-ink-3">
                  {option.recent ? (
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <circle cx="12" cy="12" r="9" />
                      <path d="M12 7v5l3 2" />
                    </svg>
                  ) : (
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <circle cx="11" cy="11" r="7" />
                      <path d="m20 20-3.5-3.5" />
                    </svg>
                  )}
                </span>
                <span lang={lang} className="min-w-0 flex-1 truncate">
                  <Highlight text={option.text} typed={typed} />
                </span>
                {option.recent && !typed && (
                  <button
                    type="button"
                    aria-label={`Remove ${option.text} from recent searches`}
                    onClick={(e) => {
                      e.stopPropagation();
                      onForget(option.text);
                    }}
                    className="rounded px-1.5 text-xs text-ink-3 opacity-0 transition group-hover:opacity-100 hover:text-ink focus:opacity-100"
                  >
                    Remove
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
      <Button type="submit" variant="primary" disabled={busy || !typed} className="min-h-12 px-5">
        Search
      </Button>
    </form>
  );
}

/** The part you typed stays plain and the completion is bold, as in a search engine's suggestions. */
function Highlight({ text, typed }: { text: string; typed: string }) {
  if (typed && text.toLowerCase().startsWith(typed.toLowerCase())) {
    return (
      <>
        <span className="text-ink-2">{text.slice(0, typed.length)}</span>
        <strong className="font-semibold text-ink">{text.slice(typed.length)}</strong>
      </>
    );
  }
  return <>{text}</>;
}

function SkeletonGrid({ count, label }: { count: number; label?: string }) {
  return (
    <ul className={GRID} aria-label={label}>
      {Array.from({ length: count }, (_, n) => (
        <li key={n}>
          <Skeleton className="aspect-[4/3.6] rounded-2xl" />
        </li>
      ))}
    </ul>
  );
}

/**
 * Results in the search's own order, never reshuffled: they are checked from the first one down, and each is shown
 * once it (and everything above it) has been checked. Results that turn out not to be in your language, or have no
 * captions in it, are left out, so nothing already on screen moves or disappears.
 */
function Results({ state, languageName, onClear }: { state: SearchState; languageName: string; onClear: () => void }) {
  const shown: SearchResult[] = [];
  const unreadable: SearchResult[] = [];
  let waiting = 0;
  for (const result of state.results) {
    if (waiting > 0 || result.state === "measuring") {
      waiting += 1;
    } else if (result.state === "ready") {
      shown.push(result);
    } else if (result.state === "failed" && state.kind === "article") {
      unreadable.push(result);
    }
  }
  const checked = state.results.length - state.pending;
  return (
    <section aria-label={`Results for ${state.query}`} className="anim-fade flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2 px-1">
        <p className="text-sm text-ink-2" aria-live="polite">
          {shown.length} {NOUN[state.kind]} in {languageName} for <strong className="text-ink">“{state.query}”</strong>
          {state.pending > 0 ? (
            <span className="ml-2 inline-flex items-center gap-1.5 text-accent">
              <Spinner /> checking language and level… {checked} of {state.results.length}
            </span>
          ) : (
            <span className="text-ink-3"> · each rated for your level</span>
          )}
        </p>
        <Button variant="ghost" className="min-h-9 px-3" onClick={onClear}>
          ← Back to suggestions
        </Button>
      </div>
      {shown.length === 0 && state.pending === 0 ? (
        <p className="rounded-2xl border border-white/10 bg-white/[0.035] p-5 text-sm text-ink-2">
          Nothing in {languageName} found. Try other words, or words in {languageName}.
        </p>
      ) : (
        <ul className={GRID}>
          {shown.map((result) => (
            <li key={result.item?.id ?? result.url ?? result.title} className="anim-in">
              <ResultCard result={result} kind={state.kind} />
            </li>
          ))}
          {Array.from({ length: Math.min(waiting, shown.length === 0 ? 6 : 3) }, (_, n) => (
            <li key={`wait-${n}`} aria-hidden="true">
              <Skeleton className="aspect-[4/3.6] rounded-2xl" />
            </li>
          ))}
        </ul>
      )}
      {unreadable.length > 0 && state.pending === 0 && (
        <details className="rounded-2xl border border-white/10 bg-white/[0.03] px-4 py-3 text-sm text-ink-2">
          <summary className="cursor-pointer">
            {unreadable.length} more {unreadable.length === 1 ? "article" : "articles"} that couldn't be read here (paywall or bot
            check): open on their site
          </summary>
          <ul className="mt-2 flex flex-col gap-1">
            {unreadable.map((r) => (
              <li key={r.url ?? r.title}>
                <a href={r.url ?? undefined} target="_blank" rel="noreferrer noopener" className="text-accent hover:underline">
                  {r.title}
                </a>
                {r.site && <span className="text-ink-3"> · {r.site}</span>}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

function ResultCard({ result, kind }: { result: SearchResult; kind: "video" | "article" }) {
  const item = result.item;
  const picture =
    kind === "video" && item?.external_id ? videoThumb({ source: "youtube", external_id: item.external_id }) : (item?.image ?? result.image);
  const minutes = kind === "video" ? (item?.duration_sec ? Math.round(item.duration_sec / 60) : null) : readingMinutes(item?.word_count ?? null);
  const length = minutes ? (kind === "video" ? `${minutes} min` : `${minutes} min read`) : null;
  const title = displayTitle(item?.title ?? result.title);
  const sub = item?.creator ?? item?.site ?? result.site ?? "";
  const body = (
    <>
      <div className="relative aspect-video overflow-hidden bg-black/40">
        {picture ? (
          <img
            src={picture}
            alt=""
            loading="lazy"
            referrerPolicy="no-referrer"
            className="h-full w-full object-cover transition duration-500 group-hover:scale-[1.03]"
          />
        ) : (
          <div className="flex h-full items-center justify-center px-3 text-center text-xs text-ink-3">{sub}</div>
        )}
        <div aria-hidden="true" className="pointer-events-none absolute inset-x-0 top-0 h-14 bg-gradient-to-b from-black/45 to-transparent" />
        <div className="absolute top-2 left-2">
          <LevelChip band={item?.band ?? null} coverage={item?.coverage ?? null} estimated={Boolean(item?.estimated)} className="bg-black/55" />
        </div>
        {item?.watched && (
          <span className="absolute top-2 right-2 rounded-full bg-emerald-400/85 px-2 py-0.5 text-[11px] font-bold text-emerald-950">
            {kind === "video" ? "watched" : "read"}
          </span>
        )}
        {length && <span className="absolute right-2 bottom-2 rounded-md bg-black/75 px-1.5 py-0.5 text-[11px] font-semibold">{length}</span>}
      </div>
      <div className="flex flex-1 flex-col gap-1 p-3">
        <span className="line-clamp-2 text-[15px] leading-snug font-semibold">{title}</span>
        <span className="truncate text-xs text-ink-3">{sub}</span>
        {item?.expected_unknown != null && (
          <span className="mt-auto pt-1 text-xs text-ink-2">≈ {Math.round(item.expected_unknown)} new words</span>
        )}
      </div>
    </>
  );
  const shell =
    "group relative flex h-full flex-col overflow-hidden rounded-2xl border border-white/10 bg-white/[0.045] transition hover:-translate-y-0.5 hover:border-white/20 hover:bg-white/[0.08]";
  if (item) {
    return (
      <Link to={kind === "video" ? "/watch/$itemId" : "/read/$itemId"} params={{ itemId: String(item.id) }} className={shell}>
        {body}
      </Link>
    );
  }
  return <div className={shell}>{body}</div>;
}
