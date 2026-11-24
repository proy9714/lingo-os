import { useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { api, mangaImage, mediaUrl } from "../api/client";
import { useContentItem, useContentMutation, useMangaPage, useMangaVocab } from "../api/hooks";
import type { AnnotatedToken, MangaBlock, MangaPageData, MangaVocabWord } from "../api/types";
import { TokenLine } from "../components/TokenLine";
import { Button, Chip, Panel, cx } from "../components/ui";
import { useEngagement } from "../lib/useEngagement";
import { useTracker } from "../lib/useTracker";
import { useLookupStore } from "../state/lookup";
import { useMediaUrl } from "../sync/useSync";

function stored(key: string, fallback: boolean): boolean {
  try {
    const value = window.localStorage.getItem(key);
    return value === null ? fallback : value === "1";
  } catch {
    return fallback;
  }
}

function remember(key: string, value: boolean) {
  try {
    window.localStorage.setItem(key, value ? "1" : "0");
  } catch {
    // not remembered
  }
}

export function MangaViewerPage() {
  const { itemId } = useParams({ strict: false }) as { itemId: string };
  const id = Number(itemId);
  const item = useContentItem(id);
  const [page, setPage] = useState<number | null>(null);
  const [spread, setSpread] = useState(() => stored("lingo.manga.spread", false));
  const [showText, setShowText] = useState(() => stored("lingo.manga.text", false));
  const [editMode, setEditMode] = useState(false);
  const [vocabOpen, setVocabOpen] = useState(false);
  const [editing, setEditing] = useState<MangaBlock | null>(null);
  const closeLookup = useLookupStore((s) => s.close);
  const lookupOpen = useLookupStore((s) => s.selection !== null);

  useEffect(() => {
    if (page !== null || !item.data) return;
    const match = /^page:(\d+)$/.exec(item.data.position_ref ?? "");
    setPage(match ? Number(match[1]) : 1);
  }, [item.data, page]);

  const current = page ?? 1;
  const first = useMangaPage(id, current);
  const total = first.data?.pages ?? item.data?.page_count ?? 1;
  const showSecond = spread && current + 1 <= total;
  const second = useMangaPage(id, showSecond ? current + 1 : current);
  const step = spread ? 2 : 1;
  const lang = item.data?.language ?? "ja";
  const rtl = lang === "ja";

  const go = (target: number) => {
    const next = Math.max(1, Math.min(total, target));
    if (next === current) return;
    if (next > current) void api.readProgress(id, Math.min(total, current + step - 1), total).catch(() => undefined);
    closeLookup();
    setPage(next);
  };
  const finish = () => void api.readProgress(id, total, total).catch(() => undefined);

  // Arrow keys follow the reading direction: in Japanese manga, left is forward.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) return;
      if (event.key === "ArrowLeft") go(rtl ? current + step : current - step);
      if (event.key === "ArrowRight") go(rtl ? current - step : current + step);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // Fetch the next page's image ahead of time.
  useEffect(() => {
    for (const n of [current + step, current + step + 1]) {
      if (n <= total) void mediaUrl(mangaImage(id, n)).then((src) => (new Image().src = src)).catch(() => undefined);
    }
  }, [id, current, step, total]);

  const engaged = useEngagement(120_000);
  useTracker({
    lang,
    activity: "manga",
    label: "Reading manga",
    contentItemId: item.data ? id : undefined,
    active: Boolean(first.data) && (engaged || lookupOpen),
  });

  const toggle = (key: string, value: boolean, set: (v: boolean) => void) => {
    set(value);
    remember(key, value);
  };

  if (item.isError) {
    return (
      <Panel role="alert">
        <p className="text-sm">This volume could not be loaded: {item.error.message}</p>
        <Link to="/manga" className="mt-3 inline-block text-sm text-accent underline">
          Back to your volumes
        </Link>
      </Panel>
    );
  }

  const pagesShown: MangaPageData[] = [];
  if (first.data) pagesShown.push(first.data);
  if (showSecond && second.data && second.data.page === current + 1) pagesShown.push(second.data);
  const ordered = rtl ? [...pagesShown].reverse() : pagesShown;
  const noText = first.data?.ocr === "pending";
  const forward = () => go(current + step);
  const back = () => go(current - step);
  const atEnd = current + step > total;

  return (
    <div className="flex flex-col gap-3">
      <header className="flex flex-wrap items-center justify-between gap-2 px-1 pt-1">
        <div className="min-w-0">
          <Link to="/manga" className="text-xs font-medium text-ink-3 hover:text-ink">
            ← Volumes
          </Link>
          <h1 className="truncate text-xl font-bold tracking-tight">{item.data?.title ?? " "}</h1>
        </div>
        <div className="flex flex-wrap items-center gap-1.5" role="toolbar" aria-label="Viewer options">
          <ToggleButton pressed={spread} onClick={() => toggle("lingo.manga.spread", !spread, setSpread)}>
            Two pages
          </ToggleButton>
          <ToggleButton pressed={showText} onClick={() => toggle("lingo.manga.text", !showText, setShowText)}>
            Show all text
          </ToggleButton>
          <ToggleButton pressed={editMode} onClick={() => setEditMode((v) => !v)}>
            Fix OCR text
          </ToggleButton>
          <ToggleButton pressed={vocabOpen} onClick={() => setVocabOpen((v) => !v)}>
            Volume words
          </ToggleButton>
        </div>
      </header>

      {first.data?.summary?.known_share !== undefined && first.data.summary?.known_share !== null && (
        <div className="flex flex-wrap items-center gap-2 px-1 text-sm">
          <Chip tone="accent">≈ {Math.round((first.data.summary?.known_share ?? 0) * 100)}% of this page likely known</Chip>
          {item.data?.coverage !== null && item.data?.coverage !== undefined && (
            <Chip>volume ≈ {Math.round(item.data.coverage * 100)}%</Chip>
          )}
          {editMode && <span className="text-xs text-ink-3">Click a bubble to correct its text.</span>}
        </div>
      )}
      {noText && <NoTextNotice id={id} />}

      <div className={cx("grid gap-3", vocabOpen && "lg:grid-cols-[minmax(0,1fr)_300px]")}>
        <Stage pages={ordered} itemId={id} lang={lang} showText={showText} editMode={editMode} onEdit={setEditing} loading={!first.data} />
        {vocabOpen && <VocabPanel id={id} lang={lang} onJump={(n) => go(n)} />}
      </div>

      <nav aria-label="Pages" className={cx("flex items-center justify-between gap-3 pb-4", rtl && "flex-row-reverse")}>
        <Button disabled={current <= 1} onClick={back}>
          {rtl ? "Previous →" : "← Previous"}
        </Button>
        <span className="text-sm text-ink-2">
          {showSecond ? `Pages ${current}–${current + 1}` : `Page ${current}`} of {total}
        </span>
        {atEnd ? (
          <Button variant="primary" onClick={finish}>
            Mark as finished
          </Button>
        ) : (
          <Button variant="primary" onClick={forward}>
            {rtl ? "← Next" : "Next →"}
          </Button>
        )}
      </nav>

      {editing && <BlockEditor block={editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

function ToggleButton({ pressed, onClick, children }: { pressed: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onClick}
      className={cx(
        "min-h-10 rounded-xl px-3 text-[13px] font-semibold transition",
        pressed ? "bg-accent/20 text-accent" : "text-ink-2 hover:bg-white/8 hover:text-ink",
      )}
    >
      {children}
    </button>
  );
}

/** Fits one or two pages into the space available and scales the text layer with them. */
function Stage(props: {
  pages: MangaPageData[];
  itemId: number;
  lang: string;
  showText: boolean;
  editMode: boolean;
  onEdit: (block: MangaBlock) => void;
  loading: boolean;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [space, setSpace] = useState({ w: 800, h: 600 });
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    const measure = () => {
      const rect = el.getBoundingClientRect();
      // leave room for the page buttons, and on phones for the bottom navigation bar
      const reserved = 76 + (window.innerWidth < 768 ? 96 : 0);
      setSpace({ w: rect.width, h: Math.max(320, window.innerHeight - rect.top - reserved) });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    window.addEventListener("resize", measure);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, []);

  const count = Math.max(1, props.pages.length);
  return (
    <div ref={box} className="flex min-h-[320px] items-start justify-center gap-1 rounded-[20px] bg-black/30 p-2">
      {props.loading && <div className="h-[60vh] w-full animate-pulse rounded-xl bg-white/5" />}
      {props.pages.map((data) => {
        const scale = Math.min((space.w - 16 - (count - 1) * 4) / count / data.width, space.h / data.height);
        return <PageView key={data.page} data={data} scale={scale} {...props} />;
      })}
    </div>
  );
}

function PageView({
  data,
  scale,
  itemId,
  lang,
  showText,
  editMode,
  onEdit,
}: {
  data: MangaPageData;
  scale: number;
  itemId: number;
  lang: string;
  showText: boolean;
  editMode: boolean;
  onEdit: (block: MangaBlock) => void;
}) {
  const image = useMediaUrl(mangaImage(itemId, data.page));
  return (
    <div className="relative shrink-0 overflow-hidden rounded-md bg-white" style={{ width: data.width * scale, height: data.height * scale }}>
      <img
        src={image}
        alt={`Page ${data.page}`}
        draggable={false}
        className="absolute inset-0 h-full w-full select-none"
      />
      {data.blocks.map((block) => (
        <BlockView
          key={block.id}
          block={block}
          scale={scale}
          lang={lang}
          page={data.page}
          itemId={itemId}
          showText={showText}
          editMode={editMode}
          onEdit={onEdit}
        />
      ))}
    </div>
  );
}

function linesOf(block: MangaBlock): { text: string; tokens: AnnotatedToken[] }[] {
  return block.lines.map((line) => {
    const end = line.start + line.text.length;
    return {
      text: line.text,
      tokens: block.tokens
        .filter((t) => t.start >= line.start && t.end <= end)
        .map((t) => ({ ...t, start: t.start - line.start, end: t.end - line.start })),
    };
  });
}

function BlockView({
  block,
  scale,
  lang,
  page,
  itemId,
  showText,
  editMode,
  onEdit,
}: {
  block: MangaBlock;
  scale: number;
  lang: string;
  page: number;
  itemId: number;
  showText: boolean;
  editMode: boolean;
  onEdit: (block: MangaBlock) => void;
}) {
  const locator = `manga:p${page}:b${block.seq}`;
  const selected = useLookupStore((s) => s.selection?.contentItemId === itemId && s.selection.locator === locator);
  const lines = useMemo(() => linesOf(block), [block]);
  const [x1, y1, x2, y2] = block.box;
  const lineCount = Math.max(1, block.lines.length);
  const estimated = block.vertical ? (x2 - x1) / lineCount : (y2 - y1) / lineCount;
  const fontSize = Math.max(8, (block.font_size ?? estimated * 0.85) * scale);
  const visible = showText || selected || editMode;

  const style: React.CSSProperties = {
    left: x1 * scale,
    top: y1 * scale,
    minWidth: (x2 - x1) * scale,
    minHeight: (y2 - y1) * scale,
    fontSize,
    lineHeight: 1.15,
    writingMode: block.vertical ? "vertical-rl" : "horizontal-tb",
  };

  if (editMode) {
    return (
      <button
        type="button"
        onClick={() => onEdit(block)}
        style={style}
        className="absolute z-10 rounded-sm border-2 border-dashed border-sky-500 bg-white/90 p-0.5 text-left text-black"
        aria-label={`Correct the text: ${block.text}`}
      >
        {block.lines.map((line, i) => (
          <span key={i} className="block whitespace-nowrap">
            {line.text}
          </span>
        ))}
      </button>
    );
  }

  return (
    <div
      style={style}
      lang={lang}
      className={cx(
        "group absolute z-10 rounded-sm p-0.5 font-sans text-black transition-opacity",
        visible ? "bg-white opacity-100 shadow-md" : "opacity-0 hover:bg-white hover:opacity-100 hover:shadow-md focus-within:bg-white focus-within:opacity-100",
      )}
    >
      {lines.map((line, i) => (
        <span key={i} className="block whitespace-nowrap">
          <TokenLine
            lang={lang}
            text={line.text}
            tokens={line.tokens}
            sentence={block.text}
            locator={locator}
            contentItemId={itemId}
          />
        </span>
      ))}
    </div>
  );
}

function NoTextNotice({ id }: { id: number }) {
  const ocr = useContentMutation(() => api.mangaOcr(id));
  return (
    <div className="glass flex flex-wrap items-center gap-3 rounded-2xl px-4 py-3 text-sm text-ink-2">
      <span>This page has no text layer yet, so words can't be clicked.</span>
      <Button disabled={ocr.isPending || ocr.isSuccess} onClick={() => ocr.mutate(undefined)}>
        {ocr.isSuccess ? "OCR queued" : "Run OCR"}
      </Button>
      {ocr.isError && <span className="text-xs text-ink-3">{ocr.error.message}</span>}
    </div>
  );
}

function VocabPanel({ id, lang, onJump }: { id: number; lang: string; onJump: (page: number) => void }) {
  const vocab = useMangaVocab(id, true);
  const select = useLookupStore((s) => s.select);
  const open = (word: MangaVocabWord) => {
    const token: AnnotatedToken = {
      start: 0,
      end: word.display.length,
      word: true,
      lemma: word.lemma,
      display: word.display,
      reading: word.reading,
      pos: word.pos,
      learnable: true,
      forms: [word.display],
      rank: word.rank,
      status: word.status,
      p: null,
    };
    select({ lang, token, surface: word.display, sentence: word.example, locator: `manga:vocab`, contentItemId: id });
  };
  return (
    <Panel aria-labelledby="t-vol-words" className="max-h-[80vh] overflow-y-auto p-4">
      <h2 id="t-vol-words" className="text-[13px] font-semibold tracking-[0.08em] text-ink-2 uppercase">
        Words in this volume
      </h2>
      {vocab.isPending ? (
        <p className="mt-3 text-sm text-ink-3">Counting…</p>
      ) : vocab.isError ? (
        <p className="mt-3 text-sm text-red-200">{vocab.error.message}</p>
      ) : vocab.data.words.length === 0 ? (
        <p className="mt-3 text-sm text-ink-2">No likely-new words found.</p>
      ) : (
        <>
          <p className="mt-1 mb-3 text-xs text-ink-3">
            {vocab.data.total_unknown} likely new or learning words, most frequent first. Knowing the top ones before you
            start makes the volume easier.
          </p>
          <ol className="flex flex-col gap-1">
            {vocab.data.words.map((word) => (
              <li key={`${word.lemma}-${word.reading}`} className="flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-white/6">
                <button type="button" onClick={() => open(word)} className="min-w-0 flex-1 text-left">
                  <span lang={lang} className="font-semibold">
                    {word.display}
                  </span>
                  {word.reading && word.reading !== word.display && <span className="ml-1.5 text-xs text-ink-3">{word.reading}</span>}
                  <span className="block text-[11px] text-ink-3">
                    {word.count}× on {word.pages} page{word.pages === 1 ? "" : "s"}
                    {word.status === "learning" && " · learning"}
                  </span>
                </button>
                <button
                  type="button"
                  onClick={() => onJump(word.first_page)}
                  className="shrink-0 rounded-md px-2 py-1 text-xs text-ink-2 hover:bg-white/10"
                  aria-label={`Go to page ${word.first_page}`}
                >
                  p. {word.first_page}
                </button>
              </li>
            ))}
          </ol>
        </>
      )}
    </Panel>
  );
}

function BlockEditor({ block, onClose }: { block: MangaBlock; onClose: () => void }) {
  const [value, setValue] = useState(block.lines.map((l) => l.text).join("\n"));
  const qc = useQueryClient();
  const save = useContentMutation((lines: string[]) => api.fixBlock(block.id, lines));
  return (
    <div role="dialog" aria-modal="true" aria-labelledby="t-fix" className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-md rounded-3xl border border-white/16 bg-[#121726] p-5">
        <h2 id="t-fix" className="text-lg font-bold">
          Correct the OCR text
        </h2>
        <p className="mt-1 text-sm text-ink-2">One line per line in the bubble.</p>
        <textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          rows={Math.max(3, block.lines.length + 1)}
          className="mt-3 w-full rounded-xl border border-white/14 bg-surface p-3 text-base text-ink"
          autoFocus
        />
        {save.isError && <p className="mt-2 text-sm text-red-200">{save.error.message}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            disabled={save.isPending || !value.trim()}
            onClick={() =>
              save.mutate(value.split("\n"), {
                onSuccess: () => {
                  void qc.invalidateQueries({ queryKey: ["manga-page"] });
                  void qc.invalidateQueries({ queryKey: ["manga-vocab"] });
                  onClose();
                },
              })
            }
          >
            {save.isPending ? "Saving…" : "Save"}
          </Button>
        </div>
      </div>
    </div>
  );
}
