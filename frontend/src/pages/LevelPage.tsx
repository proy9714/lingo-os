import { useEffect, useState } from "react";

import { api } from "../api/client";
import { useActiveLanguage, useLevelMutation, useLevelOverview } from "../api/hooks";
import type { CTestResult, CTestStart, DictationStep, LevelOverview, VocabResult, VocabStep } from "../api/types";
import { Button, Chip, Panel, PanelTitle, ProgressBar, Skeleton, cx } from "../components/ui";
import { formatDay, localDayOf } from "../lib/format";
import { canRecognize, canSpeak, speak, useSpeechInput } from "../lib/speech";

type Mode =
  | { kind: "overview" }
  | { kind: "vocab"; id: number; step: VocabStep }
  | { kind: "ctest"; start: CTestStart }
  | { kind: "dictation"; id: number; step: DictationStep }
  | { kind: "speaking"; id: number; step: DictationStep };

export function LevelPage() {
  const { code, language } = useActiveLanguage();
  const overview = useLevelOverview(code);
  const [mode, setMode] = useState<Mode>({ kind: "overview" });
  const startVocab = useLevelMutation(api.vocabTestStart);
  const startCTest = useLevelMutation(api.ctestStart);
  const startDictation = useLevelMutation(api.dictationStart);
  const startSpeaking = useLevelMutation(api.speakingStart);

  useEffect(() => setMode({ kind: "overview" }), [code]);

  if (mode.kind === "speaking") {
    return <SpeakingRunner lang={code} id={mode.id} initial={mode.step} onExit={() => setMode({ kind: "overview" })} />;
  }
  if (mode.kind === "dictation") {
    return <DictationRunner lang={code} id={mode.id} initial={mode.step} onExit={() => setMode({ kind: "overview" })} />;
  }

  if (mode.kind === "vocab") {
    return <VocabTestRunner lang={code} id={mode.id} initial={mode.step} onExit={() => setMode({ kind: "overview" })} />;
  }
  if (mode.kind === "ctest") {
    return <CTestRunner lang={code} start={mode.start} onExit={() => setMode({ kind: "overview" })} />;
  }

  return (
    <div className="flex flex-col gap-4">
      <header className="px-1 pt-1">
        <h1 className="text-[28px] font-bold tracking-tight">Level Lab · {language?.name}</h1>
        <p className="mt-1.5 max-w-2xl text-sm text-ink-2">
          Skills are measured separately, and every result is a range. Short adaptive tests replace the hours-only guess.
        </p>
      </header>
      {overview.isPending ? (
        <Skeleton className="h-72 rounded-[20px]" />
      ) : overview.isError ? (
        <Panel role="alert">Could not load the Level Lab: {overview.error.message}</Panel>
      ) : (
        <div className="grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(min(100%,340px),1fr))]">
          <SummaryCard data={overview.data} />
          <Panel aria-labelledby="t-vocab">
            <PanelTitle id="t-vocab" aside={<Chip>about 5 minutes</Chip>}>
              Vocabulary
            </PanelTitle>
            <VocabSummary data={overview.data} />
            <p className="mt-3 text-sm leading-relaxed text-ink-2">
              Say whether you know each word. Every “yes” is checked with a meaning question, and a few made-up words catch
              guessing. Words get harder or easier as you answer.
            </p>
            {startVocab.isError && <p role="alert" className="mt-2 text-sm text-red-200">{startVocab.error.message}</p>}
            <Button
              variant="primary"
              className="mt-4 w-full"
              disabled={startVocab.isPending}
              onClick={() =>
                startVocab.mutate(code, { onSuccess: (step) => setMode({ kind: "vocab", id: step.assessment_id, step }) })
              }
            >
              {startVocab.isPending ? "Preparing…" : overview.data.skills.vocabulary ? "Retake the vocabulary test" : "Start the vocabulary test"}
            </Button>
          </Panel>
          <Panel aria-labelledby="t-read">
            <PanelTitle id="t-read" aside={<Chip>6–8 minutes</Chip>}>
              Reading (C-test)
            </PanelTitle>
            <CTestSummary data={overview.data} />
            <p className="mt-3 text-sm leading-relaxed text-ink-2">
              Four short texts from A2 to C1. In each, the second half of every second word is missing; type what completes it.
              It is one of the most reliable quick reading measures.
            </p>
            {overview.data.ctest_available ? (
              <>
                {startCTest.isError && <p role="alert" className="mt-2 text-sm text-red-200">{startCTest.error.message}</p>}
                <Button
                  variant="primary"
                  className="mt-4 w-full"
                  disabled={startCTest.isPending}
                  onClick={() => startCTest.mutate(code, { onSuccess: (start) => setMode({ kind: "ctest", start }) })}
                >
                  {overview.data.skills.reading ? "Retake the reading check" : "Start the reading check"}
                </Button>
              </>
            ) : (
              <p className="well mt-4 rounded-xl p-3 text-sm text-ink-2">
                Japanese needs a character-level version of this test; it arrives in a later phase.
              </p>
            )}
          </Panel>
          <Panel aria-labelledby="t-listen">
            <PanelTitle id="t-listen" aside={<Chip>about 6 minutes</Chip>}>
              Listening (dictation)
            </PanelTitle>
            {overview.data.skills.listening?.band ? (
              <p className="text-sm text-ink-2">
                Last result: <strong className="text-ink">{overview.data.skills.listening.band}</strong>
                {overview.data.skills.listening.band_low !== overview.data.skills.listening.band_high &&
                  ` (likely ${overview.data.skills.listening.band_low}–${overview.data.skills.listening.band_high})`}
              </p>
            ) : (
              <p className="text-sm text-ink-3">Not measured yet.</p>
            )}
            <p className="mt-3 text-sm leading-relaxed text-ink-2">
              Ten sentences read aloud by your browser's voice; type what you hear. Sentences get harder after a clean answer.
              Spelling, accents and punctuation don't count.
            </p>
            {startDictation.isError && <p role="alert" className="mt-2 text-sm text-red-200">{startDictation.error.message}</p>}
            <Button
              variant="primary"
              className="mt-4 w-full"
              disabled={startDictation.isPending || !canSpeak()}
              onClick={() =>
                startDictation.mutate(code, {
                  onSuccess: (step) => step.assessment_id && setMode({ kind: "dictation", id: step.assessment_id, step }),
                })
              }
            >
              {canSpeak() ? (overview.data.skills.listening ? "Retake the listening check" : "Start the listening check") : "No browser voice available"}
            </Button>
          </Panel>
          <Panel aria-labelledby="t-speak">
            <PanelTitle id="t-speak" aside={<Chip>about 5 minutes</Chip>}>
              Speaking (repeat after me)
            </PanelTitle>
            {overview.data.skills.speaking?.band ? (
              <p className="text-sm text-ink-2">
                Last result: <strong className="text-ink">{overview.data.skills.speaking.band}</strong>
                {overview.data.skills.speaking.band_low !== overview.data.skills.speaking.band_high &&
                  ` (likely ${overview.data.skills.speaking.band_low}–${overview.data.skills.speaking.band_high})`}
              </p>
            ) : (
              <p className="text-sm text-ink-3">Not measured yet.</p>
            )}
            <p className="mt-3 text-sm leading-relaxed text-ink-2">
              Hear a sentence, then say it back. Longer sentences can only be repeated when you understand and can rebuild
              them, which makes this a good quick measure of speaking. Your browser's speech recognition scores it.
            </p>
            {startSpeaking.isError && <p role="alert" className="mt-2 text-sm text-red-200">{startSpeaking.error.message}</p>}
            <Button
              variant="primary"
              className="mt-4 w-full"
              disabled={startSpeaking.isPending || !canSpeak() || !canRecognize()}
              onClick={() =>
                startSpeaking.mutate(code, {
                  onSuccess: (step) => step.assessment_id && setMode({ kind: "speaking", id: step.assessment_id, step }),
                })
              }
            >
              {!canRecognize()
                ? "Needs speech recognition (Chrome or Edge)"
                : overview.data.skills.speaking
                  ? "Retake the speaking check"
                  : "Start the speaking check"}
            </Button>
          </Panel>
        </div>
      )}
    </div>
  );
}

