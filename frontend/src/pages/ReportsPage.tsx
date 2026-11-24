import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import { useEvolveStatus, useReportText, useReports } from "../api/hooks";
import { Button, Chip, Panel, PanelTitle, ProgressBar, Skeleton, cx } from "../components/ui";
import { formatDay } from "../lib/format";
import { Markdown } from "../lib/markdown";

export function ReportsPage() {
  const reports = useReports();
  const [selected, setSelected] = useState<string | null>(null);
  const report = useReportText(selected);
  const status = useEvolveStatus();
  const qc = useQueryClient();
  const run = useMutation({
    mutationFn: (noLlm: boolean) => api.evolveRun(noLlm),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["evolve-status"] }),
  });
  const job = status.data?.job;
  const running = job?.status === "queued" || job?.status === "running";

  useEffect(() => {
    if (!selected && reports.data?.length) setSelected(reports.data[0].path);
  }, [reports.data, selected]);
  useEffect(() => {
    if (job?.status === "done") {
      void qc.invalidateQueries({ queryKey: ["reports"] });
      void qc.invalidateQueries({ queryKey: ["report"] });
    }
  }, [job?.status, qc]);

  return (
    <div className="flex flex-col gap-4">
      <header className="px-1 pt-1">
        <h1 className="text-[28px] font-bold tracking-tight">Weekly reports</h1>
        <p className="mt-1.5 max-w-2xl text-sm text-ink-2">
          Every week the app measures what you did, nudges the difficulty of your picks (at most two points), updates the
          tutor's brief and writes this report. It runs on Sundays when scheduled, or whenever you press the button.
        </p>
      </header>

      <div className="grid grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
        <div className="flex flex-col gap-4">
          <Panel aria-labelledby="t-run-review">
            <PanelTitle id="t-run-review">Run it now</PanelTitle>
            {running && job ? (
              <div>
                <ProgressBar value={job.progress} label="Weekly review" />
                <p className="mt-1.5 text-xs text-ink-3">{String(job.result?.message ?? "Working…")}</p>
              </div>
            ) : (
              <div className="flex flex-col gap-2">
                <Button variant="primary" disabled={run.isPending} onClick={() => run.mutate(false)}>
                  Review the last 7 days
                </Button>
                <Button variant="ghost" disabled={run.isPending} onClick={() => run.mutate(true)}>
                  Numbers only (no AI)
                </Button>
              </div>
            )}
            {job?.status === "failed" && <p className="mt-2 text-xs text-red-200">The last run failed: {job.error?.split("\n")[0]}</p>}
          </Panel>
          <Panel aria-labelledby="t-report-list" className="p-4">
            <PanelTitle id="t-report-list">Reports</PanelTitle>
            {reports.isPending ? (
              <Skeleton className="h-24" />
            ) : !reports.data || reports.data.length === 0 ? (
              <p className="text-sm text-ink-3">No reports yet.</p>
            ) : (
              <ul className="flex flex-col gap-1.5">
                {reports.data.map((r) => (
                  <li key={r.path}>
                    <button
                      type="button"
                      onClick={() => setSelected(r.path)}
                      aria-current={selected === r.path}
                      className={cx("w-full rounded-xl px-3 py-2 text-left", selected === r.path ? "bg-accent/15" : "well hover:bg-white/10")}
                    >
                      <div className="text-sm font-semibold">
                        {formatDay(r.start)} – {formatDay(r.end)}
                      </div>
                      <div className="text-xs text-ink-3">
                        {r.minutes} min · {r.languages.map((l) => l.toUpperCase()).join(" ")}
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
        <Panel aria-label="Report">
          {!selected ? (
            <p className="text-sm text-ink-3">Your first report appears after the first weekly review.</p>
          ) : report.isPending ? (
            <Skeleton className="h-96" />
          ) : report.isError ? (
            <p className="text-sm text-red-200">{report.error.message}</p>
          ) : (
            <Markdown source={report.data} />
          )}
        </Panel>
      </div>
      <p className="px-1 text-xs text-ink-3">
        Reports are also saved as Markdown in <code>data\reports\</code>. <Chip className="px-2 py-0 text-[11px]">no flashcards</Chip>{" "}
        Saved words come back through what you watch and read, and through the tutor.
      </p>
    </div>
  );
}
