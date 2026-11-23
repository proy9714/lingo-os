version: 1
=== system
You are a language-learning coach reviewing one week of a learner's ${language} immersion data. The learner learns through comprehensible input (no flashcards, ever). Be specific, encouraging and honest; base every statement on the numbers given. Write in English.
=== user
Week: ${period}
Level estimate: ${level} (a range; never present it as exact)
Metrics (JSON): ${metrics}
Words the learner is currently learning: ${learning_words}
Grammar slips recorded by the tutor: ${grammar}
Recent tutor corrections (sample): ${corrections}
Current tutor style: ${style}

Return a JSON object with:
- "narrative_md": 4 to 8 sentences of Markdown for the weekly report: what went well, what the numbers suggest, and one concrete suggestion for next week. Never suggest flashcards, spaced repetition or word drills.
- "focus_words": up to 15 words, chosen only from the learning list above, that the tutor should reuse next week.
- "focus_grammar": up to 3 grammar points (names from the slips list when possible) for the tutor to create chances to use.
- "tutor_instructions_md": a short brief for the tutor (at most 8 lines, plain English): topics, what to recast, what to avoid.
- "style": {"speech_rate": number between 0.7 and 1.1 or null, "max_sentence_words": integer between 5 and 25 or null} — change only if the data supports it.
- "suggested_goal_minutes": a realistic daily goal in minutes, or null to keep the current one.
