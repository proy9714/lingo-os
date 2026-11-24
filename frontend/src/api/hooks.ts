import { type InfiniteData, useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { api } from "./client";
import type { FeedPage, Language, Settings, UpNext } from "./types";

export const keys = {
  settings: ["settings"] as const,
  languages: ["languages"] as const,
  today: (lang: string) => ["today", lang] as const,
  overview: ["overview"] as const,
  recent: (lang: string) => ["recent", lang] as const,
  system: ["system"] as const,
  flags: ["tracker-flags"] as const,
};

/** Everything that changes when time is logged or imported. */
const ACTIVITY_KEYS = [["today"], ["overview"], ["recent"], ["tracker-flags"]];

export const useSettings = () => useQuery({ queryKey: keys.settings, queryFn: api.settings });
export const useLanguages = () => useQuery({ queryKey: keys.languages, queryFn: api.languages, staleTime: Infinity });
export const useOverview = () => useQuery({ queryKey: keys.overview, queryFn: api.overview });
export const useSystemStatus = () => useQuery({ queryKey: keys.system, queryFn: api.systemStatus });
export const useTrackerFlags = () => useQuery({ queryKey: keys.flags, queryFn: api.trackerFlags });

export const useToday = (lang: string | undefined) =>
  useQuery({
    queryKey: keys.today(lang ?? ""),
    queryFn: () => api.today(lang as string),
    enabled: Boolean(lang),
    refetchInterval: 60_000,
  });

export const useRecent = (lang: string | undefined) =>
  useQuery({ queryKey: keys.recent(lang ?? ""), queryFn: () => api.recent(lang as string), enabled: Boolean(lang) });

export interface ActiveLanguage {
  code: string;
  language: Language | undefined;
  languages: Language[];
  settings: Settings | undefined;
}

export function useActiveLanguage(): ActiveLanguage {
  const settings = useSettings().data;
  const languages = useLanguages().data ?? [];
  const code = settings?.active_language ?? "de";
  return { code, language: languages.find((l) => l.code === code), languages, settings };
}

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.patchSettings,
    onMutate: async (patch) => {
      await qc.cancelQueries({ queryKey: keys.settings });
      const previous = qc.getQueryData<Settings>(keys.settings);
      if (previous) qc.setQueryData<Settings>(keys.settings, { ...previous, ...patch, goals: { ...previous.goals, ...patch.goals } });
      return { previous };
    },
    onError: (_err, _patch, context) => {
      if (context?.previous) qc.setQueryData(keys.settings, context.previous);
    },
    onSuccess: (data) => {
      qc.setQueryData(keys.settings, data);
      void qc.invalidateQueries({ queryKey: ["today"] });
    },
  });
}

function useActivityMutation<TVars, TData>(fn: (vars: TVars) => Promise<TData>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      for (const key of ACTIVITY_KEYS) void qc.invalidateQueries({ queryKey: key });
      void qc.invalidateQueries({ queryKey: keys.settings });
    },
  });
}

// ---------------------------------------------------------------- Phase 1

/** Everything that shows word statuses. */
const WORD_KEYS = [["annotate"], ["words"], ["word"], ["vocab-summary"], ["level"], ["reader"], ["transcript"], ["manga-page"], ["manga-vocab"]];

export const useAnnotation = (lang: string, text: string) =>
  useQuery({
    queryKey: ["annotate", lang, text],
    queryFn: () => api.annotate(lang, text),
    enabled: Boolean(lang && text.trim()),
    staleTime: Infinity,
  });

export const useWords = (lang: string, status: string, q: string, limit: number) =>
  useQuery({ queryKey: ["words", lang, status, q, limit], queryFn: () => api.words({ lang, status, q, limit }) });

export const useWord = (id: number | null) =>
  useQuery({ queryKey: ["word", id], queryFn: () => api.word(id as number), enabled: id !== null });

export const useVocabSummary = (lang: string) =>
  useQuery({ queryKey: ["vocab-summary", lang], queryFn: () => api.vocabSummary(lang) });

export const useLevelOverview = (lang: string) =>
  useQuery({ queryKey: ["level", lang], queryFn: () => api.levelOverview(lang) });

function useWordMutation<TVars, TData>(fn: (vars: TVars) => Promise<TData>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      for (const key of WORD_KEYS) void qc.invalidateQueries({ queryKey: key });
    },
  });
}