function SummaryCard({ data }: { data: LevelOverview }) {
  const profile = data.profile;
  const vocab = data.skills.vocabulary?.result;
  return (
    <Panel aria-labelledby="t-summary" className="glass-strong">
      <PanelTitle id="t-summary" aside={<Chip tone={profile?.measured ? "good" : "warn"}>{profile?.measured ? "measured" : "hours only · low confidence"}</Chip>}>
        Where you are
      </PanelTitle>
      {profile?.measured && vocab ? (
        <>
          <div className="text-3xl font-bold">≈ {vocab.vocabulary?.toLocaleString("en")} words</div>
          <p className="mt-1 text-sm text-ink-2">
            90% likely between {vocab.low?.toLocaleString("en")} and {vocab.high?.toLocaleString("en")}
          </p>
          <BandLine band={vocab.band} low={vocab.band_low} high={vocab.band_high} jlpt={vocab.jlpt} jlptLow={vocab.jlpt_low} jlptHigh={vocab.jlpt_high} />
        </>
      ) : (
        <>
          <div className="text-3xl font-bold">≈ {profile?.vocab_size.toLocaleString("en")} words</div>
          <p className="mt-1 text-sm text-ink-2">
            A starting guess from {data.hours_estimate.adjusted_hours} difficulty-adjusted hours (roadmap level {data.hours_estimate.level} of{" "}
            {data.hours_estimate.max_level}). The vocabulary test replaces it with a measurement.
          </p>
        </>
      )}
      {data.skills.reading?.band && (
        <p className="mt-3 text-sm text-ink-2">
          Reading: <strong className="text-ink">{data.skills.reading.band}</strong>
          {data.skills.reading.band_low !== data.skills.reading.band_high && ` (likely ${data.skills.reading.band_low}–${data.skills.reading.band_high})`}
        </p>
      )}
    </Panel>
  );
}

