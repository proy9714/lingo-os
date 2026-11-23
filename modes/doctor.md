# /lingo doctor

1. Run `uv run --project backend lingo doctor --json`.
2. List any check with `ok: false`:
   - `required: true` means something is broken. Explain the fix in one line (e.g. run `npm run setup`).
   - `required: false` means a later phase needs it. Say which, without alarm.
3. If everything required is fine, say so in one line and mention the next optional item to set up (for example the
   Gemini API key in `.env`).
