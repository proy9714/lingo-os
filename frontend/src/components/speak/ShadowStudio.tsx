import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, attemptAudio } from "../../api/client";
import { useContentItem, useShadowClip, useShadowClips, useShadowItemProgress, useShadowSources, useTranscript } from "../../api/hooks";
import type { ShadowAttempt, ShadowClip, ShadowSource, TranscriptCue } from "../../api/types";
import { formatDay, localDayOf } from "../../lib/format";
import { canSpeak, speak, stopSpeaking, useRecorder, useSpeechInput } from "../../lib/speech";
import { useEngagement } from "../../lib/useEngagement";
import { useTracker } from "../../lib/useTracker";
import { useMediaUrl } from "../../sync/useSync";
import { MediaPlayer, type PlayerControls } from "../MediaPlayer";
import { BANDS } from "../cards";
import { Icon } from "../Icon";
import { Button, Chip, Panel, PanelTitle, ProgressBar, Skeleton, cx } from "../ui";

const SPEEDS = [0.5, 0.75, 0.9, 1];

export function ShadowStudio({ lang, initialClip, initialItem = null }: { lang: string; initialClip: number | null; initialItem?: number | null }) {
  const clips = useShadowClips(lang);
  const [selected, setSelected] = useState<number | null>(initialClip);
  // a whole video or episode, line by line: "pick" shows the list to choose from, a number is the one being shadowed
  const [media, setMedia] = useState<"pick" | number | null>(initialItem);
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
    if (selected === null && media === null && clips.data && clips.data.length > 0) setSelected(clips.data[0].id);
  }, [clips.data, selected, media]);

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-[300px_minmax(0,1fr)]">
      <Panel aria-labelledby="t-clips" className="p-4">
        <button
          type="button"
          onClick={() => setMedia("pick")}
          aria-pressed={media !== null}
          className={cx(
            "mb-4 flex w-full items-center gap-3 rounded-xl border px-3 py-3 text-left transition",
            media !== null ? "border-accent/60 bg-accent/12" : "border-white/12 bg-white/[0.04] hover:bg-white/8",
          )}
        >
          <span className="grid size-9 shrink-0 place-items-center rounded-full bg-accent text-accent-ink">
            <Icon name="mic" size={18} />
          </span>
          <span className="min-w-0">
            <span className="block text-sm font-semibold">Shadow a video or podcast</span>
            <span className="block text-xs text-ink-3">Pick one, then repeat it line by line</span>
          </span>
        </button>
        <PanelTitle id="t-clips">Your clips</PanelTitle>
        <p className="mb-3 text-xs leading-relaxed text-ink-3">
          Make a clip from any line in the video player (<strong className="text-ink-2">Shadow this line</strong>), or type a
          sentence below to practise it with a native voice.
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
                  onClick={() => {
                    setMedia(null);
                    setSelected(clip.id);
                  }}
                  aria-current={media === null && selected === clip.id}
                  className={cx(
                    "w-full rounded-xl px-3 py-2 text-left transition",
                    media === null && selected === clip.id ? "bg-accent/15" : "well hover:bg-white/10",
                  )}
                >
                  <div lang={lang} className="line-clamp-2 text-sm">
                    {clip.favorite && "★ "}
                    {clip.text}
                  </div>
                  <div className="mt-0.5 text-[11px] text-ink-3">
                    {clip.item_title ? clip.item_title.slice(0, 40) : "native voice"} · {clip.practice_count}×
                    {clip.best !== null && ` · best ${Math.round(clip.best * 100)}%`}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Panel>
      {media === "pick" ? (
        <ShadowPicker lang={lang} onPick={setMedia} onCancel={() => setMedia(null)} />
      ) : media !== null ? (
        <ShadowSession key={media} lang={lang} itemId={media} onChoose={() => setMedia("pick")} />
      ) : selected !== null ? (
        <Studio key={selected} lang={lang} clipId={selected} onDeleted={() => setSelected(null)} />
      ) : (
        <div />
      )}
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
function Practice({ lang, clip, resolveClipId }: { lang: string; clip: ShadowClip; resolveClipId?: () => Promise<number> }) {
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
    mutationFn: async (v: { blob: Blob; durationMs: number; heard: string }) => {
      const id = resolveClipId ? await resolveClipId() : clip.id;
      return { id, attempt: await api.shadowAttempt(id, v.blob, v.durationMs, v.heard) };
    },
    onSuccess: ({ id, attempt }) => {
      setLast(attempt);
      for (const key of [["shadow-clip", id], ["shadow-clips"], ["shadow-item"], ["shadow-sources"]]) void qc.invalidateQueries({ queryKey: key });
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

  // another line of the same video: start fresh (the player stays, so it doesn't reload)
  const lineKey = `${clip.start_ms}:${clip.text}`;
  const shownLine = useRef(lineKey);
  useEffect(() => {
    if (shownLine.current === lineKey) return;
    shownLine.current = lineKey;
    clearTimer();
    setLoop(false);
    setPhase("idle");
    controls.current?.pause();
    setLast(null);
    setLastBlob(null);
  }, [lineKey]);

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
                    {lang === "ja" || lang === "zh" ? "" : " "}
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

// ---------------------------------------------------------------- shadowing a whole video or podcast episode

const WHY_TONE: Record<ShadowSource["why"], "accent" | "good" | "neutral"> = {
  "in progress": "accent",
  "saved for later": "accent",
  watched: "good",
  suggested: "neutral",
};

function sourcePicture(source: Pick<ShadowSource, "source" | "external_id" | "image">): string | null {
  if (source.source === "youtube" && source.external_id) return `https://i.ytimg.com/vi/${source.external_id}/mqdefault.jpg`;
  return source.image;
}

/** Choose a video or podcast episode (one with a transcript) to shadow line by line. */
function ShadowPicker({ lang, onPick, onCancel }: { lang: string; onPick: (itemId: number) => void; onCancel: () => void }) {
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(query.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [query]);
  const sources = useShadowSources(lang, debounced);
  return (
    <Panel aria-labelledby="t-pick" className="flex min-w-0 flex-col gap-3">
      <PanelTitle
        id="t-pick"
        aside={
          <Button variant="ghost" onClick={onCancel}>
            Close
          </Button>
        }
      >
        Shadow a video or podcast
      </PanelTitle>
      <p className="-mt-2 text-sm text-ink-2">
        Pick something with a transcript. You'll hear it a line at a time, say each line after the speaker, and see which words
        came through. What you're watching, saved for later or have shadowed before comes first.
      </p>
      <label className="flex items-center rounded-xl border border-white/12 bg-black/25 px-3">
        <span className="sr-only">Search videos and episodes</span>
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search titles, channels, shows…"
          className="min-h-11 w-full bg-transparent text-sm text-ink outline-none placeholder:text-ink-3"
        />
      </label>
      {sources.isPending ? (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton key={i} className="h-20 rounded-2xl" />
          ))}
        </div>
      ) : sources.isError ? (
        <p role="alert" className="text-sm text-red-200">
          Couldn't load them: {sources.error.message}
        </p>
      ) : !sources.data?.length ? (
        <p className="text-sm text-ink-3">
          {debounced ? "Nothing with a transcript matches that." : "Nothing with a transcript yet: open a video or episode with captions first."}
        </p>
      ) : (
        <ul className="flex max-h-[68vh] flex-col gap-2 overflow-y-auto pr-1" aria-label="Videos and episodes to shadow">
          {sources.data.map((source) => (
            <li key={source.id}>
              <SourceRow source={source} onPick={() => onPick(source.id)} />
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function SourceRow({ source, onPick }: { source: ShadowSource; onPick: () => void }) {
  const picture = sourcePicture(source);
  const podcast = source.type === "podcast_episode";
  const band = source.band ? BANDS[source.band] : null;
  const minutes = source.duration_sec ? `${Math.round(source.duration_sec / 60)} min` : null;
  return (
    <button
      type="button"
      onClick={onPick}
      className="group flex w-full items-center gap-3 rounded-2xl border border-white/8 bg-white/[0.04] p-2 text-left transition hover:border-accent/40 hover:bg-white/[0.08]"
    >
      <span className={cx("relative shrink-0 overflow-hidden rounded-xl bg-black/40", podcast ? "size-16" : "aspect-video w-[120px]")}>
        {picture ? (
          <img src={picture} alt="" loading="lazy" className="size-full object-cover" />
        ) : (
          <span className="grid size-full place-items-center text-ink-3">
            <Icon name={podcast ? "headphones" : "play"} size={22} />
          </span>
        )}
        {minutes && <span className="absolute right-1 bottom-1 rounded bg-black/75 px-1 text-[10px] font-semibold">{minutes}</span>}
      </span>
      <span className="min-w-0 flex-1">
        <span className="line-clamp-2 text-sm leading-snug font-semibold group-hover:text-accent">{source.title}</span>
        <span className="mt-0.5 block truncate text-xs text-ink-3">
          {[podcast ? "Podcast" : "Video", source.creator, `${source.lines} lines`, source.shadowed ? `${source.shadowed} shadowed` : null]
            .filter(Boolean)
            .join(" · ")}
        </span>
        <span className="mt-1 flex flex-wrap gap-1">
          <Chip tone={WHY_TONE[source.why]} className="px-2 py-0.5 text-[11px]">
            {source.shadowed ? "shadowing" : source.why}
          </Chip>
          {band && <span className={cx("rounded-full px-2 py-0.5 text-[11px] font-semibold", band.tone)}>{band.label}</span>}
        </span>
      </span>
      <span aria-hidden="true" className="px-2 text-lg text-ink-3 group-hover:text-accent">
        →
      </span>
    </button>
  );
}

/** A whole video or episode, a line at a time: hear it, say it, compare, next line. */
function ShadowSession({ lang, itemId, onChoose }: { lang: string; itemId: number; onChoose: () => void }) {
  const item = useContentItem(itemId);
  const transcript = useTranscript(itemId);
  const progress = useShadowItemProgress(itemId);
  const qc = useQueryClient();
  const engaged = useEngagement(120_000);
  useTracker({ lang, activity: "shadowing", label: "Shadowing", active: Boolean(item.data) && engaged });
  const cues = useMemo(() => (transcript.data?.cues ?? []).filter((c) => c.text.trim() && c.end_ms > c.start_ms), [transcript.data]);
  const byCue = useMemo(() => new Map((progress.data ?? []).map((p) => [p.cue_id, p])), [progress.data]);
  const [index, setIndex] = useState<number | null>(null);
  const list = useRef<HTMLOListElement>(null);

  // start at the first line you haven't said well yet
  useEffect(() => {
    if (index !== null || !cues.length || !progress.data) return;
    const next = cues.findIndex((c) => (byCue.get(c.id)?.best ?? 0) < 0.8);
    setIndex(next < 0 ? 0 : next);
  }, [cues, progress.data, byCue, index]);
  useEffect(() => {
    list.current?.querySelector(`[data-line="${index}"]`)?.scrollIntoView({ block: "nearest" });
  }, [index]);

  if (item.isError || transcript.isError) {
    return (
      <Panel role="alert">
        Couldn't open it: {(item.error ?? transcript.error)?.message}{" "}
        <Button variant="ghost" onClick={onChoose}>
          Choose another
        </Button>
      </Panel>
    );
  }
  if (!item.data || !transcript.data || index === null) {
    if (transcript.data && cues.length === 0) {
      return (
        <Panel>
          <p className="text-sm text-ink-2">This one has no transcript lines to shadow.</p>
          <Button className="mt-3" onClick={onChoose}>
            Choose another
          </Button>
        </Panel>
      );
    }
    return <Skeleton className="h-96 rounded-[20px]" />;
  }

  const cue = cues[index];
  const line = byCue.get(cue.id);
  const done = cues.filter((c) => (byCue.get(c.id)?.best ?? 0) >= 0.8).length;
  const clip: ShadowClip = {
    id: line?.clip_id ?? 0,
    language: lang,
    content_item_id: itemId,
    cue_id: cue.id,
    start_ms: cue.start_ms,
    end_ms: cue.end_ms,
    text: cue.text,
    reference_kind: "media",
    favorite: false,
    practice_count: line?.attempts ?? 0,
    created_at: "",
    item_title: item.data.title,
    item_source: item.data.source,
    external_id: item.data.external_id,
    item_type: item.data.type,
    best: line?.best ?? null,
    last_practised: null,
  };
  // the clip for this line is made the first time you record it (one per line, kept in "Your clips")
  const resolveClipId = async () => {
    if (line) return line.clip_id;
    const made = await api.shadowCreate({ lang, text: cue.text, content_item_id: itemId, cue_id: cue.id });
    void qc.invalidateQueries({ queryKey: ["shadow-item", itemId] });
    return made.id;
  };
  const go = (to: number) => setIndex(Math.max(0, Math.min(cues.length - 1, to)));

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <Panel className="glass-strong">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="truncate text-xs text-ink-3">
              Shadowing “{item.data.title}” · line {index + 1} of {cues.length}
            </p>
            <p lang={lang} className="mt-1 text-xl leading-relaxed font-semibold md:text-2xl">
              {cue.text}
            </p>
          </div>
          <Button variant="ghost" onClick={onChoose}>
            Choose another
          </Button>
        </div>
        <div className="mt-3">
          <ProgressBar value={cues.length ? done / cues.length : 0} label={`${done} of ${cues.length} lines said well`} />
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button onClick={() => go(index - 1)} disabled={index === 0}>
            ← Previous line
          </Button>
          <Button variant={line && line.attempts > 0 ? "primary" : "secondary"} onClick={() => go(index + 1)} disabled={index >= cues.length - 1}>
            Next line →
          </Button>
          {line?.best != null && <Chip tone={line.best >= 0.8 ? "good" : "accent"}>best {Math.round(line.best * 100)}%</Chip>}
        </div>
      </Panel>
      <Practice lang={lang} clip={clip} resolveClipId={resolveClipId} />
      <Panel aria-labelledby="t-lines" className="p-3">
        <PanelTitle id="t-lines">All lines</PanelTitle>
        <ol ref={list} className="flex max-h-[40vh] flex-col gap-0.5 overflow-y-auto">
          {cues.map((c, n) => (
            <LineRow key={c.id} lang={lang} cue={c} n={n} active={n === index} best={byCue.get(c.id)?.best ?? null} onPick={() => go(n)} />
          ))}
        </ol>
      </Panel>
    </div>
  );
}

function LineRow({ lang, cue, n, active, best, onPick }: { lang: string; cue: TranscriptCue; n: number; active: boolean; best: number | null; onPick: () => void }) {
  return (
    <li data-line={n}>
      <button
        type="button"
        onClick={onPick}
        aria-current={active}
        className={cx("flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left text-sm transition", active ? "bg-accent/15" : "hover:bg-white/6")}
      >
        <span className="w-7 shrink-0 text-right text-xs text-ink-3 tabular-nums">{n + 1}</span>
        <span lang={lang} className={cx("min-w-0 flex-1", active ? "text-ink" : "text-ink-2")}>
          {cue.text}
        </span>
        {best !== null && (
          <span className={cx("shrink-0 text-xs font-semibold tabular-nums", best >= 0.8 ? "text-good" : "text-warn")}>{Math.round(best * 100)}%</span>
        )}
      </button>
    </li>
  );
}
