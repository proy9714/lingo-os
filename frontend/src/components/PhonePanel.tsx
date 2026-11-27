import { Link } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import QRCode from "qrcode";
import { useEffect, useState } from "react";

import { syncApi } from "../api/client";
import type { SyncStatus } from "../api/types";
import { formatDay, localDayOf } from "../lib/format";
import { isNativeApp } from "../sync/remote";
import { hostingQuery } from "./HostingPanel";
import { Button, Chip, Panel, PanelTitle, Skeleton } from "./ui";

/**
 * Settings → Phone, on whichever Lingo OS the phone pairs with: a laptop (the phone syncs over the home Wi-Fi, or
 * Tailscale) or a cloud server (the phone syncs through the server's address). A laptop set to use the cloud server
 * doesn't pair phones at all: it says to pair from the server.
 */
export function PhonePanel() {
  const qc = useQueryClient();
  const status = useQuery({ queryKey: ["sync-status"], queryFn: syncApi.status, refetchInterval: 15_000 });
  const hosting = useQuery({ ...hostingQuery, enabled: !isNativeApp() });
  const toggle = useMutation({
    mutationFn: (enabled: boolean) => syncApi.enable(enabled),
    onSuccess: (data) => qc.setQueryData(["sync-status"], data),
  });
  const pair = useMutation({ mutationFn: () => syncApi.pair("Phone") });
  const remove = useMutation({
    mutationFn: syncApi.remove,
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["sync-status"] }),
  });
  const [qr, setQr] = useState<string | null>(null);

  useEffect(() => {
    if (!pair.data) return;
    void QRCode.toDataURL(pair.data.qr, { margin: 1, width: 280, errorCorrectionLevel: "M" }).then(setQr);
  }, [pair.data]);

  const data = status.data;
  const phones = data?.devices.filter((d) => d.kind === "android" && !d.revoked_at) ?? [];
  const hub = data?.devices.find((d) => d.kind === "hub");
  const server = Boolean(data?.server);
  const cloudUrl = hosting.data?.role === "laptop" && hosting.data.mode === "cloud" ? hosting.data.cloud_url : null;
  const where = server ? "this server" : "this laptop";
  const chip = !data ? null : cloudUrl ? (
    <Chip>pairs with the server</Chip>
  ) : server ? (
    data.enabled ? <Chip tone="good">phones can sync</Chip> : <Chip>off</Chip>
  ) : data.running ? (
    <Chip tone="good">listening on Wi-Fi</Chip>
  ) : (
    <Chip>off</Chip>
  );
  return (
    <Panel aria-labelledby="t-phone">
      <PanelTitle id="t-phone" aside={chip}>
        Phone
      </PanelTitle>
      {!data ? (
        <Skeleton className="h-28" />
      ) : cloudUrl ? (
        <p className="text-sm leading-relaxed text-ink-2">
          This laptop uses your cloud server, so your phone pairs with the server, not with this laptop. Open{" "}
          <a href={cloudUrl} className="font-semibold text-accent hover:underline">
            {cloudUrl.replace(/^https?:\/\//, "")}
          </a>
          , go to Settings → Phone there and press <strong>Pair a phone</strong>.
        </p>
      ) : (
        <div className="flex flex-col gap-3 text-sm">
          <p className="leading-relaxed text-ink-2">
            {server
              ? "Your Android phone uses this server from anywhere (with Tailscale on the phone), and keeps working offline with saved texts; changes sync when it's back in reach."
              : "Your Android phone uses this laptop over your home Wi-Fi (or anywhere with Tailscale), and keeps working offline with saved texts; changes sync when it's back."}{" "}
            Only paired phones can connect, and everything they send is encrypted.
          </p>
          {data.data_dir && (
            <p className="text-xs text-ink-3">
              A phone paired here syncs with the data in <code className="break-all text-ink-2">{data.data_dir}</code>.
            </p>
          )}
          {data.temporary && (
            <p role="alert" className="rounded-xl border border-warn/40 bg-warn/10 p-3 text-xs leading-relaxed text-warn">
              This is a temporary test copy of Lingo OS, not your own data. Don't pair your phone with it: the phone would
              show this copy's languages and lose track of your real progress when it's gone.
            </p>
          )}
          {!data.allowed && <p className="text-xs text-ink-3">Phone sync is turned off for this server.</p>}
          <label className="flex items-center gap-2.5">
            <input
              type="checkbox"
              checked={data.enabled}
              disabled={toggle.isPending || (!data.allowed && !data.enabled)}
              onChange={(e) => toggle.mutate(e.target.checked)}
              className="size-4 accent-[var(--accent)]"
            />
            {server ? "Let phones sync with this server" : "Let a phone sync over this Wi-Fi"}
          </label>
          {data.enabled && data.error && <p className="text-xs text-red-200">The listener couldn't start: {data.error}</p>}
          {data.enabled && server && data.public_url && (
            <p className="text-xs text-ink-3">
              Phones reach it at <code className="text-ink-2">{data.public_url}</code>. Install Tailscale on the phone and
              sign in to the same account.
            </p>
          )}
          {data.enabled && !server && data.running && (
            <p className="text-xs text-ink-3">
              Address: {data.addresses.join(", ") || "unknown"}. If Windows asks whether Python may use the network, allow
              it on <strong>private</strong> networks only.
            </p>
          )}
          {data.enabled && (
            <div className="well rounded-xl p-3">
              {qr && pair.data ? (
                <div className="flex flex-col items-center gap-2 text-center">
                  <img src={qr} alt="Pairing code for the phone app" className="size-56 rounded-lg bg-white p-1" />
                  <p className="text-xs text-ink-2">
                    In the Lingo OS app on your phone, open <strong>Connect</strong> (it's the first screen until the phone is
                    paired; once paired, Disconnect first) and scan this. It works once and expires at{" "}
                    {new Date(pair.data.expires).toLocaleTimeString()}.
                  </p>
                  <Button variant="ghost" onClick={() => (setQr(null), pair.reset())}>
                    Done
                  </Button>
                </div>
              ) : (
                <Button variant="primary" disabled={pair.isPending} onClick={() => pair.mutate()}>
                  Pair a phone
                </Button>
              )}
              {pair.isError && <p className="mt-2 text-xs text-red-200">{pair.error.message}</p>}
            </div>
          )}
          <ul className="flex flex-col gap-1.5">
            <li className="flex items-center justify-between gap-2 text-xs text-ink-3">
              <span>
                {hub?.name ?? (server ? "This server" : "This laptop")} · hub ({where})
              </span>
            </li>
            {phones.map((phone) => (
              <li key={phone.id} className="well flex items-center justify-between gap-2 rounded-xl px-3 py-2">
                <div className="min-w-0">
                  <div className="font-semibold">{phone.name}</div>
                  <div className="text-xs text-ink-3">
                    {phone.last_seen_at ? `last seen ${formatDay(localDayOf(phone.last_seen_at))}` : "never connected"} · {phone.events}{" "}
                    changes synced · {phone.packs} offline items
                  </div>
                </div>
                <Button
                  variant="ghost"
                  onClick={() => {
                    if (window.confirm(`Remove ${phone.name}? It will need to be paired again.`)) remove.mutate(phone.id);
                  }}
                >
                  Remove
                </Button>
              </li>
            ))}
          </ul>
          {data.enabled && !server && <AwayFromHome data={data} onSaved={(next) => qc.setQueryData(["sync-status"], next)} />}
          <p className="text-xs text-ink-3">
            Install the phone app from GitHub releases (Obtainium keeps it updated).{" "}
            <Link to="/help" hash="phone" className="font-semibold text-accent hover:underline">
              Step-by-step guide
            </Link>
          </p>
        </div>
      )}
    </Panel>
  );
}

/** Syncing away from home: Tailscale (free) puts the laptop and the phone on one private network anywhere. */
function AwayFromHome({ data, onSaved }: { data: SyncStatus; onSaved: (status: SyncStatus) => void }) {
  const [text, setText] = useState(data.extra_addresses.join("\n"));
  const save = useMutation({
    mutationFn: () => syncApi.setAddresses(text.split(/[\s,]+/).filter(Boolean)),
    onSuccess: onSaved,
  });
  return (
    <details className="well rounded-xl p-3 text-sm" open={data.tailscale.length > 0 || data.extra_addresses.length > 0}>
      <summary className="cursor-pointer font-semibold">Sync away from home</summary>
      <div className="mt-2 flex flex-col gap-2 text-ink-2">
        <p className="text-xs leading-relaxed">
          Install <strong>Tailscale</strong> (free) on this laptop and on the phone, and sign in to the same account on both. The
          phone then reaches the laptop over mobile data too, still encrypted end to end.{" "}
          {data.tailscale.length > 0
            ? `Tailscale is running here (${data.tailscale.join(", ")}): paired phones learn this address on their next sync.`
            : "Once Tailscale runs here, its address is found by itself."}
        </p>
        <label className="flex flex-col gap-1 text-xs">
          Other addresses for this laptop (optional, one per line), such as its Tailscale name
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={2}
            placeholder="laptop.tail1234.ts.net"
            className="rounded-lg border border-white/14 bg-surface p-2 font-mono text-xs text-ink"
          />
        </label>
        <div className="flex items-center gap-2">
          <Button disabled={save.isPending} onClick={() => save.mutate()}>
            {save.isPending ? "Saving…" : "Save addresses"}
          </Button>
          {save.isSuccess && <span className="text-xs text-good">Saved: phones pick them up on their next sync.</span>}
          {save.isError && <span className="text-xs text-red-200">{save.error.message}</span>}
        </div>
      </div>
    </details>
  );
}
