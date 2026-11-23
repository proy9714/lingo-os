import { Link, useParams } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState } from "react";

import { api } from "../api/client";
import { useContentItem, usePageList, useReaderPage } from "../api/hooks";
import type { ReaderParagraph } from "../api/types";
import { TokenLine } from "../components/TokenLine";
import { Button, Chip, Panel, Skeleton, cx } from "../components/ui";
import { splitSentences } from "../lib/sentences";
import { useEngagement } from "../lib/useEngagement";
import { useTracker } from "../lib/useTracker";
import { useLookupStore } from "../state/lookup";

/** Reading counts while the page is open and you've scrolled, clicked or moved the mouse in the last 3 minutes. */
const IDLE_AFTER_MS = 180_000;
const SIZES = [17, 19, 21, 24];

function loadSize(): number {
  try {
    const value = Number(window.localStorage.getItem("lingo.reader.size"));
    return SIZES.includes(value) ? value : 19;
  } catch {
    return 19;
  }
}

export function ReaderPage() {
  const { itemId } = useParams({ strict: false }) as { itemId: string };
  const id = Number(itemId);
  const item = useContentItem(id);
  const [page, setPage] = useState<number | null>(null);
  const [size, setSize] = useState(loadSize);
  const reader = useReaderPage(id, page ?? 1);
  const pageList = usePageList(id);
  const lookupOpen = useLookupStore((s) => s.selection !== null);
  const closeLookup = useLookupStore((s) => s.close);
  const top = useRef<HTMLDivElement>(null);

  // Resume where you left off.
  useEffect(() => {
    if (page !== null || !item.data) return;
    const match = /^page:(\d+)$/.exec(item.data.position_ref ?? "");
    setPage(match ? Number(match[1]) : 1);
  }, [item.data, page]);

  const total = reader.data?.pages ?? pageList.data?.total ?? 1;
  const current = reader.data?.page ?? page ?? 1;

  const go = (next: number) => {
    const target = Math.max(1, Math.min(total, next));
    if (target === current) return;
    if (target > current) void api.readProgress(id, current, total).catch(() => undefined);
    closeLookup();
    setPage(target);
    top.current?.scrollIntoView({ block: "start" });
  };
  const finish = () => void api.readProgress(id, total, total).catch(() => undefined);

  // Left/right arrow keys turn pages (not while typing).
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) return;
      if (event.key === "ArrowRight") go(current + 1);
      if (event.key === "ArrowLeft") go(current - 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const engaged = useEngagement(IDLE_AFTER_MS);
  const lang = item.data?.language ?? "de";
  useTracker({
    lang,
    activity: item.data?.type === "article" ? "article" : "reading",
    label: "Reading",
    contentItemId: item.data ? id : undefined,
    active: Boolean(reader.data) && (engaged || lookupOpen),
  });

  const changeSize = (delta: number) => {
    const next = SIZES[Math.max(0, Math.min(SIZES.length - 1, SIZES.indexOf(size) + delta))];
    setSize(next);
    try {
      window.localStorage.setItem("lingo.reader.size", String(next));
    } catch {
      // not remembered
    }
  };

  if (item.isError) {
    return (
      <Panel role="alert">
        <p className="text-sm">This item could not be loaded: {item.error.message}</p>
        <Link to="/read" className="mt-3 inline-block text-sm text-accent underline">
          Back to your shelf
        </Link>
      </Panel>
    );
  }

  const data = reader.data;
  const share = data?.summary?.known_share;
  return (
    <div ref={top} className="flex scroll-mt-24 flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-3 px-1 pt-1">
        <div className="min-w-0">
          <Link to="/read" className="text-xs font-medium text-ink-3 hover:text-ink">
            ← Shelf
          </Link>
          <h1 className="mt-1 text-2xl font-bold tracking-tight">{item.data?.title ?? " "}</h1>
          {item.data?.creator && <p className="mt-1 text-sm text-ink-2">{item.data.creator}</p>}
        </div>
        <div className="flex items-center gap-1.5">
          <Button variant="ghost" aria-label="Smaller text" disabled={size === SIZES[0]} onClick={() => changeSize(-1)}>
            A−
          </Button>
          <Button variant="ghost" aria-label="Larger text" disabled={size === SIZES[SIZES.length - 1]} onClick={() => changeSize(1)}>
            A+
          </Button>
        </div>
      </header>

      <div className="glass flex flex-wrap items-center gap-2 rounded-2xl px-4 py-3 text-sm">
        {share !== null && share !== undefined && <Chip tone="accent">≈ {Math.round(share * 100)}% of this page likely known</Chip>}
        {data?.summary && <Chip>{data.summary.new_words} likely new</Chip>}
        {item.data?.coverage !== null && item.data?.coverage !== undefined && (
          <Chip>whole text ≈ {Math.round(item.data.coverage * 100)}%</Chip>
        )}
        <PagePicker
          current={current}
          total={total}
          titles={pageList.data?.pages ?? []}
          onPick={(n) => go(n)}
        />
      </div>

      {reader.isError ? (
        <Panel role="alert">Could not load this page: {reader.error.message}</Panel>
      ) : !data ? (
        <Skeleton className="h-[60vh] rounded-[20px]" />
      ) : (
        <article
          className={cx(
            "rounded-[20px] bg-[#f6f2ea] px-5 py-8 text-[#1f1d1a] shadow-[0_30px_60px_rgb(0_0_0/0.35)] transition-opacity md:px-14 md:py-12",
            reader.isPlaceholderData && "opacity-60",
          )}
        >
          <div
            className={cx("mx-auto max-w-[680px] leading-[1.9]", lang === "ja" ? "font-sans" : "font-serif")}
            style={{ fontSize: `${size}px` }}
          >
            {data.title && (
              <h2 className="mb-6 text-[1.35em] leading-snug font-bold" lang={lang}>
                {data.title}
              </h2>
            )}
            {data.paragraphs.map((paragraph) =>
              data.title && paragraph.text === data.title ? null : (
                <Paragraph key={paragraph.seq} lang={lang} paragraph={paragraph} contentItemId={id} />
              ),
            )}
          </div>
        </article>
      )}

      <nav aria-label="Pages" className="flex items-center justify-between gap-3 pb-4">
        <Button disabled={current <= 1} onClick={() => go(current - 1)}>
          ← Previous
        </Button>
        <span className="text-sm text-ink-2">
          Page {current} of {total}
        </span>
        {current < total ? (
          <Button variant="primary" onClick={() => go(current + 1)}>
            Next →
          </Button>
        ) : (
          <Button variant="primary" onClick={finish}>
            Mark as finished
          </Button>
        )}
      </nav>
    </div>
  );
}

