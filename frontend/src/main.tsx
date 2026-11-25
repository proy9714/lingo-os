import "@fontsource-variable/inter";
import "./styles.css";

import { createSyncStoragePersister } from "@tanstack/query-sync-storage-persister";
import { QueryClient } from "@tanstack/react-query";
import { PersistQueryClientProvider, removeOldestQuery } from "@tanstack/react-query-persist-client";
import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { router } from "./router";
import { isNativeApp } from "./sync/remote";

if (isNativeApp()) {
  // the phone app draws edge to edge: room for curved corners, and light status-bar icons on the dark background
  document.documentElement.classList.add("native");
  void import("@capacitor/core").then(({ SystemBars, SystemBarsStyle }) => SystemBars.setStyle({ style: SystemBarsStyle.Dark })).catch(() => undefined);
}

const DAY = 24 * 60 * 60_000;
const queryClient = new QueryClient({
  // A few retries cover the API starting a second after the web server in `npm run dev`. Answers are kept a day
  // (gcTime) so they can be saved below and shown at once next time, then refreshed in the background.
  defaultOptions: { queries: { staleTime: 30_000, gcTime: DAY, retry: 3 } },
});

// The last answers are saved in this browser, so reopening the app shows your pages at once instead of loading
// screens; each is refreshed in the background as soon as it shows. A new version of the app starts afresh.
// settings and languages are always asked afresh: a new data folder or another laptop must never start in old languages
const NOT_SAVED = new Set(["settings", "languages", "language-catalog", "search", "search-suggest", "ai-models", "annotate", "transcript", "manga-page", "shadow-clip", "pages"]);
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
        maxAge: DAY,
        buster: __APP_VERSION__,
        dehydrateOptions: {
          shouldDehydrateQuery: (query) =>
            query.state.status === "success" && !NOT_SAVED.has(String(query.queryKey[0])) && JSON.stringify(query.state.data ?? null).length < 200_000,
        },
      }}
      // saved answers show at once; every one is then fetched afresh in the background (some lists, such as your
      // languages, never refresh on their own while the app is open, and they may have changed since)
      onSuccess={() => void queryClient.invalidateQueries()}
    >
      <RouterProvider router={router} />
    </PersistQueryClientProvider>
  </StrictMode>,
);
