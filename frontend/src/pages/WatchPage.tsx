import { Link } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";

import { api } from "../api/client";
import { useActiveLanguage, useContentMutation, useEvidence, useLibrary, usePool } from "../api/hooks";
import type { ContentItem } from "../api/types";
import { GRID, SuggestionGrid } from "../components/Suggestions";
import { Button, Chip, Panel, PanelTitle, ProgressBar, Skeleton, Tabs } from "../components/ui";
import { formatDay, localDayOf } from "../lib/format";
import { useInfiniteSentinel } from "../lib/useInfiniteSentinel";

type WatchTab = "for-you" | "watched";

export function WatchPage() {
  const { code, language } = useActiveLanguage();
  const [tab, setTab] = useState<WatchTab>("for-you");
  const [adding, setAdding] = useState(false);
  const pool = usePool(code).data;
  const watched = useLibrary(code, "watch", "watched", "").data?.pages[0]?.total;

  return (
    <div className="flex flex-col gap-5">
      <header className="flex flex-wrap items-end justify-between gap-3 px-1 pt-1">
        <div>
          <h1 className="text-[28px] font-bold tracking-tight">Watch &amp; listen</h1>
          <p className="mt-1.5 max-w-2xl text-sm text-ink-2">
            {language?.name} videos picked for your level, each with a clickable transcript: click a word and the video pauses
            while you look it up. Watching time counts only while a video actually plays.
          </p>
        </div>
        <Button variant={adding ? "secondary" : "primary"} aria-expanded={adding} onClick={() => setAdding((v) => !v)}>
          {adding ? "Close" : "+ Add a video"}
        </Button>
      </header>

      {adding && <AddVideoPanel lang={code} />}

      <Tabs<WatchTab>
        label="Videos"
        value={tab}
        onChange={setTab}
        items={[
          { value: "for-you", label: "For you", count: pool?.pools.watch ?? null },
          { value: "watched", label: "Watched", count: watched ?? null },
        ]}
      />

      {tab === "for-you" ? <SuggestionGrid key={code} lang={code} shelf="watch" /> : <WatchedTab lang={code} />}
    </div>
  );
}

function AddVideoPanel({ lang }: { lang: string }) {
  const [url, setUrl] = useState("");
  const add = useContentMutation((link: string) => api.addYouTube(lang, link));
  const scan = useContentMutation(() => api.scanMedia());
  return (
    <Panel aria-labelledby="t-add" className="grid gap-6 md:grid-cols-2">
      <div>
        <PanelTitle id="t-add">Add a YouTube video</PanelTitle>
        <form
          className="flex flex-col gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (url.trim()) add.mutate(url.trim(), { onSuccess: () => setUrl("") });
          }}
        >
          <label className="text-xs font-medium text-ink-2" htmlFor="yt-url">
            YouTube link
          </label>
          <div className="flex gap-2">
            <input
              id="yt-url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://www.youtube.com/watch?v=…"
              className="min-h-11 min-w-0 flex-1 rounded-xl border border-white/14 bg-surface px-3 text-sm text-ink placeholder:text-ink-3"
            />
            <Button type="submit" variant="primary" disabled={add.isPending || !url.trim()}>
              {add.isPending ? "Adding…" : "Add"}
            </Button>
          </div>
          {add.isError && <p role="alert" className="text-sm text-red-200">{add.error.message}</p>}
          {add.data && (
            <p className="text-sm text-good">
              Added “{add.data.title}”{add.data.transcript_kind ? " with its transcript. " : " (no captions in this language). "}
              <Link to="/watch/$itemId" params={{ itemId: String(add.data.id) }} className="font-semibold underline">
                Watch it now
              </Link>
            </p>
          )}
        </form>
      </div>
      <div>
        <PanelTitle>Your own files</PanelTitle>
        <p className="text-sm text-ink-2">
          Put video or audio files in <code className="rounded bg-black/40 px-1">data\library\media\{lang}\</code>, with a same-named{" "}
          <code className="rounded bg-black/40 px-1">.srt</code> or <code className="rounded bg-black/40 px-1">.vtt</code> file for the
          transcript.
        </p>
        <Button className="mt-3" disabled={scan.isPending} onClick={() => scan.mutate(undefined)}>
          {scan.isPending ? "Scanning…" : "Scan the media folder"}
        </Button>
        {scan.data && (
          <p className="mt-2 text-sm text-ink-2">
            {scan.data.added.length} new file(s), {scan.data.with_subtitles} with subtitles.
            {scan.data.problems.length > 0 && ` Problems: ${scan.data.problems.join("; ")}`}
          </p>
        )}
      </div>
    </Panel>
  );
}

