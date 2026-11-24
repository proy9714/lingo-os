-- 0004: languages you add yourself.
--   languages.variant    regional variety chosen when the language was added (e.g. 'br' for Brazilian Portuguese)
--   languages.position   the order languages were added (the switcher follows it)
--   languages.direction  'rtl' for Arabic; 'ltr' for the rest
--   install_language     background job that downloads a language's word-splitting model and dictionary
-- SQLite cannot change a CHECK constraint in place, so the jobs table is rebuilt with its rows (as in 0003).

ALTER TABLE languages ADD COLUMN variant TEXT;
ALTER TABLE languages ADD COLUMN position INTEGER NOT NULL DEFAULT 0;
ALTER TABLE languages ADD COLUMN direction TEXT NOT NULL DEFAULT 'ltr' CHECK (direction IN ('ltr','rtl'));
UPDATE languages SET position = CASE code WHEN 'de' THEN 1 WHEN 'es' THEN 2 WHEN 'ja' THEN 3 ELSE 9 END;

CREATE TABLE jobs_new (
  id            INTEGER PRIMARY KEY,
  kind          TEXT NOT NULL CHECK (kind IN
                ('analyze_content','fetch_subtitles','transcribe','ocr_manga','extract_text',
                 'extract_clip','import_dictionary','rescore','tutor_postprocess','backup',
                 'fetch_history_captions','update_content','evolve_profile','build_offline_pack',
                 'verify_candidates','install_language')),
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
