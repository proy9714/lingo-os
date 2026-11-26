import { useEffect, useRef, useState } from "react";

import type { ContentItem } from "../api/types";
import { YT_EMBED_BLOCKED, YT_PLAYING, loadYouTubeApi, type YTPlayer } from "../lib/youtube";
import { getMedia } from "../sync/packs";

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
