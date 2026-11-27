import { Link } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { hostingApi } from "../api/client";
import type { Hosting } from "../api/types";
import { Button, Chip, Panel, PanelTitle, Skeleton, cx } from "./ui";

export const hostingQuery = { queryKey: ["hosting"], queryFn: hostingApi.get, staleTime: 60_000 };

/**
 * Settings → Where Lingo OS runs. On this laptop (the phone pairs with the laptop), or on your cloud server (the
 * laptop's browser and the phone both use the server). docs/DEPLOY.md, "Two ways to run".
 */
export function HostingPanel() {
  const hosting = useQuery(hostingQuery);
  const data = hosting.data;
  return (
    <Panel aria-labelledby="t-hosting">
      <PanelTitle
        id="t-hosting"
        aside={
          data && (
            <Chip tone="accent">{data.role === "server" ? "this is the cloud server" : data.mode === "cloud" ? "cloud server" : "this laptop"}</Chip>
          )
        }
      >
        Where Lingo OS runs
      </PanelTitle>
      {!data ? <Skeleton className="h-28" /> : data.role === "server" ? <ServerNote data={data} /> : <Chooser data={data} />}
    </Panel>
  );
}

function ServerNote({ data }: { data: Hosting }) {
  return (
    <div className="flex flex-col gap-2 text-sm leading-relaxed text-ink-2">
      <p>
        This Lingo OS is your <strong>cloud server</strong>. Your laptop opens it in a browser and your phone pairs with it
        (Settings → Phone), so both always show the same data.
      </p>
      {data.public_url && (
        <p className="text-xs text-ink-3">
          Its address: <code className="text-ink-2">{data.public_url}</code>. On the laptop, choose <em>On my cloud server</em>{" "}
          under Settings → Where Lingo OS runs and enter this address.
        </p>
      )}
      <p className="text-xs text-ink-3">It updates itself from GitHub (LINGO_UPDATE_CHANNEL on the server).</p>
    </div>
  );
}

function Chooser({ data }: { data: Hosting }) {
  const qc = useQueryClient();
  const [mode, setMode] = useState<Hosting["mode"]>(data.mode);
  const [url, setUrl] = useState(data.cloud_url ?? "");
  const check = useMutation({ mutationFn: () => hostingApi.check(url) });
  const save = useMutation({
    mutationFn: () => hostingApi.set(mode, mode === "cloud" || url ? url : null),
    onSuccess: (next) => {
      qc.setQueryData(hostingQuery.queryKey, next);
      void qc.invalidateQueries({ queryKey: ["sync-status"] });
    },
  });
  const changed = mode !== data.mode || (url || null) !== (data.cloud_url || null);
  return (
    <div className="flex flex-col gap-3 text-sm">
      <Option
        checked={mode === "local"}
        onChange={() => setMode("local")}
        title="On this laptop"
        detail="You use Lingo OS here, and your phone pairs with this laptop and syncs with it: over the home Wi-Fi, or anywhere with Tailscale. The laptop has to be on for the phone to get anything new."
      />
      <Option
        checked={mode === "cloud"}
        onChange={() => setMode("cloud")}
        title="On my cloud server"
        detail="This laptop and your phone both use your always-on server, so they always show the same thing. This laptop's own copy steps aside: its pages send you to the server, and its phone sync and background searches stay off."
      />
      {mode === "cloud" && (
        <div className="well flex flex-col gap-2 rounded-xl p-3">
          <label className="flex flex-col gap-1 text-xs text-ink-2">
            Your server's address
            <input
              value={url}
              onChange={(e) => (setUrl(e.target.value), check.reset())}
              placeholder="https://lingo-os.tail1234.ts.net"
              className="rounded-lg border border-white/14 bg-surface p-2 font-mono text-xs text-ink"
            />
          </label>
          <div className="flex flex-wrap items-center gap-2">
            <Button disabled={!url || check.isPending} onClick={() => check.mutate()}>
              {check.isPending ? "Checking…" : "Check the address"}
            </Button>
            {check.data &&
              (check.data.reachable ? (
                <span className="text-xs text-good">Lingo OS {check.data.version} answers there.</span>
              ) : (
                <span className="text-xs text-warn">No answer ({check.data.error ?? "unknown"}). Is Tailscale on here?</span>
              ))}
            {check.isError && <span className="text-xs text-red-200">{check.error.message}</span>}
          </div>
        </div>
      )}
      <MovingData from={data.mode} to={mode} />
      <div className="flex items-center gap-2">
        <Button variant="primary" disabled={!changed || save.isPending || (mode === "cloud" && !url)} onClick={() => save.mutate()}>
          {save.isPending ? "Saving…" : "Save"}
        </Button>
        {save.isError && <span className="text-xs text-red-200">{save.error.message}</span>}
        {save.isSuccess && !changed && <span className="text-xs text-good">Saved.</span>}
      </div>
      <p className="text-xs text-ink-3">
        Setting up a server:{" "}
        <Link to="/help" hash="server" className="font-semibold text-accent hover:underline">
          step-by-step guide
        </Link>{" "}
        (docs/DEPLOY.md).
      </p>
    </div>
  );
}

