# /lingo tutor-brief [de|es|ja]

Show or edit the brief the AI tutor follows next week.

1. Show it: `uv run --project backend lingo tutor-brief show --lang <code> --json`.
2. If the learner wants changes, write `data/proposals/brief-<code>.json`:
   ```json
   {"tutor_instructions_md": "Topics, what to recast, what to avoid (at most 8 lines).",
    "focus_words": ["words the learner is learning"],
    "focus_grammar": ["up to 3 points"],
    "style": {"speech_rate": 0.9, "max_sentence_words": 12}}
   ```
   Focus words must come from the learning list (`lingo evolve-profile --dry-run --json` → `context.learning_words`).
3. Apply: `uv run --project backend lingo tutor-brief set --lang <code> --file data/proposals/brief-<code>.json`.
   Report any guardrail notes it prints (speech rate changes by at most 0.1, sentence length by at most 3 words).
