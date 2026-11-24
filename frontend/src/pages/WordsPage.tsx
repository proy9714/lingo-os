import { useEffect, useState } from "react";

import { useActiveLanguage, usePatchWord, useVocabSummary, useWord, useWords } from "../api/hooks";
import type { WordListItem, WordStatus } from "../api/types";
import { Button, Chip, Panel, Skeleton, cx } from "../components/ui";
import { formatDay, localDayOf } from "../lib/format";

const FILTERS: { key: string; label: string }[] = [
  { key: "", label: "All" },
  { key: "saved", label: "Saved" },
  { key: "learning", label: "Learning" },
  { key: "known", label: "Known" },
  { key: "seen", label: "Looked up" },
  { key: "ignored", label: "Ignored" },
];

const STATUS_LABEL: Record<WordStatus, string> = {
  seen: "looked up",
  learning: "learning",
  familiar: "familiar",
  known: "known",
  ignored: "ignored",
};

export function WordsPage() {
  const { code } = useActiveLanguage();
  const [chosen, setFilter] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [limit, setLimit] = useState(50);
  const [openId, setOpenId] = useState<number | null>(null);
  const summary = useVocabSummary(code).data;
  // open on Saved, unless nothing is saved yet: then show everything rather than an empty list
  const filter = chosen ?? (summary && !summary.saved ? "" : "saved");
  const words = useWords(code, filter, debounced, limit);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(query.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    setLimit(50);
    setOpenId(null);
  }, [code, filter, debounced]);

  const count = (key: string) => (key ? summary?.[key] : summary ? Object.entries(summary).filter(([k]) => k !== "saved").reduce((a, [, v]) => a + v, 0) : undefined);

  return (
    <div className="flex flex-col gap-4">
      <header className="px-1 pt-1">
        <h1 className="text-[28px] font-bold tracking-tight">Words</h1>
        <p className="mt-1.5 max-w-2xl text-sm text-ink-2">
          Every word you looked up or saved, with the sentence you met it in. A browser, not flashcards: saved words come back
          through what you read and watch.
        </p>
      </header>

      <div className="glass flex flex-wrap items-center gap-2 rounded-2xl p-2.5">
        <div role="group" aria-label="Filter words" className="flex flex-wrap gap-1.5">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              type="button"
              aria-pressed={filter === f.key}
              onClick={() => setFilter(f.key)}
              className={cx(
                "min-h-10 rounded-full px-3.5 text-[13px] font-semibold transition",
                filter === f.key ? "border border-white bg-white/16 text-white" : "border border-white/14 text-ink-2 hover:bg-white/8",
              )}
            >
              {f.label}
              {count(f.key) !== undefined && <span className="ml-1.5 text-ink-3">{count(f.key)}</span>}
            </button>
          ))}
        </div>
        <label className="ml-auto flex min-w-[220px] flex-1 items-center gap-2 rounded-xl border border-white/10 bg-black/25 px-3 sm:flex-none">
          <span className="sr-only">Search words</span>
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search words, notes…"
            className="min-h-10 w-full bg-transparent text-sm text-ink outline-none placeholder:text-ink-3"
          />
        </label>
      </div>

      {words.isPending ? (
        <Skeleton className="h-64 rounded-[20px]" />
      ) : words.isError ? (
        <Panel role="alert">Could not load words: {words.error.message}</Panel>
      ) : words.data.items.length === 0 ? (
        <Panel>
          <p className="text-sm text-ink-2">
            {filter === "saved"
              ? "No saved words yet. Open Read, paste a text, click a word and press “Save to my words”."
              : "Nothing here yet."}
          </p>
        </Panel>
      ) : (
        <Panel className="p-2 md:p-3">
          <ul className="flex flex-col">
            {words.data.items.map((item) => (
              <WordRow key={item.lexeme_id} item={item} lang={code} open={openId === item.lexeme_id} onToggle={() => setOpenId(openId === item.lexeme_id ? null : item.lexeme_id)} />
            ))}
          </ul>
          {words.data.total > words.data.items.length && (
            <div className="flex justify-center p-2">
              <Button onClick={() => setLimit(limit + 50)}>Show more ({words.data.total - words.data.items.length} left)</Button>
            </div>
          )}
        </Panel>
      )}
    </div>
  );
}