function WatchedTab({ lang }: { lang: string }) {
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(query.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [query]);
  const list = useLibrary(lang, "watch", "watched", debounced);
  const items = useMemo(() => list.data?.pages.flatMap((p) => p.items) ?? [], [list.data]);
  const sentinel = useInfiniteSentinel(
    () => {
      if (list.hasNextPage && !list.isFetchingNextPage) void list.fetchNextPage();
    },
    Boolean(list.hasNextPage),
    items.length,
  );

  return (
    <div className="flex flex-col gap-4">
      <HistoryCard lang={lang} />
      <div className="flex flex-wrap items-center justify-between gap-2 px-1">
        <p className="text-sm text-ink-3">Everything you've watched, newest first. These are never suggested again.</p>
        <label className="flex min-w-[240px] items-center rounded-xl border border-white/10 bg-black/25 px-3">
          <span className="sr-only">Search watched videos</span>
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search titles, channels…"
            className="min-h-10 w-full bg-transparent text-sm text-ink outline-none placeholder:text-ink-3"
          />
        </label>
      </div>
      {list.isPending ? (
        <Skeleton className="h-64 rounded-[20px]" />
      ) : list.isError ? (
        <Panel role="alert">Could not load your videos: {list.error.message}</Panel>
      ) : items.length === 0 ? (
        <Panel>
          <p className="text-sm text-ink-2">{debounced ? "No watched video matches that." : "Nothing watched yet."}</p>
        </Panel>
      ) : (
        <ul className={GRID}>
          {items.map((item) => (
            <VideoCard key={item.id} item={item} />
          ))}
        </ul>
      )}
      <div ref={sentinel} aria-hidden="true" />
      {list.isFetchingNextPage && <Skeleton className="h-40 rounded-[20px]" />}
    </div>
  );
}

function VideoCard({ item }: { item: ContentItem }) {
  const minutes = item.duration_sec ? Math.round(item.duration_sec / 60) : null;
  const thumb = item.source === "youtube" && item.external_id ? `https://i.ytimg.com/vi/${item.external_id}/mqdefault.jpg` : null;
  return (
    <li>
      <Link
        to="/watch/$itemId"
        params={{ itemId: String(item.id) }}
        className="flex h-full flex-col overflow-hidden rounded-2xl border border-white/10 bg-white/[0.045] transition hover:border-white/20 hover:bg-white/[0.08]"
      >
        <div className="relative aspect-video bg-black/40">
          {thumb ? (
            <img src={thumb} alt="" loading="lazy" className="h-full w-full object-cover" />
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-ink-3">{item.type === "audio" ? "Audio" : "Local video"}</div>
          )}
          {minutes !== null && <span className="absolute right-2 bottom-2 rounded-md bg-black/75 px-1.5 py-0.5 text-xs">{minutes} min</span>}
          {item.progress > 0.02 && item.progress < 0.9 && (
            <div className="absolute inset-x-0 bottom-0 h-1 bg-black/50">
              <div className="h-full bg-accent" style={{ width: `${item.progress * 100}%` }} />
            </div>
          )}
        </div>
        <div className="flex flex-1 flex-col gap-2 p-3">
          <div className="line-clamp-2 text-sm leading-snug font-semibold">{item.title}</div>
          <div className="text-xs text-ink-3">
            {item.creator ?? (item.source === "local" ? "Local file" : "")}
            {item.times_watched > 0 && ` · watched ${item.times_watched}×`}
            {item.last_watched_at && ` · ${formatDay(localDayOf(item.last_watched_at))}`}
          </div>
          <div className="mt-auto flex flex-wrap gap-1.5">
            {item.coverage !== null ? (
              <Chip tone="accent" className="px-2 py-0.5 text-[11px]">
                ≈ {Math.round(item.coverage * 100)}% known
              </Chip>
            ) : (
              <Chip className="px-2 py-0.5 text-[11px]">{item.transcript_kind ? "analysing…" : "no transcript yet"}</Chip>
            )}
            {item.expected_unknown !== null && (
              <Chip className="px-2 py-0.5 text-[11px]">≈ {Math.round(item.expected_unknown)} new words</Chip>
            )}
            {item.speech_wpm && <Chip className="px-2 py-0.5 text-[11px]">{Math.round(item.speech_wpm)} wpm</Chip>}
          </div>
        </div>
      </Link>
    </li>
  );
}

