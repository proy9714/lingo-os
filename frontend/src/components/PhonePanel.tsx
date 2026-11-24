import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import QRCode from "qrcode";
import { useEffect, useState } from "react";

import { syncApi } from "../api/client";
import { formatDay, localDayOf } from "../lib/format";
import { Button, Chip, Panel, PanelTitle, Skeleton } from "./ui";

/** Settings on the laptop: let a phone sync over the home Wi-Fi, pair it with a QR code, remove phones. */
export function PhonePanel() {
  const qc = useQueryClient();
  const status = useQuery({ queryKey: ["sync-status"], queryFn: syncApi.status, refetchInterval: 15_000 });
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
  return (
    <Panel aria-labelledby="t-phone">
      <PanelTitle
        id="t-phone"
        aside={data && (data.running ? <Chip tone="good">listening on Wi-Fi</Chip> : <Chip>off</Chip>)}
      >
        Phone
      </PanelTitle>
      {!data ? (
        <Skeleton className="h-28" />
      ) : (
        <div className="flex flex-col gap-3 text-sm">
          <p className="leading-relaxed text-ink-2">
            Your Android phone uses this laptop over your home Wi-Fi, and keeps working offline with saved texts; changes
            sync when it's back. Only paired phones can connect, and everything they send is encrypted.
          </p>
          <label className="flex items-center gap-2.5">
            <input
              type="checkbox"
              checked={data.enabled}
              disabled={toggle.isPending}
              onChange={(e) => toggle.mutate(e.target.checked)}
              className="size-4 accent-[var(--accent)]"
            />
            Let a phone sync over this Wi-Fi
          </label>
          {data.enabled && data.error && <p className="text-xs text-red-200">The listener couldn't start: {data.error}</p>}
          {data.enabled && data.running && (
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
                    In the Lingo OS app on your phone, choose <strong>Connect to your laptop</strong> and scan this. It works
                    once and expires at {new Date(pair.data.expires).toLocaleTimeString()}.
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
              <span>{hub?.name ?? "This laptop"} · hub</span>
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
          <p className="text-xs text-ink-3">
            The phone app is built from this project with Android Studio: see <code>docs/PHONE.md</code>.
          </p>
        </div>
      )}
    </Panel>
  );
}