function Option({ checked, onChange, title, detail }: { checked: boolean; onChange: () => void; title: string; detail: string }) {
  return (
    <label className={cx("well flex cursor-pointer gap-3 rounded-xl p-3", checked && "ring-1 ring-accent/60")}>
      <input type="radio" name="hosting" checked={checked} onChange={onChange} className="mt-1 size-4 accent-[var(--accent)]" />
      <span className="flex flex-col gap-1">
        <span className="font-semibold">{title}</span>
        <span className="text-xs leading-relaxed text-ink-2">{detail}</span>
      </span>
    </label>
  );
}

/** Switching doesn't copy data: say how to bring it along, in the direction being switched. */
function MovingData({ from, to }: { from: Hosting["mode"]; to: Hosting["mode"] }) {
  if (from === to) return null;
  return (
    <div role="note" className="rounded-xl border border-warn/40 bg-warn/10 p-3 text-xs leading-relaxed text-warn">
      {to === "cloud" ? (
        <>
          <strong>Bring your data along first.</strong> Stop Lingo OS here, then copy this laptop's data to the server:{" "}
          <code>.\deploy\push-data.ps1 -Server lingo-oracle</code>. Then pair your phone again, this time from the server
          (open it, Settings → Phone): on the phone, Disconnect, then scan the new code.
        </>
      ) : (
        <>
          <strong>Bring your data back first.</strong> Stop Lingo OS here, then copy the server's data to this laptop:{" "}
          <code>.\deploy\pull-data.ps1 -Server lingo-oracle</code>. Then turn on Settings → Phone here and pair your phone
          again with this laptop: on the phone, Disconnect, then scan the new code.
        </>
      )}
    </div>
  );
}

/** Shown instead of the pages on a laptop set to use the cloud server (Settings stays reachable, to switch back). */
export function CloudNotice({ url }: { url: string }) {
  return (
    <div className="grid min-h-[60vh] place-items-center px-6">
      <div className="glass flex max-w-md flex-col items-center gap-4 rounded-[20px] p-8 text-center">
        <h1 className="text-xl font-semibold text-ink">Lingo OS runs on your cloud server</h1>
        <p className="text-sm leading-relaxed text-ink-2">
          This laptop is set to use your server, so your laptop and phone always show the same thing. This copy on the
          laptop stays out of the way.
        </p>
        <a href={url} className="rounded-xl bg-accent px-5 py-3 text-sm font-bold text-accent-ink hover:brightness-110">
          Open {url.replace(/^https?:\/\//, "")}
        </a>
        <Link to="/settings" className="text-xs font-semibold text-ink-2 hover:text-ink hover:underline">
          Use this laptop instead (Settings → Where Lingo OS runs)
        </Link>
      </div>
    </div>
  );
}
