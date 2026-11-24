import { Link } from "@tanstack/react-router";
import { useEffect, useMemo, useRef } from "react";

import { useAutoTopUp, useFeed, usePool, useTopUp } from "../api/hooks";
import type { PoolStatus, UpNextPick } from "../api/types";
import { useInfiniteSentinel } from "../lib/useInfiniteSentinel";
import { PickCard } from "./cards";
import { Button, ProgressBar, Skeleton, cx } from "./ui";

const NOUN = { watch: "videos", read: "articles" } as const;

export function relativeTime(iso: string | null): string {
  if (!iso) return "never";
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return `${Math.round(hours / 24)} days ago`;
}

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cx("inline-block size-3.5 animate-spin rounded-full border-2 border-current border-r-transparent", className)}
    />
  );
}

/** The app bar badge while new content is being looked for in the background. */
export function SearchPill({ pool }: { pool: PoolStatus | undefined }) {
  if (!pool?.searching) return null;
  const message = String(pool.job?.result?.message ?? "starting");
  return (
    <div
      role="status"
      title={`Looking for new content at your level: ${message}`}
      className="flex min-h-10 items-center gap-2 rounded-xl bg-accent/14 px-3 text-xs font-semibold text-accent"
    >
      <Spinner />
      <span className="hidden sm:inline">Finding new content</span>
      <span className="tabular-nums">{Math.round((pool.job?.progress ?? 0) * 100)}%</span>
    </div>
  );
}

/** Dedupe across pages: a re-ranked item can move from one page to the next. */
function flatten(pages: { items: UpNextPick[] }[] | undefined): UpNextPick[] {
  const seen = new Set<number>();
  const out: UpNextPick[] = [];
  for (const page of pages ?? []) {
    for (const item of page.items) {
      if (!seen.has(item.id)) {
        seen.add(item.id);
        out.push(item);
      }
    }
  }
  return out;
}

export const GRID = "grid gap-4 [grid-template-columns:repeat(auto-fill,minmax(min(100%,260px),1fr))]";

