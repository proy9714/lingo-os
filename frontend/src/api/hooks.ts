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

export const useLogManual = () => useActivityMutation(api.logManual);
export const useImportTracker = () => useActivityMutation((path?: string) => api.importTracker(path));
export const useCountFlag = () => useActivityMutation(api.countFlag);
