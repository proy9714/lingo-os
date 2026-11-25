import { useMutation } from "@tanstack/react-query";
import { useNavigate, useParams } from "@tanstack/react-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "../api/client";
import { useContentItem, useContentMutation, useTranscript } from "../api/hooks";
import type { TranscriptCue } from "../api/types";
import { FuriganaToggle } from "../lib/furigana";
import { BANDS } from "../components/cards";
import { CompletedButton } from "../components/CompletedButton";
import { DifficultyRating } from "../components/DifficultyRating";
import { MediaPlayer, type PlayerControls } from "../components/MediaPlayer";
import { TokenLine } from "../components/TokenLine";
import { Button, Chip, Panel, Skeleton, cx } from "../components/ui";
import { BackLink, displayTitle } from "../lib/nav";
import { useTracker } from "../lib/useTracker";
import { useLookupStore } from "../state/lookup";
import { useShadowTarget } from "../state/shadow";

const SPEEDS = [0.75, 0.9, 1, 1.25];

function clock(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const pad = (n: number) => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(s % 60)}` : `${pad(m)}:${pad(s % 60)}`;
}

export function PlayerPage() {
  const { itemId } = useParams({ strict: false }) as { itemId: string };
  const id = Number(itemId);
  const item = useContentItem(id);
  const transcript = useTranscript(id);
  const fetchCaptions = useContentMutation(() => api.fetchCaptions(id));
  // A suggested video whose level was only estimated: fetch its captions and measure it as soon as it's opened.
  const autoFetched = useRef<number | null>(null);
  const needsCaptions =
    item.data?.source === "youtube" && !item.data.transcript_kind && item.data.metadata?.captions !== "none";
  useEffect(() => {
    if (needsCaptions && autoFetched.current !== id && !fetchCaptions.isPending) {
      autoFetched.current = id;
      fetchCaptions.mutate(undefined);
    }
  }, [needsCaptions, id, fetchCaptions]);

  const controls = useRef<PlayerControls | null>(null);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [rate, setRate] = useState(1);
  const [pauseEachLine, setPauseEachLine] = useState(false);
  const resumeAfterLookup = useRef(false);
  const lastAutoPause = useRef(-1);
  const listRef = useRef<HTMLOListElement>(null);
  const lookupOpen = useLookupStore((s) => s.selection !== null);

  const navigate = useNavigate();
  const openClip = useShadowTarget((s) => s.open);
  const shadow = useMutation({
    mutationFn: (cue: TranscriptCue) =>
      api.shadowCreate({ lang: item.data?.language ?? "de", text: cue.text, content_item_id: id, cue_id: cue.id }),
    onSuccess: (clip) => {
      controls.current?.pause();
      openClip(clip.id);
      void navigate({ to: "/speak" });
    },
  });
  const cues = transcript.data?.cues ?? [];
  const activeIndex = useMemo(() => {
    let found = -1;
    for (let i = 0; i < cues.length && cues[i].start_ms <= time + 150; i++) found = i;
    return found;
  }, [cues, time]);

  const lang = item.data?.language ?? "de";
  useTracker({
    lang,
    activity: item.data?.type === "audio" ? "audio" : "video",
    label: item.data?.type === "audio" ? "Listening" : "Watching",
    contentItemId: item.data ? id : undefined,
    active: Boolean(item.data) && playing,
    position: () => controls.current?.time(),
    duration: () => controls.current?.duration(),
  });

  // Pause at the end of each line when that mode is on.
  useEffect(() => {
    if (!pauseEachLine || !playing || activeIndex < 0) return;
    const cue = cues[activeIndex];
    if (time >= cue.end_ms - 80 && lastAutoPause.current !== cue.seq) {
      lastAutoPause.current = cue.seq;
      controls.current?.pause();
    }
  }, [time, pauseEachLine, playing, activeIndex, cues]);

  // Resume after the lookup panel closes, if a word click paused the video.
  useEffect(() => {
    if (!lookupOpen && resumeAfterLookup.current) {
      resumeAfterLookup.current = false;
      controls.current?.play();
    }
  }, [lookupOpen]);

  // Keep the active line in view.
  useEffect(() => {
    if (activeIndex < 0 || !listRef.current) return;
    const node = listRef.current.querySelector<HTMLElement>(`[data-seq="${cues[activeIndex].seq}"]`);
    node?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [activeIndex, cues]);

  const seekTo = useCallback((ms: number) => {
    lastAutoPause.current = -1;
    controls.current?.seek(ms);
    setTime(ms);
  }, []);

  const jump = useCallback(
    (delta: number) => {
      const target = cues[Math.max(0, Math.min(cues.length - 1, (activeIndex < 0 ? 0 : activeIndex) + delta))];
      if (target) seekTo(target.start_ms);
    },
    [cues, activeIndex, seekTo],
  );

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      if (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "BUTTON") return;
      if (event.key === " ") {
        event.preventDefault();
        if (playing) controls.current?.pause();
        else controls.current?.play();
      } else if (event.key === "ArrowLeft") jump(-1);
      else if (event.key === "ArrowRight") jump(1);
      else if (event.key.toLowerCase() === "r" && activeIndex >= 0) {
        seekTo(cues[activeIndex].start_ms);
        controls.current?.play();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [playing, jump, seekTo, activeIndex, cues]);

  if (item.isPending) return <Skeleton className="h-96 rounded-[20px]" />;
  if (item.isError) return <Panel role="alert">Could not open this video: {item.error.message}</Panel>;
  const data = item.data;
  const startMs = data.position_ref?.startsWith("ms:") && data.progress < 0.9 ? Number(data.position_ref.slice(3)) : undefined;
  const summary = transcript.data?.summary;

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-start justify-between gap-3 px-1 pt-1">
        <div className="min-w-0">
          <BackLink to="/watch" label="All videos" className="text-sm text-ink-2 hover:text-ink" />
          <h1 className="mt-1 text-xl leading-snug font-bold md:text-2xl">{displayTitle(data.title)}</h1>
          <p className="mt-1 text-sm text-ink-2">
            {data.creator ?? "Local file"}
            {data.transcript_kind && ` · transcript: ${data.transcript_kind === "auto_caption" ? "YouTube automatic captions" : data.transcript_kind === "manual" ? "uploaded subtitles" : "your subtitle file"}`}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {summary?.known_share != null && (
            <>
              <Chip tone="accent">≈ {Math.round(summary.known_share * 100)}% known</Chip>
              {data.band && BANDS[data.band] && <Chip>{BANDS[data.band].label} for you</Chip>}
              <Chip>{summary.new_words} likely new</Chip>
              {data.speech_wpm && <Chip>{Math.round(data.speech_wpm)} words/min</Chip>}
            </>
          )}
          <CompletedButton id={id} kind="video" finished={data.status === "finished"} onDone={() => controls.current?.pause()} />
        </div>
      </header>

      <div className="grid grid-cols-[minmax(0,1fr)] gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
        <div className="flex min-w-0 flex-col gap-3">
          <MediaPlayer
            item={data}
            startMs={startMs}
            onReady={(c) => {
              controls.current = c;
              c.setRate(rate);
            }}
            onTime={setTime}
            onPlaying={setPlaying}
          />
          <div role="toolbar" aria-label="Player controls" className="glass flex flex-wrap items-center gap-2 rounded-2xl p-2">
            <Button variant="primary" onClick={() => (playing ? controls.current?.pause() : controls.current?.play())}>
              {playing ? "Pause" : "Play"}
            </Button>
            <Button onClick={() => jump(-1)} title="Previous line (←)">
              ← Line
            </Button>
            <Button
              onClick={() => {
                if (activeIndex >= 0) seekTo(cues[activeIndex].start_ms);
                controls.current?.play();
              }}
              title="Replay line (R)"
            >
              Replay
            </Button>
            <Button onClick={() => jump(1)} title="Next line (→)">
              Line →
            </Button>
            <Button
              onClick={() => activeIndex >= 0 && shadow.mutate(cues[activeIndex])}
              disabled={activeIndex < 0 || shadow.isPending}
              title="Practise saying the current line"
            >
              Shadow this line
            </Button>
            <label className="flex items-center gap-2 text-sm text-ink-2">
              Speed
              <select
                value={rate}
                onChange={(e) => {
                  const value = Number(e.target.value);
                  setRate(value);
                  controls.current?.setRate(value);
                }}
                className="min-h-10 rounded-lg border border-white/14 bg-surface px-2 text-ink"
              >
                {SPEEDS.map((s) => (
                  <option key={s} value={s}>
                    {s}×
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              aria-pressed={pauseEachLine}
              onClick={() => setPauseEachLine(!pauseEachLine)}
              className={cx(
                "min-h-10 rounded-xl px-3 text-sm font-semibold",
                pauseEachLine ? "border border-accent/60 bg-accent/15 text-accent" : "border border-white/14 text-ink-2 hover:bg-white/8",
              )}
            >
              Pause after each line
            </button>
            <span className="ml-auto text-xs text-ink-3 tabular-nums">{clock(time)}</span>
          </div>
          <div className="glass rounded-2xl px-3 py-2.5">
            <DifficultyRating itemId={id} value={data.difficulty} />
            <p className="mt-1.5 text-xs text-ink-3">Your rating tunes how hard your suggested videos are.</p>
          </div>
        </div>

        <section aria-labelledby="t-transcript" className="solid flex max-h-[70dvh] min-h-[320px] flex-col rounded-[18px]">
          <div className="flex items-center justify-between border-b border-white/8 px-4 py-3">
            <h2 id="t-transcript" className="text-[13px] font-semibold tracking-[0.08em] text-ink-2 uppercase">
              Transcript
            </h2>
            {lang === "ja" ? (
              <FuriganaToggle className="rounded-lg px-2 py-1 text-xs font-semibold text-ink-2 transition hover:bg-white/8 hover:text-ink" />
            ) : (
              <span className="text-xs text-ink-3">click a word to look it up</span>
            )}
          </div>
          {transcript.isPending ? (
            <div className="flex flex-col gap-2 p-4">
              <Skeleton className="h-5" />
              <Skeleton className="h-5 w-4/5" />
            </div>
          ) : cues.length === 0 ? (
            <div className="flex flex-col items-start gap-3 p-4 text-sm text-ink-2">
              <p>No transcript yet.</p>
              {data.source === "youtube" && (
                <Button onClick={() => fetchCaptions.mutate(undefined)} disabled={fetchCaptions.isPending}>
                  {fetchCaptions.isPending ? "Fetching…" : "Fetch YouTube captions"}
                </Button>
              )}
              {fetchCaptions.isError && <p className="text-red-200">{fetchCaptions.error.message}</p>}
            </div>
          ) : (
            <ol ref={listRef} className="flex-1 overflow-y-auto p-2">
              {cues.map((cue, index) => (
                <CueRow
                  key={cue.id}
                  cue={cue}
                  lang={lang}
                  itemId={id}
                  active={index === activeIndex}
                  onSeek={() => {
                    seekTo(cue.start_ms);
                    controls.current?.play();
                  }}
                  onWord={() => {
                    if (playing) {
                      resumeAfterLookup.current = true;
                      controls.current?.pause();
                    }
                  }}
                />
              ))}
            </ol>
          )}
        </section>
      </div>
      <p className="px-1 text-xs text-ink-3">Space play/pause · ← → previous/next line · R replay line. Watching time counts only while playing.</p>
    </div>
  );
}

function CueRow(props: { cue: TranscriptCue; lang: string; itemId: number; active: boolean; onSeek: () => void; onWord: () => void }) {
  const { cue, lang, itemId, active, onSeek, onWord } = props;
  return (
    <li data-seq={cue.seq} className={cx("flex gap-2 rounded-xl px-2 py-1.5", active && "bg-accent/10")}>
      <button
        type="button"
        onClick={onSeek}
        className={cx("h-7 shrink-0 rounded-md px-1.5 text-xs tabular-nums", active ? "bg-accent/25 text-accent" : "bg-white/6 text-ink-3 hover:text-ink")}
        aria-label={`Play from ${clock(cue.start_ms)}`}
      >
        {clock(cue.start_ms)}
      </button>
      <p className={cx("text-[16px] leading-relaxed", active ? "text-ink" : "text-ink-2")}>
        <TokenLine
          lang={lang}
          text={cue.text}
          tokens={cue.tokens}
          sentence={cue.text}
          locator={`ms:${cue.start_ms}`}
          contentItemId={itemId}
          theme="dark"
          onWordClick={onWord}
        />
      </p>
    </li>
  );
}
