// Podcasts: episodes suggested at your level from the shows you follow; find and follow shows; what you've heard.
import { Link } from "@tanstack/react-router";
import { useState } from "react";

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
import { GRID, SuggestionGrid } from "../components/Suggestions";
import { Button, Chip, Panel, PanelTitle, Skeleton, Tabs } from "../components/ui";
import { formatDay, localDayOf } from "../lib/format";
import { displayTitle, useTabParam } from "../lib/nav";

type PodcastTab = "for-you" | "shows" | "listened";

export function PodcastPage() {
  const { code, language } = useActiveLanguage();
  const [tab, setTab] = useTabParam<PodcastTab>(["for-you", "shows", "listened"]);
  const shows = usePodcastShows(code).data?.shows;
  usePodcastRefresh(code);
  const following = shows?.length ?? 0;

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

function ShowsTab({ lang, shows }: { lang: string; shows: PodcastShow[] | undefined }) {
  const [open, setOpen] = useState<number | null>(null);
  const unfollow = usePodcastMutation((id: number) => api.podcastUnsubscribe(id));
  return (
    <div className="flex flex-col gap-5">
      {shows === undefined ? (
        <Skeleton className="h-32" />
      ) : shows.length > 0 ? (
        <ul className="flex flex-col gap-3">
          {shows.map((show) => (
            <li key={show.id} className="glass rounded-2xl p-4">
              <div className="flex items-start gap-4">
                <Artwork src={show.image} title={show.title} className="w-20 shrink-0" />
                <div className="min-w-0 flex-1">
                  <h3 className="font-semibold">{show.title}</h3>
                  <p className="text-xs text-ink-2">
                    {[show.author, `${show.episodes} episodes`, show.listened ? `${show.listened} heard` : null, show.latest ? `latest ${formatDay(localDayOf(show.latest))}` : null]
                      .filter(Boolean)
                      .join(" · ")}
                  </p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <Button variant="secondary" className="min-h-9 px-3 text-xs" onClick={() => setOpen(open === show.id ? null : show.id)}>
                      {open === show.id ? "Hide episodes" : "Episodes"}
                    </Button>
                    <Button variant="ghost" className="min-h-9 px-3 text-xs" disabled={unfollow.isPending} onClick={() => unfollow.mutate(show.id)}>
                      Unfollow
                    </Button>
                  </div>
                </div>
              </div>
              {open === show.id && <Episodes id={show.id} />}
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

function Episodes({ id }: { id: number }) {
  const episodes = usePodcastEpisodes(id);
  if (!episodes.data) return <Skeleton className="mt-3 h-24" />;
  return (
    <ul className="mt-3 flex flex-col divide-y divide-white/8">
      {episodes.data.items.map((item) => (
        <EpisodeRow key={item.id} item={item} />
      ))}
    </ul>
  );
}

function EpisodeRow({ item }: { item: ContentItem }) {
  const minutes = item.duration_sec ? `${Math.round(item.duration_sec / 60)} min` : null;
  return (
    <li className="flex flex-wrap items-center gap-3 py-2.5">
      <Link to="/listen/$itemId" params={{ itemId: String(item.id) }} className="min-w-0 flex-1 hover:text-accent">
        <p className="truncate text-sm font-semibold">{displayTitle(item.title)}</p>
        <p className="text-xs text-ink-2">
          {[item.published_at ? formatDay(localDayOf(item.published_at)) : null, minutes, item.transcript_kind ? "transcript" : null]
            .filter(Boolean)
            .join(" · ")}
        </p>
      </Link>
      {item.status === "finished" && <Chip tone="good">heard</Chip>}
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
