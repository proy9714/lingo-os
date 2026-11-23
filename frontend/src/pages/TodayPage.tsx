import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useEffect } from "react";

import { api } from "../api/client";
import {
  useActiveLanguage,
  useContentMutation,
  useDiscoverStatus,
  useImportTracker,
  useLevelOverview,
  useOverview,
  useRecent,
  useRecommend,
  useReports,
  useToday,
  useUpdateSettings,
} from "../api/hooks";
import type { LanguageOverview, RecentSession, TodayStats, UpNextPick } from "../api/types";
import { Button, Chip, Panel, PanelTitle, ProgressBar, Skeleton, cx } from "../components/ui";
import {
  ACTIVITY_LABELS,
  formatDay,
  formatHours,
  formatLongToday,
  formatMinutes,
  formatMonth,
  formatWeekday,
  greeting,
  localDayOf,
  todayIso,
} from "../lib/format";

export function TodayPage() {
  const { code, language, languages } = useActiveLanguage();
  const today = useToday(code);
  const overview = useOverview();
  const recent = useRecent(code);

  const all = overview.data?.languages ?? [];
  const current = all.find((entry) => entry.language === code);
  const empty = overview.isSuccess && all.every((entry) => entry.total_hours === 0);

  if (overview.isError) {
    return (
      <Panel role="alert">
        <PanelTitle>Can't reach the Lingo OS server</PanelTitle>
        <p className="text-sm text-ink-2">
          Start it with <code className="rounded bg-black/40 px-1.5 py-0.5">npm run dev</code> in the project folder, then reload.
        </p>
      </Panel>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <header className="px-1 pt-1">
        <h1 lang={code} className="text-[28px] font-bold tracking-tight md:text-3xl">
          {greeting(code)}
        </h1>
        <p className="mt-1.5 text-sm text-ink-2">
          {formatLongToday()} · {language?.name ?? ""}
        </p>
      </header>

      {empty && <ImportPrompt />}

      <div className="grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr))]">
        <GoalCard data={today.data} />
        <LevelCard data={current} languageName={language?.name} lang={code} />
        <LanguagesCard
          entries={all}
          active={code}
          names={Object.fromEntries(languages.map((l) => [l.code, l.name]))}
        />
        <UpNextCard lang={code} />
        <WeeklyCard />
        <RecentCard sessions={recent.data} />
        <MonthlyCard data={current} />
      </div>
    </div>
  );
}

function ImportPrompt() {
  const importer = useImportTracker();
  return (
    <Panel className="glass-strong">
      <PanelTitle>Bring in your history</PanelTitle>
      <p className="max-w-2xl text-sm leading-relaxed text-ink-2">
        Import your Immersion Tracker logs to fill in your hours, streak and starting level. It is safe to run again whenever
        the tracker has new entries.
      </p>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => importer.mutate(undefined)}
          disabled={importer.isPending}
          className="min-h-11 rounded-xl bg-accent px-4 text-sm font-bold text-accent-ink disabled:opacity-60"
        >
          {importer.isPending ? "Importing…" : "Import from Immersion Tracker"}
        </button>
        {importer.isError && <span className="text-sm text-red-200">{importer.error.message}</span>}
      </div>
    </Panel>
  );
}

function GoalRing({ value, goal }: { value: number; goal: number }) {
  const radius = 40;
  const circumference = 2 * Math.PI * radius;
  const share = goal > 0 ? Math.min(1, value / goal) : 0;
  return (
    <svg width="96" height="96" viewBox="0 0 96 96" role="img" aria-label={`${value} of ${goal} minutes today`}>
      <circle cx="48" cy="48" r={radius} fill="none" stroke="rgb(255 255 255 / 0.1)" strokeWidth="10" />
      <circle
        cx="48"
        cy="48"
        r={radius}
        fill="none"
        stroke={share >= 1 ? "#34d399" : "var(--accent)"}
        strokeWidth="10"
        strokeLinecap="round"
        strokeDasharray={`${Math.max(share * circumference, 0.01)} ${circumference}`}
        transform="rotate(-90 48 48)"
      />
    </svg>
  );
}

