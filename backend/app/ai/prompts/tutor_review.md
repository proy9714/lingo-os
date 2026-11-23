version: 1
=== system
You review a ${language} conversation between a learner (level about ${level}) and a tutor. Be accurate, kind and brief. Write explanations in English.
=== user
Conversation (learner turns are numbered L1, L2, …; tutor turns are T):
${transcript}

Return a JSON object with:
- "summary": 2 to 3 sentences in English on what was discussed and how the learner did.
- "strengths": up to 3 short things the learner did well (English).
- "corrections": every real mistake in the learner's turns (not style preferences), each with
  "turn" (the number from L1, L2, …), "original" (the learner's words, copied exactly), "corrected" (the natural ${language} version),
  "explanation" (one short English sentence) and "grammar" (a textbook name for the grammar point, such as "dative after mit",
  "ser vs estar" or "te-form + iru"; "" if it is a vocabulary or spelling slip).
- "words_used": ${language} dictionary forms of less common words the learner used correctly.
