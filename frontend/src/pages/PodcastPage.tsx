// Podcasts: episodes suggested at your level from the shows you follow; find and follow shows; what you've heard.
import { Link, useNavigate, useParams } from "@tanstack/react-router";
import { useMemo, useState } from "react";

import { api } from "../api/client";
import {
  useActiveLanguage,
  useLibrary,
  usePodcastEpisodes,
  usePodcastMutation,
  usePodcastRefresh,
  usePodcastSearch,
  usePodcastShows,
} from "../api/hooks";
import type { ContentItem, PodcastSearchResult, PodcastShow } from "../api/types";
import { DownloadButton } from "../components/DownloadButton";
import { Icon } from "../components/Icon";
import { BANDS, LaterButton } from "../components/cards";
import { LaterList } from "../components/Later";
import { GRID, SuggestionGrid } from "../components/Suggestions";
import { Button, Chip, Panel, PanelTitle, Skeleton, Tabs, cx } from "../components/ui";
import { formatDay, localDayOf } from "../lib/format";
import { BackLink, displayTitle, useTabParam } from "../lib/nav";
import { useInfiniteSentinel } from "../lib/useInfiniteSentinel";
import * as audioPlayer from "../state/audio";
import { useAudio } from "../state/audio";

type PodcastTab = "for-you" | "later" | "shows" | "listened";

export function PodcastPage() {
  const { code, language } = useActiveLanguage();
  const [tab, setTab] = useTabParam<PodcastTab>(["for-you", "later", "shows", "listened"]);
  const shows = usePodcastShows(code).data?.shows;
  usePodcastRefresh(code);
  const following = shows?.length ?? 0;
  const later = useLibrary(code, "listen", "later", "").data?.pages[0]?.total;

  return (
    <div className="flex flex-col gap-5">
      <header className="px-1 pt-1">
        <h1 className="text-[28px] font-bold tracking-tight">Podcasts</h1>
        <p className="mt-1.5 max-w-2xl text-sm text-ink-2">
          {language?.name} podcasts picked for your level from the shows you follow. Episodes with a transcript are measured
          like videos (click any word); the others get one from Whisper when transcription is on. Listening time counts while
          an episode plays, and you can download episodes to listen offline.
        </p>
      </header>
      <Tabs<PodcastTab>
        label="Podcasts"
        value={tab}
        onChange={setTab}
        items={[
          { value: "for-you", label: "For you", count: null },
          { value: "later", label: "Listen later", count: later || null },
          { value: "shows", label: "Shows", count: following || null },
          { value: "listened", label: "Listened", count: null },
        ]}
      />
      <div key={tab} className="anim-fade">
        {tab === "for-you" ? (
          following === 0 && shows ? (
            <Panel>
              <p className="text-sm text-ink-2">
                Follow a show or two first: pick from podcasts for learners of {language?.name ?? "your language"} below, or search
                for one you like.
              </p>
              <div className="mt-4">
                <FindShows lang={code} />
              </div>
            </Panel>
          ) : (
            <SuggestionGrid key={code} lang={code} shelf="listen" />
          )
        ) : tab === "later" ? (
          <LaterList lang={code} shelf="listen" />
        ) : tab === "shows" ? (
          <ShowsTab lang={code} shows={shows} />
        ) : (
          <ListenedTab lang={code} />
        )}
      </div>
    </div>
  );
}

function Artwork({ src, title, className }: { src: string | null | undefined; title: string; className?: string }) {
  return src ? (
    <img src={src} alt="" loading="lazy" className={`aspect-square rounded-xl object-cover ${className ?? ""}`} />
  ) : (
    <div aria-label={title} className={`grid aspect-square place-items-center rounded-xl bg-white/8 text-ink-3 ${className ?? ""}`}>
      <Icon name="headphones" size={28} />
    </div>
  );
}

/** Feed descriptions are often HTML: show them as plain text. */
function plainText(html: string | null | undefined): string {
  if (!html) return "";
  const doc = new DOMParser().parseFromString(html, "text/html");
  return (doc.body.textContent ?? "").replace(/\s+/g, " ").trim();
}

