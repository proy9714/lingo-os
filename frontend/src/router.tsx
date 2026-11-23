import { createRootRoute, createRoute, createRouter } from "@tanstack/react-router";

import { AppShell } from "./components/AppShell";
import { ComingSoonPage, PREVIEWS } from "./pages/ComingSoonPage";
import { LevelPage } from "./pages/LevelPage";
import { ReadPage } from "./pages/ReadPage";
import { SettingsPage } from "./pages/SettingsPage";
import { TodayPage } from "./pages/TodayPage";
import { WordsPage } from "./pages/WordsPage";

const rootRoute = createRootRoute({ component: AppShell });

const page = <TPath extends string>(path: TPath, component: () => React.JSX.Element) =>
  createRoute({ getParentRoute: () => rootRoute, path, component });

const preview = (key: keyof typeof PREVIEWS) => () => <ComingSoonPage preview={PREVIEWS[key]} />;

const routeTree = rootRoute.addChildren([
  page("/", TodayPage),
  page("/watch", preview("watch")),
  page("/read", ReadPage),
  page("/manga", preview("manga")),
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
