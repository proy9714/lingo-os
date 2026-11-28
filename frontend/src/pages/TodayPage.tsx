import { Link } from "@tanstack/react-router";
import { useMemo } from "react";

import {
  useActiveLanguage,
  useFeed,
  useLevelOverview,
  useOverview,
  usePool,
  useRecent,
  useRecommend,
  useSetLevel,
  useStartingPoint,
  useReports,
  useToday,
  useTopUp,
  useUpdateSettings,
} from "../api/hooks";
import type { LanguageOverview, PoolStatus, RecentSession, TodayStats, UpNextPick } from "../api/types";
import { FeaturedCard, PickRow } from "../components/cards";
import { Spinner, SuggestionRow, relativeTime } from "../components/Suggestions";
import { LevelChips } from "../components/StartingPoint";
import { TasteCard } from "../components/TasteCard";
import { WordMovesCard } from "../components/WordMovesCard";
import { useStableOrder } from "../lib/stableOrder";
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
    <div className="flex flex-col gap-8">
      <header className="flex flex-wrap items-end justify-between gap-4 px-1 pt-1">
        <div>
          <h1 lang={code} className="text-[28px] font-bold tracking-tight md:text-[34px]">
            {greeting(code)}
          </h1>
          <p className="mt-1 text-sm text-ink-2">
            {formatLongToday()} · {language?.name ?? ""} · what to watch and read next, picked for your level
          </p>
        </div>
        <TodayStrip today={today.data} current={current} lang={code} />
      </header>

      <StartPrompt lang={code} languageName={language?.name ?? ""} />
      <WordMovesCard lang={code} />

      <Suggestions lang={code} />

      <section aria-labelledby="t-progress" className="flex flex-col gap-3">
        <div className="flex items-end justify-between gap-2 px-1">
          <h2 id="t-progress" className="text-xl font-bold tracking-tight">
            Your progress
          </h2>
          <Link to="/reports" className="text-sm font-semibold text-accent hover:underline">
            Weekly reports →
          </Link>
        </div>
        <div className="grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr))]">
          <GoalCard data={today.data} />
          <LevelCard data={current} languageName={language?.name} lang={code} />
          <TasteCard lang={code} />
          <WeeklyCard />
          <RecentCard sessions={recent.data} />
          <LanguagesCard
            entries={all}
            active={code}
            names={Object.fromEntries(languages.map((l) => [l.code, l.name]))}
          />
          <MonthlyCard data={current} />
        </div>
      </section>
    </div>
  );
}

/** Today at a glance, in one line: minutes against the goal, total hours, level. */
function TodayStrip({ today, current, lang }: { today: TodayStats | undefined; current: LanguageOverview | undefined; lang: string }) {
  const level = useLevelOverview(lang).data;
  const vocab = level?.profile?.measured ? level.skills.vocabulary?.result : null;
  const pill = "flex min-h-11 items-center gap-2.5 rounded-2xl border border-white/10 bg-white/[0.05] px-3.5 text-sm";
  return (
    <div className="flex flex-wrap gap-2">
      <div className={pill} title="Today's immersion against your daily goal">
        {today ? <MiniRing value={today.today_minutes} goal={today.goal_minutes} /> : <Skeleton className="size-6 rounded-full" />}
        <span>
          <strong>{today?.today_minutes ?? "–"}</strong>
          <span className="text-ink-3"> / {today?.goal_minutes ?? "–"} min today</span>
        </span>
      </div>
      <div className={pill} title="All immersion in this language, including time before tracking">
        <strong>{current ? formatHours(current.total_hours) : "–"}</strong>
        <span className="text-ink-3">total</span>
      </div>
      <Link to="/level" className={cx(pill, "transition hover:bg-white/10")} title="Your level (a range, never exact)">
        {vocab?.vocabulary ? (
          <>
            <strong>≈ {vocab.vocabulary.toLocaleString("en")}</strong>
            <span className="text-ink-3">words known</span>
          </>
        ) : current ? (
          <>
            <strong>Level {current.estimate.level}</strong>
            <span className="text-ink-3">of {current.estimate.max_level} (rough estimate)</span>
          </>
        ) : (
          "Level"
        )}
      </Link>
    </div>
  );
}

