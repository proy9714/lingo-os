# /lingo recommend [lang]

1. Run `uv run --project backend lingo recommend --json` (add `--lang <code>` if the user named a language).
2. Show the picks as a numbered list: title, channel or author, and the `reasons` joined with " · ".
   Mark `band: "stretch"` picks as a stretch and `comfortable` ones as easy listening.
3. If `available` is below 10, say that only that many items have been analysed and suggest one way to get more:
   `uv run --project backend lingo content fetch-history` (captions of watched videos), adding a book or article on
   the Read page, or `/lingo update-content`.
4. Do not reorder the picks or invent new ones. Never turn saved words into a review list: they come back through
   these picks ("brings back N of your saved words").