function GoalCard({ data }: { data: TodayStats | undefined }) {
  if (!data) return <Skeleton className="h-[300px] rounded-[20px]" />;
  const peak = Math.max(data.goal_minutes, ...data.last7.map((d) => d.minutes), 1);
  const chartHeight = 96;
  const goalLine = (data.goal_minutes / peak) * chartHeight;
  const today = todayIso();
  return (
    <Panel aria-labelledby="t-goal">
      <PanelTitle id="t-goal">Daily goal</PanelTitle>
      <div className="flex items-center gap-4">
        <GoalRing value={data.today_minutes} goal={data.goal_minutes} />
        <div>
          <div className="text-3xl font-bold">
            {data.today_minutes}
            <span className="text-sm font-medium text-ink-2"> / {data.goal_minutes} min</span>
          </div>
          <div className="mt-1 text-xs text-ink-2">
            {data.last_session
              ? `Last session ${formatDay(data.last_session.date)} · ${formatMinutes(data.last_session.day_minutes)} that day`
              : "No sessions yet"}
          </div>
        </div>
      </div>
      <div
        role="img"
        aria-label={`Last 7 days: ${data.last7.map((d) => `${formatWeekday(d.date)} ${d.minutes} minutes`).join(", ")}`}
        className="relative mt-5 grid grid-cols-7 items-end gap-1.5 border-b border-white/12"
        style={{ height: chartHeight }}
      >
        <div aria-hidden="true" className="absolute inset-x-0 border-t border-dashed border-accent/60" style={{ bottom: goalLine }} />
        {data.last7.map((d) => (
          <div
            key={d.date}
            className={cx("rounded-t-[4px]", d.minutes === 0 ? "bg-white/18" : d.minutes >= data.goal_minutes ? "bg-accent" : "bg-accent/70")}
            style={{ height: d.minutes === 0 ? 3 : Math.max(4, (d.minutes / peak) * chartHeight) }}
          />
        ))}
      </div>
      <div aria-hidden="true" className="mt-1.5 grid grid-cols-7 gap-1.5 text-center text-[11px] text-ink-3">
        {data.last7.map((d) => (
          <span key={d.date} className={d.date === today ? "text-ink" : undefined}>
            {d.date === today ? "Today" : formatWeekday(d.date)}
          </span>
        ))}
      </div>
    </Panel>
  );
}

