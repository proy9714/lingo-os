import { Link, Outlet, useRouterState } from "@tanstack/react-router";
import { useEffect } from "react";

import { useActiveLanguage, useLanguages, useSearchWatcher, useSettings, useToday, useUpdateSettings, useVoices } from "../api/hooks";
import { onSpeechUnavailable, setSpeechEngine, setSpeechLocales } from "../lib/speech";
import { FirstRun } from "./FirstRun";
import { PhoneWelcome } from "./PhoneWelcome";
import { isNativeApp, remoteConfig, useSyncState } from "../sync/remote";
import { usePhoneSync } from "../sync/useSync";
import { useLookupStore } from "../state/lookup";
import { useTrackerStore } from "../state/tracker";
import { useUi } from "../state/ui";
import { Icon } from "./Icon";
import { LookupPanel } from "./LookupPanel";
import { Logo } from "./Logo";
import { navFor } from "./nav";
import { QuickLogModal } from "./QuickLogModal";
import { SearchPill } from "./Suggestions";
import { Toast } from "./Toast";
import { Button, cx } from "./ui";

/** "#f5b443" → "rgb(245 180 67 / 0.18)" */
function tint(hex: string, alpha: number): string {
  const n = Number.parseInt(hex.replace("#", ""), 16);
  return `rgb(${(n >> 16) & 255} ${(n >> 8) & 255} ${n & 255} / ${alpha})`;
}

/**
 * First run: the Android app starts by pairing with a computer (PhoneWelcome); a computer, or a phone paired with a
 * computer that has no language yet, starts by choosing one (FirstRun).
 */
export function AppShell() {
  if (isNativeApp() && !remoteConfig()) return <PhoneWelcome />;
  return <SetupGate />;
}

function SetupGate() {
  const settings = useSettings();
  const languages = useLanguages();
  if (settings.isPending || languages.isPending) return <div className="min-h-dvh bg-canvas" aria-busy="true" />;
  if (languages.isSuccess && languages.data.length === 0) return <FirstRun />;
  return <Shell />;
}

function Shell() {
  const { code, languages } = useActiveLanguage();
  const active = languages.find((l) => l.code === code);
  const openQuickLog = useUi((s) => s.openQuickLog);
  const lookupOpen = useLookupStore((s) => s.selection !== null);
  const closeLookup = useLookupStore((s) => s.close);
  usePhoneSync();
  const showToast = useUi((s) => s.showToast);
  const engine = useVoices(code).data?.engine;
  useEffect(() => {
    if (engine) setSpeechEngine(engine);
  }, [engine]);
  useEffect(() => onSpeechUnavailable((_lang, reason) => showToast(reason)), [showToast]);
  const pathname = useRouterState({ select: (s) => s.location.pathname });

  useEffect(() => {
    const root = document.documentElement;
    root.dataset.lang = code;
    if (active) {
      // each language tints the app with its own colour
      root.style.setProperty("--accent", active.accent_color);
      root.style.setProperty("--accent-ink", active.accent_ink);
      root.style.setProperty("--glow-1", tint(active.accent_color, 0.2));
    }
    closeLookup(); // a lookup belongs to the language it was opened in
  }, [code, active, closeLookup]);
  useEffect(() => {
    setSpeechLocales(Object.fromEntries(languages.map((l) => [l.code, l.locale])));
  }, [languages]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "l") {
        event.preventDefault();
        openQuickLog();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [openQuickLog]);

  return (
    <div className="relative min-h-dvh">
      <div className="ambient" aria-hidden="true" />
      <a
        href="#main"
        className="sr-only z-50 rounded-lg bg-accent px-3 py-2 text-accent-ink focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
      >
        Skip to content
      </a>
      <div className="shell-pad relative mx-auto flex max-w-[1480px] gap-4">
        <SideRail />
        <div className={cx("flex min-w-0 flex-1 flex-col gap-4 transition-[margin]", lookupOpen && "md:mr-[396px]")}>
          <TopBar />
          <main id="main" className="min-w-0">
            <div key={pathname} className="anim-page">
              <Outlet />
            </div>
          </main>
        </div>
      </div>
      <BottomNav />
      <QuickLogModal />
      <LookupPanel />
      <Toast />
    </div>
  );
}

const railLink =
  "flex w-[72px] flex-col items-center gap-1 rounded-xl py-2.5 text-[11px] font-medium text-ink-2 transition hover:bg-white/6 hover:text-ink data-[status=active]:bg-white/12 data-[status=active]:font-semibold data-[status=active]:text-white data-[status=active]:shadow-[inset_0_0_0_1px_rgb(255_255_255/0.16)]";

function SideRail() {
  const { code } = useActiveLanguage();
  return (
    <nav
      aria-label="Main"
      className="glass sticky top-[calc(var(--inset-top)+1rem)] hidden h-[calc(100dvh-2rem-var(--inset-top))] w-[88px] shrink-0 flex-col items-center gap-1.5 overflow-x-hidden overflow-y-auto rounded-[20px] py-4 [scrollbar-width:none] md:flex [&::-webkit-scrollbar]:hidden"
    >
      <Link to="/" aria-label="Lingo OS: Today" className="mb-3 rounded-[11px] transition hover:scale-105">
        <Logo size={40} />
      </Link>
      {navFor(code).map((item) => (
        <Link key={item.to} to={item.to} activeOptions={{ exact: item.to === "/" }} className={railLink}>
          <Icon name={item.icon} />
          <span>{item.label}</span>
        </Link>
      ))}
    </nav>
  );
}

