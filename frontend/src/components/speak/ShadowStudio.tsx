import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { api, attemptAudio } from "../../api/client";
import { useContentItem, useShadowClip, useShadowClips } from "../../api/hooks";
import type { ShadowAttempt, ShadowClip } from "../../api/types";
import { formatDay, localDayOf } from "../../lib/format";
import { canSpeak, speak, stopSpeaking, useRecorder, useSpeechInput } from "../../lib/speech";
import { useEngagement } from "../../lib/useEngagement";
import { useTracker } from "../../lib/useTracker";
import { useMediaUrl } from "../../sync/useSync";
import { MediaPlayer, type PlayerControls } from "../MediaPlayer";
import { Button, Chip, Panel, PanelTitle, Skeleton, cx } from "../ui";

const SPEEDS = [0.5, 0.75, 0.9, 1];

export function ShadowStudio({ lang, initialClip }: { lang: string; initialClip: number | null }) {
  const clips = useShadowClips(lang);
  const [selected, setSelected] = useState<number | null>(initialClip);
  const [draft, setDraft] = useState("");
  const qc = useQueryClient();
  const create = useMutation({
    mutationFn: (text: string) => api.shadowCreate({ lang, text }),
    onSuccess: (clip) => {
      setDraft("");
      setSelected(clip.id);
      void qc.invalidateQueries({ queryKey: ["shadow-clips"] });
    },
  });

  useEffect(() => {
    if (initialClip !== null) setSelected(initialClip);
  }, [initialClip]);
  useEffect(() => {
    if (selected === null && clips.data && clips.data.length > 0) setSelected(clips.data[0].id);
  }, [clips.data, selected]);

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-[300px_minmax(0,1fr)]">
      <Panel aria-labelledby="t-clips" className="p-4">
        <PanelTitle id="t-clips">Your clips</PanelTitle>
        <p className="mb-3 text-xs leading-relaxed text-ink-3">
          Make a clip from any line in the video player (<strong className="text-ink-2">Shadow this line</strong>), or type a
          sentence below to practise it with the browser's voice.
        </p>
        <form
          className="mb-3 flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (draft.trim()) create.mutate(draft.trim());
          }}
        >
          <input
            lang={lang}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="A sentence to practise…"
            aria-label="A sentence to practise"
            className="min-h-10 min-w-0 flex-1 rounded-xl border border-white/14 bg-surface px-3 text-sm text-ink placeholder:text-ink-3"
          />
          <Button type="submit" disabled={!draft.trim() || create.isPending}>
            Add
          </Button>
        </form>
        {clips.isPending ? (
          <Skeleton className="h-32" />
        ) : !clips.data || clips.data.length === 0 ? (
          <p className="text-sm text-ink-3">No clips yet.</p>
        ) : (
          <ul className="flex max-h-[60vh] flex-col gap-1.5 overflow-y-auto">
            {clips.data.map((clip) => (
              <li key={clip.id}>
                <button
                  type="button"
                  onClick={() => setSelected(clip.id)}
                  aria-current={selected === clip.id}
                  className={cx(
                    "w-full rounded-xl px-3 py-2 text-left transition",
                    selected === clip.id ? "bg-accent/15" : "well hover:bg-white/10",
                  )}
                >
                  <div lang={lang} className="line-clamp-2 text-sm">
                    {clip.favorite && "★ "}
                    {clip.text}
                  </div>
                  <div className="mt-0.5 text-[11px] text-ink-3">
                    {clip.item_title ? clip.item_title.slice(0, 40) : "browser voice"} · {clip.practice_count}×
                    {clip.best !== null && ` · best ${Math.round(clip.best * 100)}%`}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Panel>
      {selected !== null ? <Studio key={selected} lang={lang} clipId={selected} onDeleted={() => setSelected(null)} /> : <div />}
    </div>
  );
}

function Studio({ lang, clipId, onDeleted }: { lang: string; clipId: number; onDeleted: () => void }) {
  const clip = useShadowClip(clipId).data;
  const qc = useQueryClient();
  const engaged = useEngagement(120_000);
  useTracker({ lang, activity: "shadowing", label: "Shadowing", active: Boolean(clip) && engaged });

  const favorite = useMutation({
    mutationFn: (value: boolean) => api.shadowFavorite(clipId, value),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["shadow-clip", clipId] });
      void qc.invalidateQueries({ queryKey: ["shadow-clips"] });
    },
  });
  const remove = useMutation({
    mutationFn: () => api.shadowDelete(clipId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["shadow-clips"] });
      onDeleted();
    },
  });

  if (!clip) return <Skeleton className="h-96 rounded-[20px]" />;
  return (
    <div className="flex min-w-0 flex-col gap-4">
      <Panel className="glass-strong">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <p lang={lang} className="text-xl leading-relaxed font-semibold md:text-2xl">
            {clip.text}
          </p>
          <div className="flex gap-1">
            <Button variant="ghost" aria-pressed={clip.favorite} onClick={() => favorite.mutate(!clip.favorite)}>
              {clip.favorite ? "★" : "☆"}
            </Button>
            <Button
              variant="ghost"
              onClick={() => {
                if (window.confirm("Delete this clip and its recordings? This can't be undone.")) remove.mutate();
              }}
            >
              Delete
            </Button>
          </div>
        </div>
        {clip.item_title && <p className="mt-1 text-xs text-ink-3">From “{clip.item_title}”</p>}
      </Panel>
      <Practice lang={lang} clip={clip} />
      <Attempts lang={lang} attempts={clip.attempts ?? []} />
    </div>
  );
}

