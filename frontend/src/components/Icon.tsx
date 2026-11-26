import type { ReactNode } from "react";

export type IconName = "home" | "play" | "book" | "manga" | "mic" | "words" | "gauge" | "settings" | "plus" | "close" | "sync" | "help" | "grammar" | "check" | "download" | "headphones";

const PATHS: Record<IconName, ReactNode> = {
  home: <path d="M3 10.5 12 3l9 7.5V21h-6v-6H9v6H3z" />,
  play: (
    <>
      <rect x="3" y="5" width="18" height="14" rx="3" />
      <path d="M10 9.5v5l4.5-2.5z" />
    </>
  ),
  book: <path d="M4 5.5C4 4.7 4.7 4 5.5 4H11v16H5.5A1.5 1.5 0 0 1 4 18.5zM20 5.5c0-.8-.7-1.5-1.5-1.5H13v16h5.5c.8 0 1.5-.7 1.5-1.5z" />,
  manga: (
    <>
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <path d="M3 11h9M12 3v18M12 15h9" />
    </>
  ),
  mic: (
    <>
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
    </>
  ),
  words: (
    <>
      <path d="M5 4h10l4 4v12H5z" />
      <path d="M9 11h6M9 15h6" />
    </>
  ),
  gauge: (
    <>
      <path d="M4 18a8 8 0 1 1 16 0" />
      <path d="m12 18 4-6" />
    </>
  ),
  settings: (
    <>
      <path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1" />
      <circle cx="15" cy="6" r="2" />
      <circle cx="9" cy="12" r="2" />
      <circle cx="17" cy="18" r="2" />
    </>
  ),
  plus: <path d="M12 5v14M5 12h14" />,
  check: <path d="m5 12.5 4.5 4.5L19 7" />,
  download: <path d="M12 4v11M7 10.5l5 5 5-5M5 19.5h14" />,
  headphones: <path d="M4 15v-3a8 8 0 0 1 16 0v3M4 15a2 2 0 0 1 2-2h1v7H6a2 2 0 0 1-2-2zM20 15a2 2 0 0 0-2-2h-1v7h1a2 2 0 0 0 2-2z" />,
  close: <path d="M6 6l12 12M18 6 6 18" />,
  sync: <path d="M20 11a8 8 0 0 0-14.3-4.3L4 8M4 4v4h4M4 13a8 8 0 0 0 14.3 4.3L20 16M20 20v-4h-4" />,
  grammar: <path d="M4 19 8.5 6h1L14 19M5.6 14.5h6.8M15 13.2c.7-1 1.7-1.5 2.9-1.5 1.8 0 2.6 1 2.6 2.7V19M20.5 15.6c-.9-.3-1.8-.4-2.6-.3-1.6.2-2.6 1-2.6 2.1 0 1 .8 1.7 2 1.7 1.4 0 2.6-.8 3.2-2" />,
  help: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M9.6 9.3a2.5 2.5 0 1 1 3.6 2.3c-.7.4-1.2 1-1.2 1.8v.4M12 17.2v.1" />
    </>
  ),
};

export function Icon({ name, size = 22, className }: { name: IconName; size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={className}
    >
      {PATHS[name]}
    </svg>
  );
}