function LevelCard({ data, languageName, lang }: { data: LanguageOverview | undefined; languageName: string | undefined; lang: string }) {
  const level = useLevelOverview(lang).data;
  if (!data) return <Skeleton className="h-[300px] rounded-[20px]" />;
  const vocab = level?.skills.vocabulary?.result;
  if (level?.profile?.measured && vocab?.vocabulary) {
    const reading = level.skills.reading;
    return (
      <Panel aria-labelledby="t-level">
        <PanelTitle id="t-level" aside={<Chip tone="good">measured</Chip>}>
          Your {languageName} level
        </PanelTitle>
        <div className="text-xl font-bold">≈ {vocab.vocabulary.toLocaleString("en")} words</div>
        <p className="mt-1 text-sm text-ink-2">
          90% likely {vocab.low?.toLocaleString("en")}–{vocab.high?.toLocaleString("en")}
          {vocab.band && ` · vocabulary band ≈ ${vocab.band}`}
          {vocab.jlpt && ` · JLPT ≈ ${vocab.jlpt}`}
        </p>
        <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
          <div className="well rounded-xl p-3">
            <dt className="text-xs text-ink-3">Reading</dt>
            <dd className="mt-1 font-semibold">{reading?.band ?? "not measured"}</dd>
          </div>
          <div className="well rounded-xl p-3">
            <dt className="text-xs text-ink-3">Total immersion</dt>
            <dd className="mt-1 font-semibold">{formatHours(data.total_hours)}</dd>
          </div>
        </dl>
        <Link to="/level" className="mt-4 inline-block text-sm font-semibold text-accent hover:underline">
          Open Level Lab →
        </Link>
      </Panel>
    );
  }
  const est = data.estimate;
  return (
    <Panel aria-labelledby="t-level">
      <PanelTitle id="t-level" aside={<Chip tone="warn">low confidence · hours only</Chip>}>
        Your {languageName} level
      </PanelTitle>
      <div className="text-xl font-bold">
        Roadmap level {est.level} of {est.max_level}
      </div>
      <p className="mt-1 text-sm text-ink-2">{est.level_label}</p>
      <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
        <div className="well rounded-xl p-3">
          <dt className="text-xs text-ink-3">Total immersion</dt>
          <dd className="mt-1 font-semibold">{formatHours(data.total_hours)}</dd>
        </div>
        <div className="well rounded-xl p-3">
          <dt className="text-xs text-ink-3">Vocabulary prior</dt>
          <dd className="mt-1 font-semibold">≈ {est.words_prior.toLocaleString("en")} words</dd>
        </div>
      </dl>
      {est.next_level && (
        <div className="mt-4">
          <ProgressBar value={est.progress_to_next} label={`Progress to roadmap level ${est.next_level}`} />
          <p className="mt-2 text-xs text-ink-3">
            {formatHours(est.hours_to_next_level)} to level {est.next_level}
            {est.divisor !== 1 && ` · hours count ÷${est.divisor} for difficulty (≈ ${formatHours(est.adjusted_hours)} Spanish-equivalent)`}
          </p>
        </div>
      )}
      <Link to="/level" className="mt-4 inline-block text-sm font-semibold text-accent hover:underline">
        Measure it in Level Lab (about 5 minutes) →
      </Link>
    </Panel>
  );
}