function Paragraph({ lang, paragraph, contentItemId }: { lang: string; paragraph: ReaderParagraph; contentItemId: number }) {
  const sentences = useMemo(() => splitSentences(paragraph.text, paragraph.tokens), [paragraph]);
  return (
    <p className="mb-[1em]" lang={lang}>
      {sentences.map((sentence) => (
        <TokenLine
          key={sentence.start}
          lang={lang}
          text={sentence.text}
          tokens={sentence.tokens}
          sentence={sentence.text.trim()}
          locator={`${paragraph.locator.split("|")[0]}@${sentence.start}`}
          contentItemId={contentItemId}
        />
      ))}
    </p>
  );
}

function PagePicker({
  current,
  total,
  titles,
  onPick,
}: {
  current: number;
  total: number;
  titles: { n: number; title: string | null }[];
  onPick: (n: number) => void;
}) {
  if (total <= 1) return null;
  // Label each page with the chapter it belongs to.
  let chapter = "";
  const options = titles.map((p) => {
    if (p.title) chapter = p.title;
    return { n: p.n, label: chapter ? `${p.n} · ${chapter.slice(0, 48)}` : String(p.n) };
  });
  return (
    <label className="ml-auto flex items-center gap-2 text-xs text-ink-2">
      Go to
      <select
        value={current}
        onChange={(e) => onPick(Number(e.target.value))}
        className="min-h-9 max-w-[260px] rounded-lg border border-white/14 bg-surface px-2 text-sm text-ink"
      >
        {(options.length ? options : Array.from({ length: total }, (_, i) => ({ n: i + 1, label: String(i + 1) }))).map((o) => (
          <option key={o.n} value={o.n}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}
