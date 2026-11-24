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
  summary: { words: number; running_words?: number; known_share: number | null; new_words: number; profile_measured: boolean };
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

// ---------------------------------------------------------------- Phase 2: library, player, listening

export interface ContentItem {
  id: number;
  language: string;
  type: string;
  title: string;
  creator: string | null;
  source: string;
  url: string | null;
  external_id: string | null;
  local_path: string | null;
  duration_sec: number | null;
  status: string;
  progress: number;
  position_ref: string | null;
  analysis_status: string;
  last_opened_at: string | null;
  metadata: Record<string, unknown>;
  times_watched: number;
  last_watched_at: string | null;
  transcript_kind: string | null;
  coverage: number | null;
  expected_unknown: number | null;
  band: string | null;
  speech_wpm: number | null;
  word_count: number | null;
  page_count: number | null;
  difficulty: number | null;
  estimated: number;
}

export interface TranscriptCue {
  id: number;
  seq: number;
  start_ms: number;
  end_ms: number;
  text: string;
  tokens: AnnotatedToken[];
}

export interface TranscriptData {
  item: ContentItem;
  cues: TranscriptCue[];
  summary: Annotation["summary"] | null;
}

export interface Job {
  id: number;
  kind: string;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  progress: number;
  result: Record<string, unknown> | null;
  error: string | null;
}

export interface Evidence {
  videos_watched: number;
  videos_analysed: number;
  content_words_heard: number;
  lemmas_heard: number;
  lemmas_heard_10_plus: number;
  lemmas_heard_3_to_9: number;
  vocabulary_for_90_percent: number | null;
  coverage_target: number;
  job: Job | null;
}

export interface DictationItem {
  id: number;
  seq: number;
  level: string;
  speak: string;
  total: number;
  max_plays: number;
}

export interface DictationResult {
  band: string;
  band_low: string;
  band_high: string;
  averages: Record<string, number>;
  overall: number;
  sentences: number;
}