function showFacts(show: PodcastShow): string {
  return [
    show.author,
    `${show.episodes.toLocaleString("en")} episodes`,
    show.listened ? `${show.listened} heard` : null,
    show.latest ? `latest ${formatDay(localDayOf(show.latest))}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

function ShowsTab({ lang, shows }: { lang: string; shows: PodcastShow[] | undefined }) {
  return (
    <div className="flex flex-col gap-5">
      {shows === undefined ? (
        <div className={GRID}>
          {Array.from({ length: 3 }, (_, i) => (
            <Skeleton key={i} className="h-44 rounded-2xl" />
          ))}
        </div>
      ) : shows.length > 0 ? (
        <ul className="grid gap-4 [grid-template-columns:repeat(auto-fill,minmax(min(100%,360px),1fr))]">
          {shows.map((show) => (
            <li key={show.id}>
              <ShowCard show={show} />
            </li>
          ))}
        </ul>
      ) : null}
      <Panel>
        <PanelTitle>Find shows</PanelTitle>
        <FindShows lang={lang} />
      </Panel>
    </div>
  );
}

/** A followed show: artwork, what it's about, how much of it you've heard; opens the show's page. */
function ShowCard({ show }: { show: PodcastShow }) {
  const about = plainText(show.description);
  return (
    <Link
      to="/listen/show/$showId"
      params={{ showId: String(show.id) }}
      className="glass group flex h-full gap-4 rounded-2xl p-4 transition hover:bg-white/[0.06]"
    >
      <Artwork src={show.image} title={show.title} className="w-24 shrink-0 shadow-lg transition group-hover:scale-[1.03]" />
      <div className="flex min-w-0 flex-1 flex-col">
        <h3 className="line-clamp-2 font-semibold group-hover:text-accent">{show.title}</h3>
        <p className="mt-0.5 text-xs text-ink-2">{showFacts(show)}</p>
        {about && <p className="mt-2 line-clamp-3 text-xs leading-relaxed text-ink-3">{about}</p>}
        {show.episodes > 0 && show.listened > 0 && (
          <div className="mt-auto pt-2">
            <div className="h-1 overflow-hidden rounded-full bg-white/10">
              <div className="h-full rounded-full bg-accent" style={{ width: `${Math.min(100, (show.listened / show.episodes) * 100)}%` }} />
            </div>
          </div>
        )}
      </div>
    </Link>
  );
}

/** One show: what it is, follow or unfollow, and every episode (newest first, more as you scroll). */
export function PodcastShowPage() {
  const { showId } = useParams({ strict: false }) as { showId: string };
  const id = Number(showId);
  const episodes = usePodcastEpisodes(id);
  const { code } = useActiveLanguage();
  const navigate = useNavigate();
  const unfollow = usePodcastMutation((showId: number) => api.podcastUnsubscribe(showId));
  const follow = usePodcastMutation((url: string) => api.podcastSubscribe(code, url));
  const [more, setMore] = useState(false);
  const show = episodes.data?.pages[0]?.show;
  const items = useMemo(() => episodes.data?.pages.flatMap((p) => p.items) ?? [], [episodes.data]);
  const total = episodes.data?.pages[0]?.total ?? 0;
  const sentinel = useInfiniteSentinel(
    () => {
      if (episodes.hasNextPage && !episodes.isFetchingNextPage) void episodes.fetchNextPage();
    },
    Boolean(episodes.hasNextPage),
    items.length,
  );

  if (episodes.isError) {
    return (
      <div className="flex flex-col gap-4">
        <BackLink to="/listen" label="Podcasts" />
        <p role="alert" className="rounded-2xl bg-red-500/10 p-4 text-sm text-red-200">
          {episodes.error.message}
        </p>
      </div>
    );
  }
  const about = plainText(show?.description);
  return (
    <div className="flex flex-col gap-5">
      <BackLink to="/listen" label="Podcasts" />
      {!show ? (
        <Skeleton className="h-56 rounded-[22px]" />
      ) : (
        <header className="glass relative overflow-hidden rounded-[22px] p-5 sm:p-6">
          {show.image && (
            <img
              src={show.image}
              alt=""
              aria-hidden="true"
              className="pointer-events-none absolute inset-0 size-full scale-125 object-cover opacity-15 blur-3xl"
            />
          )}
          <div className="relative flex flex-col gap-5 sm:flex-row">
            <Artwork src={show.image} title={show.title} className="w-36 shrink-0 shadow-2xl sm:w-44" />
            <div className="flex min-w-0 flex-1 flex-col">
              <p className="text-xs font-semibold tracking-[0.08em] text-ink-3 uppercase">Podcast</p>
              <h1 className="mt-1 text-[26px] leading-tight font-bold tracking-tight">{show.title}</h1>
              <p className="mt-1 text-sm text-ink-2">{showFacts(show)}</p>
              {about && <p className={cx("mt-3 max-w-3xl text-sm leading-relaxed text-ink-2", !more && "line-clamp-3")}>{about}</p>}
              {about.length > 240 && (
                <button type="button" onClick={() => setMore(!more)} className="mt-1 self-start text-xs font-semibold text-accent hover:underline">
                  {more ? "Less" : "More"}
                </button>
              )}
              <div className="mt-4 flex flex-wrap items-center gap-2">
                {items[0] && (
                  <Button variant="primary" onClick={() => void audioPlayer.load(items[0], { autoplay: true })}>
                    ▶ Play the latest
                  </Button>
                )}
                {show.subscribed ? (
                  <Button
                    variant="ghost"
                    disabled={unfollow.isPending}
                    onClick={() => unfollow.mutate(show.id, { onSuccess: () => void navigate({ to: "/listen" }) })}
                  >
                    Unfollow
                  </Button>
                ) : (
                  <Button variant="secondary" disabled={follow.isPending} onClick={() => follow.mutate(show.feed_url)}>
                    {follow.isPending ? "Following…" : "Follow"}
                  </Button>
                )}
                {show.link && (
                  <a href={show.link} target="_blank" rel="noopener" className="px-2 text-sm font-semibold text-accent hover:underline">
                    Website ↗
                  </a>
                )}
              </div>
            </div>
          </div>
        </header>
      )}
      <section aria-labelledby="t-episodes" className="glass rounded-[22px] p-3 sm:p-4">
        <h2 id="t-episodes" className="px-2 pt-1 pb-2 text-sm font-semibold tracking-[0.08em] text-ink-2 uppercase">
          Episodes {total > 0 && <span className="text-ink-3">· {total.toLocaleString("en")}</span>}
        </h2>
        {episodes.isPending ? (
          <div className="flex flex-col gap-2 p-2">
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="h-14" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <p className="p-2 text-sm text-ink-2">No episodes yet: the feed is checked again every 12 hours.</p>
        ) : (
          <ul className="flex flex-col divide-y divide-white/8">
            {items.map((item) => (
              <EpisodeRow key={item.id} item={item} />
            ))}
            {episodes.isFetchingNextPage &&
              Array.from({ length: 3 }, (_, i) => (
                <li key={`more-${i}`} className="py-2">
                  <Skeleton className="h-12" />
                </li>
              ))}
          </ul>
        )}
        <div ref={sentinel} aria-hidden="true" />
      </section>
    </div>
  );
}

/** An episode: play it in the floating player, or open it with its transcript. */
function EpisodeRow({ item }: { item: ContentItem }) {
  const minutes = item.duration_sec ? `${Math.round(item.duration_sec / 60)} min` : null;
  const current = useAudio((s) => s.item?.id === item.id);
  const playing = useAudio((s) => s.item?.id === item.id && s.playing);
  const band = item.band ? BANDS[item.band] : null;
  return (
    <li className={cx("flex items-center gap-3 rounded-xl px-2 py-2.5", current && "bg-accent/[0.07]")}>
      <button
        type="button"
        onClick={() => (current ? audioPlayer.toggle() : void audioPlayer.load(item, { autoplay: true }))}
        aria-label={playing ? `Pause ${item.title}` : `Play ${item.title}`}
        className={cx(
          "flex size-10 shrink-0 items-center justify-center rounded-full text-sm transition",
          current ? "bg-accent text-accent-ink" : "bg-white/8 text-ink hover:bg-accent hover:text-accent-ink",
        )}
      >
        {playing ? "❚❚" : "▶"}
      </button>
      <Link to="/listen/$itemId" params={{ itemId: String(item.id) }} className="min-w-0 flex-1 hover:text-accent" title="Open with the transcript">
        <p className="truncate text-sm font-semibold">{displayTitle(item.title)}</p>
        <p className="text-xs text-ink-2">
          {[item.published_at ? formatDay(localDayOf(item.published_at)) : null, minutes, item.transcript_kind ? "transcript" : null]
            .filter(Boolean)
            .join(" · ")}
        </p>
      </Link>
      {band && (
        <span className={cx("hidden rounded-full px-2 py-0.5 text-[11px] font-semibold sm:inline", band.tone)} title={band.hint}>
          {band.label}
        </span>
      )}
      {item.status === "finished" && <Chip tone="good">heard</Chip>}
      <LaterButton
        id={item.id}
        title={item.title}
        later={Boolean(item.metadata?.saved_at)}
        kind="podcast"
        className="size-9 rounded-full bg-white/6 opacity-100!"
      />
      <DownloadButton item={item} compact />
    </li>
  );
}

function FindShows({ lang }: { lang: string }) {
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [feed, setFeed] = useState("");
  const results = usePodcastSearch(lang, submitted, true);
  const follow = usePodcastMutation((url: string) => api.podcastSubscribe(lang, url));
  const isUrl = /^https?:\/\//.test(query.trim());
  return (
    <div className="flex flex-col gap-4">
      <form
        className="flex gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (isUrl) follow.mutate(query.trim(), { onSuccess: () => setQuery("") });
          else setSubmitted(query.trim());
        }}
      >
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search for a show or topic, or paste a podcast's RSS address"
          aria-label="Search podcasts"
          className="min-h-11 min-w-0 flex-1 rounded-xl border border-white/14 bg-surface px-3 text-sm text-ink placeholder:text-ink-3"
        />
        <Button type="submit" variant="primary" disabled={follow.isPending}>
          {isUrl ? (follow.isPending ? "Following…" : "Follow") : "Search"}
        </Button>
      </form>
      {follow.isError && <p role="alert" className="text-sm text-red-200">{follow.error.message}</p>}
      {follow.data && <p className="text-sm text-good">Following “{follow.data.title}”: {follow.data.added} episodes added.</p>}
      <p className="text-xs text-ink-3">
        {submitted ? `Results for “${submitted}”` : "Podcasts for learners"} from the Apple Podcasts directory (only your search words are sent).
      </p>
      {results.isPending ? (
        <div className={GRID}>
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-24 rounded-2xl" />
          ))}
        </div>
      ) : results.isError ? (
        <p className="text-sm text-ink-2">The directory couldn't be reached right now. You can still paste a show's RSS address.</p>
      ) : (
        <ul className={GRID}>
          {(results.data?.results ?? []).map((show) => (
            <SearchResult key={show.feed_url} show={show} following={show.following || feed === show.feed_url} onFollow={() => {
              setFeed(show.feed_url);
              follow.mutate(show.feed_url);
            }} busy={follow.isPending && feed === show.feed_url} />
          ))}
        </ul>
      )}
    </div>
  );
}

function SearchResult({ show, following, onFollow, busy }: { show: PodcastSearchResult; following: boolean; onFollow: () => void; busy: boolean }) {
  return (
    <li className="glass flex gap-3 rounded-2xl p-3">
      <Artwork src={show.image} title={show.title} className="w-16 shrink-0" />
      <div className="min-w-0 flex-1">
        <p className="line-clamp-2 text-sm font-semibold">{show.title}</p>
        <p className="truncate text-xs text-ink-2">{[show.author, show.episodes ? `${show.episodes} episodes` : null].filter(Boolean).join(" · ")}</p>
        <Button variant={following ? "ghost" : "secondary"} className="mt-2 min-h-8 px-3 text-xs" disabled={following || busy} onClick={onFollow}>
          {following ? "Following" : busy ? "Following…" : "Follow"}
        </Button>
      </div>
    </li>
  );
}

function ListenedTab({ lang }: { lang: string }) {
  const library = useLibrary(lang, "listen", "watched", "");
  const items = library.data?.pages.flatMap((p) => p.items) ?? [];
  if (library.isPending) return <Skeleton className="h-32" />;
  if (!items.length) return <p className="px-1 text-sm text-ink-2">Episodes you listen to show up here.</p>;
  return (
    <ul className="flex flex-col divide-y divide-white/8">
      {items.map((item) => (
        <EpisodeRow key={item.id} item={item} />
      ))}
    </ul>
  );
}
