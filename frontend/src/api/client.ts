import type {
  Annotation,
  ContentItem,
  VoiceList,
  CatalogLanguage,
  StartingPoint,
  WordMove,
  SearchState,
  HistoryImportReport,
  ImportHistory,
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
  AiProviders,
  WhisperSettings,
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
  FeedShelf,
  Shelf,
  WordModel,
  WordProgress,
  PodcastSearchResult,
  PodcastShow,
} from "./types";

import { flush } from "../sync/outbox";
import { offlineAnswer, remember } from "../sync/offline";
import type { Pack } from "../sync/packs";
import { getPageImage } from "../sync/packs";
import { blobUrl, OfflineError, remoteConfig, reportReachable, rpc, useSyncState, withTimeout } from "../sync/remote";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

// On the computer the API is this browser's own server. When it can't be reached (stopped, or a remote server out of
// reach) requests fail fast with ApiError(0) instead of hanging, saved answers are shown where there are some, and
// the server is checked every 15 seconds so the app picks up again by itself once it answers.
const REQUEST_MS = 20_000;
const SLOW_REQUEST_MS = 120_000; // things that legitimately take long: packs, AI answers, searches, imports
const SERVER_RECHECK_MS = 15_000;
let serverRecheck: number | null = null;

function serverLost() {
  reportReachable(false);
  if (serverRecheck !== null) return;
  serverRecheck = window.setInterval(() => {
    void fetch("/api/health", { cache: "no-store" })
      .then((r) => {
        if (!r.ok) return;
        if (serverRecheck !== null) window.clearInterval(serverRecheck);
        serverRecheck = null;
        reportReachable(true);
      })
      .catch(() => undefined);
  }, SERVER_RECHECK_MS);
}

function timeoutFor(path: string, method: string): number {
  if (/^\/api\/(packs|ai|tutor|search|imports|data|discover|level)/.test(path)) return SLOW_REQUEST_MS;
  return method === "GET" ? REQUEST_MS : SLOW_REQUEST_MS;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  if (remoteConfig()) return remoteRequest<T>(path, init);
  const method = (init?.method ?? "GET").toUpperCase();
  const controller = new AbortController();
  const outer = init?.signal;
  if (outer) outer.addEventListener("abort", () => controller.abort(), { once: true });
  let response: Response;
  try {
    response = await withTimeout(
      fetch(path, { ...init, signal: controller.signal, headers: { "Content-Type": "application/json", ...init?.headers } }),
      timeoutFor(path, method),
      () => controller.abort(),
    );
  } catch (error) {
    if (outer?.aborted) throw error; // cancelled by the page, not a connection problem
    return unreachable<T>(method, path, init?.body);
  }
  // the dev server's proxy answers 502/503/504 (or a bare 500) while the API isn't running
  const proxied = response.status >= 502 || (response.status === 500 && !response.headers.get("content-type")?.includes("json"));
  if (proxied) return unreachable<T>(method, path, init?.body);
  if (useSyncState.getState().online === false) reportReachable(true);
  if (response.status === 401 && !path.startsWith("/api/health")) {
    window.location.assign("/login"); // a Lingo OS on a server asks you to sign in (backend app/access.py)
  }
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
  const data = (await response.json()) as T;
  if (method === "GET") remember(path, data);
  return data;
}