export interface DictationStep {
  done: boolean;
  assessment_id?: number;
  item?: DictationItem;
  feedback?: { sentence: string; accuracy: number; level: string };
  result?: DictationResult;
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

// ---------------------------------------------------------------- Phase 3: reading, Up Next

export interface UpNextPick {
  id: number;
  type: string;
  kind: "video" | "reading" | "manga";
  title: string;
  creator: string | null;
  source: string;
  external_id: string | null;
  duration_sec: number | null;
  word_count: number | null;
  status: string;
  progress: number | null;
  coverage: number | null;
  i1_score: number | null;
  band: string | null;
  expected_unknown: number | null;
  learning_words: number;
  watched: number;
  score: number;
  reasons: string[];
  estimated?: boolean;
  level_basis?: string | null;
  url?: string | null;
  origin?: string;
  image?: string | null;
  site?: string | null;
}

/** One page of a shelf's suggestions (infinite scroll). */
export interface FeedPage {
  language: string;
  shelf: "watch" | "read";
  total: number;
  items: UpNextPick[];
  next_offset: number | null;
  estimated?: number;
}

/** How many suggestions each shelf has, and the background search that keeps them topped up. */
export interface PoolStatus {
  language: string;
  auto: boolean;
  pools: { watch: number; read: number };
  estimated?: number;
  targets: { watch: number; read: number };
  low: ("watch" | "read")[];
  searching: boolean;
  job: Job | null;
  last_search_at: string | null;
  youtube_refused: boolean;
  next_auto_at: string | null;
  queued?: boolean;
  reason?: string;
}

export interface TutorTopic {
  id: number;
  title: string;
  type: string;
  creator: string | null;
  kind: "video" | "reading";
  last_at: string | null;
}

export interface UpNext {
  language: string;
  available: number;
  picks: UpNextPick[];
}

export interface ReaderParagraph {
  seq: number;
  locator: string;
  text: string;
  tokens: AnnotatedToken[];
}

export interface ReaderPage {
  item: ContentItem;
  page: number;
  pages: number;
  title: string | null;
  paragraphs: ReaderParagraph[];
  summary: Annotation["summary"] | null;
}

export interface AddedDocument extends ContentItem {
  analysing_in_background: boolean;
}

// ---------------------------------------------------------------- Phase 4: AI explanations

export type AiTaskStatus =
  | { enabled: true; provider: string; kind: string; model: string; local_only: boolean }
  | { enabled: false; reason: string; local_only: boolean };

export interface AiStatus {
  context: AiTaskStatus;
  grammar: AiTaskStatus;
}

export interface AiMeta {
  provider: string;
  model: string;
  cached: boolean;
}

export interface ContextGloss extends AiMeta {
  meaning: string;
  sense: number;
  note: string;
  translation: string;
  fitting_sense: string | null;
}

export interface GrammarBreakdown extends AiMeta {
  translation: string;
  literal: string;
  parts: { text: string; gloss: string; role: string }[];
  points: { name: string; explanation: string; level: string }[];
}

export interface AiUsage {
  days: number;
  calls: number;
  cost: number | null;
  cache_hits: number;
  tasks: { task: string; calls: number; ok: number; tokens_in: number; tokens_out: number; cost: number | null; avg_ms: number }[];
}

// ---------------------------------------------------------------- Phase 5: manga

export interface MangaBlock {
  id: number;
  seq: number;
  box: [number, number, number, number];
  vertical: boolean;
  font_size: number | null;
  lines: { text: string; start: number }[];
  text: string;
  corrected: boolean;
  tokens: AnnotatedToken[];
}

export interface MangaPageData {
  item: ContentItem;
  page: number;
  pages: number;
  width: number;
  height: number;
  ocr: "pending" | "done" | "failed" | "skipped";
  blocks: MangaBlock[];
  summary: Annotation["summary"] | null;
}

export interface MangaScanResult {
  folder: string;
  imported: number;
  results: { title: string; status: string; item_id?: number; pages?: number }[];
}

export interface MangaVocabWord {
  lemma: string;
  reading: string;
  display: string;
  pos: string;
  status: TokenStatus;
  rank: number | null;
  count: number;
  first_page: number;
  pages: number;
  example: string;
}

// ---------------------------------------------------------------- Phases 6–7: tutor, shadowing

export type TutorMode = "conversation" | "roleplay" | "content_discussion" | "correction_drill";

export interface TutorScenario {
  id: string;
  title: string;
  setting: string;
  you: string;
  learner: string;
}

export interface TutorOptions {
  status: AiTaskStatus;
  scenarios: TutorScenario[];
  weak_grammar: string[];
  focus_words: string[];
  speech_rate: number;
}

export interface TutorCorrection {
  turn: number;
  original: string;
  corrected: string;
  explanation: string;
  grammar: string;
}

export interface TutorMessage {
  id: number;
  seq: number;
  role: "user" | "assistant";
  input_mode: "voice" | "text" | null;
  text: string;
  coverage: number | null;
  corrections: TutorCorrection[] | null;
  tokens?: AnnotatedToken[];
  created_at: string;
}

export interface TutorSession {
  id: number;
  language_code: string;
  mode: TutorMode;
  scenario: string | null;
  content_item_id: number | null;
  summary_md: string | null;
  postprocessed: number;
  started_at: string;
  ended_at: string | null;
  messages: TutorMessage[];
  speech_rate?: number;
}

export interface TutorSessionRow {
  id: number;
  mode: TutorMode;
  scenario: string | null;
  started_at: string;
  ended_at: string | null;
  postprocessed: number;
  summary_md: string | null;
  turns: number;
  title: string | null;
}

export interface GrammarRow {
  key: string;
  title: string;
  level: string | null;
  status: string;
  errors: number;
  successes: number;
  mastery: number;
  last_error_at: string | null;
  example: string | null;
}

export interface ShadowAttempt {
  id: number;
  duration_ms: number;
  heard: string | null;
  similarity: number | null;
  diff: { text: string; ok: boolean }[];
  self_rating: number | null;
  created_at: string;
}

export interface ShadowClip {
  id: number;
  language: string;
  content_item_id: number | null;
  cue_id: number | null;
  start_ms: number;
  end_ms: number;
  text: string;
  reference_kind: "media" | "tts";
  favorite: boolean;
  practice_count: number;
  created_at: string;
  item_title: string | null;
  item_source: string | null;
  external_id: string | null;
  item_type: string | null;
  best: number | null;
  last_practised: string | null;
  attempts?: ShadowAttempt[];
}

// ---------------------------------------------------------------- Phase 8: discovery, weekly review

export interface ReportRow {
  path: string;
  start: string;
  end: string;
  created_at: string;
  languages: string[];
  minutes: number;
}

export interface ScrapeRun {
  id: number;
  language: string;
  status: string;
  listed: number;
  added: number;
  started_at: string;
  finished_at: string | null;
  errors: string[];
  added_titles: string[];
  stopped_early: boolean;
}

export interface ContentSource {
  id: number;
  kind: string;
  name: string;
  target: string;
  origin: string;
  level_label: string | null;
  enabled: boolean;
  last_fetched_at: string | null;
  last_status: string | null;
  config: { section?: string; note?: string; flags?: string[]; site?: string; youtube?: string | null };
}

// ---------------------------------------------------------------- Phase 9: phone sync

export interface DeviceRow {
  id: string;
  name: string;
  kind: "hub" | "android";
  last_seen_at: string | null;
  paired_at: string;
  revoked_at: string | null;
  events: number;
  packs: number;
}

export interface SyncStatus {
  enabled: boolean;
  running: boolean;
  error: string | null;
  port: number;
  addresses: string[];
  devices: DeviceRow[];
}

// ---------------------------------------------------------------- grammar reference

export type GrammarKind = "structure" | "verbs" | "contrast" | "summary";

export interface GrammarTable {
  caption?: string;
  head: string[];
  rows: string[][];
}

export interface GrammarExample {
  text: string;
  translation: string;
  note: string | null;
  reading: string | null;
}

export interface GrammarSection {
  number: number;
  id: string;
  title: string;
  kind: GrammarKind;
  level: string;
  tags: string[];
  rule: string | null;
  text: string | null;
  tables: GrammarTable[];
  after: string | null;
  examples: GrammarExample[];
  points: string[];
  tip: string | null;
}

export interface GrammarWeakSpot {
  key: string;
  title: string;
  errors: number;
  mastery: number;
  example: string | null;
  sections: string[];
}

export interface GrammarReference {
  language: string;
  title: string;
  intro: string;
  sections: GrammarSection[];
  weak_spots: GrammarWeakSpot[];
}

// ---------------------------------------------------------------- ratings and taste

export interface DifficultyResult {
  id: number;
  value: number | null;
  label: string | null;
  modality: "listening" | "reading";
  ideal_before: number;
  ideal_after: number;
  ratings: number;
  message: string;
}

export interface TasteSummary {
  language: string;
  signals: number;
  channels: { name: string; affinity: number; evidence: number }[];
  less_of: { name: string; affinity: number }[];
  lengths: { bucket: string; affinity: number }[];
  topics: string[];
  calibration: Record<"listening" | "reading", { ideal: number; default: number; ratings: number; counts: Record<string, number> }>;
}