function LanguagesCard({ entries, active, names }: { entries: LanguageOverview[]; active: string; names: Record<string, string> }) {
  const update = useUpdateSettings();
  if (!entries.length) return <Skeleton className="h-[300px] rounded-[20px]" />;
  return (
    <Panel aria-labelledby="t-langs">
      <PanelTitle id="t-langs">All languages</PanelTitle>
      <ul className="flex flex-col gap-2">
        {entries.map((entry) => (
          <li key={entry.language}>
            <button
              type="button"
              onClick={() => entry.language !== active && update.mutate({ active_language: entry.language })}
              aria-current={entry.language === active ? "true" : undefined}
              className={cx(
                "well flex w-full items-center gap-3 rounded-xl p-3 text-left transition hover:bg-white/8",
                entry.language === active && "ring-1 ring-accent/60",
              )}
            >
              <span data-lang-chip={entry.language} className="w-9 text-center text-sm font-bold">
                {entry.language.toUpperCase()}
              </span>
              <span className="flex-1">
                <span className="block text-sm font-semibold">
                  {names[entry.language]} · {formatHours(entry.total_hours)}
                </span>
                <span className="block text-xs text-ink-3">
                  {formatHours(entry.baseline_hours)} before tracking · {formatHours(entry.tracked_hours)} tracked
                </span>
              </span>
              <span className="text-xs text-ink-3">
                {entry.last_session_date ? `last ${formatDay(entry.last_session_date)}` : "no sessions yet"}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

function UpNextCard({ lang }: { lang: string }) {
  const recommend = useRecommend(lang);
  const dismiss = useContentMutation((id: number) => api.dismiss(id));
  const data = recommend.data;
  return (
    <Panel aria-labelledby="t-next" className="[grid-column:1/-1]">
      <PanelTitle
        id="t-next"
        aside={data && data.picks.length > 0 && <Chip>{data.picks.length} picks from {data.available} analysed</Chip>}
      >
        Up next
      </PanelTitle>
      {recommend.isError ? (
        <p role="alert" className="text-sm text-red-200">
          Could not load picks: {recommend.error.message}
        </p>
      ) : !data ? (
        <Skeleton className="h-40" />
      ) : data.picks.length === 0 ? (
        <EmptyUpNext lang={lang} />
      ) : (
        <>
          <ol className="grid gap-2.5 [grid-template-columns:repeat(auto-fill,minmax(min(100%,300px),1fr))]">
            {data.picks.map((pick) => (
              <PickRow key={pick.id} pick={pick} onDismiss={() => dismiss.mutate(pick.id)} />
            ))}
          </ol>
          {data.picks.length < 10 && (
            <p className="mt-3 text-xs text-ink-3">
              Only {data.picks.length} analysed item{data.picks.length === 1 ? "" : "s"} so far. Add videos or books to get at least 10
              picks.
            </p>
          )}
        </>
      )}
    </Panel>
  );
}

const BAND_LABELS: Record<string, string> = {
  too_easy: "easy",
  comfortable: "comfortable",
  i_plus_1: "just right",
  stretch: "stretch",
  too_hard: "hard",
};

function PickRow({ pick, onDismiss }: { pick: UpNextPick; onDismiss: () => void }) {
  const thumb = pick.source === "youtube" && pick.external_id ? `https://i.ytimg.com/vi/${pick.external_id}/default.jpg` : null;
  const length =
    pick.kind === "manga"
      ? null
      : pick.kind === "video"
      ? pick.duration_sec
        ? `${Math.round(pick.duration_sec / 60)} min`
        : null
      : pick.word_count
        ? `${pick.word_count.toLocaleString("en")} words`
        : null;
  const target = pick.kind === "reading" ? "/read/$itemId" : pick.kind === "manga" ? "/manga/$itemId" : "/watch/$itemId";
  return (
    <li className="well group relative flex gap-3 rounded-xl p-2.5 pr-9">
      <div aria-hidden="true" className="flex h-[54px] w-[72px] shrink-0 items-center justify-center overflow-hidden rounded-lg bg-black/40">
        {thumb ? (
          <img src={thumb} alt="" loading="lazy" className="h-full w-full object-cover" />
        ) : (
          <span className="text-[10px] font-bold tracking-wider text-ink-3 uppercase">
            {pick.kind === "reading" ? "Read" : pick.kind === "manga" ? "Manga" : "Media"}
          </span>
        )}
      </div>
      <div className="min-w-0 flex-1">
        <Link
          to={target}
          params={{ itemId: String(pick.id) }}
          className="line-clamp-2 text-sm leading-snug font-semibold after:absolute after:inset-0 after:content-['']"
        >
          {pick.title}
        </Link>
        <div className="mt-1 truncate text-xs text-ink-3">
          {[pick.creator, length, pick.band ? BAND_LABELS[pick.band] : null].filter(Boolean).join(" · ")}
        </div>
        <div className="mt-1 truncate text-xs text-ink-2">{pick.reasons.join(" · ")}</div>
      </div>
      <button
        type="button"
        onClick={onDismiss}
        aria-label={`Not interested in ${pick.title}`}
        title="Not interested"
        className="absolute top-1.5 right-1.5 z-10 flex h-7 w-7 items-center justify-center rounded-lg text-ink-3 opacity-60 transition hover:bg-white/10 hover:text-ink group-hover:opacity-100 focus-visible:opacity-100"
      >
        ×
      </button>
    </li>
  );
}

function RecentCard({ sessions }: { sessions: RecentSession[] | undefined }) {
  if (!sessions) return <Skeleton className="h-[300px] rounded-[20px]" />;
  return (
    <Panel aria-labelledby="t-recent">
      <PanelTitle id="t-recent">Recent sessions</PanelTitle>
      {sessions.length === 0 ? (
        <p className="text-sm text-ink-2">Nothing logged yet in this language.</p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {sessions.map((s) => (
            <li key={s.id} className="well flex items-center gap-3 rounded-xl px-3 py-2.5">
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">{s.title || ACTIVITY_LABELS[s.activity]}</span>
                <span className="block text-xs text-ink-3">
                  {formatDay(localDayOf(s.started_at))} · {ACTIVITY_LABELS[s.activity] ?? s.activity}
                  {s.tracking === "manual" ? " · logged here" : ""}
                </span>
              </span>
              <span className="shrink-0 text-sm text-ink-2">{formatMinutes(s.minutes)}</span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function MonthlyCard({ data }: { data: LanguageOverview | undefined }) {
  if (!data) return <Skeleton className="h-[300px] rounded-[20px]" />;
  const months = data.monthly.slice(-6);
  const peak = Math.max(...months.map((m) => m.hours), 1);
  return (
    <Panel aria-labelledby="t-months">
      <PanelTitle id="t-months">Tracked hours by month</PanelTitle>
      {months.length === 0 ? (
        <p className="text-sm text-ink-2">No tracked sessions yet. Time from before tracking counts toward your total only.</p>
      ) : (
        <>
          <div
            role="img"
            aria-label={months.map((m) => `${formatMonth(m.month)} ${m.hours} hours`).join(", ")}
            className="flex h-32 items-end gap-2 border-b border-white/12"
          >
            {months.map((m) => (
              <div key={m.month} className="flex flex-1 flex-col items-center justify-end gap-1">
                <span className="text-[11px] text-ink-2">{m.hours}</span>
                <div className="w-full rounded-t-[4px] bg-accent/80" style={{ height: `${Math.max(3, (m.hours / peak) * 96)}px` }} />
              </div>
            ))}
          </div>
          <div aria-hidden="true" className="mt-1.5 flex gap-2 text-center text-[11px] text-ink-3">
            {months.map((m) => (
              <span key={m.month} className="flex-1">
                {formatMonth(m.month)}
              </span>
            ))}
          </div>
          <p className="mt-3 text-xs text-ink-3">
            {data.sessions} sessions on {data.active_days} days since {data.first_session_date ? formatDay(data.first_session_date) : "-"}
          </p>
        </>
      )}
    </Panel>
  );
}

function WeeklyCard() {
  const reports = useReports().data;
  const latest = reports?.[0];
  return (
    <Panel aria-labelledby="t-weekly">
      <PanelTitle id="t-weekly" aside={latest && <Chip tone="accent">{latest.minutes} min</Chip>}>
        Weekly report
      </PanelTitle>
      {latest ? (
        <p className="text-sm text-ink-2">
          {formatDay(latest.start)} – {formatDay(latest.end)}: what you did, what changed in your picks, and the tutor's brief
          for next week.
        </p>
      ) : (
        <p className="text-sm text-ink-2">
          The first weekly review measures your week, adjusts your picks a little and briefs the tutor.
        </p>
      )}
      <Link to="/reports" className="mt-3 inline-flex min-h-10 items-center text-sm font-semibold text-accent hover:underline">
        {latest ? "Open the report →" : "Run the first review →"}
      </Link>
    </Panel>
  );
}

/** Up Next never repeats what you've watched, so it can run dry: offer to find new content right here. */
function EmptyUpNext({ lang }: { lang: string }) {
  const status = useDiscoverStatus();
  const qc = useQueryClient();
  const run = useMutation({
    mutationFn: () => api.discoverRun(lang),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["discover-status"] }),
  });
  const job = status.data?.job;
  const running = job?.status === "queued" || job?.status === "running";
  useEffect(() => {
    if (job?.status === "done") {
      for (const key of [["recommend"], ["content"]]) void qc.invalidateQueries({ queryKey: key });
    }
  }, [job?.status, job?.id, qc]);
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm leading-relaxed text-ink-2">
        Nothing new to suggest: Up Next never repeats videos you've watched (here or in your tracker history) or things
        you've finished. Find new videos and articles at your level, or add a book on{" "}
        <Link to="/read" className="text-accent underline">
          Read
        </Link>
        .
      </p>
      {running && job ? (
        <div className="max-w-md">
          <ProgressBar value={job.progress} label="Looking for content" />
          <p className="mt-1.5 truncate text-xs text-ink-3">{String(job.result?.message ?? "Starting…")}</p>
        </div>
      ) : (
        <Button variant="primary" className="self-start" disabled={run.isPending} onClick={() => run.mutate()}>
          Find new content now
        </Button>
      )}
    </div>
  );
}