/** The server can't be reached: answer from what's saved in this browser when possible, else fail at once. */
async function unreachable<T>(method: string, path: string, rawBody?: RequestInit["body"]): Promise<T> {
  serverLost();
  const url = new URL(path, window.location.origin);
  // reading only: pages, lists and transcripts of what's downloaded, and dictionary lookups in saved dictionaries
  if (method === "GET" || url.pathname === "/api/nlp/lookup") {
    const body = typeof rawBody === "string" ? (JSON.parse(rawBody) as Record<string, unknown>) : null;
    try {
      return (await offlineAnswer(method, url.pathname, url.searchParams, body)) as T;
    } catch {
      // nothing saved for this
    }
  }
  throw new ApiError(0, "Can't reach the Lingo OS server. Is it running?");
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
  languageCatalog: () => request<CatalogLanguage[]>("/api/languages/catalog"),
  addLanguage: (code: string, variant?: string) =>
    request<{ code: string; added: boolean; installing: boolean }>("/api/languages", { method: "POST", body: json({ code, variant }) }),
  removeLanguage: (code: string) => request<{ removed: boolean }>(`/api/languages/${encodeURIComponent(code)}`, { method: "DELETE" }),
  search: (lang: string, kind: "video" | "article", q: string) =>
    request<SearchState>("/api/search", { method: "POST", body: json({ lang, kind, q }) }),
  searchSuggest: (lang: string, kind: "video" | "article", q: string) =>
    request<{ q: string; suggestions: string[] }>(`/api/search/suggest?${new URLSearchParams({ lang, kind, q })}`),
  searchResults: (id: string) => request<SearchState>(`/api/search/${encodeURIComponent(id)}`),
  podcastShows: (lang: string) => request<{ shows: PodcastShow[] }>(`/api/podcasts?lang=${encodeURIComponent(lang)}`),
  podcastSearch: (lang: string, q: string) =>
    request<{ results: PodcastSearchResult[] }>(`/api/podcasts/search?lang=${encodeURIComponent(lang)}&q=${encodeURIComponent(q)}`),
  podcastSubscribe: (lang: string, feedUrl: string) =>
    request<PodcastShow & { added: number; collection_id: number }>("/api/podcasts/subscribe", { method: "POST", body: json({ lang, feed_url: feedUrl }) }),
  podcastUnsubscribe: (id: number) => request<{ unsubscribed: boolean }>(`/api/podcasts/${id}`, { method: "DELETE" }),
  podcastEpisodes: (id: number, offset = 0) =>
    request<{ show: PodcastShow; total: number; items: ContentItem[]; next_offset: number | null }>(`/api/podcasts/${id}/episodes?offset=${offset}`),
  podcastRefresh: (lang: string, force = false) =>
    request<{ added: number; errors: string[] }>("/api/podcasts/refresh", { method: "POST", body: json({ lang, force }) }),
  wordProgress: (id: number) => request<WordProgress>(`/api/vocab/words/${id}/progress`),
  wordModel: (lang: string) => request<WordModel>(`/api/vocab/model?lang=${encodeURIComponent(lang)}`),
  setWordModel: (prefs: Partial<WordModel["preferences"]>) =>
    request<Pick<WordModel, "preferences">>("/api/vocab/model", { method: "PUT", body: json(prefs) }),
  wordMoves: (lang: string) => request<{ at: string | null; moves: WordMove[] }>(`/api/vocab/moves?lang=${encodeURIComponent(lang)}`),
  languageStart: (code: string) => request<StartingPoint>(`/api/languages/${encodeURIComponent(code)}/start`),
  setLanguageLevel: (code: string, level: string | null) =>
    request<StartingPoint>(`/api/languages/${encodeURIComponent(code)}/level`, { method: "PUT", body: json({ level }) }),
  setLanguageExam: (code: string, exam: { exam: string; level: string; passed_on?: string } | null) =>
    request<StartingPoint>(`/api/languages/${encodeURIComponent(code)}/exam`, {
      method: "PUT",
      body: json(exam ?? { exam: null }),
    }),
  setLanguageBaseline: (code: string, hours: number) =>
    request<StartingPoint>(`/api/languages/${encodeURIComponent(code)}/baseline`, { method: "PUT", body: json({ hours }) }),
  importHistory: async (code: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    const response = await fetch(`/api/languages/${encodeURIComponent(code)}/history`, { method: "POST", body: form });
    if (!response.ok) {
      const body = (await response.json().catch(() => ({}))) as { detail?: unknown };
      throw new ApiError(response.status, typeof body.detail === "string" ? body.detail : response.statusText);
    }
    return (await response.json()) as HistoryImportReport;
  },
  importHistoryList: (code: string) => request<ImportHistory>(`/api/languages/${encodeURIComponent(code)}/history`),
  setLanguageVariant: (code: string, variant: string) =>
    request<{ variant: string }>(`/api/languages/${encodeURIComponent(code)}`, { method: "PATCH", body: json({ variant }) }),
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
  lookup: (input: { lang: string; lemma: string; reading?: string; pos?: string; forms?: string[]; record?: boolean; content_item_id?: number | null }) =>
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
    shelf: Shelf = "watch",
    opts: { state?: "all" | "watched" | "mine"; offset?: number; limit?: number } = {},
  ) =>
    request<{ total: number; items: ContentItem[] }>(
      `/api/content?lang=${encodeURIComponent(lang)}&shelf=${shelf}&state=${opts.state ?? "all"}&limit=${opts.limit ?? 120}` +
        `&offset=${opts.offset ?? 0}${q ? `&q=${encodeURIComponent(q)}` : ""}`,
    ),
  feed: (lang: string, shelf: FeedShelf, offset = 0, limit = 24) =>
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
  translation: (id: number) =>
    request<{ to: string; available: boolean; source: "youtube" | "ai" | null; reason: string | null; cues: { start_ms: number; end_ms: number; text: string }[] }>(
      `/api/content/${id}/translation?to=en`,
    ),
  job: (id: number) => request<Job>(`/api/jobs/${id}`),
  transcribe: (id: number) => request<{ job_id: number }>(`/api/content/${id}/transcribe`, { method: "POST" }),
  whisper: () => request<WhisperSettings>("/api/whisper"),
  chooseWhisper: (model: string | null) => request<WhisperSettings>("/api/whisper", { method: "PUT", body: json({ model }) }),
  recommendSeen: (ids: number[]) => request<{ counted: number }>("/api/recommend/seen", { method: "POST", body: json({ ids }) }),
  restoreBackup: async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    const response = await fetch("/api/data/import", { method: "POST", body: form });
    if (!response.ok) {
      const body = (await response.json().catch(() => ({}))) as { detail?: unknown };
      throw new ApiError(response.status, typeof body.detail === "string" ? body.detail : response.statusText);
    }
    return (await response.json()) as {
      restored: boolean;
      previous_data: string;
      downloading: string[];
      manifest: { created_at: string; languages: string[]; words: number; sessions: number };
    };
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
  aiProviders: () => request<AiProviders>("/api/ai/providers"),
  aiChoose: (body: { provider?: string; models?: Record<string, Partial<Record<"fast" | "smart", string | null>>> }) =>
    request<AiProviders>("/api/ai/choice", { method: "PUT", body: json(body) }),
  aiSaveKey: (provider: string, key: string) => request<AiProviders>("/api/ai/keys", { method: "PUT", body: json({ provider, key }) }),
  aiModels: (provider: string) => request<{ provider: string; models: string[] }>(`/api/ai/models?provider=${encodeURIComponent(provider)}`),
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
  /** The tutor's reply as it's written (laptop only: through the phone channel, replies come whole). */
  tutorSayStream: async (
    id: number,
    text: string,
    inputMode: "text" | "voice",
    onDelta: (piece: string) => void,
  ): Promise<{ user: TutorMessage; assistant: TutorMessage; simplified: boolean }> => {
    if (remoteConfig()) return api.tutorSay(id, text, inputMode);
    const response = await fetch(`/api/tutor/sessions/${id}/messages/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: json({ text, input_mode: inputMode }),
    });
    if (!response.ok || !response.body) throw new ApiError(response.status, response.statusText);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
      let end = buffer.indexOf("\n\n");
      while (end >= 0) {
        const line = buffer.slice(0, end).replace(/^data: ?/, "");
        buffer = buffer.slice(end + 2);
        end = buffer.indexOf("\n\n");
        if (!line) continue;
        const event = JSON.parse(line) as {
          delta?: string;
          error?: string;
          done?: { user: TutorMessage; assistant: TutorMessage; simplified: boolean };
        };
        if (event.delta) onDelta(event.delta);
        if (event.error) throw new ApiError(503, event.error);
        if (event.done) return event.done;
      }
      if (done) throw new ApiError(0, "The reply stopped before it was finished.");
    }
  },
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
  dailyRefresh: (lang: string) =>
    request<{ language: string; ran: boolean; date: string }>("/api/discover/daily", { method: "POST", body: json({ lang }) }),
  topUp: (lang: string, opts: { force?: boolean; shelf?: FeedShelf; atEnd?: boolean } = {}) =>
    request<PoolStatus>("/api/discover/top-up", {
      method: "POST",
      body: json({ lang, force: Boolean(opts.force), shelf: opts.shelf, at_end: Boolean(opts.atEnd) }),
    }),
  rateDifficulty: (id: number, value: number | null) =>
    request<DifficultyResult>(`/api/content/${id}/difficulty`, { method: "PUT", body: json({ value }) }),
  taste: (lang: string) => request<TasteSummary>(`/api/taste?lang=${encodeURIComponent(lang)}`),
  grammarReference: (lang: string) => request<GrammarReference>(`/api/tutor/reference/${encodeURIComponent(lang)}`),
  grammarWeakSpots: (lang: string) =>
    request<Pick<GrammarReference, "language" | "weak_spots">>(`/api/tutor/reference/${encodeURIComponent(lang)}/weak-spots`),
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
    pending = rpc("GET", path, null, null, 60_000)
      .then((r) => {
        if (r.status >= 400 || !r.b64) throw new ApiError(r.status, "media unavailable");
        return blobUrl(r.b64, r.type ?? "application/octet-stream");
      })
      .catch(async (error: unknown) => {
        const page = path.match(/^\/api\/manga\/(\d+)\/image\/(\d+)$/); // a manga page saved for offline
        const saved = page ? await getPageImage(Number(page[1]), Number(page[2])) : undefined;
        if (saved) return URL.createObjectURL(saved);
        throw error;
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
  setAddresses: (addresses: string[]) => request<SyncStatus>("/api/sync/addresses", { method: "PUT", body: json({ addresses }) }),
  pack: (itemId: number) => request<Pack>(`/api/packs/${itemId}`),
};
