import { useEffect, useMemo, useState, type ReactNode } from "react";

import { ApiError } from "../api/client";
import { useActiveLanguage, useAnnotation, useGrammarReference } from "../api/hooks";
import type { GrammarExample, GrammarKind, GrammarSection, GrammarTable } from "../api/types";
import { TokenLine } from "../components/TokenLine";
import { Skeleton, Tabs, cx } from "../components/ui";
import { canSpeak, speak } from "../lib/speech";

const KINDS: Record<GrammarKind, { label: string; badge: string; accent: string; box: string; mark: string }> = {
  structure: {
    label: "Structure & mechanics",
    badge: "bg-sky-500/25 text-sky-100",
    accent: "border-sky-400/50",
    box: "bg-sky-400/[0.07]",
    mark: "text-sky-300",
  },
  verbs: {
    label: "Verb forms",
    badge: "bg-amber-500/25 text-amber-100",
    accent: "border-amber-400/50",
    box: "bg-amber-400/[0.07]",
    mark: "text-amber-300",
  },
  contrast: {
    label: "Watch-out contrasts",
    badge: "bg-rose-500/25 text-rose-100",
    accent: "border-rose-400/50",
    box: "bg-rose-400/[0.07]",
    mark: "text-rose-300",
  },
  summary: {
    label: "Summary",
    badge: "bg-emerald-500/25 text-emerald-100",
    accent: "border-emerald-400/50",
    box: "bg-emerald-400/[0.07]",
    mark: "text-emerald-300",
  },
};

