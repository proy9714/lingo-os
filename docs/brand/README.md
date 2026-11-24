# Lingo OS logo

Four letters from four writing systems on four tiles: **A** (Latin), **あ** (Japanese kana), **文** (Chinese
character), **Я** (Cyrillic), in the colours the app uses for its languages.

| File | Use |
|---|---|
| `logo.svg` | The icon: dark rounded square with the tiles (also `frontend/public/favicon.svg`) |
| `logo-round.svg` | The same on a circle (Android round launcher icon) |
| `logo-mark.svg` | The tiles alone, transparent (Android adaptive icon foreground, in-app use) |
| `logo-256.png`, `logo-1024.png` | Raster versions (README, social preview) |

The letters are outlines (no font needed to display them), taken at weight 800 from
[Inter](https://rsms.me/inter/) (A, Я) and [Noto Sans JP](https://fonts.google.com/noto/specimen/Noto+Sans+JP)
(あ, 文), both under the SIL Open Font License 1.1. The in-app `<Logo />` uses the same paths
(`frontend/src/components/logoPaths.ts`). The Android launcher icons and splash screens in
`frontend/android/app/src/main/res` are rendered from these files.
