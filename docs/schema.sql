-- =====================================================================
--  Lingo OS — SQLite schema v1 (planning draft, validated against SQLite 3.45)
--
--  Main DB        : data/lingo.db
--  Dictionary DB  : data/dictionaries.db  (ATTACHed as "dict"; section 4)
--                   Kept separate because it is large, rebuildable and
--                   should not bloat backups of your personal data.
--
--  Conventions
--   * Timestamps : TEXT, ISO-8601 UTC  e.g. '2026-11-23T18:04:05.123Z'
--   * Positions  : INTEGER ms for media; TEXT "locator" for documents
--                  (EPUB CFI | 'page:12' | 'para:40' | 'manga:p12:b3' | 'ms:93120')
--   * Durations  : INTEGER seconds
--   * *_json     : TEXT holding JSON, enforced with json_valid()
--   * Languages  : ISO 639-1 ('de','es','ja'). Adding a language later =
--                  1 row in `languages` + 1 LanguagePack class. No schema change.
--   * Connection : PRAGMA foreign_keys=ON; journal_mode=WAL;
--                  synchronous=NORMAL; busy_timeout=5000
--  Runtime migrations live in backend/app/db/migrations/{main,dict}/NNNN_*.sql;
--  backend/tests/test_migrations.py fails if they drift from this file.
-- =====================================================================

PRAGMA foreign_keys = ON;

-- =====================================================================
-- 1. LANGUAGES & SETTINGS
-- =====================================================================

CREATE TABLE languages (
  code             TEXT PRIMARY KEY,                     -- 'de' | 'es' | 'ja'
  name             TEXT NOT NULL,                        -- 'German'
  native_name      TEXT NOT NULL,                        -- 'Deutsch'
  definition_lang  TEXT NOT NULL DEFAULT 'en',           -- language for glosses/explanations
  writing_mode     TEXT NOT NULL DEFAULT 'horizontal-tb'
                   CHECK (writing_mode IN ('horizontal-tb','vertical-rl')),
  accent_color     TEXT,                                 -- per-language UI tint
  enabled          INTEGER NOT NULL DEFAULT 1,
  settings_json    TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(settings_json))
);

-- UI/runtime preferences editable in Settings. Provider credentials are NOT
-- stored here: they live in .env; model routing lives in config/llm.yaml.
CREATE TABLE app_settings (
  key         TEXT PRIMARY KEY,
  value_json  TEXT NOT NULL CHECK (json_valid(value_json)),
  updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- =====================================================================
-- 2. PROFICIENCY PROFILE, REPORTS, GOALS
-- =====================================================================

-- The live `User_Proficiency_Profile`, one row per language.
-- Vocabulary model:  P(known | freq rank r) = 1 / (1 + exp(k * (ln r - ln r50)))
CREATE TABLE proficiency_profiles (
  language_code        TEXT PRIMARY KEY REFERENCES languages(code),
  version              INTEGER NOT NULL DEFAULT 1,       -- bumped on every recalibration
  vocab_r50            REAL NOT NULL,                    -- rank where P(known)=0.5 (the "frontier")
  vocab_k              REAL NOT NULL DEFAULT 1.6,        -- curve steepness
  est_vocab_size       INTEGER NOT NULL,                 -- Σ P(known) over the frequency list
  est_level            TEXT,                             -- CEFR estimate, e.g. 'B1'
  est_level_alt        TEXT,                             -- JLPT estimate for ja, e.g. 'N3'
  level_confidence     REAL NOT NULL DEFAULT 0.3,        -- 0..1, grows with evidence
  comfort_reading      REAL NOT NULL DEFAULT 0.5,        -- 0..1
  comfort_listening    REAL NOT NULL DEFAULT 0.5,
  comfort_speaking     REAL NOT NULL DEFAULT 0.3,
  comfortable_wpm      REAL,                             -- speech rate handled comfortably
  read_cov_min         REAL NOT NULL DEFAULT 0.85,       -- i+1 band for text
  read_cov_max         REAL NOT NULL DEFAULT 0.95,
  listen_cov_min       REAL NOT NULL DEFAULT 0.88,       -- i+1 band for audio/video
  listen_cov_max       REAL NOT NULL DEFAULT 0.97,
  total_seconds        INTEGER NOT NULL DEFAULT 0,
  seconds_by_modality_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(seconds_by_modality_json)),
  profile_json         TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(profile_json)), -- full document (ARCHITECTURE §5.3)
  updated_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- Weekly (or ad-hoc) progress reports produced by `evolve-profile`.
CREATE TABLE progress_reports (
  id               INTEGER PRIMARY KEY,
  language_code    TEXT REFERENCES languages(code),      -- NULL = combined report
  period_start     TEXT NOT NULL,
  period_end       TEXT NOT NULL,
  metrics_json     TEXT NOT NULL CHECK (json_valid(metrics_json)),      -- deterministic numbers
  narrative_md     TEXT,                                                -- LLM-written (NULL with --no-llm)
  adjustments_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(adjustments_json)), -- what changed & why
  llm_model        TEXT,
  markdown_path    TEXT,                                 -- data/reports/2026-W48.md
  created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- Immutable history of the profile, for charts and rollback.
CREATE TABLE profile_snapshots (
  id               INTEGER PRIMARY KEY,
  language_code    TEXT NOT NULL REFERENCES languages(code),
  profile_version  INTEGER NOT NULL,
  reason           TEXT NOT NULL CHECK (reason IN
                   ('baseline','csv_import','assessment','weekly_evolve','manual','recompute')),
  profile_json     TEXT NOT NULL CHECK (json_valid(profile_json)),
  report_id        INTEGER REFERENCES progress_reports(id) ON DELETE SET NULL,
  created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE (language_code, profile_version)
);