function HistoryCard({ lang }: { lang: string }) {
  const evidence = useEvidence(lang);
  const start = useContentMutation(() => api.startHistory());
  const data = evidence.data;
  const job = data?.job;
  const running = job?.status === "queued" || job?.status === "running";
  return (
    <Panel aria-labelledby="t-history">
      <PanelTitle id="t-history" aside={data && <Chip>{data.videos_analysed}/{data.videos_watched} analysed</Chip>}>
        What your videos contained
      </PanelTitle>
      {!data ? (
        <Skeleton className="h-28" />
      ) : (
        <>
          {data.videos_analysed > 0 ? (
            <dl className="grid grid-cols-2 gap-2 text-sm">
              <div className="well rounded-xl p-3">
                <dt className="text-xs text-ink-3">Content words heard</dt>
                <dd className="mt-1 font-semibold">{data.content_words_heard.toLocaleString("en")}</dd>
              </div>
              <div className="well rounded-xl p-3">
                <dt className="text-xs text-ink-3">Words heard 10+ times</dt>
                <dd className="mt-1 font-semibold">{data.lemmas_heard_10_plus.toLocaleString("en")}</dd>
              </div>
              <div className="well col-span-2 rounded-xl p-3">
                <dt className="text-xs text-ink-3">Your usual videos need about</dt>
                <dd className="mt-1 font-semibold">
                  {data.vocabulary_for_90_percent ? `${data.vocabulary_for_90_percent.toLocaleString("en")} words` : "–"} for 90% of their words
                </dd>
              </div>
            </dl>
          ) : (
            <p className="text-sm text-ink-2">
              Fetch the captions of the videos you've watched to see what they contained. This feeds your starting level and
              colours words you've heard often as known.
            </p>
          )}
          {running && job && (
            <div className="mt-3">
              <ProgressBar value={job.progress} label="Fetching captions" />
              <p className="mt-1.5 truncate text-xs text-ink-3">{String(job.result?.message ?? "Starting…")}</p>
            </div>
          )}
          {job?.status === "done" && job.result && "fetched" in job.result && (
            <p className="mt-3 text-xs text-ink-3">
              Last run: {String(job.result.fetched)} fetched, {String(job.result.no_captions)} without captions,{" "}
              {String(job.result.errors)} errors.
            </p>
          )}
          <Button className="mt-3 w-full" disabled={running || start.isPending} onClick={() => start.mutate(undefined)}>
            {running ? "Working…" : data.videos_analysed < data.videos_watched ? "Fetch and analyse my watched videos" : "Check for new videos"}
          </Button>
        </>
      )}
    </Panel>
  );
}
