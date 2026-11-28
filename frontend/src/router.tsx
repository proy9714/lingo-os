import { createRootRoute, createRoute, createRouter, lazyRouteComponent } from "@tanstack/react-router";

import { AppShell } from "./components/AppShell";
import { TodayPage } from "./pages/TodayPage";

const rootRoute = createRootRoute({ component: AppShell });

type Component = Parameters<typeof createRoute>[0]["component"];

const page = <TPath extends string>(path: TPath, component: Component) =>
  createRoute({ getParentRoute: () => rootRoute, path, component });

// Today is in the first download; every other page is its own small file, fetched the first time it's opened (or
// when the pointer rests on a link to it), then cached by the browser for good.
const routeTree = rootRoute.addChildren([
  page("/", TodayPage),
  page("/watch", lazyRouteComponent(() => import("./pages/WatchPage"), "WatchPage")),
  page("/watch/$itemId", lazyRouteComponent(() => import("./pages/PlayerPage"), "PlayerPage")),
  page("/listen", lazyRouteComponent(() => import("./pages/PodcastPage"), "PodcastPage")),
  page("/listen/show/$showId", lazyRouteComponent(() => import("./pages/PodcastPage"), "PodcastShowPage")),
  page("/listen/$itemId", lazyRouteComponent(() => import("./pages/PlayerPage"), "PlayerPage")),
  page("/read", lazyRouteComponent(() => import("./pages/ReadPage"), "ReadPage")),
  page("/read/$itemId", lazyRouteComponent(() => import("./pages/ReaderPage"), "ReaderPage")),
  page("/manga", lazyRouteComponent(() => import("./pages/MangaPage"), "MangaPage")),
  page("/manga/$itemId", lazyRouteComponent(() => import("./pages/MangaViewerPage"), "MangaViewerPage")),
  page("/speak", lazyRouteComponent(() => import("./pages/SpeakPage"), "SpeakPage")),
  page("/words", lazyRouteComponent(() => import("./pages/WordsPage"), "WordsPage")),
  page("/grammar", lazyRouteComponent(() => import("./pages/GrammarPage"), "GrammarPage")),
  page("/level", lazyRouteComponent(() => import("./pages/LevelPage"), "LevelPage")),
  page("/settings", lazyRouteComponent(() => import("./pages/SettingsPage"), "SettingsPage")),
  page("/reports", lazyRouteComponent(() => import("./pages/ReportsPage"), "ReportsPage")),
  page("/downloads", lazyRouteComponent(() => import("./pages/DownloadsPage"), "DownloadsPage")),
  page("/connect", lazyRouteComponent(() => import("./pages/ConnectPage"), "ConnectPage")),
  page("/help", lazyRouteComponent(() => import("./pages/HelpPage"), "HelpPage")),
]);

export const router = createRouter({ routeTree, defaultPreload: "intent", scrollRestoration: true });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
