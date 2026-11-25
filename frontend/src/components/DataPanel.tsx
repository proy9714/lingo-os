import { useMutation } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { api } from "../api/client";
import { Button, Chip, Panel, PanelTitle, cx } from "./ui";

/**
 * Restore from a backup file: in Settings, and on the first-run screen ("coming from another computer?").
 * Replacing everything is a big step, so it asks once more before going ahead.
 */
export function RestoreBackup({ compact = false }: { compact?: boolean }) {
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const restore = useMutation({
    mutationFn: api.restoreBackup,
    onSuccess: () => {
      // every page starts afresh from the restored data
      window.localStorage.removeItem("lingo.query-cache");
      window.setTimeout(() => window.location.replace("/"), 1800);
    },
  });
  return (
    <div className={cx("flex flex-col gap-2 text-sm", compact ? "" : "well rounded-xl p-3")}>
      <input
        ref={input}
        type="file"
        accept=".lingo,application/zip"
        className="sr-only"
        onChange={(e) => {
          setFile(e.target.files?.[0] ?? null);
          restore.reset();
        }}
      />
      {!file ? (
        <Button className="self-start" onClick={() => input.current?.click()}>
          Restore from a backup…
        </Button>
      ) : restore.isSuccess ? (
        <p role="status" className="text-good">
          Restored your data from {restore.data.manifest.created_at.slice(0, 10)}. Opening it…
          {restore.data.downloading.length > 0 && " Dictionaries download again in the background."}
        </p>
      ) : (
        <div role="alert" className="flex flex-col gap-2 rounded-xl border border-warn/40 bg-warn/10 p-3 text-ink-2">
          <p>
            Replace {compact ? "this new install" : "everything in Lingo OS on this computer"} with <strong className="text-ink">{file.name}</strong>?
            {!compact && " Your current data is saved as a backup in data/backups first."}
          </p>
          <div className="flex gap-2">
            <Button variant="primary" disabled={restore.isPending} onClick={() => restore.mutate(file)}>
              {restore.isPending ? "Restoring…" : "Yes, restore"}
            </Button>
            <Button variant="ghost" disabled={restore.isPending} onClick={() => setFile(null)}>
              Cancel
            </Button>
          </div>
          {restore.isError && <p className="text-red-200">{restore.error.message}</p>}
        </div>
      )}
    </div>
  );
}

/** Settings: everything in one file, to keep safe or move to another computer. */
export function DataPanel() {
  return (
    <Panel aria-labelledby="t-data">
      <PanelTitle id="t-data" aside={<Chip>one file</Chip>}>
        Your data
      </PanelTitle>
      <div className="flex flex-col gap-3 text-sm">
        <p className="leading-relaxed text-ink-2">
          Save everything in one <code>.lingo</code> file: your words, progress and history, settings, books and manga,
          recordings and reports. Keep it somewhere safe, or restore it on another computer. Dictionaries and language models
          aren't in it (they download again), nor are your AI keys.
        </p>
        <a href="/api/data/export" download className="self-start">
          <Button tabIndex={-1}>Download a backup</Button>
        </a>
        <RestoreBackup />
      </div>
    </Panel>
  );
}