export const useSetStatus = () => useWordMutation(api.setStatus);
export const usePatchWord = () =>
  useWordMutation((v: { id: number; patch: Parameters<typeof api.patchWord>[1] }) => api.patchWord(v.id, v.patch));
export const useLevelMutation = <TVars, TData>(fn: (vars: TVars) => Promise<TData>) => useWordMutation(fn);

// ---------------------------------------------------------------- Phase 2

export const useContentList = (lang: string, q: string, shelf: "watch" | "read" | "manga" = "watch") =>
  useQuery({
    queryKey: ["content", lang, q, shelf],
    queryFn: () => api.content(lang, q, shelf),
    // books are analysed in the background: poll until they're done
    refetchInterval: (query) =>
      query.state.data?.items.some((i) => i.analysis_status === "queued" || i.analysis_status === "running") ? 3000 : false,
  });

export const useContentItem = (id: number) => useQuery({ queryKey: ["content-item", id], queryFn: () => api.contentItem(id) });

export const useTranscript = (id: number) =>
  useQuery({ queryKey: ["transcript", id], queryFn: () => api.transcript(id), staleTime: 60_000 });

export const useEvidence = (lang: string) =>
  useQuery({
    queryKey: ["evidence", lang],
    queryFn: () => api.evidence(lang),
    refetchInterval: (query) => {
      const status = query.state.data?.job?.status;
      return status === "queued" || status === "running" ? 2000 : false;
    },
  });

export function useContentMutation<TVars, TData>(fn: (vars: TVars) => Promise<TData>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      for (const key of [["content"], ["content-item"], ["transcript"], ["evidence"], ["level"], ["annotate"], ["recommend"], ["feed"], ["discover-pool"]]) {
        void qc.invalidateQueries({ queryKey: key });
      }
    },
  });
}

const SUGGESTION_KEYS = [["feed"], ["recommend"], ["content"], ["content-item"], ["discover-pool"], ["taste"], ["evidence"]];

/** Take an item off every suggestion list in the cache at once, before the server answers. */
async function removeFromSuggestions(qc: ReturnType<typeof useQueryClient>, id: number) {
  await Promise.all([qc.cancelQueries({ queryKey: ["feed"] }), qc.cancelQueries({ queryKey: ["recommend"] })]);
  qc.setQueriesData<InfiniteData<FeedPage>>({ queryKey: ["feed"] }, (data) =>
    data ? { ...data, pages: data.pages.map((p) => ({ ...p, items: p.items.filter((i) => i.id !== id) })) } : data,
  );
  qc.setQueriesData<UpNext>({ queryKey: ["recommend"] }, (data) => (data ? { ...data, picks: data.picks.filter((i) => i.id !== id) } : data));
}

/** Not interested: hidden from suggestions for good. */
export function useDismiss() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.dismiss(id),
    onMutate: (id) => removeFromSuggestions(qc, id),
    onSettled: () => {
      for (const key of SUGGESTION_KEYS) void qc.invalidateQueries({ queryKey: key });
    },
  });
}

/** Mark something as already watched (or undo it). It leaves the suggestions at once and joins the Watched tab. */
export function useMarkWatched() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { id: number; watched: boolean }) => api.markWatched(v.id, v.watched),
    onMutate: async ({ id, watched }) => {
      if (watched) await removeFromSuggestions(qc, id);
    },
    onSettled: () => {
      for (const key of SUGGESTION_KEYS) void qc.invalidateQueries({ queryKey: key });
    },
  });
}

export const useLogManual = () => useActivityMutation(api.logManual);
export const useImportTracker = () => useActivityMutation((path?: string) => api.importTracker(path));
export const useCountFlag = () => useActivityMutation(api.countFlag);

// ---------------------------------------------------------------- Phase 3

export const useRecommend = (lang: string) =>
  useQuery({ queryKey: ["recommend", lang], queryFn: () => api.recommend(lang, 12), staleTime: 60_000 });

export const useReaderPage = (id: number, page: number) =>
  useQuery({ queryKey: ["reader", id, page], queryFn: () => api.readerPage(id, page), placeholderData: (previous) => previous });

export const usePageList = (id: number) => useQuery({ queryKey: ["pages", id], queryFn: () => api.pageList(id), staleTime: Infinity });

