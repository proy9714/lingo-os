import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import { Button, Chip, Panel, PanelTitle, Skeleton, cx } from "./ui";

/** Settings: speech to text on this laptop, for videos without captions in your language and your own media. */
export function WhisperPanel() {
  const qc = useQueryClient();
  const settings = useQuery({ queryKey: ["whisper"], queryFn: api.whisper });
  const choose = useMutation({ mutationFn: api.chooseWhisper, onSuccess: (data) => qc.setQueryData(["whisper"], data) });
  const data = settings.data;
  return (
    <Panel aria-labelledby="t-whisper">
      <PanelTitle id="t-whisper" aside={data && <Chip tone={data.model ? "good" : "neutral"}>{data.model ? "on" : "off"}</Chip>}>
        Transcription
      </PanelTitle>
      <p className="text-sm text-ink-2">
        Make a transcript on this laptop (Whisper) for videos with no captions in your language and for your own audio and video
        files. Nothing is sent anywhere; the model downloads once, the first time it's needed.
      </p>
      {!data ? (
        <Skeleton className="mt-3 h-20" />
      ) : (
        <div role="radiogroup" aria-label="Transcription model" className="mt-3 flex flex-col gap-2">
          {[{ id: null, label: "Off", size_mb: 0, downloaded: false }, ...data.models].map((m) => (
            <label
              key={m.id ?? "off"}
              className={cx(
                "flex cursor-pointer items-center gap-3 rounded-xl border px-3 py-2 text-sm transition",
                data.model === m.id ? "border-accent/50 bg-accent/[0.07]" : "border-white/10 hover:bg-white/[0.04]",
              )}
            >
              <input
                type="radio"
                name="whisper-model"
                checked={data.model === m.id}
                disabled={choose.isPending}
                onChange={() => choose.mutate(m.id)}
                className="size-4 accent-[var(--accent)]"
              />
              <span className="flex-1">{m.label}</span>
              {m.id && <span className="text-xs text-ink-3">{m.downloaded ? "downloaded" : `${m.size_mb} MB`}</span>}
            </label>
          ))}
        </div>
      )}
    </Panel>
  );
}

/** On a video without a transcript: make one with Whisper, with progress. */
export function TranscribeButton({ itemId }: { itemId: number }) {
  const qc = useQueryClient();
  const settings = useQuery({ queryKey: ["whisper"], queryFn: api.whisper });
  const [jobId, setJobId] = useState<number | null>(null);
  const start = useMutation({ mutationFn: () => api.transcribe(itemId), onSuccess: (r) => setJobId(r.job_id) });
  const job = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api.job(jobId as number),
    enabled: jobId !== null,
    refetchInterval: (q) => (q.state.data && ["done", "failed"].includes(q.state.data.status) ? false : 1500),
  });
  const status = job.data?.status;
  useEffect(() => {
    if (status === "done") {
      void qc.invalidateQueries({ queryKey: ["transcript", itemId] });
      void qc.invalidateQueries({ queryKey: ["content-item", itemId] });
    }
  }, [status, qc, itemId]);

  if (!settings.data) return null;
  if (!settings.data.model) {
    return (
      <p className="text-xs text-ink-3">
        No captions? Turn on{" "}
        <Link to="/settings" hash="t-whisper" className="font-semibold text-accent hover:underline">
          Transcription
        </Link>{" "}
        in Settings to make a transcript on this laptop.
      </p>
    );
  }
  const busy = start.isPending || (jobId !== null && status !== "done" && status !== "failed");
  const message = (job.data?.result as { message?: string } | null)?.message;
  return (
    <div className="flex flex-col gap-1.5">
      <Button onClick={() => start.mutate()} disabled={busy}>
        {busy ? `Transcribing… ${Math.round((job.data?.progress ?? 0) * 100)}%` : "Transcribe with Whisper"}
      </Button>
      {busy && message && <p className="text-xs text-ink-3">{message}</p>}
      {status === "failed" && <p className="text-xs text-red-200">{job.data?.error}</p>}
      {start.isError && <p className="text-xs text-red-200">{start.error.message}</p>}
    </div>
  );
}
