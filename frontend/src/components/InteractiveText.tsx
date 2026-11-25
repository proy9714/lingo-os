import { Fragment, useMemo } from "react";

import { useAnnotation } from "../api/hooks";
import type { AnnotatedToken, Annotation, TokenStatus } from "../api/types";
import { useFurigana, withFurigana } from "../lib/furigana";
import { useLookupStore } from "../state/lookup";
import { Skeleton, cx } from "./ui";

/** Colours for text on the light reading page. Function words and known words stay plain. */
export const STATUS_CLASS: Record<TokenStatus, string> = {
  none: "",
  likely: "",
  known: "",
  ignored: "",
  new: "bg-amber-200/80 shadow-[inset_0_-2px_0_#b8700f]",
  learning: "bg-sky-200/90",
  familiar: "shadow-[inset_0_-1px_0_rgb(80_72_60/0.7)]",
};

export function InteractiveText({ lang, text, locator }: { lang: string; text: string; locator?: string }) {
  const annotation = useAnnotation(lang, text);
  if (annotation.isPending) {
    return (
      <div className="flex flex-col gap-3" aria-busy="true">
        <Skeleton className="h-5 w-full bg-black/10" />
        <Skeleton className="h-5 w-11/12 bg-black/10" />
        <Skeleton className="h-5 w-4/5 bg-black/10" />
      </div>
    );
  }
  if (annotation.isError) {
    return <p role="alert" className="text-red-700">Could not analyse this text: {annotation.error.message}</p>;
  }
  return <Rendered lang={lang} text={text} data={annotation.data} locator={locator} />;
}

function Rendered({ lang, text, data, locator }: { lang: string; text: string; data: Annotation; locator?: string }) {
  const select = useLookupStore((s) => s.select);
  const selected = useLookupStore((s) => s.selection);
  const furigana = useFurigana();

  const pieces = useMemo(() => {
    const out: { key: string; gap: string; token: AnnotatedToken }[] = [];
    let cursor = 0;
    data.tokens.forEach((token, index) => {
      out.push({ key: `${index}-${token.start}`, gap: text.slice(cursor, token.start), token });
      cursor = token.end;
    });
    return { out, tail: text.slice(cursor) };
  }, [data, text]);

  const sentenceOf = (token: AnnotatedToken) => {
    const sentence = data.sentences.find((s) => token.start >= s.start && token.start < s.end);
    return sentence ? text.slice(sentence.start, sentence.end).trim() : text.slice(Math.max(0, token.start - 80), token.end + 80);
  };

  return (
    <div lang={lang} className="whitespace-pre-wrap">
      {pieces.out.map(({ key, gap, token }) => {
        const content = text.slice(token.start, token.end);
        const isSelected =
          selected?.token.start === token.start && selected?.lang === lang && selected.sentence === sentenceOf(token);
        return (
          <Fragment key={key}>
            {gap}
            {token.word ? (
              <button
                type="button"
                onClick={() => select({ lang, token, surface: content, sentence: sentenceOf(token), locator })}
                className={cx(
                  "cursor-pointer rounded-[4px] px-[1px] text-inherit transition-colors hover:bg-black/10",
                  STATUS_CLASS[token.status],
                  isSelected && "outline-2 outline-offset-1 outline-[#1f1d1a]",
                )}
                aria-label={`${content}: look up${token.status === "new" ? " (new word)" : ""}`}
              >
                {withFurigana(token, content, furigana)}
              </button>
            ) : (
              content
            )}
          </Fragment>
        );
      })}
      {pieces.tail}
    </div>
  );
}
