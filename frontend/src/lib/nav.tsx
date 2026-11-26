import { Link, useCanGoBack, useNavigate, useRouter, useSearch } from "@tanstack/react-router";

/**
 * A page's tab, kept in the address (?tab=…) so Back, reloads and links return to the same tab.
 * The first value is the default and is left out of the address.
 */
export function useTabParam<T extends string>(values: readonly T[]): [T, (tab: T) => void] {
  const search = useSearch({ strict: false }) as { tab?: unknown };
  const navigate = useNavigate();
  const current = values.find((v) => v === search.tab) ?? values[0];
  const set = (tab: T) =>
    void navigate({
      to: ".",
      search: ((prev: Record<string, unknown>) => ({ ...prev, tab: tab === values[0] ? undefined : tab })) as never,
      replace: true,
    });
  return [current, set];
}

/**
 * "← Back" on a detail page: returns to where you came from (Today, the Watched tab, a search…) with its scroll
 * position; when the page was opened directly, it links to the section instead.
 */
export function BackLink({ to, label, className }: { to: "/watch" | "/listen" | "/read" | "/manga"; label: string; className?: string }) {
  const canGoBack = useCanGoBack();
  const router = useRouter();
  return (
    <Link
      to={to}
      className={className}
      onClick={(event) => {
        if (!canGoBack || event.metaKey || event.ctrlKey || event.shiftKey) return;
        event.preventDefault();
        router.history.back();
      }}
    >
      ← {canGoBack ? "Back" : label}
    </Link>
  );
}

const FLAG = /[\u{1F1E6}-\u{1F1FF}]{2}/gu;
const NO_FLAG_EMOJI = typeof navigator !== "undefined" && /Windows/.test(navigator.userAgent);

/** Titles as shown: Windows has no flag emoji and draws them as letters ("DE", "TR"), so they're left out there. */
export function displayTitle(title: string): string {
  return NO_FLAG_EMOJI ? title.replace(FLAG, "").replace(/\s{2,}/g, " ").trim() : title;
}
