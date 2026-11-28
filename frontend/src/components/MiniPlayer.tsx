import { Link } from "@tanstack/react-router";

import { useTracker } from "../lib/useTracker";
import * as audioPlayer from "../state/audio";
import { useAudio } from "../state/audio";
import { Icon } from "./Icon";
import { clockOf } from "./MediaPlayer";
import { cx } from "./ui";

/**
 * The floating player: the podcast episode you started keeps playing while you use the rest of the app, until you
 * close it here. On the episode's own page the page's player takes over (with the transcript), so this one hides.
 */
export function MiniPlayer() {
  const item = useAudio((s) => s.item);
  const playing = useAudio((s) => s.playing);
  const time = useAudio((s) => s.time);
  const duration = useAudio((s) => s.duration);
  const error = useAudio((s) => s.error);
  const onPage = useAudio((s) => s.onPage);
  // the episode's own page (or a shadowing session) is showing its player
  const onItsPage = Boolean(item) && onPage === item?.id;

  if (!item || onItsPage) return null;
  const progress = duration > 0 ? Math.min(1, time / duration) : 0;
  return (
    <aside
      aria-label="Now playing"
      className="above-bottom-nav anim-in fixed right-3 left-3 z-40 md:right-6 md:left-auto md:w-[380px]"
    >
      <ListeningTime id={item.id} lang={item.lang} playing={playing} />
      <div className="relative overflow-hidden rounded-[20px] border border-white/14 bg-[rgb(14_18_30/0.92)] shadow-2xl shadow-black/50 backdrop-blur-xl">
        {/* the artwork, blurred, tints the card */}
        {item.image && (
          <img src={item.image} alt="" aria-hidden="true" className="pointer-events-none absolute inset-0 size-full scale-125 object-cover opacity-20 blur-2xl" />
        )}
        <div className="relative flex items-center gap-3 p-3">
          <Link to="/listen/$itemId" params={{ itemId: String(item.id) }} className="group relative shrink-0" title="Open the episode with its transcript">
            {item.image ? (
              <img src={item.image} alt="" className={cx("size-14 rounded-xl object-cover shadow-lg transition group-hover:scale-105", playing && "ring-2 ring-accent/70")} />
            ) : (
              <span className="grid size-14 place-items-center rounded-xl bg-white/10 text-ink-2">
                <Icon name="headphones" size={24} />
              </span>
            )}
            {playing && (
              <span aria-hidden="true" className="absolute right-1 bottom-1 flex h-3 items-end gap-[2px]">
                {[0, 1, 2].map((n) => (
                  <span key={n} className="eq-bar w-[3px] rounded-full bg-accent" style={{ animationDelay: `${n * 0.18}s` }} />
                ))}
              </span>
            )}
          </Link>
          <div className="min-w-0 flex-1">
            <Link to="/listen/$itemId" params={{ itemId: String(item.id) }} className="block truncate text-sm font-semibold hover:text-accent">
              {item.title}
            </Link>
            <p className="truncate text-xs text-ink-3">
              {error ?? [item.show, duration ? `${clockOf(time)} / ${clockOf(duration)}` : null].filter(Boolean).join(" · ")}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-0.5">
            <button
              type="button"
              onClick={() => audioPlayer.skip(-15_000)}
              aria-label="Back 15 seconds"
              className="hidden size-9 items-center justify-center rounded-full text-[11px] font-semibold text-ink-2 hover:bg-white/10 sm:flex"
            >
              −15
            </button>
            <button
              type="button"
              onClick={audioPlayer.toggle}
              aria-label={playing ? "Pause" : "Play"}
              className="flex size-11 items-center justify-center rounded-full bg-accent text-accent-ink shadow-lg shadow-accent/30 transition hover:scale-105"
            >
              {playing ? "❚❚" : "▶"}
            </button>
            <button
              type="button"
              onClick={() => audioPlayer.skip(15_000)}
              aria-label="Forward 15 seconds"
              className="hidden size-9 items-center justify-center rounded-full text-[11px] font-semibold text-ink-2 hover:bg-white/10 sm:flex"
            >
              +15
            </button>
            <button
              type="button"
              onClick={audioPlayer.close}
              aria-label="Close the player"
              className="flex size-9 items-center justify-center rounded-full text-ink-3 hover:bg-white/10 hover:text-ink"
            >
              <Icon name="close" size={16} />
            </button>
          </div>
        </div>
        {/* position: click or drag along the bottom edge */}
        <div className="relative h-1.5 bg-white/8">
          <div className="absolute inset-y-0 left-0 bg-accent transition-[width] duration-300" style={{ width: `${progress * 100}%` }} />
          <input
            type="range"
            min={0}
            max={Math.max(1, Math.round(duration / 1000))}
            value={Math.round(time / 1000)}
            onChange={(e) => audioPlayer.seek(Number(e.target.value) * 1000)}
            aria-label="Position"
            className="absolute inset-0 size-full cursor-pointer opacity-0"
          />
        </div>
      </div>
    </aside>
  );
}

/** Listening time counts here while the episode plays away from its page (the page counts it there). */
function ListeningTime({ id, lang, playing }: { id: number; lang: string; playing: boolean }) {
  useTracker({
    lang,
    activity: "podcast",
    label: "Listening",
    contentItemId: id,
    active: playing,
    position: () => audioPlayer.controls().time(),
    duration: () => audioPlayer.controls().duration(),
  });
  return null;
}
