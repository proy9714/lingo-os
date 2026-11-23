import { useMutation } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import { useSetStatus } from "../api/hooks";
import type { LookupResult, WordStatus } from "../api/types";
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
  const lookup = useMutation({ mutationFn: api.lookup, onSuccess: setResult });
  const setStatus = useSetStatus();

  useEffect(() => {
    if (!selection) return;
    setResult(null);
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
                <li key={gloss}>{gloss}</li>
              ))}
            </ol>
            {entry.note && <p className="mt-2 text-xs leading-relaxed text-ink-3">{entry.note}</p>}
            <p className="mt-2 text-[11px] text-ink-3">{entry.dictionary}</p>
          </section>
        ))}

        {sentence && (
          <section className="rounded-xl border border-white/10 p-3">
            <h3 className="mb-1 text-[11px] font-semibold tracking-[0.08em] text-ink-3 uppercase">In this sentence</h3>
            <p lang={lang} className="text-sm leading-relaxed text-ink-2">
              {sentence}
            </p>
            <p className="mt-2 text-[11px] text-ink-3">An AI explanation of the meaning here arrives in Phase 4.</p>
          </section>
        )}

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
