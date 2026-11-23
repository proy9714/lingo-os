import type { AnnotatedToken } from "../api/types";

export interface SentencePiece {
  text: string;
  start: number;
  tokens: AnnotatedToken[];
}

// A sentence ends at . ! ? … or their Japanese forms, plus any closing quotes or brackets.
const END = /[.!?…。！？]+["'»”’」』）)]*\s*/g;

/**
 * Split a paragraph into sentences and give each its own tokens (offsets made relative to the sentence),
 * so a word saved from a long paragraph keeps just its sentence as context.
 */
export function splitSentences(text: string, tokens: AnnotatedToken[]): SentencePiece[] {
  const bounds: [number, number][] = [];
  let start = 0;
  for (const match of text.matchAll(END)) {
    const end = (match.index ?? 0) + match[0].length;
    // "Dr. Weber", "z. B.", "3.5": not a sentence end when a lowercase letter or digit follows
    const next = text.charAt(end);
    if (next && /[\p{Ll}\d]/u.test(next)) continue;
    if (end > start) bounds.push([start, end]);
    start = end;
  }
  if (start < text.length) bounds.push([start, text.length]);
  return bounds.map(([from, to]) => ({
    text: text.slice(from, to),
    start: from,
    tokens: tokens
      .filter((t) => t.start >= from && t.end <= to)
      .map((t) => ({ ...t, start: t.start - from, end: t.end - from })),
  }));
}