function MiniRing({ value, goal }: { value: number; goal: number }) {
  const r = 9;
  const c = 2 * Math.PI * r;
  const share = goal > 0 ? Math.min(1, value / goal) : 0;
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r={r} fill="none" stroke="rgb(255 255 255 / 0.14)" strokeWidth="4" />
      <circle
        cx="12"
        cy="12"
        r={r}
        fill="none"
        stroke={share >= 1 ? "#34d399" : "var(--accent)"}
        strokeWidth="4"
        strokeLinecap="round"
        strokeDasharray={`${Math.max(share * c, 0.01)} ${c}`}
        transform="rotate(-90 12 12)"
      />
    </svg>
  );
}

/** The top of Today: one big pick, four more beside it, then rows of videos and of things to read. */
function Suggestions({ lang }: { lang: string }) {
  const recommend = useRecommend(lang);
  const videos = useFeed(lang, "watch");
  const reading = useFeed(lang, "read");
  const pool = usePool(lang).data;
  const picks = useMemo(() => recommend.data?.picks ?? [], [recommend.data]);
  const heroIds = useMemo(() => new Set(picks.slice(0, 5).map((p) => p.id)), [picks]);
  const rest = (pages: { items: UpNextPick[] }[] | undefined) =>
    (pages?.[0]?.items ?? []).filter((p) => !heroIds.has(p.id)).slice(0, 16);
  // new finds join the end of each row instead of reshuffling it (lib/stableOrder.ts)
  const videoRow = useStableOrder(`today:${lang}:watch`, useMemo(() => rest(videos.data?.pages), [videos.data, heroIds]));
  const readRow = useStableOrder(`today:${lang}:read`, useMemo(() => rest(reading.data?.pages), [reading.data, heroIds]));

  return (
    <>
      {recommend.isPending ? (
        <div className="grid grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)]">
          <Skeleton className="min-h-[380px] rounded-[22px]" />
          <div className="flex flex-col gap-2.5">
            {Array.from({ length: 4 }, (_, n) => (
              <Skeleton key={n} className="h-[86px] rounded-2xl" />
            ))}
          </div>
        </div>
      ) : picks.length === 0 ? (
        <HeroEmpty lang={lang} pool={pool} />
      ) : (
        <section aria-labelledby="t-upnext" className="grid grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)]">
          <h2 id="t-upnext" className="sr-only">
            Up next
          </h2>
          <FeaturedCard pick={picks[0]} />
          <div className="flex flex-col gap-2.5">
            <div className="flex items-baseline justify-between gap-2 px-1">
              <h3 className="text-[13px] font-semibold tracking-[0.08em] text-ink-2 uppercase">Also up next</h3>
              <span className="text-xs text-ink-3">{recommend.data?.available} at your level</span>
            </div>
            {picks.slice(1, 5).map((pick) => (
              <PickRow key={pick.id} pick={pick} />
            ))}
            <SearchNote pool={pool} />
          </div>
        </section>
      )}

      <SuggestionRow
        title="Videos for you"
        subtitle="Never one you've already watched"
        items={videoRow}
        to="/watch"
        loading={videos.isPending}
        empty={<RowEmpty lang={lang} pool={pool} noun="videos" />}
      />
      <SuggestionRow
        title="Articles & books for you"
        subtitle="From the web and your shelf, matched to your reading level"
        items={readRow}
        to="/read"
        loading={reading.isPending}
        empty={<RowEmpty lang={lang} pool={pool} noun="articles" />}
      />
    </>
  );
}

function SearchNote({ pool }: { pool: PoolStatus | undefined }) {
  if (!pool?.searching) return null;
  return (
    <p role="status" className="flex items-center gap-2 rounded-2xl border border-accent/20 bg-accent/[0.06] px-3 py-3 text-xs text-accent">
      <Spinner /> Finding more at your level in the background…
    </p>
  );
}

