// Offline packs on the phone, kept in IndexedDB (they can be several megabytes; localStorage is too small).
import type { AnnotatedToken, MangaBlock } from "../api/types";

export interface PackParagraph {
  seq: number;
  text: string;
  tokens: AnnotatedToken[];
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
  };
  kind: "text" | "manga";
  pages: { n: number; title: string | null; paragraphs: PackParagraph[] }[];
  // manga packs: each page's size and text boxes; the images are kept in their own store
  manga_pages?: { page: number; width: number; height: number; ocr: string; blocks: MangaBlock[] }[];
  images?: string[];
  dictionary: Record<string, { term: string; reading: string; pos: string[]; glosses: string[] }[]>;
  saved_at?: string;
}

const DB = "lingo-packs";
const STORE = "packs";
const IMAGES = "images"; // manga page images: "<item id>/<page>" → Blob

function db(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB, 2);
    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(STORE)) database.createObjectStore(STORE);
      if (!database.objectStoreNames.contains(IMAGES)) database.createObjectStore(IMAGES);
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
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
  return run("readwrite", (s) => s.delete(id));
};
export const savePageImage = (id: number, page: number, image: Blob) => run("readwrite", (s) => s.put(image, `${id}/${page}`), IMAGES);
export const getPageImage = (id: number, page: number) => run<Blob | undefined>("readonly", (s) => s.get(`${id}/${page}`), IMAGES);
export const allPacks = () => run<Pack[]>("readonly", (s) => s.getAll());