/** A shelf's suggestions as an endless grid: more load as you scroll, more are found in the background. */
export function SuggestionGrid({ lang, shelf }: { lang: string; shelf: "watch" | "read" }) {
  const feed = useFeed(lang, shelf);
  const pool = usePool(lang);
  const topUp = useTopUp(lang);
  useAutoTopUp(lang);
  const items = useMemo(() => flatten(feed.data?.pages), [feed.data]);
  const sentinel = useInfiniteSentinel(
    () => {
      if (feed.hasNextPage && !feed.isFetchingNextPage) void feed.fetchNextPage();
    },
    Boolean(feed.hasNextPage),
    items.length,
  );
  const atEnd = feed.isSuccess && !feed.hasNextPage;

  // Reaching the end asks for more in the background (the server keeps to its cooldown).
  const askedAtEnd = useRef(false);
  useEffect(() => {
    if (atEnd && items.length > 0 && !askedAtEnd.current) {
      askedAtEnd.current = true;
      topUp.mutate(false);
    }
  }, [atEnd, items.length, topUp]);

  // While a search runs and there's little to show, pick up new finds as they arrive.
  const searching = pool.data?.searching;
  const refetch = feed.refetch;
  useEffect(() => {
    if (!searching || items.length >= 12) return;
    const timer = window.setInterval(() => void refetch(), 12_000);
    return () => window.clearInterval(timer);
  }, [searching, items.length, refetch]);

  if (feed.isError) {
    return (
      <p role="alert" className="rounded-2xl bg-red-500/10 p-4 text-sm text-red-200">
        Could not load suggestions: {feed.error.message}
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-5">
      {feed.isPending ? (
        <ul className={GRID} aria-label="Loading suggestions">
          {Array.from({ length: 8 }, (_, n) => (
            <li key={n}>
              <Skeleton className="aspect-[4/3.6] rounded-2xl" />
            </li>
          ))}
        </ul>
      ) : (
        items.length > 0 && (
          <ul className={GRID}>
            {items.map((pick) => (
              <li key={pick.id}>
                <PickCard pick={pick} />
              </li>
            ))}
            {feed.isFetchingNextPage &&
              Array.from({ length: 4 }, (_, n) => (
                <li key={`more-${n}`}>
                  <Skeleton className="aspect-[4/3.6] rounded-2xl" />
                </li>
              ))}
          </ul>
        )
      )}
      <div ref={sentinel} aria-hidden="true" />
      {atEnd && <FeedEnd shelf={shelf} count={items.length} pool={pool.data} onFind={() => topUp.mutate(true)} finding={topUp.isPending} />}
    </div>
  );
}

function FeedEnd({
  shelf,
  count,
  pool,
  onFind,
  finding,
}: {
  shelf: "watch" | "read";
  count: number;
  pool: PoolStatus | undefined;
  onFind: () => void;
  finding: boolean;
}) {
  const noun = NOUN[shelf];
  if (pool?.searching) {
    const message = String(pool.job?.result?.message ?? "starting");
    return (
      <div role="status" className="rounded-2xl border border-accent/25 bg-accent/[0.07] p-5">
        <div className="flex items-center gap-2.5 font-semibold text-accent">
          <Spinner /> Looking for more {noun} at your level…
        </div>
        <p className="mt-1.5 text-sm text-ink-2">
          This runs in the background: keep browsing or watching. New finds appear here {count > 0 ? "when it's done" : "as they're found"}.
        </p>
        <div className="mt-3 max-w-md">
          <ProgressBar value={pool.job?.progress ?? 0} label="Search progress" />
          <p className="mt-1.5 truncate text-xs text-ink-3">{message}</p>
        </div>
      </div>
    );
  }
  return (
    <div className={cx("rounded-2xl border border-white/10 bg-white/[0.035] p-5", count === 0 && "py-10 text-center")}>
      <p className="font-semibold">
        {count === 0 ? `No ${noun} to suggest yet` : `That's all ${count} suggested ${noun} for now`}
      </p>
      <p className={cx("mt-1.5 max-w-2xl text-sm text-ink-2", count === 0 && "mx-auto")}>
        {shelf === "watch"
          ? "Suggestions never include videos you've watched (here or in your Immersion Tracker history). "
          : "Articles come from news and learner sites listed in config/sources.yaml; only those near your level are kept. "}
        New ones are looked for automatically in the background when this list runs low
        {pool?.last_search_at ? ` (last search ${relativeTime(pool.last_search_at)})` : ""}.
      </p>
      {pool?.youtube_refused && shelf === "watch" && (
        <p className="mt-2 text-xs text-warn">
          YouTube asked the last search to slow down, so automatic searches wait 12 hours. Articles aren't affected.
        </p>
      )}
      <div className={cx("mt-4 flex flex-wrap items-center gap-3", count === 0 && "justify-center")}>
        <Button variant="primary" disabled={finding} onClick={onFind}>
          Find more now
        </Button>
        <Link to="/help" hash="suggestions" className="text-sm font-semibold text-accent hover:underline">
          How suggestions work
        </Link>
      </div>
    </div>
  );
}

/** A horizontal row of suggestions for Today, with a link to the full shelf. */
export function SuggestionRow({
  title,
  subtitle,
  items,
  to,
  loading,
  empty,
}: {
  title: string;
  subtitle?: string;
  items: UpNextPick[];
  to: "/watch" | "/read";
  loading: boolean;
  empty: React.ReactNode;
}) {
  const scroller = useRef<HTMLUListElement>(null);
  const scroll = (direction: number) => scroller.current?.scrollBy({ left: direction * scroller.current.clientWidth * 0.85, behavior: "smooth" });
  return (
    <section aria-label={title} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end justify-between gap-2 px-1">
        <div>
          <h2 className="text-xl font-bold tracking-tight">{title}</h2>
          {subtitle && <p className="mt-0.5 text-sm text-ink-3">{subtitle}</p>}
        </div>
        <div className="flex items-center gap-1.5">
          {items.length > 3 && (
            <>
              <button
                type="button"
                onClick={() => scroll(-1)}
                aria-label={`Scroll ${title} left`}
                className="hidden size-9 items-center justify-center rounded-full border border-white/12 text-ink-2 hover:bg-white/10 md:flex"
              >
                ‹
              </button>
              <button
                type="button"
                onClick={() => scroll(1)}
                aria-label={`Scroll ${title} right`}
                className="hidden size-9 items-center justify-center rounded-full border border-white/12 text-ink-2 hover:bg-white/10 md:flex"
              >
                ›
              </button>
            </>
          )}
          <Link to={to} className="ml-1 inline-flex min-h-9 items-center rounded-full px-3 text-sm font-semibold text-accent hover:bg-accent/10">
            See all →
          </Link>
        </div>
      </div>
      {loading ? (
        <div className="flex gap-4 overflow-hidden">
          {Array.from({ length: 4 }, (_, n) => (
            <Skeleton key={n} className="aspect-[4/3.6] w-[280px] shrink-0 rounded-2xl" />
          ))}
        </div>
      ) : items.length === 0 ? (
        empty
      ) : (
        <ul
          ref={scroller}
          className="-mx-1 flex snap-x snap-mandatory gap-4 overflow-x-auto px-1 pb-3 [scrollbar-color:rgb(255_255_255/0.18)_transparent] [scrollbar-width:thin]"
        >
          {items.map((pick) => (
            <li key={pick.id} className="w-[min(78vw,280px)] shrink-0 snap-start">
              <PickCard pick={pick} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
