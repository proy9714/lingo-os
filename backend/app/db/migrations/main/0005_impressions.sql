-- 0005: what the suggestions showed you, so things you keep scrolling past sink (services/ranker.py).
--   shown            times the card was on screen (counted at most once every 6 hours)
--   first/last_shown_at  when

CREATE TABLE item_impressions (
  content_item_id  INTEGER PRIMARY KEY REFERENCES content_items(id) ON DELETE CASCADE,
  shown            INTEGER NOT NULL DEFAULT 0,
  first_shown_at   TEXT,
  last_shown_at    TEXT
);