function BandLine(props: { band?: string | null; low?: string | null; high?: string | null; jlpt?: string | null; jlptLow?: string | null; jlptHigh?: string | null }) {
  if (!props.band) return null;
  return (
    <p className="mt-3 text-sm text-ink-2">
      Vocabulary band ≈ <strong className="text-ink">{props.band}</strong>
      {props.low !== props.high && ` (likely ${props.low}–${props.high})`}
      {props.jlpt && (
        <>
          {" "}· JLPT ≈ <strong className="text-ink">{props.jlpt}</strong>
          {props.jlptLow !== props.jlptHigh && ` (${props.jlptLow}–${props.jlptHigh})`}
        </>
      )}
      <span className="block text-xs text-ink-3">Bands from vocabulary size are approximate; listening and speaking are measured separately.</span>
    </p>
  );
}

function VocabSummary({ data }: { data: LevelOverview }) {
  const skill = data.skills.vocabulary;
  if (!skill?.result?.vocabulary) return <p className="text-sm text-ink-3">Not measured yet.</p>;
  return (
    <p className="text-sm text-ink-2">
      Last result: <strong className="text-ink">≈ {skill.result.vocabulary.toLocaleString("en")} words</strong>
      {skill.last_tested_at && ` · ${formatDay(localDayOf(skill.last_tested_at))}`}
    </p>
  );
}

