import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";

import { api } from "../../api/client";
import { useTutorGrammar, useTutorOptions, useTutorSessions, useTutorTopics } from "../../api/hooks";
import type { TutorMessage, TutorMode, TutorSession } from "../../api/types";
import { formatDay, localDayOf } from "../../lib/format";
import { canSpeak, speak, stopSpeaking, useSpeechInput } from "../../lib/speech";
import { useEngagement } from "../../lib/useEngagement";
import { useTracker } from "../../lib/useTracker";
import { TokenLine } from "../TokenLine";
import { Button, Chip, Panel, PanelTitle, Skeleton, cx } from "../ui";

const MODE_LABELS: Record<TutorMode, string> = {
  conversation: "Conversation",
  roleplay: "Role-play",
  content_discussion: "Talk about something",
  correction_drill: "Grammar practice",
};

function storedFlag(key: string, fallback: boolean): boolean {
  try {
    const v = window.localStorage.getItem(key);
    return v === null ? fallback : v === "1";
  } catch {
    return fallback;
  }
}

export function TutorPanel({ lang }: { lang: string }) {
  const options = useTutorOptions(lang);
  const [session, setSession] = useState<TutorSession | null>(null);
  const qc = useQueryClient();
  const start = useMutation({
    mutationFn: api.tutorStart,
    onSuccess: (data) => {
      setSession(data);
      void qc.invalidateQueries({ queryKey: ["tutor-sessions"] });
    },
  });

  useEffect(() => setSession(null), [lang]);

  if (session) {
    return (
      <ChatView
        key={session.id}
        lang={lang}
        initial={session}
        speechRate={options.data?.speech_rate ?? 0.9}
        onClose={() => {
          setSession(null);
          void qc.invalidateQueries({ queryKey: ["tutor-sessions"] });
          void qc.invalidateQueries({ queryKey: ["tutor-grammar"] });
        }}
      />
    );
  }

  if (options.isPending) return <Skeleton className="h-72 rounded-[20px]" />;
  if (options.isError) return <Panel role="alert">Could not load the tutor: {options.error.message}</Panel>;
  const status = options.data.status;

  return (
    <div className="flex flex-col gap-4">
      {!status.enabled && (
        <Panel className="glass-strong">
          <PanelTitle>The tutor needs an AI model</PanelTitle>
          <p className="text-sm leading-relaxed text-ink-2">
            It's off right now. Paste a Gemini, Claude or ChatGPT key in{" "}
            <Link to="/settings" className="text-accent underline">Settings → AI explanations</Link>; it works at once. The
            Shadowing tab works without it.
          </p>
        </Panel>
      )}
      {start.isError && (
        <Panel role="alert">
          <p className="text-sm text-red-200">{start.error.message}</p>
        </Panel>
      )}
      <div className="grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr))]">
        <StartCard
          lang={lang}
          disabled={!status.enabled || start.isPending}
          pending={start.isPending}
          scenarios={options.data.scenarios}
          weakGrammar={options.data.weak_grammar}
          onStart={(mode, extra) => start.mutate({ lang, mode, ...extra })}
        />
        <div className="flex flex-col gap-4">
          <PastSessions lang={lang} onOpen={async (id) => setSession(await api.tutorSession(id))} />
          <GrammarCard lang={lang} />
        </div>
      </div>
    </div>
  );
}

