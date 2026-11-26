// Everything saved on this device for offline use: open it, see how much room it takes, remove it.
import { Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";

import { DownloadButton } from "../components/DownloadButton";
import { Chip, Panel, PanelTitle } from "../components/ui";
import { formatBytes, useSavedDownloads, type SavedEntry } from "../sync/downloads";
import { storageUsed } from "../sync/packs";
import { remoteConfig } from "../sync/remote";

const GROUPS: { title: string; match: (e: SavedEntry) => boolean }[] = [
  { title: "Podcasts and audio", match: (e) => e.kind === "media" && (e.type === "podcast_episode" || e.type === "audio") },
  { title: "Videos (transcripts to read along)", match: (e) => e.kind === "media" && e.type !== "podcast_episode" && e.type !== "audio" },
  { title: "Reading", match: (e) => e.kind === "text" },
  { title: "Manga", match: (e) => e.kind === "manga" },
];

function openLink(entry: SavedEntry): { to: "/watch/$itemId" | "/read/$itemId" | "/manga/$itemId"; itemId: string } {
  const itemId = String(entry.id);
  if (entry.kind === "manga") return { to: "/manga/$itemId", itemId };
  if (entry.kind === "text") return { to: "/read/$itemId", itemId };
  return { to: "/watch/$itemId", itemId };
}

export function DownloadsPage() {
  const { loaded, saved, jobs } = useSavedDownloads();
  const [usage, setUsage] = useState<{ used: number; quota: number } | null>(null);
  const entries = Object.values(saved).sort((a, b) => (b.saved_at ?? "").localeCompare(a.saved_at ?? ""));
  const total = entries.reduce((sum, e) => sum + e.bytes, 0);
  const busy = Object.keys(jobs).length;

  useEffect(() => {
    void storageUsed().then(setUsage);
  }, [entries.length]);

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
      <header className="px-1 pt-1">
        <h1 className="text-[28px] font-bold tracking-tight">Downloads</h1>
        <p className="mt-1.5 text-sm text-ink-2">
          Saved on this {remoteConfig() ? "phone" : "computer"} to use with no connection: reading, lookups in the words you
          meet, and listening work offline. Press <strong className="text-ink">Download</strong> on a text, a manga volume,
          an episode or a video with a transcript to add it here.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <Chip>{entries.length} saved · {formatBytes(total)}</Chip>
          {usage && usage.quota > 0 && <Chip>this device: {formatBytes(usage.used)} used of {formatBytes(usage.quota)} available</Chip>}
          {busy > 0 && <Chip tone="accent">{busy} downloading</Chip>}
        </div>
      </header>

      {loaded && entries.length === 0 && (
        <Panel>
          <p className="text-sm text-ink-2">
            Nothing saved yet. Open something in <Link to="/read" className="text-accent hover:underline">Read</Link> or{" "}
            <Link to="/watch" className="text-accent hover:underline">Watch</Link> and press Download.
          </p>
        </Panel>
      )}

      {GROUPS.map((group) => {
        const list = entries.filter(group.match);
        if (!list.length) return null;
        return (
          <Panel key={group.title}>
            <PanelTitle>{group.title}</PanelTitle>
            <ul className="flex flex-col divide-y divide-white/8">
              {list.map((entry) => {
                const link = openLink(entry);
                return (
                  <li key={entry.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                    <Link to={link.to} params={{ itemId: link.itemId }} className="min-w-0 flex-1 hover:text-accent">
                      <p className="truncate font-semibold">{entry.title}</p>
                      <p className="text-xs text-ink-2">
                        {[entry.creator, formatBytes(entry.bytes), entry.kind === "media" && (entry.hasRecording ? "recording and transcript" : "transcript")]
                          .filter(Boolean)
                          .join(" · ")}
                      </p>
                    </Link>
                    <DownloadButton item={{ id: entry.id, type: entry.type, title: entry.title }} compact />
                  </li>
                );
              })}
            </ul>
          </Panel>
        );
      })}
    </div>
  );
}
