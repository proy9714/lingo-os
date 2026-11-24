import { useEffect, useRef, useState } from "react";

import { useImportHistory, useImportHistoryList, useSetBaseline, useSetLevel, useStartingPoint } from "../api/hooks";
import type { HistoryImportReport } from "../api/types";
import { formatDay, localDayOf } from "../lib/format";
import { isNativeApp } from "../sync/remote";
import { Button, Chip, Panel, PanelTitle, ProgressBar, Skeleton, cx } from "./ui";

const CEFR: [string, string, string][] = [
  ["A0", "New to it", "You're starting from zero, or know a handful of words."],
  ["A1", "A1", "Basic phrases; you follow very slow, simple speech."],
  ["A2", "A2", "Everyday topics with simple sentences; learner videos make sense."],
  ["B1", "B1", "You follow learner content easily and the gist of slower native speech."],
  ["B2", "B2", "You follow most native content on familiar topics."],
  ["C1", "C1", "Native content is comfortable; only rare words trip you up."],
  ["C2", "C2", "Near-native: you understand practically everything."],
];
const JLPT: [string, string, string][] = [
  ["A0", "New to it", "You're starting from zero, or know kana and a few words."],
  ["N5", "N5", "Basic phrases and kana; very simple sentences."],
  ["N4", "N4", "Everyday conversation at a slow pace."],
  ["N3", "N3", "Everyday Japanese at near-natural speed."],
  ["N2", "N2", "Most native content on familiar topics."],
  ["N1", "N1", "Native content is comfortable."],
];

export const levelChoices = (lang: string) => (lang === "ja" ? JLPT : CEFR);