function StartCard({
  lang,
  disabled,
  pending,
  scenarios,
  weakGrammar,
  onStart,
}: {
  lang: string;
  disabled: boolean;
  pending: boolean;
  scenarios: { id: string; title: string }[];
  weakGrammar: string[];
  onStart: (mode: TutorMode, extra?: { scenario?: string; content_item_id?: number }) => void;
}) {
  const recent = useTutorTopics(lang).data ?? [];
  const [itemId, setItemId] = useState<string>("");

  return (
    <Panel aria-labelledby="t-tutor-start">
      <PanelTitle id="t-tutor-start" aside={pending && <Chip>starting…</Chip>}>
        Start a conversation
      </PanelTitle>
      <div className="flex flex-col gap-4">
        <div>
          <Button variant="primary" className="w-full" disabled={disabled} onClick={() => onStart("conversation")}>
            Just chat
          </Button>
          <p className="mt-1.5 text-xs text-ink-3">Relaxed conversation at your level. It reuses words you're learning.</p>
        </div>
        <div>
          <h3 className="mb-2 text-xs font-semibold text-ink-2">Role-play</h3>
          <div className="grid gap-2 sm:grid-cols-2">
            {scenarios.map((s) => (
              <button
                key={s.id}
                type="button"
                disabled={disabled}
                onClick={() => onStart("roleplay", { scenario: s.id })}
                className="well min-h-11 rounded-xl px-3 py-2 text-left text-sm hover:bg-white/10 disabled:opacity-50"
              >
                {s.title}
              </button>
            ))}
          </div>
        </div>
        <div>
          <h3 className="mb-2 text-xs font-semibold text-ink-2">Talk about something you watched or read</h3>
          <p className="-mt-1 mb-2 text-xs text-ink-3">Your last {recent.length || 10} videos and texts, most recent first.</p>
          <div className="flex gap-2">
            <select
              value={itemId}
              onChange={(e) => setItemId(e.target.value)}
              aria-label="Choose a video or text"
              className="min-h-11 min-w-0 flex-1 rounded-xl border border-white/14 bg-surface px-2 text-sm text-ink"
            >
              <option value="">{recent.length ? "Choose a video or text…" : "Watch or read something first"}</option>
              {recent.map((i) => (
                <option key={i.id} value={i.id}>
                  {i.kind === "video" ? "Video" : "Read"} · {i.title.slice(0, 70)}
                  {i.last_at ? ` (${formatDay(localDayOf(i.last_at))})` : ""}
                </option>
              ))}
            </select>
            <Button disabled={disabled || !itemId} onClick={() => onStart("content_discussion", { content_item_id: Number(itemId) })}>
              Start
            </Button>
          </div>
        </div>
        <div>
          <Button className="w-full" disabled={disabled} onClick={() => onStart("correction_drill")}>
            Grammar practice
          </Button>
          <p className="mt-1.5 text-xs text-ink-3">
            {weakGrammar.length > 0
              ? `Works on: ${weakGrammar.join(", ")}.`
              : "Your weak spots appear here after a few conversations; until then it practises everyday patterns."}
          </p>
        </div>
      </div>
    </Panel>
  );
}

