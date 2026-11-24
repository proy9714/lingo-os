import type {
  Annotation,
  ContentItem,
  VoiceList,
  FeedPage,
  DifficultyResult,
  GrammarReference,
  TasteSummary,
  PoolStatus,
  TutorTopic,
  CTestResult,
  CTestStart,
  DictationStep,
  Evidence,
  TranscriptData,
  AddedDocument,
  SyncStatus,
  ContentSource,
  Job,
  ReportRow,
  ScrapeRun,
  GrammarRow,
  ShadowAttempt,
  ShadowClip,
  TutorMessage,
  TutorMode,
  TutorOptions,
  TutorSession,
  TutorSessionRow,
  MangaPageData,
  MangaScanResult,
  MangaVocabWord,
  AiStatus,
  AiUsage,
  ContextGloss,
  GrammarBreakdown,
  ReaderPage,
  UpNext,
  Language,
  LevelOverview,
  LookupResult,
  ManualLogInput,
  VocabStep,
  WordDetail,
  WordListItem,
  WordState,
  WordStatus,
  Overview,
  RecentSession,
  Settings,
  SystemStatus,
  TodayStats,
  TrackerFlag,
  TrackerImportSummary,
} from "./types";

import { flush } from "../sync/outbox";
import { offlineAnswer, remember } from "../sync/offline";
import type { Pack } from "../sync/packs";
import { blobUrl, OfflineError, remoteConfig, rpc } from "../sync/remote";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  if (remoteConfig()) return remoteRequest<T>(path, init);
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) {
        detail = body.detail.map((d: { msg?: string }) => d.msg ?? "invalid value").join("; ");
      }
    } catch {
      // keep statusText
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

const json = (body: unknown): RequestInit["body"] => JSON.stringify(body);

/** On the phone: the same API, through the encrypted channel to the laptop; offline answers come from packs. */
async function remoteRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const url = new URL(path, "http://hub");
  const method = (init?.method ?? "GET").toUpperCase();
  const body = typeof init?.body === "string" ? (JSON.parse(init.body) as Record<string, unknown>) : null;
  const query = Object.fromEntries(url.searchParams);
  try {
    const result = await rpc(method, url.pathname, Object.keys(query).length ? query : null, body, url.pathname.startsWith("/api/packs") ? 180_000 : 30_000);
    if (result.status >= 400) {
      const detail = (result.json as { detail?: unknown } | undefined)?.detail;
      throw new ApiError(result.status, typeof detail === "string" ? detail : `Request failed (${result.status})`);
    }
    const data = (result.json ?? result.text) as T;
    if (method === "GET") remember(url.pathname + url.search, data);
    void flush().catch(() => undefined); // back in reach: send what was queued
    return data;
  } catch (error) {
    if (!(error instanceof OfflineError)) throw error;
    try {
      return (await offlineAnswer(method, url.pathname, url.searchParams, body)) as T;
    } catch (offline) {
      throw new ApiError(0, offline instanceof Error ? offline.message : "Offline");
    }
  }
}

