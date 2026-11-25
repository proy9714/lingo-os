import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";

import { api, syncApi } from "../api/client";
import { useActiveLanguage } from "../api/hooks";
import { Button, Chip, Panel, PanelTitle } from "../components/ui";
import { flush, pending } from "../sync/outbox";
import { allPacks, deletePack, savePack } from "../sync/packs";
import {
  disconnect,
  pairWith,
  remoteConfig,
  useSyncState,
} from "../sync/remote";

/** On the phone: connect to the laptop once, then see sync status and manage what's saved for offline reading. */
export function ConnectPage() {
  const [config, setConfig] = useState(remoteConfig);
  return config ? (
    <Connected onDisconnect={() => (disconnect(), setConfig(null))} />
  ) : (
    <Pairing onPaired={() => setConfig(remoteConfig())} />
  );
}

interface Detector {
  detect(source: CanvasImageSource): Promise<{ rawValue: string }[]>;
}

export function Pairing({
  onPaired,
  intro = true,
}: {
  onPaired: () => void;
  intro?: boolean;
}) {
  const [code, setCode] = useState("");
  const [name, setName] = useState("Phone");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [scanning, setScanning] = useState(false);
  const video = useRef<HTMLVideoElement>(null);
  const canScan =
    typeof window !== "undefined" &&
    "BarcodeDetector" in window &&
    Boolean(navigator.mediaDevices?.getUserMedia);

  const connect = async (value: string) => {
    setBusy(true);
    setError(null);
    try {
      await pairWith(value, name.trim() || "Phone");
      onPaired();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't connect");
    } finally {
      setBusy(false);
    }
  };

  // Scan the QR code with the camera where the browser can read barcodes.
  useEffect(() => {
    if (!scanning) return;
    let stream: MediaStream | null = null;
    let stop = false;
    const Ctor = (
      window as unknown as {
        BarcodeDetector: new (o: { formats: string[] }) => Detector;
      }
    ).BarcodeDetector;
    const detector = new Ctor({ formats: ["qr_code"] });
    void (async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: "environment" },
        });
        if (!video.current) return;
        video.current.srcObject = stream;
        await video.current.play();
        while (!stop) {
          const found = await detector.detect(video.current).catch(() => []);
          if (found[0]?.rawValue) {
            setScanning(false);
            setCode(found[0].rawValue);
            void connect(found[0].rawValue);
            return;
          }
          await new Promise((r) => setTimeout(r, 300));
        }
      } catch {
        setError("The camera isn't available; paste the code instead.");
        setScanning(false);
      }
    })();
    return () => {
      stop = true;
      stream?.getTracks().forEach((t) => t.stop());
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scanning]);

  return (
    <div className="mx-auto flex w-full max-w-lg flex-col gap-4">
      {intro && (
        <header className="px-1 pt-1">
          <h1 className="text-[28px] font-bold tracking-tight">
            Connect to your laptop
          </h1>
          <p className="mt-1.5 text-sm text-ink-2">
            On the laptop, open Settings → Phone, turn on syncing and press{" "}
            <strong>Pair a phone</strong>. Both need to be on the same Wi-Fi.
          </p>
        </header>
      )}
      <Panel>
        <label className="flex flex-col gap-1.5 text-sm text-ink-2">
          Name this phone
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={40}
            className="min-h-11 rounded-xl border border-white/14 bg-surface px-3 text-ink"
          />
        </label>
        {canScan && (
          <div className="mt-4">
            {scanning ? (
              <video
                ref={video}
                muted
                playsInline
                className="aspect-square w-full rounded-xl bg-black object-cover"
              />
            ) : (
              <Button
                variant="primary"
                className="w-full"
                disabled={busy}
                onClick={() => setScanning(true)}
              >
                Scan the code
              </Button>
            )}
          </div>
        )}
        <label className="mt-4 flex flex-col gap-1.5 text-sm text-ink-2">
          {canScan ? "Or paste the code's text" : "Paste the code's text"}
          <textarea
            value={code}
            onChange={(e) => setCode(e.target.value)}
            rows={3}
            className="rounded-xl border border-white/14 bg-surface p-2 font-mono text-xs text-ink"
          />
        </label>
        <Button
          className="mt-3 w-full"
          disabled={busy || !code.trim()}
          onClick={() => connect(code)}
        >
          {busy ? "Connecting…" : "Connect"}
        </Button>
        {error && (
          <p role="alert" className="mt-3 text-sm text-red-200">
            {error}
          </p>
        )}
      </Panel>
    </div>
  );
}