function PastSessions({ lang, onOpen }: { lang: string; onOpen: (id: number) => void }) {
  const sessions = useTutorSessions(lang).data;
  return (
    <Panel aria-labelledby="t-tutor-past">
      <PanelTitle id="t-tutor-past">Past conversations</PanelTitle>
      {!sessions ? (
        <Skeleton className="h-20" />
      ) : sessions.length === 0 ? (
        <p className="text-sm text-ink-3">None yet.</p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {sessions.slice(0, 8).map((s) => (
            <li key={s.id}>
              <button type="button" onClick={() => onOpen(s.id)} className="well w-full rounded-xl px-3 py-2 text-left hover:bg-white/10">
                <div className="flex items-center justify-between gap-2 text-sm">
                  <span className="font-semibold">{s.title ?? MODE_LABELS[s.mode]}</span>
                  <span className="text-xs text-ink-3">{formatDay(localDayOf(s.started_at))}</span>
                </div>
                <div className="mt-0.5 line-clamp-2 text-xs text-ink-2">
                  {s.summary_md ?? `${s.turns} of your turns${s.ended_at ? "" : " · not ended"}`}
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function GrammarCard({ lang }: { lang: string }) {
  const rows = useTutorGrammar(lang).data;
  if (!rows || rows.length === 0) return null;
  return (
    <Panel aria-labelledby="t-grammar">
      <PanelTitle id="t-grammar">Grammar to watch</PanelTitle>
      <ul className="flex flex-col gap-2">
        {rows.slice(0, 6).map((g) => (
          <li key={g.key} className="well rounded-xl p-3 text-sm">
            <div className="flex flex-wrap items-center gap-1.5">
              <strong>{g.title}</strong>
              <Chip tone={g.status === "weak" ? "warn" : "neutral"} className="px-2 py-0 text-[11px]">
                {g.status} · {g.errors} slip{g.errors === 1 ? "" : "s"}
              </Chip>
            </div>
            {g.example && (
              <p lang={lang} className="mt-1 text-xs text-ink-2">
                {g.example}
              </p>
            )}
          </li>
        ))}
      </ul>
    </Panel>
  );
}

function ChatView({ lang, initial, speechRate, onClose }: { lang: string; initial: TutorSession; speechRate: number; onClose: () => void }) {
  const [messages, setMessages] = useState<TutorMessage[]>(initial.messages);
  const [draft, setDraft] = useState("");
  const [autoSpeak, setAutoSpeak] = useState(() => storedFlag("lingo.tutor.speak", true));
  const [ended, setEnded] = useState(Boolean(initial.ended_at));
  const [reviewJob, setReviewJob] = useState<number | null>(null);
  const voice = useSpeechInput(lang);
  const list = useRef<HTMLOListElement>(null);
  const qc = useQueryClient();

  const say = useMutation({
    mutationFn: (v: { text: string; mode: "text" | "voice" }) => api.tutorSay(initial.id, v.text, v.mode),
    onSuccess: (data) => {
      setMessages((prev) => [...prev, data.user, data.assistant]);
      if (autoSpeak) speak(data.assistant.text, lang, speechRate);
    },
  });
  const end = useMutation({
    mutationFn: () => api.tutorEnd(initial.id),
    onSuccess: (data) => {
      setEnded(true);
      setReviewJob(data.review_job);
      stopSpeaking();
    },
  });
  // After ending, poll until the review (corrections, summary) is in.
  const review = useQuery({
    queryKey: ["tutor-session", initial.id, "review"],
    queryFn: () => api.tutorSession(initial.id),
    enabled: ended && (reviewJob !== null || initial.postprocessed === 1),
    refetchInterval: (query) => (query.state.data?.postprocessed ? false : 2500),
  });
  useEffect(() => {
    if (review.data?.postprocessed) {
      setMessages(review.data.messages);
      void qc.invalidateQueries({ queryKey: ["tutor-grammar"] });
    }
  }, [review.data, qc]);

  // Speak the opening line once.
  useEffect(() => {
    if (!initial.ended_at && autoSpeak && initial.messages.length === 1) speak(initial.messages[0].text, lang, speechRate);
    return () => stopSpeaking();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    list.current?.lastElementChild?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [messages.length, say.isPending]);

  const engaged = useEngagement(120_000);
  useTracker({ lang, activity: "tutor", label: "Speaking", active: !ended && engaged });

  const send = (value: string, mode: "text" | "voice") => {
    const text = value.trim();
    if (!text || say.isPending) return;
    stopSpeaking();
    say.mutate({ text, mode }, { onSuccess: () => setDraft("") });
  };

  const toggleMic = async () => {
    if (voice.listening) {
      const heard = await voice.stop();
      send(heard, "voice");
    } else {
      stopSpeaking();
      voice.start();
    }
  };

  const summary = review.data?.summary_md ?? initial.summary_md;
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2 px-1">
        <div>
          <h2 className="text-lg font-bold">{MODE_LABELS[initial.mode]}</h2>
          <p className="text-xs text-ink-3">Click any word in the tutor's replies to look it up.</p>
        </div>
        <div className="flex items-center gap-1.5">
          {canSpeak() && (
            <button
              type="button"
              aria-pressed={autoSpeak}
              onClick={() => {
                setAutoSpeak(!autoSpeak);
                try {
                  window.localStorage.setItem("lingo.tutor.speak", autoSpeak ? "0" : "1");
                } catch {
                  // not remembered
                }
              }}
              className={cx("min-h-10 rounded-xl px-3 text-[13px] font-semibold", autoSpeak ? "bg-accent/20 text-accent" : "text-ink-2 hover:bg-white/8")}
            >
              Read replies aloud
            </button>
          )}
          {!ended ? (
            <Button disabled={end.isPending} onClick={() => end.mutate()}>
              End and review
            </Button>
          ) : (
            <Button onClick={onClose}>Back</Button>
          )}
        </div>
      </div>

      <ol ref={list} className="flex flex-col gap-3 [&>li]:scroll-mb-64 md:[&>li]:scroll-mb-40" aria-live="polite">
        {messages.map((m) => (
          <MessageBubble key={m.id} lang={lang} message={m} speechRate={speechRate} />
        ))}
        {say.isPending && (
          <li className="glass self-start rounded-2xl px-4 py-3 text-sm text-ink-3">…</li>
        )}
      </ol>

      {ended ? (
        <Panel className="glass-strong">
          <PanelTitle>Review</PanelTitle>
          {summary ? (
            <p className="text-sm leading-relaxed whitespace-pre-line text-ink-2">{summary}</p>
          ) : reviewJob || review.isFetching ? (
            <p className="text-sm text-ink-3">Reviewing the conversation: corrections and a summary appear here in a moment.</p>
          ) : (
            <p className="text-sm text-ink-3">Nothing to review.</p>
          )}
        </Panel>
      ) : (
        <div className="glass sticky bottom-24 flex flex-col gap-2 rounded-2xl p-3 md:bottom-4">
          <div className="flex items-end gap-2">
            <textarea
              lang={lang}
              value={voice.listening ? voice.text : draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send(draft, "text");
                }
              }}
              readOnly={voice.listening}
              rows={2}
              placeholder={voice.listening ? "Listening…" : "Type your answer, or use the microphone"}
              aria-label="Your message"
              className="min-h-12 min-w-0 flex-1 resize-none rounded-xl border border-white/14 bg-surface p-2.5 text-base text-ink placeholder:text-ink-3"
            />
            {voice.supported && (
              <Button
                variant={voice.listening ? "primary" : "secondary"}
                aria-pressed={voice.listening}
                aria-label={voice.listening ? "Stop and send" : "Speak"}
                onClick={toggleMic}
                disabled={say.isPending}
              >
                {voice.listening ? "■ Send" : "🎤"}
              </Button>
            )}
            {!voice.listening && (
              <Button variant="primary" disabled={say.isPending || !draft.trim()} onClick={() => send(draft, "text")}>
                Send
              </Button>
            )}
          </div>
          {(say.error || voice.error) && (
            <p role="alert" className="text-xs text-red-200">
              {say.error ? say.error.message : voice.error}
            </p>
          )}
          {voice.supported && (
            <p className="text-[11px] text-ink-3">The microphone uses your browser's speech recognition (Chrome and Edge send the audio to their speech service).</p>
          )}
        </div>
      )}
    </div>
  );
}

function MessageBubble({ lang, message, speechRate }: { lang: string; message: TutorMessage; speechRate: number }) {
  if (message.role === "user") {
    return (
      <li className="flex flex-col items-end gap-1">
        <div lang={lang} className="max-w-[85%] rounded-2xl bg-accent/18 px-4 py-2.5 text-[15px] leading-relaxed">
          {message.text}
        </div>
        {message.corrections?.map((c, i) => (
          <div key={i} className="max-w-[85%] rounded-xl border border-emerald-300/30 bg-emerald-400/10 px-3 py-2 text-xs">
            <div lang={lang}>
              <span className="text-ink-3 line-through">{c.original}</span> → <strong className="text-good">{c.corrected}</strong>
            </div>
            {c.explanation && <div className="mt-0.5 text-ink-2">{c.explanation}</div>}
          </div>
        ))}
      </li>
    );
  }
  return (
    <li className="glass flex max-w-[90%] items-start gap-2 self-start rounded-2xl px-4 py-3">
      <p className="text-[16px] leading-relaxed">
        {message.tokens ? (
          <TokenLine
            lang={lang}
            text={message.text}
            tokens={message.tokens}
            sentence={message.text}
            locator={`tutor:${message.id}`}
            theme="dark"
          />
        ) : (
          <span lang={lang}>{message.text}</span>
        )}
      </p>
      {canSpeak() && (
        <button
          type="button"
          onClick={() => speak(message.text, lang, speechRate)}
          aria-label="Read this aloud"
          className="shrink-0 rounded-lg px-1.5 py-1 text-xs text-ink-3 hover:bg-white/10 hover:text-ink"
        >
          ▶
        </button>
      )}
    </li>
  );
}