function WordRow({ item, lang, open, onToggle }: { item: WordListItem; lang: string; open: boolean; onToggle: () => void }) {
  return (
    <li className="border-b border-white/6 last:border-0">
      <button type="button" onClick={onToggle} aria-expanded={open} className="flex w-full items-start gap-3 rounded-xl px-3 py-3 text-left hover:bg-white/5">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-2">
            <span lang={lang} className="text-base font-semibold">
              {item.lemma}
            </span>
            {item.reading && item.reading !== item.lemma && <span className="text-sm text-ink-2">{item.reading}</span>}
            {item.saved && <Chip tone="accent" className="px-2 py-0.5 text-[11px]">saved</Chip>}
          </div>
          {item.latest_sentence && (
            <p lang={lang} className="mt-1 truncate text-sm text-ink-2">
              {item.latest_sentence}
            </p>
          )}
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1 text-xs text-ink-3">
          <span className={cx(item.status === "known" ? "text-good" : item.status === "learning" ? "text-sky-300" : "")}>{STATUS_LABEL[item.status]}</span>
          {item.last_seen_at && <span>{formatDay(localDayOf(item.last_seen_at))}</span>}
        </div>
      </button>
      {open && <WordDetailPanel id={item.lexeme_id} lang={lang} />}
    </li>
  );
}

function WordDetailPanel({ id, lang }: { id: number; lang: string }) {
  const detail = useWord(id);
  const patch = usePatchWord();
  const [note, setNote] = useState("");

  useEffect(() => {
    if (detail.data) setNote(detail.data.user_note ?? "");
  }, [detail.data]);

  if (!detail.data) return <Skeleton className="mx-3 mb-3 h-24" />;
  const word = detail.data;
  return (
    <div className="mx-3 mb-3 flex flex-col gap-3 rounded-xl bg-black/20 p-3">
      <div role="group" aria-label="Status" className="flex flex-wrap gap-1.5">
        {(["learning", "known", "ignored"] as WordStatus[]).map((status) => (
          <button
            key={status}
            type="button"
            aria-pressed={word.status === status}
            onClick={() => patch.mutate({ id, patch: { status } })}
            className={cx(
              "min-h-10 rounded-xl px-3 text-[13px] font-semibold",
              word.status === status ? "border border-white bg-white/16" : "border border-white/14 text-ink-2 hover:bg-white/8",
            )}
          >
            {STATUS_LABEL[status]}
          </button>
        ))}
        <span className="ml-auto self-center text-xs text-ink-3">
          {word.rank ? `rank ${word.rank.toLocaleString("en")} · ` : ""}looked up {word.lookups ?? 0}×
        </span>
      </div>
      {word.contexts_list.length > 0 && (
        <ul className="flex flex-col gap-1.5">
          {word.contexts_list.map((c) => (
            <li key={c.id} lang={lang} className="rounded-lg bg-white/5 px-3 py-2 text-sm text-ink-2">
              {c.sentence}
            </li>
          ))}
        </ul>
      )}
      <label className="flex flex-col gap-1.5 text-xs font-medium text-ink-2">
        Your note
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          maxLength={2000}
          className="min-h-16 rounded-xl border border-white/14 bg-surface p-2 text-sm text-ink"
        />
      </label>
      <div className="flex justify-end">
        <Button disabled={note === (word.user_note ?? "") || patch.isPending} onClick={() => patch.mutate({ id, patch: { note } })}>
          Save note
        </Button>
      </div>
    </div>
  );
}
