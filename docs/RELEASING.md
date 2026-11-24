# Releasing Lingo OS (maintainers)

A release is a GitHub release with short notes and the signed Android APK (`lingo-os-vX.Y.Z.apk`). Phones install
it from the release page or follow it with [Obtainium](https://github.com/ImranR98/Obtainium). The laptop app updates
with `git pull`.

## Making a release

In an AI terminal opened in the project folder (Claude Code, Gemini CLI, Codex…):

```
/lingo release
```

It checks the last release, stops if only docs or tests changed, drafts the notes and a version, and **asks before
publishing**. Without an AI terminal, the same two steps by hand:

```powershell
uv run --project backend lingo release check
uv run --project backend lingo release publish --version 0.3.0 --notes notes.md --dry-run
uv run --project backend lingo release publish --version 0.3.0 --notes notes.md
```

`publish` runs the tests, sets the version in `package.json`, `frontend/package.json`, `backend/pyproject.toml` and
`backend/app/__init__.py`, builds and signs the APK, commits "Release v0.3.0", tags `v0.3.0`, pushes, and creates the
release with the APK attached. A failed test or build leaves the repository unchanged. `--dry-run` does everything
except commit and publish, and leaves the APK in `release/`.

Versions: minor (0.3.0 → 0.4.0) for new features, patch (0.3.0 → 0.3.1) for fixes. Android's `versionCode` is
derived from the version (`major·10000 + minor·100 + patch`), so it always grows.

## One-time setup

- **JDK 21** (`JAVA_HOME`) and the **Android SDK** (`ANDROID_HOME`) with `platforms;android-36` and build-tools 36.
  Android Studio brings both, or the command-line tools alone:
  `android sdk install platforms/android-36 build-tools/36.1.0 platform-tools`.
- **GitHub CLI**, logged in: `gh auth login`.
- **The release signing key**, in `%USERPROFILE%\.lingo\` (or the path in `LINGO_KEYSTORE_PROPERTIES`):
  `lingo-release.jks` and `release-keystore.properties` (store path, passwords, alias, and the certificate's SHA-256).
  It is never committed. `publish` refuses an APK signed with any other key.

## Back up the signing key

**Copy `%USERPROFILE%\.lingo\` somewhere safe (a password manager, an encrypted drive).** Android only installs an
update signed with the same key as the installed app. If the key is lost, every phone has to uninstall the app (losing
anything not yet synced) and install the new one, and Obtainium stops updating.

Certificate SHA-256 of the current key (shown to users so they can check an APK):
`92:59:B0:4D:71:5C:53:B8:20:5E:F5:62:47:25:35:67:13:AA:88:42:0A:DC:D2:0E:D4:D7:99:DD:25:47:72:4B`
