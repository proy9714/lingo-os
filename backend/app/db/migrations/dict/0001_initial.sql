-- Generated from docs/schema.sql by splitting out the dictionary section.
-- Keep both in sync: tests/test_migrations.py fails if they drift apart.

PRAGMA foreign_keys = ON;

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

