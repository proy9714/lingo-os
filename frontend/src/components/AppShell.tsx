import { Link, Outlet } from "@tanstack/react-router";
import { useEffect } from "react";

import { useActiveLanguage, useToday, useUpdateSettings } from "../api/hooks";
import { useUi } from "../state/ui";
import { Icon } from "./Icon";
import { NAV } from "./nav";
import { QuickLogModal } from "./QuickLogModal";
import { Toast } from "./Toast";
import { Button, cx } from "./ui";

export function AppShell() {
  const { code } = useActiveLanguage();
  const openQuickLog = useUi((s) => s.openQuickLog);

  useEffect(() => {
    document.documentElement.dataset.lang = code;
  }, [code]);

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
      <div className="relative mx-auto flex max-w-[1480px] gap-4 p-3 pb-28 md:p-4 md:pb-6">
        <SideRail />
        <div className="flex min-w-0 flex-1 flex-col gap-4">
          <TopBar />
          <main id="main" className="min-w-0">
            <Outlet />
          </main>
        </div>
      </div>
      <BottomNav />
      <QuickLogModal />
      <Toast />
    </div>
  );
}

const railLink =
  "flex w-[72px] flex-col items-center gap-1 rounded-xl py-2.5 text-[11px] font-medium text-ink-2 transition hover:bg-white/6 hover:text-ink data-[status=active]:bg-white/12 data-[status=active]:font-semibold data-[status=active]:text-white data-[status=active]:shadow-[inset_0_0_0_1px_rgb(255_255_255/0.16)]";

function SideRail() {
  return (
    <nav
      aria-label="Main"
      className="glass sticky top-4 hidden h-[calc(100dvh-2rem)] w-[88px] shrink-0 flex-col items-center gap-1.5 overflow-y-auto rounded-[20px] py-4 md:flex"
    >
      <div
        aria-hidden="true"
        className="mb-3 flex size-9 items-center justify-center rounded-[11px] bg-accent text-base font-bold text-accent-ink"
      >
        L
      </div>
      {NAV.map((item) => (
        <Link key={item.to} to={item.to} activeOptions={{ exact: item.to === "/" }} className={railLink}>
          <Icon name={item.icon} />
          <span>{item.label}</span>
        </Link>
      ))}
    </nav>
  );
}

function BottomNav() {
  return (
    <nav
      aria-label="Main"
      className="glass-strong fixed inset-x-2 bottom-2 z-30 flex gap-1 overflow-x-auto rounded-2xl p-1.5 [scrollbar-width:none] md:hidden [&::-webkit-scrollbar]:hidden"
      style={{ paddingBottom: "max(0.375rem, env(safe-area-inset-bottom))" }}
    >
      {NAV.map((item) => (
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
  return (
    <header className="glass flex flex-wrap items-center gap-2.5 rounded-[18px] p-2.5 md:gap-3 md:p-3">
      <LanguageSwitcher />
      <div className="flex-1" />
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
            onClick={() => !active && update.mutate({ active_language: lang.code })}
            className={cx(
              "h-9 min-w-12 rounded-[9px] px-2 text-[13px] transition",
              active ? "bg-accent font-bold text-accent-ink" : "font-semibold text-ink-2 hover:bg-white/8 hover:text-ink",
            )}
          >
            {lang.code.toUpperCase()}
          </button>
        );
      })}
    </div>
  );
}

function TimerPill() {
  const { code } = useActiveLanguage();
  const today = useToday(code).data;
  const done = today ? today.today_minutes : 0;
  const goal = today?.goal_minutes ?? 60;
  const dot = done >= goal ? "bg-emerald-400" : done > 0 ? "bg-accent" : "bg-gray-500";
  return (
    <div className="flex h-11 items-center gap-2 rounded-full border border-white/10 bg-black/30 px-3.5 text-[13px] text-ink-2">
      <span aria-hidden="true" className={cx("size-2 rounded-full", dot)} />
      <span>
        Today <strong className="text-ink">{done}</strong> / {goal} min
      </span>
    </div>
  );
}
