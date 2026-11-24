-- 0003: a much bigger catalogue of suggestions.
--   content_scores.estimated  1 = the level is estimated (from the channel's other videos or the source's level label)
--                             because the item hasn't been analysed yet; 0 = measured from its own words.
--   verify_candidates         background job that fetches captions for estimated videos and measures them.
-- SQLite cannot change a CHECK constraint in place, so the jobs table is rebuilt with its rows.

ALTER TABLE content_scores ADD COLUMN estimated INTEGER NOT NULL DEFAULT 0;
CREATE INDEX ix_scores_estimated ON content_scores(estimated);

CREATE TABLE jobs_new (
  id            INTEGER PRIMARY KEY,
  kind          TEXT NOT NULL CHECK (kind IN
                ('analyze_content','fetch_subtitles','transcribe','ocr_manga','extract_text',
                 'extract_clip','import_dictionary','rescore','tutor_postprocess','backup',
                 'fetch_history_captions','update_content','evolve_profile','build_offline_pack',
                 'verify_candidates')),
  lane          TEXT NOT NULL DEFAULT 'cpu' CHECK (lane IN ('cpu','gpu')),
  status        TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','done','failed','cancelled')),
  priority      INTEGER NOT NULL DEFAULT 5,              -- lower runs first
  payload_json  TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(payload_json)),
  result_json   TEXT CHECK (result_json IS NULL OR json_valid(result_json)),
  progress      REAL NOT NULL DEFAULT 0,
  attempts      INTEGER NOT NULL DEFAULT 0,
  error         TEXT,
  created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  started_at    TEXT,
  finished_at   TEXT
);
INSERT INTO jobs_new (id, kind, lane, status, priority, payload_json, result_json, progress, attempts, error, created_at,
                      started_at, finished_at)
  SELECT id, kind, lane, status, priority, payload_json, result_json, progress, attempts, error, created_at, started_at,
         finished_at FROM jobs;
DROP TABLE jobs;
ALTER TABLE jobs_new RENAME TO jobs;
CREATE INDEX ix_jobs_queue ON jobs(status, lane, priority, created_at);