/** Your level today, as you'd describe it: a starting estimate until a Level Lab test measures it. */
export function LevelChips({ lang, value, onChange, disabled }: { lang: string; value: string | null; onChange: (level: string | null) => void; disabled?: boolean }) {
  return (
    <div role="radiogroup" aria-label="Your level today" className="flex flex-wrap gap-1.5">
      {levelChoices(lang).map(([id, label, hint]) => (
        <button
          key={id}
          type="button"
          role="radio"
          aria-checked={value === id}
          title={hint}
          disabled={disabled}
          onClick={() => onChange(value === id ? null : id)}
          className={cx(
            "min-h-9 rounded-full px-3 text-[13px] font-semibold transition disabled:opacity-50",
            value === id ? "bg-accent text-accent-ink" : "border border-white/14 text-ink-2 hover:bg-white/8",
          )}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

/** How the history CSV should look, what's read from it, and a template to start from. */
export function CsvFormatHelp() {
  return (
    <details className="rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-xs text-ink-2">
      <summary className="cursor-pointer font-semibold text-ink">Which CSV files work?</summary>
      <div className="mt-2 flex flex-col gap-2 leading-relaxed">
        <p>
          <strong className="text-ink">Simple format</strong>: one row per session, with a header row. Needed: <code>date</code>{" "}
          (2026-03-01, 01.03.2026 or 03/01/2026), <code>title</code> or <code>url</code>, and the time as <code>minutes</code>,{" "}
          <code>seconds</code> or <code>duration</code> (18, 1:10:00, 1h 10m). Optional: <code>channel</code>, <code>category</code>{" "}
          (video, podcast, reading, speaking, class…). Commas, semicolons or tabs.
        </p>
        <pre className="overflow-x-auto rounded-lg bg-black/40 p-2 text-[11px] text-ink">
          {"date,title,minutes,url,channel,category\n2026-03-01,Street interviews,18,https://www.youtube.com/watch?v=…,Easy German,video\n2026-03-02,Podcast episode 12,35,,,podcast"}
        </pre>
        <p>
          <strong className="text-ink">Immersion Tracker</strong> exports (<code>immersion_log_xx.csv</code>) are recognised as they are.
        </p>
        <p>
          <strong className="text-ink">What's analysed</strong>: rows with a YouTube link are looked up, and their captions in this language
          are read word by word, so the words you've heard count toward your level. Videos without captions in the language, and
          everything else (Netflix, podcasts, books, classes, rows without a link) count as time only.
        </p>
        <a href="/api/languages/history-template.csv" className="w-fit font-semibold text-accent underline" download>
          Download a template
        </a>
      </div>
    </details>
  );
}

function ImportReport({ report }: { report: HistoryImportReport }) {
  if (report.status === "unchanged") {
    return <p className="text-sm text-ink-2">This file was imported before: nothing new in it, nothing counted twice.</p>;
  }
  return (
    <div role="status" className="anim-fade rounded-xl border border-white/10 bg-white/[0.035] p-3 text-sm">
      <p className="font-semibold">
        {report.file}: {report.imported} of {report.rows} rows added
        <span className="font-normal text-ink-3"> ({report.format === "simple" ? "simple format" : "Immersion Tracker"})</span>
      </p>
      <ul className="mt-1.5 flex flex-col gap-0.5 text-ink-2">
        <li>{report.videos} YouTube video{report.videos === 1 ? "" : "s"} found: their captions are being fetched and analysed now.</li>
        <li>{report.time_only_rows} row{report.time_only_rows === 1 ? "" : "s"} without a video counted as time only.</li>
        {report.already_present > 0 && <li>{report.already_present} already imported before (not counted twice).</li>}
        {report.duplicates > 0 && <li>{report.duplicates} look like the same video logged twice: confirm them in Settings → Immersion Tracker.</li>}
      </ul>
      {report.errors.length > 0 && (
        <details className="mt-2 text-xs text-warn">
          <summary className="cursor-pointer font-semibold">{report.errors.length} row{report.errors.length === 1 ? "" : "s"} couldn't be read</summary>
          <ul className="mt-1 flex flex-col gap-0.5">
            {report.errors.slice(0, 30).map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

/** Pick a CSV and import it, then show what was read. */
export function HistoryUpload({ lang, compact = false }: { lang: string; compact?: boolean }) {
  const upload = useImportHistory();
  const input = useRef<HTMLInputElement>(null);
  if (isNativeApp()) {
    return <p className="text-xs text-ink-3">History CSVs are imported on the laptop (Settings → Your starting point).</p>;
  }
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <input
          ref={input}
          type="file"
          accept=".csv,.tsv,.txt,text/csv"
          className="sr-only"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) upload.mutate({ code: lang, file });
            e.target.value = "";
          }}
        />
        <Button className={compact ? "min-h-9 px-3" : undefined} disabled={upload.isPending} onClick={() => input.current?.click()}>
          {upload.isPending ? "Importing…" : "Import a CSV of what you've watched"}
        </Button>
      </div>
      {upload.isError && <p role="alert" className="text-sm text-red-200">{upload.error.message}</p>}
      {upload.data && <ImportReport report={upload.data} />}
      {!compact && <CsvFormatHelp />}
    </div>
  );
}

function VideoAnalysis({ lang }: { lang: string }) {
  const list = useImportHistoryList(lang).data;
  if (!list || (list.imports.length === 0 && list.videos.watched === 0)) return null;
  const job = list.job;
  const running = job?.status === "queued" || job?.status === "running";
  return (
    <div className="flex flex-col gap-2">
      <h3 className="text-sm font-semibold">Your imported history</h3>
      <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
        {(
          [
            ["Videos you watched", list.videos.watched],
            ["Analysed (words counted)", list.videos.analysed],
            ["No captions in the language", list.videos.no_captions],
            ["Waiting to be analysed", list.videos.waiting],
          ] as const
        ).map(([label, value]) => (
          <div key={label} className="well rounded-xl p-2.5">
            <dt className="text-[11px] text-ink-3">{label}</dt>
            <dd className="mt-0.5 font-semibold tabular-nums">{value.toLocaleString("en")}</dd>
          </div>
        ))}
      </dl>
      {running && job && (
        <div>
          <ProgressBar value={job.progress} label="Analysing your videos" />
          <p className="mt-1 truncate text-xs text-ink-3">{String(job.result?.message ?? "Fetching captions…")}</p>
        </div>
      )}
      {list.imports.length > 0 && (
        <ul className="flex flex-col gap-1 text-xs text-ink-2">
          {list.imports.map((b) => (
            <li key={b.id}>
              {formatDay(localDayOf(b.at))} · <span className="text-ink">{b.file}</span> · {b.imported} of {b.rows} rows added
              {b.errors > 0 && <span className="text-warn"> · {b.errors} unreadable</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Settings: your level, hours before Lingo OS, and imported history, for the active language. */
export function StartingPointPanel({ lang, languageName }: { lang: string; languageName: string }) {
  const start = useStartingPoint(lang);
  const setLevel = useSetLevel();
  const setBaseline = useSetBaseline();
  const [hours, setHours] = useState("");
  useEffect(() => {
    if (start.data) setHours(String(start.data.baseline_hours || ""));
  }, [start.data]);
  if (start.isPending) return <Skeleton className="h-64 rounded-[20px]" />;
  if (start.isError) return null;
  const data = start.data;
  const parsed = Number(hours.replace(",", "."));
  const valid = hours.trim() === "" || (Number.isFinite(parsed) && parsed >= 0 && parsed <= 20000);
  return (
    <Panel id="start" aria-labelledby="t-start" className="scroll-mt-4 [grid-column:1/-1]">
      <PanelTitle id="t-start" aside={<Chip tone={data.measured ? "good" : "neutral"}>{data.measured ? "level measured" : "starting estimate"}</Chip>}>
        Your starting point · {languageName}
      </PanelTitle>
      <div className="grid gap-6 lg:grid-cols-2">
        <div className="flex flex-col gap-4">
          <div>
            <h3 className="mb-1 text-sm font-semibold">Your level today</h3>
            <p className="mb-2 text-xs text-ink-3">
              {data.measured
                ? "Your Level Lab test result is used; this choice no longer changes your estimate."
                : "Your best guess. Suggestions start from it until a Level Lab test measures you."}
            </p>
            <LevelChips
              lang={lang}
              value={data.self_level}
              disabled={setLevel.isPending}
              onChange={(level) => setLevel.mutate({ code: lang, level })}
            />
          </div>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (valid) setBaseline.mutate({ code: lang, hours: hours.trim() === "" ? 0 : parsed });
            }}
          >
            <label htmlFor="baseline-hours" className="mb-1 block text-sm font-semibold">
              Hours before Lingo OS
            </label>
            <p className="mb-2 text-xs text-ink-3">
              Everything you did in {languageName} before using this app: watching, reading, classes, conversation.
              {data.imported_baseline_hours > 0 && ` Includes ${data.imported_baseline_hours} h from your imported history.`}
            </p>
            <div className="flex items-center gap-2">
              <input
                id="baseline-hours"
                inputMode="decimal"
                value={hours}
                onChange={(e) => setHours(e.target.value)}
                placeholder="0"
                className="min-h-10 w-28 rounded-lg border border-white/14 bg-surface px-3 text-right text-sm tabular-nums text-ink"
              />
              <span className="text-sm text-ink-3">hours</span>
              <Button className="min-h-10" type="submit" disabled={!valid || setBaseline.isPending}>
                Save
              </Button>
              {setBaseline.isSuccess && <span className="text-xs text-good">Saved</span>}
            </div>
            {setBaseline.isError && <p className="mt-1 text-xs text-red-200">{setBaseline.error.message}</p>}
            <p className="mt-2 text-xs text-ink-3">
              Tracked in Lingo OS so far: {data.tracked_hours} h
              {data.imported_session_hours > 0 && ` · from imported sessions: ${data.imported_session_hours} h`}.
            </p>
          </form>
        </div>
        <div className="flex flex-col gap-4">
          <div>
            <h3 className="mb-1 text-sm font-semibold">Import what you've watched</h3>
            <p className="mb-2 text-xs text-ink-3">
              A CSV of past sessions counts their time, and the YouTube videos in it are analysed so the words you've heard count too.
              Videos in it are never suggested again.
            </p>
            <HistoryUpload lang={lang} />
          </div>
          <VideoAnalysis lang={lang} />
        </div>
      </div>
    </Panel>
  );
}
