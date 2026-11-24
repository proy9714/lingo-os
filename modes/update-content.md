# /lingo update-content [lang]

Find new videos and articles near the learner's level. The script does the fetching and scoring; you explain the result.

1. Preview first: `uv run --project backend lingo update-content --lang <code> --dry-run --json`
   (omit `--lang` for all languages). Show how many new videos and articles would be checked, with a few titles.
2. Run it: `uv run --project backend lingo update-content --lang <code> --json`. It checks at most the configured
   number of videos per language (each one is a request to YouTube) and keeps only items in or near the i+1 band.
3. Report per language: `added` videos and `articles_added`, `off_level`, `no_captions`, and the `added_titles`.
   If `stopped_early` is true, YouTube asked for a sign-in: say it's temporary and to try again later; do not retry.
4. Optional extra source: you may use your own web search to suggest **one or two** channels, podcasts or sites in the
   target language at the learner's level. Present them as suggestions with links only. Do not add them anywhere, and
   never send the learner's data (words, history, reports) to a search engine.
5. Never crawl Mokuro Bunko (catalog.mokuro.moe) or the Comprehensible Input Wiki API. The wiki's public language page
   is read by the script itself, at most once a week.
