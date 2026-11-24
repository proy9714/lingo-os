// Offline packs on the phone, kept in IndexedDB (they can be several megabytes; localStorage is too small).
import type { AnnotatedToken } from "../api/types";

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
  dictionary: Record<string, { term: string; reading: string; pos: string[]; glosses: string[] }[]>;
  saved_at?: string;
}

const DB = "lingo-packs";
const STORE = "packs";

function db(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function run<T>(mode: IDBTransactionMode, action: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const database = await db();
  return new Promise((resolve, reject) => {
    const request = action(database.transaction(STORE, mode).objectStore(STORE));
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

export const savePack = (pack: Pack) => run("readwrite", (s) => s.put({ ...pack, saved_at: new Date().toISOString() }, pack.item.id));
export const getPack = (id: number) => run<Pack | undefined>("readonly", (s) => s.get(id));
export const deletePack = (id: number) => run("readwrite", (s) => s.delete(id));
export const allPacks = () => run<Pack[]>("readonly", (s) => s.getAll());