-- ---------- Level Lab (ARCHITECTURE §6.12) ----------
-- One row per test session. Skills are measured separately; θ is an IRT
-- ability estimate on that skill's scale, with its standard error.
CREATE TABLE assessments (
  id               INTEGER PRIMARY KEY,
  language_code    TEXT NOT NULL REFERENCES languages(code),
  skill            TEXT NOT NULL CHECK (skill IN ('vocabulary','listening','reading','speaking','grammar')),
  method           TEXT NOT NULL CHECK (method IN
                   ('vocab_adaptive','dictation','comprehension','c_test','reading_speed',
                    'elicited_imitation','conversation_rubric','grammar_items','external_exam')),
  status           TEXT NOT NULL DEFAULT 'in_progress' CHECK (status IN ('in_progress','done','abandoned')),
  theta            REAL,
  theta_se         REAL,
  raw_score        REAL,                                 -- C-test % correct, dictation WER, ...
  result_json      TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(result_json)),
                   -- vocab size + interval, false-alarm rate, comfortable wpm, fluency metrics ...
  external_exam    TEXT,                                 -- 'Goethe B1', 'DELE B2', 'JLPT N3' (method = external_exam)
  client_uuid      TEXT UNIQUE,
  started_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  finished_at      TEXT
);
CREATE INDEX ix_assessments_lang ON assessments(language_code, skill, finished_at);

-- Every item shown, with the running estimate after it (full audit trail).
CREATE TABLE assessment_items (
  id               INTEGER PRIMARY KEY,
  assessment_id    INTEGER NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
  seq              INTEGER NOT NULL,
  item_type        TEXT NOT NULL CHECK (item_type IN
                   ('yes_no','pseudo_word','meaning_choice','reading_input','dictation',
                    'c_gap','comprehension_choice','imitation','grammar_choice')),
  lexeme_id        INTEGER REFERENCES lexemes(id) ON DELETE SET NULL,
  difficulty       REAL,                                 -- IRT b-parameter (rank, speed, length ...)
  prompt_json      TEXT NOT NULL CHECK (json_valid(prompt_json)),
  response         TEXT,
  score            REAL,                                 -- 0..1, partial credit allowed
  response_ms      INTEGER,
  theta_after      REAL,
  UNIQUE (assessment_id, seq)
);

-- Current ability per language × skill. Uncertainty widens slowly between tests.
CREATE TABLE skill_estimates (
  language_code    TEXT NOT NULL REFERENCES languages(code),
  skill            TEXT NOT NULL CHECK (skill IN ('vocabulary','listening','reading','speaking','grammar')),
  theta            REAL NOT NULL,
  theta_se         REAL NOT NULL,
  band             TEXT,                                 -- 'B1' | 'N3'
  band_low         TEXT,                                 -- 90% interval
  band_high        TEXT,
  last_tested_at   TEXT,
  updated_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  PRIMARY KEY (language_code, skill)
);

CREATE TABLE goals (
  id             INTEGER PRIMARY KEY,
  language_code  TEXT NOT NULL REFERENCES languages(code),
  period         TEXT NOT NULL CHECK (period IN ('daily','weekly','monthly')),
  metric         TEXT NOT NULL CHECK (metric IN ('minutes','words_learned','tutor_minutes','pages','episodes')),
  modality       TEXT CHECK (modality IN ('listening','reading','speaking','writing')),
  target         REAL NOT NULL,
  active         INTEGER NOT NULL DEFAULT 1,
  created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- Topics you care about; drive content discovery and tutor small talk.
CREATE TABLE interests (
  id             INTEGER PRIMARY KEY,
  language_code  TEXT NOT NULL DEFAULT '*',              -- '*' = all languages
  topic          TEXT NOT NULL,
  weight         REAL NOT NULL DEFAULT 1.0,
  origin         TEXT NOT NULL CHECK (origin IN ('manual','csv_import','engagement','evolve')),
  updated_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE (language_code, topic)
);

-- =====================================================================
-- 3. VOCABULARY
-- =====================================================================

-- Dictionary-independent word identity. Created lazily for every lemma the
-- analyzer meets in any content, so coverage can be computed by SQL join.
CREATE TABLE lexemes (
  id             INTEGER PRIMARY KEY,
  language_code  TEXT NOT NULL REFERENCES languages(code),
  lemma          TEXT NOT NULL,                          -- 'anrufen' | 'comer' | '食べる'
  reading        TEXT NOT NULL DEFAULT '',               -- ja kana reading ('たべる'); '' otherwise
  pos            TEXT NOT NULL DEFAULT '',               -- most frequent UPOS seen (NOUN, VERB...)
  freq_rank      INTEGER,                                -- rank in frequency list; NULL = unranked
  zipf           REAL,                                   -- wordfreq Zipf score
  is_proper      INTEGER NOT NULL DEFAULT 0,             -- names: excluded from coverage
  extra_json     TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(extra_json)), -- gender, plural, pitch accent...
  created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE (language_code, lemma, reading)
);
CREATE INDEX ix_lexemes_rank ON lexemes(language_code, freq_rank);

