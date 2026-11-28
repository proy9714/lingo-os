import { useEffect, useRef, useState } from "react";

import type { ContentItem } from "../api/types";
import { YT_EMBED_BLOCKED, YT_PLAYING, loadYouTubeApi, type YTPlayer } from "../lib/youtube";
import { getMedia } from "../sync/packs";
import * as audioPlayer from "../state/audio";
import { useAudio } from "../state/audio";

export interface PlayerControls {
  play(): void;
  pause(): void;
  seek(ms: number): void;
  setRate(rate: number): void;
  time(): number;
  duration(): number;
}

interface Props {
  item: ContentItem;
  startMs?: number;
  onReady: (controls: PlayerControls) => void;
  onTime: (ms: number) => void;
  onPlaying: (playing: boolean) => void;
}

/** One interface over the YouTube IFrame player and the browser's own <video>/<audio>. */
export function MediaPlayer({ item, startMs, onReady, onTime, onPlaying }: Props) {
  if (item.type === "podcast_episode") {
    return <EpisodeAudio item={item} startMs={startMs} onReady={onReady} onTime={onTime} onPlaying={onPlaying} />;
  }
  return item.source === "youtube" && item.external_id ? (
    <YouTube videoId={item.external_id} startMs={startMs} onReady={onReady} onTime={onTime} onPlaying={onPlaying} />
  ) : (
    <LocalMedia item={item} startMs={startMs} onReady={onReady} onTime={onTime} onPlaying={onPlaying} />
  );
}

function YouTube({ videoId, startMs, onReady, onTime, onPlaying }: Omit<Props, "item"> & { videoId: string }) {
  const host = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const callbacks = useRef({ onReady, onTime, onPlaying });
  callbacks.current = { onReady, onTime, onPlaying };

  useEffect(() => {
    let player: YTPlayer | null = null;
    let poll = 0;
    let cancelled = false;
    loadYouTubeApi()
      .then((YT) => {
        if (cancelled || !host.current) return;
        const mount = document.createElement("div");
        host.current.appendChild(mount);
        player = new YT.Player(mount, {
          videoId,
          playerVars: { rel: 0, playsinline: 1, modestbranding: 1, cc_load_policy: 0, start: Math.floor((startMs ?? 0) / 1000) },
          events: {
            onReady: () => {
              const p = player as YTPlayer;
              callbacks.current.onReady({
                play: () => p.playVideo(),
                pause: () => p.pauseVideo(),
                seek: (ms) => p.seekTo(ms / 1000, true),
                setRate: (rate) => p.setPlaybackRate(rate),
                time: () => p.getCurrentTime() * 1000,
                duration: () => p.getDuration() * 1000,
              });
              poll = window.setInterval(() => callbacks.current.onTime(p.getCurrentTime() * 1000), 200);
            },
            onStateChange: (event) => callbacks.current.onPlaying(event.data === YT_PLAYING),
            onError: (event) =>
              setError(
                YT_EMBED_BLOCKED.has(event.data)
                  ? "The uploader doesn't allow this video to play outside YouTube."
                  : `YouTube player error ${event.data}.`,
              ),
          },
        });
      })
      .catch((exc: Error) => setError(exc.message));
    return () => {
      cancelled = true;
      window.clearInterval(poll);
      player?.destroy();
      if (host.current) host.current.innerHTML = "";
    };
    // startMs is only used for the first load
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videoId]);

  return (
    <div className="relative aspect-video w-full overflow-hidden rounded-[18px] border border-white/10 bg-black">
      <div ref={host} className="absolute inset-0 [&_iframe]:h-full [&_iframe]:w-full" />
      {error && (
        <div role="alert" className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-black/85 p-6 text-center text-sm">
          <p>{error}</p>
          <a href={`https://www.youtube.com/watch?v=${videoId}`} target="_blank" rel="noopener" className="font-semibold text-accent underline">
            Open on YouTube
          </a>
        </div>
      )}
    </div>
  );
}

/**
 * Where to play a recording from: the copy downloaded on this device when there is one (works offline), otherwise the
 * laptop or server.
 */