export const api = {
  settings: () => request<Settings>("/api/settings"),
  patchSettings: (patch: Partial<Pick<Settings, "active_language" | "goals">>) =>
    request<Settings>("/api/settings", { method: "PATCH", body: json(patch) }),
  languages: () => request<Language[]>("/api/languages"),
  today: (lang: string) => request<TodayStats>(`/api/stats/today?lang=${encodeURIComponent(lang)}`),
  overview: () => request<Overview>("/api/stats/overview"),
  recent: (lang: string, limit = 8) =>
    request<RecentSession[]>(`/api/activity/recent?lang=${encodeURIComponent(lang)}&limit=${limit}`),
  logManual: (input: ManualLogInput) =>
    request<{ client_uuid: string; minutes: number; date: string }>("/api/activity/manual", {
      method: "POST",
      body: json(input),
    }),
  systemStatus: () => request<SystemStatus>("/api/system/status"),
  importTracker: (path?: string) =>
    request<TrackerImportSummary>("/api/imports/tracker", { method: "POST", body: json(path ? { path } : {}) }),
  trackerFlags: () => request<TrackerFlag[]>("/api/imports/tracker/flags"),
  countFlag: (entryId: string) =>
    request<{ counted: string }>(`/api/imports/tracker/flags/${encodeURIComponent(entryId)}/count`, {
      method: "POST",
    }),

  // Phase 1
  annotate: (lang: string, text: string) =>
    request<Annotation>("/api/nlp/tokenize", { method: "POST", body: json({ lang, text }) }),
  lookup: (input: { lang: string; lemma: string; reading?: string; pos?: string; forms?: string[]; record?: boolean }) =>
    request<LookupResult>("/api/nlp/lookup", { method: "POST", body: json(input) }),
  setStatus: (input: {
    lang: string;
    lemma: string;
    reading?: string;
    pos?: string;
    status: WordStatus;
    save?: boolean;
    context?: { sentence: string; surface?: string; locator?: string; content_item_id?: number };
  }) => request<WordState>("/api/vocab/status", { method: "POST", body: json(input) }),
  words: (params: { lang: string; status?: string; q?: string; limit?: number; offset?: number }) => {
    const query = new URLSearchParams(
      Object.entries(params)
        .filter(([, value]) => value !== undefined && value !== "")
        .map(([key, value]) => [key, String(value)]),
    );
    return request<{ total: number; items: WordListItem[] }>(`/api/vocab/words?${query}`);
  },
  word: (id: number) => request<WordDetail>(`/api/vocab/words/${id}`),
  patchWord: (id: number, patch: { status?: WordStatus; note?: string; gloss?: string }) =>
    request<WordState>(`/api/vocab/words/${id}`, { method: "PATCH", body: json(patch) }),
  vocabSummary: (lang: string) => request<Record<string, number>>(`/api/vocab/summary?lang=${encodeURIComponent(lang)}`),
  levelOverview: (lang: string) => request<LevelOverview>(`/api/level/${encodeURIComponent(lang)}/overview`),
  vocabTestStart: (lang: string) =>
    request<VocabStep & { assessment_id: number }>(`/api/level/${encodeURIComponent(lang)}/vocab/start`, { method: "POST" }),
  vocabTestAnswer: (id: number, itemId: number, known: boolean) =>
    request<VocabStep>(`/api/level/vocab/${id}/answer`, { method: "POST", body: json({ item_id: itemId, known }) }),
  vocabTestMeaning: (id: number, itemId: number, choice: number | null) =>
    request<VocabStep>(`/api/level/vocab/${id}/meaning`, { method: "POST", body: json({ item_id: itemId, choice }) }),
  vocabTestFinish: (id: number) => request<VocabStep>(`/api/level/vocab/${id}/finish`, { method: "POST" }),
  ctestStart: (lang: string) => request<CTestStart>(`/api/level/${encodeURIComponent(lang)}/ctest/start`, { method: "POST" }),
  ctestSubmit: (id: number, answers: Record<number, string>) =>
    request<CTestResult>(`/api/level/ctest/${id}/submit`, { method: "POST", body: json({ answers }) }),

  // Phase 2
  content: (
    lang: string,
    q = "",
    shelf: "watch" | "read" | "manga" = "watch",
    opts: { state?: "all" | "watched" | "mine"; offset?: number; limit?: number } = {},
  ) =>
    request<{ total: number; items: ContentItem[] }>(
      `/api/content?lang=${encodeURIComponent(lang)}&shelf=${shelf}&state=${opts.state ?? "all"}&limit=${opts.limit ?? 120}` +
        `&offset=${opts.offset ?? 0}${q ? `&q=${encodeURIComponent(q)}` : ""}`,
    ),
  feed: (lang: string, shelf: "watch" | "read", offset = 0, limit = 24) =>
    request<FeedPage>(`/api/feed?lang=${encodeURIComponent(lang)}&shelf=${shelf}&offset=${offset}&limit=${limit}`),
  contentItem: (id: number) => request<ContentItem>(`/api/content/${id}`),
  addYouTube: (lang: string, url: string) =>
    request<ContentItem>("/api/content/youtube", { method: "POST", body: json({ lang, url }) }),
  scanMedia: () => request<{ added: string[]; with_subtitles: number; problems: string[]; folder: string }>("/api/content/scan", { method: "POST" }),
  transcript: (id: number) => request<TranscriptData>(`/api/content/${id}/transcript`),
  fetchCaptions: (id: number) => request<ContentItem>(`/api/content/${id}/captions`, { method: "POST" }),
  evidence: (lang: string) => request<Evidence>(`/api/content/evidence?lang=${encodeURIComponent(lang)}`),
  startHistory: (lang?: string) =>
    request<{ job_id: number }>("/api/content/history/fetch", { method: "POST", body: json(lang ? { lang } : {}) }),
  heartbeat: (body: {
    lang: string;
    activity: string;
    session: string;
    seconds: number;
    content_item_id?: number;
    position_ms?: number;
    duration_ms?: number;
  }) => request<{ session_id: number; active_seconds: number }>("/api/activity/heartbeat", { method: "POST", body: json(body) }),
  stopSession: (session: string) => request<{ stopped: boolean }>("/api/activity/stop", { method: "POST", body: json({ session }) }),
  dictationStart: (lang: string) => request<DictationStep>(`/api/level/${encodeURIComponent(lang)}/dictation/start`, { method: "POST" }),
  dictationAnswer: (id: number, itemId: number, typed: string, plays: number) =>
    request<DictationStep>(`/api/level/dictation/${id}/answer`, {
      method: "POST",
      body: json({ item_id: itemId, typed, plays }),
    }),

  // Phase 3
  recommend: (lang: string, n = 12) => request<UpNext>(`/api/recommend?lang=${encodeURIComponent(lang)}&n=${n}`),
  uploadDocument: async (lang: string, file: File) => {
    const form = new FormData();
    form.append("lang", lang);
    form.append("file", file);
    const response = await fetch("/api/content/upload", { method: "POST", body: form });
    if (!response.ok) {
      const body = (await response.json().catch(() => ({}))) as { detail?: unknown };
      throw new ApiError(response.status, typeof body.detail === "string" ? body.detail : response.statusText);
    }
    return (await response.json()) as AddedDocument;
  },
  addArticle: (lang: string, url: string) =>
    request<AddedDocument>("/api/content/article", { method: "POST", body: json({ lang, url }) }),
  addText: (lang: string, title: string, text: string) =>
    request<AddedDocument>("/api/content/text", { method: "POST", body: json({ lang, title, text }) }),
  pageList: (id: number) => request<{ total: number; pages: { n: number; title: string | null }[] }>(`/api/content/${id}/pages`),
  readerPage: (id: number, page: number) => request<ReaderPage>(`/api/content/${id}/page/${page}`),
  readProgress: (id: number, page: number, total: number) =>
    request<{ ok: boolean }>(`/api/content/${id}/read-progress`, { method: "POST", body: json({ page, total }) }),
  dismiss: (id: number) => request<{ ok: boolean }>(`/api/content/${id}/dismiss`, { method: "POST" }),
  ttsVoices: (lang: string) => request<VoiceList>(`/api/tts/voices?lang=${encodeURIComponent(lang)}`),
  saveTts: (body: { engine?: "neural" | "device"; lang?: string; voice?: string }) =>
    request<{ engine: "neural" | "device" }>("/api/tts/settings", { method: "PUT", body: json(body) }),
  markWatched: (id: number, watched = true) =>
    request<ContentItem>(`/api/content/${id}/watched`, { method: "POST", body: json({ watched }) }),

  // Phase 4
  aiStatus: () => request<AiStatus>("/api/ai/status"),
  aiUsage: () => request<AiUsage>("/api/ai/usage"),
  aiTest: () => request<{ ok: boolean; provider: string; model: string }>("/api/ai/test", { method: "POST" }),
  aiGloss: (body: { lang: string; sentence: string; surface: string; lemma: string; pos?: string; reading?: string }) =>
    request<ContextGloss>("/api/ai/gloss", { method: "POST", body: json(body) }),
  aiGrammar: (lang: string, sentence: string) =>
    request<GrammarBreakdown>("/api/ai/grammar", { method: "POST", body: json({ lang, sentence }) }),

  // Phase 5
  mangaInbox: () => request<{ folder: string; ocr_available: boolean }>("/api/manga/inbox"),
  mangaScan: () => request<MangaScanResult>("/api/manga/scan", { method: "POST" }),
  mangaUpload: async (lang: string, file: File) => {
    const form = new FormData();
    form.append("lang", lang);
    form.append("file", file);
    const response = await fetch("/api/manga/upload", { method: "POST", body: form });
    if (!response.ok) {
      const body = (await response.json().catch(() => ({}))) as { detail?: unknown };
      throw new ApiError(response.status, typeof body.detail === "string" ? body.detail : response.statusText);
    }
    return (await response.json()) as MangaScanResult;
  },
  mangaPage: (id: number, page: number) => request<MangaPageData>(`/api/manga/${id}/page/${page}`),
  mangaVocab: (id: number) =>
    request<{ item_id: number; total_unknown: number; words: MangaVocabWord[] }>(`/api/manga/${id}/vocab?limit=120`),
  fixBlock: (blockId: number, lines: string[]) =>
    request<{ id: number; text: string }>(`/api/manga/blocks/${blockId}`, { method: "PUT", body: json({ lines }) }),
  mangaOcr: (id: number) => request<{ job_id: number }>(`/api/manga/${id}/ocr`, { method: "POST" }),

  // Phases 6–7
  speakingStart: (lang: string) => request<DictationStep>(`/api/level/${encodeURIComponent(lang)}/speaking/start`, { method: "POST" }),
  tutorOptions: (lang: string) => request<TutorOptions>(`/api/tutor/options?lang=${encodeURIComponent(lang)}`),
  tutorTopics: (lang: string) => request<TutorTopic[]>(`/api/tutor/recent-items?lang=${encodeURIComponent(lang)}`),
  tutorSessions: (lang: string) => request<TutorSessionRow[]>(`/api/tutor/sessions?lang=${encodeURIComponent(lang)}`),
  tutorSession: (id: number) => request<TutorSession>(`/api/tutor/sessions/${id}`),
  tutorStart: (body: { lang: string; mode: TutorMode; scenario?: string; content_item_id?: number }) =>
    request<TutorSession>("/api/tutor/sessions", { method: "POST", body: json(body) }),
  tutorSay: (id: number, text: string, inputMode: "text" | "voice") =>
    request<{ user: TutorMessage; assistant: TutorMessage; simplified: boolean }>(`/api/tutor/sessions/${id}/messages`, {
      method: "POST",
      body: json({ text, input_mode: inputMode }),
    }),
  tutorEnd: (id: number) => request<{ ended: boolean; review_job: number | null }>(`/api/tutor/sessions/${id}/end`, { method: "POST" }),
  tutorGrammar: (lang: string) => request<GrammarRow[]>(`/api/tutor/grammar?lang=${encodeURIComponent(lang)}`),
  shadowClips: (lang: string) => request<ShadowClip[]>(`/api/shadow/clips?lang=${encodeURIComponent(lang)}`),
  shadowClip: (id: number) => request<ShadowClip>(`/api/shadow/clips/${id}`),
  shadowCreate: (body: { lang: string; text: string; content_item_id?: number; cue_id?: number; start_ms?: number; end_ms?: number }) =>
    request<ShadowClip>("/api/shadow/clips", { method: "POST", body: json(body) }),
  shadowFavorite: (id: number, favorite: boolean) =>
    request<ShadowClip>(`/api/shadow/clips/${id}`, { method: "PATCH", body: json({ favorite }) }),
  shadowDelete: (id: number) => request<{ deleted: boolean }>(`/api/shadow/clips/${id}`, { method: "DELETE" }),
  shadowAttempt: async (id: number, audio: Blob, durationMs: number, heard: string) => {
    const form = new FormData();
    const type = audio.type.split(";")[0] || "audio/webm";
    form.append("audio", new File([audio], `attempt.${type.split("/")[1] ?? "webm"}`, { type }));
    form.append("duration_ms", String(durationMs));
    form.append("heard", heard);
    const response = await fetch(`/api/shadow/clips/${id}/attempts`, { method: "POST", body: form });
    if (!response.ok) {
      const body = (await response.json().catch(() => ({}))) as { detail?: unknown };
      throw new ApiError(response.status, typeof body.detail === "string" ? body.detail : response.statusText);
    }
    return (await response.json()) as ShadowAttempt;
  },

  // Phase 8
  discoverRun: (lang?: string) =>
    request<{ job_id: number }>("/api/discover/run", { method: "POST", body: json(lang ? { lang } : {}) }),
  discoverStatus: () => request<{ job: Job | null; runs: ScrapeRun[] }>("/api/discover/status"),
  discoverPool: (lang: string) => request<PoolStatus>(`/api/discover/pool?lang=${encodeURIComponent(lang)}`),
  topUp: (lang: string, opts: { force?: boolean; shelf?: "watch" | "read"; atEnd?: boolean } = {}) =>
    request<PoolStatus>("/api/discover/top-up", {
      method: "POST",
      body: json({ lang, force: Boolean(opts.force), shelf: opts.shelf, at_end: Boolean(opts.atEnd) }),
    }),
  rateDifficulty: (id: number, value: number | null) =>
    request<DifficultyResult>(`/api/content/${id}/difficulty`, { method: "PUT", body: json({ value }) }),
  taste: (lang: string) => request<TasteSummary>(`/api/taste?lang=${encodeURIComponent(lang)}`),
  grammarReference: (lang: string) => request<GrammarReference>(`/api/tutor/reference/${encodeURIComponent(lang)}`),
  setDiscoverAuto: (enabled: boolean) =>
    request<{ enabled: boolean }>("/api/discover/auto", { method: "PUT", body: json({ enabled }) }),
  sources: (lang: string) => request<ContentSource[]>(`/api/sources?lang=${encodeURIComponent(lang)}`),
  setSource: (id: number, enabled: boolean) =>
    request<{ enabled: boolean }>(`/api/sources/${id}`, { method: "PATCH", body: json({ enabled }) }),
  evolveRun: (noLlm = false) => request<{ job_id: number }>("/api/evolve/run", { method: "POST", body: json({ no_llm: noLlm }) }),
  evolveStatus: () => request<{ job: Job | null }>("/api/evolve/status"),
  reports: () => request<ReportRow[]>("/api/reports"),
  reportText: async (path: string) => {
    if (remoteConfig()) return request<string>(`/api/reports/file?path=${encodeURIComponent(path)}`);
    const response = await fetch(`/api/reports/file?path=${encodeURIComponent(path)}`);
    if (!response.ok) throw new ApiError(response.status, "Could not load the report");
    return response.text();
  },
};

