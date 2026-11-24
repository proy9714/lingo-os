# /lingo release

Publish a new release on GitHub: short notes on what changed, plus the signed Android APK (phones update through
Obtainium or by downloading it). **Only release when the app itself changed**, and **always get the maintainer's
yes before publishing**: publishing pushes to the public repository and can't be quietly undone.

1. Check: `uv run --project backend lingo release check --json`.
   - `should_release: false` → say so in one line (with `reason`, e.g. "only docs changed since v0.3.0") and stop.
   - `uncommitted_changes` not empty → list them and stop: they must be committed (or stashed) first. Don't commit
     them yourself unless the maintainer asks.
   - `branch` must be `main`.
2. Read what changed: the `commits` (subject and body) and, where a subject is vague, `git show --stat <sha>` or the
   diff of the files in `app_files_changed`. Don't guess from file names alone.
3. Draft the notes for **users, not developers**, in this shape (leave out empty sections; 3–10 bullets in total;
   one line each; no file names, function names or commit hashes):

   ```markdown
   ## New
   - …
   ## Improved
   - …
   ## Fixed
   - …
   ```

   Group related commits into one bullet. Mention anything a user must do after updating (re-pair the phone, a new
   setting to look at). Leave out pure refactors and test-only work.
4. Version: start from `suggested_version`. Use a **minor** bump (0.3.0 → 0.4.0) when there is anything under "New",
   a **patch** bump (0.3.0 → 0.3.1) for fixes and polish only, and **major** only if the maintainer asks.
5. Show the maintainer the proposed version and the notes, and ask: publish? Wait for an explicit yes. If they edit
   the notes or version, use theirs.
6. On yes: write the notes to a temporary file (outside the repository) and run
   `uv run --project backend lingo release publish --version <x.y.z> --notes <file> --json`.
   It runs the tests, sets the version everywhere, builds and signs the APK, commits "Release vX.Y.Z", tags, pushes
   and creates the GitHub release. It takes a few minutes; run it in the background if your terminal allows.
   - For a rehearsal (nothing committed or published) add `--dry-run`.
   - On `error`: show it verbatim. A test or build failure leaves the repository as it was. If the error says the
     commit and tag exist locally (a push or upload failed), follow the commands it gives once the cause is fixed.
7. Report the release `url` and the APK file name in two lines. Don't paste the full notes again.

Never: publish without the yes, skip the tests to get a release out, sign with any key other than the release key,
or delete a published release or tag (ask the maintainer to do that on GitHub if a release must go).