-- Your relationship with a word. No row = never interacted (engine falls back
-- to the frequency model for P(known)).
CREATE TABLE user_words (
  lexeme_id          INTEGER PRIMARY KEY REFERENCES lexemes(id) ON DELETE CASCADE,
  status             TEXT NOT NULL DEFAULT 'seen'
                     CHECK (status IN ('seen','learning','familiar','known','ignored')),
  p_known            REAL NOT NULL,                      -- engine belief 0..1
  saved              INTEGER NOT NULL DEFAULT 0,         -- 1 = explicit "Save to Vocab"
  exposures          INTEGER NOT NULL DEFAULT 0,         -- times met in consumed content
  lookups            INTEGER NOT NULL DEFAULT 0,
  tutor_heard        INTEGER NOT NULL DEFAULT 0,
  tutor_used_ok      INTEGER NOT NULL DEFAULT 0,         -- used correctly in conversation
  user_gloss         TEXT,                               -- the meaning you chose to keep
  user_note          TEXT,
  tags_json          TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(tags_json)),
  first_seen_at      TEXT,
  last_seen_at       TEXT,
  last_lookup_at     TEXT,
  status_changed_at  TEXT,
  updated_hlc        TEXT                                -- clock of the last edit: last-writer-wins across devices
);
CREATE INDEX ix_user_words_status ON user_words(status, status_changed_at);

-- Every sentence a word was looked up or saved in, with a jump-back locator.
CREATE TABLE word_contexts (
  id                   INTEGER PRIMARY KEY,
  lexeme_id            INTEGER NOT NULL REFERENCES lexemes(id) ON DELETE CASCADE,
  content_item_id      INTEGER REFERENCES content_items(id) ON DELETE SET NULL,
  surface              TEXT NOT NULL,                    -- form as it appeared ('rief … an')
  sentence             TEXT NOT NULL,
  sentence_translation TEXT,
  locator              TEXT,                             -- 'ms:93120' | CFI | 'page:12' | 'manga:p12:b3'
  screenshot_path      TEXT,                             -- video frame / manga panel crop
  audio_path           TEXT,                             -- sentence audio snippet
  client_uuid          TEXT UNIQUE,
  created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX ix_word_contexts_lexeme ON word_contexts(lexeme_id);

-- Append-only evidence log feeding the adaptive engine. Exposures are written
-- aggregated: one row per (lexeme, activity session) with value = count.
CREATE TABLE word_events (
  id                   INTEGER PRIMARY KEY,
  lexeme_id            INTEGER NOT NULL REFERENCES lexemes(id) ON DELETE CASCADE,
  event                TEXT NOT NULL CHECK (event IN
                       ('lookup','save','status_change','exposure','tutor_heard',
                        'tutor_used_ok','tutor_misused','test_known','test_unknown','shadowed')),
  value                TEXT,                             -- new status, exposure count, ...
  client_uuid          TEXT UNIQUE,                      -- set when the event came from the phone
  content_item_id      INTEGER REFERENCES content_items(id) ON DELETE SET NULL,
  activity_session_id  INTEGER REFERENCES activity_sessions(id) ON DELETE SET NULL,
  created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX ix_word_events_time   ON word_events(created_at);
CREATE INDEX ix_word_events_lexeme ON word_events(lexeme_id, created_at);

-- =====================================================================
-- 4. DICTIONARIES   (lives in data/dictionaries.db, ATTACHed as "dict")
--    Import format: Yomitan dictionary zips (JMdict/Jitendex, KANJIDIC,
--    pitch-accent dicts, Wiktionary-derived de/es dicts, frequency dicts).
-- =====================================================================

CREATE TABLE dictionaries (
  id             INTEGER PRIMARY KEY,
  language_code  TEXT NOT NULL,                          -- no FK: separate database file
  name           TEXT NOT NULL,
  kind           TEXT NOT NULL CHECK (kind IN ('term','kanji','frequency','pitch','grammar')),
  format         TEXT NOT NULL CHECK (format IN ('yomitan','stardict','csv','builtin')),
  revision       TEXT,
  attribution    TEXT,                                   -- licence text (JMdict & Wiktionary are CC BY-SA)
  source_path    TEXT,
  priority       INTEGER NOT NULL DEFAULT 100,           -- lower = shown first
  enabled        INTEGER NOT NULL DEFAULT 1,
  entry_count    INTEGER NOT NULL DEFAULT 0,
  imported_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE (language_code, name, revision)
);

CREATE TABLE dict_terms (
  id              INTEGER PRIMARY KEY,
  dictionary_id   INTEGER NOT NULL REFERENCES dictionaries(id) ON DELETE CASCADE,
  term            TEXT NOT NULL,
  reading         TEXT NOT NULL DEFAULT '',
  definition_tags TEXT,
  rules           TEXT,                                  -- Yomitan deinflection rule ids (v1, v5, adj-i ...)
  score           INTEGER NOT NULL DEFAULT 0,
  glossary_json   TEXT NOT NULL CHECK (json_valid(glossary_json)), -- strings or structured-content
  sequence        INTEGER,
  term_tags       TEXT
);
CREATE INDEX ix_dict_terms_term    ON dict_terms(term);
CREATE INDEX ix_dict_terms_reading ON dict_terms(reading);

CREATE TABLE dict_term_meta (                            -- frequency / pitch / IPA per term
  id             INTEGER PRIMARY KEY,
  dictionary_id  INTEGER NOT NULL REFERENCES dictionaries(id) ON DELETE CASCADE,
  term           TEXT NOT NULL,
  reading        TEXT NOT NULL DEFAULT '',
  mode           TEXT NOT NULL CHECK (mode IN ('freq','pitch','ipa')),
  data_json      TEXT NOT NULL CHECK (json_valid(data_json))
);
CREATE INDEX ix_dict_meta_term ON dict_term_meta(term, mode);

CREATE TABLE dict_kanji (
  id             INTEGER PRIMARY KEY,
  dictionary_id  INTEGER NOT NULL REFERENCES dictionaries(id) ON DELETE CASCADE,
  character      TEXT NOT NULL,
  onyomi         TEXT,
  kunyomi        TEXT,
  tags           TEXT,
  meanings_json  TEXT NOT NULL CHECK (json_valid(meanings_json)),
  stats_json     TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(stats_json)) -- strokes, grade, JLPT, freq
);
CREATE INDEX ix_dict_kanji_char ON dict_kanji(character);

-- =====================================================================
-- 5. CONTENT LIBRARY
-- =====================================================================

-- Groups: manga series, book series, YouTube channels, podcast shows, sites.
CREATE TABLE collections (
  id             INTEGER PRIMARY KEY,
  language_code  TEXT NOT NULL REFERENCES languages(code),
  kind           TEXT NOT NULL CHECK (kind IN
                 ('manga_series','book_series','youtube_channel','youtube_playlist',
                  'podcast','site','custom')),
  title          TEXT NOT NULL,
  creator        TEXT,
  source_url     TEXT,
  cover_path     TEXT,
  subscribed     INTEGER NOT NULL DEFAULT 0,             -- update-content pulls new items
  metadata_json  TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
  created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- Where `update-content` looks (seeded from config/sources.yaml, editable in UI).
CREATE TABLE content_sources (
  id                INTEGER PRIMARY KEY,
  language_code     TEXT NOT NULL REFERENCES languages(code),
  kind              TEXT NOT NULL CHECK (kind IN
                    ('youtube_channel','youtube_playlist','youtube_search','podcast_feed',
                     'podcast_search','rss','gutenberg','aozora','web_section')),
  name              TEXT NOT NULL,
  target            TEXT NOT NULL,                       -- URL, channel id, feed URL or query template
  topics_json       TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(topics_json)),
  origin            TEXT NOT NULL DEFAULT 'config' CHECK (origin IN ('config','manual','discovered','ci_wiki')),
  level_label       TEXT,                                -- level as the source labels it ('beginner', 'B1', 'Level 3')
  enabled           INTEGER NOT NULL DEFAULT 1,
  fetch_every_hours INTEGER NOT NULL DEFAULT 24,
  last_fetched_at   TEXT,
  last_status       TEXT,
  config_json       TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(config_json)), -- duration limits, etc.
  UNIQUE (kind, target)
);

