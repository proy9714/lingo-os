import type { IconName } from "./Icon";

export interface NavItem {
  to: "/" | "/watch" | "/read" | "/manga" | "/speak" | "/words" | "/level" | "/settings" | "/help";
  label: string;
  icon: IconName;
}

export const NAV: NavItem[] = [
  { to: "/", label: "Today", icon: "home" },
  { to: "/watch", label: "Watch", icon: "play" },
  { to: "/read", label: "Read", icon: "book" },
  { to: "/manga", label: "Manga", icon: "manga" },
  { to: "/speak", label: "Speak", icon: "mic" },
  { to: "/words", label: "Words", icon: "words" },
  { to: "/level", label: "Level", icon: "gauge" },
  { to: "/settings", label: "Settings", icon: "settings" },
  { to: "/help", label: "Help", icon: "help" },
];