function RowEmpty({ lang, pool, noun }: { lang: string; pool: PoolStatus | undefined; noun: string }) {
  const topUp = useTopUp(lang);
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-dashed border-white/14 px-4 py-6 text-sm text-ink-2">
      {pool?.searching ? (
        <span role="status" className="flex items-center gap-2 text-accent">
          <Spinner /> Looking for {noun} at your level in the background. They'll show up here.
        </span>
      ) : (
        <>
          <span>No {noun} at your level yet.</span>
          <Button disabled={topUp.isPending} onClick={() => topUp.mutate({ force: true })}>
            Find some now
          </Button>
        </>
      )}
    </div>
  );
}

function HeroEmpty({ lang, pool }: { lang: string; pool: PoolStatus | undefined }) {
  const topUp = useTopUp(lang);
  const job = pool?.job;
  return (
    <section className="relative overflow-hidden rounded-[22px] border border-white/12 bg-gradient-to-br from-accent/[0.14] via-white/[0.03] to-transparent p-6 md:p-9">
      <h2 className="text-2xl font-bold tracking-tight md:text-3xl">
        {pool?.searching ? "Finding things to watch and read…" : "Nothing new to suggest right now"}
      </h2>
      <p className="mt-2 max-w-2xl text-sm leading-relaxed text-ink-2">
        Suggestions never repeat videos you've watched (here or in your Immersion Tracker history) or things you've finished.
        {pool?.searching
          ? " New videos and articles at your level are being looked for in the background. They appear here as soon as they're found, so keep using the app meanwhile."
          : ` New ones are looked for automatically in the background${pool?.last_search_at ? ` (last search ${relativeTime(pool.last_search_at)})` : ""}. You can also add your own on Watch or Read.`}
      </p>
      {pool?.searching && job ? (
        <div className="mt-5 max-w-md">
          <ProgressBar value={job.progress} label="Search progress" />
          <p className="mt-1.5 truncate text-xs text-ink-3">{String(job.result?.message ?? "starting")}</p>
        </div>
      ) : (
        <div className="mt-5 flex flex-wrap gap-2">
          <Button variant="primary" disabled={topUp.isPending} onClick={() => topUp.mutate({ force: true })}>
            Find new content now
          </Button>
          <Link to="/read" className="inline-flex min-h-11 items-center rounded-xl px-4 text-sm font-semibold text-ink-2 hover:bg-white/8">
            Add a book or article
          </Link>
        </div>
      )}
    </section>
  );
}

/** A new language with nothing to go on yet: ask where the learner is, so suggestions fit from the start. */
function StartPrompt({ lang, languageName }: { lang: string; languageName: string }) {
  const start = useStartingPoint(lang).data;
  const setLevel = useSetLevel();
  if (!start || start.has_start) return null;
  return (
    <Panel className="glass-strong anim-in">
      <PanelTitle>Where are you in {languageName}?</PanelTitle>
      <p className="max-w-2xl text-sm leading-relaxed text-ink-2">
        Pick your level so suggestions fit you from the start. You can also add the hours you've already spent, or import a CSV
        of what you've watched, in Settings.
      </p>
      <div className="mt-4 flex flex-col gap-3">
        <LevelChips lang={lang} value={start.self_level} disabled={setLevel.isPending} onChange={(level) => setLevel.mutate({ code: lang, level })} />
        <Link to="/settings" hash="start" className="w-fit text-sm font-semibold text-accent hover:underline">
          Add past hours or import your history →
        </Link>
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
  const fromChoice = est.basis === "chosen level";
  return (
    <Panel aria-labelledby="t-level">
      <PanelTitle id="t-level" aside={<Chip tone="warn">{fromChoice ? `approximate · from ${est.start_label ?? "your level"}` : "low confidence · hours only"}</Chip>}>
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
          <dt className="text-xs text-ink-3">{fromChoice ? "Vocabulary (approx.)" : "Vocabulary prior"}</dt>
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
          {fromChoice && (
            <p className="mt-1 text-xs text-ink-3">
              Placed from the level you chose ({est.start_label}), not measured yet. Your logged hours take over once they go further.
            </p>
          )}
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