export function GrammarPage() {
  const { code, languages } = useActiveLanguage();
  const tabs = languages.map((l) => ({ value: l.code, label: l.name }));
  const [lang, setLang] = useState(code);
  const languageName = languages.find((l) => l.code === lang)?.name ?? "this language";
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<GrammarKind | "all">("all");
  const reference = useGrammarReference(lang);

  useEffect(() => setLang(code), [code]); // follows the language switcher

  const q = query.trim().toLowerCase();
  const sections = useMemo(() => {
    const all = reference.data?.sections ?? [];
    return all.filter((s) => {
      if (kind !== "all" && s.kind !== kind) return false;
      if (!q) return true;
      const haystack = [s.title, s.text, s.rule, s.after, ...s.tags, ...s.examples.map((e) => `${e.text} ${e.translation}`)]
        .join(" ")
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [reference.data, kind, q]);

  const byId = useMemo(() => new Map((reference.data?.sections ?? []).map((s) => [s.id, s])), [reference.data]);

  return (
    <div className="flex flex-col gap-5">
      <header className="flex flex-col gap-4 px-1 pt-1">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-[28px] font-bold tracking-tight md:text-[34px]">Grammar</h1>
            <p className="mt-1.5 max-w-3xl text-sm leading-relaxed text-ink-2">
              {reference.data?.intro ??
                "A working reference for beginners to intermediate learners: every pattern with real sentences and a translation."}
            </p>
          </div>
          {tabs.length > 1 && <Tabs label="Language" value={lang} onChange={setLang} items={tabs} />}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex min-w-[260px] flex-1 items-center gap-2 rounded-2xl border border-white/12 bg-black/25 px-4 sm:max-w-md">
            <span aria-hidden="true" className="text-ink-3">
              ⌕
            </span>
            <span className="sr-only">Search the grammar</span>
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search: dative, ser, て form, past tense…"
              className="min-h-11 w-full bg-transparent text-sm text-ink outline-none placeholder:text-ink-3"
            />
          </label>
          <div role="group" aria-label="Show" className="flex flex-wrap gap-1.5">
            {(["all", "structure", "verbs", "contrast"] as const).map((k) => (
              <button
                key={k}
                type="button"
                aria-pressed={kind === k}
                onClick={() => setKind(k)}
                className={cx(
                  "flex min-h-10 items-center gap-2 rounded-xl border px-3 text-xs font-semibold transition",
                  kind === k ? "border-white/30 bg-white/12 text-ink" : "border-white/10 text-ink-2 hover:bg-white/6",
                )}
              >
                {k !== "all" && <span aria-hidden="true" className={cx("size-2.5 rounded-sm", KINDS[k].badge)} />}
                {k === "all" ? "All" : KINDS[k].label}
              </button>
            ))}
          </div>
        </div>
      </header>

      {reference.isPending ? (
        <Skeleton className="h-96 rounded-[20px]" />
      ) : reference.isError ? (
        reference.error instanceof ApiError && reference.error.status === 404 ? (
          <p className="rounded-2xl border border-white/10 bg-white/[0.035] p-5 text-sm text-ink-2">
            A grammar reference for {languageName} isn't written yet. Until it is, the tutor's notes and the lookup panel's grammar
            breakdown (with an AI key) cover {languageName} too.
          </p>
        ) : (
          <p role="alert" className="rounded-2xl bg-red-500/10 p-4 text-sm text-red-200">
            Could not load the grammar: {reference.error.message}
          </p>
        )
      ) : (
        <>
          {reference.data.weak_spots.length > 0 && kind === "all" && !q && (
            <section aria-label="From your tutor" className="rounded-[20px] border border-accent/25 bg-accent/[0.06] p-5">
              <h2 className="text-sm font-semibold text-accent">From your tutor conversations: still worth a look</h2>
              <ul className="mt-3 flex flex-col gap-2 text-sm">
                {reference.data.weak_spots.map((spot) => (
                  <li key={spot.key} className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                    <span className="font-semibold text-ink">{spot.title}</span>
                    <span className="text-xs text-ink-3">
                      {spot.errors} slip{spot.errors === 1 ? "" : "s"}
                      {spot.example && ` · e.g. ${spot.example}`}
                    </span>
                    {spot.sections.map((id) => (
                      <a key={id} href={`#g-${id}`} className="text-xs font-semibold text-accent hover:underline">
                        → {byId.get(id)?.number}. {byId.get(id)?.title}
                      </a>
                    ))}
                  </li>
                ))}
              </ul>
            </section>
          )}

          <div className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[250px_minmax(0,1fr)]">
            <nav aria-label="Grammar topics" className="lg:sticky lg:top-4 lg:max-h-[calc(100dvh-2rem)] lg:self-start lg:overflow-y-auto">
              <ol className="flex gap-1.5 overflow-x-auto pb-1 lg:flex-col lg:overflow-visible lg:pb-0">
                {reference.data.sections.map((s) => (
                  <li key={s.id} className="shrink-0">
                    <a
                      href={`#g-${s.id}`}
                      className={cx(
                        "flex items-center gap-2.5 rounded-xl px-2.5 py-1.5 text-sm text-ink-2 transition hover:bg-white/8 hover:text-ink",
                        !sections.includes(s) && "opacity-35",
                      )}
                    >
                      <span className={cx("flex size-6 shrink-0 items-center justify-center rounded-md text-[11px] font-bold", KINDS[s.kind].badge)}>
                        {s.number}
                      </span>
                      <span className="truncate">{s.title}</span>
                    </a>
                  </li>
                ))}
              </ol>
            </nav>

            <div className="flex min-w-0 flex-col gap-5">
              {sections.length === 0 && (
                <p className="rounded-2xl border border-white/10 bg-white/[0.04] p-5 text-sm text-ink-2">Nothing matches “{query}”.</p>
              )}
              {sections.map((s) => (
                <Section key={`${lang}-${s.id}`} lang={lang} section={s} />
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- one section

function Section({ lang, section }: { lang: string; section: GrammarSection }) {
  const kind = KINDS[section.kind];
  return (
    <section
      id={`g-${section.id}`}
      aria-labelledby={`gh-${section.id}`}
      // sections off screen aren't laid out until you scroll near them: long references open fast on a phone
      className="scroll-mt-4 rounded-[20px] border border-white/10 bg-white/[0.04] p-5 [contain-intrinsic-size:auto_640px] [content-visibility:auto] md:p-7"
    >
      <div className="flex flex-wrap items-center gap-3">
        <span className={cx("flex size-8 items-center justify-center rounded-lg text-sm font-bold", kind.badge)}>{section.number}</span>
        <h2 id={`gh-${section.id}`} className="font-serif text-xl font-bold tracking-tight md:text-2xl">
          {section.title}
        </h2>
        {section.level && section.level !== "all" && (
          <span className="rounded-full border border-white/12 px-2 py-0.5 text-[11px] font-semibold text-ink-3">{section.level}</span>
        )}
        <span className="ml-auto hidden text-[11px] font-semibold tracking-[0.12em] text-ink-3 uppercase sm:inline">{kind.label}</span>
      </div>

      <div className="mt-4 flex flex-col gap-4 text-[15px] leading-relaxed text-ink-2">
        {section.rule && <p className={cx("max-w-3xl rounded-xl px-4 py-3 text-sm text-ink", kind.box)}>{rich(section.rule)}</p>}
        {section.tables.map((table, n) => (
          <Table key={n} lang={lang} table={table} mark={kind.mark} />
        ))}
        {section.text && <p className="max-w-3xl">{rich(section.text)}</p>}
        {section.after && <p className="max-w-3xl">{rich(section.after)}</p>}
        {section.points.length > 0 && (
          <ul className="flex max-w-3xl flex-col gap-2">
            {section.points.map((point) => (
              <li key={point} className="flex gap-2.5">
                <span aria-hidden="true" className={cx("mt-0.5 font-bold", kind.mark)}>
                  ✓
                </span>
                <span>{rich(point)}</span>
              </li>
            ))}
          </ul>
        )}
        {section.tip && <p className={cx("max-w-3xl rounded-xl px-4 py-3 text-sm text-ink", kind.box)}>{rich(section.tip)}</p>}
        {section.examples.length > 0 && (
          <div className={cx("max-w-3xl rounded-2xl border-t-2 bg-black/25 p-4", kind.accent)}>
            <h3 className="text-[11px] font-bold tracking-[0.14em] text-ink-3 uppercase">In use</h3>
            <ul className="mt-2 divide-y divide-dashed divide-white/10">
              {section.examples.map((example) => (
                <Example key={example.text} lang={lang} example={example} />
              ))}
            </ul>
          </div>
        )}
      </div>
    </section>
  );
}

/** **bold** in explanations. */
function rich(value: string): ReactNode {
  return value.split(/(\*\*[^*]+\*\*)/g).map((part, n) =>
    part.startsWith("**") && part.endsWith("**") ? (
      <strong key={n} className="font-semibold text-ink">
        {part.slice(2, -2)}
      </strong>
    ) : (
      part
    ),
  );
}

/** {…} marks an ending in a table cell. */
function marked(value: string, mark: string): ReactNode {
  return value.split(/(\{[^}]+\})/g).map((part, n) =>
    part.startsWith("{") && part.endsWith("}") ? (
      <strong key={n} className={cx("font-bold", mark)}>
        {part.slice(1, -1)}
      </strong>
    ) : (
      part
    ),
  );
}

function Cell({ lang, value, mark, first }: { lang: string; value: string; mark: string; first: boolean }) {
  const pairs = value.split(" ;; ");
  return (
    <div className="flex flex-col gap-1.5">
      {pairs.map((pair, n) => {
        const [target, translation] = pair.split(" | ");
        return (
          <div key={n}>
            <span lang={first ? undefined : lang} className="text-ink">
              {marked(target, mark)}
            </span>
            {translation && <span className="block text-[13px] text-ink-3 italic">— {translation}</span>}
          </div>
        );
      })}
    </div>
  );
}

function Table({ lang, table, mark }: { lang: string; table: GrammarTable; mark: string }) {
  return (
    <div>
      {table.caption && <p className="mb-1.5 text-xs font-semibold text-ink-3">{table.caption}</p>}
      <div className="overflow-x-auto rounded-xl border border-white/8">
        <table className="w-full min-w-[480px] border-collapse text-left text-sm">
          <thead>
            <tr className="border-b border-white/12 bg-white/[0.03]">
              {table.head.map((h, n) => {
                const [label, meaning] = h.split(" | ");
                return (
                  <th key={n} scope="col" className="px-3 py-2.5 align-bottom text-xs font-semibold text-ink-2">
                    {label}
                    {meaning && <span className="block font-normal text-ink-3 italic">{meaning}</span>}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody className="divide-y divide-white/8">
            {table.rows.map((row, r) => (
              <tr key={r}>
                {row.map((cell, c) =>
                  c === 0 ? (
                    <th key={c} scope="row" className="px-3 py-2.5 align-top font-medium text-ink-2">
                      <Cell lang={lang} value={cell} mark={mark} first />
                    </th>
                  ) : (
                    <td key={c} className="px-3 py-2.5 align-top">
                      <Cell lang={lang} value={cell} mark={mark} first={false} />
                    </td>
                  ),
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- examples: listen, look words up

function Example({ lang, example }: { lang: string; example: GrammarExample }) {
  const [words, setWords] = useState(false);
  return (
    <li className="flex gap-3 py-2.5">
      <div className="min-w-0 flex-1">
        <p lang={lang} className="text-[15px] font-semibold text-ink">
          {words ? <ClickableSentence lang={lang} text={example.text} /> : example.text}
        </p>
        {example.reading && (
          <p lang={lang} className="text-xs text-ink-3">
            {example.reading}
          </p>
        )}
        <p className="text-sm text-ink-3 italic">
          — {example.translation}
          {example.note && <span className="not-italic text-ink-3"> ({example.note})</span>}
        </p>
      </div>
      <div className="flex shrink-0 items-start gap-1">
        {canSpeak() && (
          <button
            type="button"
            onClick={() => speak(example.text, lang)}
            aria-label={`Listen: ${example.text}`}
            title="Listen"
            className="flex size-9 items-center justify-center rounded-lg text-ink-3 transition hover:bg-white/10 hover:text-ink"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
              <path d="M4 9v6h4l5 4V5L8 9H4zM16.5 8.5a5 5 0 0 1 0 7M19 6a8.5 8.5 0 0 1 0 12" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        )}
        <button
          type="button"
          aria-pressed={words}
          onClick={() => setWords((v) => !v)}
          title="Look up the words"
          className={cx(
            "flex h-9 items-center rounded-lg px-2 text-xs font-semibold transition",
            words ? "bg-accent/20 text-accent" : "text-ink-3 hover:bg-white/10 hover:text-ink",
          )}
        >
          Aa
        </button>
      </div>
    </li>
  );
}

function ClickableSentence({ lang, text }: { lang: string; text: string }) {
  const annotation = useAnnotation(lang, text);
  if (!annotation.data) return <>{text}</>;
  return <TokenLine lang={lang} text={text} tokens={annotation.data.tokens} sentence={text} locator="grammar" theme="dark" />;
}