export function useRecordingSrc(id: number, fallback = `/api/content/${id}/media`): string | undefined {
  const [src, setSrc] = useState<string | undefined>(undefined);
  useEffect(() => {
    let live = true;
    let url: string | null = null;
    void getMedia(id).then((blob) => {
      if (!live) return;
      if (blob) {
        url = URL.createObjectURL(blob);
        setSrc(url);
      } else setSrc(fallback);
    });
    return () => {
      live = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, [id, fallback]);
  return src;
}

function LocalMedia({ item, startMs, onReady, onTime, onPlaying }: Props) {
  const ref = useRef<HTMLVideoElement & HTMLAudioElement>(null);
  const isAudio = item.type === "audio" || item.type === "podcast_episode";

  useEffect(() => {
    const media = ref.current;
    if (!media) return;
    if (startMs) media.currentTime = startMs / 1000;
    onReady({
      play: () => void media.play(),
      pause: () => media.pause(),
      seek: (ms) => {
        media.currentTime = ms / 1000;
      },
      setRate: (rate) => {
        media.playbackRate = rate;
      },
      time: () => media.currentTime * 1000,
      duration: () => (Number.isFinite(media.duration) ? media.duration * 1000 : 0),
    });
    const poll = window.setInterval(() => onTime(media.currentTime * 1000), 200);
    return () => window.clearInterval(poll);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.id]);

  // a podcast episode not downloaded here plays straight from its publisher (that works on the phone too)
  const enclosure = item.type === "podcast_episode" ? (item.metadata as { enclosure_url?: string } | null)?.enclosure_url : undefined;
  const src = useRecordingSrc(item.id, enclosure ?? `/api/content/${item.id}/media`);
  useEffect(() => {
    // the lock screen and notification shade show what's playing, with play/pause and ±15 s
    const session = typeof navigator !== "undefined" ? navigator.mediaSession : undefined;
    if (!session || typeof MediaMetadata === "undefined") return;
    const image = (item.metadata as { image?: string } | null)?.image;
    session.metadata = new MediaMetadata({ title: item.title, artist: item.creator ?? "", artwork: image ? [{ src: image }] : [] });
    const media = ref.current;
    if (!media) return;
    session.setActionHandler("play", () => void media.play());
    session.setActionHandler("pause", () => media.pause());
    session.setActionHandler("seekbackward", () => (media.currentTime = Math.max(0, media.currentTime - 15)));
    session.setActionHandler("seekforward", () => (media.currentTime = media.currentTime + 15));
    return () => {
      for (const action of ["play", "pause", "seekbackward", "seekforward"] as const) session.setActionHandler(action, null);
    };
  }, [item.id, item.title, item.creator, item.metadata]);
  const common = {
    src,
    controls: true,
    preload: "metadata" as const,
    onPlay: () => onPlaying(true),
    onPause: () => onPlaying(false),
    onEnded: () => onPlaying(false),
  };
  return isAudio ? (
    <div className="rounded-[18px] border border-white/10 bg-black/40 p-6">
      <audio ref={ref} {...common} className="w-full" />
    </div>
  ) : (
    <video ref={ref} {...common} className="aspect-video w-full rounded-[18px] border border-white/10 bg-black" />
  );
}

/**
 * A podcast episode plays in the app's own audio player (state/audio.ts), so it carries on in the floating mini player
 * when you leave this page.
 */
function EpisodeAudio({ item, startMs, onReady, onTime, onPlaying }: Props) {
  const callbacks = useRef({ onTime, onPlaying });
  callbacks.current = { onTime, onPlaying };
  const playing = useAudio((s) => s.item?.id === item.id && s.playing);
  const time = useAudio((s) => (s.item?.id === item.id ? s.time : 0));
  const duration = useAudio((s) => (s.item?.id === item.id ? s.duration : 0)) || (item.duration_sec ?? 0) * 1000;
  const error = useAudio((s) => (s.item?.id === item.id ? s.error : null));
  const image = (item.metadata as { image?: string } | null)?.image;

  useEffect(() => {
    // already playing in the mini player: carry on from where it is; otherwise load it, ready to play
    void audioPlayer.load(item, { startMs });
    onReady(audioPlayer.controls());
    useAudio.setState({ onPage: item.id }); // this page plays it: the floating player steps aside
    const poll = window.setInterval(() => {
      const state = useAudio.getState();
      if (state.item?.id === item.id) callbacks.current.onTime(audioPlayer.controls().time());
    }, 200);
    return () => {
      window.clearInterval(poll);
      if (useAudio.getState().onPage === item.id) useAudio.setState({ onPage: null });
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.id]);

  useEffect(() => callbacks.current.onPlaying(playing), [playing]);

  return (
    <div className="flex items-center gap-4 rounded-[18px] border border-white/10 bg-black/40 p-4 sm:p-5">
      {image ? (
        <img src={image} alt="" className="size-20 shrink-0 rounded-xl object-cover sm:size-24" />
      ) : null}
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => audioPlayer.skip(-15_000)}
            aria-label="Back 15 seconds"
            className="flex size-10 items-center justify-center rounded-full text-xs font-semibold text-ink-2 hover:bg-white/10"
          >
            −15
          </button>
          <button
            type="button"
            onClick={() => (useAudio.getState().item?.id === item.id ? audioPlayer.toggle() : void audioPlayer.load(item, { autoplay: true }))}
            aria-label={playing ? "Pause" : "Play"}
            className="flex size-12 items-center justify-center rounded-full bg-accent text-lg text-black shadow-lg shadow-accent/25 transition hover:scale-105"
          >
            {playing ? "❚❚" : "▶"}
          </button>
          <button
            type="button"
            onClick={() => audioPlayer.skip(15_000)}
            aria-label="Forward 15 seconds"
            className="flex size-10 items-center justify-center rounded-full text-xs font-semibold text-ink-2 hover:bg-white/10"
          >
            +15
          </button>
        </div>
        <SeekBar time={time} duration={duration} />
        {error && <p role="alert" className="text-xs text-red-200">{error}</p>}
      </div>
    </div>
  );
}

export function clockOf(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const pad = (n: number) => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(s % 60)}` : `${pad(m)}:${pad(s % 60)}`;
}

/** A thin position bar for the app's audio player. */
export function SeekBar({ time, duration, compact = false }: { time: number; duration: number; compact?: boolean }) {
  return (
    <div className="flex items-center gap-2 text-[11px] text-ink-3 tabular-nums">
      {!compact && <span>{clockOf(time)}</span>}
      <input
        type="range"
        min={0}
        max={Math.max(1, Math.round(duration / 1000))}
        value={Math.min(Math.round(time / 1000), Math.max(1, Math.round(duration / 1000)))}
        onChange={(e) => audioPlayer.seek(Number(e.target.value) * 1000)}
        aria-label="Position"
        className="h-1 min-w-0 flex-1 cursor-pointer accent-[var(--accent)]"
      />
      {!compact && <span>{duration ? clockOf(duration) : "--:--"}</span>}
    </div>
  );
}