CREATE TABLE content_items (
  id                INTEGER PRIMARY KEY,
  language_code     TEXT NOT NULL REFERENCES languages(code),
  type              TEXT NOT NULL CHECK (type IN
                    ('youtube','video','audio','podcast_episode','epub','pdf','article',
                     'manga_volume','text')),
  title             TEXT NOT NULL,
  creator           TEXT,                                -- author / channel / publisher
  collection_id     INTEGER REFERENCES collections(id) ON DELETE SET NULL,
  collection_index  REAL,                                -- volume / episode number
  origin            TEXT NOT NULL CHECK (origin IN ('user_added','scraper','csv_import')),
  source            TEXT NOT NULL,                       -- 'youtube','local','rss','gutenberg','aozora','web','mokuro'
  source_id         INTEGER REFERENCES content_sources(id) ON DELETE SET NULL,
  source_url        TEXT,
  external_id       TEXT,                                -- YouTube id, RSS guid, ISBN ...
  local_path        TEXT,                                -- relative to data dir
  cover_path        TEXT,
  duration_sec      INTEGER,
  page_count        INTEGER,
  word_count        INTEGER,
  published_at      TEXT,
  topics_json       TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(topics_json)),
  status            TEXT NOT NULL DEFAULT 'library' CHECK (status IN
                    ('candidate','library','in_progress','finished','abandoned','dismissed','archived')),
  progress          REAL NOT NULL DEFAULT 0,             -- 0..1
  position_ref      TEXT,                                -- resume locator
  rating            INTEGER CHECK (rating BETWEEN 1 AND 5),
  perceived_difficulty INTEGER CHECK (perceived_difficulty BETWEEN 1 AND 5),
  analysis_status   TEXT NOT NULL DEFAULT 'pending' CHECK (analysis_status IN
                    ('pending','queued','done','failed','no_text')),
  metadata_json     TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
  added_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  last_opened_at    TEXT,
  finished_at       TEXT,
  progress_hlc      TEXT,                                -- clock of the last progress/status edit (phone vs laptop)
  UNIQUE (source, external_id)
);
CREATE INDEX ix_content_lang_status ON content_items(language_code, status, type);
CREATE INDEX ix_content_collection  ON content_items(collection_id, collection_index);

