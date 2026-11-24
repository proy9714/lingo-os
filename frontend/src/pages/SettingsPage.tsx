import { useEffect, useState } from "react";

import {
  useActiveLanguage,
  useCountFlag,
  useImportTracker,
  useSystemStatus,
  useTrackerFlags,
  useUpdateSettings,
} from "../api/hooks";
import type { TrackerImportSummary } from "../api/types";
import { Button, Chip, Panel, PanelTitle, Skeleton, cx } from "../components/ui";
import { formatDay, formatMinutes } from "../lib/format";
import { useUi } from "../state/ui";
import { AiPanel } from "../components/AiPanel";
import { PhonePanel } from "../components/PhonePanel";
import { SourcesPanel } from "../components/SourcesPanel";
import { LanguagesPanel } from "../components/LanguagesPanel";
import { StartingPointPanel } from "../components/StartingPoint";
import { VoicesPanel } from "../components/VoicesPanel";

export function SettingsPage() {
  return (
    <div className="flex flex-col gap-4">
      <header className="px-1 pt-1">
        <h1 className="text-[28px] font-bold tracking-tight">Settings</h1>
        <p className="mt-1.5 text-sm text-ink-2">Your languages, goals, voices, your Immersion Tracker history, AI explanations, and what this laptop can do.</p>
      </header>
      <div className="grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(min(100%,380px),1fr))]">
        <LanguagesPanel />
        <ActiveStartingPoint />
        <GoalsPanel />
        <TrackerPanel />
        <AiPanel />
        <VoicesPanel />
        <SourcesSection />
        <SystemPanel />
        <PhonePanel />
      </div>
    </div>
  );
}

function ActiveStartingPoint() {
  const { code, language } = useActiveLanguage();
  return code ? <StartingPointPanel key={code} lang={code} languageName={language?.name ?? code} /> : null;
}

function GoalsPanel() {
  const { languages, settings } = useActiveLanguage();
  const update = useUpdateSettings();
  const showToast = useUi((s) => s.showToast);
  const [draft, setDraft] = useState<Record<string, number>>({});

  useEffect(() => {
    if (settings) setDraft(settings.goals);
  }, [settings]);

  if (!settings) return <Skeleton className="h-64 rounded-[20px]" />;
  const changed = languages.some((l) => draft[l.code] !== settings.goals[l.code]);
  const valid = Object.values(draft).every((m) => Number.isInteger(m) && m >= 1 && m <= 720);

  return (
    <Panel aria-labelledby="t-goals">
      <PanelTitle id="t-goals">Daily goals</PanelTitle>
      <form
        className="flex flex-col gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          update.mutate({ goals: draft }, { onSuccess: () => showToast("Daily goals saved") });
        }}
      >
        {languages.map((lang) => (
          <label key={lang.code} className="well flex items-center gap-3 rounded-xl px-3 py-2">
            <span className="flex-1 text-sm">
              <span className="font-semibold">{lang.name}</span> <span className="text-ink-3">{lang.native_name}</span>
            </span>
            <input
              type="number"
              min={1}
              max={720}
              value={draft[lang.code] ?? ""}
              onChange={(e) => setDraft({ ...draft, [lang.code]: Number(e.target.value) })}
              className="min-h-11 w-24 rounded-xl border border-white/14 bg-surface px-3 text-right text-sm"
              aria-label={`${lang.name} daily goal in minutes`}
            />
            <span className="w-8 text-sm text-ink-3">min</span>
          </label>
        ))}
        {update.isError && <p className="text-sm text-red-200">{update.error.message}</p>}
        <div className="flex justify-end">
          <Button variant="primary" type="submit" disabled={!changed || !valid || update.isPending}>
            Save goals
          </Button>
        </div>
      </form>
    </Panel>
  );
}

