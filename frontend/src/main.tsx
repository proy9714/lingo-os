import "@fontsource-variable/inter";
import "./styles.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
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

const queryClient = new QueryClient({
  // A few retries cover the API starting a second after the web server in `npm run dev`.
  defaultOptions: { queries: { staleTime: 30_000, retry: 3 } },
});

const root = document.getElementById("root");
if (!root) throw new Error("index.html is missing #root");

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
