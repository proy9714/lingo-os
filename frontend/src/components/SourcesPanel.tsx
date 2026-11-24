import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { api } from "../api/client";
import { useDiscoverStatus, usePool, useSources } from "../api/hooks";
import { formatDay, localDayOf } from "../lib/format";
import { Button, Chip, Panel, PanelTitle, ProgressBar, Skeleton } from "./ui";

/** Settings: where new content comes from, and the last discovery runs. */
export function SourcesPanel({ lang, languageName }: { lang: string; languageName: string }) {
  const sources = useSources(lang);
  const status = useDiscoverStatus();
  const qc = useQueryClient();
  const toggle = useMutation({
    mutationFn: (v: { id: number; enabled: boolean }) => api.setSource(v.id, v.enabled),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["sources"] }),
  });
  const run = useMutation({
    mutationFn: () => api.discoverRun(lang),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["discover-status"] }),
  });
  const pool = usePool(lang).data;
  const auto = useMutation({
    mutationFn: (enabled: boolean) => api.setDiscoverAuto(enabled),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["discover-pool"] }),
  });
  const job = status.data?.job;
  const running = job?.status === "queued" || job?.status === "running";
  useEffect(() => {
    if (job?.status === "done") {
      for (const key of [["recommend"], ["content"], ["sources"]]) void qc.invalidateQueries({ queryKey: key });
    }
  }, [job?.status, job?.id, qc]);
  const youtube = sources.data?.filter((s) => s.kind === "youtube_channel") ?? [];
  const links = sources.data?.filter((s) => s.kind !== "youtube_channel") ?? [];
  const lastRun = status.data?.runs.find((r) => r.language === lang);

  return (
    <Panel aria-labelledby="t-sources">
      <PanelTitle id="t-sources" aside={sources.data && <Chip>{sources.data.length} sources</Chip>}>
        New content · {languageName}
      </PanelTitle>
      <p className="text-sm leading-relaxed text-ink-2">
        Finds videos (YouTube channels from the Comprehensible Input Wiki and searches at your level) and articles (RSS feeds
        in <code>config/sources.yaml</code>). Only items near your level are kept; they show up on Today, Watch and Read.
      </p>
      <label className="mt-3 flex items-start gap-2.5 text-sm">
        <input
          type="checkbox"
          checked={pool?.auto ?? true}
          disabled={!pool || auto.isPending}
          onChange={(e) => auto.mutate(e.target.checked)}
          className="mt-0.5 size-4 accent-[var(--accent)]"
        />
        <span>
          Search automatically in the background when suggestions run low
          <span className="block text-xs text-ink-3">
            Below {pool?.targets.watch ?? 24} videos or {pool?.targets.read ?? 12} articles; at most every 2 hours (12 hours after
            YouTube refuses).
            {pool && ` Now: ${pool.pools.watch} videos, ${pool.pools.read} articles suggested.`}
          </span>
        </span>
      </label>
      <div className="mt-3">
        {running && job ? (
          <div>
            <ProgressBar value={job.progress} label="Looking for content" />
            <p className="mt-1.5 truncate text-xs text-ink-3">{String(job.result?.message ?? "Starting…")}</p>
          </div>
        ) : (
          <Button variant="primary" disabled={run.isPending} onClick={() => run.mutate()}>
            Find new {languageName} content now
          </Button>
        )}
      </div>
      {lastRun && (
        <div className="well mt-3 rounded-xl p-3 text-xs text-ink-2">
          Last run {formatDay(localDayOf(lastRun.started_at))}: {lastRun.added} kept of {lastRun.listed} new
          {lastRun.stopped_early && " · stopped early (YouTube asked for a sign-in; try again later)"}
          {lastRun.added_titles.length > 0 && (
            <ul className="mt-1.5 list-disc pl-4">
              {lastRun.added_titles.slice(0, 5).map((t) => (
                <li key={t}>{t}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      <details className="mt-3">
        <summary className="cursor-pointer text-sm font-semibold text-ink-2">
          YouTube channels {youtube.length > 0 && `(${youtube.filter((s) => s.enabled).length} on)`}
        </summary>
        {sources.isPending ? (
          <Skeleton className="mt-2 h-16" />
        ) : youtube.length === 0 ? (
          <p className="mt-2 text-xs text-ink-3">The wiki's channel list is read on the first run (at most once a week).</p>
        ) : (
          <ul className="mt-2 flex max-h-72 flex-col gap-1 overflow-y-auto">
            {youtube.map((s) => (
              <li key={s.id} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={s.enabled}
                  onChange={(e) => toggle.mutate({ id: s.id, enabled: e.target.checked })}
                  aria-label={`Fetch new videos from ${s.name}`}
                  className="size-4 accent-[var(--accent)]"
                />
                <a href={s.target} target="_blank" rel="noopener noreferrer" className="min-w-0 flex-1 truncate hover:underline">
                  {s.name}
                </a>
                {s.level_label && <span className="shrink-0 text-[11px] text-ink-3">{s.level_label}</span>}
              </li>
            ))}
          </ul>
        )}
      </details>
      {links.length > 0 && (
        <details className="mt-2">
          <summary className="cursor-pointer text-sm font-semibold text-ink-2">Other resources from the wiki ({links.length})</summary>
          <ul className="mt-2 flex max-h-72 flex-col gap-1 overflow-y-auto text-sm">
            {links.map((s) => (
              <li key={s.id} className="flex items-center gap-2">
                <a href={s.config.site ?? s.target} target="_blank" rel="noopener noreferrer" className="min-w-0 flex-1 truncate hover:underline">
                  {s.name}
                </a>
                {s.config.flags?.includes("paid") && <span className="text-[11px] text-ink-3">paid</span>}
                {s.level_label && <span className="text-[11px] text-ink-3">{s.level_label}</span>}
              </li>
            ))}
          </ul>
          <p className="mt-1 text-[11px] text-ink-3">Links only: these sites are never fetched by the app.</p>
        </details>
      )}
    </Panel>
  );
}