export const mangaImage = (id: number, page: number) => `/api/manga/${id}/image/${page}`;
export const attemptAudio = (id: number) => `/api/shadow/attempts/${id}/audio`;

/** An image or audio URL that works on the laptop (served directly) and on the phone (fetched through sync). */
const mediaCache = new Map<string, Promise<string>>();
export function mediaUrl(path: string): Promise<string> {
  if (!remoteConfig()) return Promise.resolve(path);
  let pending = mediaCache.get(path);
  if (!pending) {
    pending = rpc("GET", path, null, null, 60_000).then((r) => {
      if (r.status >= 400 || !r.b64) throw new ApiError(r.status, "media unavailable");
      return blobUrl(r.b64, r.type ?? "application/octet-stream");
    });
    pending.catch(() => mediaCache.delete(path));
    mediaCache.set(path, pending);
  }
  return pending;
}

// Phase 9: phone sync (laptop side)
export const syncApi = {
  status: () => request<SyncStatus>("/api/sync/status"),
  enable: (enabled: boolean) => request<SyncStatus>("/api/sync/enable", { method: "POST", body: json({ enabled }) }),
  pair: (name: string) =>
    request<{ device_id: string; expires: string; qr: string; addresses: string[] }>("/api/sync/pair", { method: "POST", body: json({ name }) }),
  remove: (id: string) => request<{ removed: boolean }>(`/api/devices/${encodeURIComponent(id)}`, { method: "DELETE" }),
  pack: (itemId: number) => request<Pack>(`/api/packs/${itemId}`),
};
