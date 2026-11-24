import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { api } from "../api/client";
import type { SearchResult, SearchState } from "../api/types";
import { displayTitle } from "../lib/nav";
import { LevelChip, readingMinutes, videoThumb } from "./cards";
import { GRID, Spinner } from "./Suggestions";
import { Button, Skeleton, cx } from "./ui";

const NOUN = { video: "videos", article: "articles" } as const;

/**
 * Search YouTube (Watch) or the news (Read) in the language you're learning. Results appear at once; each one's level
 * is measured in the background and fills in as it arrives, so you see how hard every result is before opening it.
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
    refetchInterval: (q) => ((q.state.data?.pending ?? 0) > 0 ? 2000 : false),
  });
  const clear = () => {
    setSearchId(null);
    setQuery("");
    onActive(false);
    void qc.invalidateQueries({ queryKey: ["feed"] });
  };
  return (
    <div className="flex flex-col gap-4">
      <form
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          if (query.trim()) start.mutate(query.trim());
        }}
        className="flex gap-2"
      >
        <label className="flex min-h-12 flex-1 items-center gap-2 rounded-2xl border border-white/12 bg-black/25 px-4 focus-within:border-accent/60">
          <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="shrink-0 text-ink-3">
            <circle cx="11" cy="11" r="7" />
            <path d="m20 20-3.5-3.5" />
          </svg>
          <span className="sr-only">Search {kind === "video" ? "YouTube" : "the news"}</span>
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={kind === "video" ? `Search YouTube in ${languageName}…` : `Search the news in ${languageName}…`}
            className="min-w-0 flex-1 bg-transparent text-[15px] text-ink outline-none placeholder:text-ink-3"
            enterKeyHint="search"
          />
        </label>
        <Button type="submit" variant="primary" disabled={start.isPending || !query.trim()} className="min-h-12">
          {start.isPending ? <Spinner /> : "Search"}
        </Button>
      </form>
      {start.isError && (
        <p role="alert" className="text-sm text-red-200">
          {start.error.message}
        </p>
      )}
      {start.isPending && (
        <ul className={GRID} aria-label="Searching">
          {Array.from({ length: 6 }, (_, n) => (
            <li key={n}>
              <Skeleton className="aspect-[4/3.6] rounded-2xl" />
            </li>
          ))}
        </ul>
      )}
      {results.data && !start.isPending && <Results state={results.data} onClear={clear} />}
    </div>
  );
}

// keep the search's own order while levels arrive (no jumping); only results that can't be rated move to the end
const ORDER: Record<SearchResult["state"], number> = { ready: 0, measuring: 0, no_captions: 1, failed: 2 };

function Results({ state, onClear }: { state: SearchState; onClear: () => void }) {
  const rated = state.results.filter((r) => r.state === "ready").length;
  // articles that couldn't be read here go to a short list at the end
  const shown = state.results
    .filter((r) => !(state.kind === "article" && r.state === "failed"))
    .sort((a, b) => ORDER[a.state] - ORDER[b.state]);
  const unreadable = state.kind === "article" ? state.results.filter((r) => r.state === "failed") : [];
  return (
    <section aria-label={`Results for ${state.query}`} className="anim-fade flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2 px-1">
        <p className="text-sm text-ink-2">
          {state.results.length} {NOUN[state.kind]} for <strong className="text-ink">“{state.query}”</strong>
          {state.pending > 0 ? (
            <span className="ml-2 inline-flex items-center gap-1.5 text-accent">
              <Spinner /> rating their level… {rated} of {state.results.length}
            </span>
          ) : (
            <span className="text-ink-3"> · each rated for your level</span>
          )}
        </p>
        <Button variant="ghost" className="min-h-9 px-3" onClick={onClear}>
          ← Back to suggestions
        </Button>
      </div>
      {state.results.length === 0 ? (
        <p className="rounded-2xl border border-white/10 bg-white/[0.035] p-5 text-sm text-ink-2">Nothing found. Try other words.</p>
      ) : (
        <ul className={GRID}>
          {shown.map((result, n) => (
            <li key={`${result.item?.id ?? result.url}-${n}`} className="anim-in" style={{ "--i": n } as React.CSSProperties}>
              <ResultCard result={result} kind={state.kind} />
            </li>
          ))}
        </ul>
      )}
      {unreadable.length > 0 && (
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

const STATE_CHIP = "rounded-full bg-black/60 px-2 py-0.5 text-[11px] font-semibold";

function ResultCard({ result, kind }: { result: SearchResult; kind: "video" | "article" }) {
  const item = result.item;
  const picture =
    kind === "video" && item?.external_id ? videoThumb({ source: "youtube", external_id: item.external_id }) : (item?.image ?? result.image);
  const minutes = kind === "video" ? (item?.duration_sec ? Math.round(item.duration_sec / 60) : null) : readingMinutes(item?.word_count ?? null);
  const length = minutes ? (kind === "video" ? `${minutes} min` : `${minutes} min read`) : null;
  const title = displayTitle(item?.title ?? result.title);
  const sub = item?.creator ?? item?.site ?? result.site ?? "";
  let status;
  if (result.state === "measuring") {
    status = <span className={cx(STATE_CHIP, "shimmer text-ink-2")}>rating level…</span>;
  } else if (result.state === "no_captions") {
    status = <span className={cx(STATE_CHIP, "text-ink-2")}>no captions in this language</span>;
  } else if (result.state === "failed") {
    status = (
      <span className={cx(STATE_CHIP, "text-warn")} title={result.error ?? undefined}>
        could not be rated
      </span>
    );
  } else {
    status = <LevelChip band={item?.band ?? null} coverage={item?.coverage ?? null} estimated={Boolean(item?.estimated)} className="bg-black/55" />;
  }
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
        <div className="absolute top-2 left-2">{status}</div>
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
        {result.state === "ready" && item?.expected_unknown != null && (
          <span className="mt-auto pt-1 text-xs text-ink-2">≈ {Math.round(item.expected_unknown)} new words</span>
        )}
      </div>
    </>
  );
  const shell =
    "group relative flex h-full flex-col overflow-hidden rounded-2xl border border-white/10 bg-white/[0.045] transition hover:-translate-y-0.5 hover:border-white/20 hover:bg-white/[0.08]";
  if (item && result.state !== "failed") {
    return (
      <Link to={kind === "video" ? "/watch/$itemId" : "/read/$itemId"} params={{ itemId: String(item.id) }} className={shell}>
        {body}
      </Link>
    );
  }
  if (result.url) {
    // couldn't be read here: open the article on its own site
    return (
      <a href={result.url} target="_blank" rel="noreferrer noopener" className={cx(shell, result.state === "measuring" && "pointer-events-none opacity-80")}>
        {body}
      </a>
    );
  }
  return <div className={shell}>{body}</div>;
}