function BottomNav() {
  const { code } = useActiveLanguage();
  return (
    <nav
      aria-label="Main"
      className="bottom-nav fixed z-30 flex gap-1 overflow-x-auto rounded-[22px] p-1.5 [scrollbar-width:none] md:hidden [&::-webkit-scrollbar]:hidden"
    >
      {navFor(code).map((item) => (
        <Link
          key={item.to}
          to={item.to}
          activeOptions={{ exact: item.to === "/" }}
          className={cx(railLink, "min-w-[64px] flex-1")}
        >
          <Icon name={item.icon} size={20} />
          <span>{item.label}</span>
        </Link>
      ))}
    </nav>
  );
}

function TopBar() {
  const openQuickLog = useUi((s) => s.openQuickLog);
  const { code } = useActiveLanguage();
  const pool = useSearchWatcher(code);
  return (
    <header className="glass flex flex-wrap items-center gap-2.5 rounded-[18px] p-2.5 md:gap-3 md:p-3">
      <LanguageSwitcher />
      <div className="flex-1" />
      <SearchPill pool={pool.data} />
      <SyncBadge />
      <TimerPill />
      <Button variant="secondary" onClick={openQuickLog} aria-keyshortcuts="Control+L" title="Log offline time (Ctrl+L)">
        <Icon name="plus" size={18} />
        <span>
          Log <span className="hidden sm:inline">time</span>
        </span>
      </Button>
    </header>
  );
}

function LanguageSwitcher() {
  const { code, languages } = useActiveLanguage();
  const update = useUpdateSettings();
  const choose = (next: string) => next !== code && update.mutate({ active_language: next });
  if (languages.length > 4) {
    const active = languages.find((l) => l.code === code);
    return (
      <label className="flex items-center gap-2 rounded-xl bg-black/30 p-1 pr-2">
        <span className="flex h-9 min-w-12 items-center justify-center rounded-[9px] bg-accent px-2 text-[13px] font-bold text-accent-ink">
          {code.toUpperCase()}
        </span>
        <span className="sr-only">Language</span>
        <select
          value={code}
          onChange={(e) => choose(e.target.value)}
          className="min-h-9 max-w-[160px] rounded-lg bg-transparent text-sm font-semibold text-ink outline-none"
          title={active ? `${active.name} · ${active.native_name}` : undefined}
        >
          {languages.map((lang) => (
            <option key={lang.code} value={lang.code} className="bg-surface">
              {lang.name} · {lang.native_name}
            </option>
          ))}
        </select>
      </label>
    );
  }
  return (
    <div role="group" aria-label="Language" className="flex gap-1 rounded-xl bg-black/30 p-1">
      {languages.map((lang) => {
        const active = lang.code === code;
        return (
          <button
            key={lang.code}
            type="button"
            aria-pressed={active}
            title={`${lang.name} · ${lang.native_name}`}
            onClick={() => choose(lang.code)}
            className={cx(
              "h-9 min-w-12 rounded-[9px] px-2 text-[13px] transition",
              active ? "bg-accent font-bold text-accent-ink" : "font-semibold text-ink-2 hover:bg-white/8 hover:text-ink",
            )}
          >
            {lang.code.toUpperCase()}
          </button>
        );
      })}
      <Link
        to="/settings"
        hash="languages"
        title="Add a language"
        aria-label="Add a language"
        className="flex h-9 w-8 items-center justify-center rounded-[9px] text-ink-3 transition hover:bg-white/8 hover:text-ink"
      >
        <Icon name="plus" size={16} />
      </Link>
    </div>
  );
}

function TimerPill() {
  const { code } = useActiveLanguage();
  const today = useToday(code).data;
  const tracker = useTrackerStore();
  const done = today ? today.today_minutes : 0;
  const goal = today?.goal_minutes ?? 60;
  const dot = tracker.active
    ? "bg-emerald-400 shadow-[0_0_0_4px_rgb(52_211_153/0.2)]"
    : done >= goal
      ? "bg-emerald-400"
      : done > 0
        ? "bg-accent"
        : "bg-gray-500";
  const mm = String(Math.floor(tracker.seconds / 60)).padStart(2, "0");
  const ss = String(tracker.seconds % 60).padStart(2, "0");
  return (
    <div
      role="status"
      aria-live="off"
      className="flex h-11 items-center gap-2 rounded-full border border-white/10 bg-black/30 px-3.5 text-[13px] text-ink-2"
    >
      <span aria-hidden="true" className={cx("size-2 rounded-full", dot)} />
      {tracker.label && (tracker.active || tracker.seconds > 0) && (
        <span className="hidden sm:inline">
          {tracker.label} <strong className="text-ink tabular-nums">{mm}:{ss}</strong> ·
        </span>
      )}
      <span>
        Today <strong className="text-ink">{done}</strong> / {goal} min
      </span>
    </div>
  );
}

/** On the phone only: offline, or changes waiting to sync. */
function SyncBadge() {
  const { online, pending } = useSyncState();
  if (!remoteConfig() || (online !== false && pending === 0)) return null;
  return (
    <Link
      to="/connect"
      className="rounded-full bg-orange-400/15 px-3 py-1.5 text-xs font-semibold text-warn"
      title="Phone sync"
    >
      {online === false ? "Offline" : "Syncing"}
      {pending > 0 && ` · ${pending} to sync`}
    </Link>
  );
}
