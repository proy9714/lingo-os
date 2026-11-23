// Mirrors the FastAPI responses (backend/app/api). Generated types replace this in a later phase.

export interface Language {
  code: string;
  name: string;
  native_name: string;
  accent_color: string;
  writing_mode: string;
  enabled: boolean;
}

export interface Settings {
  active_language: string;
  goals: Record<string, number>;
  tracker_path: string | null;
}

export interface DayMinutes {
  date: string;
  minutes: number;
}

export interface TodayStats {
  language: string;
  date: string;
  today_minutes: number;
  goal_minutes: number;
  last7: DayMinutes[];
  last_session: { date: string; title: string | null; minutes: number; day_minutes: number } | null;
}

export interface HoursEstimate {
  basis: string;
  confidence: string;
  divisor: number;
  adjusted_hours: number;
  level: number;
  level_label: string;
  max_level: number;
  next_level: number | null;
  next_level_adjusted_hours: number | null;
  hours_to_next_level: number;
  progress_to_next: number;
  words_prior: number;
}

export interface LanguageOverview {
  language: string;
  total_hours: number;
  baseline_hours: number;
  tracked_hours: number;
  sessions: number;
  content_items: number;
  active_days: number;
  first_session_date: string | null;
  last_session_date: string | null;
  monthly: { month: string; hours: number }[];
  by_modality_hours: Record<string, number>;
  estimate: HoursEstimate;
}

export interface Overview {
  languages: LanguageOverview[];
}

export interface RecentSession {
  id: number;
  activity: string;
  modality: string;
  tracking: "auto" | "manual" | "import";
  title: string | null;
  started_at: string;
  minutes: number;
}

export interface ManualLogInput {
  language: string;
  activity: string;
  minutes: number;
  day?: string;
  title?: string;
  notes?: string;
}

export interface TrackerFlag {
  entry_id: string;
  language: string;
  date: string;
  title: string;
  minutes?: number;
  reason: string;
}

export interface TrackerFileResult {
  language: string;
  file: string;
  status: "imported" | "unchanged" | "missing";
  rows: number;
  imported: number;
  already_present: number;
  duplicates: TrackerFlag[];
  errors: string[];
}

export interface TrackerImportSummary {
  folder: string;
  files: TrackerFileResult[];
  goals_imported: Record<string, number> | null;
}

// ---------------------------------------------------------------- Phase 1: words, lookups, Level Lab

export type TokenStatus = "none" | "new" | "likely" | "learning" | "familiar" | "known" | "ignored";
export type WordStatus = "seen" | "learning" | "familiar" | "known" | "ignored";

export interface AnnotatedToken {
  start: number;
  end: number;
  word: boolean;
  lemma: string;
  display: string;
  reading: string;
  pos: string;
  learnable: boolean;
  forms: string[];
  rank: number | null;
  status: TokenStatus;
  p: number | null;
}

export interface Annotation {
  language: string;
  tokens: AnnotatedToken[];
  sentences: { start: number; end: number }[];
  summary: { words: number; known_share: number | null; new_words: number; profile_measured: boolean };
}

export interface WordState {
  lexeme_id: number;
  language: string;
  lemma: string;
  reading: string;
  pos: string;
  rank: number | null;
  status: WordStatus | null;
  p_known: number | null;
  saved: boolean;
  lookups: number | null;
  user_gloss: string | null;
  user_note: string | null;
  first_seen_at: string | null;
  last_seen_at: string | null;
  contexts: number;
}

export interface WordContext {
  id: number;
  surface: string;
  sentence: string;
  locator: string | null;
  created_at: string;
}

export interface DictEntry {
  dictionary: string;
  term: string;
  reading: string;
  pos: string[];
  glosses: string[];
  note: string | null;
  via_inflection: boolean;
}

export interface LookupResult {
  lemma: string;
  reading: string;
  pos: string;
  rank: number | null;
  model_p: number;
  state: WordState | null;
  contexts: WordContext[];
  entries: DictEntry[];
  inflections: { form: string; lemma: string; rules: string[] }[];
  missing_dictionary?: boolean;
}

export interface WordListItem {
  lexeme_id: number;
  lemma: string;
  reading: string;
  pos: string;
  rank: number | null;
  status: WordStatus;
  p_known: number;
  saved: boolean;
  lookups: number;
  user_gloss: string | null;
  last_seen_at: string | null;
  contexts: number;
  latest_sentence: string | null;
}

export interface WordDetail extends WordState {
  contexts_list: WordContext[];
}

export interface Profile {
  language: string;
  version: number;
  r50: number;
  k: number;
  vocab_size: number;
  level: string | null;
  level_alt: string | null;
  confidence: number;
  measured: boolean;
  updated_at: string;
}

export interface VocabResult {
  vocabulary: number;
  low: number;
  high: number;
  band: string | null;
  band_low: string | null;
  band_high: string | null;
  jlpt: string | null;
  jlpt_low: string | null;
  jlpt_high: string | null;
  words_answered: number;
  pseudo_shown: number;
  pseudo_claimed: number;
  false_alarm_rate: number;
}

export interface CTestScores {
  scores: Record<string, number>;
  band: string;
  band_low: string;
  band_high: string;
  overall: number;
}

export interface SkillEstimate {
  band?: string | null;
  band_low?: string | null;
  band_high?: string | null;
  last_tested_at?: string | null;
  result?: Partial<VocabResult & CTestScores>;
}

export interface LevelOverview {
  language: string;
  profile: Profile | null;
  hours_estimate: HoursEstimate;
  skills: Record<string, SkillEstimate>;
  history: { id: number; skill: string; method: string; result: Record<string, unknown>; finished_at: string }[];
  ctest_available: boolean;
}

export interface VocabItem {
  id: number;
  seq: number;
  word: string;
  step: "yesno" | "meaning";
  answered: number;
  typical_length: number;
  options?: string[];
}

export type VocabStep =
  | { done: false; item: VocabItem; assessment_id?: number }
  | { done: true; result?: VocabResult; abandoned?: boolean; reason?: string };

export interface CTestSegment {
  text?: string;
  gap?: number;
  shown?: string;
  size?: number;
}

export interface CTestStart {
  assessment_id: number;
  passages: { level: string; segments: CTestSegment[] }[];
}

export interface CTestResult {
  result: CTestScores;
  review: { id: number; expected: string; given: string; score: number }[];
}

export interface SystemCheck {
  name: string;
  ok: boolean;
  detail: string;
  required: boolean;
}

export interface SystemStatus {
  version: string;
  ok: boolean;
  device_id: string;
  data_dir: string;
  checks: SystemCheck[];
}