/** Listen (once or in a loop with a pause for your turn), then record yourself. */
function Practice({ lang, clip }: { lang: string; clip: ShadowClip }) {
  const media = useContentItem(clip.content_item_id ?? 0);
  const useMedia = clip.reference_kind === "media" && clip.content_item_id !== null;
  const controls = useRef<PlayerControls | null>(null);
  const [speed, setSpeed] = useState(0.9);
  const [loop, setLoop] = useState(false);
  const [phase, setPhase] = useState<"idle" | "listening" | "your-turn">("idle");
  const loopRef = useRef(loop);
  const phaseRef = useRef(phase);
  const timer = useRef<number | null>(null);
  loopRef.current = loop;
  phaseRef.current = phase;

  const recorder = useRecorder();
  const voice = useSpeechInput(lang);
  const qc = useQueryClient();
  const [last, setLast] = useState<ShadowAttempt | null>(null);
  const [lastBlob, setLastBlob] = useState<Blob | null>(null);
  const upload = useMutation({
    mutationFn: (v: { blob: Blob; durationMs: number; heard: string }) => api.shadowAttempt(clip.id, v.blob, v.durationMs, v.heard),
    onSuccess: (attempt) => {
      setLast(attempt);
      void qc.invalidateQueries({ queryKey: ["shadow-clip", clip.id] });
      void qc.invalidateQueries({ queryKey: ["shadow-clips"] });
    },
  });

  const clipMs = Math.max(800, clip.end_ms - clip.start_ms);
  const clearTimer = () => {
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = null;
  };

  const listen = useCallback(() => {
    clearTimer();
    setPhase("listening");
    if (useMedia && controls.current) {
      controls.current.setRate(speed);
      controls.current.seek(clip.start_ms);
      controls.current.play();
      // If the browser blocks playback, don't stay in "listen" forever.
      timer.current = window.setTimeout(() => {
        if (phaseRef.current === "listening") {
          controls.current?.pause();
          afterListening();
        }
      }, clipMs / speed + 4000);
    } else {
      speak(clip.text, lang, speed, () => afterListening());
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [useMedia, speed, clip, lang]);

  // In loop mode: your turn lasts about as long as the line (a little longer at slow speeds), then it plays again.
  const afterListening = useCallback(() => {
    clearTimer();
    if (!loopRef.current) {
      setPhase("idle");
      return;
    }
    setPhase("your-turn");
    const turn = (useMedia ? clipMs / speed : Math.max(1500, clip.text.length * 90)) * 1.2 + 500;
    timer.current = window.setTimeout(() => loopRef.current && listen(), turn);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [useMedia, clipMs, speed, clip.text.length]);

  const onTime = (ms: number) => {
    if (phaseRef.current === "listening" && useMedia && ms >= clip.end_ms) {
      controls.current?.pause();
      afterListening();
    }
  };

  const stopAll = () => {
    clearTimer();
    setLoop(false);
    setPhase("idle");
    controls.current?.pause();
    stopSpeaking();
  };

  useEffect(() => () => clearTimer(), []);

  const record = async () => {
    if (recorder.recording) {
      const [result, heard] = await Promise.all([recorder.stop(), voice.stop()]);
      if (result) {
        setLastBlob(result.blob);
        upload.mutate({ blob: result.blob, durationMs: result.durationMs, heard });
      }
      return;
    }
    stopAll();
    setLast(null);
    const ok = await recorder.start();
    if (ok && voice.supported) voice.start();
  };

  return (
    <Panel aria-labelledby="t-practice">
      <PanelTitle id="t-practice" aside={phase !== "idle" && <Chip tone="accent">{phase === "listening" ? "listen" : "your turn"}</Chip>}>
        Listen and repeat
      </PanelTitle>
      {useMedia && media.data && (
        <div className="mb-3 overflow-hidden rounded-xl">
          <MediaPlayer
            item={media.data}
            startMs={clip.start_ms}
            onReady={(c) => {
              controls.current = c;
            }}
            onTime={onTime}
            onPlaying={() => undefined}
          />
        </div>
      )}
      {!useMedia && !canSpeak() && <p className="mb-3 text-sm text-ink-3">This browser has no voice to read the line aloud.</p>}

      <div className="flex flex-wrap items-center gap-2">
        <Button variant="primary" onClick={listen} disabled={recorder.recording}>
          ▶ Listen
        </Button>
        <button
          type="button"
          aria-pressed={loop}
          disabled={recorder.recording}
          onClick={() => {
            if (loop) stopAll();
            else {
              setLoop(true);
              loopRef.current = true;
              listen();
            }
          }}
          className={cx(
            "min-h-11 rounded-xl px-4 text-sm font-semibold transition disabled:opacity-50",
            loop ? "border border-accent/60 bg-accent/15 text-accent" : "border border-white/16 bg-white/8 hover:bg-white/12",
          )}
        >
          {loop ? "Stop loop" : "Loop with pauses"}
        </button>
        <label className="flex items-center gap-2 text-sm text-ink-2">
          Speed
          <select
            value={speed}
            onChange={(e) => setSpeed(Number(e.target.value))}
            className="min-h-10 rounded-lg border border-white/14 bg-surface px-2 text-ink"
          >
            {SPEEDS.map((s) => (
              <option key={s} value={s}>
                {s}×
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="mt-5 flex flex-col items-center gap-3 border-t border-white/8 pt-5">
        {recorder.supported ? (
          <Button
            variant={recorder.recording ? "primary" : "secondary"}
            className="min-w-56"
            onClick={record}
            disabled={upload.isPending}
            aria-pressed={recorder.recording}
          >
            {recorder.recording ? "■ Stop and compare" : upload.isPending ? "Comparing…" : "● Record yourself"}
          </Button>
        ) : (
          <p className="text-sm text-ink-3">This browser can't record audio.</p>
        )}
        {recorder.recording && voice.supported && (
          <p lang={lang} className="min-h-6 text-center text-sm text-ink-2">
            {voice.text || "…"}
          </p>
        )}
        {(recorder.error ?? voice.error) && <p role="alert" className="text-sm text-red-200">{recorder.error ?? voice.error}</p>}
        {upload.isError && <p role="alert" className="text-sm text-red-200">{upload.error.message}</p>}
        {!voice.supported && recorder.supported && (
          <p className="text-xs text-ink-3">No speech recognition in this browser: recordings are kept, but can't be compared word by word.</p>
        )}
      </div>

      {last && (
        <div className="mt-4 flex flex-col gap-3 rounded-xl border border-white/10 p-3">
          {last.similarity !== null ? (
            <>
              <div className="text-sm">
                <strong>{Math.round(last.similarity * 100)}%</strong> of the line was recognised.{" "}
                <span className="text-ink-3">Grey parts weren't heard; say them again.</span>
              </div>
              <p lang={lang} className="text-lg leading-relaxed">
                {last.diff.map((piece, i) => (
                  <span key={i} className={cx(piece.ok ? "text-good" : "text-ink-3 underline decoration-dotted")}>
                    {piece.text}
                    {lang === "ja" ? "" : " "}
                  </span>
                ))}
              </p>
            </>
          ) : (
            <p className="text-sm text-ink-2">Saved. Nothing was recognised, so there's no comparison this time.</p>
          )}
          {lastBlob && <Waveform blob={lastBlob} />}
        </div>
      )}
      <p className="mt-3 text-[11px] text-ink-3">
        Recordings stay on this computer. Word recognition uses your browser's speech service (Chrome and Edge send the audio to it).
      </p>
    </Panel>
  );
}

/** The recording's loudness over time, so pauses and rushed parts are visible. */
function Waveform({ blob }: { blob: Blob }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    let cancelled = false;
    const draw = async () => {
      const context = new AudioContext();
      try {
        const audio = await context.decodeAudioData(await blob.arrayBuffer());
        const el = canvas.current;
        if (cancelled || !el) return;
        const data = audio.getChannelData(0);
        const width = (el.width = el.clientWidth * window.devicePixelRatio);
        const height = (el.height = 64 * window.devicePixelRatio);
        const ctx = el.getContext("2d");
        if (!ctx) return;
        ctx.clearRect(0, 0, width, height);
        ctx.fillStyle = getComputedStyle(el).color;
        const step = Math.max(1, Math.floor(data.length / width));
        for (let x = 0; x < width; x++) {
          let peak = 0;
          for (let i = x * step; i < (x + 1) * step && i < data.length; i++) peak = Math.max(peak, Math.abs(data[i]));
          const h = Math.max(1, peak * height);
          ctx.fillRect(x, (height - h) / 2, 1, h);
        }
      } catch {
        // undecodable recording: no waveform
      } finally {
        void context.close();
      }
    };
    void draw();
    return () => {
      cancelled = true;
    };
  }, [blob]);
  return <canvas ref={canvas} className="h-16 w-full text-accent" aria-label="Waveform of your recording" role="img" />;
}

function Attempts({ lang, attempts }: { lang: string; attempts: ShadowAttempt[] }) {
  if (attempts.length === 0) return null;
  return (
    <Panel aria-labelledby="t-attempts">
      <PanelTitle id="t-attempts">Your attempts</PanelTitle>
      <ul className="flex flex-col gap-2">
        {attempts.map((a) => (
          <li key={a.id} className="well flex flex-wrap items-center gap-3 rounded-xl p-2.5 text-sm">
            <span className="w-20 shrink-0 text-xs text-ink-3">{formatDay(localDayOf(a.created_at))}</span>
            <span className="w-14 shrink-0 font-semibold">{a.similarity !== null ? `${Math.round(a.similarity * 100)}%` : "–"}</span>
            <span lang={lang} className="min-w-0 flex-1 truncate text-ink-2">
              {a.heard ?? "(nothing recognised)"}
            </span>
            <AttemptAudio id={a.id} />
          </li>
        ))}
      </ul>
    </Panel>
  );
}

function AttemptAudio({ id }: { id: number }) {
  const src = useMediaUrl(attemptAudio(id));
  return src ? <audio controls preload="none" src={src} className="h-8 max-w-full" /> : null;
}
