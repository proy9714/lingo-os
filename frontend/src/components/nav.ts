import type { IconName } from "./Icon";

export interface NavItem {
  to: "/" | "/watch" | "/read" | "/manga" | "/speak" | "/words" | "/grammar" | "/level" | "/downloads" | "/settings" | "/help";
  label: string;
  icon: IconName;
  only?: string[]; // shown only while one of these languages is active
}

export const NAV: NavItem[] = [
  { to: "/", label: "Today", icon: "home" },
  { to: "/watch", label: "Watch", icon: "play" },
  { to: "/read", label: "Read", icon: "book" },
  { to: "/manga", label: "Manga", icon: "manga", only: ["ja"] }, // mokuro manga reading is for Japanese
  { to: "/speak", label: "Speak", icon: "mic" },
  { to: "/words", label: "Words", icon: "words" },
  { to: "/grammar", label: "Grammar", icon: "grammar" },
  { to: "/level", label: "Level", icon: "gauge" },
  { to: "/downloads", label: "Downloads", icon: "download" },
  { to: "/settings", label: "Settings", icon: "settings" },
  { to: "/help", label: "Help", icon: "help" },
];

/** The menu for the active language (Manga only appears for Japanese). */
export const navFor = (lang: string): NavItem[] => NAV.filter((item) => !item.only || item.only.includes(lang));
