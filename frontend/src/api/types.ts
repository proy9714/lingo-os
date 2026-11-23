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
