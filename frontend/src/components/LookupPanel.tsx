import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import { useAiStatus, useSetStatus } from "../api/hooks";
import type { GrammarBreakdown, LookupResult, WordStatus } from "../api/types";
import { canSpeak, speak } from "../lib/speech";
import { useLookupStore } from "../state/lookup";
import { Icon } from "./Icon";
import { Button, Chip, cx } from "./ui";

const STATUS_BUTTONS: { status: WordStatus; label: string }[] = [
  { status: "seen", label: "New" },
  { status: "learning", label: "Learning" },
  { status: "known", label: "Known" },
  { status: "ignored", label: "Ignore" },
];

export function LookupPanel() {
  const selection = useLookupStore((s) => s.selection);
  const close = useLookupStore((s) => s.close);
  const [result, setResult] = useState<LookupResult | null>(null);
  const [fitting, setFitting] = useState<string | null>(null);
  const lookup = useMutation({ mutationFn: api.lookup, onSuccess: setResult });
  const setStatus = useSetStatus();

  useEffect(() => {
    if (!selection) return;
    setResult(null);
    setFitting(null);
    const { token, lang } = selection;
    lookup.mutate({ lang, lemma: token.lemma, reading: token.reading, pos: token.pos, forms: token.forms, record: token.learnable });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selection?.nonce]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && close();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [close]);

  if (!selection) return null;
  const { token, lang, sentence } = selection;
  const state = result?.state ?? null;
  const currentStatus: WordStatus = state?.status ?? "seen";

  const change = (status: WordStatus, save = false) =>
    setStatus.mutate(
      {
        lang,
        lemma: token.lemma,
        reading: token.reading,
        pos: token.pos,
        status,
        save,
        context:
          save && sentence
            ? { sentence, surface: selection.surface, locator: selection.locator, content_item_id: selection.contentItemId }
            : undefined,
      },
      { onSuccess: (newState) => setResult((prev) => (prev ? { ...prev, state: newState } : prev)) },
    );

  const inflection = result?.inflections[0];
  return (
    <aside
      aria-label="Word lookup"
      className="fixed inset-x-2 bottom-2 z-40 flex max-h-[72dvh] flex-col overflow-hidden rounded-3xl border border-white/16 bg-[#121726]/95 shadow-[0_24px_48px_rgb(0_0_0/0.45)] backdrop-blur-xl md:inset-x-auto md:top-4 md:right-4 md:bottom-4 md:max-h-none md:w-[380px]"
    >
      <div className="flex items-start justify-between gap-3 p-5 pb-3">
        <div className="min-w-0">
          {token.reading && token.reading !== token.display && <div className="text-sm text-ink-2">{token.reading}</div>}
          <div className="flex items-center gap-2">
            <h2 lang={lang} className="truncate text-[26px] font-bold">
              {token.display}
            </h2>
            {canSpeak() && (
              <button
                type="button"
                onClick={() => speak(token.display, lang)}
                aria-label="Play pronunciation"
                className="flex size-10 shrink-0 items-center justify-center rounded-full border border-white/18 bg-white/8 hover:bg-white/14"
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M4 9v6h4l5 4V5L8 9z" />
                  <path d="M16.5 8.5a5 5 0 0 1 0 7" />
                </svg>
              </button>
            )}
          </div>
          <div className="mt-1 flex flex-wrap gap-1.5 text-xs text-ink-3">
            {token.pos && <span>{token.pos.toLowerCase()}</span>}
            {result?.rank && <span>· frequency rank {result.rank.toLocaleString("en")}</span>}
            {state?.lookups ? <span>· looked up {state.lookups}×</span> : null}
          </div>
        </div>
        <button type="button" onClick={close} aria-label="Close lookup" className="flex size-11 shrink-0 items-center justify-center rounded-xl text-ink-2 hover:bg-white/8">
          <Icon name="close" size={20} />
        </button>
      </div>

      <div className="flex flex-col gap-3 overflow-y-auto px-5 pb-5">
        {inflection && inflection.lemma !== inflection.form && (
          <div className="rounded-xl bg-accent/12 px-3 py-2 text-sm">
            <span lang={lang}>{inflection.form}</span> → <strong lang={lang}>{inflection.lemma}</strong>
            {inflection.rules[0] && <span className="text-ink-2"> · {inflection.rules[0]}</span>}
          </div>
        )}

        {token.learnable && (
          <>
            <div role="group" aria-label="Word status" className="flex flex-wrap gap-1.5">
              {STATUS_BUTTONS.map(({ status, label }) => (
                <button
                  key={status}
                  type="button"
                  aria-pressed={currentStatus === status}
                  disabled={setStatus.isPending}
                  onClick={() => change(status)}
                  className={cx(
                    "min-h-10 rounded-xl px-3.5 text-[13px] font-semibold transition",
                    currentStatus === status ? "border border-white bg-white/18 text-white" : "border border-white/14 text-ink-2 hover:bg-white/8",
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
            <Button variant="primary" disabled={setStatus.isPending} onClick={() => change(currentStatus === "known" ? "known" : "learning", true)}>
              {state?.saved ? "Saved · add this sentence too" : "Save to my words, with this sentence"}
            </Button>
          </>
        )}

        {sentence && (
          <SentenceHelp
            key={selection.nonce}
            lang={lang}
            sentence={sentence}
            surface={selection.surface}
            lemma={token.lemma}
            pos={token.pos}
            reading={token.reading}
            onFittingSense={setFitting}
          />
        )}

        {lookup.isPending && <p className="text-sm text-ink-2">Looking up…</p>}
        {lookup.isError && <p role="alert" className="text-sm text-red-200">{lookup.error.message}</p>}
        {result?.missing_dictionary && (
          <p className="well rounded-xl p-3 text-sm text-ink-2">
            No dictionary installed for this language. Import one with <code>lingo dict import</code>.
          </p>
        )}
        {result && !result.missing_dictionary && result.entries.length === 0 && (
          <p className="well rounded-xl p-3 text-sm text-ink-2">No dictionary entry found for this word.</p>
        )}

        {result?.entries.map((entry, index) => (
          <section key={`${entry.term}-${entry.reading}-${index}`} className="well rounded-xl p-3">
            <div className="mb-1.5 flex flex-wrap items-baseline gap-2">
              <span lang={lang} className="font-semibold">
                {entry.term}
              </span>
              {entry.reading && <span className="text-sm text-ink-2">{entry.reading}</span>}
              {entry.pos.slice(0, 3).map((p) => (
                <Chip key={p} className="px-2 py-0.5 text-[11px]">
                  {p}
                </Chip>
              ))}
            </div>
            <ol className="list-decimal pl-5 text-sm leading-relaxed text-ink marker:text-ink-3">
              {entry.glosses.slice(0, 5).map((gloss) => (
                <li key={gloss} className={cx(fitting === gloss && "-mx-1 rounded bg-accent/15 px-1")}>
                  {gloss}
                  {fitting === gloss && <span className="ml-1.5 text-[11px] font-semibold text-accent">fits here</span>}
                </li>
              ))}
            </ol>
            {entry.note && <p className="mt-2 text-xs leading-relaxed text-ink-3">{entry.note}</p>}
            <p className="mt-2 text-[11px] text-ink-3">{entry.dictionary}</p>
          </section>
        ))}

        {result && result.contexts.length > 0 && (
          <section>
            <h3 className="mb-1.5 text-[11px] font-semibold tracking-[0.08em] text-ink-3 uppercase">Your saved sentences</h3>
            <ul className="flex flex-col gap-1.5">
              {result.contexts.map((c) => (
                <li key={c.id} lang={lang} className="well rounded-lg px-3 py-2 text-sm text-ink-2">
                  {c.sentence}
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </aside>
  );
}

interface SentenceHelpProps {
  lang: string;
  sentence: string;
  surface: string;
  lemma: string;
  pos: string;
  reading: string;
  onFittingSense: (gloss: string | null) => void;
}

/** "In this sentence": the meaning here (automatic, cached), translation and grammar on request. */
function SentenceHelp({ lang, sentence, surface, lemma, pos, reading, onFittingSense }: SentenceHelpProps) {
  const status = useAiStatus().data;
  const enabled = status?.context.enabled ?? false;
  const [showTranslation, setShowTranslation] = useState(false);
  const gloss = useQuery({
    queryKey: ["ai-gloss", lang, sentence, surface, lemma],
    queryFn: () => api.aiGloss({ lang, sentence, surface, lemma, pos, reading }),
    enabled,
    staleTime: Infinity,
    retry: false,
  });
  const grammar = useMutation({ mutationFn: () => api.aiGrammar(lang, sentence) });

  useEffect(() => {
    onFittingSense(gloss.data?.fitting_sense ?? null);
  }, [gloss.data, onFittingSense]);

  const translation = gloss.data?.translation || grammar.data?.translation;
  const offReason = status && !status.context.enabled ? status.context.reason : null;
  return (
    <section className="rounded-xl border border-white/10 p-3" aria-label="In this sentence">
      <div className="mb-1 flex items-center justify-between gap-2">
        <h3 className="text-[11px] font-semibold tracking-[0.08em] text-ink-3 uppercase">In this sentence</h3>
        {canSpeak() && (
          <button
            type="button"
            onClick={() => speak(sentence, lang)}
            className="rounded-lg px-2 py-1 text-xs text-ink-2 hover:bg-white/8 hover:text-ink"
            aria-label="Play the sentence"
          >
            ▶ Play
          </button>
        )}
      </div>
      <p lang={lang} className="text-sm leading-relaxed text-ink-2">
        {sentence}
      </p>

      {!status ? null : offReason ? (
        <p className="mt-2 text-[11px] leading-relaxed text-ink-3">
          AI explanations are off ({offReason}). Settings shows how to turn them on.
        </p>
      ) : (
        <div className="mt-3 flex flex-col gap-2.5">
          {gloss.isPending ? (
            <p className="text-sm text-ink-3">Working out the meaning here…</p>
          ) : gloss.isError ? (
            <p className="text-xs text-red-200">{gloss.error.message}</p>
          ) : (
            <div>
              <p className="text-sm">
                <strong lang={lang}>{surface}</strong> here: <span className="text-ink">{gloss.data.meaning}</span>
              </p>
              {gloss.data.note && <p className="mt-1 text-xs leading-relaxed text-ink-2">{gloss.data.note}</p>}
            </div>
          )}

          <div className="flex flex-wrap gap-1.5">
            {translation && (
              <button
                type="button"
                onClick={() => setShowTranslation((v) => !v)}
                aria-expanded={showTranslation}
                className="rounded-lg border border-white/14 px-2.5 py-1.5 text-xs font-semibold text-ink-2 hover:bg-white/8"
              >
                {showTranslation ? "Hide translation" : "Show translation"}
              </button>
            )}
            {!grammar.data && (
              <button
                type="button"
                disabled={grammar.isPending}
                onClick={() => grammar.mutate()}
                className="rounded-lg border border-white/14 px-2.5 py-1.5 text-xs font-semibold text-ink-2 hover:bg-white/8 disabled:opacity-60"
              >
                {grammar.isPending ? "Breaking it down…" : "Break down the grammar"}
              </button>
            )}
          </div>
          {showTranslation && translation && <p className="text-sm leading-relaxed text-ink-2 italic">{translation}</p>}
          {grammar.isError && <p className="text-xs text-red-200">{grammar.error.message}</p>}
          {grammar.data && <GrammarView lang={lang} data={grammar.data} />}
        </div>
      )}
    </section>
  );
}

function GrammarView({ lang, data }: { lang: string; data: GrammarBreakdown }) {
  return (
    <div className="flex flex-col gap-2.5 border-t border-white/8 pt-2.5">
      {data.parts.length > 0 && (
        <ol className="flex flex-wrap gap-1.5" aria-label="Sentence parts">
          {data.parts.map((part, index) => (
            <li key={`${part.text}-${index}`} className="rounded-lg bg-white/6 px-2 py-1">
              <span lang={lang} className="block text-sm font-semibold">
                {part.text}
              </span>
              <span className="block text-[11px] text-ink-2">{part.gloss}</span>
              {part.role && <span className="block text-[10px] tracking-wide text-ink-3 uppercase">{part.role}</span>}
            </li>
          ))}
        </ol>
      )}
      {data.literal && <p className="text-xs text-ink-3">Literally: {data.literal}</p>}
      {data.points.map((point) => (
        <div key={point.name} className="well rounded-lg p-2.5">
          <div className="flex flex-wrap items-center gap-1.5 text-sm font-semibold">
            {point.name}
            {point.level && <Chip className="px-1.5 py-0 text-[10px]">{point.level}</Chip>}
          </div>
          <p className="mt-1 text-xs leading-relaxed text-ink-2">{point.explanation}</p>
        </div>
      ))}
    </div>
  );
}
