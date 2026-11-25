// Furigana over Japanese words: off, over the words you don't know yet, or over every word with kanji.
import { useSyncExternalStore, type ReactNode } from "react";

import type { AnnotatedToken } from "../api/types";

export type FuriganaMode = "off" | "unknown" | "all";
const KEY = "lingo.furigana";
const MODES: FuriganaMode[] = ["off", "unknown", "all"];
const listeners = new Set<() => void>();

function read(): FuriganaMode {
  try {
    const value = window.localStorage.getItem(KEY);
    return MODES.includes(value as FuriganaMode) ? (value as FuriganaMode) : "off";
  } catch {
    return "off";
  }
}

export function setFurigana(mode: FuriganaMode): void {
  try {
    window.localStorage.setItem(KEY, mode);
  } catch {
    // private mode: the choice lasts until the page closes
  }
  listeners.forEach((l) => l());
}

export function useFurigana(): FuriganaMode {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    read,
    () => "off",
  );
}

/** The word as written, with its reading over the kanji when the mode asks for it. */
export function withFurigana(token: AnnotatedToken, content: string, mode: FuriganaMode): ReactNode {
  if (mode === "off" || !token.ruby?.length) return content;
  if (mode === "unknown" && !["new", "learning"].includes(token.status)) return content;
  if (token.ruby.map(([text]) => text).join("") !== content) return content; // a token cut differently: leave it
  return token.ruby.map(([text, reading], n) =>
    reading ? (
      <ruby key={n}>
        {text}
        <rt className="text-[0.55em] font-normal tracking-normal opacity-80 select-none">{reading}</rt>
      </ruby>
    ) : (
      <span key={n}>{text}</span>
    ),
  );
}

const LABEL: Record<FuriganaMode, string> = { off: "off", unknown: "new words", all: "all words" };

/** The switch for Japanese: off → over new words → over all words. */
export function FuriganaToggle({ className }: { className?: string }) {
  const mode = useFurigana();
  const next = MODES[(MODES.indexOf(mode) + 1) % MODES.length];
  return (
    <button
      type="button"
      onClick={() => setFurigana(next)}
      aria-label={`Furigana: ${LABEL[mode]}. Switch to ${LABEL[next]}.`}
      title="Readings over the kanji"
      className={className}
    >
      <span lang="ja">ふりがな</span> · {LABEL[mode]}
    </button>
  );
}