function TrackerPanel() {
  const { settings } = useActiveLanguage();
  const importer = useImportTracker();
  const flags = useTrackerFlags();
  const countFlag = useCountFlag();
  const [result, setResult] = useState<TrackerImportSummary | null>(null);

  return (
    <Panel aria-labelledby="t-tracker">
      <PanelTitle id="t-tracker">Immersion Tracker</PanelTitle>
      <p className="text-sm leading-relaxed text-ink-2">
        Re-sync whenever your old tracker has new entries. Rows already imported are skipped, so nothing is counted twice.
      </p>
      <p className="well mt-3 truncate rounded-xl px-3 py-2 font-mono text-xs text-ink-2" title={settings?.tracker_path ?? ""}>
        {settings?.tracker_path ?? "No folder configured (set immersion_tracker.path in config/app.local.yaml)"}
      </p>
      <div className="mt-3 flex items-center gap-3">
        <Button
          variant="primary"
          disabled={importer.isPending || !settings?.tracker_path}
          onClick={() => importer.mutate(undefined, { onSuccess: setResult })}
        >
          {importer.isPending ? "Syncing…" : "Sync now"}
        </Button>
        {importer.isError && <span className="text-sm text-red-200">{importer.error.message}</span>}
      </div>

      {result && (
        <table className="mt-4 w-full text-left text-sm">
          <caption className="sr-only">Sync result</caption>
          <thead className="text-xs text-ink-3">
            <tr>
              <th className="py-1 font-medium">Language</th>
              <th className="py-1 font-medium">Status</th>
              <th className="py-1 text-right font-medium">New</th>
              <th className="py-1 text-right font-medium">Already there</th>
            </tr>
          </thead>
          <tbody>
            {result.files.map((file) => (
              <tr key={file.language} className="border-t border-white/8">
                <td className="py-1.5 font-semibold">{file.language.toUpperCase()}</td>
                <td className="py-1.5 text-ink-2">{file.status}</td>
                <td className="py-1.5 text-right">{file.imported}</td>
                <td className="py-1.5 text-right text-ink-2">{file.already_present}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {flags.data && flags.data.length > 0 && (
        <div className="mt-4 flex flex-col gap-2">
          <h3 className="text-sm font-semibold">Not counted: probable double-logs</h3>
          {flags.data.map((flag) => (
            <div key={flag.entry_id} className="well flex flex-wrap items-center gap-3 rounded-xl p-3">
              <div className="min-w-0 flex-1 text-sm">
                <div className="truncate font-medium">{flag.title}</div>
                <div className="text-xs text-ink-3">
                  {flag.language.toUpperCase()} · {formatDay(flag.date)}
                  {flag.minutes ? ` · ${formatMinutes(flag.minutes)}` : ""} · {flag.reason}
                </div>
              </div>
              <Button variant="secondary" disabled={countFlag.isPending} onClick={() => countFlag.mutate(flag.entry_id)}>
                It was a rewatch: count it
              </Button>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}

function SystemPanel() {
  const status = useSystemStatus();
  if (!status.data) return <Skeleton className="h-64 rounded-[20px]" />;
  return (
    <Panel aria-labelledby="t-system">
      <PanelTitle id="t-system" aside={<Chip tone={status.data.ok ? "good" : "warn"}>v{status.data.version}</Chip>}>
        System
      </PanelTitle>
      <ul className="flex flex-col gap-1.5">
        {status.data.checks.map((check) => (
          <li key={check.name} className="well flex items-center gap-3 rounded-xl px-3 py-2 text-sm">
            <span
              aria-hidden="true"
              className={cx("size-2 shrink-0 rounded-full", check.ok ? "bg-emerald-400" : check.required ? "bg-red-400" : "bg-amber-300")}
            />
            <span className="w-40 shrink-0 font-medium">{check.name}</span>
            <span className="min-w-0 flex-1 truncate text-ink-2" title={check.detail}>
              {check.ok ? "" : check.required ? "Problem: " : "Later: "}
              {check.detail}
            </span>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

function SourcesSection() {
  const { code, language } = useActiveLanguage();
  return <SourcesPanel lang={code} languageName={language?.name ?? code} />;
}
