// Saving things on this device to use offline: one manager behind every Download button and the Downloads page.
//
// What gets saved for an item:
//   books, articles, texts   the pages, already split into words, and the dictionary entries they need
//   manga volumes            the pages and text boxes, and every page image
//   videos, audio, podcasts  the interactive transcript (a read-along); and the recording itself when there is one to
//                            download (a podcast episode or your own file; YouTube videos can't be saved)
// It works the same in the phone app and in a browser on the computer. The phone fetches through the encrypted
// channel to the laptop or server, which carries whole answers, so recordings come in 2 MB slices; a podcast episode
// is downloaded straight from its publisher when the device can.
import { useEffect } from "react";
import { create } from "zustand";

import { syncApi } from "../api/client";
import { allMedia, allPacks, deletePack, keepStorage, saveMedia, savePack, savePageImage, type Pack } from "./packs";
import { blobUrl, isNativeApp, remoteConfig, rpc, withTimeout } from "./remote";

export interface DownloadTarget {
  id: number;
  type: string;
  title: string;
}

export interface SavedEntry {
  id: number;
  title: string;
  type: string;
  language: string;
  kind: Pack["kind"];
  bytes: number; // pack + images + recording
  hasRecording: boolean;
  saved_at: string | null;
  image: string | null;
  creator: string | null;
}

interface Job {
  progress: number; // 0..1
  label: string;
  error?: string;
}

interface DownloadsState {
  loaded: boolean;
  saved: Record<number, SavedEntry>;
  jobs: Record<number, Job>;
}

export const useDownloads = create<DownloadsState>(() => ({ loaded: false, saved: {}, jobs: {} }));

const CHUNK = 2 * 1024 * 1024;
const cancelled = new Set<number>();

function setJob(id: number, job: Job | null) {
  useDownloads.setState((s) => {
    const jobs = { ...s.jobs };
    if (job) jobs[id] = job;
    else delete jobs[id];
    return { jobs };
  });
}

/** Re-read what's saved on this device. */
export async function refreshDownloads(): Promise<void> {
  try {
    const [packs, media] = await Promise.all([allPacks(), allMedia()]);
    const recordings = new Map(media.map((m) => [m.id, m.bytes]));
    const saved: Record<number, SavedEntry> = {};
    for (const pack of packs) {
      const recording = recordings.get(pack.item.id) ?? 0;
      saved[pack.item.id] = {
        id: pack.item.id,
        title: pack.item.title,
        type: pack.item.type,
        language: pack.item.language,
        kind: pack.kind,
        bytes: JSON.stringify(pack).length + recording,
        hasRecording: recordings.has(pack.item.id),
        saved_at: pack.saved_at ?? null,
        image: pack.item.image ?? null,
        creator: pack.item.creator,
      };
    }
    useDownloads.setState({ loaded: true, saved });
  } catch {
    useDownloads.setState({ loaded: true, saved: {} }); // storage unavailable (e.g. a private window)
  }
}

/** What's saved, loaded once per app start. */
export function useSavedDownloads() {
  const state = useDownloads();
  useEffect(() => {
    if (!state.loaded) void refreshDownloads();
  }, [state.loaded]);
  return state;
}

/** A file from the API as a Blob: plain fetch on the computer, the encrypted channel on the phone. */
async function apiBlob(path: string, fallbackType: string): Promise<Blob> {
  if (remoteConfig()) {
    const result = await rpc("GET", path.split("?")[0], Object.fromEntries(new URL(path, "http://hub").searchParams), null, 90_000);
    if (result.status >= 400 || !result.b64) throw new Error(`couldn't download (${result.status})`);
    return (await fetch(blobUrl(result.b64, result.type ?? fallbackType))).blob();
  }
  const response = await withTimeout(fetch(path), 120_000);
  if (!response.ok) throw new Error(`couldn't download (${response.status})`);
  return response.blob();
}

async function downloadRecording(target: DownloadTarget, pack: Pack): Promise<void> {
  const media = pack.media;
  if (!media?.available) return;
  const mime = media.mime ?? "audio/mpeg";
  const total = media.bytes ?? 0;
  const label = "Downloading the recording";
  // A podcast episode straight from its publisher: the phone app's native HTTP has no cross-site limits. In a browser
  // most publishers don't allow it, so the laptop or server fetches it instead (below).
  if (media.via === "enclosure" && media.url && isNativeApp()) {
    try {
      setJob(target.id, { progress: 0.1, label });
      const response = await withTimeout(fetch(media.url), 15 * 60_000);
      if (response.ok) {
        const blob = await response.blob();
        if (blob.size > 0) {
          await saveMedia(target.id, blob, mime);
          return;
        }
      }
    } catch {
      // fall back to the laptop or server
    }
  }
  if (!remoteConfig()) {
    // the computer: one download from its own server
    setJob(target.id, { progress: 0.1, label });
    await saveMedia(target.id, await apiBlob(`/api/content/${target.id}/media`, mime), mime);
    return;
  }
  // the phone through the encrypted channel: 2 MB at a time
  const parts: Blob[] = [];
  let offset = 0;
  for (;;) {
    if (cancelled.has(target.id)) throw new Error("cancelled");
    const part = await apiBlob(`/api/content/${target.id}/media/chunk?offset=${offset}&length=${CHUNK}`, mime);
    parts.push(part);
    offset += part.size;
    setJob(target.id, { progress: total ? Math.min(0.99, 0.1 + (0.9 * offset) / total) : 0.5, label });
    if (part.size < CHUNK || (total && offset >= total)) break;
  }
  await saveMedia(target.id, new Blob(parts, { type: mime }), mime);
}

/** Save an item on this device. Resolves when everything is stored; progress shows in useDownloads().jobs. */
export async function downloadItem(target: DownloadTarget): Promise<void> {
  if (useDownloads.getState().jobs[target.id] && !useDownloads.getState().jobs[target.id].error) return;
  cancelled.delete(target.id);
  setJob(target.id, { progress: 0.02, label: "Preparing" });
  try {
    await keepStorage();
    const pack = await syncApi.pack(target.id);
    if (pack.kind === "manga") {
      // the page images come along, one by one, while the laptop or server is in reach
      const pages = pack.pages as unknown as NonNullable<Pack["manga_pages"]>;
      for (const [n, page] of pages.entries()) {
        if (cancelled.has(target.id)) throw new Error("cancelled");
        setJob(target.id, { progress: (n + 1) / (pages.length + 1), label: `Page ${n + 1} of ${pages.length}` });
        await savePageImage(target.id, page.page, await apiBlob(`/api/manga/${target.id}/image/${page.page}`, "image/jpeg"));
      }
      await savePack({ ...pack, pages: [], manga_pages: pages });
    } else {
      await savePack(pack);
      if (pack.kind === "media") await downloadRecording(target, pack);
    }
    setJob(target.id, null);
  } catch (error) {
    if (cancelled.has(target.id)) {
      await deletePack(target.id).catch(() => undefined);
      setJob(target.id, null);
    } else {
      setJob(target.id, { progress: 0, label: "", error: error instanceof Error ? error.message : "Couldn't save it." });
    }
  } finally {
    cancelled.delete(target.id);
    await refreshDownloads();
  }
}

export function cancelDownload(id: number) {
  cancelled.add(id);
}

export async function removeDownload(id: number): Promise<void> {
  await deletePack(id);
  setJob(id, null);
  await refreshDownloads();
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}
