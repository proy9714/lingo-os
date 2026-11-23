import { Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import { useActiveLanguage, useContentList, useContentMutation, useEvidence } from "../api/hooks";
import type { ContentItem } from "../api/types";
import { Button, Chip, Panel, PanelTitle, ProgressBar, Skeleton } from "../components/ui";
import { formatDay, localDayOf } from "../lib/format";

export function WatchPage() {
  const { code, language } = useActiveLanguage();
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [url, setUrl] = useState("");
  const list = useContentList(code, debounced);
  const add = useContentMutation((link: string) => api.addYouTube(code, link));
  const scan = useContentMutation(() => api.scanMedia());

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(query.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [query]);

  return (
    <div className="flex flex-col gap-4">
      <header className="px-1 pt-1">
        <h1 className="text-[28px] font-bold tracking-tight">Watch &amp; listen</h1>
        <p className="mt-1.5 max-w-2xl text-sm text-ink-2">
          {language?.name} videos with a clickable transcript. Click a word and the video pauses while you look it up; watching
          time is tracked only while the video actually plays.
        </p>
      </header>

      <div className="grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(min(100%,340px),1fr))]">
        <Panel aria-labelledby="t-add">
          <PanelTitle id="t-add">Add a video</PanelTitle>
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
                Added “{add.data.title}”{add.data.transcript_kind ? " with its transcript." : " (no captions in this language)."}
              </p>
            )}
          </form>
          <div className="mt-4 border-t border-white/8 pt-4">
            <p className="text-sm text-ink-2">
              Own video or audio files: put them in <code className="rounded bg-black/40 px-1">data\library\media\{code}\</code>, with a
              same-named <code className="rounded bg-black/40 px-1">.srt</code> or <code className="rounded bg-black/40 px-1">.vtt</code> for the
              transcript.
            </p>
            <Button className="mt-3" disabled={scan.isPending} onClick={() => scan.mutate(undefined)}>
              {scan.isPending ? "Scanning…" : "Scan media folder"}
            </Button>
            {scan.data && (
              <p className="mt-2 text-sm text-ink-2">
                {scan.data.added.length} new file(s), {scan.data.with_subtitles} with subtitles.
                {scan.data.problems.length > 0 && ` Problems: ${scan.data.problems.join("; ")}`}
              </p>
            )}
          </div>
        </Panel>
        <HistoryCard lang={code} />
      </div>

      <section aria-labelledby="t-library" className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2 px-1">
          <h2 id="t-library" className="text-lg font-bold">
            Your videos {list.data && <span className="text-sm font-medium text-ink-3">· {list.data.total}</span>}
          </h2>
          <label className="flex min-w-[220px] items-center rounded-xl border border-white/10 bg-black/25 px-3">
            <span className="sr-only">Search videos</span>
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
        ) : list.data.items.length === 0 ? (
          <Panel>
            <p className="text-sm text-ink-2">No videos yet. Add a YouTube link above.</p>
          </Panel>
        ) : (
          <ul className="grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(min(100%,290px),1fr))]">
            {list.data.items.map((item) => (
              <VideoCard key={item.id} item={item} />
            ))}
          </ul>
        )}
      </section>
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
        className="glass flex h-full flex-col overflow-hidden rounded-2xl transition hover:bg-white/10"
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
