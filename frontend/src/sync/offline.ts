// What the phone can do with no laptop in reach: read packed texts, look words up in the pack's dictionary,
// change word statuses, track time and log progress. Changes go to the outbox and sync later.
import { enqueue, ulid } from "./outbox";
import { allPacks, getPack, type Pack } from "./packs";

const CACHE = "lingo.cache.";

export function remember(path: string, data: unknown) {
  const key = cacheKey(path);
  if (!key) return;
  try {
    window.localStorage.setItem(CACHE + key, JSON.stringify(data));
  } catch {
    // storage full
  }
}

function recall(path: string): unknown {
  const key = cacheKey(path);
  if (!key) return undefined;
  try {
    const raw = window.localStorage.getItem(CACHE + key);
    return raw ? JSON.parse(raw) : undefined;
  } catch {
    return undefined;
  }
}

// Responses worth keeping for offline use.
function cacheKey(path: string): string | null {
  if (path === "/api/settings" || path === "/api/languages") return path;
  if (path.startsWith("/api/stats/today")) return path;
  if (path.startsWith("/api/level/") && path.endsWith("/overview")) return path;
  return null;
}

function itemOf(pack: Pack) {
  return {
    ...pack.item,
    source: "pack",
    url: null,
    external_id: null,
    local_path: null,
    duration_sec: null,
    status: "in_progress",
    progress: 0,
    position_ref: null,
    analysis_status: "done",
    last_opened_at: pack.saved_at ?? null,
    metadata: { offline: true },
    times_watched: 0,
    last_watched_at: null,
    transcript_kind: null,
    expected_unknown: null,
    band: null,
    speech_wpm: null,
  };
}

const sessions = new Map<string, { started_at: string; seconds: number }>();

export async function offlineAnswer(method: string, path: string, query: URLSearchParams, body: Record<string, unknown> | null): Promise<unknown> {
  const cached = method === "GET" ? recall(path + (query.toString() ? `?${query}` : "")) ?? recall(path) : undefined;
  if (cached !== undefined) return cached;

  let m: RegExpMatchArray | null;
  if (method === "GET" && path === "/api/content") {
    const mine = (await allPacks()).filter((p) => p.item.language === query.get("lang"));
    const shelf = query.get("shelf");
    const packs = mine.filter((p) => (shelf === "manga" ? p.kind === "manga" : p.kind === "text"));
    return shelf === "read" || shelf === "manga" ? { total: packs.length, items: packs.map(itemOf) } : { total: 0, items: [] };
  }
  if (method === "GET" && (m = path.match(/^\/api\/content\/(\d+)$/))) {
    const pack = await getPack(Number(m[1]));
    if (pack) return itemOf(pack);
  }
  if (method === "GET" && (m = path.match(/^\/api\/content\/(\d+)\/pages$/))) {
    const pack = await getPack(Number(m[1]));
    if (pack) return { total: pack.pages.length, pages: pack.pages.map((p) => ({ n: p.n, title: p.title })) };
  }
  if (method === "GET" && (m = path.match(/^\/api\/content\/(\d+)\/page\/(\d+)$/))) {
    const pack = await getPack(Number(m[1]));
    if (pack && pack.kind === "text") {
      const n = Math.max(1, Math.min(pack.pages.length, Number(m[2])));
      const page = pack.pages[n - 1];
      return { item: itemOf(pack), page: n, pages: pack.pages.length, title: page.title, paragraphs: page.paragraphs, summary: null };
    }
  }
  if (method === "GET" && (m = path.match(/^\/api\/manga\/(\d+)\/page\/(\d+)$/))) {
    const pack = await getPack(Number(m[1]));
    if (pack?.kind === "manga" && pack.manga_pages?.length) {
      const pages = pack.manga_pages;
      const n = Math.max(1, Math.min(pages.length, Number(m[2])));
      const page = pages[n - 1];
      return { item: itemOf(pack), page: page.page, pages: pages.length, width: page.width, height: page.height, ocr: page.ocr, blocks: page.blocks, summary: null };
    }
  }
  if (method === "GET" && (m = path.match(/^\/api\/manga\/(\d+)\/vocab$/))) return { item_id: Number(m[1]), total_unknown: 0, words: [] };
  if (method === "GET" && path === "/api/recommend") return { language: query.get("lang"), available: 0, picks: [] };
  if (method === "GET" && path === "/api/ai/status") {
    const off = { enabled: false, reason: "offline", local_only: false };
    return { context: off, grammar: off };
  }

  if (method === "POST" && path === "/api/nlp/lookup" && body) {
    const lang = String(body.lang);
    const key = `${body.lemma}|${body.reading ?? ""}`;
    const entries = [];
    for (const pack of await allPacks()) {
      if (pack.item.language === lang && pack.dictionary[key]) {
        entries.push(...pack.dictionary[key].map((e) => ({ ...e, note: null, dictionary: "offline pack", via: false })));
        break;
      }
    }
    if (body.record) enqueue("lookup", { lang, lemma: body.lemma, reading: body.reading ?? "", pos: body.pos ?? "", forms: body.forms ?? [] });
    return { lemma: body.lemma, reading: body.reading ?? "", pos: body.pos ?? "", rank: null, model_p: null, state: null, contexts: [], entries, inflections: [] };
  }
  if (method === "POST" && path === "/api/vocab/status" && body) {
    enqueue("word_status", { ...body }, `${body.lang}|${body.lemma}|${body.reading ?? ""}`, true);
    return { lexeme_id: 0, language: body.lang, lemma: body.lemma, reading: body.reading ?? "", status: body.status, saved: Boolean(body.save), p_known: null, lookups: 0, queued: true };
  }
  if (method === "POST" && path === "/api/activity/heartbeat" && body) {
    const id = String(body.session);
    const now = new Date().toISOString();
    const entry = sessions.get(id) ?? { started_at: now, seconds: 0 };
    entry.seconds += Number(body.seconds) || 0;
    sessions.set(id, entry);
    enqueue(
      "activity",
      { client_uuid: id, lang: body.lang, activity: body.activity, started_at: entry.started_at, ended_at: now, active_seconds: entry.seconds, content_item_id: body.content_item_id ?? null },
      id,
      true,
    );
    return { session_id: 0, active_seconds: entry.seconds };
  }
  if (method === "POST" && path === "/api/activity/stop") return { stopped: true };
  if (method === "POST" && path === "/api/activity/manual" && body) {
    const minutes = Number(body.minutes) || 0;
    const end = new Date();
    const start = new Date(end.getTime() - minutes * 60_000);
    const id = ulid();
    enqueue("activity", { client_uuid: id, lang: body.language, activity: body.activity, started_at: start.toISOString(), ended_at: end.toISOString(), active_seconds: minutes * 60, title: body.title ?? null, manual: true }, id);
    return { client_uuid: id, minutes, date: end.toISOString().slice(0, 10) };
  }
  if (method === "POST" && (m = path.match(/^\/api\/content\/(\d+)\/read-progress$/)) && body) {
    enqueue("progress", { content_item_id: Number(m[1]), page: body.page, total: body.total }, m[1], true);
    return { ok: true };
  }
  throw new Error("You're offline: this needs the laptop on the same Wi-Fi.");
}
