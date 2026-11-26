import "@fontsource-variable/inter";
import "./styles.css";

import { createSyncStoragePersister } from "@tanstack/query-sync-storage-persister";
import { QueryClient } from "@tanstack/react-query";
import { PersistQueryClientProvider, removeOldestQuery } from "@tanstack/react-query-persist-client";
import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { ApiError } from "./api/client";
import { router } from "./router";
import { isNativeApp, onReachability } from "./sync/remote";

if (isNativeApp()) {
  // the phone app draws edge to edge: room for curved corners, and light status-bar icons on the dark background
  document.documentElement.classList.add("native");
  void import("@capacitor/core").then(({ SystemBars, SystemBarsStyle }) => SystemBars.setStyle({ style: SystemBarsStyle.Dark })).catch(() => undefined);
}

const DAY = 24 * 60 * 60_000;
const native = isNativeApp();

/** Don't retry what can't succeed now: offline (status 0) or a request the server refused (4xx). */
function shouldRetry(failures: number, error: unknown): boolean {
  if (error instanceof ApiError && (error.status === 0 || (error.status >= 400 && error.status < 500))) return false;
  return failures < 2;
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 7 * DAY,
      retry: shouldRetry,
      // The app decides itself whether the laptop or server is in reach (sync/remote.ts). With the default ("online")
      // a device without a connection paused every query, so loading screens spun forever instead of showing what's
      // saved or saying you're offline.
      networkMode: "always",
      // on the phone, coming back to the app refreshes only the live lists below, not every page at once
      refetchOnWindowFocus: !native,
    },
    mutations: { networkMode: "always", retry: false },
  },
});

// Back in reach: refresh what failed while offline and the lists that change by themselves.
const LIVE = new Set(["today", "recommend", "feed", "discover-pool", "overview", "words"]);
onReachability((online) => {
  if (!online) return;
  void queryClient.invalidateQueries({ predicate: (q) => q.state.status === "error" || LIVE.has(String(q.queryKey[0])) });
});
if (native) {
  let lastRefresh = 0;
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible" || Date.now() - lastRefresh < 60_000) return;
    lastRefresh = Date.now();
    void queryClient.invalidateQueries({ predicate: (q) => LIVE.has(String(q.queryKey[0])) });
  });
}

// The last answers are saved in this browser, so reopening the app shows your pages at once instead of loading
// screens; each is refreshed in the background as it shows (when it's older than its staleTime). A new version of the
// app starts afresh. Settings and languages are saved too, so the app can open before the laptop or server answers;
// they are always asked again right after opening, and pairing with another laptop clears everything saved.
const NOT_SAVED = new Set(["language-catalog", "search", "search-suggest", "ai-models", "annotate", "transcript", "manga-page", "shadow-clip"]);
const ASK_AGAIN = new Set(["settings", "languages"]);
const persister = createSyncStoragePersister({
  storage: typeof window === "undefined" ? undefined : window.localStorage,
  key: "lingo.query-cache",
  throttleTime: 2000,
  retry: removeOldestQuery, // storage full: drop the oldest answers and try again
});

const root = document.getElementById("root");
if (!root) throw new Error("index.html is missing #root");

createRoot(root).render(
  <StrictMode>
    <PersistQueryClientProvider
      client={queryClient}
      persistOptions={{
        persister,
        maxAge: 14 * DAY,
        buster: __APP_VERSION__,
        dehydrateOptions: {
          shouldDehydrateQuery: (query) =>
            query.state.status === "success" && !NOT_SAVED.has(String(query.queryKey[0])) && JSON.stringify(query.state.data ?? null).length < 200_000,
        },
      }}
      // saved answers show at once; settings and languages (which never refresh by themselves) are asked again now
      onSuccess={() => void queryClient.invalidateQueries({ predicate: (q) => ASK_AGAIN.has(String(q.queryKey[0])) })}
    >
      <RouterProvider router={router} />
    </PersistQueryClientProvider>
  </StrictMode>,
);
