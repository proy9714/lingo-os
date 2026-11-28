import { Link } from "@tanstack/react-router";
import { useMemo } from "react";

import { useLibrary } from "../api/hooks";
import type { ContentItem, FeedShelf } from "../api/types";
import { displayTitle } from "../lib/nav";
import { useInfiniteSentinel } from "../lib/useInfiniteSentinel";
import * as audioPlayer from "../state/audio";
import { useAudio } from "../state/audio";
import { BANDS, LaterButton, laterList, targetOf } from "./cards";
import { Icon } from "./Icon";
import { Panel, Skeleton, cx } from "./ui";

const READ = new Set(["epub", "pdf", "article", "text"]);

/** The card kind of a library item: where it opens and which "later" list it's on. */
export function kindOfItem(item: Pick<ContentItem, "type">): "video" | "podcast" | "reading" | "manga" {
  if (item.type === "podcast_episode") return "podcast";
  if (item.type === "manga_volume") return "manga";
  return READ.has(item.type) ? "reading" : "video";
}

function pictureOf(item: ContentItem): string | null {
  if (item.source === "youtube" && item.external_id) return `https://i.ytimg.com/vi/${item.external_id}/mqdefault.jpg`;
  const image = (item.metadata as { image?: string } | null)?.image;
  return typeof image === "string" ? image : null;
}

function lengthOf(item: ContentItem): string | null {
  if (item.duration_sec) return `${Math.round(item.duration_sec / 60)} min`;
  const words = (item as { word_count?: number | null }).word_count;
  return words ? `${Math.max(1, Math.round(words / 200))} min read` : null;
}

/** Watch later / Read later / Listen later: what you saved, most recently saved first, more as you scroll. */
export function LaterList({ lang, shelf }: { lang: string; shelf: FeedShelf }) {
  const list = useLibrary(lang, shelf, "later", "");
  const items = useMemo(() => list.data?.pages.flatMap((p) => p.items) ?? [], [list.data]);
  const sentinel = useInfiniteSentinel(
    () => {
      if (list.hasNextPage && !list.isFetchingNextPage) void list.fetchNextPage();
    },
    Boolean(list.hasNextPage),
    items.length,
  );
  const name = laterList(shelf === "watch" ? "video" : shelf === "listen" ? "podcast" : "reading");

  if (list.isPending) return <Skeleton className="h-48 rounded-[20px]" />;
  if (list.isError) return <Panel role="alert">Could not load {name}: {list.error.message}</Panel>;
  if (items.length === 0) {
    return (
      <Panel>
        <p className="flex items-center gap-2 text-sm text-ink-2">
          <Icon name="bookmark" size={16} /> Nothing saved yet. Press the bookmark on any card (or on its page) to keep it here for later.
        </p>
      </Panel>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      <p className="px-1 text-sm text-ink-3">
        {name}: {items.length < (list.data?.pages[0]?.total ?? 0) ? `${list.data?.pages[0]?.total} saved` : `${items.length} saved`}, newest first.
        They leave this list once you've finished them.
      </p>
      <ul className="flex flex-col gap-2">
        {items.map((item) => (
          <LaterRow key={item.id} item={item} />
        ))}
      </ul>
      <div ref={sentinel} aria-hidden="true" />
      {list.isFetchingNextPage && <Skeleton className="h-20 rounded-2xl" />}
    </div>
  );
}

function LaterRow({ item }: { item: ContentItem }) {
  const kind = kindOfItem(item);
  const picture = pictureOf(item);
  const length = lengthOf(item);
  const band = item.band ? BANDS[item.band] : null;
  const current = useAudio((s) => s.item?.id === item.id);
  const playing = useAudio((s) => s.item?.id === item.id && s.playing);
  const inProgress = item.progress > 0.02 && item.progress < 0.9;
  return (
    <li className="anim-in group relative flex items-center gap-3 rounded-2xl border border-white/8 bg-white/[0.04] p-2 transition hover:border-white/16 hover:bg-white/[0.07]">
      <div className={cx("relative shrink-0 overflow-hidden rounded-xl bg-black/40", kind === "podcast" ? "size-16" : "aspect-video w-[128px]")}>
        {picture ? (
          <img src={picture} alt="" loading="lazy" className="size-full object-cover" />
        ) : (
          <span className="grid size-full place-items-center text-ink-3">
            <Icon name={kind === "podcast" ? "headphones" : kind === "video" ? "play" : "book"} size={22} />
          </span>
        )}
        {inProgress && (
          <span className="absolute inset-x-0 bottom-0 h-1 bg-black/50">
            <span className="block h-full bg-accent" style={{ width: `${item.progress * 100}%` }} />
          </span>
        )}
      </div>
      <div className="min-w-0 flex-1">
        <Link to={targetOf({ kind })} params={{ itemId: String(item.id) }} className="line-clamp-2 text-sm leading-snug font-semibold hover:text-accent">
          {displayTitle(item.title)}
        </Link>
        <p className="mt-0.5 truncate text-xs text-ink-3">
          {[item.creator, length, inProgress ? `${Math.round(item.progress * 100)}% done` : null].filter(Boolean).join(" · ")}
        </p>
      </div>
      {band && (
        <span className={cx("hidden rounded-full px-2 py-0.5 text-[11px] font-semibold sm:inline", band.tone)} title={band.hint}>
          {band.label}
        </span>
      )}
      {kind === "podcast" && (
        <button
          type="button"
          onClick={() => (current ? audioPlayer.toggle() : void audioPlayer.load(item, { autoplay: true }))}
          aria-label={playing ? `Pause ${item.title}` : `Play ${item.title}`}
          className={cx(
            "flex size-10 shrink-0 items-center justify-center rounded-full text-sm transition",
            current ? "bg-accent text-accent-ink" : "bg-white/8 hover:bg-accent hover:text-accent-ink",
          )}
        >
          {playing ? "❚❚" : "▶"}
        </button>
      )}
      <LaterButton id={item.id} title={item.title} later kind={kind} className="size-9 rounded-full bg-white/6 opacity-100! text-accent" />
    </li>
  );
}