// ---------------------------------------------------------------- Phase 4

export const useAiStatus = () => useQuery({ queryKey: ["ai-status"], queryFn: api.aiStatus, staleTime: 5 * 60_000 });
export const useAiUsage = () => useQuery({ queryKey: ["ai-usage"], queryFn: api.aiUsage });

// ---------------------------------------------------------------- Phase 5

export const useMangaInbox = () => useQuery({ queryKey: ["manga-inbox"], queryFn: api.mangaInbox, staleTime: Infinity });

export const useMangaPage = (id: number, page: number) =>
  useQuery({ queryKey: ["manga-page", id, page], queryFn: () => api.mangaPage(id, page), placeholderData: (previous) => previous });

export const useMangaVocab = (id: number, enabled: boolean) =>
  useQuery({ queryKey: ["manga-vocab", id], queryFn: () => api.mangaVocab(id), enabled, staleTime: 60_000 });

// ---------------------------------------------------------------- Phases 6–7

export const useTutorOptions = (lang: string) => useQuery({ queryKey: ["tutor-options", lang], queryFn: () => api.tutorOptions(lang) });
export const useTutorSessions = (lang: string) => useQuery({ queryKey: ["tutor-sessions", lang], queryFn: () => api.tutorSessions(lang) });
export const useTutorGrammar = (lang: string) => useQuery({ queryKey: ["tutor-grammar", lang], queryFn: () => api.tutorGrammar(lang) });
export const useShadowClips = (lang: string) => useQuery({ queryKey: ["shadow-clips", lang], queryFn: () => api.shadowClips(lang) });
export const useShadowClip = (id: number | null) =>
  useQuery({ queryKey: ["shadow-clip", id], queryFn: () => api.shadowClip(id as number), enabled: id !== null });

// ---------------------------------------------------------------- Phase 8

const busy = (status?: string) => status === "queued" || status === "running";

export const useDiscoverStatus = () =>
  useQuery({
    queryKey: ["discover-status"],
    queryFn: api.discoverStatus,
    refetchInterval: (query) => (busy(query.state.data?.job?.status) ? 2500 : false),
  });

export const useEvolveStatus = () =>
  useQuery({
    queryKey: ["evolve-status"],
    queryFn: api.evolveStatus,
    refetchInterval: (query) => (busy(query.state.data?.job?.status) ? 2500 : false),
  });

export const useReports = () => useQuery({ queryKey: ["reports"], queryFn: api.reports });
export const useReportText = (path: string | null) =>
  useQuery({ queryKey: ["report", path], queryFn: () => api.reportText(path as string), enabled: Boolean(path), staleTime: Infinity });
export const useSources = (lang: string) => useQuery({ queryKey: ["sources", lang], queryFn: () => api.sources(lang) });

// ---------------------------------------------------------------- suggestions, infinite scroll, background search

const FEED_PAGE = 24;
const LIBRARY_PAGE = 36;

/** A shelf's suggestions, best first, loaded a page at a time as you scroll. */
export const useFeed = (lang: string, shelf: "watch" | "read") =>
  useInfiniteQuery({
    queryKey: ["feed", lang, shelf],
    queryFn: ({ pageParam }) => api.feed(lang, shelf, pageParam, FEED_PAGE),
    initialPageParam: 0,
    getNextPageParam: (last) => last.next_offset ?? undefined,
    staleTime: 60_000,
  });

/** The library (watched videos, your shelf), a page at a time. */
export const useLibrary = (lang: string, shelf: "watch" | "read", state: "all" | "watched" | "mine", q: string) =>
  useInfiniteQuery({
    queryKey: ["content", lang, q, shelf, state, "paged"],
    queryFn: ({ pageParam }) => api.content(lang, q, shelf, { state, offset: pageParam, limit: LIBRARY_PAGE }),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, page) => n + page.items.length, 0);
      return loaded < last.total && last.items.length > 0 ? loaded : undefined;
    },
    // books are analysed in the background: poll until they're done
    refetchInterval: (query) =>
      query.state.data?.pages.some((page) => page.items.some((i) => i.analysis_status === "queued" || i.analysis_status === "running"))
        ? 3000
        : false,
  });