function Connected({ onDisconnect }: { onDisconnect: () => void }) {
  const config = remoteConfig();
  const { code } = useActiveLanguage();
  const sync = useSyncState();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const packs = useQuery({ queryKey: ["offline-packs"], queryFn: allPacks });
  const shelf = useQuery({
    queryKey: ["content", code, "", "read"],
    queryFn: () => api.content(code, "", "read"),
  });
  const [message, setMessage] = useState<string | null>(null);
  const [saving, setSaving] = useState<number | null>(null);

  useEffect(() => {
    useSyncState.getState().set({ pending: pending().length });
  }, []);

  const syncNow = async () => {
    setMessage(null);
    try {
      const sent = await flush();
      setMessage(
        sent
          ? `Sent ${sent} change${sent === 1 ? "" : "s"}.`
          : "Everything is in sync.",
      );
      void qc.invalidateQueries();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Couldn't reach the laptop.");
    }
  };

  const saveOffline = async (id: number) => {
    setSaving(id);
    setMessage(null);
    try {
      await savePack(await syncApi.pack(id));
      void qc.invalidateQueries({ queryKey: ["offline-packs"] });
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Couldn't save it.");
    } finally {
      setSaving(null);
    }
  };

  const saved = new Set((packs.data ?? []).map((p) => p.item.id));
  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-4">
      <header className="px-1 pt-1">
        <h1 className="text-[28px] font-bold tracking-tight">Phone sync</h1>
        <p className="mt-1.5 text-sm text-ink-2">
          Connected to {config?.hubName ?? "your laptop"}.
        </p>
      </header>
      <Panel>
        <PanelTitle
          aside={
            sync.online === false ? (
              <Chip tone="warn">offline</Chip>
            ) : sync.online ? (
              <Chip tone="good">laptop in reach</Chip>
            ) : null
          }
        >
          Status
        </PanelTitle>
        <p className="text-sm text-ink-2">
          {sync.pending
            ? `${sync.pending} change${sync.pending === 1 ? "" : "s"} waiting to sync.`
            : "Nothing waiting to sync."}
          {sync.lastSync &&
            ` Last sync ${new Date(sync.lastSync).toLocaleTimeString()}.`}
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <Button variant="primary" onClick={syncNow}>
            Sync now
          </Button>
          <Button
            variant="ghost"
            onClick={() => {
              if (
                window.confirm(
                  "Disconnect this phone? Unsynced changes stay queued until you connect again.",
                )
              )
                onDisconnect();
            }}
          >
            Disconnect
          </Button>
        </div>
        {message && <p className="mt-2 text-sm text-ink-2">{message}</p>}
      </Panel>

      <Panel>
        <PanelTitle>Saved for offline</PanelTitle>
        {!packs.data || packs.data.length === 0 ? (
          <p className="text-sm text-ink-3">
            Nothing yet. Save texts below while you're on the home Wi-Fi.
          </p>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {packs.data.map((p) => (
              <li
                key={p.item.id}
                className="well flex items-center gap-2 rounded-xl px-3 py-2 text-sm"
              >
                <button
                  type="button"
                  className="min-w-0 flex-1 truncate text-left"
                  onClick={() =>
                    void navigate({
                      to: "/read/$itemId",
                      params: { itemId: String(p.item.id) },
                    })
                  }
                >
                  {p.item.title}
                </button>
                <span className="text-xs text-ink-3">
                  {p.pages.length} pages
                </span>
                <Button
                  variant="ghost"
                  onClick={async () => {
                    await deletePack(p.item.id);
                    void qc.invalidateQueries({ queryKey: ["offline-packs"] });
                  }}
                >
                  Remove
                </Button>
              </li>
            ))}
          </ul>
        )}
        {shelf.data && shelf.data.items.length > 0 && sync.online !== false && (
          <>
            <h3 className="mt-4 mb-2 text-xs font-semibold text-ink-2">
              From your shelf
            </h3>
            <ul className="flex flex-col gap-1.5">
              {shelf.data.items
                .filter((i) => !saved.has(i.id))
                .slice(0, 12)
                .map((i) => (
                  <li key={i.id} className="flex items-center gap-2 text-sm">
                    <span className="min-w-0 flex-1 truncate">{i.title}</span>
                    <Button
                      disabled={saving !== null}
                      onClick={() => saveOffline(i.id)}
                    >
                      {saving === i.id ? "Saving…" : "Save offline"}
                    </Button>
                  </li>
                ))}
            </ul>
          </>
        )}
      </Panel>
    </div>
  );
}
