import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import type { Language, Settings } from "./types";

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
const WORD_KEYS = [["annotate"], ["words"], ["word"], ["vocab-summary"], ["level"]];

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

export const useContentList = (lang: string, q: string) =>
  useQuery({ queryKey: ["content", lang, q], queryFn: () => api.content(lang, q) });

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
      for (const key of [["content"], ["content-item"], ["transcript"], ["evidence"], ["level"], ["annotate"]]) {
        void qc.invalidateQueries({ queryKey: key });
      }
    },
  });
}

export const useLogManual = () => useActivityMutation(api.logManual);
export const useImportTracker = () => useActivityMutation((path?: string) => api.importTracker(path));
export const useCountFlag = () => useActivityMutation(api.countFlag);