/** Suggestion counts and the background search. Polls while a search runs. */
export const usePool = (lang: string) =>
  useQuery({
    queryKey: ["discover-pool", lang],
    queryFn: () => api.discoverPool(lang),
    enabled: Boolean(lang),
    refetchInterval: (query) => (query.state.data?.searching ? 3000 : 60_000),
  });

export function useTopUp(lang: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (opts: { force?: boolean; shelf?: "watch" | "read"; atEnd?: boolean }) => api.topUp(lang, opts),
    onSuccess: (data) => {
      qc.setQueryData(["discover-pool", lang], data);
      void qc.invalidateQueries({ queryKey: ["discover-status"] });
    },
  });
}

/**
 * Ask for a background top-up once per language when the app opens (the server decides if one is needed). Retried
 * until the server answers: on a cold start the page often loads before the API is up.
 */
export function useAutoTopUp(lang: string) {
  const qc = useQueryClient();
  const asked = useRef<string | null>(null);
  const topUp = useMutation({
    mutationFn: (code: string) => api.topUp(code, {}),
    retry: 8,
    retryDelay: (attempt) => Math.min(1500 * 2 ** attempt, 15_000),
    onSuccess: (data, code) => {
      qc.setQueryData(["discover-pool", code], data);
      void qc.invalidateQueries({ queryKey: ["discover-status"] });
    },
    onError: (_error, code) => {
      if (asked.current === code) asked.current = null; // try again on the next render
    },
  });
  const { mutate } = topUp;
  useEffect(() => {
    if (lang && asked.current !== lang) {
      asked.current = lang;
      mutate(lang);
    }
  }, [lang, mutate]);
}

/**
 * The background search, mounted once in the app shell: asks for a top-up as soon as the app opens (the server decides
 * if one is needed), pulls new finds into the suggestion lists while the search is still running, and refreshes
 * everything when it finishes.
 */
export function useSearchWatcher(lang: string) {
  const qc = useQueryClient();
  const pool = usePool(lang);
  useAutoTopUp(lang);
  const searching = pool.data?.searching;
  const sizes = pool.data ? `${pool.data.pools.watch}/${pool.data.pools.read}/${pool.data.estimated}` : "";
  const was = useRef(searching);
  const seen = useRef(sizes);
  const lastPull = useRef(0);

  useEffect(() => {
    if (was.current && searching === false) {
      for (const key of [["feed"], ["recommend"], ["content"], ["discover-status"]]) void qc.invalidateQueries({ queryKey: key });
    }
    was.current = searching;
  }, [searching, qc]);

  // While it runs: each time the pool grows, show the new finds (at most every 8 s, so lists don't jump constantly).
  useEffect(() => {
    if (!searching || !sizes) {
      seen.current = sizes;
      return;
    }
    if (sizes === seen.current || Date.now() - lastPull.current < 8000) return;
    seen.current = sizes;
    lastPull.current = Date.now();
    void qc.invalidateQueries({ queryKey: ["feed", lang] });
    // keep Today's big pick steady while you look at it; only fill it in when it's still empty
    const upNext = qc.getQueryData<UpNext>(["recommend", lang]);
    if (!upNext || upNext.picks.length < 5) void qc.invalidateQueries({ queryKey: ["recommend", lang] });
  }, [searching, sizes, pool.dataUpdatedAt, lang, qc]);
  return pool;
}

export const useTutorTopics = (lang: string) =>
  useQuery({ queryKey: ["tutor-topics", lang], queryFn: () => api.tutorTopics(lang), staleTime: 30_000 });

/** Rate how hard something was; the server moves your level and re-ranks suggestions. */
export function useRateDifficulty() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { id: number; value: number | null }) => api.rateDifficulty(v.id, v.value),
    onSuccess: () => {
      for (const key of [["content-item"], ["content"], ["feed"], ["recommend"], ["taste"], ["discover-pool"]]) {
        void qc.invalidateQueries({ queryKey: key });
      }
    },
  });
}

export const useTaste = (lang: string) => useQuery({ queryKey: ["taste", lang], queryFn: () => api.taste(lang), staleTime: 60_000 });

export const useGrammarReference = (lang: string) =>
  useQuery({ queryKey: ["grammar", lang], queryFn: () => api.grammarReference(lang), staleTime: Infinity, enabled: Boolean(lang) });
