import { createRootRoute, createRoute, createRouter } from "@tanstack/react-router";

import { AppShell } from "./components/AppShell";
import { ComingSoonPage, PREVIEWS } from "./pages/ComingSoonPage";
import { LevelPage } from "./pages/LevelPage";
import { MangaPage } from "./pages/MangaPage";
import { MangaViewerPage } from "./pages/MangaViewerPage";
import { PlayerPage } from "./pages/PlayerPage";
import { WatchPage } from "./pages/WatchPage";
import { ReadPage } from "./pages/ReadPage";
import { ReaderPage } from "./pages/ReaderPage";
import { SettingsPage } from "./pages/SettingsPage";
import { TodayPage } from "./pages/TodayPage";
import { WordsPage } from "./pages/WordsPage";

const rootRoute = createRootRoute({ component: AppShell });

const page = <TPath extends string>(path: TPath, component: () => React.JSX.Element) =>
  createRoute({ getParentRoute: () => rootRoute, path, component });

const preview = (key: keyof typeof PREVIEWS) => () => <ComingSoonPage preview={PREVIEWS[key]} />;

const routeTree = rootRoute.addChildren([
  page("/", TodayPage),
  page("/watch", WatchPage),
  page("/watch/$itemId", PlayerPage),
  page("/read", ReadPage),
  page("/read/$itemId", ReaderPage),
  page("/manga", MangaPage),
  page("/manga/$itemId", MangaViewerPage),
  page("/speak", preview("speak")),
  page("/words", WordsPage),
  page("/level", LevelPage),
  page("/settings", SettingsPage),
]);

export const router = createRouter({ routeTree, defaultPreload: "intent" });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