CREATE TABLE annotations (
  id               INTEGER PRIMARY KEY,
  content_item_id  INTEGER NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
  kind             TEXT NOT NULL CHECK (kind IN ('bookmark','highlight','note')),
  locator          TEXT NOT NULL,
  text             TEXT,
  note             TEXT,
  color            TEXT,
  client_uuid      TEXT UNIQUE,
  created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX ix_annotations_item ON annotations(content_item_id);

-- =====================================================================
-- 6. TRANSCRIPTS, EXTRACTED TEXT, MANGA
-- =====================================================================

CREATE TABLE transcripts (
  id               INTEGER PRIMARY KEY,
  content_item_id  INTEGER NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
  language_code    TEXT NOT NULL,                        -- target language, or 'en' for a translation track
  kind             TEXT NOT NULL CHECK (kind IN ('manual','auto_caption','whisper','user_file','translation')),
  source_format    TEXT,                                 -- vtt | srt | ass | json3 | whisper
  is_primary       INTEGER NOT NULL DEFAULT 0,
  quality          REAL,                                 -- heuristic / Whisper avg logprob
  created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX ix_transcripts_item ON transcripts(content_item_id);

CREATE TABLE transcript_cues (
  id             INTEGER PRIMARY KEY,
  transcript_id  INTEGER NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
  seq            INTEGER NOT NULL,
  start_ms       INTEGER NOT NULL,
  end_ms         INTEGER NOT NULL,
  text           TEXT NOT NULL,
  words_json     TEXT CHECK (words_json IS NULL OR json_valid(words_json)), -- word timings (Whisper)
  UNIQUE (transcript_id, seq)
);
CREATE INDEX ix_cues_time ON transcript_cues(transcript_id, start_ms);

-- Normalised plain text of ANY content (book sections, PDF pages, article
-- paragraphs, subtitle lines, manga blocks). Feeds analysis + full-text search.
CREATE TABLE content_chunks (
  id               INTEGER PRIMARY KEY,
  content_item_id  INTEGER NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
  seq              INTEGER NOT NULL,
  locator          TEXT NOT NULL,
  text             TEXT NOT NULL,
  UNIQUE (content_item_id, seq)
);

-- Trigram tokenizer works for Japanese (no spaces) as well as de/es.
CREATE VIRTUAL TABLE content_fts USING fts5(
  text, content='content_chunks', content_rowid='id', tokenize='trigram'
);
CREATE TRIGGER content_chunks_ai AFTER INSERT ON content_chunks BEGIN
  INSERT INTO content_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER content_chunks_ad AFTER DELETE ON content_chunks BEGIN
  INSERT INTO content_fts(content_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
CREATE TRIGGER content_chunks_au AFTER UPDATE ON content_chunks BEGIN
  INSERT INTO content_fts(content_fts, rowid, text) VALUES ('delete', old.id, old.text);
  INSERT INTO content_fts(rowid, text) VALUES (new.id, new.text);
END;

-- Manga (mokuro-style OCR output)
CREATE TABLE manga_pages (
  id               INTEGER PRIMARY KEY,
  content_item_id  INTEGER NOT NULL REFERENCES content_items(id) ON DELETE CASCADE, -- the volume
  page_index       INTEGER NOT NULL,
  image_path       TEXT NOT NULL,
  width            INTEGER NOT NULL,
  height           INTEGER NOT NULL,
  ocr_status       TEXT NOT NULL DEFAULT 'pending' CHECK (ocr_status IN ('pending','done','failed','skipped')),
  UNIQUE (content_item_id, page_index)
);

CREATE TABLE manga_text_blocks (
  id              INTEGER PRIMARY KEY,
  page_id         INTEGER NOT NULL REFERENCES manga_pages(id) ON DELETE CASCADE,
  seq             INTEGER NOT NULL,
  x1 REAL NOT NULL, y1 REAL NOT NULL, x2 REAL NOT NULL, y2 REAL NOT NULL, -- page pixel coords
  vertical        INTEGER NOT NULL DEFAULT 1,
  font_size       REAL,
  lines_json      TEXT NOT NULL CHECK (json_valid(lines_json)),           -- [{text, coords}]
  text            TEXT NOT NULL,                                          -- joined lines
  user_corrected  INTEGER NOT NULL DEFAULT 0,
  UNIQUE (page_id, seq)
);

-- =====================================================================
-- 7. CONTENT ANALYSIS & i+1 RANKING
-- =====================================================================

CREATE TABLE content_analysis (
  content_item_id   INTEGER PRIMARY KEY REFERENCES content_items(id) ON DELETE CASCADE,
  text_source       TEXT NOT NULL,                       -- manual_sub | auto_caption | whisper | epub | pdf | ocr | article
  analyzer_version  TEXT NOT NULL,                       -- re-analyse when tokenizer/models change
  token_count       INTEGER NOT NULL,
  unique_lemmas     INTEGER NOT NULL,
  sample_ratio      REAL NOT NULL DEFAULT 1.0,           -- <1 when only a sample was analysed
  speech_wpm        REAL,                                -- audio/video only
  avg_sentence_len  REAL,
  rank_p50          INTEGER,                             -- frequency-rank percentiles of tokens
  rank_p90          INTEGER,
  rank_p95          INTEGER,
  analyzed_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- Lemma histogram per item: coverage for ANY profile state is one SQL join.
CREATE TABLE content_lemmas (
  content_item_id  INTEGER NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
  lexeme_id        INTEGER NOT NULL REFERENCES lexemes(id) ON DELETE CASCADE,
  count            INTEGER NOT NULL,
  first_locator    TEXT,
  PRIMARY KEY (content_item_id, lexeme_id)
) WITHOUT ROWID;
CREATE INDEX ix_content_lemmas_lexeme ON content_lemmas(lexeme_id);

-- Materialised ranking, recomputed when the profile version changes.
CREATE TABLE content_scores (
  content_item_id   INTEGER PRIMARY KEY REFERENCES content_items(id) ON DELETE CASCADE,
  profile_version   INTEGER NOT NULL,
  coverage          REAL NOT NULL,                       -- expected known-token ratio
  expected_unknown  REAL NOT NULL,                       -- Σ(1-p) over unique lemmas
  unknown_density   REAL,                                -- per minute (AV) or per 1000 tokens (text)
  learnability      REAL,                                -- share of unknowns that are frequent & repeated
  interest_match    REAL,
  i1_score          REAL NOT NULL,                       -- final rank score 0..1
  band              TEXT NOT NULL CHECK (band IN ('too_easy','comfortable','i_plus_1','stretch','too_hard')),
  computed_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  estimated         INTEGER NOT NULL DEFAULT 0           -- 1 = estimated from the channel/source, not yet measured (0003)
);
CREATE INDEX ix_scores_rank ON content_scores(band, i1_score DESC);
CREATE INDEX ix_scores_estimated ON content_scores(estimated);

-- =====================================================================
-- 8. IMMERSION TRACKING & CSV IMPORT
-- =====================================================================

CREATE TABLE import_batches (
  id               INTEGER PRIMARY KEY,
  filename         TEXT NOT NULL,
  file_sha256      TEXT NOT NULL,
  stored_path      TEXT NOT NULL,                        -- data/imports/<sha>.csv (original kept)
  column_map_json  TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(column_map_json)),
  default_language TEXT REFERENCES languages(code),
  row_count        INTEGER NOT NULL DEFAULT 0,
  imported_count   INTEGER NOT NULL DEFAULT 0,
  skipped_count    INTEGER NOT NULL DEFAULT 0,
  status           TEXT NOT NULL DEFAULT 'preview' CHECK (status IN ('preview','imported','failed','reverted')),
  errors_json      TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(errors_json)),
  created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX ix_import_batches_sha ON import_batches(file_sha256);

CREATE TABLE activity_sessions (
  id                 INTEGER PRIMARY KEY,
  language_code      TEXT NOT NULL REFERENCES languages(code),
  activity           TEXT NOT NULL CHECK (activity IN
                     ('video','podcast','audio','reading','article','manga','tutor','shadowing',
                      'conversation','class','writing','other')),
  modality           TEXT NOT NULL CHECK (modality IN ('listening','reading','speaking','writing','mixed')),
  tracking           TEXT NOT NULL CHECK (tracking IN ('auto','manual','import')),
  content_item_id    INTEGER REFERENCES content_items(id) ON DELETE SET NULL,
  title              TEXT,                               -- free text for manual/imported rows
  started_at         TEXT NOT NULL,
  ended_at           TEXT,
  last_heartbeat_at  TEXT,                               -- auto sessions only
  active_seconds     INTEGER NOT NULL DEFAULT 0,
  is_open            INTEGER NOT NULL DEFAULT 0,
  is_baseline        INTEGER NOT NULL DEFAULT 0,         -- 1 = pre-tracking hours carried over (kept out of daily charts)
  difficulty_self    INTEGER CHECK (difficulty_self BETWEEN 1 AND 5),
  tokens_exposed     INTEGER,
  lookups            INTEGER NOT NULL DEFAULT 0,
  words_saved        INTEGER NOT NULL DEFAULT 0,
  notes              TEXT,
  import_batch_id    INTEGER REFERENCES import_batches(id) ON DELETE CASCADE,
  external_ref       TEXT,                               -- row hash → idempotent re-imports
  client_uuid        TEXT UNIQUE,                        -- ULID when created on the phone (sync idempotency)
  created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX ix_activity_lang_time ON activity_sessions(language_code, started_at);
CREATE INDEX ix_activity_open      ON activity_sessions(is_open) WHERE is_open = 1;
CREATE UNIQUE INDEX ux_activity_external ON activity_sessions(tracking, external_ref)
  WHERE external_ref IS NOT NULL;

CREATE TABLE import_rows (
  id                   INTEGER PRIMARY KEY,
  batch_id             INTEGER NOT NULL REFERENCES import_batches(id) ON DELETE CASCADE,
  row_index            INTEGER NOT NULL,
  raw_json             TEXT NOT NULL CHECK (json_valid(raw_json)),  -- untouched source row
  status               TEXT NOT NULL CHECK (status IN ('imported','skipped','error','duplicate')),
  activity_session_id  INTEGER REFERENCES activity_sessions(id) ON DELETE SET NULL,
  message              TEXT,
  UNIQUE (batch_id, row_index)
);

-- =====================================================================
-- 9. AI TUTOR & GRAMMAR
-- =====================================================================

-- Weekly coaching brief written by `evolve-profile` (or by hand). The live
-- profile is injected separately at session start; this is the slow-moving part.
CREATE TABLE tutor_instructions (
  id                  INTEGER PRIMARY KEY,
  language_code       TEXT NOT NULL REFERENCES languages(code),
  version             INTEGER NOT NULL,
  origin              TEXT NOT NULL CHECK (origin IN ('default','evolve','manual')),
  instructions_md     TEXT NOT NULL,
  focus_words_json    TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(focus_words_json)),   -- lexeme ids
  focus_grammar_json  TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(focus_grammar_json)), -- grammar keys
  style_json          TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(style_json)),
                      -- {"speech_rate":0.9,"max_sentence_words":14,"register":"du","correction":"recast"}
  is_active           INTEGER NOT NULL DEFAULT 0,
  report_id           INTEGER REFERENCES progress_reports(id) ON DELETE SET NULL,
  created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE (language_code, version)
);
CREATE UNIQUE INDEX ux_tutor_instr_active ON tutor_instructions(language_code) WHERE is_active = 1;

CREATE TABLE tutor_sessions (
  id                   INTEGER PRIMARY KEY,
  language_code        TEXT NOT NULL REFERENCES languages(code),
  mode                 TEXT NOT NULL CHECK (mode IN
                       ('conversation','roleplay','content_discussion','correction_drill','free_write')),
  scenario             TEXT,
  content_item_id      INTEGER REFERENCES content_items(id) ON DELETE SET NULL, -- "talk about this video"
  instructions_id      INTEGER REFERENCES tutor_instructions(id) ON DELETE SET NULL,
  system_prompt        TEXT NOT NULL,                    -- exact rendered prompt (reproducible)
  llm_model            TEXT,                             -- 'provider/model' as routed
  stt_model            TEXT,
  tts_voice            TEXT,
  activity_session_id  INTEGER REFERENCES activity_sessions(id) ON DELETE SET NULL,
  summary_md           TEXT,
  postprocessed        INTEGER NOT NULL DEFAULT 0,       -- corrections/grammar extraction done
  client_uuid          TEXT UNIQUE,
  started_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  ended_at             TEXT
);
CREATE INDEX ix_tutor_sessions_time ON tutor_sessions(language_code, started_at);

CREATE TABLE tutor_messages (
  id                INTEGER PRIMARY KEY,
  session_id        INTEGER NOT NULL REFERENCES tutor_sessions(id) ON DELETE CASCADE,
  seq               INTEGER NOT NULL,
  role              TEXT NOT NULL CHECK (role IN ('user','assistant','system')),
  input_mode        TEXT CHECK (input_mode IN ('voice','text')),
  text              TEXT NOT NULL,
  audio_path        TEXT,
  stt_confidence    REAL,
  coverage          REAL,                                -- assistant turns: known-word ratio (vocab governor)
  corrections_json  TEXT CHECK (corrections_json IS NULL OR json_valid(corrections_json)),
                    -- [{original, corrected, grammar_key, explanation}]
  words_used_json   TEXT CHECK (words_used_json IS NULL OR json_valid(words_used_json)),
  latency_ms        INTEGER,
  client_uuid       TEXT UNIQUE,
  tokens_in         INTEGER,
  tokens_out        INTEGER,
  created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE (session_id, seq)
);

-- Catalog seeded per language (A1–C1 / N5–N1 lists), extended by the LLM.
CREATE TABLE grammar_points (
  id              INTEGER PRIMARY KEY,
  language_code   TEXT NOT NULL REFERENCES languages(code),
  key             TEXT NOT NULL UNIQUE,                  -- 'de.adj_endings.dative', 'ja.conditional.ba'
  title           TEXT NOT NULL,
  level           TEXT,                                  -- 'B1' | 'N3'
  category        TEXT,                                  -- 'case','mood','particles'...
  description_md  TEXT,
  examples_json   TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(examples_json)),
  origin          TEXT NOT NULL DEFAULT 'seed' CHECK (origin IN ('seed','llm','manual'))
);

