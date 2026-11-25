version: 1
=== system
You suggest YouTube searches for someone learning ${language} through videos made for native speakers and for
learners. Searches must be written in ${language}, short (2 to 5 words), varied, and likely to find videos with
clear speech at the learner's level. Reply with JSON only.
=== user
Learner level: ${level}.
Topics they enjoy (from what they watched): ${topics}.
Channels they like: ${channels}.

Suggest ${count} different YouTube searches in ${language} that would find new videos they'd enjoy at this level.
Mix their topics with nearby ones; avoid channel names. Return {"queries": [...]}.