function CTestSummary({ data }: { data: LevelOverview }) {
  const scores = data.skills.reading?.result?.scores;
  if (!scores) return <p className="text-sm text-ink-3">Not measured yet.</p>;
  return (
    <div className="grid grid-cols-4 gap-2 text-center text-xs">
      {Object.entries(scores).map(([level, score]) => (
        <div key={level} className="well rounded-lg p-2">
          <div className="font-semibold text-ink">{Math.round(score * 100)}%</div>
          <div className="text-ink-3">{level}</div>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- vocabulary test

function VocabTestRunner({ lang, id, initial, onExit }: { lang: string; id: number; initial: VocabStep; onExit: () => void }) {
  const [step, setStep] = useState<VocabStep>(initial);
  const answer = useLevelMutation((v: { itemId: number; known: boolean }) => api.vocabTestAnswer(id, v.itemId, v.known));
  const meaning = useLevelMutation((v: { itemId: number; choice: number | null }) => api.vocabTestMeaning(id, v.itemId, v.choice));
  const finish = useLevelMutation(() => api.vocabTestFinish(id));
  const busy = answer.isPending || meaning.isPending || finish.isPending;

  const item = step.done ? null : step.item;

  useEffect(() => {
    if (!item) return;
    const onKey = (event: KeyboardEvent) => {
      if (busy || event.target instanceof HTMLInputElement) return;
      if (item.step === "yesno") {
        if (event.key === "y" || event.key === "ArrowRight") answer.mutate({ itemId: item.id, known: true }, { onSuccess: setStep });
        if (event.key === "n" || event.key === "ArrowLeft") answer.mutate({ itemId: item.id, known: false }, { onSuccess: setStep });
      } else {
        const n = Number(event.key);
        if (n >= 1 && n <= (item.options?.length ?? 0)) meaning.mutate({ itemId: item.id, choice: n - 1 }, { onSuccess: setStep });
        if (event.key === "0") meaning.mutate({ itemId: item.id, choice: null }, { onSuccess: setStep });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [item, busy, answer, meaning]);

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-4">
      <div className="flex items-center justify-between px-1">
        <h1 className="text-xl font-bold">Vocabulary test</h1>
        <Button variant="ghost" onClick={onExit}>
          {step.done ? "Back to Level Lab" : "Leave (not saved)"}
        </Button>
      </div>

      {step.done ? (
        <VocabResultCard step={step} onExit={onExit} />
      ) : (
        item && (
          <Panel className="glass-strong flex flex-col items-center gap-6 py-10 text-center">
            <div className="w-full max-w-sm">
              <ProgressBar value={Math.min(1, item.answered / item.typical_length)} label="Test progress" />
              <p className="mt-2 text-xs text-ink-3">{item.answered} words answered · usually about {item.typical_length}</p>
            </div>
            <div lang={lang} className="text-5xl font-bold tracking-tight">
              {item.word}
            </div>
            {item.step === "yesno" ? (
              <>
                <p className="text-sm text-ink-2">Do you know this word? (Y / N)</p>
                <div className="flex w-full max-w-sm gap-3">
                  <Button className="flex-1" disabled={busy} onClick={() => answer.mutate({ itemId: item.id, known: false }, { onSuccess: setStep })}>
                    No
                  </Button>
                  <Button variant="primary" className="flex-1" disabled={busy} onClick={() => answer.mutate({ itemId: item.id, known: true }, { onSuccess: setStep })}>
                    Yes, I know it
                  </Button>
                </div>
              </>
            ) : (
              <>
                <p className="text-sm text-ink-2">Which meaning is it? (1–4, 0 = not sure)</p>
                <div className="grid w-full max-w-lg gap-2 sm:grid-cols-2">
                  {item.options?.map((option, index) => (
                    <button
                      key={option}
                      type="button"
                      disabled={busy}
                      onClick={() => meaning.mutate({ itemId: item.id, choice: index }, { onSuccess: setStep })}
                      className="min-h-12 rounded-xl border border-white/16 bg-white/6 px-3 py-2 text-left text-sm text-ink transition hover:bg-white/12 disabled:opacity-50"
                    >
                      <span className="mr-2 text-ink-3">{index + 1}</span>
                      {option}
                    </button>
                  ))}
                </div>
                <Button variant="ghost" disabled={busy} onClick={() => meaning.mutate({ itemId: item.id, choice: null }, { onSuccess: setStep })}>
                  I'm not sure
                </Button>
              </>
            )}
            {(answer.isError || meaning.isError) && (
              <p role="alert" className="text-sm text-red-200">{(answer.error ?? meaning.error)?.message}</p>
            )}
            {item.answered >= 10 && (
              <button type="button" disabled={busy} onClick={() => finish.mutate(undefined, { onSuccess: setStep })} className="text-xs text-ink-3 underline hover:text-ink-2">
                Finish now with a wider range
              </button>
            )}
          </Panel>
        )
      )}
    </div>
  );
}

function VocabResultCard({ step, onExit }: { step: Extract<VocabStep, { done: true }>; onExit: () => void }) {
  if (step.abandoned || !step.result) {
    return (
      <Panel>
        <p className="text-sm text-ink-2">{step.reason ?? "The test ended without a result."}</p>
        <Button className="mt-4" onClick={onExit}>
          Back
        </Button>
      </Panel>
    );
  }
  const r: VocabResult = step.result;
  return (
    <Panel className="glass-strong">
      <PanelTitle aside={<Chip tone="good">saved to your profile</Chip>}>Your result</PanelTitle>
      <div className="text-4xl font-bold">≈ {r.vocabulary.toLocaleString("en")} words</div>
      <p className="mt-1 text-sm text-ink-2">
        90% likely between {r.low.toLocaleString("en")} and {r.high.toLocaleString("en")} known words (lemmas)
      </p>
      <BandLine band={r.band} low={r.band_low} high={r.band_high} jlpt={r.jlpt} jlptLow={r.jlpt_low} jlptHigh={r.jlpt_high} />
      <dl className="mt-4 grid grid-cols-3 gap-2 text-center text-sm">
        <div className="well rounded-xl p-3">
          <dt className="text-xs text-ink-3">Words answered</dt>
          <dd className="mt-1 font-semibold">{r.words_answered}</dd>
        </div>
        <div className="well rounded-xl p-3">
          <dt className="text-xs text-ink-3">Made-up words</dt>
          <dd className="mt-1 font-semibold">{r.pseudo_shown}</dd>
        </div>
        <div className={cx("well rounded-xl p-3", r.pseudo_claimed > 0 && "ring-1 ring-orange-300/50")}>
          <dt className="text-xs text-ink-3">…you said you knew</dt>
          <dd className="mt-1 font-semibold">{r.pseudo_claimed}</dd>
        </div>
      </dl>
      <p className="mt-4 text-sm leading-relaxed text-ink-2">
        Words you proved you know are now marked known, so texts are coloured more accurately. Retake the test in a few weeks;
        the range narrows each time.
      </p>
      <Button className="mt-4" onClick={onExit}>
        Back to Level Lab
      </Button>
    </Panel>
  );
}

// ---------------------------------------------------------------- dictation

function DictationRunner({ lang, id, initial, onExit }: { lang: string; id: number; initial: DictationStep; onExit: () => void }) {
  const [step, setStep] = useState<DictationStep>(initial);
  const [typed, setTyped] = useState("");
  const [plays, setPlays] = useState(0);
  const answer = useLevelMutation((v: { itemId: number; typed: string; plays: number }) => api.dictationAnswer(id, v.itemId, v.typed, v.plays));
  const item = step.item;

  const play = () => {
    if (!item || plays >= item.max_plays) return;
    speak(item.speak, lang, 0.95);
    setPlays(plays + 1);
  };

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-4">
      <div className="flex items-center justify-between px-1">
        <h1 className="text-xl font-bold">Listening check</h1>
        <Button variant="ghost" onClick={onExit}>
          {step.done ? "Back to Level Lab" : "Leave (not saved)"}
        </Button>
      </div>
      {step.feedback && (
        <Panel className="py-4">
          <p className="text-xs text-ink-3">Previous sentence · {Math.round(step.feedback.accuracy * 100)}% of words heard</p>
          <p lang={lang} className="mt-1 text-base">
            {step.feedback.sentence}
          </p>
        </Panel>
      )}
      {step.done && step.result ? (
        <Panel className="glass-strong">
          <PanelTitle aside={<Chip tone="good">saved to your profile</Chip>}>Your result</PanelTitle>
          <div className="text-3xl font-bold">Listening ≈ {step.result.band}</div>
          <p className="mt-1 text-sm text-ink-2">
            {step.result.band_low === step.result.band_high ? "Stable band" : `Likely ${step.result.band_low}–${step.result.band_high}`} ·{" "}
            {Math.round(step.result.overall * 100)}% of words heard overall
          </p>
          <div className="mt-4 flex flex-wrap gap-2 text-xs">
            {Object.entries(step.result.averages).map(([level, avg]) => (
              <span key={level} className="well rounded-lg px-3 py-2">
                {level}: <strong className="text-ink">{Math.round(avg * 100)}%</strong>
              </span>
            ))}
          </div>
          <p className="mt-3 text-xs text-ink-3">
            Measured with a synthetic voice at normal speed. Real speakers are harder; the player shows how fast your usual videos are.
          </p>
          <Button className="mt-4" onClick={onExit}>
            Back to Level Lab
          </Button>
        </Panel>
      ) : (
        item && (
          <Panel className="glass-strong flex flex-col items-center gap-5 py-8 text-center">
            <div className="w-full max-w-sm">
              <ProgressBar value={(item.seq - 1) / item.total} label="Listening check progress" />
              <p className="mt-2 text-xs text-ink-3">
                Sentence {item.seq} of {item.total}
              </p>
            </div>
            <Button variant="primary" onClick={play} disabled={plays >= item.max_plays} className="min-w-48">
              {plays === 0 ? "▶ Play the sentence" : plays < item.max_plays ? `Play again (${item.max_plays - plays} left)` : "No plays left"}
            </Button>
            <form
              className="flex w-full flex-col gap-3"
              onSubmit={(event) => {
                event.preventDefault();
                answer.mutate(
                  { itemId: item.id, typed, plays },
                  {
                    onSuccess: (next) => {
                      setStep(next);
                      setTyped("");
                      setPlays(0);
                    },
                  },
                );
              }}
            >
              <label className="sr-only" htmlFor="dictation-input">
                What you heard
              </label>
              <textarea
                id="dictation-input"
                lang={lang}
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                rows={2}
                placeholder="Type what you heard…"
                className="w-full rounded-xl border border-white/14 bg-surface p-3 text-base text-ink placeholder:text-ink-3"
              />
              <Button type="submit" variant="primary" disabled={answer.isPending || plays === 0}>
                {answer.isPending ? "Checking…" : "Check and continue"}
              </Button>
              {answer.isError && <p role="alert" className="text-sm text-red-200">{answer.error.message}</p>}
            </form>
          </Panel>
        )
      )}
    </div>
  );
}

// ---------------------------------------------------------------- C-test

function CTestRunner({ lang, start, onExit }: { lang: string; start: CTestStart; onExit: () => void }) {
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [result, setResult] = useState<CTestResult | null>(null);
  const submit = useLevelMutation((v: Record<number, string>) => api.ctestSubmit(start.assessment_id, v));
  const gapCount = start.passages.reduce((n, p) => n + p.segments.filter((s) => s.gap !== undefined).length, 0);
  const filled = Object.values(answers).filter((v) => v.trim()).length;
  const wrong = result ? new Map(result.review.filter((r) => r.score < 1).map((r) => [r.id, r])) : null;

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
      <div className="flex items-center justify-between px-1">
        <h1 className="text-xl font-bold">Reading check (C-test)</h1>
        <Button variant="ghost" onClick={onExit}>
          {result ? "Back to Level Lab" : "Leave (not saved)"}
        </Button>
      </div>
      {!result && (
        <p className="px-1 text-sm text-ink-2">
          Complete each word: type only the missing letters. Passages get harder; skip what you can't do.
        </p>
      )}

      {result && (
        <Panel className="glass-strong">
          <PanelTitle aside={<Chip tone="good">saved to your profile</Chip>}>Your result</PanelTitle>
          <div className="text-3xl font-bold">Reading ≈ {result.result.band}</div>
          <p className="mt-1 text-sm text-ink-2">
            {result.result.band_low === result.result.band_high ? "Stable band" : `Likely ${result.result.band_low}–${result.result.band_high}`} ·{" "}
            {Math.round(result.result.overall * 100)}% of gaps correct
          </p>
          <div className="mt-4 grid grid-cols-4 gap-2 text-center text-xs">
            {Object.entries(result.result.scores).map(([level, score]) => (
              <div key={level} className={cx("well rounded-lg p-2", score >= 0.6 && "ring-1 ring-emerald-300/50")}>
                <div className="text-base font-semibold text-ink">{Math.round(score * 100)}%</div>
                <div className="text-ink-3">{level}</div>
              </div>
            ))}
          </div>
          <p className="mt-3 text-xs text-ink-3">A level counts as passed at 60%. Corrections are shown in the texts below.</p>
        </Panel>
      )}

      {start.passages.map((passage) => (
        <article key={passage.level} className="rounded-[20px] bg-[#f6f2ea] px-5 py-6 text-[#1f1d1a] md:px-8">
          <div className="mb-3 text-xs font-semibold tracking-[0.08em] text-[#6b6357] uppercase">Text {passage.level}</div>
          <p lang={lang} className="text-[17px] leading-[2.3]">
            {passage.segments.map((segment, index) =>
              segment.gap === undefined ? (
                <span key={index}>{segment.text}</span>
              ) : (
                <span key={index} className="whitespace-nowrap">
                  {segment.shown}
                  <input
                    aria-label={`Complete the word starting “${segment.shown}”`}
                    value={answers[segment.gap] ?? ""}
                    disabled={Boolean(result)}
                    onChange={(e) => setAnswers({ ...answers, [segment.gap as number]: e.target.value })}
                    autoComplete="off"
                    autoCapitalize="off"
                    spellCheck={false}
                    style={{ width: `${(segment.size ?? 3) + 1.5}ch` }}
                    className={cx(
                      "mx-px rounded border-b-2 border-[#8a7f6d] bg-white/70 px-1 font-mono text-[15px] text-[#1f1d1a] outline-none focus:border-[#b8700f] focus:bg-white",
                      wrong?.has(segment.gap) && "border-red-500 bg-red-50",
                    )}
                  />
                  {wrong?.has(segment.gap) && (
                    <span className="ml-1 rounded bg-emerald-100 px-1 text-[13px] text-emerald-900">{wrong.get(segment.gap)?.expected}</span>
                  )}
                </span>
              ),
            )}
          </p>
        </article>
      ))}

      {!result && (
        <div className="glass sticky bottom-24 flex items-center justify-between gap-3 rounded-2xl p-3 md:bottom-4">
          <span className="text-sm text-ink-2">
            {filled} of {gapCount} filled
          </span>
          {submit.isError && <span className="text-sm text-red-200">{submit.error.message}</span>}
          <Button variant="primary" disabled={submit.isPending} onClick={() => submit.mutate(answers, { onSuccess: setResult })}>
            {submit.isPending ? "Scoring…" : "Submit and see my level"}
          </Button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- speaking (elicited imitation)

function SpeakingRunner({ lang, id, initial, onExit }: { lang: string; id: number; initial: DictationStep; onExit: () => void }) {
  const [step, setStep] = useState<DictationStep>(initial);
  const [plays, setPlays] = useState(0);
  const [said, setSaid] = useState<string | null>(null);
  const voice = useSpeechInput(lang);
  const answer = useLevelMutation((v: { itemId: number; typed: string; plays: number }) => api.dictationAnswer(id, v.itemId, v.typed, v.plays));
  const item = step.item;

  const play = () => {
    if (!item || plays >= item.max_plays || voice.listening) return;
    speak(item.speak, lang, 0.95);
    setPlays(plays + 1);
  };

  const toggle = async () => {
    if (voice.listening) setSaid(await voice.stop());
    else {
      setSaid(null);
      voice.start();
    }
  };

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-4">
      <div className="flex items-center justify-between px-1">
        <h1 className="text-xl font-bold">Speaking check</h1>
        <Button variant="ghost" onClick={onExit}>
          {step.done ? "Back to Level Lab" : "Leave (not saved)"}
        </Button>
      </div>
      {step.feedback && (
        <Panel className="py-4">
          <p className="text-xs text-ink-3">Previous sentence · {Math.round(step.feedback.accuracy * 100)}% repeated</p>
          <p lang={lang} className="mt-1 text-base">
            {step.feedback.sentence}
          </p>
        </Panel>
      )}
      {step.done && step.result ? (
        <Panel className="glass-strong">
          <PanelTitle aside={<Chip tone="good">saved to your profile</Chip>}>Your result</PanelTitle>
          <div className="text-3xl font-bold">Speaking ≈ {step.result.band}</div>
          <p className="mt-1 text-sm text-ink-2">
            {step.result.band_low === step.result.band_high ? "Stable band" : `Likely ${step.result.band_low}–${step.result.band_high}`} ·{" "}
            {Math.round(step.result.overall * 100)}% repeated overall
          </p>
          <div className="mt-4 flex flex-wrap gap-2 text-xs">
            {Object.entries(step.result.averages).map(([level, avg]) => (
              <span key={level} className="well rounded-lg px-3 py-2">
                {level}: <strong className="text-ink">{Math.round(avg * 100)}%</strong>
              </span>
            ))}
          </div>
          <p className="mt-3 text-xs text-ink-3">
            Repetition measures how much you can hold and rebuild, not free conversation; the tutor's reviews add that side.
            Recognition errors can lower a score slightly.
          </p>
          <Button className="mt-4" onClick={onExit}>
            Back to Level Lab
          </Button>
        </Panel>
      ) : (
        item && (
          <Panel className="glass-strong flex flex-col items-center gap-5 py-8 text-center">
            <div className="w-full max-w-sm">
              <ProgressBar value={(item.seq - 1) / item.total} label="Speaking check progress" />
              <p className="mt-2 text-xs text-ink-3">
                Sentence {item.seq} of {item.total}
              </p>
            </div>
            <Button onClick={play} disabled={plays >= item.max_plays || voice.listening} className="min-w-48">
              {plays === 0 ? "▶ Hear the sentence" : plays < item.max_plays ? `Hear again (${item.max_plays - plays} left)` : "No plays left"}
            </Button>
            <Button variant="primary" className="min-w-48" disabled={plays === 0 || answer.isPending} onClick={toggle} aria-pressed={voice.listening}>
              {voice.listening ? "■ Done" : said !== null ? "● Say it again" : "● Say it back"}
            </Button>
            <p lang={lang} className="min-h-6 text-base text-ink-2">
              {voice.listening ? voice.text || "Listening…" : said ?? ""}
            </p>
            {voice.error && <p role="alert" className="text-sm text-red-200">{voice.error}</p>}
            <Button
              disabled={said === null || voice.listening || answer.isPending}
              onClick={() =>
                answer.mutate(
                  { itemId: item.id, typed: said ?? "", plays },
                  {
                    onSuccess: (next) => {
                      setStep(next);
                      setSaid(null);
                      setPlays(0);
                    },
                  },
                )
              }
            >
              {answer.isPending ? "Checking…" : "Check and continue"}
            </Button>
            {answer.isError && <p role="alert" className="text-sm text-red-200">{answer.error.message}</p>}
          </Panel>
        )
      )}
    </div>
  );
}
