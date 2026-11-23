import type {
  Annotation,
  CTestResult,
  CTestStart,
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

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
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
    context?: { sentence: string; surface?: string; locator?: string };
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
};
