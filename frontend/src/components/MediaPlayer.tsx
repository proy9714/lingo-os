import { useEffect, useRef, useState } from "react";

import type { ContentItem } from "../api/types";
import { YT_EMBED_BLOCKED, YT_PLAYING, loadYouTubeApi, type YTPlayer } from "../lib/youtube";

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

  const common = {
    src: `/api/content/${item.id}/media`,
    controls: true,
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
