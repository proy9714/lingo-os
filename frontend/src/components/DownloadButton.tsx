// Save an item on this device for offline use (texts, books, manga, podcast episodes, transcripts), or remove it.
import { useState } from "react";

import { cancelDownload, downloadItem, removeDownload, useSavedDownloads, type DownloadTarget } from "../sync/downloads";
import { Icon } from "./Icon";
import { cx } from "./ui";

export type { DownloadTarget };

const READ_ALONG = new Set(["youtube", "video"]); // the video itself can't be saved, its transcript can

export function DownloadButton({ item, compact = false }: { item: DownloadTarget; compact?: boolean }) {
  const { saved, jobs } = useSavedDownloads();
  const job = jobs[item.id];
  const entry = saved[item.id];
  const [confirm, setConfirm] = useState(false);
  const base = cx(
    "inline-flex items-center gap-1.5 rounded-full text-xs font-semibold transition",
    compact ? "px-2.5 py-1.5" : "px-3.5 py-2",
  );

  if (job && !job.error) {
    return (
      <button
        type="button"
        onClick={() => cancelDownload(item.id)}
        className={cx(base, "bg-white/8 text-ink-2 hover:bg-white/12")}
        title="Cancel the download"
      >
        <span className="relative inline-block size-3.5 rounded-full border-2 border-white/20">
          <span
            className="absolute inset-[-2px] rounded-full border-2 border-accent border-r-transparent border-b-transparent motion-safe:animate-spin"
            aria-hidden="true"
          />
        </span>
        {Math.round(job.progress * 100)}%{!compact && ` · ${job.label}`}
      </button>
    );
  }
  if (entry) {
    return confirm ? (
      <span className="inline-flex items-center gap-1">
        <button
          type="button"
          onClick={() => void removeDownload(item.id).finally(() => setConfirm(false))}
          className={cx(base, "bg-orange-400/15 text-warn hover:bg-orange-400/25")}
        >
          Remove from this device
        </button>
        <button type="button" onClick={() => setConfirm(false)} className={cx(base, "text-ink-2 hover:bg-white/8")}>
          Keep
        </button>
      </span>
    ) : (
      <button
        type="button"
        onClick={() => setConfirm(true)}
        className={cx(base, "bg-emerald-400/15 text-good hover:bg-emerald-400/25")}
        title={entry.kind === "media" && !entry.hasRecording ? "The transcript is saved for offline reading" : "Saved on this device"}
      >
        <Icon name="check" size={14} />
        {!compact && (entry.kind === "media" && !entry.hasRecording ? "Transcript saved" : "Saved offline")}
      </button>
    );
  }
  return (
    <span className="inline-flex flex-col items-start gap-1">
      <button
        type="button"
        onClick={() => void downloadItem(item)}
        className={cx(base, "border border-white/16 bg-white/8 text-ink hover:bg-white/12")}
        title={READ_ALONG.has(item.type) ? "Save the transcript to read along offline" : "Save it on this device to use offline"}
      >
        <Icon name="download" size={14} />
        {!compact && (READ_ALONG.has(item.type) ? "Save transcript" : "Download")}
      </button>
      {job?.error && <span className="text-xs text-warn">{job.error}</span>}
    </span>
  );
}
