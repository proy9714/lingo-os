import { useNavigate, useRouterState } from "@tanstack/react-router";
import { useEffect, useState } from "react";

import { mediaUrl } from "../api/client";
import { flush, pending } from "./outbox";
import { isNativeApp, refreshHubs, remoteConfig, useSyncState } from "./remote";

/**
 * On the phone: send queued changes when the app opens, comes back to the foreground, gets a connection, and every
 * two minutes. In the Android app with no laptop paired yet, go to the connect screen.
 */
export function usePhoneSync() {
  const navigate = useNavigate();
  const path = useRouterState({ select: (s) => s.location.pathname });

  useEffect(() => {
    if (isNativeApp() && !remoteConfig() && path !== "/connect") void navigate({ to: "/connect" });
  }, [navigate, path]);

  useEffect(() => {
    if (!remoteConfig()) return;
    useSyncState.getState().set({ pending: pending().length });
    void refreshHubs();
    const run = () => void flush().catch(() => undefined);
    const onVisible = () => document.visibilityState === "visible" && run();
    run();
    window.addEventListener("online", run);
    document.addEventListener("visibilitychange", onVisible);
    const timer = window.setInterval(run, 120_000);
    return () => {
      window.removeEventListener("online", run);
      document.removeEventListener("visibilitychange", onVisible);
      window.clearInterval(timer);
    };
  }, []);
}

/** An image or audio address usable on both devices (the phone fetches it through the encrypted channel). */
export function useMediaUrl(path: string): string | undefined {
  const [url, setUrl] = useState<string | undefined>(remoteConfig() ? undefined : path);
  useEffect(() => {
    if (!remoteConfig()) {
      setUrl(path);
      return;
    }
    let live = true;
    setUrl(undefined);
    mediaUrl(path)
      .then((u) => live && setUrl(u))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [path]);
  return url;
}
