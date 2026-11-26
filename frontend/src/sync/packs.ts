// What's saved on this device for offline use (phone app or browser), kept in IndexedDB: packs can be several
// megabytes and recordings far more, much too big for localStorage.
//   packs   item id → Pack (the text, manga pages or transcript, already split into words, plus a small dictionary)
//   images  "<item id>/<page>" → Blob (manga page images)
//   media   item id → { blob, mime, bytes, saved_at } (a downloaded recording: podcast episode, local audio or video)
import type { AnnotatedToken, MangaBlock, TranscriptData } from "../api/types";

export interface PackParagraph {
  seq: number;
  locator?: string; // saved since version 2; older packs get "seq:<n>" when read
  text: string;
  tokens: AnnotatedToken[];
}

/** Where a recording can be downloaded from (backend api/offline_media.py). */
export interface MediaSource {
  available: boolean;
  via: "server" | "enclosure" | "none";
  bytes?: number | null;
  mime?: string;
  url?: string;
}

export interface Pack {
  version: number;
  item: {
    id: number;
    language: string;
    type: string;
    title: string;
    creator: string | null;
    coverage: number | null;
    page_count: number | null;
    word_count: number | null;
    duration_sec?: number | null;
    source?: string;
    external_id?: string | null;
    image?: string | null;
  };
  kind: "text" | "manga" | "media";
  pages: { n: number; title: string | null; paragraphs: PackParagraph[] }[];
  // manga packs: each page's size and text boxes; the images are kept in their own store
  manga_pages?: { page: number; width: number; height: number; ocr: string; blocks: MangaBlock[] }[];
  images?: string[];
  // media packs (version 2): the interactive transcript, and where the recording itself can be downloaded from
  transcript?: TranscriptData;
  media?: MediaSource;
  dictionary: Record<string, { term: string; reading: string; pos: string[]; glosses: string[] }[]>;
  saved_at?: string;
}

/** A downloaded audio/video file, kept on this device for offline playback. */
export interface OfflineMedia {
  id: number;
  mime: string;
  bytes: number;
  saved_at: string;
}

const DB = "lingo-packs";
const STORE = "packs";
const IMAGES = "images";
const MEDIA = "media";

let opened: Promise<IDBDatabase> | null = null;
function db(): Promise<IDBDatabase> {
  opened ??= new Promise((resolve, reject) => {
    const request = indexedDB.open(DB, 3);
    request.onupgradeneeded = () => {
      const database = request.result;
      for (const name of [STORE, IMAGES, MEDIA]) {
        if (!database.objectStoreNames.contains(name)) database.createObjectStore(name);
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => {
      opened = null;
      reject(request.error);
    };
  });
  return opened;
}

async function run<T>(mode: IDBTransactionMode, action: (store: IDBObjectStore) => IDBRequest<T>, store = STORE): Promise<T> {
  const database = await db();
  return new Promise((resolve, reject) => {
    const request = action(database.transaction(store, mode).objectStore(store));
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

export const savePack = (pack: Pack) => run("readwrite", (s) => s.put({ ...pack, saved_at: new Date().toISOString() }, pack.item.id));
export const getPack = (id: number) => run<Pack | undefined>("readonly", (s) => s.get(id));
export const deletePack = async (id: number) => {
  const pack = await getPack(id);
  for (const page of pack?.manga_pages ?? []) await run("readwrite", (s) => s.delete(`${id}/${page.page}`), IMAGES);
  await run("readwrite", (s) => s.delete(id), MEDIA);
  return run("readwrite", (s) => s.delete(id));
};
export const savePageImage = (id: number, page: number, image: Blob) => run("readwrite", (s) => s.put(image, `${id}/${page}`), IMAGES);
export const getPageImage = (id: number, page: number) => run<Blob | undefined>("readonly", (s) => s.get(`${id}/${page}`), IMAGES);
export const allPacks = () => run<Pack[]>("readonly", (s) => s.getAll());

// ---------------------------------------------------------------- offline media

interface StoredMedia {
  blob: Blob;
  mime: string;
  bytes: number;
  saved_at: string;
}

export const saveMedia = (id: number, blob: Blob, mime: string) =>
  run("readwrite", (s) => s.put({ blob, mime, bytes: blob.size, saved_at: new Date().toISOString() } satisfies StoredMedia, id), MEDIA);

/** The downloaded recording for an item, if it was saved for offline (null otherwise). */
export async function getMedia(id: number): Promise<Blob | null> {
  try {
    const stored = await run<StoredMedia | undefined>("readonly", (s) => s.get(id), MEDIA);
    return stored?.blob ?? null;
  } catch {
    return null; // storage unavailable (private window): play from the network as usual
  }
}

export const deleteMedia = (id: number) => run("readwrite", (s) => s.delete(id), MEDIA);

export async function allMedia(): Promise<OfflineMedia[]> {
  const database = await db();
  return new Promise((resolve, reject) => {
    const out: OfflineMedia[] = [];
    const request = database.transaction(MEDIA, "readonly").objectStore(MEDIA).openCursor();
    request.onsuccess = () => {
      const cursor = request.result;
      if (!cursor) return resolve(out);
      const value = cursor.value as StoredMedia;
      out.push({ id: Number(cursor.key), mime: value.mime, bytes: value.bytes, saved_at: value.saved_at });
      cursor.continue();
    };
    request.onerror = () => reject(request.error);
  });
}

/** Ask the browser to keep what's saved even when the device runs low on space (asked once, on the first download). */
export async function keepStorage(): Promise<void> {
  try {
    if (navigator.storage?.persisted && !(await navigator.storage.persisted())) await navigator.storage.persist?.();
  } catch {
    // not supported: saved things may be cleared if the device runs out of space
  }
}

export async function storageUsed(): Promise<{ used: number; quota: number } | null> {
  try {
    const estimate = await navigator.storage?.estimate?.();
    return estimate ? { used: estimate.usage ?? 0, quota: estimate.quota ?? 0 } : null;
  } catch {
    return null;
  }
}
