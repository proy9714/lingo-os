import { create } from "zustand";

import type { PlayerControls } from "../components/MediaPlayer";
import { getMedia } from "../sync/packs";

/**
 * The one audio player of the app, for podcast episodes. It lives outside any page, so an episode keeps playing while
 * you look around the rest of the app: the episode's own page drives it (transcript, loops, lookups) and every other
 * page shows the floating mini player (components/MiniPlayer.tsx) until you close it.
 */
export interface NowPlaying {
  id: number;
  title: string;
  show: string | null;
  image: string | null;
  lang: string;
}

interface AudioState {
  item: NowPlaying | null;
  playing: boolean;
  time: number; // ms
  duration: number; // ms
  rate: number;
  error: string | null;
  /** the episode a page is showing its own player for (its page, a shadowing session): the mini player hides */
  onPage: number | null;
}

export const useAudio = create<AudioState>(() => ({ item: null, playing: false, time: 0, duration: 0, rate: 1, error: null, onPage: null }));

/** What the player needs to know about an episode (a ContentItem or a suggestion card). */
export interface PlayableEpisode {
  id: number;
  title: string;
  creator: string | null;
  language: string;
  metadata?: Record<string, unknown> | null;
  image?: string | null;
}

let element: HTMLAudioElement | null = null;
let objectUrl: string | null = null;
let loading = 0;

function audio(): HTMLAudioElement {
  if (element) return element;
  const el = new Audio();
  el.preload = "metadata";
  const set = useAudio.setState;
  el.addEventListener("play", () => set({ playing: true, error: null }));
  el.addEventListener("pause", () => set({ playing: false }));
  el.addEventListener("ended", () => set({ playing: false }));
  el.addEventListener("timeupdate", () => set({ time: el.currentTime * 1000 }));
  el.addEventListener("seeked", () => set({ time: el.currentTime * 1000 }));
  el.addEventListener("durationchange", () => set({ duration: Number.isFinite(el.duration) ? el.duration * 1000 : 0 }));
  el.addEventListener("ratechange", () => set({ rate: el.playbackRate }));
  el.addEventListener("error", () => {
    if (el.getAttribute("src")) set({ playing: false, error: "This episode couldn't be played (its publisher didn't answer)." });
  });
  element = el;
  return el;
}

function mediaSession(item: NowPlaying) {
  const session = typeof navigator !== "undefined" ? navigator.mediaSession : undefined;
  if (!session || typeof MediaMetadata === "undefined") return;
  // the lock screen and notification shade show what's playing, with play/pause and ±15 s
  session.metadata = new MediaMetadata({ title: item.title, artist: item.show ?? "", artwork: item.image ? [{ src: item.image }] : [] });
  const el = audio();
  session.setActionHandler("play", () => void el.play());
  session.setActionHandler("pause", () => el.pause());
  session.setActionHandler("seekbackward", () => skip(-15_000));
  session.setActionHandler("seekforward", () => skip(15_000));
}

/**
 * Load an episode (unless it's the one already loaded) and optionally start it. `startMs` is where to begin when
 * it's newly loaded. The copy downloaded on this device plays when there is one, else the publisher's file.
 */
export async function load(episode: PlayableEpisode, { autoplay = false, startMs }: { autoplay?: boolean; startMs?: number } = {}) {
  const el = audio();
  const current = useAudio.getState().item;
  if (current?.id === episode.id) {
    if (autoplay) void el.play().catch(() => undefined);
    return;
  }
  const token = ++loading;
  el.pause();
  const meta = (episode.metadata ?? {}) as { enclosure_url?: string; image?: string };
  const item: NowPlaying = {
    id: episode.id,
    title: episode.title,
    show: episode.creator,
    image: episode.image ?? meta.image ?? null,
    lang: episode.language,
  };
  useAudio.setState({ item, playing: false, time: startMs ?? 0, duration: 0, error: null });
  const blob = await getMedia(episode.id).catch(() => null);
  if (token !== loading) return; // another episode was picked meanwhile
  if (objectUrl) URL.revokeObjectURL(objectUrl);
  objectUrl = blob ? URL.createObjectURL(blob) : null;
  el.src = objectUrl ?? meta.enclosure_url ?? `/api/content/${episode.id}/media`;
  if (startMs) {
    el.addEventListener("loadedmetadata", () => (el.currentTime = startMs / 1000), { once: true });
  }
  mediaSession(item);
  if (autoplay) void el.play().catch(() => undefined);
}

export function play() {
  void audio().play().catch(() => undefined);
}

export function pause() {
  audio().pause();
}

export function toggle() {
  const el = audio();
  if (el.paused) play();
  else pause();
}

export function seek(ms: number) {
  const el = audio();
  el.currentTime = Math.max(0, ms / 1000);
  useAudio.setState({ time: el.currentTime * 1000 });
}

export function skip(deltaMs: number) {
  seek(audio().currentTime * 1000 + deltaMs);
}

export function setRate(rate: number) {
  audio().playbackRate = rate;
}

/** Stop and put the player away. */
export function close() {
  const el = audio();
  el.pause();
  el.removeAttribute("src");
  el.load();
  if (objectUrl) URL.revokeObjectURL(objectUrl);
  objectUrl = null;
  loading++;
  useAudio.setState({ item: null, playing: false, time: 0, duration: 0, error: null });
}

/** The same controls the video players offer, over the app's audio player (for the episode page). */
export function controls(): PlayerControls {
  const el = audio();
  return {
    play,
    pause,
    seek,
    setRate,
    time: () => el.currentTime * 1000,
    duration: () => (Number.isFinite(el.duration) ? el.duration * 1000 : 0),
  };
}