CREATE TABLE user_grammar (
  grammar_point_id  INTEGER PRIMARY KEY REFERENCES grammar_points(id) ON DELETE CASCADE,
  status            TEXT NOT NULL DEFAULT 'unseen' CHECK (status IN
                    ('unseen','introduced','practicing','solid','weak')),
  mastery           REAL NOT NULL DEFAULT 0.5,           -- 0..1, decayed error/success ratio
  errors            INTEGER NOT NULL DEFAULT 0,
  successes         INTEGER NOT NULL DEFAULT 0,
  last_error_at     TEXT,
  last_success_at   TEXT,
  updated_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE grammar_evidence (
  id                INTEGER PRIMARY KEY,
  grammar_point_id  INTEGER NOT NULL REFERENCES grammar_points(id) ON DELETE CASCADE,
  outcome           TEXT NOT NULL CHECK (outcome IN ('error','success','lookup','explained')),
  source            TEXT NOT NULL CHECK (source IN ('tutor','reader','player','manga','shadowing','manual')),
  tutor_message_id  INTEGER REFERENCES tutor_messages(id) ON DELETE SET NULL,
  content_item_id   INTEGER REFERENCES content_items(id) ON DELETE SET NULL,
  original_text     TEXT,
  corrected_text    TEXT,
  note              TEXT,
  created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX ix_grammar_evidence_point ON grammar_evidence(grammar_point_id, created_at);

-- =====================================================================
-- 10. SHADOWING STUDIO
-- =====================================================================

CREATE TABLE shadow_clips (
  id                INTEGER PRIMARY KEY,
  language_code     TEXT NOT NULL REFERENCES languages(code),
  content_item_id   INTEGER REFERENCES content_items(id) ON DELETE SET NULL,
  cue_id            INTEGER REFERENCES transcript_cues(id) ON DELETE SET NULL,
  start_ms          INTEGER NOT NULL,
  end_ms            INTEGER NOT NULL,
  text              TEXT NOT NULL,
  reference_kind    TEXT NOT NULL DEFAULT 'media' CHECK (reference_kind IN ('media','tts')),
  audio_path        TEXT,                                -- extracted reference clip (ffmpeg)
  analysis_json     TEXT CHECK (analysis_json IS NULL OR json_valid(analysis_json)), -- pitch contour, energy
  favorite          INTEGER NOT NULL DEFAULT 0,
  practice_count    INTEGER NOT NULL DEFAULT 0,
  created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE shadow_attempts (
  id                INTEGER PRIMARY KEY,
  clip_id           INTEGER NOT NULL REFERENCES shadow_clips(id) ON DELETE CASCADE,
  recording_path    TEXT NOT NULL,
  duration_ms       INTEGER NOT NULL,
  stt_text          TEXT,                                -- what the recogniser heard
  text_similarity   REAL,                                -- 0..1 vs reference text
  timing_offset_ms  INTEGER,
  pitch_similarity  REAL,                                -- DTW on pitch contours
  analysis_json     TEXT CHECK (analysis_json IS NULL OR json_valid(analysis_json)),
  self_rating       INTEGER CHECK (self_rating BETWEEN 1 AND 5),
  client_uuid       TEXT UNIQUE,
  created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX ix_shadow_attempts_clip ON shadow_attempts(clip_id, created_at);

-- =====================================================================
-- 11. AUTOMATION: SCRAPE RUNS, JOB QUEUE, AI CACHE & USAGE
-- =====================================================================

CREATE TABLE scrape_runs (
  id                INTEGER PRIMARY KEY,
  language_code     TEXT REFERENCES languages(code),     -- NULL = all languages
  status            TEXT NOT NULL CHECK (status IN ('running','done','failed','partial')),
  candidates_found  INTEGER NOT NULL DEFAULT 0,
  candidates_added  INTEGER NOT NULL DEFAULT 0,
  stats_json        TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(stats_json)),
  log_path          TEXT,
  started_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  finished_at       TEXT
);

-- In-process background worker (no Redis/Celery). Two lanes: 'cpu' and 'gpu'
-- (Whisper, manga OCR and a local LLM never share the 6 GB of VRAM at once).
CREATE TABLE jobs (
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
CREATE INDEX ix_jobs_queue ON jobs(status, lane, priority, created_at);

-- Cache for deterministic-ish AI calls (contextual glosses, translations, TTS).
CREATE TABLE ai_cache (
  key_hash       TEXT PRIMARY KEY,                       -- sha256(task|model|prompt_version|input)
  task           TEXT NOT NULL,
  model          TEXT NOT NULL,
  response_json  TEXT NOT NULL CHECK (json_valid(response_json)),
  hits           INTEGER NOT NULL DEFAULT 0,
  created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- Every model call, whatever the provider: cost/latency visibility.
CREATE TABLE ai_calls (
  id              INTEGER PRIMARY KEY,
  task            TEXT NOT NULL,                         -- 'lookup.context_gloss', 'tutor.chat', ...
  kind            TEXT NOT NULL CHECK (kind IN ('llm','stt','tts')),
  provider        TEXT NOT NULL,
  model           TEXT NOT NULL,
  ok              INTEGER NOT NULL,
  latency_ms      INTEGER,
  units_in        INTEGER,                               -- tokens in / audio seconds / characters
  units_out       INTEGER,
  cost_estimate   REAL,
  error           TEXT,
  created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX ix_ai_calls_time ON ai_calls(created_at);

-- =====================================================================
-- 12. VIEWS
-- =====================================================================

CREATE VIEW v_daily_immersion AS
SELECT language_code,
       date(started_at, 'localtime') AS day,
       activity, modality, tracking,
       SUM(active_seconds) AS seconds,
       COUNT(*)            AS sessions
FROM activity_sessions
GROUP BY language_code, day, activity, modality, tracking;

CREATE VIEW v_vocab_summary AS
SELECT l.language_code, uw.status, COUNT(*) AS words
FROM user_words uw
JOIN lexemes l ON l.id = uw.lexeme_id
GROUP BY l.language_code, uw.status;

CREATE VIEW v_library_ranked AS
SELECT ci.id, ci.language_code, ci.type, ci.title, ci.creator, ci.status,
       ci.duration_sec, ci.word_count,
       cs.coverage, cs.expected_unknown, cs.unknown_density, cs.i1_score, cs.band
FROM content_items ci
JOIN content_scores cs ON cs.content_item_id = ci.id
WHERE ci.status IN ('candidate','library','in_progress');

-- =====================================================================
-- 13. MULTI-DEVICE SYNC  (laptop = hub, Android APK = client; ARCHITECTURE §6.13)
--     Rows the phone can create carry client_uuid; rows both devices can
--     edit carry a hybrid logical clock (updated_hlc / progress_hlc).
-- =====================================================================

CREATE TABLE devices (
  id               TEXT PRIMARY KEY,                     -- ULID generated on the device
  name             TEXT NOT NULL,                        -- 'Laptop', 'Phone'
  kind             TEXT NOT NULL CHECK (kind IN ('hub','android')),
  token_hash       TEXT,                                 -- hash of the pairing token (never the token)
  last_seen_at     TEXT,
  last_pulled_seq  INTEGER NOT NULL DEFAULT 0,           -- highest sync_log.seq this device has received
  paired_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  revoked_at       TEXT
);

-- Every change other devices must see, in hub order. The phone's outbox is
-- applied here once per event_id; devices pull "everything after seq N".
CREATE TABLE sync_log (
  seq            INTEGER PRIMARY KEY,                    -- hub-assigned, monotonic
  event_id       TEXT NOT NULL UNIQUE,                   -- ULID from the originating device
  device_id      TEXT NOT NULL REFERENCES devices(id),
  hlc            TEXT NOT NULL,                          -- hybrid logical clock (conflict order)
  entity         TEXT NOT NULL,                          -- 'user_words', 'activity_sessions', 'content_progress', ...
  entity_key     TEXT NOT NULL,                          -- client_uuid, or a natural key such as 'de|anrufen|'
  op             TEXT NOT NULL CHECK (op IN ('insert','update','delete')),
  payload_json   TEXT NOT NULL CHECK (json_valid(payload_json)),
  applied_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX ix_sync_entity ON sync_log(entity, entity_key, hlc);

-- Content prepared for offline use on a device: pre-tokenised text, a
-- dictionary subset, audio / local video, manga pages + OCR boxes.
CREATE TABLE offline_packs (
  device_id        TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
  content_item_id  INTEGER NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
  status           TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','building','ready','stale','removed')),
  bytes            INTEGER,
  auto             INTEGER NOT NULL DEFAULT 0,           -- 1 = packed automatically from Up Next
  built_at         TEXT,
  PRIMARY KEY (device_id, content_item_id)
);
