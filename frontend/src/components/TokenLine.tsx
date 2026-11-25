import { Fragment } from "react";

import type { AnnotatedToken, TokenStatus } from "../api/types";
import { useFurigana, withFurigana } from "../lib/furigana";
import { useLookupStore } from "../state/lookup";
import { cx } from "./ui";

const PAPER: Record<TokenStatus, string> = {
  none: "",
  likely: "",
  known: "",
  ignored: "",
  new: "bg-amber-200/80 shadow-[inset_0_-2px_0_#b8700f]",
  learning: "bg-sky-200/90",
  familiar: "shadow-[inset_0_-1px_0_rgb(80_72_60/0.7)]",
};

const DARK: Record<TokenStatus, string> = {
  none: "",
  likely: "",
  known: "",
  ignored: "",
  new: "bg-amber-300/20 text-amber-100 shadow-[inset_0_-2px_0_#f5b443]",
  learning: "bg-sky-400/25 text-sky-100",
  familiar: "shadow-[inset_0_-1px_0_rgb(255_255_255/0.5)]",
};

interface Props {
  lang: string;
  text: string;
  tokens: AnnotatedToken[];
  sentence: string;
  locator?: string;
  contentItemId?: number;
  theme?: "paper" | "dark";
  onWordClick?: () => void;
}

/** One line of text whose words are buttons that open the lookup panel. */
export function TokenLine({ lang, text, tokens, sentence, locator, contentItemId, theme = "paper", onWordClick }: Props) {
  const select = useLookupStore((s) => s.select);
  const selected = useLookupStore((s) => s.selection);
  const classes = theme === "dark" ? DARK : PAPER;
  const furigana = useFurigana();
  let cursor = 0;
  return (
    <span lang={lang}>
      {tokens.map((token, index) => {
        const gap = text.slice(cursor, token.start);
        cursor = token.end;
        const content = text.slice(token.start, token.end);
        if (!token.word) {
          return (
            <Fragment key={index}>
              {gap}
              {content}
            </Fragment>
          );
        }
        const isSelected =
          selected?.lang === lang && selected.sentence === sentence && selected.token.start === token.start && selected.locator === locator;
        return (
          <Fragment key={index}>
            {gap}
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                onWordClick?.();
                select({ lang, token, surface: content, sentence, locator, contentItemId });
              }}
              className={cx(
                "cursor-pointer rounded-[4px] px-[1px] text-inherit transition-colors",
                theme === "dark" ? "hover:bg-white/12" : "hover:bg-black/10",
                classes[token.status],
                isSelected && (theme === "dark" ? "outline-2 outline-offset-1 outline-white" : "outline-2 outline-offset-1 outline-[#1f1d1a]"),
              )}
              aria-label={`${content}: look up${token.status === "new" ? " (new word)" : ""}`}
            >
              {withFurigana(token, content, furigana)}
            </button>
          </Fragment>
        );
      })}
      {text.slice(cursor)}
    </span>
  );
}
